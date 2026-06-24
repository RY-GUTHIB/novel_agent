"""
arc_tracker.py - 人物成长弧追踪
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ..models import ArcEvent

logger = logging.getLogger(__name__)


class ArcTracker:
    """人物成长弧事件管理器——存储 arc_events.json 并提供查询"""

    FILE_NAME = "arc_events.json"

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._events: List[ArcEvent] = []
        self._load()

    # ---- 序列化 ----

    def _load(self):
        fp = self.data_dir / self.FILE_NAME
        if not fp.exists():
            self._events = []
            return
        try:
            raw = json.loads(fp.read_text("utf-8"))
            self._events = [ArcEvent(**e) for e in raw]
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning("arc_events.json 解析失败 (%s), 重置为空", e)
            self._events = []

    def save(self):
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
        raw = [
            {
                "character": e.character,
                "chapter": e.chapter,
                "element": e.element,
                "event_type": e.event_type,
                "description": e.description,
                "new_value": e.new_value,
            }
            for e in self._events
        ]
        fp = self.data_dir / self.FILE_NAME
        fp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), "utf-8")

    # ---- 记录 ----

    def record(self, character: str, chapter: int, element: str,
               event_type: str, description: str, new_value: str = ""):
        self._events.append(ArcEvent(
            character=character, chapter=chapter,
            element=element, event_type=event_type,
            description=description, new_value=new_value,
        ))
        self.save()

    # ---- 查询 ----

    def get_character_arc(self, character: str) -> List[ArcEvent]:
        return sorted(
            [e for e in self._events if e.character == character],
            key=lambda x: x.chapter,
        )

    def get_arc_prompt(self, character: str, up_to_chapter: int = 9999) -> str:
        events = [e for e in self.get_character_arc(character)
                  if e.chapter <= up_to_chapter]
        if not events:
            return ""
        lines = [f"    {e.chapter}章 | {e.element}({e.event_type}): {e.description}"
                 + (f" → {e.new_value}" if e.new_value else "")
                 for e in events]
        return f"  {character} 成长弧:\n" + "\n".join(lines)

    def get_all_arcs_prompt(self, up_to_chapter: int = 9999) -> str:
        chars = sorted({e.character for e in self._events})
        parts = []
        for c in chars:
            p = self.get_arc_prompt(c, up_to_chapter)
            if p:
                parts.append(p)
        return "\n".join(parts)

    def check_completeness(self, character: str, up_to_chapter: int = 9999) -> Dict:
        events = [e for e in self.get_character_arc(character)
                  if e.chapter <= up_to_chapter]
        explored = {e.element for e in events}
        required = {"core_value", "core_desire", "core_fear", "flaw"}
        missing = required - explored
        return {"explored": list(explored), "missing": list(missing)}

    # ---- 批量导出 ----

    def export_all(self) -> List[Dict]:
        return [
            {
                "character": e.character,
                "chapter": e.chapter,
                "element": e.element,
                "event_type": e.event_type,
                "description": e.description,
                "new_value": e.new_value,
            }
            for e in self._events
        ]
