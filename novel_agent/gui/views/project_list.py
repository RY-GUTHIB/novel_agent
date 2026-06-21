"""
项目管理对话框：显示项目列表、新建、切换、删除。
"""
import json
import threading
import flet as ft
from novel_agent.gui.state import AppState


def _show_snackbar(page: ft.Page, message: str, duration: int = 4000):
    page.snack_bar = ft.SnackBar(ft.Text(message), duration=duration)
    page.snack_bar.open = True
    page.update()


class ProjectListDialog(ft.AlertDialog):
    def __init__(self, state: AppState, page: ft.Page, on_selected=None):
        super().__init__()
        self.state = state
        self.page_ref = page
        self.on_selected = on_selected
        self.title = ft.Text("选择小说项目")

        self.project_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("名称")),
                ft.DataColumn(ft.Text("文件夹")),
                ft.DataColumn(ft.Text("类型")),
                ft.DataColumn(ft.Text("风格")),
                ft.DataColumn(ft.Text("章节")),
                ft.DataColumn(ft.Text("操作")),
            ],
            rows=[],
            expand=True,
            heading_row_height=36,
            data_row_max_height=40,
        )

        self.content = ft.Container(
            content=ft.Column([
                ft.Container(content=self.project_table, expand=True),
                ft.Divider(height=4),
                ft.Row([
                    ft.FilledTonalButton("新建项目", icon=ft.Icons.ADD,
                                         on_click=self._show_create_form),
                    ft.OutlinedButton("取消", on_click=self._close),
                ], alignment=ft.MainAxisAlignment.END),
            ], width=780, height=420),
        )

    def _safe_update(self):
        if self.page_ref:
            self.page_ref.update()

    def _refresh_table(self):
        from novel_agent.project import list_projects
        projects = list_projects()
        rows = []
        for p in projects:
            is_current = p["name"] == self.state.current_project
            name_style = ft.Text(
                p["display_name"],
                weight=ft.FontWeight.BOLD if is_current else None,
                color="primary" if is_current else None,
            )
            action_btn = (
                ft.Text("当前", color="green", size=13)
                if is_current
                else ft.TextButton("切换", data=p["name"], on_click=self._on_switch)
            )
            rows.append(ft.DataRow(
                cells=[
                    ft.DataCell(name_style),
                    ft.DataCell(ft.Text(p["name"], size=12, color="grey_500")),
                    ft.DataCell(ft.Text(p.get("type", ""))),
                    ft.DataCell(ft.Text(p.get("style", ""))),
                    ft.DataCell(ft.Text(f"{p.get('chapters', 0)} 章")),
                    ft.DataCell(action_btn),
                ]
            ))
        self.project_table.rows = rows
        if not projects:
            self.project_table.rows = [ft.DataRow(
                cells=[ft.DataCell(ft.Text("暂无项目，点击下方新建", color="grey_500"))] * 6
            )]

    def open_dialog(self):
        self._refresh_table()
        self.page_ref.show_dialog(self)
        self._safe_update()

    def _on_switch(self, e):
        name = e.control.data
        self._close(None)
        self.state.switch_project(name)
        _show_snackbar(self.page_ref, f"已切换到项目: {name}")
        if self.on_selected:
            self.on_selected()

    def _show_create_form(self, e):
        name_field = ft.TextField(label="小说名称", width=320, autofocus=True)
        type_field = ft.Dropdown(
            label="类型", width=200,
            options=[ft.DropdownOption(t) for t in
                     ["玄幻", "仙侠", "都市", "科幻", "奇幻", "历史", "游戏", "武侠"]],
            value="玄幻",
        )
        style_field = ft.Dropdown(
            label="风格", width=200,
            options=[ft.DropdownOption(s) for s in
                     ["热血", "轻松", "黑暗", "搞笑", "烧脑", "治愈", "史诗"]],
            value="热血",
        )
        concept_field = ft.TextField(
            label="构思描述", multiline=True, min_lines=3, max_lines=6,
            width=540, hint_text="输入故事的核心构思...",
        )
        gen_outline = ft.Checkbox(label="创建后立即生成大纲", value=True)

        def do_create(e):
            name = name_field.value
            if not name or not name.strip():
                return
            from novel_agent.project import create_project
            create_project(name.strip(), type_field.value, style_field.value, concept_field.value or "")
            self.state.refresh_projects()
            self.state.switch_project(name.strip())

            if gen_outline.value:
                _show_snackbar(self.page_ref, "项目已创建，正在生成大纲...（约1-2分钟）", 3000)
                thread = threading.Thread(target=self._generate_outline_async,
                                         args=(name.strip(), type_field.value, style_field.value,
                                               concept_field.value or ""),
                                         daemon=True)
                thread.start()

                def poll_outline():
                    import time
                    while thread.is_alive():
                        time.sleep(0.5)
                    # 大纲生成完成，读取 LLM 建议标题
                    try:
                        ctx = self.state._ctx
                        if ctx:
                            outline_path = ctx.data_dir / "outline.json"
                            if outline_path.exists():
                                with open(outline_path, encoding="utf-8") as f:
                                    outline_data = json.load(f)
                                llm_title = outline_data.get("meta", {}).get("title",
                                            outline_data.get("title", ""))
                                if llm_title and llm_title != name.strip():
                                    from novel_agent.project import save_project_config
                                    cfg = {"project_name": name.strip(),
                                           "novel_title": llm_title,
                                           "type": type_field.value,
                                           "style": style_field.value,
                                           "concept": concept_field.value or ""}
                                    save_project_config(name.strip(), cfg)
                                    self.state.novel_title = llm_title
                                    self.state._update_title()
                                    _show_snackbar(
                                        self.page_ref,
                                        f"大纲已生成，LLM 建议标题: 《{llm_title}》", 6000)
                                else:
                                    _show_snackbar(self.page_ref, "大纲已生成完成", 3000)
                    except Exception:
                        _show_snackbar(self.page_ref, "大纲已生成完成", 3000)

                threading.Thread(target=poll_outline, daemon=True).start()
            else:
                _show_snackbar(self.page_ref, "项目已创建", 2000)

            if self.on_selected:
                self.on_selected()
            self._close(None)

        def do_cancel(e):
            self._switch_to_list()

        form = ft.Column([
            ft.Text("新建小说项目", size=18, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            name_field,
            ft.Row([type_field, style_field], spacing=12),
            concept_field,
            gen_outline,
            ft.Row([
                ft.FilledTonalButton("创建", on_click=do_create),
                ft.OutlinedButton("取消", on_click=do_cancel),
            ], alignment=ft.MainAxisAlignment.END),
        ], width=560, height=380)

        self.title = ft.Text("")
        self.content = ft.Container(content=form)
        self._safe_update()

    def _generate_outline_async(self, project_name, genre, style, concept):
        import config
        config.set_project(project_name)
        memory, continuity, foreshadow, rag = self.state.get_services()
        if memory:
            from novel_agent.cli.commands import generate_outline
            generate_outline(memory, continuity, foreshadow, project_name, genre, style, concept)

    def _switch_to_create(self):
        self._show_create_form(None)

    def _switch_to_list(self):
        self.title = ft.Text("选择小说项目")
        self._refresh_table()
        self.content = ft.Container(
            content=ft.Column([
                ft.Container(content=self.project_table, expand=True),
                ft.Divider(height=4),
                ft.Row([
                    ft.FilledTonalButton("新建项目", icon=ft.Icons.ADD,
                                         on_click=self._show_create_form),
                    ft.OutlinedButton("取消", on_click=self._close),
                ], alignment=ft.MainAxisAlignment.END),
            ], width=640, height=420),
        )
        self._safe_update()

    def _close(self, e):
        self.open = False
        if self.page_ref:
            self.page_ref.update()
