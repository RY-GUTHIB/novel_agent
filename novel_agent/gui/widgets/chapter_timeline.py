"""
章节时间线组件。显示所有章节的进度状态（待写/已写/已审校）。
"""
import flet as ft


class ChapterTimeline(ft.Container):
    status_colors = {
        "pending": "grey_600",
        "written": "primary",
        "reviewed": "green",
    }

    def __init__(self, chapter_plan: list, existing: set = None, reviewed: set = None,
                 on_chapter_click=None):
        super().__init__(padding=10, border_radius=8, bgcolor="surface_variant")
        self.chapter_plan = chapter_plan
        self.existing = existing or set()
        self.reviewed = reviewed or set()
        self.on_chapter_click = on_chapter_click
        self._build()

    def _build(self):
        items = []
        for ch in self.chapter_plan:
            num = ch.get("chapter", 0)
            title = ch.get("title", f"第{num}章")[:10]

            if num in self.reviewed:
                status = "reviewed"
                icon_name = ft.Icons.CHECK_CIRCLE
            elif num in self.existing:
                status = "written"
                icon_name = ft.Icons.RADIO_BUTTON_CHECKED
            else:
                status = "pending"
                icon_name = ft.Icons.RADIO_BUTTON_UNCHECKED

            color = self.status_colors[status]
            items.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(icon_name, color=color, size=14),
                        ft.Text(f"第{num}章", size=11, color=color),
                    ], spacing=2),
                    border=ft.Border.all(0.5, "grey_700"),
                    border_radius=4,
                    padding=ft.Padding.only(left=4, right=4, top=2, bottom=2),
                    tooltip=title,
                    on_click=lambda e, n=num: self._on_click(n),
                    ink=True,
                )
            )

        self.content = ft.Row(items, wrap=True, spacing=4, run_spacing=4)

    def _on_click(self, chapter_num):
        if self.on_chapter_click:
            self.on_chapter_click(chapter_num)

    def update_data(self, chapter_plan: list, existing: set = None, reviewed: set = None,
                    on_chapter_click=None):
        if chapter_plan:
            self.chapter_plan = chapter_plan
        if existing is not None:
            self.existing = existing
        if reviewed is not None:
            self.reviewed = reviewed
        if on_chapter_click is not None:
            self.on_chapter_click = on_chapter_click
        self._build()
