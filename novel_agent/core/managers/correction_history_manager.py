from datetime import date
from pathlib import Path
from typing import Dict, List

from ..file_utils import JsonRepositoryMixin


class CorrectionHistoryManager(JsonRepositoryMixin):
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._history: List[Dict] = []
        self._load()

    def _load(self):
        self._history = self._load_json("correction_history.json", default=[])

    def save(self):
        self._save_json("correction_history.json", self._history)

    def all(self) -> List[Dict]:
        return self._history

    def add(self, chapter: int, issue_type: str, issue: str, fix: str, source: str = "manual") -> str | None:
        if self._is_duplicate(issue, window=10):
            return None
        entry = {
            "id": f"CH_{len(self._history) + 1:03d}",
            "chapter": chapter,
            "type": issue_type,
            "issue": issue,
            "fix": fix,
            "source": source,
            "timestamp": str(date.today()),
        }
        self._history.append(entry)
        self.save()
        return entry["id"]

    def _is_duplicate(self, issue: str, window: int = 10) -> bool:
        recent = self._history[-window:]
        return any(r["issue"] == issue for r in recent)

    def get_prompt(self, chapter: int, limit: int = 10) -> str:
        recent = [c for c in self._history if c["chapter"] < chapter][-limit:]
        if not recent:
            return "（无历史修正记录）"
        lines = ["## ⚠️ 历史修正记录（阅读以避免重复错误）"]
        for c in recent:
            lines.append(f"- 第{c['chapter']}章 【{c['type']}】{c['issue']}")
            lines.append(f"  → {c['fix']}")
        return "\n".join(lines)
