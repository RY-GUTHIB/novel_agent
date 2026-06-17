"""
quick_new_project.py - 快速新建小说项目（非交互式）

用法：
  python quick_new_project.py <项目名> <类型> <风格> <构思文件>
  python quick_new_project.py "测试小说" "玄幻修仙" "热血激昂" "concept.txt"

如果不带参数，使用默认值：
  项目名：测试小说
  类型：玄幻修仙
  风格：热血激昂
  构思：从 stdin 或默认构思
"""

import sys
import os

# 把项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from novel_agent.project import create_project, NOVEL_TYPES, NOVEL_STYLES
from novel_agent.cli.commands import init_services, check_api_key, generate_outline


def main():
    # 默认值
    name = "测试小说"
    novel_type = "玄幻修仙"
    style = "热血激昂"
    concept = """叶青云，一个被遗弃在青云宗外的婴儿，身上只有一块残破的玉佩。
宗门弟子欺负他，师父不待见他，只有师姐对他好。
直到那天，玉佩发光，一段记忆涌入脑海——他不是废物，他是天剑尊者的遗孤。
复仇之路，从此开始。"""

    args = sys.argv[1:]

    if len(args) >= 1:
        name = args[0]
    if len(args) >= 2:
        novel_type = args[1]
    if len(args) >= 3:
        style = args[2]
    if len(args) >= 4:
        concept_file = args[3]
        if os.path.exists(concept_file):
            with open(concept_file, encoding="utf-8") as f:
                concept = f.read()
        else:
            concept = concept_file  # 直接把参数当构思文本

    print(f"📝 新建项目：{name}")
    print(f"   类型：{novel_type}")
    print(f"   风格：{style}")
    print(f"   构思长度：{len(concept)} 字")

    # 创建项目目录和 config.json
    project_dir = create_project(name, novel_type, style, concept)
    config.set_project(name)

    # 写入 .current_project
    from novel_agent.cli.commands import set_current_project
    set_current_project(name)

    print(f"\n✅ 项目「{name}」已创建！目录：{project_dir}")

    # 非交互式：默认直接生成大纲
    print("\n🤖 开始生成大纲...")
    print("   （这可能需要几分钟，请耐心等待）")

    check_api_key()
    memory, continuity, foreshadow, _ = init_services()
    generate_outline(memory, continuity, foreshadow, name, novel_type, style, concept)
    print("\n✅ 大纲生成完成！可以运行：python main.py write 开始写作")


if __name__ == "__main__":
    main()
