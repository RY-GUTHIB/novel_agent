"""
backfill_knowledge.py - 补录角色认知数据（Ch1-20）
从已写章节中提取关键角色认知变化，写入 character_knowledge.json
"""
import json
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import set_project
set_project("苍穹独狼")

from memory import MemoryManager, CharacterKnowledge

memory = MemoryManager()

# 手动整理的关键角色认知（从Ch1-20中提取的重要认知变化）
knowledge_data = [
    # 第1章：苏月华告诉叶青云的身世
    CharacterKnowledge(
        character="叶青云",
        chapter_learned=1,
        knowledge="自己是叶无痕的儿子，父亲是天孤剑尊",
        source="苏月华告知",
        detail="苏月华助他冲击炼气圆满时告知身世",
    ),
    CharacterKnowledge(
        character="叶青云",
        chapter_learned=1,
        knowledge="体内有父亲留下的封印",
        source="苏月华告知",
        detail="苏月华提到叶无痕在他体内留下了封印",
    ),
    # 第2章：叶青云知道青玄上人是新师父
    CharacterKnowledge(
        character="叶青云",
        chapter_learned=2,
        knowledge="青玄上人收他为徒，是父亲旧识",
        source="亲眼经历",
        detail="青玄上人亲自来玄月城收徒",
    ),
    # 第3章：夜枭（黑衣人）知道叶青云是叶无痕的儿子
    CharacterKnowledge(
        character="夜枭",
        chapter_learned=3,
        knowledge="叶青云是叶无痕的儿子",
        source="提前调查",
        detail="在演武场角落低声说'叶无痕的儿子……有意思'",
    ),
    # 第3章：其他弟子知道叶青云是叶无痕的儿子
    CharacterKnowledge(
        character="众弟子",
        chapter_learned=3,
        knowledge="叶青云是叶无痕的儿子，领悟了天孤剑意",
        source="听闻传闻",
        detail="演武场上弟子议论'青玄上人新收的弟子，据说还是叶无痕的儿子'",
    ),
    # 第3章：赵无极知道叶青云领悟了天孤剑意
    CharacterKnowledge(
        character="赵无极",
        chapter_learned=3,
        knowledge="叶青云领悟了天孤剑意，直接进了内门",
        source="听闻传闻",
        detail="在内门入门考核时当面挑衅",
    ),
    # 第4章：叶青云知道暗影殿要杀他
    CharacterKnowledge(
        character="叶青云",
        chapter_learned=4,
        knowledge="暗影殿要杀他，是因为父亲叶无痕的恩怨",
        source="青玄上人告知",
        detail="青玄上人解释'你父亲当年斩杀无数魔道高手'",
    ),
    CharacterKnowledge(
        character="叶青云",
        chapter_learned=4,
        knowledge="夜枭是暗影殿首席杀手",
        source="听闻",
        detail="叶青云听说过这个名字",
    ),
    # 第5章相关认知（如有重要认知变化）
    CharacterKnowledge(
        character="叶青云",
        chapter_learned=5,
        knowledge="父亲留下的遗物在天剑阁某处",
        source="青玄上人提及",
        detail="青玄上人说等他修为稳固后交给他",
    ),
]

# 写入
for k in knowledge_data:
    memory.add_character_knowledge(k)

print(f"补录完成，共 {len(knowledge_data)} 条角色认知记录")
print(f"写入文件：{memory.data_dir / 'character_knowledge.json'}")
