"""
generator.py - LLM调用封装（多后端支持）

统一接口：
    response = generate(prompt, system_prompt=..., temperature=...)
"""

import time
import json
import re
import logging
import config

logger = logging.getLogger(__name__)

# 重试配置
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # 秒，指数退避基数


def _retry(fn, *args, max_retries=MAX_RETRIES, **kwargs):
    """带指数退避的重试包装器"""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            # 不可重试的错误直接抛出
            err_str = str(e).lower()
            if any(kw in err_str for kw in ("invalid_api_key", "authentication", "permission", "401", "403")):
                raise
            if attempt < max_retries:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"LLM 调用失败（第{attempt+1}次），{delay}秒后重试: {e}")
                time.sleep(delay)
            else:
                logger.error(f"LLM 调用失败（已重试{max_retries}次）: {e}")
    raise last_exc


def _call_openai_compatible(base_url: str, api_key: str, model: str,
                              system_prompt: str, user_prompt: str,
                              temperature: float = None,
                              max_tokens: int = None) -> str:
    """调用 OpenAI 兼容接口（DeepSeek/Qwen/Ollama 均使用此格式）"""
    if temperature is None:
        temperature = config.TEMPERATURE
    if max_tokens is None:
        max_tokens = config.MAX_TOKENS
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("请先安装 openai: pip install openai>=1.0.0")

    client = OpenAI(base_url=base_url, api_key=api_key)
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
    return response.choices[0].message.content


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

    if provider == "deepseek":
        if not config.DEEPSEEK_API_KEY:
            raise ValueError("未配置 DEEPSEEK_API_KEY，请在 config.py 或环境变量中设置")
        return _retry(_call_openai_compatible,
            config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.DEEPSEEK_MODEL,
            system_prompt, user_prompt, temperature, max_tokens
        )

    elif provider == "qwen":
        if not config.QWEN_API_KEY:
            raise ValueError("未配置 QWEN_API_KEY")
        return _retry(_call_openai_compatible,
            config.QWEN_BASE_URL, config.QWEN_API_KEY, config.QWEN_MODEL,
            system_prompt, user_prompt, temperature, max_tokens
        )

    elif provider == "ollama":
        return _retry(_call_openai_compatible,
            config.OLLAMA_BASE_URL, "ollama", config.OLLAMA_MODEL,
            system_prompt, user_prompt, temperature, max_tokens
        )

    elif provider == "gemini":
        if not config.GEMINI_API_KEY:
            raise ValueError("未配置 GEMINI_API_KEY")
        return _retry(_call_gemini, system_prompt, user_prompt, temperature, max_tokens)

    elif provider == "claude":
        if not config.CLAUDE_API_KEY:
            raise ValueError("未配置 CLAUDE_API_KEY")
        return _retry(_call_claude, system_prompt, user_prompt, temperature, max_tokens)

    elif provider == "volcengine":
        if not config.VOLCENGINE_API_KEY:
            raise ValueError("未配置 VOLCENGINE_API_KEY，请在 config.py 或环境变量中设置")
        return _retry(_call_openai_compatible,
            config.VOLCENGINE_BASE_URL, config.VOLCENGINE_API_KEY, config.VOLCENGINE_MODEL,
            system_prompt, user_prompt, temperature, max_tokens
        )

    else:
        raise ValueError(f"不支持的 LLM_PROVIDER: {provider}，请在 config.py 中修改")


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
    if provider not in ("deepseek", "qwen", "ollama", "volcengine"):
        # 非流式降级为普通生成
        yield generate(system_prompt, user_prompt, temperature, max_tokens)
        return

    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("请先安装 openai: pip install openai>=1.0.0")

    if provider == "deepseek":
        client = OpenAI(base_url=config.DEEPSEEK_BASE_URL, api_key=config.DEEPSEEK_API_KEY)
        model = config.DEEPSEEK_MODEL
    elif provider == "qwen":
        client = OpenAI(base_url=config.QWEN_BASE_URL, api_key=config.QWEN_API_KEY)
        model = config.QWEN_MODEL
    elif provider == "volcengine":
        client = OpenAI(base_url=config.VOLCENGINE_BASE_URL, api_key=config.VOLCENGINE_API_KEY)
        model = config.VOLCENGINE_MODEL
    else:  # ollama
        client = OpenAI(base_url=config.OLLAMA_BASE_URL, api_key="ollama")
        model = config.OLLAMA_MODEL

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
            err_str = str(e).lower()
            if any(kw in err_str for kw in ("invalid_api_key", "authentication", "permission", "401", "403")):
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
    """从 LLM 输出中提取 JSON 对象，多层 fallback + 栈匹配避免贪婪误提取"""
    # 第1层：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 第2层：提取 markdown 代码块
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # 第3层：用栈算法找到第一个完整闭合的 JSON 对象（避免贪婪匹配吞入中间文本）
    result = _extract_first_json_object(text)
    if result is not None:
        return result
    return None


def _extract_first_json_object(text: str) -> dict | None:
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
                    # 继续找下一个闭合点
                    continue
    return None


def parse_json_array(text: str) -> list:
    """从 LLM 输出中提取 JSON 数组，多层 fallback"""
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if match:
        try:
            result = json.loads(match.group(1))
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            pass
    return []
