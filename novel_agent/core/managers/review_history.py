"""
review_history.py - 审校分数历史追踪 + 尺度漂移检测

每次审校后记录各维度分数，用于检测审校者是否在持续放松/收紧标准。
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ..file_utils import JsonRepositoryMixin

logger = logging.getLogger(__name__)


class ReviewHistoryManager(JsonRepositoryMixin):
    FILE_NAME = "review_history.json"

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._records: Dict[int, dict] = {}  # {chapter: {scores: {}, overall: X, timestamp: "..."}}
        self._load()

    def _load(self):
        raw = self._load_json(self.FILE_NAME, default={})
        self._records = {int(k): v for k, v in raw.items()}

    def save(self):
        self._save_json(self.FILE_NAME, self._records)

    def record(self, chapter: int, scores: dict, overall: float):
        """记录或覆盖（同 chapter 只保留最后一次）"""
        from datetime import date
        self._records[chapter] = {
            "scores": scores,
            "overall": overall,
            "timestamp": str(date.today()),
        }
        self.save()

    def get_scores(self, chapter: int) -> Optional[dict]:
        rc = self._records.get(chapter)
        return rc["scores"] if rc else None

    def get_overall(self, chapter: int) -> Optional[float]:
        rc = self._records.get(chapter)
        return rc["overall"] if rc else None

    def get_trend(self, window: int = 10) -> dict:
        """返回最近 window 章的趋势分析"""
        chapters = sorted(self._records.keys())
        recent = chapters[-window:] if len(chapters) >= window else chapters
        if len(recent) < 3:
            return {"mean": 0.0, "direction": "stable", "count": len(recent)}

        scores_list = [self._records[c]["overall"] for c in recent]

        # 滑动平均方向：最近 1/3 vs 最早 1/3 的均值差
        third = max(len(scores_list) // 3, 1)
        early = sum(scores_list[:third]) / third
        late = sum(scores_list[-third:]) / third
        delta = late - early

        if delta > 0.5:
            direction = "up"
        elif delta < -0.5:
            direction = "down"
        else:
            direction = "stable"

        return {
            "mean": round(sum(scores_list) / len(scores_list), 2),
            "direction": direction,
            "delta": round(delta, 2),
            "count": len(scores_list),
        }

    def get_calibration_prompt(self, chapter: int, window: int = 10) -> str:
        """生成审校 prompt 中注入的校准提示段"""
        trend = self.get_trend(window)
        if trend["count"] < 3:
            return ""

        if trend["direction"] == "up":
            return (
                f"⚠️ 校准提醒：最近 {trend['count']} 章审校评分趋势向上（+{trend['delta']}），"
                f"请特别注意不要把标准放得太松，该扣分就扣分。"
            )
        elif trend["direction"] == "down":
            return (
                f"⚠️ 校准提醒：最近 {trend['count']} 章审校评分趋势向下（{trend['delta']}），"
                f"请特别注意不要把标准收得太紧，该给分就给分。"
            )
        return ""

    def get_all_records(self) -> Dict[int, dict]:
        return dict(self._records)
