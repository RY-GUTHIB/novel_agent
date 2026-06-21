"""
版本管理。自动快照 + 一键回滚。
每章节每次修改前自动创建快照，保存在 .versions/ 目录下。
"""
from pathlib import Path
from datetime import datetime


class ChapterVersionManager:
    def __init__(self, project_dir: Path):
        self.versions_dir = project_dir / ".versions"
        self.versions_dir.mkdir(exist_ok=True)

    def save_snapshot(self, chapter: int, content: str) -> str:
        version_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        version_dir = self.versions_dir / f"ch{chapter:03d}" / version_id
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "chapter.md").write_text(content, encoding="utf-8")
        return version_id

    def list_versions(self, chapter: int) -> list:
        ch_dir = self.versions_dir / f"ch{chapter:03d}"
        if not ch_dir.exists():
            return []
        versions = []
        for v_dir in sorted(ch_dir.iterdir(), reverse=True):
            versions.append({
                "version": v_dir.name,
                "timestamp": v_dir.name.replace("_", " "),
                "path": v_dir / "chapter.md",
            })
        return versions

    def restore(self, chapter: int, version_id: str) -> str:
        version_path = self.versions_dir / f"ch{chapter:03d}" / version_id / "chapter.md"
        if version_path.exists():
            return version_path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"版本 {version_id} 不存在")
