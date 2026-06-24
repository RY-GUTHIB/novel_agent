from pathlib import Path
from typing import List

from ..models import SceneEvent
from ..file_utils import JsonRepositoryMixin


class SceneEventManager(JsonRepositoryMixin):
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._events: List[SceneEvent] = []
        self._load()

    def _load(self):
        data = self._load_json("scene_events.json")
        self._events = []
        if isinstance(data, list):
            from dataclasses import fields
            valid_fields = {f.name for f in fields(SceneEvent)}
            for item in data:
                if isinstance(item, dict):
                    filtered = {k: v for k, v in item.items() if k in valid_fields}
                    self._events.append(SceneEvent(**filtered))

    def save(self):
        data = [v.__dict__ if hasattr(v, '__dict__') else {} for v in self._events]
        self._save_json("scene_events.json", data)

    def all(self) -> List[SceneEvent]:
        return self._events

    def add(self, event: SceneEvent):
        self._events.append(event)
        self.save()

    def get_prompt(self, chapter: int = 0) -> str:
        if not self._events:
            return "（无场景事件记录）"
        events = self._events
        if chapter > 0:
            events = [e for e in events if e.chapter < chapter]
        if not events:
            return "（无场景事件记录）"
        lines = ["【场景事件记录（审校时用于检查事件发生地点是否正确）】"]
        recent = sorted(events, key=lambda e: e.chapter, reverse=True)[:50]
        for e in recent:
            chars = f"（{', '.join(e.characters)}）" if e.characters else ""
            lines.append(f"  第{e.chapter}章·{e.location}：{e.event}{chars}")
        return "\n".join(lines)
