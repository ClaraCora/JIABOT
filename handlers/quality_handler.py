"""
IP 质量检测处理模块
负责查看最后一次留存的 IPQuality 报告、手动触发实时体检与导出完整原始日志
"""

import io
import logging
from datetime import datetime
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from handlers.common import authorized_only
from ipquality_runner import ipquality_runner
from storage import storage
from vps_service import vps_service

logger = logging.getLogger(__name__)


@authorized_only
async def quality_report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查看最后一次留存的 IP 质量体检报告（秒级响应，无需重新跑脚本）
    """
    if update.callback_query:
        await update.callback_query.answer()

    record = storage.get_latest_record()

    if not record or "formatted_card" not in record:
        empty_text = (
            "📊 <b>暂无留存的 IP 质量体检报告</b>\n\n"
            "尚未执行过体检。点击下方按钮立即在 VPS 上执行 <code>xykt/IPQuality</code> 脚本！"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ 立即体检", callback_data="menu_test")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start")],
        ])
        if update.callback_query:
            await update.callback_query.edit_message_text(empty_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(empty_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return

    if record and "summary" in record and isinstance(record["summary"], dict):
        card_text = ipquality_runner._format_telegram_card(record["summary"])
    else:
        card_text = record.get("formatted_card", "")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ 重新体检", callback_data="menu_test"),
            InlineKeyboardButton("📄 导出完整日志", callback_data="export_raw_quality"),
        ],
        [
            InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start"),
        ],
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(card_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(card_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@authorized_only
async def quality_test_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    立即手动触发 xykt/IPQuality 脚本体检
    """
    if ipquality_runner.is_running:
        msg = "⚠️ 当前已有检测任务正在后台运行，请等待 1~2 分钟完成后再试！"
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg)
        return

    loading_text = (
        "⏳ <b>正在启动 xykt/IPQuality 质量体检脚本...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "正在检测公网 IPv4、多数据库风控评分、流媒体解锁 (Netflix/Disney+/YouTube/ChatGPT/TikTok) 以及 25 端口。\n\n"
        "<i>完整体检通常耗时约 30~90 秒，完成后将自动推送精美报告，请稍候...</i>"
    )

    if update.callback_query:
        await update.callback_query.answer()
        status_msg = await update.callback_query.edit_message_text(loading_text, parse_mode=ParseMode.HTML)
    else:
        status_msg = await update.message.reply_text(loading_text, parse_mode=ParseMode.HTML)

    # 获取当前 IP
    current_ip = await vps_service.get_current_ip()

    # 执行体检
    success, card_or_err, _ = await ipquality_runner.run_check(current_ip=current_ip)

    if success:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 再次体检", callback_data="menu_test"),
                InlineKeyboardButton("📄 导出完整日志", callback_data="export_raw_quality"),
            ],
            [
                InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start"),
            ],
        ])
        await status_msg.edit_text(card_or_err, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 重试", callback_data="menu_test")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start")],
        ])
        await status_msg.edit_text(card_or_err, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@authorized_only
async def quality_export_raw_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """导出纯文本完整原始体检报告文件"""
    query = update.callback_query
    await query.answer()

    record = storage.get_latest_record()
    if not record or "raw_text" not in record or not record["raw_text"]:
        await query.message.reply_text("未找到原始报告文本记录。")
        return

    raw_text = record["raw_text"]
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_bytes = io.BytesIO(raw_text.encode("utf-8"))
    file_bytes.name = f"ipquality_report_{timestamp_str}.txt"

    caption = f"📄 <b>xykt/IPQuality 原始检测日志</b>\n检测时间: {record.get('timestamp', '未知')}"
    await query.message.reply_document(
        document=file_bytes,
        filename=file_bytes.name,
        caption=caption,
        parse_mode=ParseMode.HTML
    )
