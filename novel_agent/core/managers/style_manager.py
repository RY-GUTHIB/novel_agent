from pathlib import Path

from ..file_utils import atomic_write_json, JsonRepositoryMixin
from ..models import StyleProfile


class StyleManager(JsonRepositoryMixin):
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
            for snippet in s.example_snippets[:5]:
                lines.append(f"    「{snippet[:300]}...」")
        if s.notes:
            lines.append(f"  - 备注：{s.notes}")
        return "\n".join(lines)
