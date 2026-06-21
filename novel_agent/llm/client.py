"""
generator.py - LLM调用封装（多后端支持）

统一接口：
    response = generate(prompt, system_prompt=..., temperature=...)
"""

import sys
import os
import time
import json
import re
import logging
from functools import lru_cache
from typing import Optional
import config

logger = logging.getLogger(__name__)

# 预编译正则
_JSON_BLOCK_PATTERN = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```')

# 重试配置
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # 秒，指数退避基数

# ========== 可重试异常集合 ==========

_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
)
try:
    from openai import APIError as OpenAIAPIError
    from openai import APITimeoutError, APIConnectionError, RateLimitError, InternalServerError
    _RETRYABLE_EXCEPTIONS += (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)
except ImportError:
    OpenAIAPIError = type('_DummyAPIError', (), {})  # 永远不匹配 isinstance

try:
    from anthropic import APIError as AnthropicAPIError
    from anthropic import APITimeoutError as AnthropicTimeoutError
    from anthropic import RateLimitError as AnthropicRateLimitError
    _RETRYABLE_EXCEPTIONS += (AnthropicAPIError, AnthropicTimeoutError, AnthropicRateLimitError)
except ImportError:
    pass

# 不可重试的错误
_NON_RETRYABLE_MESSAGES = ("invalid_api_key", "authentication", "permission", "invalid_request", "400", "401", "403", "422")


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否可重试"""
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return True
    # OpenAI APIError 是基类，需要排除 401/403 等不可重试子类型
    if isinstance(exc, OpenAIAPIError):
        err_str = str(exc).lower()
        if any(kw in err_str for kw in _NON_RETRYABLE_MESSAGES):
            return False
        return True
    return False


def _retry(fn, *args, max_retries=MAX_RETRIES, **kwargs):
    """带指数退避的重试包装器"""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if not _is_retryable(e):
                raise
            if attempt < max_retries:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"LLM 调用失败（第{attempt+1}次），{delay}秒后重试: {e}")
                time.sleep(delay)
            else:
                logger.error(f"LLM 调用失败（已重试{max_retries}次）: {e}")
    raise last_exc


# ========== Provider 配置策略 ==========

_PROVIDERS = {
    "deepseek": lambda: (config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.DEEPSEEK_MODEL, "openai"),
    "qwen": lambda: (config.QWEN_BASE_URL, config.QWEN_API_KEY, config.QWEN_MODEL, "openai"),
    "ollama": lambda: (config.OLLAMA_BASE_URL, "ollama", config.OLLAMA_MODEL, "openai"),
    "volcengine": lambda: (config.VOLCENGINE_BASE_URL, config.VOLCENGINE_API_KEY, config.VOLCENGINE_MODEL, "openai"),
    "gemini": lambda: ("", "", config.GEMINI_MODEL, "gemini"),
    "claude": lambda: ("", config.CLAUDE_API_KEY, config.CLAUDE_MODEL, "claude"),
}


def _get_provider_config(provider: str):
    """获取 provider 配置，返回 (base_url, api_key, model, api_type)"""
    if provider not in _PROVIDERS:
        raise ValueError(f"不支持的 LLM_PROVIDER: {provider}")
    return _PROVIDERS[provider]()


# ========== OpenAI 客户端缓存 ==========

@lru_cache(maxsize=8)
def _get_client(base_url: str, api_key: str):
    """获取或创建缓存的 OpenAI 客户端（LRU 缓存，最多 8 个客户端）"""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("请先安装 openai: pip install openai>=1.0.0")
    return OpenAI(base_url=base_url, api_key=api_key)


def clear_client_cache():
    """清理所有缓存的 OpenAI 客户端"""
    _get_client.cache_clear()


def _call_openai_compatible(base_url: str, api_key: str, model: str,
                              system_prompt: str, user_prompt: str,
                              temperature: float = None,
                              max_tokens: int = None) -> str:
    """调用 OpenAI 兼容接口（DeepSeek/Qwen/Ollama 均使用此格式）"""
    if temperature is None:
        temperature = config.TEMPERATURE
    if max_tokens is None:
        max_tokens = config.MAX_TOKENS

    client = _get_client(base_url, api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=config.TOP_P,
    )
    choice = response.choices[0]
    logger.info("LLM finish_reason=%s, prompt_tokens=%s, completion_tokens=%s",
                choice.finish_reason,
                getattr(response.usage, 'prompt_tokens', '?'),
                getattr(response.usage, 'completion_tokens', '?'))
    return choice.message.content


def _call_gemini(system_prompt: str, user_prompt: str,
                   temperature: float = None,
                   max_tokens: int = None) -> str:
    """调用 Gemini API"""
    if temperature is None:
        temperature = config.TEMPERATURE
    if max_tokens is None:
        max_tokens = config.MAX_TOKENS
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError("请先安装 google-generativeai: pip install google-generativeai")

    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        config.GEMINI_MODEL,
        system_instruction=system_prompt,
    )
    response = model.generate_content(
        user_prompt,
        generation_config=genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text


def _call_claude(system_prompt: str, user_prompt: str,
                  temperature: float = None,
                  max_tokens: int = None) -> str:
    """调用 Claude API（Anthropic 原生格式）"""
    if temperature is None:
        temperature = config.TEMPERATURE
    if max_tokens is None:
        max_tokens = config.MAX_TOKENS
    try:
        from anthropic import Anthropic
    except ImportError:
        raise ImportError("请先安装 anthropic: pip install anthropic>=0.40.0")

    client = Anthropic(api_key=config.CLAUDE_API_KEY)
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


def generate(system_prompt: str, user_prompt: str,
             temperature: float = None,
             max_tokens: int = None) -> str:
    """
    统一生成接口（带自动重试）
    :param system_prompt: 系统提示词（角色/任务描述）
    :param user_prompt: 用户输入/任务内容
    :param temperature: 创意度 0-1
    :param max_tokens: 最大输出token
    :return: 生成文本
    """
    if temperature is None:
        temperature = config.TEMPERATURE
    if max_tokens is None:
        max_tokens = config.MAX_TOKENS
    provider = config.LLM_PROVIDER.lower()
    base_url, api_key, model, api_type = _get_provider_config(provider)

    if api_type == "openai":
        return _retry(_call_openai_compatible,
            base_url, api_key, model,
            system_prompt, user_prompt, temperature, max_tokens)
    elif api_type == "gemini":
        return _retry(_call_gemini, system_prompt, user_prompt, temperature, max_tokens)
    elif api_type == "claude":
        return _retry(_call_claude, system_prompt, user_prompt, temperature, max_tokens)
    else:
        raise ValueError(f"不支持的 API 类型: {api_type}")


def _save_env_key(name: str, value: str):
    """将 API Key 写入 .env 文件并更新运行时 config"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(f"{name}="):
                    lines.append(f"{name}={value}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"{name}={value}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.environ[name] = value
    setattr(config, name, value)


def check_api_key():
    """API Key 校验。缺失时交互式引导输入并自动保存到 .env"""
    provider = config.LLM_PROVIDER.lower()
    key_map = {
        "deepseek": ("DEEPSEEK_API_KEY", config.DEEPSEEK_API_KEY, config.DEEPSEEK_BASE_URL),
        "qwen": ("QWEN_API_KEY", config.QWEN_API_KEY, config.QWEN_BASE_URL),
        "gemini": ("GEMINI_API_KEY", config.GEMINI_API_KEY, "Google AI Studio"),
        "claude": ("CLAUDE_API_KEY", config.CLAUDE_API_KEY, "Anthropic Console"),
        "volcengine": ("VOLCENGINE_API_KEY", config.VOLCENGINE_API_KEY, "火山引擎方舟控制台"),
    }
    if provider not in key_map:
        print(f"未知 provider: {provider}，跳过 key 检查")
        return

    name, key, source_hint = key_map[provider]
    if key:
        print(f"使用模型：{provider}")
        return

    print(f"\n{'='*50}")
    print(f"  当前 provider: {provider}")
    print(f"  未检测到 {name}")
    print(f"{'='*50}")
    print(f"\n请前往 {source_hint} 获取 API Key")
    print(f"获取后粘贴到下方（输入 q 放弃）：\n")

    try:
        user_input = input(f"  {name} = ").strip()
    except Exception:
        print("\n输入异常，跳过配置")
        return

    if user_input.lower() in ("q", "quit", "exit", ""):
        raise ValueError(f"未配置 {name}，操作已取消")

    if len(user_input) < 10:
        raise ValueError(f"输入的 Key 过短（{len(user_input)} 字符），请确认是否完整")

    try:
        _save_env_key(name, user_input)
        print(f"\n  已保存到 .env 文件，后续启动将自动加载\n")
    except Exception as e:
        print(f"\n  保存失败：{e}")
        print(f"  请手动在 config.py 中设置 {name}")
    print(f"使用模型：{provider}")


def generate_stream(system_prompt: str, user_prompt: str,
                    temperature: float = None,
                    max_tokens: int = None):
    """
    流式生成（yield 每个 chunk）
    目前仅支持 OpenAI 兼容接口
    """
    if temperature is None:
        temperature = config.TEMPERATURE
    if max_tokens is None:
        max_tokens = config.MAX_TOKENS
    provider = config.LLM_PROVIDER.lower()
    base_url, api_key, model, api_type = _get_provider_config(provider)

    if api_type != "openai":
        # 非流式降级为普通生成
        yield generate(system_prompt, user_prompt, temperature, max_tokens)
        return

    client = _get_client(base_url, api_key)

    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        chunks = []
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=config.TOP_P,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    chunks.append(delta)
            # 全部收集成功后才 yield，避免重试时重复输出
            for delta in chunks:
                yield delta
            return
        except Exception as e:
            last_exc = e
            if not _is_retryable(e):
                raise
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"LLM 流式调用失败（第{attempt+1}次），{delay}秒后重试: {e}")
                time.sleep(delay)
            else:
                logger.error(f"LLM 流式调用失败（已重试{MAX_RETRIES}次）: {e}")
    raise last_exc


# ========== 公共 JSON 解析工具（供 planner/writer 等模块共用）==========


def parse_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON 对象，多层 fallback + 栈匹配 + 截断修复"""
    # 第1层：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 第2层：提取 markdown 代码块
    match = _JSON_BLOCK_PATTERN.search(text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # 第3层：用栈算法找到第一个完整闭合的 JSON 对象
    result = _extract_first_json_object(text)
    if result is not None:
        return result
    # 第4层：检测截断并尝试补全闭合括号
    result = _repair_truncated_json(text)
    if result is not None:
        return result
    return None


def _repair_truncated_json(text: str) -> Optional[dict]:
    """检测被截断的 JSON，尝试补全闭合括号后解析"""
    start = text.find('{')
    if start == -1:
        return None
    partial = text[start:]

    stack = []
    in_string = False
    escape = False
    for ch in partial:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{':
                stack.pop()
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()

    open_braces = sum(1 for c in stack if c == '{')
    open_brackets = sum(1 for c in stack if c == '[')
    if open_braces == 0 and open_brackets == 0:
        return None

    repaired = partial + '}' * open_braces + ']' * open_brackets
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        return None


def _extract_first_json_object(text: str) -> Optional[dict]:
    """用栈算法从文本中提取第一个完整闭合的 JSON 对象"""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
    return None


def parse_json_array(text: str) -> list:
    """从 LLM 输出中提取 JSON 数组，多层 fallback"""
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_PATTERN.search(text)
    if match:
        try:
            result = json.loads(match.group(1))
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            pass
    return []
