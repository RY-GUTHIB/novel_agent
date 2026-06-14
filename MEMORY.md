# MEMORY.md - 小说创作 Agent 项目记忆

> 最后更新：2026-06-14
> 本文档随项目一起打包，记录当前项目状态、用法和关键上下文。

---

## 项目简介

AI 长篇小说创作 Agent，支持多 Agent 协作（规划/写作/审校）、时间线+空间线守卫、伏笔追踪、设定自动回写、三大可视化。

**技术栈：** Python 3.13 + DeepSeek API + ChromaDB(RAG) + vis-network/vis-timeline

---

## 目录结构

```
novel_agent/
├── main.py                  # CLI 入口
├── config.py                # 配置（API密钥、路径管理、项目切换）
├── generator.py             # LLM 后端（DeepSeek / OpenAI 兼容）
├── planner_agent.py         # 规划 Agent（生成大纲）
├── writer_agent.py          # 写作 Agent（写章节 + 设定自动回写）
├── reviewer_agent.py        # 审校 Agent（评分 + 自动修订）
├── memory.py                # 人物档案管理
├── continuity.py            # 时间线 + 空间线守卫
├── foreshadow.py            # 伏笔追踪
├── visualizer.py            # 三大可视化（时间线/人物关系图/世界地图）
├── rag_store.py             # 向量数据库（ChromaDB，可选）
├── vendor/                  # 离线可视化 JS 库（vis-network/vis-timeline）
├── projects/
│   └── 苍穹独狼/            # 当前小说项目
│       ├── config.json      # 项目配置
│       ├── data/            # 小说数据文件
│       │   ├── characters.json      # 人物档案
│       │   ├── world_settings.json  # 世界设定（势力/功法/物品等）
│       │   ├── locations.json       # 地点档案
│       │   ├── foreshadow.json      # 伏笔记录
│       │   ├── timeline.json        # 时间线事件
│       │   ├── plot_rules.json      # 剧情规则（IF-THEN条件规则）
│       │   ├── character_knowledge.json  # 角色认知记录（谁在第几章知道了什么）
│       │   └── outline.json         # 大纲（多卷制）
│       └── output/           # 输出目录
│           ├── chapters/     # 章节文件（chapter_001.md 等）
│           ├── reviews/      # 审校报告
│           ├── timeline.html            # 时间线可视化
│           ├── character_map.html       # 人物关系图
│           ├── world_map.html           # 世界地图
│           └── foreshadow_map.md        # 伏笔总览
└── MEMORY.md                # 本文件
```

---

## 环境要求

- **Python：** 3.13+（本项目使用管理环境 `C:\Users\RY\.workbuddy\binaries\python\envs\default\Scripts\python.exe`）
- **依赖：** `openai`, `chromadb`, `tiktoken`, `rank_bm25`
- **API：** 需配置 `DEEPSEEK_API_KEY` 环境变量（在 `config.py` 中设置）

---

## 运行方式

### 方式一：交互式 CLI

```bash
cd E:\WorkBuddy\novel_agent
python main.py
# 选择项目 → 选择功能（生成大纲/写章节/审校/可视化/查看状态）
```

### 方式二：直接写下一章

```python
import config
config.set_project('苍穹独狼')

from memory import MemoryManager
from continuity import ContinuityGuard
from foreshadow import ForeshadowTracker
from main import cmd_write

memory = MemoryManager()
continuity = ContinuityGuard()
foreshadow = ForeshadowTracker()

cmd_write(memory, continuity, foreshadow, None, '苍穹独狼')
# 指定章节：cmd_write(..., chapter=21)
```

### 方式三：生成可视化

```python
from main import cmd_viz
cmd_viz(memory, continuity, foreshadow, None, '苍穹独狼')
# 生成 timeline.html / character_map.html / world_map.html / foreshadow_map.md
```

---

## 当前项目：《苍穹独狼》

| 项目 | 内容 |
|---|---|
| 类型 | 玄幻修仙 / 热血 |
| 大纲 | 4卷40章（多卷制） |
| 进度 | **第1-20章已完成**（卷1《青云初啼》+ 卷2《血月惊澜》） |
| 待写 | 第21-40章（卷3《剑指苍穹》+ 卷4《破晓之战》） |

### 剧情梗概（截至 Ch20）

叶青云，父亲叶无痕（天孤剑尊/大乘境，域外征战），母亲苏月华（玄月世家嫡女，被软禁）。
叶青云入天剑阁拜师青玄上人，外门试炼夺冠，筑基突破，发现血煞教与暗影殿勾结图谋玄月始祖复活——
**叶青云是关键祭品**。卷2结尾，暗影殿覆灭，叶青云赶赴玄月城对峙。

### 核心人物

| 人物 | 身份 | 当前状态 |
|---|---|---|
| 叶青云 | 主角 | 筑基中期，前往玄月城 |
| 叶无痕 | 父亲/天孤剑尊 | 大乘境，域外战场，下落不明 |
| 苏月华 | 母亲 | 自碎丹田，生死未明 |
| 青玄上人 | 师父/天剑阁阁主 | alive，与血煞老祖交手 |
| 苏月瑶 | 表妹/同行者 | alive，与叶青云同行 |
| 夜枭 | 原暗影殿刺客（已反水） | 重伤存活，与叶青云同行 |
| 玄月天/玄月星河 | 玄月世家掌权者 | alive，幕后勾结血煞教 |
| 血煞老祖 | 主要反派 | 重伤未死，前往玄月世家 |

### 势力关系

- 天剑阁 ↔ 玄月世家：表面盟友
- 血煞教 + 暗影殿（已覆灭）：共同敌人，图谋玄月始祖复活
- 叶青云：复活计划的关键祭品
- 北冥王朝：暗中插手（密使"影"）

### 数据统计（截至 Ch20）

| 数据 | 数量 |
|---|---|
| 人物 | 35 |
| 世界设定 | 106 |
| 地点 | 21 |
| 伏笔 | 156（大量待回收） |
| 时间线事件 | 40 |
| 剧情规则 | 3 |
| 角色认知 | 9 |

---

## 关键代码修改记录

| 文件 | 修改内容 |
|---|---|
| `planner_agent.py` | 多卷制大纲（至少4卷40章）+ factions 字段 + 节奏控制（禁自爆/每卷只突破1-2境界） |
| `writer_agent.py` | `_extract_and_save_world_settings()` 分类回写设定（人物→characters.json / 势力功法→world_settings.json / 地点→locations.json / 空间移动→character_locations.json / 连通→spacemap.json / 剧情规则→plot_rules.json）；写作/修订 prompt 注入剧情规则 |
| `main.py` | `cmd_write` 支持 volumes 格式 + 自动审校循环（写→审→修订→再审，最多3轮） |
| `reviewer_agent.py` | 9维度审校（连续性/修为/空间/人物/伏笔/情节/文笔/规则一致性/**角色认知一致性**）；审校 prompt 注入剧情规则+角色认知 |
| `visualizer.py` | 人物关系图有向箭头 + 边颜色关键词匹配 + 地图/关系图位置固定（randomSeed） |
| `memory.py` | `export_character_relations()` 保留有向边（不去重）；新增 `PlotRule` + `CharacterKnowledge` 数据结构 + `get_active_rules_prompt()` + `get_character_knowledge_prompt()` |
| `continuity.py` | 同章节事件覆盖去重 + 人物名归一化（去掉括号后缀）；`generate_continuity_prompt` 新增 `plot_rules_text` + `character_knowledge_text` 参数 |

---

## 注意事项

1. **Python 路径：** 必须使用管理环境，不能直接用 `python` 命令
2. **API 密钥：** `config.py` 中 `DEEPSEEK_API_KEY` 需配置后才能实际运行
3. **章节文件位置：** 章节存在 `projects/<项目名>/output/chapters/` 目录下
4. **可视化离线可用：** `vendor/` 目录已包含 vis-network/vis-timeline 的离线 JS，无需联网
5. **伏笔格式：** 正文中用 `[FS:描述]` 标记伏笔，审校时会检查格式
6. **多卷制大纲：** `outline.json` 使用 `volumes` 格式，每卷内含 `chapter_plan`

---

## 下一步

- 续写第21章《父亲踪迹》（卷3《剑指苍穹》开头）
- 回收积压伏笔（当前156条，待回收量大）
- 卷3重点：域外战场 + 父子重逢 + 金丹突破
- 卷4重点：最终决战 + 救母 + 父亲沉睡结局
