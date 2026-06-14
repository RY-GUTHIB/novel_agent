"""
foreshadow.py - 伏笔/回调追踪（避免伏笔丢失）

功能：
1. 记录每章埋下的伏笔（人物、物品、预言、未解之谜）
2. 记录伏笔的兑现情况（在哪章兑现/揭露）
3. 生成本章前，自动提醒未兑现的伏笔（避免忘记回收）
4. 持久化到 data/foreshadow.json
"""

import json
import re
import config
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field


# ============ 数据结构 ============

@dataclass
class Foreshadow:
    """伏笔记录"""
    id: str                         # 唯一标识（如 "FS_001"）
    chapter_planted: int             # 埋下伏笔的章节
    type: str = "mystery"          # 类型：mystery/item/prohecy/character/event
    content: str = ""               # 伏笔内容描述
    related_characters: List[str] = field(default_factory=list)  # 涉及人物
    related_items: List[str] = field(default_factory=list)       # 涉及物品
    planted_how: str = ""           # 埋设方式（对话/场景/内心独白）
    chapter_resolved: Optional[int] = None  # 兑现/揭露章节（None表示未兑现）
    resolution: str = ""            # 兑现方式描述
    importance: int = 1             # 重要性 1-5（主线伏笔高）
    status: str = "planted"         # planted/resolved/dropped（放弃）


# ============ 主管理类 ============

class ForeshadowTracker:
    """伏笔追踪器"""

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or config.DATA_DIR)
        self.foreshadows: List[Foreshadow] = []
        self._counter = 0  # 用于生成ID
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
            json.dump([asdict(fs) for fs in self.foreshadows],
                      f, ensure_ascii=False, indent=2)

    def plant(self, chapter: int, content: str, type: str = "mystery",
              related_characters: List[str] = None,
              related_items: List[str] = None,
              planted_how: str = "",
              importance: int = 1) -> str:
        """
        埋下一个伏笔，返回伏笔ID
        """
        self._counter += 1
        fs_id = f"FS_{self._counter:03d}"
        fs = Foreshadow(
            id=fs_id,
            chapter_planted=chapter,
            type=type,
            content=content,
            related_characters=related_characters or [],
            related_items=related_items or [],
            planted_how=planted_how,
            importance=importance,
        )
        self.foreshadows.append(fs)
        self._save()
        return fs_id

    def add_manual_fs(self, chapter: int, fs_text: str, 
                      characters: List[str] = None) -> str:
        """
        手动添加伏笔（支持多种格式）
        格式1："FS：铜钱背面刻着四个小字——'窥天者死'"
        格式2："[FS: 伏笔描述]"
        格式3：纯文本 "铜钱背面刻着'窥天者死'"
        """
        # 清理格式
        fs_text = fs_text.strip()
        # 移除 [FS: ...] 或 [FS：...] 包裹
        match = re.search(r'\[FS[：:]\s*(.*?)\s*\]', fs_text)
        if match:
            fs_text = match.group(1)
        # 移除开头的 "FS：" 或 "FS:"
        fs_text = re.sub(r'^FS[：:]\s*', '', fs_text)

        return self.plant(
            chapter=chapter,
            content=fs_text,
            type="mystery",
            related_characters=characters,
            planted_how="手动记录",
            importance=2,
        )

    def resolve(self, fs_id: str, chapter: int, resolution: str):
        """兑现一个伏笔"""
        for fs in self.foreshadows:
            if fs.id == fs_id:
                fs.chapter_resolved = chapter
                fs.resolution = resolution
                fs.status = "resolved"
                self._save()
                return
        raise ValueError(f"未找到伏笔 ID: {fs_id}")

    def drop(self, fs_id: str, reason: str = ""):
        """放弃一个伏笔（如剧情调整不再需要）"""
        for fs in self.foreshadows:
            if fs.id == fs_id:
                fs.status = "dropped"
                fs.resolution = reason
                self._save()
                return

    def get_pending(self, before_chapter: int = None) -> List[Foreshadow]:
        """
        获取未兑现的伏笔
        :param before_chapter: 仅显示在此章节前埋下的伏笔
        """
        result = [fs for fs in self.foreshadows if fs.status == "planted"]
        if before_chapter is not None:
            result = [fs for fs in result if fs.chapter_planted < before_chapter]
        # 按重要性排序
        return sorted(result, key=lambda x: (-x.importance, x.chapter_planted))

    def get_for_chapter(self, chapter: int) -> List[Foreshadow]:
        """获取某章节埋下的所有伏笔"""
        return [fs for fs in self.foreshadows if fs.chapter_planted == chapter]

    def get_resolved_in_chapter(self, chapter: int) -> List[Foreshadow]:
        """获取某章节兑现的所有伏笔"""
        return [fs for fs in self.foreshadows if fs.chapter_resolved == chapter]

    def generate_foreshadow_prompt(self, chapter: int) -> str:
        """
        生成伏笔提醒（注入新章节 prompt，避免忘记回收伏笔）
        """
        pending = self.get_pending(before_chapter=chapter)
        if not pending:
            return "【伏笔追踪】当前无待回收伏笔。"

        lines = ["【⚠️ 待回收伏笔提醒（生成本章时考虑兑现）】"]
        for fs in pending[:10]:  # 最多显示10个，避免prompt过长
            char_str = f"，涉及人物：{', '.join(fs.related_characters)}" if fs.related_characters else ""
            lines.append(
                f"  [{fs.id}] 第{fs.chapter_planted}章埋下（重要度{fs.importance}）\n"
                f"    内容：{fs.content}{char_str}"
            )

        if len(pending) > 10:
            lines.append(f"  ...还有 {len(pending) - 10} 个伏笔未显示")

        return "\n".join(lines)

    def summarize(self) -> str:
        """生成伏笔总览（调试用）"""
        total = len(self.foreshadows)
        pending = len(self.get_pending())
        resolved = len([fs for fs in self.foreshadows if fs.status == "resolved"])
        dropped = len([fs for fs in self.foreshadows if fs.status == "dropped"])

        lines = [
            f"【伏笔总览】总计：{total}，已兑现：{resolved}，待回收：{pending}，已放弃：{dropped}",
            "",
            "## 待回收伏笔（按重要性排序）：",
        ]
        for fs in self.get_pending():
            lines.append(f"  {fs.id} [重要度{fs.importance}] 第{fs.chapter_planted}章：{fs.content[:50]}...")
        return "\n".join(lines)

    def export_for_viz(self) -> List[Dict]:
        """导出伏笔数据（供可视化用）"""
        return [
            {
                "id": fs.id,
                "chapter_planted": fs.chapter_planted,
                "chapter_resolved": fs.chapter_resolved,
                "type": fs.type,
                "content": fs.content,
                "status": fs.status,
                "importance": fs.importance,
                "related_characters": fs.related_characters,
            }
            for fs in self.foreshadows
        ]

    def export_to_markdown(self, output_dir: str = None) -> str:
        """
        将所有伏笔整理为 Markdown 文件，标注出处
        输出到 output/foreshadow_map.md
        """
        out_dir = Path(output_dir or config.OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)

        # 按状态分组
        planted = [fs for fs in self.foreshadows if fs.status == "planted"]
        resolved = [fs for fs in self.foreshadows if fs.status == "resolved"]
        dropped = [fs for fs in self.foreshadows if fs.status == "dropped"]

        lines = [
            "# 伏笔总览",
            "",
            f"> 共 {len(self.foreshadows)} 个伏笔 | 待回收 {len(planted)} | 已兑现 {len(resolved)} | 已放弃 {len(dropped)}",
            "",
            "---",
            "",
        ]

        # 待回收伏笔（按重要性排序）
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
            lines.append("## 待回收伏笔")
            lines.append("")
            lines.append("> 暂无待回收伏笔")
            lines.append("")

        # 已兑现伏笔
        if resolved:
            lines.append("---")
            lines.append("")
            lines.append("## 已兑现伏笔")
            lines.append("")
            for fs in sorted(resolved, key=lambda x: x.chapter_resolved or 0):
                chars = f" | 涉及人物：{', '.join(fs.related_characters)}" if fs.related_characters else ""
                lines.append(f"- **[{fs.id}]** 第{fs.chapter_planted}章埋下 → 第{fs.chapter_resolved}章兑现{chars}")
                lines.append(f"  - 内容：{fs.content}")
                lines.append(f"  - 兑现方式：{fs.resolution}")
                lines.append("")

        # 已放弃伏笔
        if dropped:
            lines.append("---")
            lines.append("")
            lines.append("## 已放弃伏笔")
            lines.append("")
            for fs in dropped:
                lines.append(f"- **[{fs.id}]** 第{fs.chapter_planted}章埋下（已放弃）")
                lines.append(f"  - 内容：{fs.content}")
                lines.append(f"  - 放弃原因：{fs.resolution}")
                lines.append("")

        # 按章节索引
        lines.append("---")
        lines.append("")
        lines.append("## 按章节索引")
        lines.append("")
        chapters = {}
        for fs in self.foreshadows:
            ch = fs.chapter_planted
            if ch not in chapters:
                chapters[ch] = []
            chapters[ch].append(fs)
        for ch in sorted(chapters.keys()):
            lines.append(f"### 第{ch}章")
            for fs in chapters[ch]:
                status_icon = {"planted": "[待回收]", "resolved": "[已兑现]", "dropped": "[已放弃]"}.get(fs.status, "")
                lines.append(f"- {status_icon} {fs.id}: {fs.content[:60]}{'...' if len(fs.content) > 60 else ''}")
            lines.append("")

        # 写入文件
        md_path = out_dir / "foreshadow_map.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return str(md_path)
