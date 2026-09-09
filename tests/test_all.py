"""
自动化单元测试与集成测试脚本
测试项目各个核心模块：配置、存储、VPS服务、IPQuality解析器、权限校验与键盘构建
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
import pytest
from config import Settings
from ipquality_runner import IPQualityRunner, clean_ansi
from storage import StorageManager
from vps_service import is_valid_ipv4


def test_config_parsing():
    """测试配置解析与鉴权方法"""
    s = Settings(
        bot_token="test_token_123",
        allowed_user_ids="1001, 1002, 1003",
        vps_change_ip_token="secret_key_888",
        vps_change_ip_params='{"auth": "{token}", "action": "change"}',
        vps_change_ip_headers='{"Authorization": "Bearer {token}"}',
    )
    assert s.bot_token == "test_token_123"
    assert s.allowed_user_ids == {1001, 1002, 1003}
    assert s.is_user_allowed(1001) is True
    assert s.is_user_allowed(9999) is False

    parsed_params = s.get_parsed_params()
    assert parsed_params["auth"] == "secret_key_888"
    assert parsed_params["action"] == "change"

    parsed_headers = s.get_parsed_headers()
    assert parsed_headers["Authorization"] == "Bearer secret_key_888"


def test_storage_manager():
    """测试存储管理读写"""
    temp_dir = Path(tempfile.mkdtemp())
    try:
        sm = StorageManager(data_dir=temp_dir)
        # 初始为空
        assert sm.get_latest_record() is None
        assert sm.get_all_history() == []

        # 保存最新记录
        test_record = {
            "timestamp": "2026-09-09 12:00:00",
            "ip": "1.2.3.4",
            "formatted_card": "<b>Test Card</b>",
        }
        sm.save_latest_record(test_record)

        loaded = sm.get_latest_record()
        assert loaded is not None
        assert loaded["ip"] == "1.2.3.4"
        assert loaded["formatted_card"] == "<b>Test Card</b>"

        # 追加历史记录
        sm.add_history_entry({"type": "ip_change", "old_ip": "1.1.1.1", "new_ip": "2.2.2.2"})
        sm.add_history_entry({"type": "quality_test", "ip": "2.2.2.2"})

        hist = sm.get_recent_history(5)
        assert len(hist) == 2
        assert hist[0]["type"] == "quality_test"  # 最新插入在最前
        assert hist[1]["type"] == "ip_change"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_ipv4_validation():
    """测试 IPv4 地址格式校验"""
    assert is_valid_ipv4("8.8.8.8") is True
    assert is_valid_ipv4("1.1.1.1") is True
    assert is_valid_ipv4("114.114.114.114") is True
    # 私有地址不计入有效公网 IP
    assert is_valid_ipv4("192.168.1.1") is False
    assert is_valid_ipv4("10.0.0.1") is False
    assert is_valid_ipv4("127.0.0.1") is False
    # 非法格式
    assert is_valid_ipv4("999.999.999.999") is False
    assert is_valid_ipv4("invalid-ip") is False
    assert is_valid_ipv4("") is False


def test_clean_ansi():
    """测试终端 ANSI 字符清洗"""
    ansi_text = "\033[31mError:\033[0m Something \033[1;32mGood\033[0m\r\nLine 2"
    cleaned = clean_ansi(ansi_text)
    assert "Error:" in cleaned
    assert "Good" in cleaned
    assert "\033[" not in cleaned


def test_ipquality_parser():
    """测试 IPQuality 文本输出解析引擎与 Telegram HTML 卡片排版"""
    sample_text = """
    ------------------------ IP质量体检报告 ------------------------
    测试时间: 2026-09-09 08:00:00 UTC
    脚本版本: v2026-09-04
    1. 基础信息 (Maxmind 数据库)
    IP 地址: 114.119.130.55
    ASN: AS2497 (Internet Initiative Japan Inc.)
    组织: IIJ
    位置: Japan Tokyo (JP)
    IP 类型: 原生家宽 / ISP (Residential)
    2. 欺诈与风控评分
    Scamalytics 欺诈分: 5 (极低风险 / Very Low Risk)
    AbuseIPDB 滥用率: 0% (Clean)
    IP2Location 风险: 低 (Clean)
    IPQS 欺诈评分: 0
    3. 流媒体与 AI 解锁检测
    Netflix: 完整解锁 (日本区 / JP)
    Disney+: 完整解锁
    YouTube Premium: 支持
    ChatGPT (OpenAI): 网页端正常解锁
    TikTok: 原生解锁
    4. 邮件端口与服务检测
    25 端口出站: 开放 (Open)
    ----------------------------------------------------------------
    """
    runner = IPQualityRunner()
    parsed = runner._parse_output(sample_text)

    assert parsed["ip"] == "114.119.130.55"
    assert "AS2497" in parsed["asn"]
    assert "IIJ" in parsed["org"]
    assert "Tokyo" in parsed["location"]
    assert "原生" in parsed["ip_type"]
    assert parsed["scamalytics_score"] == "5"
    assert parsed["abuseipdb_score"] == "0%"
    assert "完整解锁" in parsed["netflix"]
    assert "解锁" in parsed["chatgpt"]
    assert "开放" in parsed["port25"]

    card = runner._format_telegram_card(parsed)
    assert "114.119.130.55" in card
    assert "AS2497" in card
    assert "🟢" in card
    assert "Netflix" in card
    assert "ChatGPT" in card


@pytest.mark.asyncio
async def test_ipquality_mock_run():
    """测试 IPQualityRunner 在模拟环境下的异步执行流程"""
    runner = IPQualityRunner()
    ok, card, record = await runner.run_check(current_ip="114.114.114.114")
    assert ok is True
    assert "114.114.114.114" in card
    assert record["status"] == "success"
    assert "formatted_card" in record


def test_keyboards_structure():
    """测试 Telegram 键盘与操作菜单的构建"""
    from handlers.common import get_main_inline_keyboard, get_main_reply_keyboard

    reply_kb = get_main_reply_keyboard()
    assert len(reply_kb.keyboard) >= 3
    all_texts = [btn.text if hasattr(btn, "text") else btn for row in reply_kb.keyboard for btn in row]
    assert "🌐 当前IP" in all_texts
    assert "🔄 更换IP" in all_texts
    assert "📊 质量报告" in all_texts
    assert "⚡ 立即测质" in all_texts

    inline_kb = get_main_inline_keyboard()
    all_callbacks = [btn.callback_data for row in inline_kb.inline_keyboard for btn in row]
    assert "menu_ip" in all_callbacks
    assert "menu_change_ip" in all_callbacks
    assert "menu_quality" in all_callbacks
    assert "menu_test" in all_callbacks


@pytest.mark.asyncio
async def test_auth_decorator(monkeypatch):
    """测试管理员权限校验拦截器"""
    from unittest.mock import AsyncMock, MagicMock
    from handlers.common import authorized_only
    import config

    monkeypatch.setattr(config.settings, "allowed_user_ids", {88888})

    called = False

    @authorized_only
    async def sample_handler(update, context):
        nonlocal called
        called = True

    # 1. 模拟未授权用户访问
    unauth_user = MagicMock()
    unauth_user.id = 99999
    unauth_user.full_name = "Hacker"
    unauth_user.username = "hacker"

    mock_msg = MagicMock()
    mock_msg.reply_text = AsyncMock()

    mock_update = MagicMock()
    mock_update.effective_user = unauth_user
    mock_update.callback_query = None
    mock_update.message = mock_msg

    await sample_handler(mock_update, MagicMock())
    assert called is False
    mock_msg.reply_text.assert_called_once()
    assert "拒绝" in mock_msg.reply_text.call_args[0][0] or "受限" in mock_msg.reply_text.call_args[0][0]

    # 2. 模拟授权管理员访问
    mock_msg.reply_text.reset_mock()
    auth_user = MagicMock()
    auth_user.id = 88888
    mock_update.effective_user = auth_user

    await sample_handler(mock_update, MagicMock())
    assert called is True


@pytest.mark.asyncio
async def test_change_ip_two_step_confirmation(monkeypatch):
    """测试更换 IP 的防误触二次确认逻辑"""
    from unittest.mock import AsyncMock, MagicMock
    from handlers.ip_handler import change_ip_cancel_handler, change_ip_prompt_handler
    import config

    monkeypatch.setattr(config.settings, "allowed_user_ids", {12345})

    user = MagicMock()
    user.id = 12345

    # 步骤 1: 触发更换 IP 提示
    mock_msg = MagicMock()
    mock_msg.reply_text = AsyncMock()

    mock_update = MagicMock()
    mock_update.effective_user = user
    mock_update.callback_query = None
    mock_update.message = mock_msg

    await change_ip_prompt_handler(mock_update, MagicMock())
    mock_msg.reply_text.assert_called_once()
    args, kwargs = mock_msg.reply_text.call_args
    prompt_text = args[0]
    keyboard = kwargs["reply_markup"]

    # 必须包含安全确认警示与【确认更换】和【取消】按钮
    assert "安全确认" in prompt_text or "确定要更换" in prompt_text
    callbacks = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert "confirm_change_ip" in callbacks
    assert "cancel_change_ip" in callbacks

    # 步骤 2: 用户点击【取消操作】
    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    mock_update.callback_query = query
    mock_update.message = None

    await change_ip_cancel_handler(mock_update, MagicMock())
    query.answer.assert_called_once_with("已取消更换")
    query.edit_message_text.assert_called_once()
    assert "已取消" in query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_boil_network_api_calls(monkeypatch):
    """测试 boil.network API 的调用与 Bearer Token 鉴权"""
    import config
    from unittest.mock import AsyncMock, MagicMock
    from vps_service import vps_service

    test_token = "boil_test_token_abc123"
    monkeypatch.setattr(config.settings, "vps_api_token", test_token)
    monkeypatch.setattr(config.settings, "vps_change_ip_token", None)
    monkeypatch.setattr(config.settings, "vps_query_ip_token", None)
    monkeypatch.setattr(config.settings, "vps_query_ip_url", "https://ippanel.boil.network/api/v1/getIP")
    monkeypatch.setattr(config.settings, "vps_change_ip_url", "https://ippanel.boil.network/api/v1/changeIP/")
    monkeypatch.setattr(config.settings, "vps_query_ip_method", "POST")
    monkeypatch.setattr(config.settings, "vps_change_ip_method", "POST")

    assert config.settings.effective_vps_token == test_token

    # 1. 模拟查询 IP
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {"code": 200, "ip": "218.102.12.34", "msg": "success"}
    mock_get_resp.text = '{"code": 200, "ip": "218.102.12.34", "msg": "success"}'

    mock_change_resp = MagicMock()
    mock_change_resp.status_code = 200
    mock_change_resp.json.return_value = {"code": 200, "msg": "IP change request submitted successfully"}
    mock_change_resp.text = '{"code": 200, "msg": "IP change request submitted successfully"}'

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.post = AsyncMock(side_effect=[mock_get_resp, mock_change_resp])

    monkeypatch.setattr(vps_service, "_http_client", mock_client)

    # 执行查询 IP
    ip = await vps_service.get_current_ip()
    assert ip == "218.102.12.34"
    mock_client.post.assert_called_once()
    call_args, call_kwargs = mock_client.post.call_args
    assert call_args[0] == "https://ippanel.boil.network/api/v1/getIP"
    assert call_kwargs["headers"]["Authorization"] == f"Bearer {test_token}"

    # 执行更换 IP
    success, msg = await vps_service.change_ip()
    assert success is True
    assert "IP change request submitted" in msg or "受理" in msg or "成功" in msg
    assert mock_client.post.call_count == 2
    change_call_args, change_call_kwargs = mock_client.post.call_args
    assert change_call_args[0] == "https://ippanel.boil.network/api/v1/changeIP/"
    assert change_call_kwargs["headers"]["Authorization"] == f"Bearer {test_token}"
