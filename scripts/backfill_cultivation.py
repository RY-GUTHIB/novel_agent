"""
从已写章节补录人物修为到 characters.json
读取 chapters/chapter_001.md ~ chapter_020.md，用 LLM 提取每个人物的修为境界，更新 characters.json
"""
import sys
import os
import json
import re

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
config.set_project('苍穹独狼')

from novel_agent.core.memory import MemoryManager
from novel_agent.llm.client import generate

memory = MemoryManager()

# 收集所有章节内容
chapters_dir = os.path.join(config.DATA_DIR, '..', 'output', 'chapters')
chapter_files = sorted([
    f for f in os.listdir(chapters_dir) if f.startswith('chapter_') and f.endswith('.md')
])

all_content = ""
for fname in chapter_files:
    fpath = os.path.join(chapters_dir, fname)
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    ch_num = fname.replace('chapter_', '').replace('.md', '')
    all_content += f"\n\n# 第{ch_num}章\n\n{content}"

# 构建已有人物列表（不含修为的）
char_list = []
for name, c in memory.characters.items():
    cult_info = f"，当前修为={c.cultivation}" if c.cultivation else ""
    char_list.append(f"  {name}{cult_info}")

char_list_text = '\n'.join(char_list)

prompt = f"""请从以下小说章节内容中，提取每个人物的修为境界（修炼等级）。
修为境界格式如：炼气圆满、筑基初期、筑基中期、筑基后期、金丹初期等。

## 已有人物列表：
{char_list_text}

## 要求：
1. 只输出有明确文本依据的修为，不要推测
2. 如果某人物在章节中修为有明确提升（如从筑基初期突破到筑基中期），记录最终修为
3. 输出格式为 JSON 数组：
[
  {{"name": "人物名", "cultivation": "修为境界"}},
  ...
]

## 章节内容：
{all_content[:15000]}
"""

print("正在用 LLM 提取人物修为...")

try:
    result = generate(
        system_prompt="你是小说内容分析专家，擅长从玄幻小说正文中准确提取人物的修为境界信息。",
        user_prompt=prompt,
        temperature=0.2,
        max_tokens=2048,
    )
    
    # 解析 JSON
    parsed = None
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        match = re.search(r'```json\s*([\s\S]*?)\s*```', result)
        if match:
            try:
                parsed = json.loads(match.group(1))
            except:
                pass
        if parsed is None:
            match = re.search(r'\[[\s\S]*\]', result)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except:
                    pass
    
    if not parsed or not isinstance(parsed, list):
        print(f"❌ 解析失败，LLM 输出：\n{result}")
        sys.exit(1)
    
    # 更新 characters.json
    updated = 0
    for item in parsed:
        name = item.get('name', '').strip()
        cult = item.get('cultivation', '').strip()
        if name and cult and name in memory.characters:
            old = memory.characters[name].cultivation
            if old != cult:
                memory.characters[name].cultivation = cult
                print(f"  ✅ {name}：{old or '（无）'} → {cult}")
                updated += 1
    
    if updated > 0:
        memory._save_characters()
        print(f"\n✅ 已更新 {updated} 个人物的修为")
    else:
        print("\n⚠️ 没有检测到修为变化（可能 LLM 未提取到有效信息）")
        
    print("\n当前修为记录：")
    for name, c in memory.characters.items():
        if c.cultivation:
            print(f"  {name}：{c.cultivation}")
            
except Exception as e:
    print(f"❌ 错误：{e}")
    import traceback
    traceback.print_exc()
