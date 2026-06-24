"""
main.py - 小说创作 Agent CLI（多项目版）

使用方式：
  python main.py                    # 交互式启动（选项目 + 命令循环）
  python main.py new                # 新建小说（交互式输入设定）
  python main.py write              # 生成下一章
  python main.py write --ch 5       # 生成指定章节
   python main.py extend             # 扩展大纲（追加5卷）
   python main.py extend --volumes 10 # 扩展大纲（追加10卷）
  python main.py review             # 审校最新章节
  python main.py viz                # 生成三大可视化
  python main.py status             # 显示当前进度/状态
  python main.py add-fs             # 手动添加伏笔
  python main.py fs-map             # 生成伏笔总览
  python main.py list               # 列出所有小说项目
"""

import logging
import sys
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

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

from novel_agent.cli.commands import (
    select_project, create_new_project, interactive_loop,
    cmd_write, cmd_review, cmd_viz, cmd_status,
    cmd_new, cmd_add_fs, cmd_resolve_fs, cmd_fs_map, cmd_list,
    cmd_de_ai, cmd_extend, cmd_set_main_char,
    get_current_project_name,
    init_services, check_api_key,
)
import config


def main():
    if len(sys.argv) < 2:
        project_name = select_project()
        interactive_loop(project_name)
        return

    command = sys.argv[1]

    if command == "list":
        cmd_list()
        return

    if command == "new":
        project_name = create_new_project()
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
                if ch < 1:
                    print("❌ 章节号必须大于 0")
                    return
            except (IndexError, ValueError):
                print("❌ --ch 参数必须是正整数")
                return
        cmd_write(memory, continuity, foreshadow, rag, project_name, chapter=ch)
    elif command == "review":
        cmd_review(memory, continuity, foreshadow, rag, project_name)
    elif command == "viz":
        cmd_viz(memory, continuity, foreshadow, rag, project_name)
    elif command == "status":
        cmd_status(memory, continuity, foreshadow, rag, project_name)
    elif command == "add-fs":
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
    elif command == "resolve-fs":
        cmd_resolve_fs(memory, continuity, foreshadow, rag, project_name)
    elif command == "fs-map":
        cmd_fs_map(memory, continuity, foreshadow, rag, project_name)
    elif command == "de-ai":
        cmd_de_ai(memory, continuity, foreshadow, rag, project_name)
    elif command == "set-main-char":
        cmd_set_main_char(memory, continuity, foreshadow, rag, project_name)
    elif command == "extend":
        volumes = 3
        if "--volumes" in sys.argv:
            idx = sys.argv.index("--volumes")
            try:
                volumes = int(sys.argv[idx + 1])
            except (IndexError, ValueError):
                print("❌ --volumes 参数必须是正整数")
                return
        cmd_extend(memory, continuity, foreshadow, rag, project_name, volumes=volumes)
    else:
        print(f"❌ 未知命令：{command}")
        print("可用命令：new, write, review, viz, status, extend, set-main-char, add-fs, resolve-fs, fs-map, de-ai, list")
        print("或直接运行 python main.py 进入交互模式")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏸️  用户中断")
        sys.exit(0)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ 程序异常退出：{e}")
        input("\n按 Enter 键退出...")
        sys.exit(1)
