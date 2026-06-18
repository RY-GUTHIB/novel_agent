"""
managers.py - 从 MemoryManager 提取的子管理器
ItemTracker / TaskTracker / StyleManager
每个管理器独立管理各自的数据域和持久化。
"""

from dataclasses import asdict, fields
from pathlib import Path
from typing import Dict, List, Optional

from .file_utils import atomic_write_json, JsonRepositoryMixin
from .models import ItemProfile, TaskProfile, StyleProfile


class ItemTracker(JsonRepositoryMixin):
    """物品状态追踪——管理所有关键物品的归属、转移、状态"""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.items: Dict[str, ItemProfile] = {}
        self._load()

    def _load(self):
        data = self._load_json("items.json")
        for name, item_data in data.items():
            if isinstance(item_data, dict):
                self.items[name] = ItemProfile(
                    name=name,
                    type=item_data.get("type", ""),
                    description=item_data.get("description", ""),
                    first_appeared=item_data.get("first_appeared", 1),
                    first_giver=item_data.get("first_giver", ""),
                    current_holder=item_data.get("current_holder", ""),
                    subsequent_transfers=item_data.get("subsequent_transfers", []),
                    prohibited_actions=item_data.get("prohibited_actions", []),
                    status=item_data.get("status", "active"),
                    notes=item_data.get("notes", ""),
                )

    def save(self):
        data = {}
        for name, item in self.items.items():
            data[name] = {
                "type": item.type, "description": item.description,
                "first_appeared": item.first_appeared, "first_giver": item.first_giver,
                "current_holder": item.current_holder,
                "subsequent_transfers": item.subsequent_transfers,
                "prohibited_actions": item.prohibited_actions,
                "status": item.status, "notes": item.notes,
            }
        self._save_json("items.json", data)

    def add(self, item: ItemProfile):
        if item.name not in self.items:
            self.items[item.name] = item
            self.save()

    def get(self, name: str) -> Optional[ItemProfile]:
        return self.items.get(name)

    def update(self, name: str, **kwargs):
        if name not in self.items:
            self.items[name] = ItemProfile(name=name)
        item = self.items[name]
        for k, v in kwargs.items():
            if hasattr(item, k) and v:
                setattr(item, k, v)
        self.save()

    def transfer(self, item_name: str, from_holder: str, to_holder: str,
                  chapter: int, reason: str = ""):
        if item_name not in self.items:
            return
        item = self.items[item_name]
        item.current_holder = to_holder
        item.subsequent_transfers.append({
            "from": from_holder, "to": to_holder,
            "chapter": chapter, "reason": reason,
        })
        self.save()


class TaskTracker(JsonRepositoryMixin):
    """任务清单管理——追踪跨章节长线任务"""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.tasks: Dict[str, TaskProfile] = {}
        self._load()

    def _load(self):
        data = self._load_json("tasks.json")
        valid_fields = {f.name for f in fields(TaskProfile)}
        for tid, d in data.items():
            filtered = {k: v for k, v in d.items() if k in valid_fields}
            self.tasks[tid] = TaskProfile(**filtered)

    def save(self):
        data = {k: asdict(v) for k, v in self.tasks.items()}
        self._save_json("tasks.json", data)

    def get_active(self, current_chapter: int = 99999, limit: int = 5) -> List[TaskProfile]:
        active = [t for t in self.tasks.values()
                  if t.status == "active" and t.chapter_created <= current_chapter]
        active.sort(key=lambda t: t.chapter_created)
        return active[:limit]

    def add(self, task: TaskProfile):
        self.tasks[task.id] = task
        self.save()

    def complete(self, task_id: str, chapter: int):
        if task_id in self.tasks:
            self.tasks[task_id].status = "completed"
            self.tasks[task_id].chapter_completed = chapter
            self.save()

    def update_progress(self, task_id: str, progress: str):
        if task_id in self.tasks:
            self.tasks[task_id].progress = progress
            self.save()


class StyleManager(JsonRepositoryMixin):
    """风格锚点管理——全书一套风格，持久化到 style.json"""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.style: StyleProfile = StyleProfile()
        self._load()

    def _load(self):
        data = self._load_json("style.json")
        self.style = StyleProfile(
            chapter_introduced=data.get("chapter_introduced", 1),
            narrative_voice=data.get("narrative_voice", ""),
            sentence_rhythm=data.get("sentence_rhythm", ""),
            paragraph_pattern=data.get("paragraph_pattern", ""),
            rhetorical_devices=data.get("rhetorical_devices", []),
            tone_words=data.get("tone_words", []),
            forbidden_words=data.get("forbidden_words", []),
            dialect_markers=data.get("dialect_markers", ""),
            example_snippets=data.get("example_snippets", []),
            notes=data.get("notes", ""),
        )

    def save(self):
        path = self.data_dir / "style.json"
        data = {
            "chapter_introduced": self.style.chapter_introduced,
            "narrative_voice": self.style.narrative_voice,
            "sentence_rhythm": self.style.sentence_rhythm,
            "paragraph_pattern": self.style.paragraph_pattern,
            "rhetorical_devices": self.style.rhetorical_devices,
            "tone_words": self.style.tone_words,
            "forbidden_words": self.style.forbidden_words,
            "dialect_markers": self.style.dialect_markers,
            "example_snippets": self.style.example_snippets,
            "notes": self.style.notes,
        }
        atomic_write_json(path, data)

    def update(self, updates: dict) -> bool:
        changed = False
        for k, v in updates.items():
            if v and hasattr(self.style, k):
                old = getattr(self.style, k, "")
                if v != old and v not in str(old):
                    setattr(self.style, k, v)
                    changed = True
        if changed:
            self.save()
        return changed

    def get_prompt(self) -> str:
        s = self.style
        if not any([s.narrative_voice, s.sentence_rhythm, s.paragraph_pattern,
                     s.rhetorical_devices, s.tone_words, s.forbidden_words]):
            return "（未建立风格锚点，无需额外风格约束）"
        lines = ["【全文风格锚点（⚠️ 必须遵守，防止文风前后不一致）】"]
        if s.narrative_voice:
            lines.append(f"  - 叙述视角：{s.narrative_voice}")
        if s.sentence_rhythm:
            lines.append(f"  - 句节奏：{s.sentence_rhythm}")
        if s.paragraph_pattern:
            lines.append(f"  - 段落结构：{s.paragraph_pattern}")
        if s.rhetorical_devices:
            lines.append(f"  - 常用修辞：{'、'.join(s.rhetorical_devices)}")
        if s.tone_words:
            lines.append(f"  - 语气词偏好：{'、'.join(s.tone_words)}")
        if s.forbidden_words:
            lines.append(f"  - 禁用词：{'、'.join(s.forbidden_words)}")
        if s.dialect_markers:
            lines.append(f"  - 方言特征：{s.dialect_markers}")
        if s.example_snippets:
            lines.append(f"  - 风格范例（{len(s.example_snippets)} 段）：")
            for snippet in s.example_snippets[:2]:
                lines.append(f"    「{snippet[:120]}...」")
        if s.notes:
            lines.append(f"  - 备注：{s.notes}")
        return "\n".join(lines)
