from pathlib import Path
from typing import Dict

from ..models import WorldSetting
from ..file_utils import JsonRepositoryMixin


class WorldSettingManager(JsonRepositoryMixin):
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._settings: Dict[str, WorldSetting] = {}
        self._load()

    def _load(self):
        data = self._load_json("world_settings.json")
        for key, d in data.items():
            self._settings[key] = WorldSetting(**d)

    def save(self):
        data = {k: v.__dict__ if hasattr(v, '__dict__') else {} for k, v in self._settings.items()}
        self._save_json("world_settings.json", data)

    def all(self) -> Dict[str, WorldSetting]:
        return self._settings

    def get(self, key: str):
        return self._settings.get(key)

    def add(self, setting: WorldSetting):
        self._settings[setting.key] = setting

    def get_prompt(self, locations_manager=None) -> str:
        lines = ["【世界观设定】"]
        for key, s in self._settings.items():
            lines.append(f"- {key}：{s.value}")
        if locations_manager:
            locs = locations_manager.all()
            if locs:
                lines.append("\n【地点档案】")
                for name, loc in locs.items():
                    desc = loc.description[:200] + "…" if len(loc.description) > 200 else loc.description
                    lines.append(f"- {name}（{loc.type}）：{desc}")
        return "\n".join(lines)
