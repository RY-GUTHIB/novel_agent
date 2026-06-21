"""
数据管理面板。嵌套 tab 结构。
p0: 角色、伏笔（完整 crud）
p1: 地点、世界观、物品（只读表格 + 快速编辑）
p2: 其他（通用 json 编辑）
"""
import flet as ft
from novel_agent.gui.state import AppState
from novel_agent.gui.widgets.json_editor import JsonEditor
from novel_agent.gui.utils.error_handler import ErrorHandler


class DataPanelView(ft.Column):
    def __init__(self, state: AppState, page: ft.Page):
        super().__init__(expand=True)
        self.state = state
        self.page_ref = page

        self.character_editor_visible = False
        self._editing_character = None

        tab_items = [
            ft.Tab(label="角色"),
            ft.Tab(label="伏笔"),
            ft.Tab(label="地点"),
            ft.Tab(label="世界观"),
            ft.Tab(label="物品"),
            ft.Tab(label="json 编辑器"),
        ]
        tab_contents = [
            self._build_character_tab(),
            self._build_foreshadow_tab(),
            self._build_simple_table("地点"),
            self._build_simple_table("世界观"),
            self._build_simple_table("物品"),
            jsoneditor(state),
        ]
        self.tabs = ft.Tabs(
            selected_index=0,
            length=len(tab_items),
            expand=True,
            on_change=self._on_tab_change,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(tabs=tab_items),
                    ft.TabBarView(expand=True, controls=tab_contents),
                ],
            ),
        )
        self.controls = [self.tabs]

    def did_mount(self):
        try:
            self._refresh_characters()
            self._refresh_foreshadows()
            self._refresh_locations()
            self._refresh_world_settings()
            self._refresh_items()
        except RuntimeError:
            pass

    # ==================== p0: 角色 crud ====================

    def _on_tab_change(self, e):
        idx = self.tabs.selected_index
        if idx == 2:
            self._refresh_locations()
        elif idx == 3:
            self._refresh_world_settings()
        elif idx == 4:
            self._refresh_items()

    def _build_character_tab(self):
        self.char_search = ft.TextField(
            hint_text="搜索角色...", width=200, height=40,
            prefix_icon=ft.Icons.SEARCH, on_change=self._on_char_search,
        )
        self.char_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("姓名")),
                ft.DataColumn(ft.Text("性别")),
                ft.DataColumn(ft.Text("修为")),
                ft.DataColumn(ft.Text("阵营")),
                ft.DataColumn(ft.Text("所属势力")),
                ft.DataColumn(ft.Text("状态")),
                ft.DataColumn(ft.Text("操作")),
            ],
            rows=[], heading_row_height=36, data_row_max_height=38,
        )
        self.char_edit_panel = ft.Container(
            content=self._build_character_form(),
            padding=12, border_radius=8,
            bgcolor="surface_variant",
            visible=False, width=420,
        )
        return ft.Row([
            ft.Container(content=ft.Column([
                ft.Row([
                    ft.Text("角色列表", size=16, weight=ft.FontWeight.BOLD),
                    ft.FilledTonalButton("➕ 添加角色", on_click=self._add_character_click),
                    self.char_search,
                ], spacing=8),
                ft.Container(content=self.char_table, expand=True),
            ]), expand=True),
            ft.VerticalDivider(width=1),
            self.char_edit_panel,
        ], expand=True)

    def _build_character_form(self):
        self.char_name = ft.TextField(label="姓名", width=380)
        self.char_gender = ft.Dropdown(label="性别", width=180,
                                        options=[ft.DropdownOption("男"), ft.DropdownOption("女"), ft.DropdownOption("未知")])
        self.char_cultivation = ft.TextField(label="修为", width=180)
        self.char_alignment = ft.Dropdown(label="阵营", width=180,
                                           options=[ft.DropdownOption("正"), ft.DropdownOption("邪"), ft.DropdownOption("中立")])
        self.char_status = ft.Dropdown(label="状态", width=180,
                                        options=[ft.DropdownOption("alive"), ft.DropdownOption("dead"),
                                                  ft.DropdownOption("missing"), ft.DropdownOption("unknown")])
        self.char_faction = ft.TextField(label="所属势力", width=380)
        self.char_appearance = ft.TextField(label="外貌", multiline=True, min_lines=2, max_lines=4, width=380)
        self.char_personality = ft.TextField(label="性格", multiline=True, min_lines=2, max_lines=4, width=380)
        self.char_background = ft.TextField(label="背景", multiline=True, min_lines=2, max_lines=4, width=380)
        return ft.Column([
            ft.Text("角色编辑", size=15, weight=ft.FontWeight.BOLD),
            ft.Divider(height=4),
            self.char_name,
            ft.Row([self.char_gender, self.char_cultivation], spacing=8),
            ft.Row([self.char_alignment, self.char_status], spacing=8),
            self.char_faction,
            self.char_appearance,
            self.char_personality,
            self.char_background,
            ft.Row([
                ft.FilledTonalButton("💾 保存", on_click=self._save_character),
                ft.OutlinedButton("取消", on_click=self._cancel_character_edit),
                ft.TextButton("🗑 删除", on_click=self._delete_character,
                              style=ft.ButtonStyle(color="red")),
            ]),
        ], scroll=ft.ScrollMode.AUTO)

    def _refresh_characters(self, filter_text=""):
        memory = self.state._memory
        if not memory:
            self.char_table.rows = []
            self.update()
            return
        rows = []
        for name, profile in memory.characters.items():
            if filter_text and filter_text.lower() not in name.lower():
                continue
            rows.append(ft.DataRow(
                on_select_change=lambda e, n=name: self._select_character(n),
                cells=[
                    ft.DataCell(ft.Text(name, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(profile.gender)),
                    ft.DataCell(ft.Text(profile.cultivation)),
                    ft.DataCell(ft.Text(profile.alignment)),
                    ft.DataCell(ft.Text(profile.faction)),
                    ft.DataCell(ft.Text(profile.status)),
                    ft.DataCell(
                        ft.IconButton(ft.Icons.EDIT, icon_size=18,
                                      on_click=lambda e, n=name: self._select_character(n))
                    ),
                ]
            ))
        self.char_table.rows = rows
        self.update()

    def _on_char_search(self, e):
        self._refresh_characters(e.control.value)

    def _select_character(self, name):
        memory = self.state._memory
        profile = memory.characters.get(name)
        if not profile:
            return
        self._editing_character = name
        self.char_name.value = profile.name
        self.char_gender.value = profile.gender
        self.char_cultivation.value = profile.cultivation
        self.char_alignment.value = profile.alignment
        self.char_status.value = profile.status
        self.char_faction.value = profile.faction
        self.char_appearance.value = profile.appearance
        self.char_personality.value = profile.personality
        self.char_background.value = profile.background
        self.char_edit_panel.visible = True
        self.character_editor_visible = True
        self.update()

    def _save_character(self, e):
        memory = self.state._memory
        if not memory:
            return
        name = self.char_name.value
        if not name:
            return
        if self._editing_character and self._editing_character != name:
            if self._editing_character in memory.characters:
                del memory.characters[self._editing_character]
        memory.update_character_status(name, **{
            "gender": self.char_gender.value,
            "cultivation": self.char_cultivation.value,
            "alignment": self.char_alignment.value,
            "status": self.char_status.value,
            "faction": self.char_faction.value,
            "appearance": self.char_appearance.value,
            "personality": self.char_personality.value,
            "background": self.char_background.value,
        })
        self._editing_character = name
        self.char_edit_panel.visible = False
        self.character_editor_visible = False
        self._refresh_characters()

    def _cancel_character_edit(self, e):
        self.char_edit_panel.visible = False
        self.character_editor_visible = False
        self._editing_character = None
        self.update()

    def _add_character_click(self, e):
        self._editing_character = None
        self.char_name.value = ""
        self.char_gender.value = "男"
        self.char_cultivation.value = ""
        self.char_alignment.value = "正"
        self.char_status.value = "alive"
        self.char_faction.value = ""
        self.char_appearance.value = ""
        self.char_personality.value = ""
        self.char_background.value = ""
        self.char_edit_panel.visible = True
        self.character_editor_visible = True
        self.update()

    def _delete_character(self, e):
        memory = self.state._memory
        if not memory or not self._editing_character:
            return
        if self._editing_character in memory.characters:
            del memory.characters[self._editing_character]
            memory.save_characters()
        self.char_edit_panel.visible = False
        self._editing_character = None
        self._refresh_characters()

    # ==================== p0: 伏笔管理 ====================

    def _build_foreshadow_tab(self):
        self.fs_filter = ft.Dropdown(
            label="状态筛选", width=200,
            options=[
                ft.DropdownOption("all", "全部"),
                ft.DropdownOption("planted", "待回收"),
                ft.DropdownOption("resolved", "已兑现"),
                ft.DropdownOption("dropped", "已放弃"),
            ],
            value="planted", on_select=self._refresh_foreshadows,
        )
        self.fs_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("id")),
                ft.DataColumn(ft.Text("内容")),
                ft.DataColumn(ft.Text("章节")),
                ft.DataColumn(ft.Text("类型")),
                ft.DataColumn(ft.Text("角色")),
                ft.DataColumn(ft.Text("状态")),
                ft.DataColumn(ft.Text("操作")),
            ],
            rows=[], heading_row_height=36, data_row_max_height=38,
        )
        self.fs_input_content = ft.TextField(label="伏笔内容", width=400)
        self.fs_input_chapter = ft.TextField(label="章节号", width=80, value="1")
        self.fs_input_chars = ft.TextField(label="相关角色（逗号分隔）", width=300)

        return ft.Column([
            ft.Row([
                ft.Text("伏笔列表", size=16, weight=ft.FontWeight.BOLD),
                self.fs_filter,
                ft.Container(expand=True),
                ft.FilledTonalButton("➕ 种植伏笔", on_click=self._plant_foreshadow),
            ], spacing=8),
            ft.Container(content=self.fs_table, expand=True),
            ft.Divider(height=4),
            ft.Text("手动种植伏笔", size=14, weight=ft.FontWeight.BOLD),
            ft.Row([self.fs_input_chapter, self.fs_input_content, self.fs_input_chars], spacing=8),
            ft.Row([
                ft.ElevatedButton("确认种植", on_click=self._do_plant_foreshadow),
            ]),
        ], expand=True)

    def _refresh_foreshadows(self, e=None):
        fs = self.state._foreshadow
        if not fs:
            self.fs_table.rows = []
            self.update()
            return
        filter_val = self.fs_filter.value if self.fs_filter.value != "all" else None
        rows = []
        for f in fs.foreshadows:
            if filter_val and f.status != filter_val:
                continue
            status_map = {"planted": "⏳待回收", "resolved": "✅已兑现", "dropped": "❌已放弃"}
            resolve_visible = f.status == "planted"
            rows.append(ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(f.id, size=12)),
                    ft.DataCell(ft.Text(str(f.content)[:40] + ("..." if len(str(f.content)) > 40 else ""))),
                    ft.DataCell(ft.Text(str(f.chapter_planted))),
                    ft.DataCell(ft.Text(f.type)),
                    ft.DataCell(ft.Text(", ".join(f.related_characters[:3]))),
                    ft.DataCell(ft.Text(status_map.get(f.status, f.status))),
                    ft.DataCell(
                        ft.Row([
                            ft.TextButton("回收", data=f.id,
                                          visible=resolve_visible,
                                          on_click=self._resolve_fs),
                            ft.TextButton("放弃", data=f.id,
                                          visible=resolve_visible,
                                          on_click=self._drop_fs),
                        ], spacing=4)
                    ),
                ]
            ))
        self.fs_table.rows = rows
        self.update()

    def _plant_foreshadow(self, e):
        pass

    def _do_plant_foreshadow(self, e):
        fs = self.state._foreshadow
        if not fs:
            return
        chapter = int(self.fs_input_chapter.value or "1")
        content = self.fs_input_content.value
        chars = [c.strip() for c in self.fs_input_chars.value.split(",") if c.strip()]
        if not content:
            return
        fs.add_manual_fs(chapter=chapter, fs_text=content, characters=chars)
        self.fs_input_content.value = ""
        self.fs_input_chars.value = ""
        self._refresh_foreshadows()
        self.update()

    def _resolve_fs(self, e):
        fs = self.state._foreshadow
        if fs:
            fs.resolve(e.control.data, chapter=0, resolution="手动回收")
            self._refresh_foreshadows()

    def _drop_fs(self, e):
        fs = self.state._foreshadow
        if fs:
            fs.drop(e.control.data, reason="手动放弃")
            self._refresh_foreshadows()

    # ==================== p1: 简单只读表格 ====================

    def _build_simple_table(self, entity_type: str):
        if entity_type == "地点":
            return self._build_location_tab()
        if entity_type == "世界观":
            return self._build_world_setting_tab()
        if entity_type == "物品":
            return self._build_item_tab()
        return ft.Container(
            content=ft.Column([
                ft.Text(f"{entity_type}数据", size=14, color="grey_400"),
                ft.Text("完整编辑请切换到 [json 编辑器] tab", size=12, color="grey_500"),
                ft.Container(expand=True),
            ]),
            padding=20,
        )

    def _build_location_tab(self):
        self.loc_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("名称")),
                ft.DataColumn(ft.Text("类型")),
                ft.DataColumn(ft.Text("描述")),
                ft.DataColumn(ft.Text("首次出场")),
                ft.DataColumn(ft.Text("重要角色")),
                ft.DataColumn(ft.Text("连接地点")),
            ],
            rows=[], heading_row_height=36, data_row_max_height=38,
        )
        return ft.Column([
            ft.Row([
                ft.Text("地点列表", size=16, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.FilledTonalButton("🔄 刷新", on_click=self._refresh_locations),
            ], spacing=8),
            ft.Container(content=self.loc_table, expand=True),
            ft.Text("完整编辑请切换到 [json 编辑器] tab", size=12, color="grey_500"),
        ], expand=True)

    def _build_world_setting_tab(self):
        self.ws_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("键")),
                ft.DataColumn(ft.Text("值")),
                ft.DataColumn(ft.Text("首次章节")),
            ],
            rows=[], heading_row_height=36, data_row_max_height=38,
        )
        return ft.Column([
            ft.Row([
                ft.Text("世界观数据", size=16, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.FilledTonalButton("🔄 刷新", on_click=self._refresh_world_settings),
            ], spacing=8),
            ft.Container(content=self.ws_table, expand=True),
            ft.Text("完整编辑请切换到 [json 编辑器] tab", size=12, color="grey_500"),
        ], expand=True)

    def _build_item_tab(self):
        self.item_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("名称")),
                ft.DataColumn(ft.Text("类型")),
                ft.DataColumn(ft.Text("持有者")),
                ft.DataColumn(ft.Text("状态")),
                ft.DataColumn(ft.Text("首次归属")),
            ],
            rows=[], heading_row_height=36, data_row_max_height=38,
        )
        return ft.Column([
            ft.Row([
                ft.Text("物品列表", size=16, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.FilledTonalButton("🔄 刷新", on_click=self._refresh_items),
            ], spacing=8),
            ft.Container(content=self.item_table, expand=True),
            ft.Text("完整编辑请切换到 [json 编辑器] tab", size=12, color="grey_500"),
        ], expand=True)

    def _refresh_locations(self, e=None):
        memory = self.state._memory
        if not memory or not hasattr(memory, 'locations'):
            self.loc_table.rows = []
            self.update()
            return
        rows = []
        for name, loc in memory.locations.items():
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(name, weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(loc.type)),
                ft.DataCell(ft.Text(str(loc.description)[:30])),
                ft.DataCell(ft.Text(str(loc.first_appeared))),
                ft.DataCell(ft.Text(", ".join(loc.notable_characters[:3]))),
                ft.DataCell(ft.Text(", ".join(loc.connected_to[:3]))),
            ]))
        self.loc_table.rows = rows
        self.update()

    def _refresh_world_settings(self, e=None):
        memory = self.state._memory
        if not memory or not hasattr(memory, 'world_settings'):
            self.ws_table.rows = []
            self.update()
            return
        rows = []
        for key, ws in memory.world_settings.items():
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(key, weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(str(ws.value)[:50])),
                ft.DataCell(ft.Text(str(ws.chapter_introduced))),
            ]))
        self.ws_table.rows = rows
        self.update()

    def _refresh_items(self, e=None):
        memory = self.state._memory
        if not memory or not hasattr(memory, 'items'):
            self.item_table.rows = []
            self.update()
            return
        rows = []
        for name, item in memory.items.items():
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(name, weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(item.type)),
                ft.DataCell(ft.Text(item.current_holder)),
                ft.DataCell(ft.Text(item.status)),
                ft.DataCell(ft.Text(item.first_giver)),
            ]))
        self.item_table.rows = rows
        self.update()
