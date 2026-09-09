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
    """去除终端输出中的 ANSI 颜色代码和特殊光标控制符"""
    if not text:
        return ""
    cleaned = ANSI_REGEX.sub("", text)
    # 去除回车符及多余空行
    lines = [line.strip() for line in cleaned.splitlines()]
    return "\n".join([line for line in lines if line])


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
                else:
                    # Linux VPS 环境下执行真实脚本
                    raw_output = await self._run_linux_script()

                elapsed_seconds = int(time.time() - start_time)
                clean_text = clean_ansi(raw_output)

                # 解析结构化信息
                parsed_data = self._parse_output(clean_text, current_ip)
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

    async def _run_linux_script(self) -> str:
        """在 Linux VPS 上执行 xykt/IPQuality 脚本"""
        # 使用 -4 仅测试 IPv4，-f 展示完整 IP，-y 自动安装依赖，-p 隐私模式不上传公共链接
        cmd = f"bash -c 'curl -sL {settings.ipquality_script_url} | bash -s -- -4 -f -y -p'"
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
        return output

    async def _run_mock_windows(self, current_ip: Optional[str]) -> str:
        """Windows 开发调试模拟测试输出"""
        logger.info("当前运行于 Windows，使用 Mock 模拟 IPQuality 脚本输出")
        await asyncio.sleep(2)  # 模拟执行延迟
        ip = current_ip or "203.0.113.88"
        return f"""
------------------------ IP质量体检报告 ------------------------
测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
脚本版本: v2026-09-04
1. 基础信息 (Maxmind 数据库)
IP 地址: {ip}
ASN: AS2914 (NTT Communications)
组织: NTT America, Inc.
位置: Japan Tokyo (JP)
IP 类型: 原生家宽 / ISP (Residential)
2. 欺诈与风控评分
Scamalytics 欺诈分: 0 (极低风险 / Very Low Risk)
AbuseIPDB 滥用率: 0% (Clean)
IP2Location 风险: 低 (Clean)
IPQS 欺诈评分: 0
3. 流媒体与 AI 解锁检测
Netflix: 完整解锁 (日本区 / JP)
Disney+: 完整解锁
YouTube Premium: 支持
ChatGPT (OpenAI): 网页端正常解锁
TikTok: 原生解锁
Amazon Prime Video: 支持
4. 邮件端口与服务检测
25 端口出站: 开放 (Open)
----------------------------------------------------------------
"""

    def _parse_output(self, text: str, fallback_ip: Optional[str] = None) -> Dict[str, Any]:
        """从纯文本输出中通过多组模式正则解析各项指标"""
        data: Dict[str, Any] = {
            "ip": fallback_ip or "未知",
            "asn": "未知",
            "org": "未知",
            "location": "未知",
            "ip_type": "未知",
            "scamalytics_score": "未知",
            "scamalytics_level": "未知",
            "abuseipdb_score": "未知",
            "ip2location": "未知",
            "ipqs_score": "未知",
            "netflix": "未知",
            "disney": "未知",
            "youtube": "未知",
            "chatgpt": "未知",
            "tiktok": "未知",
            "port25": "未知",
        }

        for line in text.splitlines():
            line_s = line.strip()

            # IP 地址
            m = re.search(r"(?:IP\s*(?:地址|address)?|IPv4)[:：]\s*([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})", line_s, re.I)
            if m:
                data["ip"] = m.group(1)

            # ASN
            m = re.search(r"(?:ASN)[:：]\s*(AS\d+[^\n]*)", line_s, re.I)
            if m:
                data["asn"] = m.group(1).strip()

            # 组织 / ISP
            m = re.search(r"(?:组织|Organization|ISP)[:：]\s*([^\n]+)", line_s, re.I)
            if m:
                data["org"] = m.group(1).strip()

            # 位置 / Location
            m = re.search(r"(?:位置|Location|地区)[:：]\s*([^\n]+)", line_s, re.I)
            if m:
                data["location"] = m.group(1).strip()

            # IP 类型
            m = re.search(r"(?:IP\s*类型|IP\s*Type)[:：]\s*([^\n]+)", line_s, re.I)
            if m:
                data["ip_type"] = m.group(1).strip()
            elif "原生" in line_s or "Residential" in line_s or "家宽" in line_s:
                if data["ip_type"] == "未知":
                    data["ip_type"] = "原生家宽 (Residential)"

            # Scamalytics 欺诈分
            m = re.search(r"Scamalytics.*?(\d+)\s*(?:\((.*?)\))?", line_s, re.I)
            if m:
                data["scamalytics_score"] = m.group(1)
                if m.group(2):
                    data["scamalytics_level"] = m.group(2).strip()

            # AbuseIPDB
            m = re.search(r"AbuseIPDB.*?(\d+%)", line_s, re.I)
            if m:
                data["abuseipdb_score"] = m.group(1)

            # IP2Location
            m = re.search(r"IP2Location[:：\s]+([^\n]+)", line_s, re.I)
            if m:
                data["ip2location"] = m.group(1).strip()

            # IPQS
            m = re.search(r"IPQS.*?(\d+)", line_s, re.I)
            if m:
                data["ipqs_score"] = m.group(1)

            # 流媒体 Netflix
            if "netflix" in line_s.lower():
                m = re.search(r"Netflix[:：\s]+([^\n]+)", line_s, re.I)
                if m:
                    data["netflix"] = m.group(1).strip()

            # Disney+
            if "disney" in line_s.lower():
                m = re.search(r"Disney\+?[:：\s]+([^\n]+)", line_s, re.I)
                if m:
                    data["disney"] = m.group(1).strip()

            # YouTube
            if "youtube" in line_s.lower():
                m = re.search(r"YouTube.*?[:：\s]+([^\n]+)", line_s, re.I)
                if m:
                    data["youtube"] = m.group(1).strip()

            # ChatGPT
            if "chatgpt" in line_s.lower() or "openai" in line_s.lower():
                m = re.search(r"(?:ChatGPT|OpenAI)[:：\s]+([^\n]+)", line_s, re.I)
                if m:
                    data["chatgpt"] = m.group(1).strip()

            # TikTok
            if "tiktok" in line_s.lower():
                m = re.search(r"TikTok[:：\s]+([^\n]+)", line_s, re.I)
                if m:
                    data["tiktok"] = m.group(1).strip()

            # 25 端口
            if "25" in line_s and ("端口" in line_s or "port" in line_s.lower()):
                m = re.search(r"(?:25\s*端口.*?|Port\s*25.*?)[:：\s]+([^\n]+)", line_s, re.I)
                if m:
                    data["port25"] = m.group(1).strip()

        return data

    def _format_telegram_card(self, d: Dict[str, Any]) -> str:
        """将解析后的指标转化为符合 Telegram HTML 标准的精美排版卡片"""
        ip = d.get("ip", "未知")
        test_time = d.get("test_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        duration = d.get("duration_seconds", 0)

        # 辅助状态 Emoji
        def status_icon(val: str) -> str:
            v = str(val).lower()
            if any(w in v for w in ["yes", "解锁", "支持", "open", "开放", "0", "0%", "低", "clean", "low", "residential", "原生", "家宽"]):
                return "🟢"
            if any(w in v for w in ["no", "未解锁", "关闭", "closed", "block", "high", "高"]):
                return "🔴"
            if any(w in v for w in ["自制", "only", "med", "中"]):
                return "🟡"
            return "⚪"

        fraud_score = d.get("scamalytics_score", "未知")
        fraud_level = d.get("scamalytics_level", "")
        fraud_display = f"{fraud_score}" if not fraud_level else f"{fraud_score} ({fraud_level})"

        abuse_score = d.get("abuseipdb_score", "未知")
        ip_type = d.get("ip_type", "未知")

        netflix = d.get("netflix", "未知")
        disney = d.get("disney", "未知")
        youtube = d.get("youtube", "未知")
        chatgpt = d.get("chatgpt", "未知")
        tiktok = d.get("tiktok", "未知")
        port25 = d.get("port25", "未知")

        card = (
            f"📊 <b>IPv4 质量与解锁体检报告</b>\n"
            f"🕒 <b>检测时间:</b> <code>{test_time}</code> (耗时 {duration}s)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 <b>网络基础信息:</b>\n"
            f"• <b>公网 IPv4:</b> <code>{ip}</code>\n"
            f"• <b>归属地区:</b> {d.get('location', '未知')}\n"
            f"• <b>运营商/ASN:</b> {d.get('asn', '')} {d.get('org', '')}\n"
            f"• <b>IP 类型:</b> 🏠 <b>{ip_type}</b>\n\n"
            f"🛡️ <b>风控与欺诈评分:</b>\n"
            f"• Scamalytics: {status_icon(fraud_score)} <b>{fraud_display}</b>\n"
            f"• AbuseIPDB: {status_icon(abuse_score)} <b>{abuse_score}</b>\n"
            f"• IP2Location: {status_icon(d.get('ip2location', ''))} {d.get('ip2location', '正常')}\n\n"
            f"🎬 <b>流媒体与 AI 解锁:</b>\n"
            f"• Netflix: {status_icon(netflix)} {netflix}\n"
            f"• Disney+: {status_icon(disney)} {disney}\n"
            f"• YouTube: {status_icon(youtube)} {youtube}\n"
            f"• ChatGPT: {status_icon(chatgpt)} {chatgpt}\n"
            f"• TikTok: {status_icon(tiktok)} {tiktok}\n\n"
            f"✉️ <b>服务端口连通:</b>\n"
            f"• 25 端口出站: {status_icon(port25)} {port25}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>数据源自 xykt/IPQuality 开源体检脚本</i>"
        )
        return card


# 全局单例执行器实例
ipquality_runner = IPQualityRunner()
