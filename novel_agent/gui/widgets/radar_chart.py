"""
审校雷达图组件。用 stack 绘制 8 维评分多边形。
"""
import math
import flet as ft


class RadarChart(ft.Container):
    dimensions = ["一致性", "人物", "情节", "对话", "战斗", "节奏", "设定", "情感"]

    def __init__(self, scores: dict = None, size: int = 260):
        super().__init__(width=size, height=size + 30)
        self.size = size
        self.center = size // 2
        self.radius = size // 2 - 25
        self.num_axes = len(self.dimensions)
        self.angle_step = 2 * math.pi / self.num_axes
        self.scores = {}
        if scores:
            for dim in self.dimensions:
                self.scores[dim] = scores.get(dim, 5)
        else:
            self.scores = {d: 5 for d in self.dimensions}
        self._render()

    def set_scores(self, scores: dict):
        for dim in self.dimensions:
            self.scores[dim] = scores.get(dim, 5)
        self._render()

    def _render(self):
        children = []

        level_colors = ["grey_700", "grey_600", "grey_500",
                        "grey_400", "grey_300"]

        for level_idx in range(5):
            r = self.radius * (level_idx + 1) / 5
            points = []
            for i in range(self.num_axes):
                angle = -math.pi / 2 + i * self.angle_step
                x = self.center + r * math.cos(angle)
                y = self.center + r * math.sin(angle)
                points.append(f"{x},{y}")
            points.append(points[0])
            children.append(
                ft.Container(
                    width=self.size, height=self.size,
                    content=ft.Stack([ft.Text("")]),
                    border=ft.Border.all(0.5, level_colors[level_idx]),
                    border_radius=0,
                    top=0, left=0,
                )
            )

        # 轴线和标签
        for i in range(self.num_axes):
            angle = -math.pi / 2 + i * self.angle_step
            x_end = self.center + self.radius * math.cos(angle)
            y_end = self.center + self.radius * math.sin(angle)
            label_r = self.radius + 18
            lx = self.center + label_r * math.cos(angle)
            ly = self.center + label_r * math.sin(angle)
            ha = "center"
            if lx < self.center - 10:
                ha = "right"
            elif lx > self.center + 10:
                ha = "left"

            children.append(ft.Text(
                self.dimensions[i], size=10, color="grey_300",
                left=lx - 20, top=ly - 6,
            ))

        # 数据多边形点
        points = []
        for i in range(self.num_axes):
            angle = -math.pi / 2 + i * self.angle_step
            score = self.scores.get(self.dimensions[i], 5)
            r = self.radius * score / 10
            x = self.center + r * math.cos(angle)
            y = self.center + r * math.sin(angle)
            points.append((x, y))

        # 用 container 近似多边形
        for i, (x, y) in enumerate(points):
            children.append(ft.Container(
                width=8, height=8,
                bgcolor="primary",
                border_radius=4,
                left=x - 4, top=y - 4,
            ))

        self.content = ft.Stack(children, width=self.size, height=self.size)
