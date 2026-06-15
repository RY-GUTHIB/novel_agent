"""
batch_write.py - 批量生成多章（非交互式）

用法：
  python batch_write.py 2 5    # 生成第2到第5章
  python batch_write.py 6       # 生成第6章
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from novel_agent.cli.commands import (
    init_services, check_api_key, cmd_write, get_current_project_name, set_current_project,
)
from novel_agent.project import list_projects


def main():
    # 解析参数
    if len(sys.argv) < 2:
        print("用法：python batch_write.py <起始章> [结束章]")
        print("示例：python batch_write.py 2 5")
        sys.exit(1)

    start_ch = int(sys.argv[1])
    end_ch = int(sys.argv[2]) if len(sys.argv) >= 3 else start_ch

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
    memory, continuity, foreshadow = init_services()

    print(f"\n📖 项目：《{project_name}》")
    print(f"📝 批量生成第 {start_ch}-{end_ch} 章\n")

    for ch in range(start_ch, end_ch + 1):
        print(f"{'='*60}")
        print(f"  第 {ch} 章")
        print(f"{'='*60}")
        try:
            cmd_write(memory, continuity, foreshadow, project_name, chapter=ch)
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
