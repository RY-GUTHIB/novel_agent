from pathlib import Path
from typing import Dict, Optional

from ..file_utils import JsonRepositoryMixin
from ..models import ItemProfile


class ItemTracker(JsonRepositoryMixin):
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
