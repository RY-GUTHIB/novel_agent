"""
统一错误处理。处理 LLM 超时、JSON 解析失败、API Key 无效等场景。
"""
import flet as ft


class ErrorHandler:
    RETRYABLE_KEYWORDS = ("timeout", "rate_limit", "500", "503", "connection")

    @staticmethod
    def is_retryable(error_msg: str) -> bool:
        return any(kw in error_msg.lower() for kw in ErrorHandler.RETRYABLE_KEYWORDS)

    @staticmethod
    def classify(error: Exception) -> str:
        msg = str(error)
        if "api key" in msg.lower() or "api_key" in msg.lower():
            return "API_KEY_INVALID"
        if "timeout" in msg.lower():
            return "TIMEOUT"
        if "json" in msg.lower() or "parse" in msg.lower():
            return "JSON_PARSE_ERROR"
        if "401" in msg or "403" in msg:
            return "AUTH_ERROR"
        return "UNKNOWN"

    @staticmethod
    def user_message(error: Exception) -> str:
        cls = ErrorHandler.classify(error)
        messages = {
            "API_KEY_INVALID": "API Key 无效或未配置，请前往设置页面填写有效的 Key",
            "TIMEOUT": "请求超时，请检查网络连接或稍后重试",
            "JSON_PARSE_ERROR": "AI 返回的 JSON 格式异常，已展示原始输出，您可以手动修正",
            "AUTH_ERROR": "认证失败，请检查 API Key 是否有权限访问该模型",
            "UNKNOWN": f"发生未知错误: {error}",
        }
        return messages.get(cls, messages["UNKNOWN"])

    @staticmethod
    def show_api_key_dialog(page: ft.Page):
        dlg = ft.AlertDialog(
            title=ft.Text("API Key 未配置"),
            content=ft.Text("请在设置中填写有效的 API Key 后再试"),
            actions=[
                ft.TextButton("确定"),
            ],
        )
        page.show_dialog(dlg)
        page.update()
