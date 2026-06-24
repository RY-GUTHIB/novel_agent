from dataclasses import fields
from pathlib import Path
from typing import Dict

from ..models import SectFaction
from ..file_utils import JsonRepositoryMixin


class SectFactionManager(JsonRepositoryMixin):
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._factions: Dict[str, SectFaction] = {}
        self._load()

    def _load(self):
        data = self._load_json("sect_factions.json")
        if isinstance(data, list):
            data = {}
        self._factions = {}
        valid_fields = {f.name for f in fields(SectFaction)}
        for name, d in data.items():
            if isinstance(d, dict):
                filtered = {k: v for k, v in d.items() if k in valid_fields}
                self._factions[name] = SectFaction(**filtered)

    def save(self):
        data = {k: v.__dict__ if hasattr(v, '__dict__') else {} for k, v in self._factions.items()}
        self._save_json("sect_factions.json", data)

    def all(self) -> Dict[str, SectFaction]:
        return self._factions

    def get(self, name: str):
        return self._factions.get(name)

    def add(self, faction: SectFaction):
        self._factions[faction.name] = faction
        self.save()

    def update(self, name: str, **kwargs):
        if name not in self._factions:
            return
        faction = self._factions[name]
        for k, v in kwargs.items():
            if hasattr(faction, k):
                if isinstance(getattr(faction, k), list) and isinstance(v, list):
                    existing = getattr(faction, k)
                    for item in v:
                        if item not in existing:
                            existing.append(item)
                elif v:
                    setattr(faction, k, v)
        self.save()

    def get_prompt(self) -> str:
        if not self._factions:
            return "（无势力/宗派记录）"
        lines = ["【势力/宗派档案】"]
        for name, f in self._factions.items():
            lines.append(f"\n  🏛️ {name}（{f.type}）")
            if f.description:
                lines.append(f"    描述：{f.description}")
            if f.strength:
                lines.append(f"    实力：{f.strength}")
            if f.hierarchy:
                lines.append(f"    层级：{' → '.join(f.hierarchy)}")
            if f.key_members:
                lines.append(f"    核心成员：{', '.join(f.key_members)}")
            if f.allies:
                lines.append(f"    盟友：{', '.join(f.allies)}")
            if f.enemies:
                lines.append(f"    敌对：{', '.join(f.enemies)}")
            if f.location:
                lines.append(f"    所在地：{f.location}")
            if f.rules:
                lines.append(f"    门规：{'；'.join(f.rules)}")
        return "\n".join(lines)
