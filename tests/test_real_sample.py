import re
import pytest

REAL_SAMPLE = """
########################################################################
                         IP质量体检报告: 203.218.*.*
                     https://github.com/xykt/IPQuality
                    bash <(curl -sL https://Check.Place) -I
        报告时间: 2026-09-09 08:30:16 CST  脚本版本: v2026-09-04
########################################################################
一、基础信息（Maxmind 数据库）
自治系统号:         AS4760
组织:               HKT Limited
坐标:               114° 9' 57" E, 22° 15' 28" N
地图:               https://check.place/22.2578, 114.1657, 15, cn
城市:               N/A
使用地:             [HK] 香港, [AS] 亚洲
注册地:             [HK] 香港
时区:               Asia/Hong_Kong
IP类型:             原生IP
二、IP类型属性
数据库:    IPinfo    ipregistry      ipapi     IP2Location    AbuseIPDB
使用类型:   家宽        家宽          家宽         家宽          家宽
公司类型:   家宽        家宽          家宽         家宽
三、风险评分
风险等级:       极低          低          中等          高          极高
IP2Location:  0 低风险
Scamalytics:  0 低风险
ipapi:        0.17% 低风险
AbuseIPDB:    0 低风险
四、风险因子
库:  IP2Location ipapi ipregistry IPQS Scamalytics ipdata IPinfo DB-IP
地区:     [HK]      [HK]     [CN]     无     [HK]     [HK]     [HK]     无
代理:      否        否       否      无      否       否       否      无
Tor:       否        否       否      无      否       否       否      无
VPN:       否        否       否      无      否       无       否      无
服务器:    否        否       否      无      否       否       否      无
滥用:      否        否       无      无      否       无       无      无
机器人:    否        否       无      无      否       无       无      无
五、流媒体及AI服务解锁检测
服务商:     TikTok    Disney+    Netflix   Youtube   AmazonPV   Reddit    ChatGPT
状态:        解锁       解锁       解锁      解锁      解锁      解锁     仅APP
地区:      [ALISG]      [HK]       [HK]      [HK]      [HK]      [HK]      [HK]
方式:        原生       原生       原生      原生      原生      原生      原生
六、邮局连通性及黑名单检测
本地25端口出站: 阻断
通信: 远端25端口不可达
IP地址黑名单数据库:  有效 423   正常 416   已标记 6   黑名单 1
========================================================================
"""

from ipquality_runner import IPQualityRunner


def test_parse_real():
    from ipquality_runner import IPQualityRunner
    runner = IPQualityRunner()
    d = runner._parse_output(REAL_SAMPLE, fallback_ip="203.218.34.193")
    assert d["asn"] == "AS4760"
    assert d["org"] == "HKT Limited"
    assert "[HK]" in d["location"]
    assert "原生" in d["ip_type"]
    assert "5/5" in d["residential_details"]
    assert d["scamalytics_score"] == "0"
    assert d["abuseipdb_score"] == "0"
    assert "解锁 [HK] (原生)" in d["netflix"]
    assert "解锁 [HK] (原生)" in d["disney"]
    assert "解锁 [HK] (原生)" in d["youtube"]
    assert "仅APP [HK] (原生)" in d["chatgpt"]
    assert "解锁 [ALISG] (原生)" in d["tiktok"]
    assert d["port25"] == "阻断"
    assert "416 正常 / 1 黑名单" in d["blacklist_info"]

    card = runner._format_telegram_card(d)
    assert "203.218" in card
    assert "AS4760" in card
    assert "HKT Limited" in card
    assert "香港" in card
    assert "🟢" in card
    assert "Netflix" in card
    assert "ChatGPT" in card


def test_parse_chinese_colons_and_pipes():
    """测试带有中文全角冒号及终端仪表盘管道符（如 |低风险）的样本解析"""
    sample = """
一、基础信息（Maxmind 数据库）
自治系统号：         AS4760
组织：               HKT Limited
使用地：             [HK] 香港, [AS] 亚洲
IP类型：             原生IP
二、IP类型属性
使用类型:   家宽        家宽          家宽         家宽          家宽
三、风险评分
IP2Location：  0|低风险
Scamalytics：  0|低风险
ipapi：        0.17%|低风险
AbuseIPDB：    0|低风险
五、流媒体及AI服务解锁检测
服务商： TikTok   Disney+  Netflix Youtube  AmazonPV  Reddit   ChatGPT
状态：    解锁     解锁     解锁    解锁    解锁      解锁     仅APP
地区：  [ALISG]    [HK]     [HK]    [HK]    [HK]      [HK]     [HK]
方式：    原生     原生     原生    原生    原生      原生     原生
六、邮局连通性及黑名单检测
本地25端口出站：阻断
通信：远端25端口不可达
IP地址黑名单数据库：  有效 423   正常 416   已标记 6   黑名单 1
"""
    runner = IPQualityRunner()
    d = runner._parse_output(sample, fallback_ip="203.218.34.193")
    assert d["scamalytics_score"] == "0"
    assert d["scamalytics_level"] == "低风险"
    assert d["abuseipdb_score"] == "0"
    assert d["abuseipdb_level"] == "低风险"
    assert "解锁 [HK] (原生)" in d["netflix"]
    assert "仅APP [HK] (原生)" in d["chatgpt"]
    assert "解锁 [ALISG] (原生)" in d["tiktok"]

    card = runner._format_telegram_card(d)
    # 确保没有出现 (|低风险) 这种未清理的管道符
    assert "(|低风险)" not in card
    assert "0 (低风险)" in card
    # 确保流媒体不再是未解析的整行
    assert "Youtube  AmazonPV" not in card
    assert "• Netflix: 🟢 解锁 [HK] (原生)" in card
    assert "• ChatGPT: 🟡 仅APP [HK] (原生)" in card


def test_json_overlay():
    """测试脚本生成的结构化 JSON 补全机制"""
    json_data = {
        "Head": {"IP": "203.218.34.193"},
        "Info": {"Type": "原生IP"},
        "Type": {"Usage": {"IPinfo": "家宽", "ipregistry": "家宽", "ipapi": "家宽", "AbuseIPDB": "家宽", "IP2LOCATION": "家宽"}},
        "Score": {"SCAMALYTICS": "0", "AbuseIPDB": "0", "IP2LOCATION": "0", "ipapi": "0.17%"},
        "Media": {
            "Netflix": {"Status": "解锁", "Region": "HK", "Type": "原生"},
            "ChatGPT": {"Status": "仅APP", "Region": "HK", "Type": "原生"},
            "TikTok": {"Status": "解锁", "Region": "ALISG", "Type": "原生"},
        },
        "Mail": {"Port25": False, "DNSBlacklist": {"Clean": 416, "Blacklisted": 1}}
    }
    runner = IPQualityRunner()
    d = runner._parse_output("", fallback_ip="1.1.1.1", json_dict=json_data)
    assert d["ip"] == "203.218.34.193"
    assert d["scamalytics_score"] == "0"
    assert "5/5 数据库判定家宽" in d["residential_details"]
    assert "解锁 [HK] (原生)" in d["netflix"]
    assert "仅APP [HK] (原生)" in d["chatgpt"]
    assert d["port25"] == "阻断"
