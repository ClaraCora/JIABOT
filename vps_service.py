"""
VPS 运维服务模块
负责公网 IPv4 查询、归属地检测、更换 IP API/命令调用以及新 IP 异步变动探测
"""

import asyncio
import ipaddress
import logging
import re
import time
from typing import Any, Dict, Optional, Tuple
import httpx
from config import settings
from storage import storage

logger = logging.getLogger(__name__)

# 公网权威 IPv4 探测源（互为备份）
PUBLIC_IP_SOURCES = [
    "https://api.ipify.org",
    "https://ipinfo.io/ip",
    "https://icanhazip.com",
    "https://myip.check.place",
    "https://ifconfig.me/ip",
]


def is_valid_ipv4(ip_str: str) -> bool:
    """校验是否为有效的 IPv4 地址"""
    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        return ip.version == 4 and not ip.is_private
    except ValueError:
        return False


class VPSService:
    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0, follow_redirects=True)
        return self._http_client

    async def get_current_ip(self) -> Optional[str]:
        """获取 VPS 当前公网 IPv4 地址"""
        client = await self._get_client()

        # 1. 优先尝试从服务商查询 API 获取 (例如 boil.network 的 /api/v1/getIP)
        if settings.vps_query_ip_url:
            try:
                headers = {}
                token = settings.effective_vps_token
                if token:
                    headers["Authorization"] = f"Bearer {token}"

                method = settings.vps_query_ip_method.upper()
                if method == "POST":
                    resp = await client.post(settings.vps_query_ip_url, headers=headers, timeout=8.0)
                else:
                    resp = await client.get(settings.vps_query_ip_url, headers=headers, timeout=8.0)

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        # 尝试常见 JSON 结构
                        if isinstance(data, dict):
                            for key in ["ip", "ipv4", "data", "address", "result", "current_ip", "msg"]:
                                val = data.get(key)
                                if isinstance(val, str) and is_valid_ipv4(val):
                                    return val.strip()
                                if isinstance(val, dict) and "ip" in val and is_valid_ipv4(val["ip"]):
                                    return val["ip"].strip()
                        elif isinstance(data, str) and is_valid_ipv4(data):
                            return data.strip()
                    except Exception:
                        pass

                    # 兜底：从返回文本中使用正则提取 IPv4
                    m = re.search(r"([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})", resp.text)
                    if m and is_valid_ipv4(m.group(1)):
                        return m.group(1)
            except Exception as e:
                logger.warning(f"通过 VPS 服务商接口查询 IP 失败: {e}，将自动切换公网公共节点查询")

        # 2. 公网权威节点轮询获取（高可用备选池）
        for url in PUBLIC_IP_SOURCES:
            try:
                resp = await client.get(url, timeout=5.0)
                if resp.status_code == 200:
                    text = resp.text.strip()
                    if is_valid_ipv4(text):
                        return text
            except Exception as e:
                logger.debug(f"探测源 {url} 查询超时或失败: {e}")
                continue

        logger.error("所有公网 IP 探测源均无法获取当前 IPv4 地址")
        return None

    async def get_ip_details(self, ip: str) -> Dict[str, Any]:
        """获取指定 IP 的基础地理位置与 ISP 归属信息"""
        if not is_valid_ipv4(ip):
            return {"ip": ip, "country": "未知", "city": "未知", "isp": "未知", "asn": "未知"}

        client = await self._get_client()
        try:
            # 采用免费中立的 ip-api 中文节点
            url = f"http://ip-api.com/json/{ip}?lang=zh-CN&fields=status,message,country,regionName,city,isp,org,as,query"
            resp = await client.get(url, timeout=6.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return {
                        "ip": ip,
                        "country": data.get("country", "未知"),
                        "region": data.get("regionName", ""),
                        "city": data.get("city", "未知"),
                        "isp": data.get("isp", "未知"),
                        "org": data.get("org", ""),
                        "asn": data.get("as", "未知"),
                    }
        except Exception as e:
            logger.warning(f"获取 IP 归属地详情失败: {e}")

        return {"ip": ip, "country": "未知", "city": "未知", "isp": "未知", "asn": "未知"}

    async def change_ip(self) -> Tuple[bool, str]:
        """
        触发更换 IP 操作
        返回: (是否成功提交, 详细说明/错误信息)
        """
        # 模式 1: 本地命令执行 (如 PPPoE 重新拨号或自建 Shell 脚本)
        if settings.vps_change_ip_command:
            logger.info(f"执行本地更换 IP 命令: {settings.vps_change_ip_command}")
            try:
                proc = await asyncio.create_subprocess_shell(
                    settings.vps_change_ip_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
                if proc.returncode == 0:
                    out_msg = stdout.decode("utf-8", errors="replace").strip()
                    logger.info(f"本地换 IP 命令执行成功: {out_msg}")
                    return True, f"本地重拨/换IP命令已执行成功: {out_msg[:100]}"
                else:
                    err_msg = stderr.decode("utf-8", errors="replace").strip()
                    logger.error(f"本地换 IP 命令退出码非0: {proc.returncode}, 错误: {err_msg}")
                    return False, f"本地换 IP 命令执行失败 (退出码 {proc.returncode}): {err_msg[:200]}"
            except asyncio.TimeoutError:
                return False, "执行本地更换 IP 命令超时 (30秒)"
            except Exception as e:
                logger.error(f"执行本地换 IP 命令异常: {e}", exc_info=True)
                return False, f"本地命令异常: {str(e)}"

        # 模式 2: HTTP API 请求
        if settings.vps_change_ip_url:
            logger.info(f"向 VPS 服务商发送换 IP 请求: {settings.vps_change_ip_url}")
            client = await self._get_client()
            params = settings.get_parsed_params()
            headers = settings.get_parsed_headers()
            method = settings.vps_change_ip_method.upper()

            token = settings.effective_vps_token
            if not token and not settings.vps_change_ip_command:
                return False, "未配置 VPS API Token，请在 .env 中设置 VPS_API_TOKEN！"

            if token and "Authorization" not in headers:
                headers["Authorization"] = f"Bearer {token}"

            try:
                if method == "POST":
                    resp = await client.post(settings.vps_change_ip_url, params=params, json=params, headers=headers, timeout=20.0)
                else:
                    resp = await client.get(settings.vps_change_ip_url, params=params, headers=headers, timeout=20.0)

                resp_text = resp.text.strip()
                logger.info(f"服务商换 IP 接口响应 [{resp.status_code}]: {resp_text[:200]}")

                if resp.status_code in [200, 201, 202, 204]:
                    # 尝试解析可能包含的错误信息
                    try:
                        data = resp.json()
                        if isinstance(data, dict):
                            # 如果包含 code/status 且表示失败
                            code = data.get("code") or data.get("status")
                            msg = data.get("msg") or data.get("message") or ""
                            if code not in [None, 0, 200, "success", "ok", True] and "error" in str(code).lower():
                                return False, f"服务商返回业务错误: {msg or code}"
                            return True, f"请求已受理: {msg or '更换指令已发送'}"
                    except Exception:
                        pass
                    return True, "更换指令已成功发送至服务商"
                else:
                    return False, f"服务商接口返回异常状态码 {resp.status_code}: {resp_text[:200]}"
            except httpx.TimeoutException:
                return False, "请求 VPS 服务商换 IP 接口超时"
            except Exception as e:
                logger.error(f"请求 VPS 更换 IP 接口异常: {e}", exc_info=True)
                return False, f"请求接口发生异常: {str(e)}"

        return False, "未配置 VPS 更换 IP 的 API URL 或本地命令，请在 .env 中设置！"

    async def watch_ip_change(
        self,
        old_ip: Optional[str],
        timeout_seconds: int = 180,
        poll_interval: int = 6
    ) -> Tuple[bool, Optional[str], int]:
        """
        后台轮询探测新 IP，直到检测到 IP 发生变化且网络恢复
        返回: (是否成功换到新IP, 新IP地址, 总耗时秒数)
        """
        start_time = time.time()
        logger.info(f"开始轮询探测新 IP (旧IP: {old_ip})，最大等待 {timeout_seconds} 秒...")

        # 换 IP 初期给网络一点断开重连的时间，先静默等待 10 秒
        await asyncio.sleep(8)

        while time.time() - start_time < timeout_seconds:
            current_ip = await self.get_current_ip()
            elapsed = int(time.time() - start_time)

            if current_ip and is_valid_ipv4(current_ip):
                if old_ip is None or current_ip != old_ip:
                    logger.info(f"🎉 成功检测到新公网 IP: {current_ip} (原IP: {old_ip}, 耗时 {elapsed}s)")
                    # 记录至历史记录
                    storage.add_history_entry({
                        "type": "ip_change",
                        "old_ip": old_ip or "未知",
                        "new_ip": current_ip,
                        "duration_seconds": elapsed,
                        "status": "success",
                    })
                    return True, current_ip, elapsed

            await asyncio.sleep(poll_interval)

        elapsed = int(time.time() - start_time)
        latest_ip = await self.get_current_ip()
        logger.warning(f"轮询探测新 IP 超时 ({timeout_seconds}s)，当前探测到的 IP 为: {latest_ip}")
        return False, latest_ip, elapsed


# 全局单例服务实例
vps_service = VPSService()
