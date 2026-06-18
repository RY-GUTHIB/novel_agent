# MEMORY.md - 小说创作 Agent 框架

> 最后更新：2026-06-18
> 本文档记录框架通用信息。每部小说的详细状态见 `projects/<小说名>/MEMORY.md`。

---

## 项目简介

AI 长篇小说创作 Agent，支持多 Agent 协作（规划/写作/审校）、时间线+空间线守卫、伏笔追踪、设定自动回写、三大可视化。

**技术栈：** Python 3.13 + 多后端 LLM（DeepSeek/Qwen/Gemini/Claude/火山引擎）+ ChromaDB(RAG) + vis-network/vis-timeline

---

## 目录结构

```
novel_agent/
├── main.py                          # CLI 入口（项目选择 + 命令调度）
├── config.py                        # 全局配置（API密钥、路径、多后端）
├── requirements.txt                 # 依赖
├── MEMORY.md                        # 本文件（框架通用信息）
├── CLI_GUIDE.md                     # CLI 使用指南
├── batch_write.py                   # 批量写作脚本
├── quick_test.py / test_run.py      # 测试脚本
├── vendor/                          # 离线可视化 JS 库
│   ├── vis-timeline-graph2d.min.js
│   ├── vis-timeline-graph2d.min.css
│   └── vis-network.min.js
├── scripts/                         # 数据维护脚本
│   ├── backfill_cultivation.py
│   ├── backfill_knowledge.py
│   ├── backfill_rules.py
│   └── backfill_spatial.py
├── novel_agent/                     # 核心代码包
│   ├── agents/                      # 三大 Agent
│   │   ├── planner.py               # 规划 Agent（生成多卷制大纲）
│   │   ├── writer.py                # 写作 Agent（写章节 + 设定回写 + 定向修补）
│   │   ├── reviewer.py              # 审校 Agent（9维度审校 + 自动修订）
│   │   └── prompts.py               # Agent Prompt 模板
│   ├── core/                        # 核心模块
│   │   ├── memory.py                # 人物/地点/设定/规则/物品等管理
│   │   ├── continuity.py            # 时间线 + 空间线守卫
│   │   ├── foreshadow.py            # 伏笔追踪（埋设/回收/导出）
│   │   ├── rag.py                   # ChromaDB + BM25 混合检索
│   │   ├── models.py                # 数据模型定义
│   │   ├── spacetime_guard.py       # P0 时空守卫（预检 + 自动修复）
│   │   ├── logic_guard.py           # P1 逻辑约束引擎
│   │   └── validator.py             # 数据校验
│   ├── llm/                         # LLM 客户端
│   │   └── client.py                # 多后端统一接口
│   ├── visualizer/                  # 可视化
│   │   └── generator.py             # 时间线/人物关系图/世界地图 HTML
│   ├── cli/                         # CLI 命令
│   │   └── commands.py              # 所有命令实现
│   └── project/                     # 项目管理
│       └── manager.py               # 列出/创建/切换/进度更新
├── projects/                        # 小说项目目录
│   └── <小说名>/
│       ├── MEMORY.md                # 该小说的状态文档（自动更新）
│       ├── config.json              # 项目配置
│       ├── data/                    # 小说数据文件
│       │   ├── outline.json         # 大纲（多卷制）
│       │   ├── characters.json      # 人物档案
│       │   ├── world_settings.json  # 世界设定
│       │   ├── locations.json       # 地点档案
│       │   ├── foreshadow.json      # 伏笔记录
│       │   ├── timeline.json        # 时间线事件
│       │   ├── spacemap.json        # 空间地图
│       │   ├── character_locations.json  # 人物位置追踪
│       │   ├── plot_rules.json      # 剧情规则
│       │   ├── character_knowledge.json  # 角色认知
│       │   ├── items.json           # 物品档案
│       │   ├── sect_factions.json   # 势力/宗门
│       │   └── scene_events.json    # 场景事件
│       └── output/                  # 输出目录
│           ├── chapters/            # 章节文件（chapter_001.md 等）
│           ├── novel.md             # 全书合并文件
│           ├── reviews/             # 审校报告
│           ├── timeline.html        # 时间线可视化
│           ├── character_map.html   # 人物关系图
│           └── world_map.html       # 世界地图
└── data/                            # 兼容旧版（无项目模式）
```

---

## 环境要求

- **Python：** 3.13+（本项目使用管理环境 `C:\Users\RY\.workbuddy\binaries\python\envs\default\Scripts\python.exe`）
- **依赖：** `openai`, `chromadb`, `tiktoken`, `rank_bm25`
- **API：** 需在 `config.py` 中配置对应后端的 API Key

---

## 运行方式

### 交互式 CLI

```bash
cd E:\WorkBuddy\novel_agent
"C:\Users\RY\.workbuddy\binaries\python\envs\default\Scripts\python.exe" main.py
# 选择项目 → 进入交互循环
```

### 命令列表

| 命令 | 说明 |
|---|---|
| `write` | 生成下一章（含审校循环，最多3轮修订） |
| `review` | 单独审校最新章节 |
| `viz` | 生成三大可视化 |
| `status` | 查看当前进度 |
| `new` | 重新生成大纲 |
| `add-fs` | 手动添加伏笔 |
| `resolve-fs` | 手动回收/放弃伏笔 |
| `fs-map` | 生成伏笔总览 |
| `switch` | 切换到其他小说项目 |
| `list` | 列出所有项目 |
| `quit` | 退出 |

---

## 注意事项

1. **Python 路径：** 必须使用管理环境，不能直接用 `python` 命令
2. **API 密钥：** `config.py` 中对应后端需配置 API Key 后才能实际运行
3. **章节文件位置：** 章节存在 `projects/<项目名>/output/chapters/` 目录下
4. **可视化离线可用：** `vendor/` 目录已包含 vis-network/vis-timeline 的离线 JS，无需联网
5. **伏笔格式：** 正文中用 `[FS:描述]` 标记伏笔，审校时会检查格式
6. **多卷制大纲：** `outline.json` 使用 `volumes` 格式，每卷内含 `chapter_plan`
7. **MEMORY.md 自动更新：** 每次 `write` 完成后自动刷新 `projects/<项目名>/MEMORY.md` 的数据统计
