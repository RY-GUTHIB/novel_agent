"""
commands.py - CLI 命令实现

从 main.py 中提取的所有命令逻辑，与 CLI 入口解耦。
"""

import glob
import json
import re
import sys
from collections import namedtuple
from pathlib import Path


# 服务集合：所有 init_services 返回的具名元组，可按名称或位置访问
_Services = namedtuple("Services", ["memory", "continuity", "foreshadow", "rag"])

import config
from novel_agent.project import (
    list_projects, load_project_config, save_project_config,
    create_project, update_project_progress, NOVEL_TYPES, NOVEL_STYLES,
)
from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.core.models import ItemProfile
from novel_agent.core.spacetime_guard import SpacetimeGuard
from novel_agent.core.logic_guard import LogicGuard
from novel_agent.agents.planner import PlannerAgent
from novel_agent.agents.writer import WriterAgent
from novel_agent.agents.reviewer import ReviewerAgent
from novel_agent.visualizer import generate_all_visualizations
from novel_agent.llm.client import check_api_key
from novel_agent.core.file_utils import atomic_write_text


# =========== 项目管理 ===========

_CURRENT_PROJECT_FILE = config.PROJECTS_ROOT / ".current_project"


def get_current_project_name():
    if _CURRENT_PROJECT_FILE.exists():
        name = _CURRENT_PROJECT_FILE.read_text(encoding="utf-8").strip()
        if (config.PROJECTS_ROOT / name / "config.json").exists():
            return name
    return None


def set_current_project(name: str):
    atomic_write_text(_CURRENT_PROJECT_FILE, name)


def select_project() -> str:
    projects = list_projects()
    if not projects:
        print("\n📝 还没有小说项目，来创建一个吧！\n")
        return create_new_project()

    last_project = get_current_project_name()
    print("\n📚 你的小说项目：")
    print("-" * 60)
    for i, p in enumerate(projects, 1):
        marker = " ← 上次" if p["name"] == last_project else ""
        print(f"  {i}. 《{p['name']}》  类型：{p['type']}  风格：{p['style']}  已写：{p['chapters']}章{marker}")
    print(f"  0. 新建小说项目")
    print("-" * 60)

    while True:
        choice = input("\n请选择（输入编号）：").strip()
        if choice == "0":
            return create_new_project()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(projects):
                name = projects[idx]["name"]
                set_current_project(name)
                return name
        except (ValueError, IndexError):
            pass
        print("❌ 无效选择，请重新输入")


def create_new_project() -> str:
    print("\n" + "=" * 50)
    print("  📝 新建小说项目")
    print("=" * 50)

    name = _input_project_name()
    novel_type = _input_choice("小说类型", NOVEL_TYPES)
    style = _input_choice("文风", NOVEL_STYLES)
    concept = _input_concept()

    project_dir = create_project(name, novel_type, style, concept)
    set_current_project(name)

    print(f"\n✅ 项目「{name}」已创建！")

    # 创建项目 MEMORY.md
    ctx = config.set_project(name)
    _create_project_memory(name, str(ctx.data_dir))
    print(f"   类型：{novel_type} | 风格：{style}")
    print(f"   目录：{project_dir}")

    gen_outline = input("\n🤖 是否立即生成大纲？(Y/n)：").strip().lower()
    if gen_outline != "n":
        config.set_project(name)
        memory, continuity, foreshadow, rag = init_services()
        check_api_key()
        generate_outline(memory, continuity, foreshadow, name, novel_type, style, concept)

    return name


def _input_project_name() -> str:
    while True:
        name = input("\n📖 小说名称：").strip()
        if not name:
            print("❌ 名称不能为空")
            continue
        if (config.PROJECTS_ROOT / name).exists():
            overwrite = input(f"⚠️  项目「{name}」已存在，覆盖？(y/N)：").strip().lower()
            if overwrite != "y":
                continue
        return name


def _input_choice(label: str, options: list) -> str:
    print(f"\n📂 {label}：")
    for i, t in enumerate(options, 1):
        print(f"  {i}. {t}")
    choice = input("请选择（输入编号，默认1）：").strip()
    try:
        result = options[int(choice) - 1] if choice else options[0]
    except (ValueError, IndexError):
        result = options[0]
    if result == "其他":
        custom = input("自定义类型：").strip()
        if custom:
            result = custom
    return result


def _input_concept(retries: int = 3) -> str:
    print(f"\n💡 说说你的总体构思（可以是一句话，也可以是几段描述）：")
    print("   （输入空行结束）")
    lines = []
    while True:
        line = input("   ")
        if not line:
            break
        lines.append(line)
    concept = "\n".join(lines)
    if concept.strip():
        return concept
    if retries > 0:
        print(f"❌ 构思不能为空，还有 {retries} 次机会")
        return _input_concept(retries - 1)
    print("❌ 已耗尽重试次数")
    return "（空构思）"


# =========== 初始化 ===========

def init_services(ctx: config.ProjectContext = None):
    """初始化所有服务。传 ProjectContext 显式指定项目路径，否则从 config.get_project_context() 获取。"""
    from novel_agent.core.rag import RAGStore
    if ctx is None:
        ctx = config.get_project_context()
        if ctx is None:
            raise RuntimeError("init_services: 未提供 ProjectContext 且未设置当前项目")
    return _Services(
        memory=MemoryManager(data_dir=ctx.data_dir),
        continuity=ContinuityGuard(data_dir=ctx.data_dir,
                                   enable_continuity_check=config.ENABLE_CONTINUITY_CHECK),
        foreshadow=ForeshadowTracker(data_dir=ctx.data_dir),
        rag=RAGStore(persist_dir=str(ctx.data_dir),
                     top_k=config.RAG_TOP_K,
                     chunk_size=config.RAG_CHUNK_SIZE),
    )


def generate_outline(memory, continuity, foreshadow, project_name, genre, style, concept, ctx=None, gui_mode=False):
    print("\n🤖 正在调用 LLM 生成大纲，请稍候（约1-2分钟）...")
    ctx = ctx or config.get_project_context()
    planner = PlannerAgent(memory, continuity, foreshadow, ctx=ctx)
    try:
        outline = planner.generate_outline(concept, genre=genre, style=style)
        planner.save_outline_json(outline)

        # 初始化物品状态追踪（方案1+2+5：从大纲中提取 key_items）
        key_items = outline.get("key_items", [])
        for item_data in key_items:
            if isinstance(item_data, dict) and item_data.get("item_name"):
                memory.add_item(ItemProfile(
                    name=item_data["item_name"],
                    type=item_data.get("type", ""),
                    description=item_data.get("purpose", item_data.get("description", "")),
                    first_appeared=item_data.get("first_chapter", item_data.get("first_appeared", 1)),
                    first_giver=item_data.get("giver", item_data.get("first_giver", "")),
                    current_holder=item_data.get("receiver", item_data.get("current_holder", "")),
                    prohibited_actions=item_data.get("prohibited_actions",
                        ["give_again_by_other", "duplicate"]),
                    status=item_data.get("status", "active"),
                ))
        if key_items:
            print(f"  📦 初始化 {len(key_items)} 个关键物品状态追踪")

        title = outline.get("meta", {}).get("title", outline.get("title", project_name))
        update_project_progress(project_name, outline=outline, chapters_written=0)

        if title != project_name and not gui_mode:
            print(f"\n💡 LLM 建议标题：「{title}」，当前项目名：「{project_name}」")
            try:
                rename = input("   要把项目名改为 LLM 建议的标题吗？(y/N)：").strip().lower()
            except EOFError:
                rename = "n"
            if rename == "y":
                old_dir = config.PROJECTS_ROOT / project_name
                new_dir = config.PROJECTS_ROOT / title
                if not new_dir.exists():
                    old_dir.rename(new_dir)
                    set_current_project(title)
                    config.set_project(title)
                    memory, continuity, foreshadow, _ = init_services()
                    project_name = title
                    print(f"   ✅ 已重命名为「{title}」")

        # 统计章节数（兼容 volumes 格式和新旧字段名）
        chapter_count = len(_get_chapter_plan(outline))
        if chapter_count == 0 and 'volumes' in outline:
            chapter_count = sum(len(v.get('chapters', v.get('chapter_plan', []))) for v in outline['volumes'])
        vol_count = len(outline.get('volumes', []))
        vol_info = f"（{vol_count}卷）" if vol_count else ""

        print(f"\n✅ 大纲生成完成！")
        print(f"   标题：{title}")
        print(f"   人物：{len(outline.get('characters', []))} 个")
        print(f"   地点：{len(outline.get('locations', []))} 个")
        print(f"   规划章节：{chapter_count} 章{vol_info}")
    except Exception as e:
        print(f"❌ 大纲生成失败：{e}")


# =========== 命令实现 ===========

def cmd_new(memory, continuity, foreshadow, rag, project_name):
    cfg = load_project_config(project_name)
    genre = cfg.get("type", "玄幻")
    style = cfg.get("style", "热血")
    concept = cfg.get("concept", "")

    print(f"\n=== 重新生成大纲：《{project_name}》 ===")
    print(f"当前设定：类型={genre}，风格={style}")
    print(f"当前构思：{concept[:80]}...")

    change = input("\n要修改设定吗？(y/N)：").strip().lower()
    if change == "y":
        genre = _input_choice(f"类型（当前：{genre}）", NOVEL_TYPES)
        style = _input_choice(f"风格（当前：{style}）", NOVEL_STYLES)
        new_concept = input(f"\n💡 新构思（回车保持原有）：").strip()
        if new_concept:
            concept = new_concept
        cfg["type"] = genre
        cfg["style"] = style
        cfg["concept"] = concept
        save_project_config(project_name, cfg)

    check_api_key()
    generate_outline(memory, continuity, foreshadow, project_name, genre, style, concept)


def cmd_write(memory, continuity, foreshadow, rag, project_name, ctx=None, chapter=None):
    ctx = ctx or config.get_project_context()
    outline_path = ctx.data_dir / "outline.json"
    if not outline_path.exists():
        print("❌ 未找到大纲文件，请先运行：python main.py new")
        return

    with open(outline_path, "r", encoding="utf-8") as f:
        outline = json.load(f)

    chapter_plan = _get_chapter_plan(outline)
    if not chapter_plan:
        print("❌ 大纲中没有章节计划")
        return

    if chapter is None:
        existing = glob.glob(str(ctx.chapters_dir / "chapter_*.md"))
        chapter = len(existing) + 1

    ch_data = next((c for c in chapter_plan if c.get("chapter") == chapter), None)
    if ch_data is None:
        print(f"❌ 大纲中没有第 {chapter} 章的计划")
        return

    check_api_key()

    title = ch_data.get("title", "")
    summary = ch_data.get("summary", "")
    time_tag = ch_data.get("time", ch_data.get("time_tag", ""))
    location = ch_data.get("location", "")
    characters = ch_data.get("characters", [])

    print(f"\n=== 生成第 {chapter} 章：{title} ===")
    print(f"摘要：{summary}")
    print(f"时间：{time_tag} | 地点：{location}")
    print(f"人物：{', '.join(characters)}")
    print("\n🤖 正在生成，请稍候（约1-3分钟）...\n")

    meta = outline.get("meta", {})
    writer = WriterAgent(memory, continuity, foreshadow, ctx=ctx, rag_store=rag,
                         genre=meta.get("genre", outline.get("genre", "玄幻")),
                         style=meta.get("style", outline.get("style", "热血")))
    reviewer = ReviewerAgent(memory, continuity, foreshadow)

    # ===== 生成前预检 =====
    # P0: 时空守卫 —— 检查时间线自洽 + 空间可达性
    spacetime_guard = SpacetimeGuard(memory, continuity)
    result = spacetime_guard.pre_check(
        chapter=chapter, time_tag=time_tag, location=location,
        characters=characters,
    )

    # 致命错误 → 拒绝生成
    if result.fatal_errors:
        print("\n⛔ 时空守卫拒绝生成！请修复以下问题后重试：")
        for err in result.fatal_errors:
            print(f"  ❌ {err}")
        return

    # 空间不可达 → 自动补双向通道
    if result.auto_fix_channels:
        print("\n🔗 空间守卫发现通道缺失，自动修复：")
        for ch in result.auto_fix_channels:
            print(f"  ✅ 建立双向通道：「{ch.from_location}」↔「{ch.to_location}」")
        spacetime_guard.auto_fix_spacemap(continuity, result.auto_fix_channels)

    # 其他警告
    if result.warnings:
        for w in result.warnings:
            print(f"  ⚠️ {w}")

    # P1: 逻辑约束引擎 —— 生成写作前约束文本
    logic_guard = LogicGuard(memory, continuity)
    logic_constraints = logic_guard.build_constraints(
        chapter=chapter, characters=characters, location=location,
    )
    if logic_constraints:
        print(f"\n🔒 已注入 {len(logic_constraints.split(chr(10)))} 条逻辑约束")

    try:
        content, settings_json = writer.write_chapter(chapter=chapter, title=title, summary=summary,
                                        time_tag=time_tag, location=location, characters=characters,
                                        logic_constraints=logic_constraints)

        # 审校循环（finalize_chapter 会在循环结束后自动保存章节文件）
        content, settings_json = writer.review_loop(reviewer, chapter=chapter, title=title, content=content,
                                                       summary=summary, time_tag=time_tag, location=location,
                                                       characters=characters, settings_json=settings_json,
                                                       logic_constraints=logic_constraints)

        update_project_progress(project_name, chapters_written=chapter)
        rebuild_novel_md(ctx.output_dir)
        update_project_memory(project_name, memory, continuity, foreshadow, output_dir=ctx.output_dir)

        print(f"\n✅ 第 {chapter} 章完成！")
        print(f"  字数：约 {len(content)} 字")
        print(f"  保存至：{ctx.chapters_dir}/chapter_{chapter:03d}.md")

        # 伏笔报告
        pending = foreshadow.get_pending()
        new_fs = [fs for fs in pending if fs.chapter_planted == chapter]
        if new_fs:
            print("\n📌 本章提取的伏笔：")
            for fs in new_fs:
                print(f"  - [{fs.id}] {fs.content[:50]}...")

        print(f"\n--- 正文预览（前300字）---\n{content[:300]}\n...")

        next_ch = chapter + 1
        if next_ch < len(chapter_plan):
            print(f"\n💡 下一步：python main.py write  # 生成第{next_ch}章")
        else:
            print("\n💡 大纲章节已全部生成！")
    except Exception as e:
        print(f"❌ 生成失败：{e}")
        import traceback
        traceback.print_exc()


def _get_chapter_plan(outline: dict) -> list:
    """获取扁平章节列表，兼容新旧格式"""
    # 新格式：volumes[].chapters
    if "volumes" in outline:
        chapters = []
        for vol in outline.get("volumes", []):
            chapters.extend(vol.get("chapters", vol.get("chapter_plan", [])))
        if chapters:
            return chapters
    # 旧格式：顶层 chapter_plan
    return outline.get("chapter_plan", [])





def cmd_review(memory, continuity, foreshadow, rag, project_name, ctx=None):
    ctx = ctx or config.get_project_context()
    existing = sorted(glob.glob(str(ctx.chapters_dir / "chapter_*.md")))
    if not existing:
        print("❌ 没有已生成的章节")
        return

    last_path = existing[-1]
    chapter_num = int(Path(last_path).stem.split("_")[1])
    with open(last_path, "r", encoding="utf-8") as f:
        content = f.read()

    outline_path = ctx.data_dir / "outline.json"
    title = f"第{chapter_num}章"
    ch_data = None
    if outline_path.exists():
        with open(outline_path, "r", encoding="utf-8") as f:
            outline = json.load(f)
        ch_data = next((c for c in _get_chapter_plan(outline) if c["chapter"] == chapter_num), None)
        if ch_data:
            title = ch_data.get("title", title)

    check_api_key()
    print(f"\n=== 审校第 {chapter_num} 章：{title} ===\n🤖 正在审校，请稍候...\n")

    reviewer = ReviewerAgent(memory, continuity, foreshadow)
    try:
        report = reviewer.review_chapter(chapter_num, title, content,
                                          characters=ch_data.get("characters", []) if ch_data else [])
        print(report["raw_text"])
        reviewer.save_review_report(chapter_num, report, output_dir=str(ctx.output_dir))
        print(f"\n📁 审校报告：{ctx.chapters_dir.parent}/review_chapter_{chapter_num:03d}.md")
        print(f"结论：{report['verdict']}")
    except Exception as e:
        print(f"❌ 审校失败：{e}")


def cmd_viz(memory, continuity, foreshadow, rag, project_name, ctx=None):
    ctx = ctx or config.get_project_context()
    print("\n=== 生成可视化 ===")
    try:
        results = generate_all_visualizations(memory, continuity, ctx.output_dir, project_name=project_name)
        print("✅ 可视化生成完成！")
        for name, path in results.items():
            print(f"  {name}：{path}")
        fs_path = foreshadow.export_to_markdown(output_dir=ctx.output_dir)
        print(f"  伏笔总览：{fs_path}")
        print("\n💡 用浏览器打开 HTML 文件即可查看")
    except Exception as e:
        print(f"❌ 可视化生成失败：{e}")


def cmd_status(memory, continuity, foreshadow, rag, project_name, ctx=None):
    ctx = ctx or config.get_project_context()
    cfg = load_project_config(project_name)
    novel_title = _get_novel_title(data_dir=ctx.data_dir)
    print(f"\n=== 《{novel_title or project_name}》创作进度 ===")
    print(f"项目名：{project_name} | 类型：{cfg.get('type', '未知')} | 风格：{cfg.get('style', '未知')}")
    if cfg.get("concept"):
        print(f"构思：{cfg['concept'][:80]}...")

    outline_path = ctx.data_dir / "outline.json"
    if outline_path.exists():
        with open(outline_path, "r", encoding="utf-8") as f:
            outline = json.load(f)
        print(f"\n大纲标题：{outline.get('meta', {}).get('title', outline.get('title', '未知'))}")
        chapter_plan = _get_chapter_plan(outline)
        print(f"规划章节：{len(chapter_plan)} 章")
    else:
        print("\n⚠️  未找到大纲（请先运行 python main.py new）")

    existing = sorted(glob.glob(str(ctx.chapters_dir / "chapter_*.md")))
    print(f"\n已生成章节：{len(existing)} 章")
    for path in existing[-5:]:
        print(f"  - {Path(path).name}")

    print(f"\n人物数量：{len(memory.characters)}")
    for name in list(memory.characters.keys())[:10]:
        print(f"  - {name}（{memory.characters[name].status}）")

    pending = foreshadow.get_pending()
    resolved = len([fs for fs in foreshadow.foreshadows if fs.status == "resolved"])
    print(f"\n伏笔：已埋 {len(foreshadow.foreshadows)} 个，已兑现 {resolved} 个，待回收 {len(pending)} 个")
    print(f"\n时间线事件：{len(continuity.timeline)} 条")
    print(f"地点数量：{len(memory.locations)} 个")


def cmd_add_fs(memory, continuity, foreshadow, rag, project_name):
    print("\n=== 手动添加伏笔 ===")
    chapter = input("埋下伏笔的章节号：").strip()
    try:
        chapter = int(chapter)
    except ValueError:
        print("❌ 章节号必须是数字")
        return

    content = input("伏笔内容（支持 FS： 格式）：").strip()
    if not content:
        print("❌ 内容不能为空")
        return

    characters_str = input("涉及人物（多个用逗号分隔，可留空）：").strip()
    characters = [c.strip() for c in characters_str.split(",") if c.strip()]

    try:
        fs_id = foreshadow.add_manual_fs(chapter=chapter, fs_text=content, characters=characters)
        print(f"\n✅ 伏笔添加成功！ID: {fs_id}")
        print(f"   内容：{content}")
        print(f"   章节：第 {chapter} 章")
        if characters:
            print(f"   人物：{', '.join(characters)}")
    except Exception as e:
        print(f"❌ 添加失败：{e}")


def cmd_fs_map(memory, continuity, foreshadow, rag, project_name, ctx=None):
    ctx = ctx or config.get_project_context()
    try:
        path = foreshadow.export_to_markdown(output_dir=ctx.output_dir)
        print(f"\n✅ 伏笔总览已生成：{path}")
        print(f"   总计 {len(foreshadow.foreshadows)} 个伏笔")
        print(f"   待回收 {len(foreshadow.get_pending())} 个")
        print(f"   已兑现 {len([fs for fs in foreshadow.foreshadows if fs.status == 'resolved'])} 个")
    except Exception as e:
        print(f"❌ 生成失败：{e}")


def cmd_de_ai(memory, continuity, foreshadow, rag, project_name, ctx=None):
    """反高潮二创：对最新章节做去AI味改写"""
    from novel_agent.agents.writer import WriterAgent
    ctx = ctx or config.get_project_context()
    existing = sorted(glob.glob(str(ctx.chapters_dir / "chapter_*.md")))
    if not existing:
        print("❌ 没有已生成的章节")
        return
    last_path = existing[-1]
    chapter_num = int(Path(last_path).stem.split("_")[1])
    with open(last_path, "r", encoding="utf-8") as f:
        content = f.read()
    writer = WriterAgent(memory, continuity, foreshadow, rag, ctx)
    print(f"  [进展] 正在对第{chapter_num}章做去AI改写...")
    rewritten = writer.de_ai_rewrite(chapter_num, content)
    if rewritten:
        print(f"✅ 第{chapter_num}章去AI改写完成")
        print(f"  原版备份：chapter_{chapter_num:03d}_pre_deai_*.md")
    else:
        print(f"❌ 去AI改写失败")


def cmd_resolve_fs(memory, continuity, foreshadow, rag, project_name):
    print("\n=== 手动回收/放弃伏笔 ===")
    pending = foreshadow.get_pending()
    if not pending:
        print("✅ 没有待回收的伏笔")
        return
    
    print(f"\n待回收伏笔（共 {len(pending)} 个）：")
    print("-" * 60)
    for fs in sorted(pending, key=lambda x: (-x.importance, x.chapter_planted)):
        chars = f" | 人物：{', '.join(fs.related_characters)}" if fs.related_characters else ""
        print(f"  [{fs.id}] 第{fs.chapter_planted}章（重要度{fs.importance}）{chars}")
        print(f"    内容：{fs.content[:80]}{'...' if len(fs.content) > 80 else ''}")
    print("-" * 60)
    
    fs_id = input("\n伏笔ID（如 FS_001）：").strip().upper()
    if not fs_id:
        print("❌ ID 不能为空")
        return
    if not fs_id.startswith("FS_"):
        fs_id = "FS_" + fs_id.lstrip("FS_").lstrip("fs_")
    
    target = next((fs for fs in foreshadow.foreshadows if fs.id == fs_id), None)
    if not target:
        print(f"❌ 未找到伏笔 {fs_id}")
        return
    
    print(f"\n伏笔内容：{target.content}")
    action = input("操作：1-回收  2-放弃  其他-取消：").strip()
    
    if action == "1":
        chapter = input("兑现章节号：").strip()
        resolution = input("兑现方式描述（可选）：").strip()
        try:
            foreshadow.resolve(fs_id, int(chapter) if chapter else 0, resolution or "手动回收")
            print(f"\n✅ 伏笔 {fs_id} 已标记为已兑现")
        except Exception as e:
            print(f"❌ 回收失败：{e}")
    elif action == "2":
        reason = input("放弃原因（可选）：").strip()
        try:
            foreshadow.drop(fs_id, reason or "手动放弃")
            print(f"\n✅ 伏笔 {fs_id} 已标记为已放弃")
        except Exception as e:
            print(f"❌ 操作失败：{e}")
    else:
        print("已取消")


def cmd_list():
    projects = list_projects()
    if not projects:
        print("\n📝 暂无小说项目")
        print("   运行 python main.py new 创建第一个")
        return

    print(f"\n📚 小说项目（共 {len(projects)} 个）")
    print("-" * 70)
    for p in projects:
        print(f"  《{p['name']}》  类型：{p['type']}  风格：{p['style']}  已写：{p['chapters']}章")
        if p["concept"]:
            print(f"    构思：{p['concept']}")
    print("-" * 70)
    print(f"项目目录：{config.PROJECTS_ROOT}")


# =========== 交互循环 ===========

def interactive_loop(project_name):
    ctx = config.set_project(project_name)
    memory, continuity, foreshadow, rag = init_services(ctx)

    while True:
        print(f"\n📖 当前项目：《{project_name}》")
        print("命令：write | review | viz | status | new | add-fs | resolve-fs | fs-map | de-ai | switch | list | quit")
        cmd = input(">>> ").strip().lower()

        if cmd in ("quit", "exit", "q"):
            print("👋 再见！")
            break
        elif cmd == "write":
            cmd_write(memory, continuity, foreshadow, rag, project_name, ctx=ctx)
        elif cmd == "review":
            cmd_review(memory, continuity, foreshadow, rag, project_name, ctx=ctx)
        elif cmd == "viz":
            cmd_viz(memory, continuity, foreshadow, rag, project_name, ctx=ctx)
        elif cmd == "status":
            cmd_status(memory, continuity, foreshadow, rag, project_name, ctx=ctx)
        elif cmd == "new":
            cmd_new(memory, continuity, foreshadow, rag, project_name)
        elif cmd == "add-fs":
            cmd_add_fs(memory, continuity, foreshadow, rag, project_name)
        elif cmd == "resolve-fs":
            cmd_resolve_fs(memory, continuity, foreshadow, rag, project_name)
        elif cmd == "fs-map":
            cmd_fs_map(memory, continuity, foreshadow, rag, project_name, ctx=ctx)
        elif cmd == "de-ai":
            cmd_de_ai(memory, continuity, foreshadow, rag, project_name, ctx=ctx)
        elif cmd == "switch":
            new_name = select_project()
            if new_name != project_name:
                project_name = new_name
                ctx = config.set_project(project_name)
                memory, continuity, foreshadow, rag = init_services(ctx)
        elif cmd == "list":
            cmd_list()
        elif cmd == "help":
            print("""
命令说明：
  write      - 生成下一章
  review     - 审校最新章节
  viz        - 生成可视化（时间线/人物关系/世界地图）
  status     - 显示当前进度
  new        - 重新生成大纲
  add-fs     - 手动添加伏笔
  resolve-fs - 手动回收/放弃伏笔
  fs-map     - 生成伏笔总览
  de-ai      - 对最新章节做去AI味改写
  switch     - 切换到其他小说项目
  list       - 列出所有项目
  quit       - 退出
""")
        else:
            print("❌ 未知命令，输入 help 查看帮助")


# =========== 辅助函数 ===========

def rebuild_novel_md(output_dir: str):
    out_dir = Path(output_dir)
    chapters_dir = out_dir / "chapters"
    novel_path = out_dir / "novel.md"
    if not chapters_dir.exists():
        return
    files = sorted(glob.glob(str(chapters_dir / "chapter_*.md")))
    if not files:
        return
    content_parts = []
    for fp in files:
        with open(fp, "r", encoding="utf-8") as cf:
            content_parts.append(cf.read())
    atomic_write_text(novel_path, "\n\n".join(content_parts) + "\n\n")
    print(f"  🔄 novel.md 已重新生成（{len(files)} 章）")


def update_project_memory(project_name: str, memory: MemoryManager,
                          continuity: ContinuityGuard,
                          foreshadow: ForeshadowTracker,
                          output_dir: str):
    """自动更新 projects/<项目名>/MEMORY.md 的数据统计部分"""
    from datetime import datetime

    mem_path = config.PROJECTS_ROOT / project_name / "MEMORY.md"
    if not mem_path.exists():
        # 不存在则从模板创建
        ctx = config.get_project_context()
        data_dir = str(ctx.data_dir) if ctx else str(config.PROJECTS_ROOT / project_name / "data")
        _create_project_memory(project_name, data_dir)
        if not mem_path.exists():
            return

    content = mem_path.read_text(encoding="utf-8")

    # 更新小说标题
    novel_title = _get_novel_title(data_dir=Path(output_dir).parent / "data")
    if novel_title:
        content = re.sub(
            r"^# MEMORY\.md - 《.+》",
            f"# MEMORY.md - 《{novel_title}》",
            content,
        )
        content = re.sub(
            r"\| 小说标题 \| .+ \|",
            f"| 小说标题 | {novel_title} |",
            content,
        )

    # 更新最后更新时间
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = re.sub(
        r"> 最后更新：.*",
        f"> 最后更新：{now}（自动更新）",
        content,
    )

    # 更新数据统计
    out_dir = Path(output_dir)
    chapters_dir = out_dir / "chapters"
    written = len(glob.glob(str(chapters_dir / "chapter_*.md"))) if chapters_dir.exists() else 0
    resolved = len([fs for fs in foreshadow.foreshadows if fs.status == "resolved"])

    stats_table = f"""| 数据 | 数量 |
|---|---|
| 人物 | {len(memory.characters)} |
| 世界设定 | {len(memory.world_settings)} |
| 地点 | {len(memory.locations)} |
| 伏笔 | {len(foreshadow.foreshadows)}（已兑现 {resolved}） |
| 时间线事件 | {len(continuity.timeline)} |
| 已写章节 | {written} |"""

    # 匹配并替换 "## 数据统计" 下面的表格
    stats_pattern = r"(## 数据统计\n\n)\|.*?\|.*?\|[\s\S]*?(?=\n\n##|\n\n---|\Z)"
    if re.search(stats_pattern, content):
        content = re.sub(stats_pattern, r"\1" + stats_table, content)

    mem_path.write_text(content, encoding="utf-8")


def _create_project_memory(project_name: str, data_dir: str):
    """为项目创建初始 MEMORY.md 模板"""
    from datetime import datetime

    mem_path = config.PROJECTS_ROOT / project_name / "MEMORY.md"
    if mem_path.exists():
        return

    novel_title = _get_novel_title(data_dir=data_dir)
    cfg = load_project_config(project_name)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    template = f"""# MEMORY.md - 《{novel_title or project_name}》

> 最后更新：{now}（自动更新）

---

## 基本信息

| 项目 | 内容 |
|---|---|
| 项目名 | {project_name} |
| 小说标题 | {novel_title or '（未生成大纲）'} |
| 类型 | {cfg.get('type', '未知')} |
| 风格 | {cfg.get('style', '未知')} |
| 构思 | {cfg.get('concept', '')[:100]} |

---

## 剧情梗概

（待大纲生成后填写）

---

## 核心人物

（待写作后自动填充）

---

## 数据统计

| 数据 | 数量 |
|---|---|
| 人物 | 0 |
| 世界设定 | 0 |
| 地点 | 0 |
| 伏笔 | 0（已兑现 0） |
| 时间线事件 | 0 |
| 已写章节 | 0 |

---

## 下一步

- 运行 `python main.py new` 生成大纲
- 运行 `python main.py write` 开始写作
"""
    mem_path.write_text(template, encoding="utf-8")
    print(f"  📄 已创建项目记忆文件：{mem_path}")


def _get_novel_title(data_dir: str) -> str:
    """从 outline.json 读取小说标题"""
    outline_path = Path(data_dir) / "outline.json"
    if outline_path.exists():
        with open(outline_path, "r", encoding="utf-8") as f:
            outline = json.load(f)
        return outline.get("meta", {}).get("title", outline.get("title", ""))
    return ""
