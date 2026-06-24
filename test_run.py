"""
novel_agent 自动化测试脚本
演示完整流程：创建项目 → 生成大纲 → 写第1章 → 审校 → 生成可视化
"""
import sys
import os

# 强制 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from pathlib import Path
import json

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import config
from novel_agent.project import create_project, get_project_paths, update_project_progress
from novel_agent.core.memory import MemoryManager, WorldSetting, CharacterProfile, LocationProfile
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.agents.planner import PlannerAgent
from novel_agent.agents.writer import WriterAgent
from novel_agent.agents.reviewer import ReviewerAgent
from novel_agent.visualizer import generate_timeline_html, generate_character_map_html, generate_world_map_html

# ============================================================
# 测试配置
# ============================================================

TEST_PROJECT = "测试小说"
TEST_GENRE = "玄幻"
TEST_STYLE = "热血"
TEST_IDEA = "一个在天桥下摆摊算命的少年，偶然捡到一枚来自上古时期的铜钱，从此能看见万物的\"气数\"，却也因此被卷入一场跨越千年的布局。"

print("=" * 60)
print("小说创作 Agent - 自动化测试（多项目版）")
print("=" * 60)

# ----------------------------------------------------------
# Step 0: 创建测试项目
# ----------------------------------------------------------
print(f"\n[0/6] 创建测试项目「{TEST_PROJECT}」...")
try:
    project_dir = create_project(TEST_PROJECT, TEST_GENRE, TEST_STYLE, TEST_IDEA)
    config.set_project(TEST_PROJECT)
    print(f"  [OK] 项目目录: {project_dir}")
except Exception as e:
    print(f"  [FAIL] 创建项目失败: {e}")
    sys.exit(1)

# ----------------------------------------------------------
# 初始化所有依赖（在 set_project 之后）
# ----------------------------------------------------------
print("\n[初始化] 创建内存管理器、连续性守卫、伏笔追踪器...")
try:
    ctx = config.get_project_context()
    memory = MemoryManager(data_dir=ctx.data_dir)
    continuity = ContinuityGuard(data_dir=ctx.data_dir)
    foreshadow = ForeshadowTracker(data_dir=ctx.data_dir)

    print("  [OK] 初始化完成")
    print(f"  data_dir: {ctx.data_dir}")
    print(f"  output_dir: {ctx.output_dir}")
except Exception as e:
    print(f"  [FAIL] 初始化失败: {e}")
    sys.exit(1)

# ----------------------------------------------------------
# Step 1: 生成大纲
# ----------------------------------------------------------
print("\n[1/6] 开始生成大纲...")
try:
    planner = PlannerAgent(memory, continuity, foreshadow, ctx=ctx)
    outline = planner.generate_outline(TEST_IDEA, TEST_GENRE, TEST_STYLE)
    if outline:
        planner.save_outline_json(outline)
        all_chapters = []
        for vol in outline.get("volumes", []):
            all_chapters.extend(vol.get("chapters", []))
        total = outline.get("meta", {}).get("total_chapters", len(all_chapters))
        print(f"  [OK] 大纲生成成功！标题: {outline.get('title', '未知')}")
        print(f"  规划章节数: {total}")
        print(f"  人物数: {len(outline.get('characters', []))}")
        print(f"  地点数: {len(outline.get('locations', []))}")

        # 更新项目进度
        update_project_progress(TEST_PROJECT, outline=outline)
    else:
        print("  [FAIL] 大纲生成失败（JSON 解析失败）")
        sys.exit(1)
except Exception as e:
    print(f"  [FAIL] 大纲生成异常: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ----------------------------------------------------------
# Step 2: 写第1章
# ----------------------------------------------------------
print("\n[2/6] 开始写第1章...")
try:
    writer = WriterAgent(memory, continuity, foreshadow, ctx=ctx, genre=TEST_GENRE, style=TEST_STYLE)

    all_chapters = []
    for vol in outline.get("volumes", []):
        all_chapters.extend(vol.get("chapters", []))
    ch_info = None
    for ch in all_chapters:
        if ch.get("chapter") == 1:
            ch_info = ch
            break

    if not ch_info:
        print("  [FAIL] 大纲中没有第1章的信息")
        sys.exit(1)

    content, settings_json = writer.write_chapter(
        chapter=ch_info.get("chapter", 1),
        title=ch_info.get("title", ""),
        summary=ch_info.get("summary", ""),
        time_tag=ch_info.get("time", ""),
        location=ch_info.get("location", ""),
        characters=ch_info.get("characters", [])
    )
    if content:
        writer.save_chapter(1, ch_info.get("title", ""), content)
        print(f"  [OK] 第1章生成成功！字数: {len(content)}")
        print(f"  预览: {content[:100]}...")

        update_project_progress(TEST_PROJECT, chapters_written=1)
    else:
        print("  [FAIL] 第1章生成失败")
        sys.exit(1)
except Exception as e:
    print(f"  [FAIL] 写第1章异常: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ----------------------------------------------------------
# Step 3: 审校第1章
# ----------------------------------------------------------
print("\n[3/6] 开始审校第1章...")
try:
    reviewer = ReviewerAgent(memory, continuity, foreshadow)
    review_result = reviewer.review_chapter(1, ch_info.get("title", ""), content)
    if review_result:
        passed = review_result.get("passed", False)
        score = review_result.get("overall_score", 0)
        print(f"  [OK] 审校完成！通过: {passed}, 评分: {score}/100")
        if not passed:
            issues = review_result.get('issues', [])
            print(f"  主要问题: {issues[:2] if issues else '无'}")
    else:
        print("  [WARN] 审校返回为空")
except Exception as e:
    print(f"  [FAIL] 审校异常: {e}")
    import traceback; traceback.print_exc()

# ----------------------------------------------------------
# Step 4: 保存数据到 JSON
# ----------------------------------------------------------
print("\n[4/6] 保存数据到 JSON...")
try:
    memory.save_all()
    continuity.save_all()
    foreshadow.save()

    print(f"  [OK] 数据保存成功")
    print(f"  人物档案: {len(memory.characters)} 个")
    print(f"  时间线事件: {len(continuity.timeline)} 个")
    print(f"  地点: {len(memory.locations)} 个")
except Exception as e:
    print(f"  [FAIL] 保存数据异常: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ----------------------------------------------------------
# Step 5: 生成三大可视化
# ----------------------------------------------------------
print("\n[5/6] 生成可视化...")
try:
    viz_files = {}

    output_dir = str(ctx.output_dir)
    timeline_path = generate_timeline_html(continuity, output_path=output_dir, project_name=TEST_PROJECT)
    viz_files["时间线"] = timeline_path

    charmap_path = generate_character_map_html(memory, output_path=output_dir, project_name=TEST_PROJECT)
    viz_files["人物关系图"] = charmap_path

    worldmap_path = generate_world_map_html(continuity, output_path=output_dir, project_name=TEST_PROJECT)
    viz_files["世界地图"] = worldmap_path

    # 伏笔总览
    fs_path = foreshadow.export_to_markdown(output_dir=output_dir)
    viz_files["伏笔总览"] = fs_path

    print(f"  [OK] 可视化生成成功！")
    for name, path in viz_files.items():
        print(f"  - {name}: {path}")
except Exception as e:
    print(f"  [FAIL] 可视化生成异常: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ----------------------------------------------------------
# Step 6: 完成
# ----------------------------------------------------------
paths = get_project_paths(TEST_PROJECT)

print("\n" + "=" * 60)
print("[6/6] 测试完成！")
print("=" * 60)
print(f"\n项目：{TEST_PROJECT}")
print(f"目录：{paths['project_dir']}")
print(f"\n输出文件:")
print(f"  - 大纲: {paths['data_dir']}/outline.json")
print(f"  - 第1章: {paths['output_dir']}/chapters/chapter_001.md")
print(f"  - 时间线: {paths['output_dir']}/timeline.html")
print(f"  - 人物关系: {paths['output_dir']}/character_map.html")
print(f"  - 世界地图: {paths['output_dir']}/world_map.html")
print(f"\n继续创作: python main.py  # 选择项目后进入交互模式")
