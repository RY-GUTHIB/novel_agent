from dataclasses import asdict, fields
from pathlib import Path
from typing import Dict, List

from ..file_utils import JsonRepositoryMixin
from ..models import TaskProfile


class TaskTracker(JsonRepositoryMixin):
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

    def get_active(self, current_chapter: int = 99999, limit: int = 0) -> List[TaskProfile]:
        active = [t for t in self.tasks.values()
                  if t.status == "active" and t.chapter_created <= current_chapter]
        active.sort(key=lambda t: t.chapter_created)
        return active if limit <= 0 else active[:limit]

    def add(self, task: TaskProfile):
        import uuid
        while task.id in self.tasks:
            task.id = f"{task.id}_{uuid.uuid4().hex[:4]}"
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
