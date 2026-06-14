"""
novel_agent 快速验证脚本（不使用项目系统，验证核心逻辑）
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import config
# 使用默认路径（data/ 和 output/），不走项目系统
from memory import MemoryManager, CharacterProfile, LocationProfile
from continuity import ContinuityGuard
from foreshadow import ForeshadowTracker
from planner_agent import PlannerAgent
from writer_agent import WriterAgent
from reviewer_agent import ReviewerAgent
from visualizer import generate_timeline_html, generate_character_map_html, generate_world_map_html

TEST_GENRE = "玄幻"
TEST_STYLE = "热血"
TEST_IDEA = "一个在天桥下摆摊算命的少年，偶然捡到一枚来自上古时期的铜钱，从此能看见万物的\"气数\"，却也因此被卷入一场跨越千年的布局。"

print("=" * 60)
print("小说创作 Agent - 核心逻辑验证")
print("=" * 60)

print(f"\ndata_dir: {config.DATA_DIR}")
print(f"output_dir: {config.OUTPUT_DIR}")

# 初始化
print("\n[初始化]...")
memory = MemoryManager()
continuity = ContinuityGuard()
foreshadow = ForeshadowTracker()
print("  [OK]")

# Step 1: 生成大纲
print("\n[1/5] 生成大纲...")
planner = PlannerAgent(memory, continuity, foreshadow)
outline = planner.generate_outline(TEST_IDEA, TEST_GENRE, TEST_STYLE)
planner.save_outline_json(outline)
print(f"  [OK] 标题: {outline.get('title', '未知')}")
print(f"  章节: {len(outline.get('chapter_plan', []))}  人物: {len(outline.get('characters', []))}")

# Step 2: 写第1章
print("\n[2/5] 写第1章...")
writer = WriterAgent(memory, continuity, foreshadow, genre=TEST_GENRE, style=TEST_STYLE)
ch_info = next((c for c in outline.get("chapter_plan", []) if c.get("chapter") == 1), None)
content = writer.write_chapter(
    chapter=1,
    title=ch_info.get("title", ""),
    summary=ch_info.get("summary", ""),
    time_tag=ch_info.get("time_tag", ""),
    location=ch_info.get("location", ""),
    characters=ch_info.get("characters", []),
)
writer.save_chapter(1, ch_info.get("title", ""), content)
print(f"  [OK] 字数: {len(content)}")

# Step 3: 审校
print("\n[3/5] 审校...")
reviewer = ReviewerAgent(memory, continuity, foreshadow)
report = reviewer.review_chapter(1, ch_info.get("title", ""), content)
reviewer.save_review_report(1, report)
print(f"  [OK] 评分: {report.get('overall_score', 0)} 通过: {report.get('passed', False)}")

# Step 4: 保存
print("\n[4/5] 保存数据...")
memory.save_all()
continuity.save_all()
foreshadow._save()
foreshadow.export_to_markdown()
print("  [OK]")

# Step 5: 可视化
print("\n[5/5] 生成可视化...")
generate_timeline_html(continuity)
generate_character_map_html(memory)
generate_world_map_html(continuity)
print("  [OK]")

print("\n" + "=" * 60)
print("验证完成！核心逻辑正常。")
print("交互式项目系统请手动运行：python main.py")
print("=" * 60)
