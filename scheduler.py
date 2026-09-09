"""
定时任务调度模块
基于 APScheduler 实现定时自动执行 xykt/IPQuality 体检并向管理员推送报告，以及 IP 意外变动心跳监控
"""

import asyncio
import logging
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.constants import ParseMode
from config import settings
from ipquality_runner import ipquality_runner
from storage import storage
from vps_service import vps_service

logger = logging.getLogger(__name__)


class TaskScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.bot: Optional[Bot] = None
        self._last_known_ip: Optional[str] = None

    def init_bot(self, bot: Bot):
        self.bot = bot

    def start(self):
        """配置并启动定时任务"""
        # 1. 定时质量体检任务 (每 N 小时执行一次)
        hours = max(1, settings.ipquality_cron_hours)
        self.scheduler.add_job(
            self._scheduled_quality_check,
            "interval",
            hours=hours,
            id="scheduled_ipquality",
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info(f"已注册定时 IPQuality 体检任务：每 {hours} 小时自动执行一次")

        # 2. IP 意外变动探测任务 (每 20 分钟检测一次，检测家宽是否被运营商强制重拨换 IP)
        self.scheduler.add_job(
            self._heartbeat_ip_check,
            "interval",
            minutes=20,
            id="heartbeat_ip_check",
            replace_existing=True,
            misfire_grace_time=120,
        )
        logger.info("已注册 IP 意外变动心跳监控任务：每 20 分钟探测一次")

        self.scheduler.start()

    def shutdown(self):
        """关闭调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("定时任务调度器已停止")

    async def _scheduled_quality_check(self):
        """定时体检执行函数"""
        logger.info("⏰ 触发定时 IPQuality 体检任务...")
        current_ip = await vps_service.get_current_ip()
        success, card_text, _ = await ipquality_runner.run_check(current_ip=current_ip)

        if success and self.bot:
            push_text = f"⏰ <b>【定时巡检通知】</b>\n\n{card_text}"
            await self._broadcast_to_admins(push_text)
        else:
            logger.warning(f"定时体检未成功完成: {card_text}")

    async def _heartbeat_ip_check(self):
        """心跳检查是否发生未经由 Bot 触发的 IP 变更（如运营商强制重拨）"""
        current_ip = await vps_service.get_current_ip()
        if not current_ip:
            return

        if self._last_known_ip is None:
            # 首次记录
            self._last_known_ip = current_ip
            return

        if current_ip != self._last_known_ip:
            old_ip = self._last_known_ip
            self._last_known_ip = current_ip
            logger.info(f"⚠️ 监控到公网 IP 自动变更: {old_ip} -> {current_ip}")

            storage.add_history_entry({
                "type": "ip_change",
                "old_ip": old_ip,
                "new_ip": current_ip,
                "duration_seconds": 0,
                "status": "auto_detected",
            })

            details = await vps_service.get_ip_details(current_ip)
            loc = f"{details.get('country', '')} {details.get('city', '')}".strip()

            msg = (
                f"🚨 <b>【IP 自动变更提醒】</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"系统监测到 VPS 公网 IP 发生自然变动（可能由宽带租约到期或重拨引起）：\n\n"
                f"• <b>原 IPv4:</b> <code>{old_ip}</code>\n"
                f"• <b>新 IPv4:</b> <code>{current_ip}</code>\n"
                f"• <b>新归属:</b> {loc} ({details.get('isp', '未知')})\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            await self._broadcast_to_admins(msg)

            if settings.auto_test_on_ip_change:
                # 自动对新 IP 进行体检
                await asyncio.sleep(5)
                success, card_text, _ = await ipquality_runner.run_check(current_ip=current_ip)
                if success:
                    await self._broadcast_to_admins(card_text)

    async def _broadcast_to_admins(self, text: str):
        """向所有已授权的管理员广播消息"""
        if not self.bot:
            return
        for user_id in settings.allowed_user_ids:
            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"向管理员 {user_id} 推送通知失败: {e}")


# 全局单例调度器实例
scheduler = TaskScheduler()
