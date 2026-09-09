"""
xykt/IPQuality 脚本执行与解析模块
负责在后台异步执行 IP 质量检测、清理 ANSI 转义码、结构化解析数据并生成精美的 Telegram 报告卡片
"""

import asyncio
import json
import logging
import os
import platform
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from config import settings
from storage import storage

logger = logging.getLogger(__name__)

# 用于剔除终端 ANSI 颜色与控制字符的正则
ANSI_REGEX = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def clean_ansi(text: str) -> str:
    """去除终端输出中的 ANSI 颜色代码、特殊光标控制符及回车覆盖进度字符"""
    if not text:
        return ""
    cleaned = ANSI_REGEX.sub("", text)
    result_lines = []
    for raw_line in cleaned.split("\n"):
        # 如果一行中含有回车符 \r，说明存在终端覆盖输出，取覆盖后的最后一个有效片段
        if "\r" in raw_line:
            segments = [s.strip() for s in raw_line.split("\r") if s.strip()]
            raw_line = segments[-1] if segments else ""
        line = raw_line.strip()
        # 剔除可能遗留的终端进度点或转轮百分比 (如 ............... ⠴ 51%)
        line = re.sub(r"[\.·]{3,}\s*[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]?\s*\d*%", "", line).strip()
        if line:
            result_lines.append(line)
    return "\n".join(result_lines)


class IPQualityRunner:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.is_running: bool = False
        self.last_run_time: Optional[float] = None

    async def run_check(self, current_ip: Optional[str] = None) -> Tuple[bool, str, Dict[str, Any]]:
        """
        执行 IP 质量体检
        返回: (是否成功, Telegram 格式化卡片文本, 结构化数据字典)
        """
        if self._lock.locked():
            return False, "⚠️ 当前已有 IPQuality 检测任务正在运行中，请等待上一任务完成后再试！", {}

        async with self._lock:
            self.is_running = True
            start_time = time.time()
            logger.info("开始执行 xykt/IPQuality 检测任务...")

            try:
                # 判断当前系统环境
                is_windows = platform.system().lower() == "windows"

                if is_windows:
                    # Windows 环境下（本地开发/测试），提供逼真的 Mock 测试数据
                    raw_output = await self._run_mock_windows(current_ip)
                    json_data = None
                else:
                    # Linux VPS 环境下执行真实脚本
                    raw_output, json_data = await self._run_linux_script()

                elapsed_seconds = int(time.time() - start_time)
                clean_text = clean_ansi(raw_output)

                # 解析结构化信息 (结合文本解析与 JSON 结构化数据互补)
                parsed_data = self._parse_output(clean_text, current_ip, json_dict=json_data)
                parsed_data["duration_seconds"] = elapsed_seconds
                parsed_data["test_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 生成 Telegram HTML 卡片
                card_text = self._format_telegram_card(parsed_data)

                # 留存最新记录至存储
                record = {
                    "timestamp": parsed_data["test_time"],
                    "ip": parsed_data.get("ip", current_ip or "未知"),
                    "duration_seconds": elapsed_seconds,
                    "status": "success",
                    "summary": parsed_data,
                    "formatted_card": card_text,
                    "raw_text": clean_text[:4000],  # 保留清洗后的纯文本
                }
                storage.save_latest_record(record)

                # 记录简要历史
                storage.add_history_entry({
                    "type": "quality_test",
                    "ip": parsed_data.get("ip", current_ip or "未知"),
                    "scamalytics_score": parsed_data.get("scamalytics_score", "N/A"),
                    "ip_type": parsed_data.get("ip_type", "未知"),
                    "netflix": parsed_data.get("netflix", "未知"),
                    "chatgpt": parsed_data.get("chatgpt", "未知"),
                    "duration_seconds": elapsed_seconds,
                    "status": "success",
                })

                self.last_run_time = time.time()
                logger.info(f"IPQuality 检测完成，耗时: {elapsed_seconds} 秒")
                return True, card_text, record

            except asyncio.TimeoutError:
                logger.error(f"IPQuality 脚本执行超时 (超过 {settings.ipquality_test_timeout} 秒)")
                err_msg = f"❌ 检测超时：脚本执行超过了最大时限 ({settings.ipquality_test_timeout} 秒)。"
                return False, err_msg, {}
            except Exception as e:
                logger.error(f"IPQuality 脚本执行异常: {e}", exc_info=True)
                err_msg = f"❌ 脚本执行遇到异常: {str(e)}"
                return False, err_msg, {}
            finally:
                self.is_running = False

    async def _run_linux_script(self) -> Tuple[str, Optional[Dict[str, Any]]]:
        """在 Linux VPS 上执行 xykt/IPQuality 脚本并读取结构化 JSON 输出"""
        # 使用 -4 仅测试 IPv4，-f 展示完整 IP，-y 自动安装依赖，-p 隐私模式不上传公共链接，-o 导出完整 JSON
        json_tmp_path = "/tmp/ipquality_result.json"
        cmd = f"bash -c 'rm -f {json_tmp_path} && curl -sL {settings.ipquality_script_url} | bash -s -- -4 -f -y -p -o {json_tmp_path}'"
        logger.info(f"执行命令: {cmd}")

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        stdout, _ = await asyncio.wait_for(
            proc.communicate(),
            timeout=float(settings.ipquality_test_timeout)
        )

        output = stdout.decode("utf-8", errors="replace")

        json_data = None
        if os.path.exists(json_tmp_path):
            try:
                with open(json_tmp_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        json_data = json.loads(content)
                        logger.info(f"成功读取 {json_tmp_path} 结构化 JSON 数据")
            except Exception as e:
                logger.warning(f"读取 {json_tmp_path} 异常: {e}")

        return output, json_data

    async def _run_mock_windows(self, current_ip: Optional[str]) -> str:
        """Windows 开发调试模拟测试输出"""
        logger.info("当前运行于 Windows，使用 Mock 模拟 IPQuality 脚本输出")
        await asyncio.sleep(1)
        ip = current_ip or "203.218.34.193"
        return f"""
########################################################################
                         IP质量体检报告: {ip}
                     https://github.com/xykt/IPQuality
                    bash <(curl -sL https://Check.Place) -I
        报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S CST')}  脚本版本: v2026-09-04
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

    def _parse_output(
        self,
        text: str,
        fallback_ip: Optional[str] = None,
        json_dict: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """按大章节划分精准解析 xykt/IPQuality 各项指标，并支持结合 JSON 结构化数据补全"""
        data: Dict[str, Any] = {
            "ip": fallback_ip or "未知",
            "asn": "未知",
            "org": "未知",
            "location": "未知",
            "city": "",
            "ip_type": "未知",
            "residential_details": "",
            "scamalytics_score": "未知",
            "scamalytics_level": "",
            "abuseipdb_score": "未知",
            "abuseipdb_level": "",
            "ip2location_score": "未知",
            "ip2location_level": "",
            "ipapi_score": "未知",
            "ipapi_level": "",
            "media_unlock": {},
            "netflix": "未知",
            "disney": "未知",
            "youtube": "未知",
            "chatgpt": "未知",
            "tiktok": "未知",
            "amazon": "未知",
            "reddit": "未知",
            "port25": "未知",
            "port25_detail": "",
            "blacklist_info": "未知",
        }

        # 1. 尝试从标题或头部提取公网 IP
        m_ip = re.search(r"(?:IP\s*(?:质量体检报告|地址|address)?|IPv4)[:：]\s*([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})", text, re.I)
        if m_ip:
            data["ip"] = m_ip.group(1)

        # 2. 划分章节
        sec_map: Dict[str, list] = {}
        cur_sec = "0"
        sec_map[cur_sec] = []

        for line in text.splitlines():
            l = line.strip()
            if not l:
                continue
            if any(k in l for k in ["一、基础信息", "1. 基础信息", "1. Basic Information"]):
                cur_sec = "1"
            elif any(k in l for k in ["二、IP类型属性", "2. IP类型", "2. IP Type"]):
                cur_sec = "2"
            elif any(k in l for k in ["三、风险评分", "3. 风险评分", "2. 欺诈与风控评分", "3. Risk Scores"]):
                cur_sec = "3"
            elif any(k in l for k in ["四、风险因子", "4. 风险因子", "4. Risk Factors"]):
                cur_sec = "4"
            elif any(k in l for k in ["五、流媒体", "3. 流媒体", "5. 流媒体", "5. Media Unlock", "5. Accessibility"]):
                cur_sec = "5"
            elif any(k in l for k in ["六、邮局", "4. 邮件", "6. 邮局", "6. Mail"]):
                cur_sec = "6"
            sec_map.setdefault(cur_sec, []).append(l)

        # 3. 解析第一章节：基础信息
        sec1 = sec_map.get("1", [])
        for l in sec1:
            m = re.search(r"(?:自治系统号|ASN)[:：\s]+([A-Za-z0-9]+(?:\s+[^\n]+)?)", l)
            if m and data["asn"] == "未知":
                data["asn"] = m.group(1).strip()

            m = re.search(r"(?:组织|Organization|ISP)[:：\s]+([^\n]+)", l)
            if m and data["org"] == "未知":
                data["org"] = m.group(1).strip()

            m = re.search(r"(?:城市|City)[:：\s]+([^\n]+)", l)
            if m and m.group(1).strip() not in ["N/A", "未知", "None"]:
                data["city"] = m.group(1).strip()

            m = re.search(r"(?:使用地|注册地|Location|位置)[:：\s]+([^\n]+)", l)
            if m and data["location"] == "未知":
                data["location"] = m.group(1).strip()

            m = re.search(r"(?:IP\s*类型|IP\s*Type)[:：\s]+([^\n]+)", l)
            if m and data["ip_type"] == "未知":
                data["ip_type"] = m.group(1).strip()

        # 4. 解析第二章节：IP类型属性（统计有多少家宽判定）
        sec2 = sec_map.get("2", [])
        for l in sec2:
            if "使用类型" in l:
                home_hits = len(re.findall(r"(?:家宽|住宅|Residential|ISP)", l))
                if home_hits > 0:
                    data["residential_details"] = f"{home_hits}/5 数据库判定家宽"
                    if "原生" in data["ip_type"]:
                        data["ip_type"] = f"{data['ip_type']} (住宅家宽)"
                    elif data["ip_type"] == "未知":
                        data["ip_type"] = "住宅家宽 (Residential)"

        # 5. 解析第三章节：风险评分
        sec3 = sec_map.get("3", [])
        for l in sec3:
            m = re.search(r"Scamalytics.*?[：:\s]\s*([0-9.]+)\s*([^\n]*)", l, re.I)
            if m:
                data["scamalytics_score"] = m.group(1).strip()
                data["scamalytics_level"] = re.sub(r"^[|\s]+", "", m.group(2)).strip()

            m = re.search(r"AbuseIPDB.*?[：:\s]\s*([0-9.]+%?)\s*([^\n]*)", l, re.I)
            if m:
                data["abuseipdb_score"] = m.group(1).strip()
                data["abuseipdb_level"] = re.sub(r"^[|\s]+", "", m.group(2)).strip()

            m = re.search(r"IP2Location.*?[：:\s]\s*([0-9.]+|[\u4e00-\u9fa5A-Za-z]+)\s*([^\n]*)", l, re.I)
            if m:
                data["ip2location_score"] = m.group(1).strip()
                data["ip2location_level"] = re.sub(r"^[|\s]+", "", m.group(2)).strip()

            m = re.search(r"ipapi.*?[：:\s]\s*([0-9.]+%?)\s*([^\n]*)", l, re.I)
            if m:
                data["ipapi_score"] = m.group(1).strip()
                data["ipapi_level"] = re.sub(r"^[|\s]+", "", m.group(2)).strip()

        # 风险评分全文本兜底扫描
        if data["scamalytics_score"] == "未知":
            for l in text.splitlines():
                m = re.search(r"Scamalytics.*?[：:\s]\s*([0-9.]+)\s*([^\n]*)", l, re.I)
                if m:
                    data["scamalytics_score"] = m.group(1).strip()
                    data["scamalytics_level"] = re.sub(r"^[|\s]+", "", m.group(2)).strip()
                    break
        if data["abuseipdb_score"] == "未知":
            for l in text.splitlines():
                m = re.search(r"AbuseIPDB.*?[：:\s]\s*([0-9.]+%?)\s*([^\n]*)", l, re.I)
                if m:
                    data["abuseipdb_score"] = m.group(1).strip()
                    data["abuseipdb_level"] = re.sub(r"^[|\s]+", "", m.group(2)).strip()
                    break

        # 6. 解析第五章节：流媒体及AI服务解锁
        sec5 = sec_map.get("5", [])
        services, statuses, regions, methods = [], [], [], []
        for l in sec5:
            if re.search(r"(?:服务商|Service)[:：]", l):
                services = re.split(r"(?:服务商|Service)[:：]\s*", l, maxsplit=1)[1].strip().split()
            elif re.search(r"(?:状态|Status)[:：]", l):
                statuses = re.split(r"(?:状态|Status)[:：]\s*", l, maxsplit=1)[1].strip().split()
            elif re.search(r"(?:地区|Region)[:：]", l):
                regions = re.split(r"(?:地区|Region)[:：]\s*", l, maxsplit=1)[1].strip().split()
            elif re.search(r"(?:方式|Type)[:：]", l):
                methods = re.split(r"(?:方式|Type)[:：]\s*", l, maxsplit=1)[1].strip().split()

        # 若在第 5 章节未提取到服务商（可能章节未对齐或脚本格式调整），扫描全部文本行
        if not services:
            for l in text.splitlines():
                if re.search(r"(?:服务商|Service)[:：]", l) and not services:
                    services = re.split(r"(?:服务商|Service)[:：]\s*", l, maxsplit=1)[1].strip().split()
                elif re.search(r"(?:状态|Status)[:：]", l) and not statuses:
                    statuses = re.split(r"(?:状态|Status)[:：]\s*", l, maxsplit=1)[1].strip().split()
                elif re.search(r"(?:地区|Region)[:：]", l) and not regions:
                    regions = re.split(r"(?:地区|Region)[:：]\s*", l, maxsplit=1)[1].strip().split()
                elif re.search(r"(?:方式|Type)[:：]", l) and not methods:
                    methods = re.split(r"(?:方式|Type)[:：]\s*", l, maxsplit=1)[1].strip().split()

        if services:
            for i, svc_name in enumerate(services):
                st = statuses[i] if i < len(statuses) else ""
                rg = regions[i] if i < len(regions) else ""
                mt = methods[i] if i < len(methods) else ""
                display_str = f"{st} {rg} ({mt})".strip().replace("()", "").strip()
                data["media_unlock"][svc_name.lower()] = display_str

                k = svc_name.lower()
                if "netflix" in k:
                    data["netflix"] = display_str
                elif "disney" in k:
                    data["disney"] = display_str
                elif "youtube" in k:
                    data["youtube"] = display_str
                elif "chatgpt" in k or "openai" in k:
                    data["chatgpt"] = display_str
                elif "tiktok" in k:
                    data["tiktok"] = display_str
                elif "amazon" in k:
                    data["amazon"] = display_str
                elif "reddit" in k:
                    data["reddit"] = display_str
        else:
            # 兼容单行键值对格式 (如 Netflix: 解锁，要求必须有冒号，避免把表头当成值)
            for line_s in text.splitlines():
                if re.search(r"Netflix.*?[:：]", line_s, re.I):
                    m = re.search(r"Netflix.*?[:：]\s*([^\n]+)", line_s, re.I)
                    if m: data["netflix"] = m.group(1).strip()
                if re.search(r"Disney\+?.*?[:：]", line_s, re.I):
                    m = re.search(r"Disney\+?.*?[:：]\s*([^\n]+)", line_s, re.I)
                    if m: data["disney"] = m.group(1).strip()
                if re.search(r"YouTube.*?[:：]", line_s, re.I):
                    m = re.search(r"YouTube.*?[:：]\s*([^\n]+)", line_s, re.I)
                    if m: data["youtube"] = m.group(1).strip()
                if re.search(r"(?:ChatGPT|OpenAI).*?[:：]", line_s, re.I):
                    m = re.search(r"(?:ChatGPT|OpenAI).*?[:：]\s*([^\n]+)", line_s, re.I)
                    if m: data["chatgpt"] = m.group(1).strip()
                if re.search(r"TikTok.*?[:：]", line_s, re.I):
                    m = re.search(r"TikTok.*?[:：]\s*([^\n]+)", line_s, re.I)
                    if m: data["tiktok"] = m.group(1).strip()

        # 7. 解析第六章节：邮局与黑名单
        sec6 = sec_map.get("6", [])
        for l in sec6:
            m = re.search(r"(?:本地25端口出站|25\s*端口.*?)[:：\s]+([^\n]+)", l)
            if m:
                data["port25"] = m.group(1).strip()
            m = re.search(r"通信[:：\s]+([^\n]+)", l)
            if m:
                data["port25_detail"] = m.group(1).strip()
            m = re.search(r"IP地址黑名单数据库.*?正常\s*(\d+).*?黑名单\s*(\d+)", l)
            if m:
                data["blacklist_info"] = f"{m.group(1)} 正常 / {m.group(2)} 黑名单"

        # 邮局 25 端口全文本兜底
        if data["port25"] == "未知":
            for line_s in text.splitlines():
                m = re.search(r"(?:本地25端口出站|25\s*端口.*?)[:：\s]+([^\n]+)", line_s)
                if m:
                    data["port25"] = m.group(1).strip()
                    break

        # 8. 若存在原生导出的 JSON 数据，进行高精度覆盖与补全
        if json_dict and isinstance(json_dict, dict):
            head = json_dict.get("Head", {})
            if head.get("IP") and str(head["IP"]) not in ["null", "None", ""]:
                data["ip"] = str(head["IP"])

            info = json_dict.get("Info", {})
            if info.get("Type") and str(info["Type"]) not in ["null", "None", ""]:
                data["ip_type"] = str(info["Type"])

            type_sec = json_dict.get("Type", {})
            usage = type_sec.get("Usage", {})
            if isinstance(usage, dict):
                home_hits = sum(1 for v in usage.values() if any(k in str(v) for k in ["家宽", "住宅", "Residential"]))
                if home_hits > 0:
                    data["residential_details"] = f"{home_hits}/{len(usage)} 数据库判定家宽"
                    if "原生" in data["ip_type"] and "家宽" not in data["ip_type"]:
                        data["ip_type"] = f"{data['ip_type']} (住宅家宽)"
                    elif data["ip_type"] == "未知":
                        data["ip_type"] = "住宅家宽 (Residential)"

            score_sec = json_dict.get("Score", {})
            if score_sec.get("SCAMALYTICS") and str(score_sec["SCAMALYTICS"]) != "null":
                data["scamalytics_score"] = str(score_sec["SCAMALYTICS"])
                data["scamalytics_level"] = "低风险" if data["scamalytics_score"] == "0" else ""
            if score_sec.get("AbuseIPDB") and str(score_sec["AbuseIPDB"]) != "null":
                data["abuseipdb_score"] = str(score_sec["AbuseIPDB"])
                data["abuseipdb_level"] = "低风险" if data["abuseipdb_score"] in ["0", "0%"] else ""
            if score_sec.get("IP2LOCATION") and str(score_sec["IP2LOCATION"]) != "null":
                data["ip2location_score"] = str(score_sec["IP2LOCATION"])
                data["ip2location_level"] = "低风险" if data["ip2location_score"] == "0" else ""
            if score_sec.get("ipapi") and str(score_sec["ipapi"]) != "null":
                data["ipapi_score"] = str(score_sec["ipapi"])
                data["ipapi_level"] = "低风险"

            media_sec = json_dict.get("Media", {})
            if isinstance(media_sec, dict):
                def parse_media_item(item_data):
                    if not isinstance(item_data, dict):
                        return ""
                    st = str(item_data.get("Status", "")).replace("null", "").strip()
                    rg = str(item_data.get("Region", "")).replace("null", "").strip()
                    tp = str(item_data.get("Type", "")).replace("null", "").strip()
                    if not st:
                        return ""
                    res = st
                    if rg:
                        res += f" [{rg}]"
                    if tp:
                        res += f" ({tp})"
                    return res

                item_map = {
                    "netflix": parse_media_item(media_sec.get("Netflix", {})),
                    "disney": parse_media_item(media_sec.get("DisneyPlus", {})),
                    "youtube": parse_media_item(media_sec.get("Youtube", {})),
                    "chatgpt": parse_media_item(media_sec.get("ChatGPT", {})),
                    "tiktok": parse_media_item(media_sec.get("TikTok", {})),
                    "amazon": parse_media_item(media_sec.get("AmazonPrimeVideo", {})),
                    "reddit": parse_media_item(media_sec.get("Reddit", {})),
                }
                for k, v in item_map.items():
                    if v:
                        data[k] = v

            mail_sec = json_dict.get("Mail", {})
            if isinstance(mail_sec, dict):
                p25 = mail_sec.get("Port25")
                if p25 is True:
                    data["port25"] = "可用"
                elif p25 is False:
                    data["port25"] = "阻断"
                dnsbl = mail_sec.get("DNSBlacklist", {})
                if isinstance(dnsbl, dict):
                    clean_c = dnsbl.get("Clean", 0)
                    black_c = dnsbl.get("Blacklisted", 0)
                    if clean_c or black_c:
                        data["blacklist_info"] = f"{clean_c} 正常 / {black_c} 黑名单"

        return data

    def _format_telegram_card(self, d: Dict[str, Any]) -> str:
        """将解析后的指标转化为符合 Telegram HTML 标准的精美排版卡片"""
        ip = d.get("ip", "未知")
        test_time = d.get("test_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        duration = d.get("duration_seconds", 0)

        # 状态指示符
        def media_status_icon(text: str) -> str:
            t = str(text).lower()
            if any(k in t for k in ["解锁", "支持", "open", "开放", "yes"]):
                return "🟢"
            if any(k in t for k in ["仅app", "app", "自制", "only", "仅"]):
                return "🟡"
            if any(k in t for k in ["阻断", "不可达", "未解锁", "block", "fail", "no", "closed", "屏蔽"]):
                return "🔴"
            return "⚪"

        def risk_status_icon(score: str, level: str = "") -> str:
            s = str(score).lower().replace("%", "")
            lvl = str(level).lower()
            try:
                val = float(s)
                if val == 0 or any(k in lvl for k in ["极低", "低", "clean", "low"]):
                    return "🟢"
                if val <= 25 or "中" in lvl:
                    return "🟡"
                return "🔴"
            except ValueError:
                if any(k in lvl for k in ["极低", "低", "clean", "low"]):
                    return "🟢"
                if "中" in lvl:
                    return "🟡"
                if "高" in lvl:
                    return "🔴"
                return "🟢"

        # 地理位置排版增强
        raw_loc = d.get("location", "未知")
        loc_display = raw_loc
        if "[HK]" in raw_loc or "香港" in raw_loc:
            loc_display = "🇭🇰 香港 (Hong Kong)"
        elif "[TW]" in raw_loc or "台湾" in raw_loc:
            loc_display = "🇹🇼 台湾 (Taiwan)"
        elif "[JP]" in raw_loc or "日本" in raw_loc:
            loc_display = "🇯🇵 日本 (Japan)"
        elif "[US]" in raw_loc or "美国" in raw_loc:
            loc_display = "🇺🇸 美国 (United States)"
        elif "[SG]" in raw_loc or "新加坡" in raw_loc:
            loc_display = "🇸🇬 新加坡 (Singapore)"

        # 风险评分排版 (去除多余管道符与仪表盘残余)
        scam_s = d.get("scamalytics_score", "0")
        scam_l = re.sub(r"^[|\s]+", "", d.get("scamalytics_level", "")).strip(" |[]()")
        if not scam_l or scam_l == "未知":
            scam_l = "低风险" if scam_s == "0" else ""
        scam_display = f"{scam_s} ({scam_l})" if scam_l else scam_s

        abuse_s = d.get("abuseipdb_score", "0")
        abuse_l = re.sub(r"^[|\s]+", "", d.get("abuseipdb_level", "")).strip(" |[]()")
        if not abuse_l or abuse_l == "未知":
            abuse_l = "低风险" if abuse_s in ["0", "0%"] else ""
        abuse_display = f"{abuse_s} ({abuse_l})" if abuse_l else abuse_s

        ip2loc_s = d.get("ip2location_score", "0")
        ip2loc_l = re.sub(r"^[|\s]+", "", d.get("ip2location_level", "")).strip(" |[]()")
        if not ip2loc_l or ip2loc_l == "未知":
            ip2loc_l = "低风险" if ip2loc_s == "0" else ""
        ip2loc_display = f"{ip2loc_s} ({ip2loc_l})" if ip2loc_l else ip2loc_s

        ipapi_s = d.get("ipapi_score", "0%")
        ipapi_l = re.sub(r"^[|\s]+", "", d.get("ipapi_level", "")).strip(" |[]()")
        if not ipapi_l or ipapi_l == "未知":
            ipapi_l = "低风险"
        ipapi_display = f"{ipapi_s} ({ipapi_l})" if ipapi_l else ipapi_s

        # 家宽属性补充
        ip_type = d.get("ip_type", "未知")
        res_detail = d.get("residential_details", "")
        type_line = f"• <b>IP 类型:</b> 🏠 <b>{ip_type}</b>"
        if res_detail:
            type_line += f"\n• <b>家宽判定:</b> 🛡️ {res_detail}"

        # 流媒体列表构建
        media_items = [
            ("Netflix", d.get("netflix", "未知")),
            ("Disney+", d.get("disney", "未知")),
            ("YouTube", d.get("youtube", "未知")),
            ("ChatGPT", d.get("chatgpt", "未知")),
            ("TikTok", d.get("tiktok", "未知")),
            ("AmazonPV", d.get("amazon", "未知")),
            ("Reddit", d.get("reddit", "未知")),
        ]
        media_lines = []
        for name, val in media_items:
            if val != "未知":
                icon = media_status_icon(val)
                media_lines.append(f"• {name}: {icon} {val}")
            else:
                media_lines.append(f"• {name}: ⚪ 未知")

        media_text = "\n".join(media_lines)

        # 端口与黑名单
        port25 = d.get("port25", "未知")
        port25_icon = media_status_icon(port25)
        port25_line = f"• 25 端口出站: {port25_icon} {port25}"
        if d.get("port25_detail"):
            port25_line += f" ({d.get('port25_detail')})"

        blacklist_info = d.get("blacklist_info", "")
        blacklist_line = f"\n• 黑名单检测: {blacklist_info}" if blacklist_info != "未知" else ""

        card = (
            f"📊 <b>IPv4 质量与解锁体检报告</b>\n"
            f"🕒 <b>检测时间:</b> <code>{test_time}</code> (耗时 {duration}s)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 <b>网络基础信息:</b>\n"
            f"• <b>公网 IPv4:</b> <code>{ip}</code>\n"
            f"• <b>归属地区:</b> {loc_display}\n"
            f"• <b>运营商/ASN:</b> {d.get('asn', '')} {d.get('org', '')}\n"
            f"{type_line}\n\n"
            f"🛡️ <b>风控与欺诈评分:</b>\n"
            f"• Scamalytics: {risk_status_icon(scam_s, scam_l)} <b>{scam_display}</b>\n"
            f"• AbuseIPDB: {risk_status_icon(abuse_s, abuse_l)} <b>{abuse_display}</b>\n"
            f"• IP2Location: {risk_status_icon(ip2loc_s, ip2loc_l)} {ip2loc_display}\n"
            f"• ipapi: {risk_status_icon(ipapi_s, ipapi_l)} {ipapi_display}\n\n"
            f"🎬 <b>流媒体与 AI 解锁:</b>\n"
            f"{media_text}\n\n"
            f"✉️ <b>服务端口与黑名单:</b>\n"
            f"{port25_line}{blacklist_line}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>数据源自 xykt/IPQuality 开源体检脚本</i>"
        )
        return card


# 全局单例执行器实例
ipquality_runner = IPQualityRunner()
