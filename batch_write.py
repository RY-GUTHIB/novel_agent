"""
batch_write.py - 批量生成多章（非交互式）

用法：
  python batch_write.py 2 5         # 生成第2到第5章
  python batch_write.py 6            # 生成第6章
  python batch_write.py 1 10 --resume  # 跳过已生成的章节，续写
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from novel_agent.cli.commands import (
    init_services, check_api_key, cmd_write, get_current_project_name, set_current_project,
)
from novel_agent.project import list_projects


def main():
    # 解析参数
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    resume = "--resume" in sys.argv

    if len(args) < 1:
        print("用法：python batch_write.py <起始章> [结束章] [--resume]")
        print("示例：python batch_write.py 2 5")
        print("      python batch_write.py 1 10 --resume  # 跳过已生成章节")
        sys.exit(1)

    start_ch = int(args[0])
    end_ch = int(args[1]) if len(args) >= 2 else start_ch

    # 获取当前项目
    project_name = get_current_project_name()
    if not project_name:
        projects = list_projects()
        if not projects:
            print("❌ 没有小说项目")
            sys.exit(1)
        project_name = projects[0]["name"]
        set_current_project(project_name)

    config.set_project(project_name)
    check_api_key()
    memory, continuity, foreshadow, rag = init_services()

    chapters_dir = Path(config.OUTPUT_DIR) / "chapters"

    # --resume：跳过已生成的章节
    if resume:
        skip_chapters = []
        active_range = []
        for ch in range(start_ch, end_ch + 1):
            ch_path = chapters_dir / f"chapter_{ch:03d}.md"
            if ch_path.exists():
                skip_chapters.append(ch)
            else:
                active_range.append(ch)
        if skip_chapters:
            print(f"⏭️  --resume：跳过已生成的章节 {skip_chapters}")
        if not active_range:
            print("✅ 所有章节已生成，无需续写")
            return
        start_ch, end_ch = active_range[0], active_range[-1]

    print(f"\n📖 项目：《{project_name}》")
    print(f"📝 批量生成第 {start_ch}-{end_ch} 章\n")

    for ch in range(start_ch, end_ch + 1):
        print(f"{'='*60}")
        print(f"  第 {ch} 章")
        print(f"{'='*60}")
        try:
            cmd_write(memory, continuity, foreshadow, rag, project_name, chapter=ch)
        except Exception as e:
            print(f"❌ 第 {ch} 章生成失败：{e}")
            import traceback
            traceback.print_exc()
            ans = input("\n继续下一章？(Y/n)：").strip().lower()
            if ans == "n":
                break

    print(f"\n✅ 批量生成完成！")

if __name__ == "__main__":
    main()
