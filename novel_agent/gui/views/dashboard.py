"""
工作台首页。显示项目概览、最近章节、快速操作入口。
"""
import glob
import re
import threading
from pathlib import Path
import flet as ft
from novel_agent.gui.state import AppState
from novel_agent.gui.widgets.chapter_timeline import ChapterTimeline


def _show_snackbar(page: ft.Page, message: str, duration: int = 4000):
    page.snack_bar = ft.SnackBar(ft.Text(message), duration=duration)
    page.snack_bar.open = True
    page.update()


class DashboardView(ft.Column):
    def __init__(self, state: AppState, page: ft.Page):
        super().__init__(expand=True, spacing=16, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self.page_ref = page

        # ===== 欢迎区 =====
        self.greeting = ft.Text("欢迎使用 novel_agent", size=26, weight=ft.FontWeight.BOLD)
        self.subtitle = ft.Text("请选择或创建一个项目开始写作", size=14, color="grey_400")

        # ===== 项目快捷卡片 =====
        self.project_card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.FOLDER_OPEN, size=40, color="primary"),
                    ft.Column([
                        ft.Text("当前项目", size=14, color="grey_400"),
                        ft.Text("《无》", size=20, weight=ft.FontWeight.BOLD),
                    ], spacing=2),
                    ft.Container(expand=True),
                ]),
                ft.Divider(height=8),
                ft.Row([
                    ft.FilledTonalButton("选择项目", icon=ft.Icons.FOLDER_OPEN,
                                         on_click=self._on_select_project),
                    ft.FilledTonalButton("新建项目", icon=ft.Icons.ADD,
                                         on_click=self._on_create_project),
                ]),
            ]),
            padding=20, border_radius=12, bgcolor="surface_variant", expand=True,
        )

        # ===== 进度卡片 =====
        self.progress_card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.TRENDING_UP, size=24, color="green"),
                    ft.Text("创作进度", size=16, weight=ft.FontWeight.BOLD),
                ]),
                ft.Divider(height=4),
                ft.Text("章节: 0 / 0", size=14),
                ft.ProgressBar(value=0, width=300, color="primary"),
                ft.Text("总字数: 0", size=14, color="grey_400"),
            ]),
            padding=16, border_radius=12, bgcolor="surface_variant", expand=True,
        )

        # ===== 状态卡片 =====
        self.status_card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=20, color="primary"),
                    ft.Text("世界状态", size=16, weight=ft.FontWeight.BOLD),
                ]),
                ft.Divider(height=4),
                ft.Text("角色: 0"),
                ft.Text("地点: 0"),
                ft.Text("伏笔: 0 / 0"),
            ]),
            padding=16, border_radius=12, bgcolor="surface_variant", expand=True,
        )

        # ===== 章节时间线 =====
        self.chapter_timeline = ft.Container(
            content=ft.Text("暂无项目数据", color="grey_500"),
            padding=16, border_radius=12, bgcolor="surface_variant",
        )

        # ===== 最近章节 =====
        self.recent_chapters = ft.Container(
            content=ft.Text("近期章节将在这里显示", color="grey_500"),
            padding=16, border_radius=12, bgcolor="surface_variant",
        )

        # ===== 快速操作 =====
        self.quick_actions = ft.Container(
            content=ft.Row([
                ft.FilledTonalButton("✍️ 写下一章", icon=ft.Icons.EDIT,
                                     on_click=self._go_write),
                ft.FilledTonalButton("📋 查看大纲", icon=ft.Icons.LIST,
                                     on_click=self._go_outline),
            ], spacing=12),
            padding=16, border_radius=12, bgcolor="surface_variant",
        )

        # ===== 布局组合 =====
        self.controls = [
            ft.Column([
                self.greeting,
                self.subtitle,
            ]),
            ft.Row([self.project_card, self.progress_card, self.status_card], spacing=12),
            self.quick_actions,
            ft.Text("📖 章节进度", size=16, weight=ft.FontWeight.BOLD),
            self.chapter_timeline,
            ft.Text("📄 最近章节", size=16, weight=ft.FontWeight.BOLD),
            self.recent_chapters,
        ]

    def did_mount(self):
        try:
            self.refresh()
        except RuntimeError:
            pass  # not yet mounted in page tree

    def refresh(self):
        state = self.state
        state.refresh_projects()

        if not state.current_project:
            self.greeting.value = "欢迎使用 novel_agent"
            self.subtitle.value = "请先选择或创建一个项目"
            self._disable_actions()
            self._update_card_no_project()
            if self.page:
                self.update()
            return

        self.greeting.value = f"📖 《{state.novel_title or state.current_project}》"

        existing = set()
        if state._ctx:
            files = glob.glob(str(state._ctx.chapters_dir / "chapter_*.md"))
            for f in files:
                stem = Path(f).stem
                parts_id = stem.split("_")
                if len(parts_id) > 1 and parts_id[1].isdigit():
                    existing.add(int(parts_id[1]))

        genre = getattr(state, '_project_genre', '') or ''
        style = getattr(state, '_project_style', '') or ''
        parts = []
        if genre:
            parts.append(f"类型: {genre}")
        if style:
            parts.append(f"风格: {style}")
        parts.append(f"已写: {len(existing)} 章")
        self.subtitle.value = " · ".join(parts)

        memory, continuity, foreshadow, rag = state.get_services()

        # 更新项目卡片
        self.project_card.content = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.FOLDER_OPEN, size=40, color="primary"),
                ft.Column([
                    ft.Text("当前项目", size=14, color="grey_400"),
                    ft.Text(f"《{state.novel_title or state.current_project}》",
                            size=20, weight=ft.FontWeight.BOLD),
                ], spacing=2),
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.MORE_VERT, tooltip="更多"),
            ]),
            ft.Divider(height=8),
            ft.Row([
                ft.FilledTonalButton("切换项目", icon=ft.Icons.SWAP_HORIZ,
                                     on_click=self._on_select_project),
                ft.FilledTonalButton("项目设置", icon=ft.Icons.SETTINGS,
                                     on_click=self._go_settings),
            ]),
        ])

        # 更新进度
        total_chars = 0
        if state._ctx:
            for f in glob.glob(str(state._ctx.chapters_dir / "chapter_*.md")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        content = fh.read()
                    total_chars += len(re.sub(r'\s+', '', content))
                except Exception:
                    pass

        total = len(state.chapter_plan)
        written = len(existing)
        progress_val = written / max(total, 1)

        if total_chars >= 10000:
            word_str = f"{total_chars / 10000:.1f}万字"
        else:
            word_str = f"{total_chars}字"

        self.progress_card.content = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.TRENDING_UP, size=24, color="green"),
                ft.Text("创作进度", size=16, weight=ft.FontWeight.BOLD),
            ]),
            ft.Divider(height=4),
            ft.Text(f"章节: {written} / {total}", size=14),
            ft.ProgressBar(value=progress_val, width=300, color="primary"),
            ft.Text(f"总字数: {word_str}", size=14, color="grey_400"),
        ])

        # 更新时间线（可点击跳转）
        if state.chapter_plan:
            timeline = ChapterTimeline(state.chapter_plan, existing,
                                       on_chapter_click=self._go_chapter)
            self.chapter_timeline.content = timeline
        else:
            self.chapter_timeline.content = ft.Text("大纲未生成", color="grey_500")

        # 更新世界状态
        char_count = len(memory.characters) if memory else 0
        loc_count = len(memory.locations) if memory else 0
        ws_count = len(memory.world_settings) if memory else 0
        item_count = len(memory.items) if memory else 0
        timeline_events = len(continuity.timeline) if continuity else 0
        fs_total = len(foreshadow.foreshadows) if foreshadow else 0
        fs_pending = len(foreshadow.get_pending()) if foreshadow else 0
        self.status_card.content = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, size=20, color="primary"),
                ft.Text("世界状态", size=16, weight=ft.FontWeight.BOLD),
            ]),
            ft.Divider(height=4),
            ft.Text(f"角色: {char_count}"),
            ft.Text(f"地点: {loc_count}"),
            ft.Text(f"世界观: {ws_count}  物品: {item_count}"),
            ft.Text(f"时间线事件: {timeline_events}"),
            ft.Text(f"伏笔: {fs_total}（待回收 {fs_pending}）"),
        ])

        # 启用操作按钮
        has_outline = bool(state.outline)
        for btn in self.quick_actions.content.controls:
            btn.disabled = not has_outline

        # 最近章节
        if state._ctx:
            files = sorted(glob.glob(str(state._ctx.chapters_dir / "chapter_*.md")), reverse=True)[:5]
            if files:
                recent_rows = []
                for f in files:
                    fname = Path(f).name
                    ch_num = Path(f).stem.split("_")[1]
                    title = ""
                    for c in state.chapter_plan:
                        if str(c.get("chapter")) == ch_num:
                            title = c.get("title", "")
                            break
                    ch_num_int = int(ch_num) if ch_num.isdigit() else 0
                    row = ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.DESCRIPTION, size=16, color="primary"),
                            ft.Text(f"第{ch_num}章 {title}", size=13, expand=True),
                            ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color="grey_400"),
                        ]),
                        padding=ft.Padding.only(left=8, top=4, right=8, bottom=4),
                        border_radius=6,
                        on_click=lambda e, num=ch_num_int: self._go_chapter(num),
                        ink=True,
                    )
                    recent_rows.append(row)
                self.recent_chapters.content = ft.Column(recent_rows, spacing=2)
            else:
                self.recent_chapters.content = ft.Text("还没有已写的章节", color="grey_500")

        self.update()

    def _disable_actions(self):
        for btn in self.quick_actions.content.controls:
            btn.disabled = True

    def _update_card_no_project(self):
        self.project_card.content = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.FOLDER_OPEN, size=40, color="primary"),
                ft.Column([
                    ft.Text("当前项目", size=14, color="grey_400"),
                    ft.Text("《无》", size=20, weight=ft.FontWeight.BOLD),
                ], spacing=2),
            ]),
            ft.Divider(height=8),
            ft.Row([
                ft.FilledTonalButton("选择项目", icon=ft.Icons.FOLDER_OPEN,
                                     on_click=self._on_select_project),
                ft.FilledTonalButton("新建项目", icon=ft.Icons.ADD,
                                     on_click=self._on_create_project),
            ]),
        ])

    # ===== 导航 =====

    def _go_write(self, e):
        self.state._pending_auto_write = True
        if hasattr(self.state, '_navigate') and callable(self.state._navigate):
            self.state._navigate(2)

    def _go_chapter(self, chapter_num: int):
        self.state.current_chapter = chapter_num
        if hasattr(self.state, '_navigate') and callable(self.state._navigate):
            self.state._navigate(2)

    def _go_outline(self, e):
        if hasattr(self.state, '_navigate') and callable(self.state._navigate):
            self.state._navigate(1)

    def _go_settings(self, e):
        if hasattr(self.state, '_navigate') and callable(self.state._navigate):
            self.state._navigate(4)

    def _on_select_project(self, e):
        from novel_agent.gui.views.project_list import ProjectListDialog
        dlg = ProjectListDialog(self.state, self.page_ref, on_selected=self.refresh)
        dlg.open_dialog()

    def _on_create_project(self, e):
        from novel_agent.gui.views.project_list import ProjectListDialog
        dlg = ProjectListDialog(self.state, self.page_ref, on_selected=self.refresh)
        dlg._switch_to_create()
        self.page_ref.show_dialog(dlg)
