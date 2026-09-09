"""
持久化数据存储模块
管理最新 IP 质量检测报告 (latest_record.json) 与 IP 变更及历史记录 (history.json)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from config import settings

logger = logging.getLogger(__name__)


class StorageManager:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or settings.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.latest_record_file = self.data_dir / "latest_record.json"
        self.history_file = self.data_dir / "history.json"

    def save_latest_record(self, record: Dict[str, Any]) -> None:
        """保存最新的 IP 质量体检报告（原子写入）"""
        try:
            temp_file = self.latest_record_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            temp_file.replace(self.latest_record_file)
            logger.info("已成功留存最新 IPQuality 记录")
        except Exception as e:
            logger.error(f"保存 latest_record.json 失败: {e}", exc_info=True)

    def get_latest_record(self) -> Optional[Dict[str, Any]]:
        """获取最后一次留存的 IP 质量体检报告"""
        if not self.latest_record_file.exists():
            return None
        try:
            with open(self.latest_record_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取 latest_record.json 失败: {e}")
            return None

    def add_history_entry(self, entry: Dict[str, Any], max_entries: int = 100) -> None:
        """追加一条历史记录（如 IP 更换或体检摘要）"""
        try:
            history = self.get_all_history()
            if "timestamp" not in entry:
                entry["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            history.insert(0, entry)
            # 保留最近的 max_entries 条记录
            history = history[:max_entries]

            temp_file = self.history_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            temp_file.replace(self.history_file)
        except Exception as e:
            logger.error(f"追加 history.json 失败: {e}", exc_info=True)

    def get_all_history(self) -> List[Dict[str, Any]]:
        """获取全部历史记录列表"""
        if not self.history_file.exists():
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"读取 history.json 失败: {e}")
            return []

    def get_recent_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近 N 条历史记录"""
        history = self.get_all_history()
        return history[:limit]


# 全局单例存储实例
storage = StorageManager()
