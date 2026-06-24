from pathlib import Path
from typing import Dict, Optional

from ..models import LocationProfile
from ..file_utils import JsonRepositoryMixin


class LocationManager(JsonRepositoryMixin):
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._locations: Dict[str, LocationProfile] = {}
        self._load()

    def _load(self):
        data = self._load_json("locations.json")
        for name, d in data.items():
            self._locations[name] = LocationProfile(**d)

    def save(self):
        data = {k: v.__dict__ if hasattr(v, '__dict__') else {} for k, v in self._locations.items()}
        self._save_json("locations.json", data)

    def all(self) -> Dict[str, LocationProfile]:
        return self._locations

    def get(self, name: str) -> Optional[LocationProfile]:
        return self._locations.get(name)

    def add(self, profile: LocationProfile):
        self._locations[profile.name] = profile

    def get_prompt(self, name: str) -> str:
        if name not in self._locations:
            return ""
        loc = self._locations[name]
        return f"【地点：{loc.name}】\n类型：{loc.type}\n描述：{loc.description}\n相邻地点：{', '.join(loc.connected_to)}"
