"""
设置面板。llm 配置、生成参数。
所有设置持久化到 config.SETTINGS_FILE (settings.json)。
"""
import json
import logging
import os
import threading
import flet as ft
import config

logger = logging.getLogger(__name__)
from novel_agent.gui.state import AppState

_PROVIDER_KEY_MAP = {
    "volcengine": "volcengine_api_key",
    "deepseek": "deepseek_api_key",
    "qwen": "qwen_api_key",
    "gemini": "gemini_api_key",
    "claude": "claude_api_key",
}
_PROVIDER_DEFAULTS = {
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-max"),
    "gemini": ("", "gemini-2.0-flash-exp"),
    "claude": ("", "claude-sonnet-4-20250514"),
    "ollama": ("http://localhost:11434/v1", "llama3.3:70b"),
    "volcengine": ("https://ark.cn-beijing.volces.com/api/coding/v3", "deepseek-v4-flash"),
}


def _load_settings() -> dict:
    try:
        if config.SETTINGS_FILE.exists():
            with open(config.SETTINGS_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("settings load failed: %s", e)
    return {}


def _save_settings_to_disk(data: dict):
    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("settings saved to %s", config.SETTINGS_FILE)


def _snackbar(page: ft.Page, message: str, color: str = "green"):
    page.snack_bar = ft.SnackBar(
        ft.Text(message, color="white"), bgcolor=color, duration=4000,
    )
    page.snack_bar.open = True
    page.update()


class SettingsView(ft.Column):
    def __init__(self, state: AppState, page: ft.Page):
        super().__init__(expand=True, spacing=16, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self.page_ref = page
        saved = _load_settings()

        # ===== llm 配置 =====
        self.provider = ft.Dropdown(
            label="provider", width=250,
            options=[
                ft.DropdownOption("deepseek", "deepseek"),
                ft.DropdownOption("qwen", "通义千问"),
                ft.DropdownOption("gemini", "gemini"),
                ft.DropdownOption("claude", "claude"),
                ft.DropdownOption("ollama", "ollama (本地)"),
                ft.DropdownOption("volcengine", "火山引擎"),
            ],
            value=saved.get("llm_provider", os.getenv("LLM_PROVIDER", "volcengine")),
            on_select=self._on_provider_change,
        )
        self.api_key = ft.TextField(
            label="api key", width=500, password=True,
            can_reveal_password=True,
            value=saved.get("volcengine_api_key",
                  saved.get("deepseek_api_key",
                  saved.get("qwen_api_key",
                  saved.get("gemini_api_key",
                  saved.get("claude_api_key", ""))))),
        )
        self.model = ft.TextField(
            label="model", width=300,
            value=saved.get("model", os.getenv("deepseek_model", "deepseek-chat")),
        )
        self.base_url = ft.TextField(
            label="base url", width=500,
            value=saved.get("base_url",
                  "https://ark.cn-beijing.volces.com/api/coding/v3"),
        )

        self._verify_btn = ft.ElevatedButton(
            "验证连接", on_click=self._verify_connection,
        )
        self.llm_card = ft.Container(
            content=ft.Column([
                ft.Text("llm 配置", size=18, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Row([self.provider, self._verify_btn]),
                self.api_key,
                ft.Row([self.model, self.base_url], spacing=12),
            ]),
            padding=20, border_radius=12, bgcolor="surface_variant",
        )

        # ===== 生成参数 =====
        temp = saved.get("temperature", config.TEMPERATURE)
        mt = saved.get("max_tokens", config.MAX_TOKENS)
        tp = saved.get("top_p", config.TOP_P)

        self.temperature = ft.Slider(label="temperature", min=0, max=2, value=temp,
                                      divisions=20, width=300,
                                      on_change=self._on_slider_change)
        self.temp_val = ft.Text(f"{temp:.2f}", size=14)
        self.max_tokens = ft.Slider(label="max tokens", min=1000, max=128000,
                                     value=mt, divisions=127, width=300,
                                     on_change=self._on_slider_change)
        self.tokens_val = ft.Text(f"{int(mt)}", size=14)
        self.top_p = ft.Slider(label="top-p", min=0, max=1, value=tp,
                                divisions=10, width=300,
                                on_change=self._on_slider_change)
        self.top_p_val = ft.Text(f"{tp:.1f}", size=14)

        self.param_card = ft.Container(
            content=ft.Column([
                ft.Text("生成参数", size=18, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Row([self.temperature, self.temp_val]),
                ft.Row([self.max_tokens, self.tokens_val]),
                ft.Row([self.top_p, self.top_p_val]),
            ]),
            padding=20, border_radius=12, bgcolor="surface_variant",
        )

        # ===== 项目路径 =====
        self.project_path = ft.TextField(
            label="项目根目录", width=500, read_only=True,
            value=str(config.PROJECTS_ROOT),
        )
        self.proj_card = ft.Container(
            content=ft.Column([
                ft.Text("项目路径", size=18, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                self.project_path,
            ]),
            padding=20, border_radius=12, bgcolor="surface_variant",
        )

        # ===== 按钮 =====
        self._save_btn = ft.FilledTonalButton("保存设置", on_click=self._save_settings)

        self.controls = [
            ft.Text("设置", size=22, weight=ft.FontWeight.BOLD),
            self.llm_card,
            self.param_card,
            self.proj_card,
            self._save_btn,
        ]

    def _on_provider_change(self, e):
        provider = self.provider.value
        url, model = _PROVIDER_DEFAULTS.get(provider, ("", ""))
        saved = _load_settings()
        env_key = _PROVIDER_KEY_MAP.get(provider, "")
        self.api_key.value = saved.get(env_key, os.getenv(env_key, "")) if env_key else ""
        self.base_url.value = url
        self.model.value = model
        self.update()

    def _on_slider_change(self, e):
        if e.control == self.temperature:
            self.temp_val.value = f"{e.control.value:.2f}"
        elif e.control == self.max_tokens:
            self.tokens_val.value = f"{int(e.control.value)}"
        elif e.control == self.top_p:
            self.top_p_val.value = f"{e.control.value:.1f}"
        self.update()

    def _verify_connection(self, e):
        self._verify_btn.text = "验证中..."
        self._verify_btn.disabled = True
        self.page_ref.update()

        def _test():
            try:
                provider = self.provider.value
                api_key = self.api_key.value
                model = self.model.value
                base_url = self.base_url.value
                if not api_key:
                    _snackbar(self.page_ref, "请先填写 API Key", "orange")
                    self._verify_btn.text = "验证连接"
                    self._verify_btn.disabled = False
                    self.page_ref.update()
                    return

                provider_u = provider.upper()
                config.LLM_PROVIDER = provider
                setattr(config, f"{provider_u}_BASE_URL", base_url)
                setattr(config, f"{provider_u}_MODEL", model)
                setattr(config, f"{provider_u}_API_KEY", api_key)

                from novel_agent.llm.client import generate
                text = generate(
                    system_prompt="你是一个助手。",
                    user_prompt="回复'ok'",
                    temperature=0.1, max_tokens=5,
                )
                if text and text.strip():
                    _snackbar(self.page_ref, "连接成功", "green")
                else:
                    _snackbar(self.page_ref, "连接失败: 返回内容为空", "red")
            except Exception as ex:
                _snackbar(self.page_ref, f"连接失败: {str(ex)[:80]}", "red")
            finally:
                self._verify_btn.text = "验证连接"
                self._verify_btn.disabled = False
                self.page_ref.update()

        threading.Thread(target=_test, daemon=True).start()

    def _save_settings(self, e):
        saved = _load_settings()
        provider = self.provider.value
        api_key_val = self.api_key.value

        data = {
            "llm_provider": provider,
            "model": self.model.value,
            "base_url": self.base_url.value,
            "temperature": self.temperature.value,
            "max_tokens": int(self.max_tokens.value),
            "top_p": self.top_p.value,
        }

        for p, key in _PROVIDER_KEY_MAP.items():
            if p == provider:
                data[key] = api_key_val
            else:
                data[key] = saved.get(key, "")

        _save_settings_to_disk(data)

        # 立即应用到运行时 config 模块
        config.LLM_PROVIDER = provider
        config.TEMPERATURE = data["temperature"]
        config.MAX_TOKENS = data["max_tokens"]
        config.TOP_P = data["top_p"]
        provider_upper = provider.upper()
        setattr(config, f"{provider_upper}_BASE_URL", self.base_url.value)
        setattr(config, f"{provider_upper}_MODEL", self.model.value)
        api_key_attr = _PROVIDER_KEY_MAP.get(provider, "")
        if api_key_attr:
            env_key = api_key_attr.upper()
            setattr(config, env_key, api_key_val)

        from novel_agent.llm.client import clear_client_cache
        clear_client_cache()

        _snackbar(self.page_ref, "设置已保存", "green")
