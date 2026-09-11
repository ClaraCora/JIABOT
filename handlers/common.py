"""
通用处理模块
包含鉴权装饰器、常驻键盘定义、/start 与 /help 命令以及主菜单路由
"""

import functools
import logging
from typing import Callable
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import settings
from storage import storage
from ipquality_runner import (
    extract_fallback_region,
    format_location_display,
    media_status_icon,
    risk_status_icon,
    sanitize_media_display_val,
)

logger = logging.getLogger(__name__)


def authorized_only(func: Callable):
    """权限校验装饰器：仅允许在 ALLOWED_USER_IDS 中的用户执行"""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return

        user_id = user.id
        if not settings.is_user_allowed(user_id):
            logger.warning(f"未授权用户尝试访问: ID={user_id}, Name={user.full_name}, Username=@{user.username}")
            msg = (
                f"⛔ <b>访问受限 / Access Denied</b>\n\n"
                f"您不在当前机器人的管理员授权白名单中。\n"
                f"您的 Telegram User ID 为: <code>{user_id}</code>\n\n"
                f"<i>请将此 ID 填入 VPS 机器人的 <code>ALLOWED_USER_IDS</code> 配置项后重试。</i>"
            )
            if update.callback_query:
                await update.callback_query.answer("⛔ 权限不足", show_alert=True)
                await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.HTML)
            elif update.message:
                await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            return

        return await func(update, context, *args, **kwargs)

    return wrapper


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """构建底部常驻回复键盘，方便手机端直接点击常用功能"""
    keyboard = [
        ["🌐 当前IP", "🔄 更换IP"],
        ["📊 质量报告", "⚡ 立即测质"],
        ["📜 历史记录", "❓ 帮助说明"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    """构建内联控制面板按钮"""
    buttons = [
        [
            InlineKeyboardButton("🌐 查询当前IP", callback_data="menu_ip"),
            InlineKeyboardButton("🔄 更换 VPS IP", callback_data="menu_change_ip"),
        ],
        [
            InlineKeyboardButton("📊 查看质量报告", callback_data="menu_quality"),
            InlineKeyboardButton("⚡ 立即体检IP", callback_data="menu_test"),
        ],
        [
            InlineKeyboardButton("📜 IP/检测历史", callback_data="menu_history"),
            InlineKeyboardButton("❓ 帮助说明", callback_data="menu_help"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


@authorized_only
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """响应 /start 命令"""
    user = update.effective_user
    welcome_text = (
        f"👋 您好，<b>{user.first_name}</b>！\n\n"
        f"🤖 欢迎使用 <b>家宽 VPS 自动化运维机器人</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"本机器人已与您的 VPS 绑定，提供以下核心能力：\n\n"
        f"• 🌐 <b>IP 查询</b>：实时获取公网 IPv4 及归属地运营商\n"
        f"• 🔄 <b>更换 IP</b>：双重确认防误触更换 VPS 公网 IP\n"
        f"• 📊 <b>质量体检</b>：查看由 <code>xykt/IPQuality</code> 测得的最新评分与解锁\n"
        f"• ⚡ <b>实时体检</b>：一键在 VPS 后台运行脚本并推送卡片\n"
        f"• ⏰ <b>定时巡检</b>：每 <b>{settings.ipquality_cron_hours}</b> 小时自动体检留存\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 请点击下方菜单或直接在键盘选择功能："
    )

    if update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_reply_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        # 附带一个内联面板
        await update.message.reply_text(
            "🕹️ <b>快捷主控面板：</b>",
            reply_markup=get_main_inline_keyboard(),
            parse_mode=ParseMode.HTML,
        )
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            welcome_text,
            reply_markup=get_main_inline_keyboard(),
            parse_mode=ParseMode.HTML,
        )


@authorized_only
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """响应 /help 命令与帮助菜单"""
    help_text = (
        f"📖 <b>家宽 VPS 机器人指令与使用手册</b>\n\n"
        f"<b>常用命令列表：</b>\n"
        f"• /start - 唤出主控面板与常驻快捷键盘\n"
        f"• /ip - 快速查询 VPS 当前公网 IPv4 与位置\n"
        f"• /change_ip - 启动更换 IP 流程 (带二次确认)\n"
        f"• /quality 或 /report - 查看最后一次留存的质量体检报告\n"
        f"• /test - 立即执行 <code>xykt/IPQuality</code> 脚本体检\n"
        f"• /history - 查看最近的 IP 变动与体检历史\n"
        f"• /help - 查看本使用说明\n\n"
        f"<b>防误触更换 IP 说明：</b>\n"
        f"点击“更换IP”后，机器人将弹出<b>二次确认菜单</b>，必须显式点击【⚠️ 确认更换】才会发起请求，有效避免日常误触中断业务。\n\n"
        f"<b>自动体检机制：</b>\n"
        f"机器人内置定时巡检，每天在 {settings.ipquality_cron_times}（时区: {settings.timezone}）自动体检一次并推送报告。若配置了换 IP 后自动体检，换 IP 完成后也会自动推送新 IP 质量。"
    )

    if update.message:
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)
    elif update.callback_query:
        await update.callback_query.answer()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start")]
        ])
        await update.callback_query.edit_message_text(
            help_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )


HISTORY_PAGE_SIZE = 4


def format_history_card(items: list, page: int, total_pages: int, total_count: int) -> str:
    """格式化历史记录卡片，包含详细网络属性、风险评分与每一次完整的流媒体/AI解锁状态"""
    if not items:
        return "📜 <b>历史记录</b>\n\n暂无历史记录，换 IP 或体检完成后将在此展示。"

    lines = [
        f"📜 <b>最近 IP 变动与体检历史记录</b> (第 {page}/{total_pages} 页 · 共 {total_count} 条)",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for idx, item in enumerate(items, 1):
        global_idx = (page - 1) * HISTORY_PAGE_SIZE + idx
        t = item.get("timestamp", "未知时间")
        item_type = item.get("type", "unknown")

        if item_type == "ip_change":
            old_ip = item.get("old_ip", "未知")
            new_ip = item.get("new_ip", "未知")
            dur = item.get("duration_seconds", 0)
            dur_text = f" (耗时 {dur}s)" if dur > 0 else " (自动监控)"
            loc = format_location_display(item.get("location", ""))
            loc_line = f"\n   🌐 地区: {loc}" if loc else ""
            lines.append(
                f"<b>{global_idx}. 🔄 IP 更换:</b>\n"
                f"   • 链路: <code>{old_ip}</code> ➔ <code>{new_ip}</code>\n"
                f"   • 时间: 🕒 <i>{t}</i>{dur_text}{loc_line}"
            )

        elif item_type == "quality_test":
            ip = item.get("ip", "未知")
            dur = item.get("duration_seconds", 0)
            raw_loc = item.get("location", "")
            loc = format_location_display(raw_loc)
            loc_str = f" ({loc})" if loc else ""
            ip_type = item.get("ip_type", "原生IP")
            scam_s = item.get("scamalytics_score", "0")
            scam_l = item.get("scamalytics_level", "低风险" if str(scam_s) in ["0", "0%"] else "")
            scam_display = f"{scam_s} ({scam_l})" if scam_l else str(scam_s)
            scam_icon = risk_status_icon(scam_s, scam_l)

            # 流媒体与 AI 解锁列表
            media_dict = item.get("media_unlock") or item.get("unlocks") or {}
            media_services = [
                ("Netflix", item.get("netflix") or media_dict.get("netflix") or media_dict.get("Netflix")),
                ("Disney+", item.get("disney") or media_dict.get("disney+") or media_dict.get("disney") or media_dict.get("Disney+")),
                ("YouTube", item.get("youtube") or media_dict.get("youtube") or media_dict.get("YouTube")),
                ("ChatGPT", item.get("chatgpt") or media_dict.get("chatgpt") or media_dict.get("ChatGPT")),
                ("TikTok", item.get("tiktok") or media_dict.get("tiktok") or media_dict.get("TikTok")),
                ("AmazonPV", item.get("amazon") or media_dict.get("amazonpv") or media_dict.get("amazon") or media_dict.get("AmazonPV")),
                ("Reddit", item.get("reddit") or media_dict.get("reddit") or media_dict.get("Reddit")),
            ]

            # 判断是否为新版记录（含有多个服务）
            is_new_style = any(k in item for k in ["disney", "youtube", "tiktok", "amazon", "reddit"]) or bool(media_dict)
            fallback_rg = extract_fallback_region(item)

            unlock_lines = []
            for name, val in media_services:
                val = sanitize_media_display_val(val, fallback_rg=fallback_rg)
                if val and str(val).strip() and str(val).strip() != "未知":
                    val_str = str(val).strip()
                    icon = media_status_icon(val_str)
                    icon_prefix = f"{icon} " if icon else ""
                    unlock_lines.append(f"   • {name}: {icon_prefix}{val_str}")
                elif is_new_style:
                    unlock_lines.append(f"   • {name}: ⚪ 未知")

            record_text = (
                f"<b>{global_idx}. 📊 质量体检:</b> <code>{ip}</code>{loc_str}\n"
                f"   🕒 <i>{t}</i> (耗时 {dur}s)\n"
                f"   🏠 {ip_type} | 🛡️ 欺诈: {scam_icon} {scam_display}"
            )

            if unlock_lines:
                record_text += "\n   🎬 <b>流媒体与 AI 解锁:</b>\n" + "\n".join(unlock_lines)
            else:
                record_text += "\n   🎬 <b>解锁状态:</b> ⚪ 暂无解锁数据"

            lines.append(record_text)

        else:
            lines.append(f"<b>{global_idx}. 记录:</b> 🕒 <i>{t}</i>")

        if idx < len(items):
            lines.append("────────────────────")

    return "\n".join(lines)


@authorized_only
async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """响应 /history 命令与分页回调，查看历史记录"""
    page = 1
    if update.callback_query and update.callback_query.data:
        data = update.callback_query.data
        if data.startswith("history_page:"):
            try:
                page = int(data.split(":")[1])
            except (IndexError, ValueError):
                page = 1

    all_history = storage.get_all_history()
    total_count = len(all_history)
    page_size = HISTORY_PAGE_SIZE
    total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count > 0 else 1
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_items = all_history[start_idx:end_idx]

    text = format_history_card(page_items, page, total_pages, total_count)

    keyboard_buttons = []
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"history_page:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"{page} / {total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("下一页 ▶️", callback_data=f"history_page:{page + 1}"))
        keyboard_buttons.append(nav_row)

    action_row = [
        InlineKeyboardButton("🔄 刷新", callback_data=f"history_page:{page}"),
        InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start"),
    ]
    keyboard_buttons.append(action_row)
    keyboard = InlineKeyboardMarkup(keyboard_buttons)

    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            await update.callback_query.answer()
        except Exception as e:
            if "Message is not modified" in str(e):
                await update.callback_query.answer("已是最新记录")
            else:
                logger.warning(f"更新历史记录消息失败: {e}")
                await update.callback_query.answer()


@authorized_only
async def noop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用于不可点击的占位按钮（如页码显示）"""
    if update.callback_query:
        await update.callback_query.answer()
