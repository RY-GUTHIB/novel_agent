"""
Flet 应用根。初始化主题、注册路由、绑定全局状态。
"""
import flet as ft
from novel_agent.gui.state import AppState
from novel_agent.gui.theme import AppTheme
from novel_agent.gui.views.dashboard import DashboardView
from novel_agent.gui.views.writing_pipeline import WritingPipelineView
from novel_agent.gui.views.settings import SettingsView
from novel_agent.gui.views.outline_view import OutlineView
from novel_agent.gui.views.review_view import ReviewView
from novel_agent.gui.views.visualization import VisualizationView


def main():
    ft.app(target=_page_init)


_VIEW_CACHE = {}

def _page_init(page: ft.Page):
    page.title = "novel_agent - 网文AI写作助手"
    page.theme = AppTheme.get_page_theme()
    page.window.width = 1400
    page.window.height = 900
    page.window.min_width = 1000
    page.window.min_height = 700
    page.padding = 0

    state = AppState(page=page)
    state._navigate = None  # will be set after switch_view is defined

    # ===== 底部导航栏 =====
    nav_items = [
        ft.NavigationBarDestination(icon=ft.Icons.HOME_OUTLINED,
                                    selected_icon=ft.Icons.HOME, label="工作台"),
        ft.NavigationBarDestination(icon=ft.Icons.MENU_BOOK_OUTLINED,
                                    selected_icon=ft.Icons.MENU_BOOK, label="大纲"),
        ft.NavigationBarDestination(icon=ft.Icons.EDIT_OUTLINED,
                                    selected_icon=ft.Icons.EDIT, label="写作"),
        ft.NavigationBarDestination(icon=ft.Icons.FACT_CHECK_OUTLINED,
                                    selected_icon=ft.Icons.FACT_CHECK, label="审校"),
        ft.NavigationBarDestination(icon=ft.Icons.VISIBILITY_OUTLINED,
                                    selected_icon=ft.Icons.VISIBILITY, label="可视化"),
    ]

    # ===== 内容容器 =====
    content_area = ft.Container(expand=True, padding=20)

    def get_view(idx):
        if idx in _VIEW_CACHE:
            return _VIEW_CACHE[idx]
        if idx == 0:
            v = DashboardView(state, page)
        elif idx == 1:
            v = OutlineView(state, page)
        elif idx == 2:
            v = WritingPipelineView(state, page)
        elif idx == 3:
            v = ReviewView(state, page)
        elif idx == 4:
            v = VisualizationView(state, page)
        elif idx == 5:
            v = SettingsView(state, page)
        else:
            v = DashboardView(state, page)
        _VIEW_CACHE[idx] = v
        return v

    def switch_view(idx):
        state.current_tab = idx
        v = get_view(idx)
        content_area.content = v
        try:
            v.did_mount()
        except RuntimeError:
            pass
        if idx < 5:
            page.navigation_bar.selected_index = idx
        page.update()

    state._navigate = switch_view

    def on_nav_change(e):
        switch_view(e.control.selected_index)

    bottom_nav = ft.NavigationBar(
        destinations=nav_items,
        on_change=on_nav_change,
        selected_index=0,
    )

    project_title_ref = ft.Text("项目: 《无》", size=14)

    app_bar = ft.AppBar(
        leading=ft.Icon(ft.Icons.AUTO_STORIES, color=AppTheme.PRIMARY),
        title=ft.Text("novel_agent", weight=ft.FontWeight.BOLD),
        actions=[
            project_title_ref,
            ft.VerticalDivider(width=1),
            ft.IconButton(ft.Icons.SETTINGS_OUTLINED, tooltip="设置",
                          on_click=lambda e: switch_view(5)),
            ft.IconButton(ft.Icons.NOTIFICATIONS_OUTLINED, tooltip="通知"),
        ],
    )

    state._update_title = lambda: _update_title_impl(state, project_title_ref)

    page.appbar = app_bar
    page.navigation_bar = bottom_nav
    page.add(content_area)

    # 启动时加载项目列表
    state.refresh_projects()
    switch_view(0)


def _update_title_impl(state, ref):
    title = state.novel_title or state.current_project or "无"
    ref.value = f"项目: 《{title}》"
    if state.page:
        state.page.update()



