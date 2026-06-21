"""
流式输出查看组件。显示实时文本、字数进度、目标进度条。
"""
import flet as ft


class StreamingViewer(ft.Container):
    def __init__(self):
        super().__init__(
            bgcolor="surface_variant",
            border_radius=8,
            padding=16,
            visible=False,
        )
        self._edit_mode = False

        self.target_words = ft.TextField(
            label="目标字数", width=120, value="5000",
            text_align=ft.TextAlign.RIGHT, height=40,
        )
        self.progress_bar = ft.ProgressBar(value=0, width=400, color="primary")
        self.word_count = ft.Text("0 / 5000 字", size=14)
        self._display_text = ft.Text(
            "等待生成...", selectable=True, font_family="monospace", size=13,
        )
        self.content_display = ft.Container(
            content=ft.Column([self._display_text], scroll=ft.ScrollMode.ALWAYS),
            padding=10,
            bgcolor="black87",
            border_radius=4,
            height=300,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )
        self._edit_field = ft.TextField(
            multiline=True, min_lines=10, max_lines=20,
            expand=True, text_style=ft.TextStyle(font_family="monospace", size=13),
            visible=False,
        )

        self.content = ft.Column([
            ft.Text("步骤 2：流式生成", size=16, weight=ft.FontWeight.BOLD),
            ft.Row([
                self.target_words,
                ft.IconButton(ft.Icons.PAUSE_CIRCLE_OUTLINED, tooltip="暂停"),
                ft.IconButton(ft.Icons.STOP_CIRCLE_OUTLINED, tooltip="停止"),
                ft.TextButton("手动编辑", on_click=self._toggle_edit),
            ]),
            self.progress_bar,
            self.word_count,
            self.content_display,
            self._edit_field,
        ])

    def update_content(self, text: str, current: int, target: int):
        display_text = text[-3000:] if len(text) > 3000 else text
        self._display_text.value = display_text
        self.word_count.value = f"{current} / {target} 字"
        self.progress_bar.value = min(current / max(target, 1), 1.0)

    def show_loading(self):
        pass

    def set_edit_content(self, text: str):
        self._edit_field.value = text

    def get_edit_content(self) -> str:
        return self._edit_field.value or ""

    def _toggle_edit(self, e):
        if not self._edit_mode:
            self._edit_field.value = self._extract_text()
            self._edit_field.visible = True
            self.content_display.visible = False
            e.control.text = "返回预览"
        else:
            self._edit_field.visible = False
            self.content_display.visible = True
            e.control.text = "手动编辑"
        self._edit_mode = not self._edit_mode
        self.update()

    def _extract_text(self) -> str:
        c = self.content_display.content
        if isinstance(c, ft.Column) and c.controls:
            return c.controls[0].value or ""
        if isinstance(c, ft.Text):
            return c.value or ""
        return ""
