"""
config.py - 全局配置
支持多后端LLM，默认 DeepSeek
支持多项目管理（按小说名分目录）
"""

import os
import sys
from pathlib import Path

# ============ 路径配置 ============
BASE_DIR = Path(__file__).parent
PROJECTS_ROOT = BASE_DIR / "projects"

# 当前激活的项目名（None 表示未选中）
_CURRENT_PROJECT = None

# 模块级路径变量（其他模块通过 config.DATA_DIR 访问，不要用 from import）
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"


def set_project(project_name: str):
    """切换当前项目，更新 DATA_DIR / OUTPUT_DIR（模块属性，兼容 import config 用法）"""
    global _CURRENT_PROJECT, DATA_DIR, OUTPUT_DIR
    _CURRENT_PROJECT = project_name
    project_dir = PROJECTS_ROOT / project_name
    data_dir = project_dir / "data"
    output_dir = project_dir / "output"
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "chapters").mkdir(exist_ok=True)

    # 更新模块属性，使 config.DATA_DIR 拿到新值
    mod = sys.modules[__name__]
    mod.DATA_DIR = data_dir
    mod.OUTPUT_DIR = output_dir


def get_project_name():
    return _CURRENT_PROJECT


# ============ LLM 配置 ============
# 支持: "deepseek", "qwen", "gemini", "ollama", "claude", "volcengine"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "volcengine")

# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"  # 或 "deepseek-reasoner"

# Qwen/通义千问 配置（备用）
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_MODEL = "qwen-max"

# Gemini 配置（备用，上下文超大）
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash-exp"

# Ollama 本地配置（备用）
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "llama3.3:70b"  # 或 "qwen3:32b"

# Claude 配置（备用）
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# 火山引擎方舟配置（备用，OpenAI 兼容接口）
# 请勿使用 https://ark.cn-beijing.volces.com/api/v3 ：该 Base URL 不会消耗您的 Coding Plan 额度，而是会产生额外费用
VOLCENGINE_API_KEY = os.getenv("VOLCENGINE_API_KEY", "ark-9c1b2f85-d6c7-4c7b-bf57-74754cfb8189-05cc6")
VOLCENGINE_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
VOLCENGINE_MODEL = "deepseek-v4-flash"  # 或 "doubao-1.5-pro-32k" 等

# ============ 生成参数 ============
MAX_TOKENS = 64000      # 单章最大token（正文+SETTINGS_JSON）
TEMPERATURE = 0.85      # 创意度（0-1，小说建议0.7-0.9）
TOP_P = 0.9

# ============ 小说配置 ============
DEFAULT_GENRE = "玄幻"   # 默认类型
DEFAULT_STYLE = "热血"    # 默认风格
CHAPTER_WORD_TARGET = 3000  # 每章目标字数

# ============ RAG 配置 ============
RAG_TOP_K = 5            # 检索相关片段数量
RAG_CHUNK_SIZE = 500      # 文本切片大小（字）

# ============ 连续性检查配置 ============
TIME_JUMP_WARN_DAYS = 30   # 时间跳跃超过N天警告
ENABLE_CONTINUITY_CHECK = True
ENABLE_FORESHADOW_TRACK = True

# ============ 可视化配置 ============
# 离线模式：从 vendor/ 目录加载，不走 CDN
VENDOR_DIR = BASE_DIR / "vendor"
