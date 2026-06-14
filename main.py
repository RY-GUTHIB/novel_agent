"""
main.py - 小说创作 Agent CLI（多项目版）

使用方式：
  python main.py              # 交互式启动（选项目 + 命令循环）
  python main.py new          # 新建小说（交互式输入设定）
  python main.py write        # 生成下一章
  python main.py write --ch 5 # 生成指定章节
  python main.py review       # 审校最新章节
  python main.py viz          # 生成三大可视化
  python main.py status       # 显示当前进度/状态
  python main.py add-fs       # 手动添加伏笔
  python main.py fs-map       # 生成伏笔总览
  python main.py list         # 列出所有小说项目
"""

import json
import sys
import os
from pathlib import Path

# Windows 控制台 UTF-8 修复
if sys.platform == "win32":
    try:
        os.system("chcp 65001 >nul 2>&1")
    except Exception:
        pass
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 本地模块
import config
from novel_agent.project import (
    list_projects, load_project_config, save_project_config,
    create_project, get_project_paths, update_project_progress,
    NOVEL_TYPES, NOVEL_STYLES, PROJECTS_ROOT,
)
from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.agents.planner import PlannerAgent
from novel_agent.agents.writer import WriterAgent
from novel_agent.agents.reviewer import ReviewerAgent
from novel_agent.visualizer import generate_all_visualizations

# 当前项目标记文件
_CURRENT_PROJECT_FILE = Path(__file__).parent / ".current_project"


# =========== 项目选择 ===========

def get_current_project_name():
    """获取上次选择的项目名"""
    if _CURRENT_PROJECT_FILE.exists():
        name = _CURRENT_PROJECT_FILE.read_text(encoding="utf-8").strip()
        # 确认项目仍存在
        if (PROJECTS_ROOT / name / "config.json").exists():
            return name
    return None


def set_current_project(name: str):
    """记录当前项目"""
    _CURRENT_PROJECT_FILE.write_text(name, encoding="utf-8")


def select_project() -> str:
    """
    交互式选择项目
    返回项目名
    """
    projects = list_projects()

    if not projects:
        print("\n📝 还没有小说项目，来创建一个吧！\n")
        return create_new_project()

    # 上次使用的项目
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
    """
    交互式创建新项目
    返回项目名
    """
    print("\n" + "=" * 50)
    print("  📝 新建小说项目")
    print("=" * 50)

    # 1. 小说名
    while True:
        name = input("\n📖 小说名称：").strip()
        if not name:
            print("❌ 名称不能为空")
            continue
        # 检查是否已存在
        if (PROJECTS_ROOT / name).exists():
            overwrite = input(f"⚠️  项目「{name}」已存在，覆盖？(y/N)：").strip().lower()
            if overwrite != "y":
                continue
        break

    # 2. 类型
    print(f"\n📂 小说类型：")
    for i, t in enumerate(NOVEL_TYPES, 1):
        print(f"  {i}. {t}")
    type_choice = input("请选择（输入编号，默认1）：").strip()
    try:
        novel_type = NOVEL_TYPES[int(type_choice) - 1] if type_choice else NOVEL_TYPES[0]
    except (ValueError, IndexError):
        novel_type = NOVEL_TYPES[0]
    # 如果选了"其他"，让用户自定义
    if novel_type == "其他":
        custom = input("自定义类型：").strip()
        if custom:
            novel_type = custom

    # 3. 风格
    print(f"\n🎨 文风：")
    for i, s in enumerate(NOVEL_STYLES, 1):
        print(f"  {i}. {s}")
    style_choice = input("请选择（输入编号，默认1）：").strip()
    try:
        style = NOVEL_STYLES[int(style_choice) - 1] if style_choice else NOVEL_STYLES[0]
    except (ValueError, IndexError):
        style = NOVEL_STYLES[0]

    # 4. 总体构思
    print(f"\n💡 说说你的总体构思（可以是一句话，也可以是几段描述）：")
    print("   （输入空行结束）")
    idea_lines = []
    while True:
        line = input("   ")
        if not line:
            break
        idea_lines.append(line)
    concept = "\n".join(idea_lines)

    if not concept.strip():
        print("❌ 构思不能为空，至少说点什么吧")
        return create_new_project()

    # 创建项目目录和配置
    project_dir = create_project(name, novel_type, style, concept)
    set_current_project(name)

    print(f"\n✅ 项目「{name}」已创建！")
    print(f"   类型：{novel_type} | 风格：{style}")
    print(f"   目录：{project_dir}")

    # 询问是否立即生成大纲
    gen_outline = input("\n🤖 是否立即生成大纲？(Y/n)：").strip().lower()
    if gen_outline != "n":
        config.set_project(name)
        memory, continuity, foreshadow, rag = init_services()
        check_api_key()
        generate_outline(memory, continuity, foreshadow, rag, name, novel_type, style, concept)

    return name


# =========== 初始化 ===========

def init_services():
    """初始化所有服务（必须在 config.set_project() 之后调用）"""
    memory = MemoryManager()
    continuity = ContinuityGuard()
    foreshadow = ForeshadowTracker()
    rag = None  # RAG 暂时禁用
    return memory, continuity, foreshadow, rag


def check_api_key():
    """检查 API Key 是否配置"""
    if config.LLM_PROVIDER == "deepseek" and not config.DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY")
        print("请在 novel_agent/config.py 中设置，或设置环境变量：")
        print("  set DEEPSEEK_API_KEY=your-key-here")
        sys.exit(1)
    print(f"✅ 使用模型：{config.LLM_PROVIDER}")


# =========== 核心操作 ===========

def generate_outline(memory, continuity, foreshadow, rag, project_name, genre, style, concept):
    """生成大纲"""
    print("\n🤖 正在调用 LLM 生成大纲，请稍候（约1-2分钟）...")
    planner = PlannerAgent(memory, continuity, foreshadow)
    try:
        outline = planner.generate_outline(concept, genre=genre, style=style)
        planner.save_outline_json(outline)

        # 更新项目进度
        title = outline.get("title", project_name)
        update_project_progress(project_name,
                                outline=outline,
                                chapters_written=0)

        # 如果 LLM 给的标题跟项目名不同，提示用户
        if title != project_name:
            print(f"\n💡 LLM 建议标题：「{title}」，当前项目名：「{project_name}」")
            rename = input("   要把项目名改为 LLM 建议的标题吗？(y/N)：").strip().lower()
            if rename == "y":
                old_dir = PROJECTS_ROOT / project_name
                new_dir = PROJECTS_ROOT / title
                if not new_dir.exists():
                    old_dir.rename(new_dir)
                    set_current_project(title)
                    config.set_project(title)
                    # 重新初始化（路径变了）
                    memory, continuity, foreshadow, rag = init_services()
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

def cmd_new(memory, continuity, foreshadow, rag, project_name):
    """重新生成大纲（已有项目内）"""
    cfg = load_project_config(project_name)
    genre = cfg.get("type", "玄幻")
    style = cfg.get("style", "热血")
    concept = cfg.get("concept", "")

    print(f"\n=== 重新生成大纲：《{project_name}》 ===")
    print(f"当前设定：类型={genre}，风格={style}")
    print(f"当前构思：{concept[:80]}...")

    change = input("\n要修改设定吗？(y/N)：").strip().lower()
    if change == "y":
        print(f"\n📂 类型（当前：{genre}）：")
        for i, t in enumerate(NOVEL_TYPES, 1):
            marker = " ←" if t == genre else ""
            print(f"  {i}. {t}{marker}")
        type_choice = input("选择（回车保持）：").strip()
        try:
            if type_choice:
                genre = NOVEL_TYPES[int(type_choice) - 1]
        except (ValueError, IndexError):
            pass

        print(f"\n🎨 风格（当前：{style}）：")
        for i, s in enumerate(NOVEL_STYLES, 1):
            marker = " ←" if s == style else ""
            print(f"  {i}. {s}{marker}")
        style_choice = input("选择（回车保持）：").strip()
        try:
            if style_choice:
                style = NOVEL_STYLES[int(style_choice) - 1]
        except (ValueError, IndexError):
            pass

        new_concept = input(f"\n💡 新构思（回车保持原有）：").strip()
        if new_concept:
            concept = new_concept

        # 更新配置
        cfg["type"] = genre
        cfg["style"] = style
        cfg["concept"] = concept
        save_project_config(project_name, cfg)

    check_api_key()
    generate_outline(memory, continuity, foreshadow, rag, project_name, genre, style, concept)


def cmd_write(memory, continuity, foreshadow, rag, project_name, chapter=None):
    """生成章节（含审校自动修改循环）"""
    outline_path = Path(config.DATA_DIR) / "outline.json"
    if not outline_path.exists():
        print("❌ 未找到大纲文件，请先运行：python main.py new")
        return

    with open(outline_path, "r", encoding="utf-8") as f:
        outline = json.load(f)

    # 支持两种大纲格式：顶层 chapter_plan 或 volumes 内嵌 chapter_plan
    chapter_plan = outline.get("chapter_plan", [])
    if not chapter_plan and "volumes" in outline:
        for vol in outline.get("volumes", []):
            chapter_plan.extend(vol.get("chapter_plan", []))
    if not chapter_plan:
        print("❌ 大纲中没有章节计划")
        return

    if chapter is None:
        import glob
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

    print()
    print(f"=== 生成第 {chapter} 章：{title} ===")
    print(f"摘要：{summary}")
    print(f"时间：{time_tag}")
    print(f"地点：{location}")
    print("人物：" + ", ".join(characters))
    print()
    print("🤖 正在生成，请稍候（约1-3分钟）...")
    print()

    writer = WriterAgent(
        memory, continuity, foreshadow, rag,
        genre=outline.get("genre", "玄幻"),
        style=outline.get("style", "热血"),
    )
    reviewer = ReviewerAgent(memory, continuity, foreshadow)

    try:
        # 1. 生成章节
        content = writer.write_chapter(
            chapter=chapter,
            title=title,
            summary=summary,
            time_tag=time_tag,
            location=location,
            characters=characters,
        )
        writer.save_chapter(chapter, title, content)

        # 2. 审校 + 自动修改循环
        max_revisions = 3
        for rev in range(max_revisions + 1):
            report = reviewer.review_chapter(chapter, title, content)
            print()
            print(f"📋 审校报告（第{rev+1}次）：")
            raw = report["raw_text"]
            print(raw[:2000])
            v = report["verdict"]
            s = report["overall_score"]
            print()
            print(f"结论：{v} | 总分：{s}")

            if report["passed"]:
                print()
                print("✅ 审校通过！")
                break

            if rev >= max_revisions:
                print()
                print(f"⚠️ 已达最大修订次数（{max_revisions}），接受当前版本")
                break

            # 自动修改
            print()
            print(f"🔧 根据审校意见自动修改（第{rev+1}次修订）...")
            content = writer.revise_chapter(
                chapter=chapter,
                title=title,
                original_content=content,
                review_report=report["raw_text"],
                summary=summary,
                time_tag=time_tag,
                location=location,
                characters=characters,
            )
            writer.save_chapter(chapter, title, content)
            print("  修订完成，重新审校...")

        # 3. 更新项目进度
        update_project_progress(project_name, chapters_written=chapter)

        # 4. 重新生成 novel.md
        rebuild_novel_md(config.OUTPUT_DIR)

        print()
        print(f"✅ 第 {chapter} 章完成！")
        print(f"  字数：约 {len(content)} 字")
        print(f"  保存至：{config.OUTPUT_DIR}/chapters/chapter_{chapter:03d}.md")

        # 伏笔
        pending = foreshadow.get_pending()
        new_fs = [fs for fs in pending if fs.chapter_planted == chapter]
        if new_fs:
            print()
            print("📌 本章提取的伏笔：")
            for fs in new_fs:
                print(f"  - [{fs.id}] {fs.content[:50]}...")
        else:
            print()
            print("📌 本章无新伏笔")

        print()
        print("--- 正文预览（前300字）---")
        print(content[:300])
        print("...")

        next_ch = chapter + 1
        if next_ch <= len(chapter_plan):
            print()
            print(f"💡 下一步：python main.py write  # 生成第{next_ch}章")
        else:
            print()
            print("💡 大纲章节已全部生成！")
    except Exception as e:
        print(f"❌ 生成失败：{e}")
        import traceback
        traceback.print_exc()

def cmd_review(memory, continuity, foreshadow, rag, project_name):
    """审校最新章节"""
    import glob
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
        ch_data = next((c for c in outline.get("chapter_plan", [])
                        if c["chapter"] == chapter_num), None)
        if ch_data:
            title = ch_data.get("title", title)

    check_api_key()

    print(f"\n=== 审校第 {chapter_num} 章：{title} ===")
    print("🤖 正在审校，请稍候...\n")

    reviewer = ReviewerAgent(memory, continuity, foreshadow)
    try:
        report = reviewer.review_chapter(chapter_num, title, content)
        print(report["raw_text"])
        reviewer.save_review_report(chapter_num, report)
        print(f"\n📁 审校报告：{config.OUTPUT_DIR}/review_chapter_{chapter_num:03d}.md")
        print(f"结论：{report['verdict']}")
    except Exception as e:
        print(f"❌ 审校失败：{e}")


def cmd_viz(memory, continuity, foreshadow, rag, project_name):
    """生成三大可视化 + 伏笔总览"""
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


def cmd_status(memory, continuity, foreshadow, rag, project_name):
    """显示当前进度"""
    cfg = load_project_config(project_name)

    print(f"\n=== 《{project_name}》创作进度 ===")
    print(f"类型：{cfg.get('type', '未知')} | 风格：{cfg.get('style', '未知')}")
    if cfg.get("concept"):
        print(f"构思：{cfg['concept'][:80]}...")

    # 大纲
    outline_path = Path(config.DATA_DIR) / "outline.json"
    if outline_path.exists():
        with open(outline_path, "r", encoding="utf-8") as f:
            outline = json.load(f)
        print(f"\n标题：{outline.get('title', '未知')}")
        print(f"规划章节：{len(outline.get('chapter_plan', []))} 章")
    else:
        print("\n⚠️  未找到大纲（请先运行 python main.py new）")

    # 已生成章节
    import glob
    existing = sorted(glob.glob(str(Path(config.OUTPUT_DIR) / "chapters" / "chapter_*.md")))
    print(f"\n已生成章节：{len(existing)} 章")
    for path in existing[-5:]:
        print(f"  - {Path(path).name}")

    # 人物
    print(f"\n人物数量：{len(memory.characters)}")
    for name in list(memory.characters.keys())[:10]:
        print(f"  - {name}（{memory.characters[name].status}）")

    # 伏笔
    pending = foreshadow.get_pending()
    resolved = len([fs for fs in foreshadow.foreshadows if fs.status == "resolved"])
    print(f"\n伏笔：已埋 {len(foreshadow.foreshadows)} 个，已兑现 {resolved} 个，待回收 {len(pending)} 个")

    # 时间线
    print(f"\n时间线事件：{len(continuity.timeline)} 条")
    print(f"地点数量：{len(memory.locations)} 个")


def cmd_add_fs(memory, continuity, foreshadow, rag, project_name):
    """交互式添加伏笔"""
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
        fs_id = foreshadow.add_manual_fs(
            chapter=chapter,
            fs_text=content,
            characters=characters,
        )
        print(f"\n✅ 伏笔添加成功！ID: {fs_id}")
        print(f"   内容：{content}")
        print(f"   章节：第 {chapter} 章")
        if characters:
            print(f"   人物：{', '.join(characters)}")
    except Exception as e:
        print(f"❌ 添加失败：{e}")


def cmd_fs_map(memory, continuity, foreshadow, rag, project_name):
    """生成伏笔总览"""
    try:
        path = foreshadow.export_to_markdown()
        print(f"\n✅ 伏笔总览已生成：{path}")
        print(f"   总计 {len(foreshadow.foreshadows)} 个伏笔")
        print(f"   待回收 {len(foreshadow.get_pending())} 个")
        print(f"   已兑现 {len([fs for fs in foreshadow.foreshadows if fs.status == 'resolved'])} 个")
    except Exception as e:
        print(f"❌ 生成失败：{e}")


def cmd_list():
    """列出所有项目"""
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
    print(f"项目目录：{PROJECTS_ROOT}")


# =========== 交互式命令循环 ===========

def interactive_loop(project_name):
    """进入交互式命令循环"""
    config.set_project(project_name)
    memory, continuity, foreshadow, rag = init_services()

    while True:
        print(f"\n📖 当前项目：《{project_name}》")
        print("命令：write | review | viz | status | new | add-fs | fs-map | switch | list | quit")
        cmd = input(">>> ").strip().lower()

        if cmd in ("quit", "exit", "q"):
            print("👋 再见！")
            break
        elif cmd == "write":
            cmd_write(memory, continuity, foreshadow, rag, project_name)
        elif cmd == "review":
            cmd_review(memory, continuity, foreshadow, rag, project_name)
        elif cmd == "viz":
            cmd_viz(memory, continuity, foreshadow, rag, project_name)
        elif cmd == "status":
            cmd_status(memory, continuity, foreshadow, rag, project_name)
        elif cmd == "new":
            cmd_new(memory, continuity, foreshadow, rag, project_name)
        elif cmd == "add-fs":
            cmd_add_fs(memory, continuity, foreshadow, rag, project_name)
        elif cmd == "fs-map":
            cmd_fs_map(memory, continuity, foreshadow, rag, project_name)
        elif cmd == "switch":
            new_name = select_project()
            if new_name != project_name:
                project_name = new_name
                config.set_project(project_name)
                memory, continuity, foreshadow, rag = init_services()
        elif cmd == "list":
            cmd_list()
        elif cmd == "help":
            print("""
命令说明：
  write    - 生成下一章
  review   - 审校最新章节
  viz      - 生成可视化（时间线/人物关系/世界地图）
  status   - 显示当前进度
  new      - 重新生成大纲
  add-fs   - 手动添加伏笔
  fs-map   - 生成伏笔总览
  switch   - 切换到其他小说项目
  list     - 列出所有项目
  quit     - 退出
""")
        else:
            print("❌ 未知命令，输入 help 查看帮助")


# =========== 主函数 ===========

def main():
    if len(sys.argv) < 2:
        # 无参数 → 交互式模式
        project_name = select_project()
        interactive_loop(project_name)
        return

    command = sys.argv[1]

    if command == "list":
        cmd_list()
        return

    if command == "new":
        # 新建项目（命令行方式）
        project_name = create_new_project()
        # 创建后进入交互模式
        enter = input("\n进入交互模式继续创作？(Y/n)：").strip().lower()
        if enter != "n":
            interactive_loop(project_name)
        return

    # 以下命令需要项目上下文
    project_name = get_current_project_name()
    if not project_name:
        project_name = select_project()

    config.set_project(project_name)
    memory, continuity, foreshadow, rag = init_services()

    if command == "write":
        ch = None
        if "--ch" in sys.argv:
            idx = sys.argv.index("--ch")
            try:
                ch = int(sys.argv[idx + 1])
            except (IndexError, ValueError):
                pass
        cmd_write(memory, continuity, foreshadow, rag, project_name, chapter=ch)
    elif command == "review":
        cmd_review(memory, continuity, foreshadow, rag, project_name)
    elif command == "viz":
        cmd_viz(memory, continuity, foreshadow, rag, project_name)
    elif command == "status":
        cmd_status(memory, continuity, foreshadow, rag, project_name)
    elif command == "add-fs":
        # 支持命令行参数和交互式两种方式
        if "--chapter" in sys.argv and "--content" in sys.argv:
            idx_ch = sys.argv.index("--chapter")
            idx_content = sys.argv.index("--content")
            try:
                chapter = int(sys.argv[idx_ch + 1])
                content = sys.argv[idx_content + 1]
                chars_str = ""
                if "--characters" in sys.argv:
                    idx_chars = sys.argv.index("--characters")
                    chars_str = sys.argv[idx_chars + 1]
                characters = [c.strip() for c in chars_str.split(",") if c.strip()]
                fs_id = foreshadow.add_manual_fs(chapter=chapter, fs_text=content, characters=characters)
                print(f"✅ 伏笔添加成功！ID: {fs_id}")
            except (IndexError, ValueError) as e:
                print(f"❌ 参数错误：{e}")
        else:
            cmd_add_fs(memory, continuity, foreshadow, rag, project_name)
    elif command == "fs-map":
        cmd_fs_map(memory, continuity, foreshadow, rag, project_name)
    else:
        print(f"❌ 未知命令：{command}")
        print("可用命令：new, write, review, viz, status, add-fs, fs-map, list")
        print("或直接运行 python main.py 进入交互模式")




# ============ 辅助函数 ============

def rebuild_novel_md(output_dir: str = None):
    """重新生成 novel.md（从 chapters/ 目录按章节顺序拼接）"""
    import glob
    from pathlib import Path as _Path
    out_dir = _Path(output_dir or config.OUTPUT_DIR)
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
                text = cf.read()
            f.write(text)
            f.write("\n\n")
    print(f"  🔄 novel.md 已重新生成（{len(files)} 章）")


if __name__ == "__main__":
    main()
