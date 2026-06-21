"""
compat.py - Flet 0.85 兼容性适配层

Flet 0.85.3 与后续版本的部分 API 存在差异，
此模块统一处理这些差异，避免散落在各视图代码中。
"""

import flet as ft


# ===== alignment =====
# Flet 0.85 没有预定义的 alignment 常量（如 center），需手动构造。

ALIGN_CENTER = ft.alignment.Alignment(0, 0)
ALIGN_TOP_LEFT = ft.alignment.Alignment(-1, -1)
ALIGN_TOP_CENTER = ft.alignment.Alignment(0, -1)
ALIGN_TOP_RIGHT = ft.alignment.Alignment(1, -1)
ALIGN_BOTTOM_LEFT = ft.alignment.Alignment(-1, 1)
ALIGN_BOTTOM_CENTER = ft.alignment.Alignment(0, 1)
ALIGN_BOTTOM_RIGHT = ft.alignment.Alignment(1, 1)


def container_center(content, **kwargs):
    """快捷创建居中 Container（Flet 0.85 兼容）"""
    return ft.Container(content=content, alignment=ALIGN_CENTER, **kwargs)


# ===== NavigationRailDestination =====
# Flet 0.85 的 NavigationRailDestination 不支持 label_content 参数。
# label 接受 str 或 Control，但建议用字符串版本确保兼容。

def nav_dest(label: str, icon, selected_icon=None):
    """Flet 0.85 兼容的 NavigationRailDestination 工厂"""
    return ft.NavigationRailDestination(
        label=label,
        icon=icon,
        selected_icon=selected_icon or icon,
    )


# ===== 通用工具 =====

def snackbar(page: ft.Page, message: str, duration: int = 4000, color: str = None):
    """Flet 0.85 兼容的 SnackBar 显示"""
    bgcolor = color or ("red_400" if "失败" in message else None)
    sb = ft.SnackBar(
        ft.Text(message),
        duration=duration,
        bgcolor=bgcolor,
    )
    page.snack_bar = sb
    sb.open = True
    page.update()
