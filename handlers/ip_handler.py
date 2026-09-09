"""
IP 查询与更换处理模块
包含公网 IP 探测、二次确认安全菜单、更换 IP 触发与后台新 IP 变动监听通知
"""

import asyncio
import logging
from typing import Optional
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import settings
from handlers.common import authorized_only
from ipquality_runner import ipquality_runner
from vps_service import vps_service

logger = logging.getLogger(__name__)


@authorized_only
async def ip_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """响应 /ip 命令与“当前IP”查询"""
    # 优先给予加载反馈
    loading_text = "🔍 正在探测 VPS 公网 IPv4 地址与节点归属，请稍候..."
    if update.callback_query:
        await update.callback_query.answer()
        status_msg = await update.callback_query.edit_message_text(loading_text, parse_mode=ParseMode.HTML)
    else:
        status_msg = await update.message.reply_text(loading_text, parse_mode=ParseMode.HTML)

    ip = await vps_service.get_current_ip()
    if not ip:
        err_text = (
            "❌ <b>获取公网 IPv4 失败</b>\n\n"
            "无法通过公网探测源或服务商 API 获取当前 IP，请检查 VPS 外网连通性。"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 重新查询", callback_data="menu_ip")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start")],
        ])
        await status_msg.edit_text(err_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return

    details = await vps_service.get_ip_details(ip)
    country = details.get("country", "未知")
    city = details.get("city", "")
    region = details.get("region", "")
    loc_str = f"{country} {region} {city}".strip()
    isp = details.get("isp", "未知")
    asn = details.get("asn", "")

    result_text = (
        f"🌐 <b>VPS 当前公网 IPv4 信息</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>公网 IPv4:</b> <code>{ip}</code>\n"
        f"• <b>归属地区:</b> {loc_str or '未知'}\n"
        f"• <b>服务商/ISP:</b> {isp}\n"
        f"• <b>自治域/ASN:</b> {asn}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>提示：如需更换此 IP，请点击下方“更换 IP”按钮。</i>"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 更换此 IP", callback_data="menu_change_ip"),
            InlineKeyboardButton("⚡ 体检此 IP", callback_data="menu_test"),
        ],
        [
            InlineKeyboardButton("🔄 刷新", callback_data="menu_ip"),
            InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start"),
        ],
    ])

    await status_msg.edit_text(result_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@authorized_only
async def change_ip_prompt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    更换 IP 入口：展示【二次安全确认菜单】，防止误触导致 VPS 网络中断
    """
    if update.callback_query:
        await update.callback_query.answer()

    # 先获取当前 IP 告知用户
    current_ip = await vps_service.get_current_ip()
    ip_display = f"<code>{current_ip}</code>" if current_ip else "<i>(探测中)</i>"

    prompt_text = (
        f"⚠️ <b>【安全确认】您确定要更换 VPS 的公网 IP 吗？</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>当前 IPv4:</b> {ip_display}\n\n"
        f"❗ <b>重要风险提示：</b>\n"
        f"1. 更换 IP 将导致 VPS 网络连接出现 <b>30秒 ~ 2分钟</b> 的短暂中断。\n"
        f"2. 现有的 SSH 终端连接、在线代理会话等都将被切断并重新连接。\n"
        f"3. 更换完成后，机器人将在后台自动追踪并通知您新的 IP 地址。\n\n"
        f"<b>请确认是否立即执行更换？</b>"
    )

    # 关键防误触按钮：确认更换 与 取消
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ 确认更换 IP ⚠️", callback_data="confirm_change_ip"),
        ],
        [
            InlineKeyboardButton("❌ 取消操作", callback_data="cancel_change_ip"),
            InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start"),
        ],
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(prompt_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(prompt_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@authorized_only
async def change_ip_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    用户点击【确认更换】后执行实际更换流程，并在后台轮询探测新 IP
    """
    query = update.callback_query
    await query.answer("正在提交换 IP 请求...", show_alert=False)

    chat_id = update.effective_chat.id

    # 记录更换前的旧 IP
    old_ip = await vps_service.get_current_ip()

    await query.edit_message_text(
        "⏳ <b>正在向 VPS 服务商发送更换 IP 请求...</b>",
        parse_mode=ParseMode.HTML
    )

    # 调用换 IP API 或 本地脚本
    success, msg = await vps_service.change_ip()

    if not success:
        logger.error(f"更换 IP 请求失败: {msg}")
        fail_text = (
            f"❌ <b>更换 IP 请求失败</b>\n\n"
            f"<b>原因:</b> {msg}\n\n"
            f"请检查 <code>.env</code> 中的 API 接口配置、Token 或网络连通性。"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 重试", callback_data="menu_change_ip")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start")],
        ])
        await query.edit_message_text(fail_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return

    # 请求已成功受理
    process_text = (
        f"📡 <b>换 IP 请求已成功发送！</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>原公网 IPv4:</b> <code>{old_ip or '未知'}</code>\n"
        f"• <b>服务商响应:</b> {msg}\n\n"
        f"⏳ <b>正在监听网络重新连接与新 IP...</b>\n"
        f"<i>（家宽重新拨号/分配通常需要 30~90 秒，完成后将自动发送新 IP 通知）</i>"
    )
    await query.edit_message_text(process_text, parse_mode=ParseMode.HTML)

    # 启动后台异步任务等待并探测新 IP
    asyncio.create_task(_watch_and_notify_new_ip(chat_id, old_ip, context))


async def _watch_and_notify_new_ip(chat_id: int, old_ip: Optional[str], context: ContextTypes.DEFAULT_TYPE):
    """后台异步轮询探测新 IP 并推送通知"""
    try:
        ok, new_ip, elapsed = await vps_service.watch_ip_change(old_ip=old_ip, timeout_seconds=180, poll_interval=6)

        if ok and new_ip:
            details = await vps_service.get_ip_details(new_ip)
            country = details.get("country", "未知")
            city = details.get("city", "")
            isp = details.get("isp", "未知")
            loc_str = f"{country} {city}".strip()

            success_text = (
                f"🎉 <b>VPS 公网 IP 更换成功！</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>原 IPv4:</b> <code>{old_ip or '未知'}</code>\n"
                f"• <b>新 IPv4:</b> <code>{new_ip}</code>\n"
                f"• <b>新归属:</b> {loc_str} ({isp})\n"
                f"• <b>耗时:</b> {elapsed} 秒\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ 立即体检新 IP", callback_data="menu_test")],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start")],
            ])

            await context.bot.send_message(
                chat_id=chat_id,
                text=success_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

            # 若配置了换 IP 后自动体检，则自动触发一次体检
            if settings.auto_test_on_ip_change:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚡ <i>已配置换 IP 自动体检，正在调用 xykt/IPQuality 脚本对新 IP 进行体检，请稍候约 1 分钟...</i>",
                    parse_mode=ParseMode.HTML
                )
                success_test, card_text, _ = await ipquality_runner.run_check(current_ip=new_ip)
                if success_test:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=card_text,
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ 自动体检新 IP 异常: {card_text}",
                        parse_mode=ParseMode.HTML
                    )
        else:
            timeout_text = (
                f"⚠️ <b>探测新 IP 超时 (已等待 {elapsed} 秒)</b>\n\n"
                f"当前获取到的 IP: <code>{new_ip or '无法连接'}</code>\n"
                f"可能原因：服务商换 IP 耗时较长、网络未完全恢复或换到了相同 IP。\n"
                f"您可以稍后发送 /ip 重新手动检测。"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 重新探测 IP", callback_data="menu_ip")],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start")],
            ])
            await context.bot.send_message(
                chat_id=chat_id,
                text=timeout_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.error(f"后台新 IP 探测发生未捕获异常: {e}", exc_info=True)


@authorized_only
async def change_ip_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    用户点击【取消操作】
    """
    query = update.callback_query
    await query.answer("已取消更换")

    cancel_text = (
        "✅ <b>已取消更换 IP 操作</b>\n\n"
        "VPS 网络连接未发生任何更改，业务正常运行。"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_start")]
    ])

    await query.edit_message_text(cancel_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
