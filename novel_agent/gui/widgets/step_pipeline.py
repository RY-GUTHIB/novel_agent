"""
步骤条组件。水平排列 4 步，高亮当前，完成标记绿色。
"""
import flet as ft


class StepPipeline(ft.Row):
    def __init__(self, steps: list, current_step: int = 0):
        super().__init__(spacing=4, alignment=ft.MainAxisAlignment.CENTER)
        self._steps = steps
        self._current = current_step
        self._completed = set()
        self._build()

    def _build(self):
        self.controls.clear()
        for i, name in enumerate(self._steps):
            if i in self._completed:
                color = "green"
                icon_name = ft.Icons.CHECK_CIRCLE
            elif i == self._current:
                color = "primary"
                icon_name = ft.Icons.RADIO_BUTTON_CHECKED
            else:
                color = "grey_500"
                icon_name = ft.Icons.RADIO_BUTTON_UNCHECKED

            dot = ft.Icon(icon_name, color=color, size=20)
            label = ft.Text(
                name, color=color, size=14,
                weight=ft.FontWeight.BOLD if i == self._current else None,
            )
            step = ft.Row([dot, label], spacing=4)
            self.controls.append(step)

            if i < len(self._steps) - 1:
                line_color = "green" if i in self._completed else "grey_400"
                self.controls.append(ft.Container(
                    width=60, height=2, bgcolor=line_color,
                    margin=ft.Margin.only(left=4, right=4),
                ))

    def set_current(self, value):
        self._current = value
        self._build()

    def complete(self, index):
        self._completed.add(index)
        self._build()
