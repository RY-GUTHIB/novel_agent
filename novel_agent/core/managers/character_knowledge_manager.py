from pathlib import Path
from typing import Dict, List

from ..models import CharacterKnowledge
from ..file_utils import JsonRepositoryMixin


class CharacterKnowledgeManager(JsonRepositoryMixin):
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._knowledge: Dict[str, List[CharacterKnowledge]] = {}
        self._load()

    def _load(self):
        data = self._load_json("character_knowledge.json")
        self._knowledge = {}
        for char_name, items in data.items():
            if isinstance(items, list):
                self._knowledge[char_name] = [
                    CharacterKnowledge(**item) for item in items if isinstance(item, dict)
                ]

    def save(self):
        data = {k: [v.__dict__ if hasattr(v, '__dict__') else {} for v in vals] for k, vals in self._knowledge.items()}
        self._save_json("character_knowledge.json", data)

    def all(self) -> Dict[str, List[CharacterKnowledge]]:
        return self._knowledge

    def get_for_character(self, character: str) -> List[CharacterKnowledge]:
        return self._knowledge.get(character, [])

    def add(self, knowledge: CharacterKnowledge):
        if knowledge.character not in self._knowledge:
            self._knowledge[knowledge.character] = []
        existing = self._knowledge[knowledge.character]
        for k in existing:
            if k.knowledge == knowledge.knowledge:
                return
        existing.append(knowledge)
        self.save()

    def get_prompt(self, chapter: int = 0, main_character: str = "") -> str:
        if not self._knowledge:
            return "（无角色认知记录）"
        max_per_char = 50
        lines = ["【角色已知信息（写作时必须遵守——角色不能对已知信息表现惊讶）】"]
        for char_name, knowledge_list in self._knowledge.items():
            known_by_chapter = [k for k in knowledge_list if k.chapter_learned <= chapter] if chapter > 0 else knowledge_list
            if not known_by_chapter:
                continue
            limit = len(known_by_chapter) if char_name == main_character else max_per_char
            lines.append(f"\n  🧠 {char_name} 已知：")
            display = known_by_chapter[-limit:]
            for k in display:
                source_tag = f"（{k.source}，第{k.chapter_learned}章）"
                detail_tag = f" —— {k.detail}" if k.detail else ""
                lines.append(f"    - {k.knowledge}{source_tag}{detail_tag}")
            overflow = len(known_by_chapter) - limit
            if overflow > 0:
                lines.append(f"    ...等共 {len(known_by_chapter)} 条已知信息，省略 {overflow} 条")
        if len(lines) == 1:
            return "（无角色认知记录）"
        lines.append("\n⚠️ 以上角色已在正文中获知这些信息。后续章节中，角色对这些信息不应再表现出惊讶、好奇或首次获知的反应。")
        return "\n".join(lines)
