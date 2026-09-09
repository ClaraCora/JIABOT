"""
家宽 VPS Telegram 机器人主程序入口
"""

import asyncio
import logging
import sys
from config import settings


def setup_logging():
    """配置日志格式与等级"""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )
    # 降低第三方网络库的冗长日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


def main():
    setup_logging()
    logger = logging.getLogger("main")
    logger.info("==========================================")
    logger.info("🤖 家宽 VPS Telegram 运维机器人正在启动...")
    logger.info("==========================================")

    # 检查基本配置
    if not settings.bot_token:
        logger.error("❌ 错误：BOT_TOKEN 为空！请在 .env 文件中配置 Telegram Bot Token。")
        logger.error("请参考 .env.example 进行配置。")
        sys.exit(1)

    if not settings.allowed_user_ids:
        logger.warning("⚠️ 警告：ALLOWED_USER_IDS 未配置任何用户 ID！所有非授权用户都将被拦截。")
    else:
        logger.info(f"✅ 已配置管理员 ID 列表 ({len(settings.allowed_user_ids)} 个): {list(settings.allowed_user_ids)}")

    if settings.vps_change_ip_command:
        logger.info(f"✅ VPS 更换 IP 方式: 本地 Shell 命令 ({settings.vps_change_ip_command})")
    elif settings.vps_change_ip_url:
        logger.info(f"✅ VPS 更换 IP 方式: HTTP API ({settings.vps_change_ip_url})")
    else:
        logger.warning("⚠️ 提示：未配置 VPS 更换 IP 的 API 或本地命令，更换 IP 功能将处于不可用状态。")

    # 延迟导入 bot 以确保配置已加载
    from bot import create_bot_application

    app = create_bot_application()

    logger.info("🚀 Telegram Bot 已进入长轮询 (Polling) 监听模式...")
    try:
        app.run_polling(drop_pending_updates=True)
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到退出信号，正在安全停止...")
    finally:
        logger.info("机器人已安全退出。")


if __name__ == "__main__":
    main()
