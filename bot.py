"""
Telegram 机器人核心构建与分发模块
负责注册全部命令处理器、文本按钮监听器、内联回调处理器及错误捕获
"""

import logging
from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from config import settings
from handlers.common import (
    help_handler,
    history_handler,
    start_handler,
)
from handlers.ip_handler import (
    change_ip_cancel_handler,
    change_ip_confirm_handler,
    change_ip_prompt_handler,
    ip_query_handler,
)
from handlers.quality_handler import (
    quality_export_raw_handler,
    quality_report_handler,
    quality_test_handler,
)

from scheduler import scheduler

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """全局异常处理器"""
    logger.error(f"处理 Update 时发生未捕获异常: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                f"⚠️ 系统遇到内部错误：<code>{str(context.error)}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass


async def post_init(application: Application) -> None:
    """Bot 初始化后的钩子：自动注册 Telegram 快捷命令列表并启动后台定时调度器"""
    commands = [
        BotCommand("start", "唤出主控面板与常驻快捷键盘"),
        BotCommand("ip", "查询 VPS 当前公网 IPv4 与位置"),
        BotCommand("change_ip", "更换 VPS IP (带二次安全确认)"),
        BotCommand("quality", "查看最后一次留存的质量报告 (秒出)"),
        BotCommand("test", "主动执行 IP 质量体检 (实时跑脚本)"),
        BotCommand("check", "主动执行 IP 质量体检 (实时跑脚本)"),
        BotCommand("history", "查看历史 IP 与体检记录"),
        BotCommand("help", "查看使用帮助说明"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("已成功向 Telegram 注册 Bot 指令菜单列表")
    except Exception as e:
        logger.warning(f"向 Telegram 注册 Bot 指令菜单失败: {e}")

    # 在运行中的事件循环中启动定时调度器
    scheduler.init_bot(application.bot)
    scheduler.start()


async def post_shutdown(application: Application) -> None:
    """Bot 关闭时的清理钩子"""
    scheduler.shutdown()


def create_bot_application() -> Application:
    """构建并配置 Telegram Application 实例"""
    if not settings.bot_token:
        raise ValueError("BOT_TOKEN 未配置，请在 .env 文件中设置！")

    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # 1. 注册 Slash 指令处理器
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("menu", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("ip", ip_query_handler))
    app.add_handler(CommandHandler("change_ip", change_ip_prompt_handler))
    app.add_handler(CommandHandler(["quality", "report", "last"], quality_report_handler))
    app.add_handler(CommandHandler(["test", "check", "ipquality", "testip"], quality_test_handler))
    app.add_handler(CommandHandler("history", history_handler))

    # 2. 注册底部常驻 ReplyKeyboard 文本按钮匹配处理器
    app.add_handler(MessageHandler(filters.Regex("^🌐 当前IP$"), ip_query_handler))
    app.add_handler(MessageHandler(filters.Regex("^🔄 更换IP$"), change_ip_prompt_handler))
    app.add_handler(MessageHandler(filters.Regex("^📊 质量报告$"), quality_report_handler))
    app.add_handler(MessageHandler(filters.Regex("^⚡ 立即测质$"), quality_test_handler))
    app.add_handler(MessageHandler(filters.Regex("^📜 历史记录$"), history_handler))
    app.add_handler(MessageHandler(filters.Regex("^❓ 帮助说明$"), help_handler))

    # 3. 注册内联 InlineKeyboard 回调查询处理器
    app.add_handler(CallbackQueryHandler(start_handler, pattern="^menu_start$"))
    app.add_handler(CallbackQueryHandler(ip_query_handler, pattern="^menu_ip$"))
    app.add_handler(CallbackQueryHandler(change_ip_prompt_handler, pattern="^menu_change_ip$"))
    app.add_handler(CallbackQueryHandler(change_ip_confirm_handler, pattern="^confirm_change_ip$"))
    app.add_handler(CallbackQueryHandler(change_ip_cancel_handler, pattern="^cancel_change_ip$"))
    app.add_handler(CallbackQueryHandler(quality_report_handler, pattern="^menu_quality$"))
    app.add_handler(CallbackQueryHandler(quality_test_handler, pattern="^menu_test$"))
    app.add_handler(CallbackQueryHandler(history_handler, pattern="^menu_history$"))
    app.add_handler(CallbackQueryHandler(help_handler, pattern="^menu_help$"))
    app.add_handler(CallbackQueryHandler(quality_export_raw_handler, pattern="^export_raw_quality$"))

    # 4. 注册全局异常处理器
    app.add_error_handler(error_handler)

    return app
