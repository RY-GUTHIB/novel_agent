"""
foreshadow.py - 伏笔/回调追踪

功能：
1. 记录每章埋下的伏笔
2. 记录伏笔的兑现情况
3. 生成本章前，自动提醒未兑现的伏笔
4. 持久化到 data/foreshadow.json
"""

import json
import re
import config
from pathlib import Path
from typing import List
from dataclasses import asdict
from .models import Foreshadow


class ForeshadowTracker:
    """伏笔追踪器"""

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or config.DATA_DIR)
        self.foreshadows: List[Foreshadow] = []
        self._counter = 0
        self._load()

    def _load(self):
        path = self.data_dir / "foreshadow.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.foreshadows = [Foreshadow(**d) for d in data]
            if self.foreshadows:
                self._counter = max(int(fs.id.split("_")[1]) for fs in self.foreshadows)

    def _save(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.data_dir / "foreshadow.json", "w", encoding="utf-8") as f:
            json.dump([asdict(fs) for fs in self.foreshadows], f, ensure_ascii=False, indent=2)

    def plant(self, chapter: int, content: str, type: str = "mystery",
              related_characters: List[str] = None, related_items: List[str] = None,
              planted_how: str = "", importance: int = 1) -> str:
        self._counter += 1
        fs_id = f"FS_{self._counter:03d}"
        self.foreshadows.append(Foreshadow(
            id=fs_id, chapter_planted=chapter, type=type, content=content,
            related_characters=related_characters or [], related_items=related_items or [],
            planted_how=planted_how, importance=importance,
        ))
        self._save()
        return fs_id

    def add_manual_fs(self, chapter: int, fs_text: str, characters: List[str] = None) -> str:
        fs_text = fs_text.strip()
        match = re.search(r'\[FS[：:]\s*(.*?)\s*\]', fs_text)
        if match:
            fs_text = match.group(1)
        fs_text = re.sub(r'^FS[：:]\s*', '', fs_text)
        return self.plant(chapter=chapter, content=fs_text, type="mystery",
                          related_characters=characters, planted_how="手动记录", importance=2)

    def resolve(self, fs_id: str, chapter: int, resolution: str):
        for fs in self.foreshadows:
            if fs.id == fs_id:
                fs.chapter_resolved = chapter
                fs.resolution = resolution
                fs.status = "resolved"
                self._save()
                return
        raise ValueError(f"未找到伏笔 ID: {fs_id}")

    def drop(self, fs_id: str, reason: str = ""):
        for fs in self.foreshadows:
            if fs.id == fs_id:
                fs.status = "dropped"
                fs.resolution = reason
                self._save()
                return

    def auto_resolve(self, content: str, chapter: int) -> int:
        """自动检测正文中是否兑现了待回收伏笔（仅依赖显式标记，不调 LLM）
        
        检测方式：正文中的 [FS_RESOLVE: FS_xxx] 显式标记
        
        :return: 成功回收的伏笔数量
        """
        # 显式标记 [FS_RESOLVE: FS_xxx] 或 [FS_RESOLVE：FS_xxx]
        resolve_matches = re.findall(r'\[FS_RESOLVE[：:]\s*(FS_\d+)\s*\]', content)
        resolved_ids = set(resolve_matches)
        
        # 执行回收
        count = 0
        for fs_id in resolved_ids:
            try:
                self.resolve(fs_id, chapter, f"第{chapter}章自动回收")
                count += 1
            except ValueError:
                pass
        
        if count:
            self._save()
        return count

    def get_pending(self, before_chapter: int = None) -> List[Foreshadow]:
        result = [fs for fs in self.foreshadows if fs.status == "planted"]
        if before_chapter is not None:
            result = [fs for fs in result if fs.chapter_planted < before_chapter]
        return sorted(result, key=lambda x: (-x.importance, x.chapter_planted))

    def get_for_chapter(self, chapter: int) -> List[Foreshadow]:
        return [fs for fs in self.foreshadows if fs.chapter_planted == chapter]

    def get_resolved_in_chapter(self, chapter: int) -> List[Foreshadow]:
        return [fs for fs in self.foreshadows if fs.chapter_resolved == chapter]

    def generate_foreshadow_prompt(self, chapter: int) -> str:
        pending = self.get_pending(before_chapter=chapter)
        if not pending:
            return "【伏笔追踪】当前无待回收伏笔。"
        lines = ["【⚠️ 待回收伏笔提醒（生成本章时考虑兑现）】"]
        for fs in pending[:10]:
            char_str = f"，涉及人物：{', '.join(fs.related_characters)}" if fs.related_characters else ""
            lines.append(
                f"  [{fs.id}] 第{fs.chapter_planted}章埋下（重要度{fs.importance}）\n"
                f"    内容：{fs.content}{char_str}"
            )
        if len(pending) > 10:
            lines.append(f"  ...还有 {len(pending) - 10} 个伏笔未显示")
        return "\n".join(lines)

    def summarize(self) -> str:
        total = len(self.foreshadows)
        pending = len(self.get_pending())
        resolved = len([fs for fs in self.foreshadows if fs.status == "resolved"])
        dropped = len([fs for fs in self.foreshadows if fs.status == "dropped"])
        lines = [
            f"【伏笔总览】总计：{total}，已兑现：{resolved}，待回收：{pending}，已放弃：{dropped}",
            "", "## 待回收伏笔（按重要性排序）：",
        ]
        for fs in self.get_pending():
            lines.append(f"  {fs.id} [重要度{fs.importance}] 第{fs.chapter_planted}章：{fs.content[:50]}...")
        return "\n".join(lines)

    def export_for_viz(self) -> List[dict]:
        return [
            {"id": fs.id, "chapter_planted": fs.chapter_planted,
             "chapter_resolved": fs.chapter_resolved, "type": fs.type,
             "content": fs.content, "status": fs.status, "importance": fs.importance,
             "related_characters": fs.related_characters}
            for fs in self.foreshadows
        ]

    def export_to_markdown(self, output_dir: str = None) -> str:
        out_dir = Path(output_dir or config.OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)

        planted = [fs for fs in self.foreshadows if fs.status == "planted"]
        resolved = [fs for fs in self.foreshadows if fs.status == "resolved"]
        dropped = [fs for fs in self.foreshadows if fs.status == "dropped"]

        lines = [
            "# 伏笔总览", "",
            f"> 共 {len(self.foreshadows)} 个伏笔 | 待回收 {len(planted)} | 已兑现 {len(resolved)} | 已放弃 {len(dropped)}",
            "", "---", "",
        ]

        if planted:
            lines.append("## 待回收伏笔（按重要性排序）")
            lines.append("")
            for fs in sorted(planted, key=lambda x: (-x.importance, x.chapter_planted)):
                chars = f" | 涉及人物：{', '.join(fs.related_characters)}" if fs.related_characters else ""
                how = f" | 埋设方式：{fs.planted_how}" if fs.planted_how else ""
                items = f" | 涉及物品：{', '.join(fs.related_items)}" if fs.related_items else ""
                lines.append(f"- **[{fs.id}]** 第{fs.chapter_planted}章埋下（重要度 {fs.importance}）{chars}{items}{how}")
                lines.append(f"  - 内容：{fs.content}")
                lines.append("")
        else:
            lines.extend(["## 待回收伏笔", "", "> 暂无待回收伏笔", ""])

        if resolved:
            lines.extend(["---", "", "## 已兑现伏笔", ""])
            for fs in sorted(resolved, key=lambda x: x.chapter_resolved or 0):
                chars = f" | 涉及人物：{', '.join(fs.related_characters)}" if fs.related_characters else ""
                lines.append(f"- **[{fs.id}]** 第{fs.chapter_planted}章埋下 → 第{fs.chapter_resolved}章兑现{chars}")
                lines.append(f"  - 内容：{fs.content}")
                lines.append(f"  - 兑现方式：{fs.resolution}")
                lines.append("")

        if dropped:
            lines.extend(["---", "", "## 已放弃伏笔", ""])
            for fs in dropped:
                lines.append(f"- **[{fs.id}]** 第{fs.chapter_planted}章埋下（已放弃）")
                lines.append(f"  - 内容：{fs.content}")
                lines.append(f"  - 放弃原因：{fs.resolution}")
                lines.append("")

        # 按章节索引
        lines.extend(["---", "", "## 按章节索引", ""])
        chapters = {}
        for fs in self.foreshadows:
            chapters.setdefault(fs.chapter_planted, []).append(fs)
        for ch in sorted(chapters.keys()):
            lines.append(f"### 第{ch}章")
            for fs in chapters[ch]:
                status_icon = {"planted": "[待回收]", "resolved": "[已兑现]", "dropped": "[已放弃]"}.get(fs.status, "")
                lines.append(f"- {status_icon} {fs.id}: {fs.content[:60]}{'...' if len(fs.content) > 60 else ''}")
            lines.append("")

        md_path = out_dir / "foreshadow_map.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return str(md_path)
