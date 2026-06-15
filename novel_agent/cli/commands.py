"""
commands.py - CLI 命令实现

从 main.py 中提取的所有命令逻辑，与 CLI 入口解耦。
"""

import glob
import json
import sys
from pathlib import Path

import config
from novel_agent.project import (
    list_projects, load_project_config, save_project_config,
    create_project, update_project_progress, NOVEL_TYPES, NOVEL_STYLES,
)
from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.agents.planner import PlannerAgent
from novel_agent.agents.writer import WriterAgent
from novel_agent.agents.reviewer import ReviewerAgent
from novel_agent.visualizer import generate_all_visualizations


# =========== 项目管理 ===========

_CURRENT_PROJECT_FILE = config.PROJECTS_ROOT / ".current_project"


def get_current_project_name():
    if _CURRENT_PROJECT_FILE.exists():
        name = _CURRENT_PROJECT_FILE.read_text(encoding="utf-8").strip()
        if (config.PROJECTS_ROOT / name / "config.json").exists():
            return name
    return None


def set_current_project(name: str):
    _CURRENT_PROJECT_FILE.write_text(name, encoding="utf-8")


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
    print(f"   类型：{novel_type} | 风格：{style}")
    print(f"   目录：{project_dir}")

    gen_outline = input("\n🤖 是否立即生成大纲？(Y/n)：").strip().lower()
    if gen_outline != "n":
        config.set_project(name)
        memory, continuity, foreshadow = init_services()
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


def _input_concept() -> str:
    print(f"\n💡 说说你的总体构思（可以是一句话，也可以是几段描述）：")
    print("   （输入空行结束）")
    lines = []
    while True:
        line = input("   ")
        if not line:
            break
        lines.append(line)
    concept = "\n".join(lines)
    if not concept.strip():
        print("❌ 构思不能为空，至少说点什么吧")
        return _input_concept()
    return concept


# =========== 初始化 ===========

def init_services():
    """初始化所有服务（必须在 config.set_project() 之后调用）"""
    return MemoryManager(), ContinuityGuard(), ForeshadowTracker()


def check_api_key():
    if config.LLM_PROVIDER == "deepseek" and not config.DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY")
        print("请在 novel_agent/config.py 中设置，或设置环境变量：")
        print("  set DEEPSEEK_API_KEY=your-key-here")
        sys.exit(1)
    print(f"✅ 使用模型：{config.LLM_PROVIDER}")


def generate_outline(memory, continuity, foreshadow, project_name, genre, style, concept):
    print("\n🤖 正在调用 LLM 生成大纲，请稍候（约1-2分钟）...")
    planner = PlannerAgent(memory, continuity, foreshadow)
    try:
        outline = planner.generate_outline(concept, genre=genre, style=style)
        planner.save_outline_json(outline)

        title = outline.get("title", project_name)
        update_project_progress(project_name, outline=outline, chapters_written=0)

        if title != project_name:
            print(f"\n💡 LLM 建议标题：「{title}」，当前项目名：「{project_name}」")
            rename = input("   要把项目名改为 LLM 建议的标题吗？(y/N)：").strip().lower()
            if rename == "y":
                old_dir = config.PROJECTS_ROOT / project_name
                new_dir = config.PROJECTS_ROOT / title
                if not new_dir.exists():
                    old_dir.rename(new_dir)
                    set_current_project(title)
                    config.set_project(title)
                    memory, continuity, foreshadow = init_services()
                    project_name = title
                    print(f"   ✅ 已重命名为「{title}」")

        print(f"\n✅ 大纲生成完成！")
        print(f"   标题：{outline.get('title', '未知')}")
        print(f"   人物：{len(outline.get('characters', []))} 个")
        print(f"   地点：{len(outline.get('locations', []))} 个")
        print(f"   规划章节：{len(outline.get('chapter_plan', []))} 章")
    except Exception as e:
        print(f"❌ 大纲生成失败：{e}")


# =========== 命令实现 ===========

def cmd_new(memory, continuity, foreshadow, project_name):
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


def cmd_write(memory, continuity, foreshadow, project_name, chapter=None):
    outline_path = Path(config.DATA_DIR) / "outline.json"
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
        existing = glob.glob(str(Path(config.OUTPUT_DIR) / "chapters" / "chapter_*.md"))
        chapter = len(existing) + 1

    ch_data = next((c for c in chapter_plan if c["chapter"] == chapter), None)
    if ch_data is None:
        print(f"❌ 大纲中没有第 {chapter} 章的计划")
        return

    check_api_key()

    title = ch_data.get("title", "")
    summary = ch_data.get("summary", "")
    time_tag = ch_data.get("time_tag", "")
    location = ch_data.get("location", "")
    characters = ch_data.get("characters", [])

    print(f"\n=== 生成第 {chapter} 章：{title} ===")
    print(f"摘要：{summary}")
    print(f"时间：{time_tag} | 地点：{location}")
    print(f"人物：{', '.join(characters)}")
    print("\n🤖 正在生成，请稍候（约1-3分钟）...\n")

    writer = WriterAgent(memory, continuity, foreshadow, genre=outline.get("genre", "玄幻"), style=outline.get("style", "热血"))
    reviewer = ReviewerAgent(memory, continuity, foreshadow)

    try:
        content = writer.write_chapter(chapter=chapter, title=title, summary=summary,
                                        time_tag=time_tag, location=location, characters=characters)
        writer.save_chapter(chapter, title, content)

        # 审校循环
        content = _review_loop(writer, reviewer, chapter, title, content, summary, time_tag, location, characters)

        update_project_progress(project_name, chapters_written=chapter)
        rebuild_novel_md(config.OUTPUT_DIR)

        print(f"\n✅ 第 {chapter} 章完成！")
        print(f"  字数：约 {len(content)} 字")
        print(f"  保存至：{config.OUTPUT_DIR}/chapters/chapter_{chapter:03d}.md")

        # 伏笔报告
        pending = foreshadow.get_pending()
        new_fs = [fs for fs in pending if fs.chapter_planted == chapter]
        if new_fs:
            print("\n📌 本章提取的伏笔：")
            for fs in new_fs:
                print(f"  - [{fs.id}] {fs.content[:50]}...")

        print(f"\n--- 正文预览（前300字）---\n{content[:300]}\n...")

        next_ch = chapter + 1
        if next_ch <= len(chapter_plan):
            print(f"\n💡 下一步：python main.py write  # 生成第{next_ch}章")
        else:
            print("\n💡 大纲章节已全部生成！")
    except Exception as e:
        print(f"❌ 生成失败：{e}")
        import traceback
        traceback.print_exc()


def _get_chapter_plan(outline: dict) -> list:
    chapter_plan = outline.get("chapter_plan", [])
    if not chapter_plan and "volumes" in outline:
        for vol in outline.get("volumes", []):
            chapter_plan.extend(vol.get("chapter_plan", []))
    return chapter_plan


def _review_loop(writer, reviewer, chapter, title, content, summary, time_tag, location, characters):
    max_revisions = 3
    prev_score = None
    no_improvement_count = 0
    for rev in range(max_revisions + 1):
        report = reviewer.review_chapter(chapter, title, content)
        print(f"\n📋 审校报告（第{rev+1}次）：")
        print(report["raw_text"][:2000])
        print(f"\n结论：{report['verdict']} | 总分：{report['overall_score']}")

        if report["passed"]:
            print("\n✅ 审校通过！")
            break

        if rev >= max_revisions:
            print(f"\n⚠️ 已达最大修订次数（{max_revisions}），接受当前版本")
            break

        # 收敛检测：本次审校的分数 vs 上次修订后的分数
        # 注意：首次审校(rev=0)没有 prev_score，直接进入修订
        if prev_score is not None and report["overall_score"] <= prev_score:
            no_improvement_count += 1
        else:
            no_improvement_count = 0

        print(f"\n🔧 根据审校意见自动修改（第{rev+1}次修订）...")
        content = writer.revise_chapter(
            chapter=chapter, title=title, original_content=content,
            review_report=report["raw_text"], summary=summary,
            time_tag=time_tag, location=location, characters=characters,
        )
        writer.save_chapter(chapter, title, content)
        print("  修订完成，重新审校...")

        # 修订后记录本次分数，供下一轮比较
        prev_score = report["overall_score"]

        # 如果连续2次修订后分数都没提升，下一轮审校后提前终止
        if no_improvement_count >= 2:
            print(f"\n⚠️ 连续{no_improvement_count}次修订分数未提升，提前终止修订")
            break

    # 审校循环结束后，提取最终版本的伏笔和自动回收
    writer.finalize_foreshadows(content, chapter, characters)
    return content


def cmd_review(memory, continuity, foreshadow, project_name):
    existing = sorted(glob.glob(str(Path(config.OUTPUT_DIR) / "chapters" / "chapter_*.md")))
    if not existing:
        print("❌ 没有已生成的章节")
        return

    last_path = existing[-1]
    chapter_num = int(Path(last_path).stem.split("_")[1])
    with open(last_path, "r", encoding="utf-8") as f:
        content = f.read()

    outline_path = Path(config.DATA_DIR) / "outline.json"
    title = f"第{chapter_num}章"
    if outline_path.exists():
        with open(outline_path, "r", encoding="utf-8") as f:
            outline = json.load(f)
        ch_data = next((c for c in outline.get("chapter_plan", []) if c["chapter"] == chapter_num), None)
        if ch_data:
            title = ch_data.get("title", title)

    check_api_key()
    print(f"\n=== 审校第 {chapter_num} 章：{title} ===\n🤖 正在审校，请稍候...\n")

    reviewer = ReviewerAgent(memory, continuity, foreshadow)
    try:
        report = reviewer.review_chapter(chapter_num, title, content)
        print(report["raw_text"])
        reviewer.save_review_report(chapter_num, report)
        print(f"\n📁 审校报告：{config.OUTPUT_DIR}/review_chapter_{chapter_num:03d}.md")
        print(f"结论：{report['verdict']}")
    except Exception as e:
        print(f"❌ 审校失败：{e}")


def cmd_viz(memory, continuity, foreshadow, project_name):
    print("\n=== 生成可视化 ===")
    try:
        results = generate_all_visualizations(memory, continuity, project_name=project_name)
        print("✅ 可视化生成完成！")
        for name, path in results.items():
            print(f"  {name}：{path}")
        fs_path = foreshadow.export_to_markdown()
        print(f"  伏笔总览：{fs_path}")
        print("\n💡 用浏览器打开 HTML 文件即可查看")
    except Exception as e:
        print(f"❌ 可视化生成失败：{e}")


def cmd_status(memory, continuity, foreshadow, project_name):
    cfg = load_project_config(project_name)
    print(f"\n=== 《{project_name}》创作进度 ===")
    print(f"类型：{cfg.get('type', '未知')} | 风格：{cfg.get('style', '未知')}")
    if cfg.get("concept"):
        print(f"构思：{cfg['concept'][:80]}...")

    outline_path = Path(config.DATA_DIR) / "outline.json"
    if outline_path.exists():
        with open(outline_path, "r", encoding="utf-8") as f:
            outline = json.load(f)
        print(f"\n标题：{outline.get('title', '未知')}")
        print(f"规划章节：{len(outline.get('chapter_plan', []))} 章")
    else:
        print("\n⚠️  未找到大纲（请先运行 python main.py new）")

    existing = sorted(glob.glob(str(Path(config.OUTPUT_DIR) / "chapters" / "chapter_*.md")))
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


def cmd_add_fs(memory, continuity, foreshadow, project_name):
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


def cmd_fs_map(memory, continuity, foreshadow, project_name):
    try:
        path = foreshadow.export_to_markdown()
        print(f"\n✅ 伏笔总览已生成：{path}")
        print(f"   总计 {len(foreshadow.foreshadows)} 个伏笔")
        print(f"   待回收 {len(foreshadow.get_pending())} 个")
        print(f"   已兑现 {len([fs for fs in foreshadow.foreshadows if fs.status == 'resolved'])} 个")
    except Exception as e:
        print(f"❌ 生成失败：{e}")


def cmd_resolve_fs(memory, continuity, foreshadow, project_name):
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
    config.set_project(project_name)
    memory, continuity, foreshadow = init_services()

    while True:
        print(f"\n📖 当前项目：《{project_name}》")
        print("命令：write | review | viz | status | new | add-fs | resolve-fs | fs-map | switch | list | quit")
        cmd = input(">>> ").strip().lower()

        if cmd in ("quit", "exit", "q"):
            print("👋 再见！")
            break
        elif cmd == "write":
            cmd_write(memory, continuity, foreshadow, project_name)
        elif cmd == "review":
            cmd_review(memory, continuity, foreshadow, project_name)
        elif cmd == "viz":
            cmd_viz(memory, continuity, foreshadow, project_name)
        elif cmd == "status":
            cmd_status(memory, continuity, foreshadow, project_name)
        elif cmd == "new":
            cmd_new(memory, continuity, foreshadow, project_name)
        elif cmd == "add-fs":
            cmd_add_fs(memory, continuity, foreshadow, project_name)
        elif cmd == "resolve-fs":
            cmd_resolve_fs(memory, continuity, foreshadow, project_name)
        elif cmd == "fs-map":
            cmd_fs_map(memory, continuity, foreshadow, project_name)
        elif cmd == "switch":
            new_name = select_project()
            if new_name != project_name:
                project_name = new_name
                config.set_project(project_name)
                memory, continuity, foreshadow = init_services()
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
  switch     - 切换到其他小说项目
  list       - 列出所有项目
  quit       - 退出
""")
        else:
            print("❌ 未知命令，输入 help 查看帮助")


# =========== 辅助函数 ===========

def rebuild_novel_md(output_dir: str = None):
    out_dir = Path(output_dir or config.OUTPUT_DIR)
    chapters_dir = out_dir / "chapters"
    novel_path = out_dir / "novel.md"
    if not chapters_dir.exists():
        return
    files = sorted(glob.glob(str(chapters_dir / "chapter_*.md")))
    if not files:
        return
    with open(novel_path, "w", encoding="utf-8") as f:
        for fp in files:
            with open(fp, "r", encoding="utf-8") as cf:
                f.write(cf.read())
            f.write("\n\n")
    print(f"  🔄 novel.md 已重新生成（{len(files)} 章）")
