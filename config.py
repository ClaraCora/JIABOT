"""
配置管理模块
基于 pydantic-settings，支持从 .env 文件及环境变量中自动加载与校验配置
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True
    )

    # 1. Telegram Bot 基本配置
    bot_token: str = Field(default="", description="Telegram Bot Token", validation_alias="BOT_TOKEN")
    allowed_user_ids: Set[int] = Field(default_factory=set, description="允许使用的 Telegram 用户 ID 集合", validation_alias="ALLOWED_USER_IDS")

    # 2. VPS 更换 IP 与 查询 IP 配置 (适配 boil.network 等家宽平台)
    vps_api_token: Optional[str] = Field(default=None, description="VPS API 统一 Token", validation_alias="VPS_API_TOKEN")
    vps_change_ip_url: str = Field(default="https://ippanel.boil.network/api/v1/changeIP/", description="VPS 更换 IP API URL", validation_alias="VPS_CHANGE_IP_URL")
    vps_change_ip_token: Optional[str] = Field(default=None, description="VPS 更换 IP API Token", validation_alias="VPS_CHANGE_IP_TOKEN")
    vps_change_ip_method: str = Field(default="POST", description="API 请求方法 GET 或 POST", validation_alias="VPS_CHANGE_IP_METHOD")
    vps_change_ip_params: Optional[str] = Field(default=None, description="请求参数 JSON 字符串", validation_alias="VPS_CHANGE_IP_PARAMS")
    vps_change_ip_headers: Optional[str] = Field(default=None, description="请求头 JSON 字符串", validation_alias="VPS_CHANGE_IP_HEADERS")
    vps_change_ip_command: Optional[str] = Field(default=None, description="本地更换 IP Shell 命令", validation_alias="VPS_CHANGE_IP_COMMAND")

    # 3. VPS IP 查询配置
    vps_query_ip_url: str = Field(default="https://ippanel.boil.network/api/v1/getIP", description="VPS 服务商 IP 查询 API", validation_alias="VPS_QUERY_IP_URL")
    vps_query_ip_token: Optional[str] = Field(default=None, description="VPS 查询 IP API Token", validation_alias="VPS_QUERY_IP_TOKEN")
    vps_query_ip_method: str = Field(default="POST", description="查询 IP API 方法 GET 或 POST", validation_alias="VPS_QUERY_IP_METHOD")

    # 4. xykt/IPQuality 脚本检测与调度配置
    ipquality_cron_hours: int = Field(default=12, description="定时检测周期(小时)", validation_alias="IPQUALITY_CRON_HOURS")
    auto_test_on_ip_change: bool = Field(default=True, description="换 IP 成功后是否自动体检", validation_alias="AUTO_TEST_ON_IP_CHANGE")
    ipquality_test_timeout: int = Field(default=300, description="IPQuality 执行超时秒数", validation_alias="IPQUALITY_TEST_TIMEOUT")
    ipquality_script_url: str = Field(default="https://IP.Check.Place", description="脚本 URL", validation_alias="IPQUALITY_SCRIPT_URL")

    # 5. 系统与存储配置
    data_dir: Path = Field(default=Path("./data"), description="数据存储路径", validation_alias="DATA_DIR")
    log_level: str = Field(default="INFO", description="日志等级", validation_alias="LOG_LEVEL")

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, v: Any) -> Set[int]:
        if isinstance(v, set):
            return {int(x) for x in v}
        if isinstance(v, list):
            return {int(x) for x in v}
        if isinstance(v, str):
            res = set()
            for part in v.split(","):
                part = part.strip()
                if part and part.isdigit():
                    res.add(int(part))
            return res
        return set()

    @field_validator("data_dir", mode="before")
    @classmethod
    def parse_data_dir(cls, v: Any) -> Path:
        p = Path(v) if isinstance(v, str) else v
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def effective_vps_token(self) -> str:
        """获取生效的 VPS API Token（优先使用统一配置 VPS_API_TOKEN）"""
        return self.vps_api_token or self.vps_change_ip_token or self.vps_query_ip_token or ""

    def get_parsed_params(self) -> Dict[str, Any]:
        """解析自定义参数模板，自动将 {token} 替换为实际 token"""
        if not self.vps_change_ip_params:
            return {}
        try:
            token = self.effective_vps_token
            raw = self.vps_change_ip_params.replace("{token}", token)
            return json.loads(raw)
        except Exception as e:
            logging.warning(f"解析 VPS_CHANGE_IP_PARAMS 失败: {e}")
            return {}

    def get_parsed_headers(self) -> Dict[str, str]:
        """解析自定义请求头模板，自动将 {token} 替换为实际 token"""
        headers: Dict[str, str] = {}
        # 如果配置了自定义头，优先解析
        if self.vps_change_ip_headers:
            try:
                token = self.effective_vps_token
                raw = self.vps_change_ip_headers.replace("{token}", token)
                headers = json.loads(raw)
            except Exception as e:
                logging.warning(f"解析 VPS_CHANGE_IP_HEADERS 失败: {e}")
        # 如果未显式定义 Authorization，且有 token，则默认添加 Bearer 鉴权头
        if self.effective_vps_token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.effective_vps_token}"
        return headers

    def is_user_allowed(self, user_id: int) -> bool:
        """检查用户 ID 是否在授权白名单内"""
        # 如果未配置任何管理员 ID，出于安全保护默认拒绝访问并告警
        if not self.allowed_user_ids:
            return False
        return user_id in self.allowed_user_ids


# 全局单例配置实例
settings = Settings()
