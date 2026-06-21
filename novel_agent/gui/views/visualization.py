"""
可视化面板。左侧选择可视化类型，右侧展示生成结果。
"""

import threading
import webbrowser
from pathlib import Path
import flet as ft
from novel_agent.gui.state import AppState
from novel_agent.gui.compat import ALIGN_CENTER, snackbar


_VIZ_ITEMS = [
    {
        "key": "timeline",
        "label": "时间线",
        "icon": ft.Icons.TIMELINE_OUTLINED,
        "icon_active": ft.Icons.TIMELINE,
        "desc": "故事事件按时间轴排列，多人物并行轨道",
        "file": "timeline.html",
    },
    {
        "key": "character_map",
        "label": "人物关系图",
        "icon": ft.Icons.HUB_OUTLINED,
        "icon_active": ft.Icons.HUB,
        "desc": "角色节点与关系连线，颜色区分阵营/状态",
        "file": "character_map.html",
    },
    {
        "key": "world_map",
        "label": "世界地图",
        "icon": ft.Icons.MAP_OUTLINED,
        "icon_active": ft.Icons.MAP,
        "desc": "地点拓扑图，类型分形状，路线标注通行时间",
        "file": "world_map.html",
    },
]

_ACTIVE_BG = "primary"
_INACTIVE_BG = "transparent"


class VisualizationView(ft.Column):
    def __init__(self, state: AppState, page: ft.Page):
        super().__init__(expand=True, spacing=0)
        self.state = state
        self.page_ref = page
        self._selected_idx = 0
        self._generated = {v["key"]: False for v in _VIZ_ITEMS}
        self._gen_stats = {}

        # ===== 左：自定义导航面板 =====
        self._nav_cards = []
        for i, v in enumerate(_VIZ_ITEMS):
            card = ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(v["icon"], size=22, color="white"),
                        ft.Text(v["label"], size=15, weight=ft.FontWeight.W_600, color="white"),
                    ], spacing=10),
                    ft.Text(v["desc"], size=10, color="grey_400"),
                ], spacing=4),
                padding=ft.Padding(left=16, top=12, right=16, bottom=12),
                border_radius=10,
                bgcolor=_ACTIVE_BG if i == 0 else _INACTIVE_BG,
                ink=True,
                on_click=lambda _, idx=i: self._on_nav_click(idx),
            )
            self._nav_cards.append(card)

        left_panel = ft.Container(
            content=ft.Column([
                ft.Text("可视化", size=18, weight=ft.FontWeight.BOLD),
                ft.Divider(height=8),
                *self._nav_cards,
                ft.Container(expand=True),
                ft.FilledTonalButton(
                    "🔄 全部重新生成",
                    on_click=self._regenerate_all,
                    expand=True,
                ),
            ], spacing=6, expand=True),
            width=220,
            bgcolor="surface_variant",
            padding=16,
        )

        # ===== 右：内容区 =====
        self._header = ft.Text("时间线", size=20, weight=ft.FontWeight.BOLD)
        self._status_text = ft.Text("", size=13, color="grey_400")
        self._content_area = ft.Container(expand=True, alignment=ALIGN_CENTER)
        self._build_placeholder()

        right_column = ft.Column([
            ft.Row([
                self._header,
                ft.Container(expand=True),
                ft.FilledTonalButton("🔄 全部重新生成", on_click=self._regenerate_all),
            ]),
            ft.Divider(height=8),
            self._status_text,
            self._content_area,
        ], expand=True, spacing=8)

        # ===== 整体布局 =====
        self.controls = [
            ft.Row([
                left_panel,
                ft.VerticalDivider(width=1),
                right_column,
            ], expand=True, spacing=0),
        ]

    # ========== 占位/内容构建 ==========

    def _build_placeholder(self):
        item = _VIZ_ITEMS[self._selected_idx]
        self._content_area.content = ft.Column([
            ft.Icon(item["icon_active"], size=64, color="grey_500"),
            ft.Text(item["label"], size=20, weight=ft.FontWeight.BOLD, color="grey_400"),
            ft.Text(item["desc"], size=13, color="grey_500"),
            ft.Container(height=16),
            ft.FilledTonalButton(
                "⚡ 生成并查看",
                icon=ft.Icons.PLAY_ARROW,
                on_click=lambda e: self._do_generate(all_viz=False),
            ),
        ], alignment=ft.MainAxisAlignment.CENTER,
           horizontal_alignment=ft.CrossAxisAlignment.CENTER,
           spacing=4)

    def _build_result(self, key: str, file_path: Path):
        stats = self._gen_stats.get(key, {})
        now_label = _VIZ_ITEMS[self._selected_idx]["label"]

        stat_rows = []
        if stats:
            for k, v in stats.items():
                stat_rows.append(
                    ft.Row([
                        ft.Text(f"{k}：", size=13, color="grey_400"),
                        ft.Text(str(v), size=13, weight=ft.FontWeight.BOLD),
                    ], spacing=4)
                )
        else:
            stat_rows.append(ft.Text("生成完成", size=13, color="grey_400"))

        self._content_area.content = ft.Column([
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.CHECK_CIRCLE, size=24, color="green"),
                        ft.Text(f"✅ {now_label} 已生成", size=16, weight=ft.FontWeight.BOLD),
                    ], spacing=8),
                    ft.Divider(height=4),
                    *stat_rows,
                    ft.Divider(height=4),
                    ft.Text("文件路径：", size=12, color="grey_500"),
                    ft.Text(str(file_path), size=12, selectable=True, color="blue"),
                    ft.Divider(height=8),
                    ft.FilledTonalButton(
                        "🌐 在浏览器中打开",
                        icon=ft.Icons.OPEN_IN_BROWSER,
                        on_click=lambda e, p=str(file_path): webbrowser.open(p),
                    ),
                ], spacing=8),
                padding=20,
                border_radius=12,
                bgcolor="surface_variant",
            ),
        ], alignment=ft.MainAxisAlignment.CENTER,
           horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    def _build_no_project(self):
        self._content_area.content = ft.Column([
            ft.Icon(ft.Icons.FOLDER_OFF_OUTLINED, size=64, color="grey_500"),
            ft.Text("请先选择项目", size=16, color="grey_500"),
            ft.Text("在「工作台」选择或创建项目后，再来生成可视化", size=13, color="grey_400"),
        ], alignment=ft.MainAxisAlignment.CENTER,
           horizontal_alignment=ft.CrossAxisAlignment.CENTER,
           spacing=8)

    # ========== 事件 ==========

    def _on_nav_click(self, idx: int):
        self._selected_idx = idx
        item = _VIZ_ITEMS[idx]
        self._header.value = item["label"]
        self._status_text.value = ""
        # 更新卡片高亮
        for i, card in enumerate(self._nav_cards):
            card.bgcolor = _ACTIVE_BG if i == idx else _INACTIVE_BG
        self._refresh_or_generate()
        self.update()

    def _refresh_or_generate(self):
        if not self.state._ctx:
            self._build_no_project()
            self.update()
            return

        item = _VIZ_ITEMS[self._selected_idx]
        key = item["key"]
        file_path = self.state._ctx.output_dir / item["file"]

        if file_path.exists() and self._generated[key]:
            self._build_result(key, file_path)
        else:
            self._do_generate(all_viz=False)

    def did_mount(self):
        try:
            self._refresh_or_generate()
        except RuntimeError:
            pass

    def _regenerate_all(self, e=None):
        if not self.state._ctx:
            return
        self._do_generate(all_viz=True)

    def _do_generate(self, all_viz=False):
        if not self.state._ctx:
            return

        memory, continuity, foreshadow, rag = self.state.get_services()
        if not memory:
            return

        def task():
            try:
                from novel_agent.visualizer import (
                    generate_timeline_html,
                    generate_character_map_html,
                    generate_world_map_html,
                )

                if all_viz:
                    targets = [(v["key"], v["file"]) for v in _VIZ_ITEMS]
                else:
                    item = _VIZ_ITEMS[self._selected_idx]
                    targets = [(item["key"], item["file"])]

                for key, fname in targets:
                    file_path = self.state._ctx.output_dir / fname
                    if key == "timeline":
                        generate_timeline_html(continuity, str(self.state._ctx.output_dir),
                                               self.state.current_project)
                        self._gen_stats[key] = {
                            "事件数": len(continuity.timeline) if continuity else 0,
                        }
                    elif key == "character_map":
                        generate_character_map_html(memory, str(self.state._ctx.output_dir),
                                                    self.state.current_project)
                        self._gen_stats[key] = {
                            "角色数": len(memory.characters) if memory else 0,
                            "关系数": len(memory.character_relations) if hasattr(memory, 'character_relations') else 0,
                        }
                    elif key == "world_map":
                        generate_world_map_html(continuity, str(self.state._ctx.output_dir),
                                                self.state.current_project)
                        space_data = continuity.export_spacemap_for_viz() if continuity else {"nodes": [], "edges": []}
                        self._gen_stats[key] = {
                            "地点数": len(space_data.get("nodes", [])),
                            "路径数": len(space_data.get("edges", [])),
                        }
                    self._generated[key] = True

                if foreshadow:
                    foreshadow.export_to_markdown(output_dir=self.state._ctx.output_dir)

                if self.page_ref:
                    snackbar(self.page_ref, "✅ 可视化生成完成！")

                self._refresh_or_generate()
                if self.page_ref:
                    self.page_ref.update()
            except Exception as ex:
                if self.page_ref:
                    snackbar(self.page_ref, f"❌ 生成失败: {ex}", duration=5000)

        self._status_text.value = "⏳ 正在生成可视化数据..."
        self.update()
        threading.Thread(target=task, daemon=True).start()
