"""
统一错误横幅。可显示在页面顶部，支持 dismiss 和多种严重级别。
"""
import flet as ft


class ErrorBanner(ft.Container):
    def __init__(self):
        super().__init__(
            visible=False,
            padding=12,
            border_radius=8,
            margin=ft.Margin.only(bottom=8),
        )
        self._icon = ft.Icon(ft.Icons.ERROR_OUTLINE, size=20)
        self._text = ft.Text(selectable=True, size=14, expand=True)
        self._dismiss_btn = ft.IconButton(
            ft.Icons.CLOSE, icon_size=18,
            on_click=lambda e: self.hide(),
        )
        self.content = ft.Row([
            self._icon,
            self._text,
            self._dismiss_btn,
        ], vertical_alignment=ft.CrossAxisAlignment.START)

    def show(self, message: str, severity: str = "warning"):
        color_map = {
            "error":   ("red_900", "red_100", ft.Icons.ERROR_OUTLINE),
            "warning": ("amber_900", "amber_100", ft.Icons.WARNING_AMBER_OUTLINED),
            "info":    ("blue_900", "blue_100", ft.Icons.INFO_OUTLINED),
            "success": ("green_900", "green_100", ft.Icons.CHECK_CIRCLE_OUTLINE),
        }
        bg, fg, icon = color_map.get(severity, color_map["warning"])
        self.bgcolor = bg
        self._icon.name = icon
        self._icon.color = fg
        self._text.value = message
        self._text.color = fg
        self.visible = True

    def hide(self):
        self.visible = False
