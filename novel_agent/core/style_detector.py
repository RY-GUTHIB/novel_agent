"""
style_detector.py - 风格漂移检测

基于字符 4-gram Jaccard 距离，判断每章与之前 window 章的文风偏差。
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


class StyleDetector:
    """风格漂移检测器"""

    FILE_NAME = "style_drift.json"

    def __init__(self, data_dir: str, window: int = 30):
        self.data_dir = Path(data_dir)
        self.window = window
        self._history: Dict[int, float] = {}   # {chapter: drift_score}
        self._ngrams: Dict[int, set] = {}      # {chapter: 4-gram set}
        self._load()

    # ---- 序列化 ----

    def _load(self):
        fp = self.data_dir / self.FILE_NAME
        if not fp.exists():
            self._history = {}
            self._ngrams = {}
            return
        try:
            raw = json.loads(fp.read_text("utf-8"))
            self._history = {int(k): v for k, v in raw.get("history", {}).items()}
            self._ngrams = {
                int(k): set(v) for k, v in raw.get("ngrams", {}).items()
            }
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning("style_drift.json 解析失败 (%s), 重置", e)
            self._history = {}
            self._ngrams = {}

    def _save(self):
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
        raw = {
            "history": {str(k): v for k, v in self._history.items()},
            "ngrams": {str(k): list(v) for k, v in self._ngrams.items()},
        }
        fp = self.data_dir / self.FILE_NAME
        fp.write_text(json.dumps(raw, ensure_ascii=False), "utf-8")

    # ---- n-gram 提取 ----

    @staticmethod
    def _extract_ngrams(text: str, n: int = 4) -> set:
        clean = re.sub(r'===PRE_FLIGHT_CHECK===.*?(?:\n|$)', '', text)
        clean = re.sub(r'\[FS:.*?\]', '', clean)
        clean = re.sub(r'\d+', '', clean)
        clean = re.sub(r'\s+', '', clean)
        if len(clean) < n:
            return set()
        return {clean[i:i+n] for i in range(len(clean) - n + 1)}

    # ---- 核心 ----

    def add_chapter(self, chapter: int, text: str):
        ngrams = self._extract_ngrams(text)
        if not ngrams:
            self._ngrams[chapter] = set()
            self._history[chapter] = 0.0
            logger.info("章 %d 正文过短，无法计算风格漂移", chapter)
            self._save()
            return

        self._ngrams[chapter] = ngrams

        # 用最近 window 章做基准
        ref_chapters = sorted(
            [c for c in self._ngrams if c < chapter],
        )[-self.window:]

        if ref_chapters:
            ref_sets = [self._ngrams[c] for c in ref_chapters if self._ngrams[c]]
            if ref_sets:
                ref_union = set().union(*ref_sets)
                ref_inter = ref_sets[0]
                for s in ref_sets[1:]:
                    ref_inter &= s
                if ref_union:
                    jaccard = len(ngrams & ref_union) / len(ngrams | ref_union)
                    drift = 1.0 - jaccard
                    self._history[chapter] = round(drift, 4)
                    logger.info("章 %d 风格漂移指数: %.4f", chapter, drift)
                else:
                    self._history[chapter] = 0.0
            else:
                self._history[chapter] = 0.0
        else:
            self._history[chapter] = 0.0

        self._save()

    # ---- 查询 ----

    def get_drift_score(self, chapter: int) -> float:
        return self._history.get(chapter, 0.0)

    def get_latest_drift(self, n: int = 5) -> float:
        scores = list(self._history.values())
        recent = scores[-n:] if len(scores) >= n else scores
        return sum(recent) / len(recent) if recent else 0.0

    def get_drift_prompt(self) -> str:
        avg = self.get_latest_drift()
        if avg < 0.10:
            return "（风格稳定）"
        elif avg < 0.20:
            return f"⚠️ 风格轻微漂移（漂移指数 {avg:.2f}，建议审校时关注）"
        else:
            return f"🔴 风格明显漂移（漂移指数 {avg:.2f}，建议检查文风一致性）"

    def get_all_scores(self) -> Dict[int, float]:
        return dict(self._history)
