"""
审校独立视图。选择已写章节 → 执行审校 → 显示评分/问题/验证结果。
前端实现，后端调用 revieweragent + contractvalidator（已有）。
"""
import glob
import json
import queue
import threading
from pathlib import Path
import flet as ft
from novel_agent.gui.state import AppState
from novel_agent.gui.widgets.error_banner import ErrorBanner
from novel_agent.gui.widgets.radar_chart import RadarChart


class ReviewView(ft.Column):
    def __init__(self, state: AppState, page: ft.Page):
        super().__init__(expand=True, spacing=12, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self.page_ref = page

        # ===== 章节选择 =====
        self.chapter_dropdown = ft.Dropdown(
            label="选择已写章节", width=280,
            on_select=self._on_chapter_select,
        )
        self.review_btn = ft.FilledTonalButton(
            "🔍 开始审校", icon=ft.Icons.FACT_CHECK,
            on_click=self._start_review, disabled=True,
        )
        self.validate_btn = ft.OutlinedButton(
            "📋 后验校验 (contractvalidator)", icon=ft.Icons.VERIFIED,
            on_click=self._run_validator, disabled=True,
        )

        # ===== 章节预览 =====
        self.chapter_preview = ft.Container(
            content=ft.Text("选择章节后显示内容预览", color="grey_500"),
            padding=12, border_radius=8, bgcolor="surface_variant",
            height=200, visible=False,
        )

        # ===== 审校结果区域 =====
        self.score_text = ft.Text("总分: --/100", size=22, weight=ft.FontWeight.BOLD)
        self.verdict_badge = ft.Container(
            content=ft.Text("待审校", color="white"),
            padding=ft.Padding.only(left=16, right=16, top=6, bottom=6),
            border_radius=12, bgcolor="grey_600",
        )

        # 雷达图
        self.radar = RadarChart(size=240)

        # 维度评分表
        self.score_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("维度")),
                ft.DataColumn(ft.Text("分数")),
                ft.DataColumn(ft.Text("评定")),
            ],
            rows=[], heading_row_height=32,
        )

        # 问题列表
        self.issue_list = ft.Column([ft.Text("暂无问题", color="grey_500")])

        # 原始审校报告
        self.raw_report = ft.Container(
            content=ft.Text("", selectable=True, font_family="monospace", size=12),
            padding=12, border_radius=8, bgcolor="black87",
            visible=False, height=300,
        )

        self.result_card = ft.Container(
            content=ft.Column([
                ft.Text("审校结果", size=18, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Row([
                    ft.Column([
                        ft.Row([self.score_text, self.verdict_badge], spacing=16),
                        ft.Container(height=10),
                        ft.Text("评分分布", size=14, weight=ft.FontWeight.BOLD),
                        self.score_table,
                    ], expand=2),
                    ft.Container(width=20),
                    ft.Column([
                        ft.Text("评分雷达图", size=14, weight=ft.FontWeight.BOLD),
                        self.radar,
                    ], expand=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                ]),
                ft.Divider(),
                ft.Text("发现问题", size=14, weight=ft.FontWeight.BOLD),
                self.issue_list,
                ft.Divider(),
                ft.Row([
                    ft.ElevatedButton("📄 展开原始报告", on_click=self._toggle_raw),
                ]),
                self.raw_report,
            ]),
            padding=20, border_radius=12, bgcolor="surface_variant",
            visible=False,
        )

        # ===== 验证结果 =====
        self.validation_card = ft.Container(
            content=ft.Column([
                ft.Text("后验校验 (contractvalidator)", size=16, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Text("尚未运行", color="grey_500"),
            ]),
            padding=16, border_radius=12, bgcolor="surface_variant",
            visible=False,
        )

        # ===== 错误横幅 =====
        self.error = ErrorBanner()

        # ===== 加载状态 =====
        self.loading = ft.ProgressBar(visible=False)

        self.controls = [
            ft.Text("📋 ai 审校", size=22, weight=ft.FontWeight.BOLD),
            ft.Row([
                self.chapter_dropdown,
                self.review_btn,
                self.validate_btn,
            ], spacing=12),
            self.chapter_preview,
            self.loading,
            self.error,
            self.result_card,
            self.validation_card,
        ]

        self._selected_chapter = None
        self._chapter_content = ""

    def did_mount(self):
        try:
            self._refresh_chapters()
        except RuntimeError:
            pass

    def _refresh_chapters(self):
        if not self.state._ctx:
            self.chapter_dropdown.options = [ft.DropdownOption("", "请先选择项目")]
            self.update()
            return
        files = sorted(glob.glob(str(self.state._ctx.chapters_dir / "chapter_*.md")))
        options = []
        for f in files:
            stem = Path(f).stem
            try:
                ch_num = int(stem.split("_")[1])
                title = ""
                for c in self.state.chapter_plan:
                    if c.get("chapter") == ch_num:
                        title = c.get("title", "")
                        break
                label = f"第{ch_num}章 {title}".strip()
                options.append(ft.DropdownOption(key=str(ch_num), text=label))
            except (IndexError, ValueError):
                continue
        self.chapter_dropdown.options = options if options else [ft.DropdownOption("", "暂无已写章节")]
        self.review_btn.disabled = not bool(options)
        self.validate_btn.disabled = not bool(options)
        self.update()

    def _on_chapter_select(self, e):
        if not self.chapter_dropdown.value:
            return
        ch_num = int(self.chapter_dropdown.value)
        self._selected_chapter = ch_num
        self._load_chapter_preview(ch_num)
        self.result_card.visible = False
        self.validation_card.visible = False
        self.review_btn.disabled = False
        self.validate_btn.disabled = False
        self.update()

    def _load_chapter_preview(self, ch_num):
        if not self.state._ctx:
            return
        path = self.state._ctx.chapters_dir / f"chapter_{ch_num:03d}.md"
        if path.exists():
            content = path.read_text(encoding="utf-8")
            self._chapter_content = content
            preview = content[:500] + ("..." if len(content) > 500 else "")
            self.chapter_preview.content = ft.Column([
                ft.Text(f"第{ch_num}章 预览（前500字）", size=14, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=ft.Text(preview, selectable=True, size=13, font_family="monospace"),
                    padding=8, bgcolor="black87", border_radius=4, expand=True,
                ),
            ], expand=True)
            self.chapter_preview.visible = True
        else:
            self.chapter_preview.visible = False

    # ===== 审校 =====

    def _start_review(self, e):
        if not self._selected_chapter or not self._chapter_content:
            return

        self.loading.visible = True
        self.error.hide()
        self.result_card.visible = False
        self.update()

        _result = [None]
        _error = [None]
        _DONE = object()
        _queue = queue.Queue()

        def do_review():
            try:
                memory, continuity, foreshadow, rag = self.state.get_services()
                from novel_agent.agents.reviewer import ReviewerAgent
                from novel_agent.llm.client import check_api_key
                check_api_key()

                ch_data = None
                for c in self.state.chapter_plan:
                    if c.get("chapter") == self._selected_chapter:
                        ch_data = c
                        break

                reviewer = ReviewerAgent(memory, continuity, foreshadow)
                report = reviewer.review_chapter(
                    self._selected_chapter,
                    ch_data.get("title", "") if ch_data else "",
                    self._chapter_content,
                    characters=ch_data.get("characters", []) if ch_data else [],
                )
                _result[0] = (report, ch_data)
            except Exception as ex:
                _error[0] = ex
            finally:
                _queue.put(_DONE)

        self.loading.visible = True
        self.update()
        thread = threading.Thread(target=do_review, daemon=True)
        thread.start()

        import asyncio, threading
        async def _wait_for_review():
            loop = asyncio.get_running_loop()
            while thread.is_alive() or not _queue.empty():
                try:
                    _queue.get(timeout=0.1)
                    break
                except queue.Empty:
                    await asyncio.sleep(0.1)
            thread.join(timeout=5)
            self.loading.visible = False
            if _error[0]:
                self.error.show(str(_error[0]), "error")
            elif _result[0]:
                report, ch_data = _result[0]
                self._display_review(report, ch_data)
            self.update()

        threading.Thread(target=lambda: asyncio.run(_wait_for_review()), daemon=True).start()

    def _display_review(self, report, ch_data):
        scores = report.get("scores", {})
        overall = report.get("overall_score", 0)
        passed = report.get("passed", False)
        verdict = report.get("verdict", "未知")
        issues = report.get("issues", [])
        raw = report.get("raw_text", "")

        # 总分 + 判定
        self.score_text.value = f"总分: {overall}/100"
        self.verdict_badge.content = ft.Text(
            "✅ 通过" if passed else "❌ 未通过", color="white",
        )
        self.verdict_badge.bgcolor = "green" if passed else "red"

        # 雷达图
        self.radar.set_scores(scores)

        # 评分表格
        score_rows = []
        for dim_name in RadarChart.dimensions:
            val = scores.get(dim_name, 0)
            if val >= 8:
                level = "优秀"
            elif val >= 6:
                level = "良好"
            elif val >= 4:
                level = "一般"
            else:
                level = "需改进"
            score_rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(dim_name)),
                ft.DataCell(ft.Text(str(val))),
                ft.DataCell(ft.Text(level)),
            ]))
        self.score_table.rows = score_rows

        # 问题列表
        self.issue_list.controls.clear()
        if issues:
            for issue in issues[:15]:
                sev = issue.get("severity", "中")
                desc = issue.get("description", "")[:100]
                icon = {"高": "🔴", "中": "🟡", "低": "🟢", "critical": "🔴",
                        "major": "🟡", "minor": "🟢"}.get(sev, "⚪")
                self.issue_list.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(icon, size=16),
                            ft.Text(f"[{sev}] {desc}", size=13, expand=True),
                        ]),
                        padding=6, border=ft.Border.all(0.5, "grey_800"),
                        border_radius=4, margin=ft.Margin.only(bottom=2),
                    )
                )
        else:
            self.issue_list.controls.append(ft.Text("✅ 未发现明显问题", color="green"))

        # 原始报告
        self.raw_report.content = ft.Column([
            ft.Text(raw[:3000], selectable=True, font_family="monospace", size=12),
        ], scroll=ft.ScrollMode.ALWAYS)

        # 保存审校报告到文件
        if self.state._ctx:
            from novel_agent.agents.reviewer import ReviewerAgent
            memory, continuity, foreshadow, rag = self.state.get_services()
            dummy_reviewer = ReviewerAgent(memory, continuity, foreshadow)
            dummy_reviewer.save_review_report(
                self._selected_chapter, report,
                output_dir=str(self.state._ctx.output_dir),
            )

        self.result_card.visible = True
        self.update()

    def _toggle_raw(self, e):
        self.raw_report.visible = not self.raw_report.visible
        self.update()

    # ===== 后验校验 =====

    def _run_validator(self, e):
        if not self._selected_chapter or not self._chapter_content:
            return

        self.loading.visible = True
        self.update()

        _result = [None]
        _error = [None]
        _DONE = object()
        _queue = queue.Queue()

        def do_validate():
            try:
                memory, continuity, foreshadow, rag = self.state.get_services()
                from novel_agent.core.validator import ContractValidator, format_violations_report

                ch_data = None
                for c in self.state.chapter_plan:
                    if c.get("chapter") == self._selected_chapter:
                        ch_data = c
                        break
                characters = ch_data.get("characters", []) if ch_data else []

                validator = ContractValidator()
                violations = validator.validate(
                    self._chapter_content,
                    self._selected_chapter,
                    characters, memory,
                    continuity_guard=continuity,
                )

                _result[0] = (violations, format_violations_report)
            except Exception as ex:
                _error[0] = ex
            finally:
                _queue.put(_DONE)

        thread = threading.Thread(target=do_validate, daemon=True)
        thread.start()

        import asyncio, threading
        async def _wait_for_validate():
            loop = asyncio.get_running_loop()
            while thread.is_alive() or not _queue.empty():
                try:
                    _queue.get(timeout=0.1)
                    break
                except queue.Empty:
                    await asyncio.sleep(0.1)
            thread.join(timeout=5)
            self.loading.visible = False
            if _error[0]:
                self.error.show(str(_error[0]), "error")
            elif _result[0]:
                violations, formatter = _result[0]
                self._display_validation(violations, formatter)
            self.update()

        threading.Thread(target=lambda: asyncio.run(_wait_for_validate()), daemon=True).start()

    def _display_validation(self, violations, formatter):
        items = []
        if violations:
            for v in violations:
                sev = v.severity
                icon = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(sev, "⚪")
                items.append(ft.Row([
                    ft.Text(icon, size=14),
                    ft.Text(f"[{sev}] {v.category}: {v.message[:80]}", size=13, expand=True),
                ]))
        else:
            items.append(ft.Text("✅ 所有校验通过，未发现违反", color="green"))

        self.validation_card.content = ft.Column([
            ft.Text("后验校验 (contractvalidator)", size=16, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            ft.Text(f"检查项: 15  |  违反: {len(violations)}", size=13, color="grey_400"),
            *items,
        ])
        self.validation_card.visible = True
        self.update()
