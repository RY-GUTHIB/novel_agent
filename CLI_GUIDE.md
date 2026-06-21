# CLI_GUIDE.md - novel_agent 启动与常用指令速查

> 最后更新：2026-06-16
> 本文档专注「怎么启动」和「命令怎么用」，不重复 MEMORY.md 里的项目背景。

---

## 一、启动前准备

### Python 路径（重要）

本项目**不能用系统 `python`**，必须用管理环境（以下为示例，请替换为你的实际 Python 路径）：

```
<python_env_path>/python.exe
```

**Windows 快捷方式：** 把 Python 路径存成一个 `.bat` 文件，比如 `run_agent.bat`：

```bat
@echo off
cd /d <project_root>
<python_env_path>/python.exe main.py %*
pause
```

双击 `run_agent.bat` 即可运行，支持带参数（如 `run_agent.bat write --ch 22`）。

### 依赖检查

管理环境的 pip 路径：
```
<python_env_path>/pip.exe
```

安装依赖（如果还没装）：
```bash
<python_env_path>/pip.exe install -r requirements.txt
```

### API Key

在 `config.py` 中确认对应后端的 API Key 已配置（当前默认后端为 `volcengine`，见 `LLM_PROVIDER` 字段）：

```python
# config.py 中对应后端的 API Key
VOLCENGINE_API_KEY = "ark-..."   # 默认后端（火山引擎）
DEEPSEEK_API_KEY = "sk-..."     # 备用后端（DeepSeek）
```

如果切换了 `LLM_PROVIDER`，需确保对应后端的 Key 已填写。

---

## 二、启动方式一览

### 方式 A：交互式 CLI（推荐，适合逐章操作）

```bash
cd <project_root>
<python_env_path>/python.exe main.py
```

启动后：
1. 选择项目（输入编号）
2. 进入命令循环，输入以下命令：

| 命令 | 说明 |
|------|------|
| `write` | 生成下一章 |
| `review` | 审校最新章节 |
| `viz` | 生成三大可视化（时间线/人物关系/世界地图） |
| `status` | 查看当前进度 |
| `add-fs` | 手动添加伏笔 |
| `resolve-fs` | 回收/放弃伏笔 |
| `fs-map` | 生成伏笔总览 |
| `switch` | 切换项目 |
| `list` | 列出所有项目 |
| `quit` / `q` | 退出 |

### 方式 B：直接命令行（适合脚本/自动化）

无需交互，直接指定命令：

```bash
# 写下一章
python main.py write

# 写指定章节
python main.py write --ch 22

# 审校最新章
python main.py review

# 生成可视化
python main.py viz

# 查看状态
python main.py status

# 列出所有项目
python main.py list

# 新建项目
python main.py new
```

> ⚠️ 命令行模式会尝试读取 `.current_project` 文件来确定当前项目。
> 如果文件不存在或损坏，会退回交互式选择。

### 批量写作

```bash
# 连续写第 21 到 25 章
python batch_write.py 21 25

# 跳过已生成的章节续写
python batch_write.py 1 30 --resume
```

---

## 三、核心工作流

### 日常写作流程

```
status        → 查看当前进度（确认接下来写哪章）
write --ch N  → 生成指定章节
review        → 审校（自动触发修订循环，最多3轮）
viz           → 生成可视化（检查时间线/人物关系）
```

### 伏笔管理流程

```
add-fs              → 手动添加伏笔（交互式）
resolve-fs          → 标记伏笔已回收/已放弃
fs-map              → 生成伏笔总览（Markdown）
```

### 可视化输出位置

生成后文件在：
```
<project_root>/projects/<项目名>/output/
├── timeline.html        # 时间线可视化
├── character_map.html   # 人物关系图
├── world_map.html       # 世界地图
└── foreshadow_map.md    # 伏笔总览
```

用浏览器直接打开 `.html` 文件即可查看（离线可用，无需联网）。

---

## 四、常见问题

### Q: 启动时提示 `PermissionError: .current_project`

**原因：** 沙箱/权限问题，或文件被占用。

**解决：** 在本地 Windows 直接运行（不在 WorkBuddy 沙箱内），或手动创建 `.current_project` 文件：
```bash
echo <项目名> > <project_root>/projects/.current_project
```

### Q: `python` 命令找不到 / 用了错误版本

**解决：** 始终用完整路径：
```
<python_env_path>/python.exe
```

### Q: DeepSeek API 报错

**检查：** `config.py` 第 49 行 `DEEPSEEK_API_KEY` 是否正确。
**网络：** 确认能访问 `https://api.deepseek.com`（公司网络可能有代理）。

### Q: 想从某一章重新写

**方法：** 删除该章节文件，再 `write --ch N`：
```bash
del <project_root>/projects/<项目名>/output/chapters/chapter_022.md
python main.py write --ch 22
```

### Q: 审校卡住 / 修订循环不结束

**机制：** 最多 3 轮自动修订，仍不通过会强制输出。
**手动干预：** 直接编辑 `chapter_NNN.md`，然后 `review` 重新审校。

---

## 五、项目状态快照（2026-06-15）

| 项目 | 《<项目名>》 |
|------|-------------|
| 已完成 | 第 1-X 章 |
| 下一章 | 第 N 章 |
| 总大纲 | （依项目而定） |
| 伏笔 | （依项目而定） |
| 人物 | （依项目而定） |

---

## 六、脚本自动化示例

### 一键写章 + 审校 + 可视化

`scripts/daily_write.bat`：
```bat
@echo off
cd /d <project_root>
set PY=<python_env_path>/python.exe
%PY% main.py write
%PY% main.py review
%PY% main.py viz
pause
```

### 定时任务（Windows 任务计划器）

触发器：每天 20:00
操作：运行 `<project_root>/scripts/daily_write.bat`
