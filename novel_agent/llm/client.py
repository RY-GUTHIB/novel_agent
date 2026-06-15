"""
generator.py - LLM调用封装（多后端支持）

统一接口：
    response = generate(prompt, system_prompt=..., temperature=...)
"""

import os
import json
import time
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
    if provider not in ("deepseek", "qwen", "ollama"):
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
    else:  # ollama
        client = OpenAI(base_url=config.OLLAMA_BASE_URL, api_key="ollama")
        model = config.OLLAMA_MODEL

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
            yield delta
