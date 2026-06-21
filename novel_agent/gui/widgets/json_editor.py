"""
通用 json 编辑器。用于所有 p2/p3 实体的查看和编辑。
支持格式化、校验、保存。
"""
import json
import flet as ft


data_files = [
    "characters.json", "locations.json", "world_settings.json",
    "plot_rules.json", "sect_factions.json", "items.json",
    "tasks.json", "style.json", "foreshadow.json",
    "timeline.json", "spacemap.json", "character_knowledge.json",
    "scene_events.json",
]


class JsonEditor(ft.Column):
    def __init__(self, state):
        super().__init__(expand=True)
        self.state = state

        self.path_dropdown = ft.Dropdown(
            label="选择数据文件",
            options=[ft.DropdownOption(f) for f in data_files],
            on_select=self._load_file,
            width=280,
        )
        self.editor = ft.TextField(
            multiline=True, min_lines=15, max_lines=40,
            expand=True, text_style=ft.TextStyle(font_family="monospace", size=13),
        )
        self.status_text = ft.Text("", size=12, color="grey_400")

        self.controls = [
            ft.Row([
                self.path_dropdown,
                ft.ElevatedButton("📋 格式化", on_click=self._format_json),
                ft.FilledTonalButton("💾 保存到文件", on_click=self._save_file),
                self.status_text,
            ]),
            self.editor,
        ]

    def _load_file(self, e):
        memory = self.state._memory
        if not memory or not self.path_dropdown.value:
            return
        filepath = memory.data_dir / self.path_dropdown.value
        if filepath.exists():
            data = json.loads(filepath.read_text(encoding="utf-8"))
            self.editor.value = json.dumps(data, ensure_ascii=False, indent=2)
            self.status_text.value = f"已加载 {filepath.name}"
            self.status_text.color = "green"
        else:
            self.editor.value = "{}"
            self.status_text.value = f"文件不存在，将新建"
            self.status_text.color = "amber"
        self.update()

    def _format_json(self, e):
        try:
            data = json.loads(self.editor.value)
            self.editor.value = json.dumps(data, ensure_ascii=False, indent=2)
            self.status_text.value = "json 格式正确"
            self.status_text.color = "green"
        except json.JSONDecodeError as ex:
            self.status_text.value = f"json 解析错误: {ex}"
            self.status_text.color = "red"
        self.update()

    def _save_file(self, e):
        try:
            data = json.loads(self.editor.value)
            memory = self.state._memory
            if memory and self.path_dropdown.value:
                filepath = memory.data_dir / self.path_dropdown.value
                from novel_agent.core.file_utils import atomic_write_json
                atomic_write_json(filepath, data)
                self.status_text.value = f"已保存至 {filepath.name}"
                self.status_text.color = "green"
        except json.JSONDecodeError as ex:
            self.status_text.value = f"保存失败: json 格式错误: {ex}"
            self.status_text.color = "red"
        self.update()
