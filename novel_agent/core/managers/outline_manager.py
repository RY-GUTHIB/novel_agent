import re
from pathlib import Path

from ..file_utils import JsonRepositoryMixin, parse_chinese_number
import config as _cfg


class OutlineManager(JsonRepositoryMixin):
    _CHAPTER_DAY_RE = re.compile(r'第\s*([\d零一二三四五六七八九十百千]+)\s*天')

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._outline: dict = {}
        self._chapter_days: dict = {}
        self._load()

    def _load(self):
        self._outline = self._load_json("outline.json", default={})
        self._rebuild_chapter_days()

    def get(self) -> dict:
        return self._outline

    def set(self, outline: dict):
        self._outline = outline
        self._rebuild_chapter_days()

    def rebuild_chapter_days(self, outline: dict = None):
        self._rebuild_chapter_days(outline)

    def _rebuild_chapter_days(self, outline: dict = None):
        self._chapter_days = {}
        source = outline if outline is not None else self._outline
        volumes = source.get("volumes", [])
        all_chapters = []
        for vol in volumes:
            all_chapters.extend(vol.get("chapters", []))
        if not all_chapters:
            all_chapters = source.get("chapter_plan", [])

        prev_day = 0
        for ch_data in all_chapters:
            ch = ch_data.get("chapter", 0)
            time_tag = ch_data.get("time", f"第{ch}章")
            m = self._CHAPTER_DAY_RE.search(time_tag)
            if m:
                raw = parse_chinese_number(m.group(1))
                if raw and raw > prev_day:
                    self._chapter_days[ch] = raw
                    prev_day = raw
                elif raw and raw <= prev_day:
                    self._chapter_days[ch] = prev_day + 1
                    prev_day = prev_day + 1

    def get_day_gap(self, chapter: int) -> int:
        if chapter > 1 and chapter in self._chapter_days and (chapter - 1) in self._chapter_days:
            return self._chapter_days[chapter] - self._chapter_days[chapter - 1]
        return 0

    def get_chapter_day(self, chapter: int) -> int:
        return self._chapter_days.get(chapter, 0)

    def backfill_summary(self, chapter: int, summary: str):
        for ch in self._get_plan():
            if ch.get("chapter") == chapter:
                ch["summary"] = summary
                break
        self._save()

    def _get_plan(self) -> list:
        if "volumes" in self._outline:
            chapters = []
            for vol in self._outline.get("volumes", []):
                chapters.extend(vol.get("chapters", vol.get("chapter_plan", [])))
            if chapters:
                return chapters
        return self._outline.get("chapter_plan", [])

    def _save(self):
        self._save_json("outline.json", self._outline)

    def get_outline_context_prompt(self, chapter: int) -> str:
        if not self._outline:
            return "（无大纲数据）"
        volumes = self._outline.get("volumes", [])
        if not volumes:
            return "（无大纲数据）"

        all_chapters = []
        for vol in volumes:
            vol_title = vol.get("title", "")
            for ch in vol.get("chapters", []):
                all_chapters.append({
                    "chapter": ch.get("chapter"),
                    "title": ch.get("title", ""),
                    "summary": ch.get("summary", ""),
                    "volume": vol_title,
                })

        if not all_chapters:
            return "（大纲无章节数据）"

        current_idx = -1
        for i, ch in enumerate(all_chapters):
            if ch["chapter"] == chapter:
                current_idx = i
                break
        if current_idx == -1:
            return "（当前章不在大纲中）"

        start = max(0, current_idx - _cfg.OUTLINE_WINDOW_BEFORE)
        end = min(len(all_chapters), current_idx + _cfg.OUTLINE_WINDOW_AFTER + 1)
        window = all_chapters[start:end]

        lines = ["【大纲上下文（写作时必须参考，确保不偏离整体走向）】"]
        lines.append(f"当前位置：第{chapter}章，大纲窗口显示第{window[0]['chapter']}章 ～ 第{window[-1]['chapter']}章\n")

        prev_vol = None
        for ch in window:
            if ch["volume"] != prev_vol:
                lines.append(f"—— 第{ch['volume']} ——")
                prev_vol = ch["volume"]
            prefix = "▶ " if ch["chapter"] == chapter else "   "
            lines.append(f"{prefix}第{ch['chapter']}章《{ch['title']}》：{ch['summary']}")

        return "\n".join(lines)
