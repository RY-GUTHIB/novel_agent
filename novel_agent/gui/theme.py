"""
主题样式配置。集中管理颜色、字体、间距，方便全局更换。
"""
import flet as ft


class AppTheme:
    PRIMARY = "indigo"
    SURFACE = "grey_900"
    SURFACE_VARIANT = "grey_850"
    ERROR = "red_400"
    SUCCESS = "green_400"
    WARNING = "amber_400"

    @staticmethod
    def get_page_theme():
        return ft.Theme(
            color_scheme_seed=AppTheme.PRIMARY,
            use_material3=True,
        )

    @staticmethod
    def card(bgcolor=None):
        return ft.Container(
            bgcolor=bgcolor or AppTheme.SURFACE_VARIANT,
            border_radius=8,
            padding=16,
        )

    @staticmethod
    def section_title(text: str, size: int = 16):
        return ft.Text(text, size=size, weight=ft.FontWeight.BOLD)

    @staticmethod
    def monospace():
        return ft.TextStyle(font_family="monospace", size=13)
