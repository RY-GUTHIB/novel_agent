"""
写作管线页面。单页垂直滚动，步骤自动推进。
步骤: 预检 → 生成(流式) → 审校(含修订) → 定稿
"""
import asyncio
import logging
import threading
import queue
import flet as ft

logger = logging.getLogger(__name__)
from novel_agent.gui.state import AppState
from novel_agent.gui.widgets.step_pipeline import StepPipeline
from novel_agent.gui.widgets.streaming_viewer import StreamingViewer
from novel_agent.gui.widgets.error_banner import ErrorBanner
from novel_agent.gui.utils.error_handler import ErrorHandler
from novel_agent.gui.utils.versioning import ChapterVersionManager


class WritingPipelineView(ft.Column):
    def __init__(self, state: AppState, page: ft.Page):
        super().__init__(expand=True, spacing=16, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self.page_ref = page

        # ===== 步骤条 =====
        self.step_pipeline = StepPipeline(
            steps=["预检", "生成", "审校", "定稿"], current_step=0,
        )

        # ===== 章节选择器 =====
        self.chapter_selector = ft.Dropdown(
            label="选择章节", width=280,
            on_select=self._on_chapter_change,
        )
        self.write_button = ft.FilledTonalButton(
            "🚀 开始写作", icon=ft.Icons.PLAY_ARROW,
            on_click=self._on_write_click,
        )
        self.batch_switch = ft.Switch(label="连续模式", value=False)
        self.batch_end = ft.TextField(label="结束章节", width=100, value="", visible=False)

        def on_batch_toggle(e):
            self.batch_end.visible = self.batch_switch.value
            self.update()
        self.batch_switch.on_change = on_batch_toggle

        # ===== 章节详情卡片 =====
        self.chapter_info = ft.Container(
            content=ft.Text("请选择章节", color="grey_500"),
            padding=12, bgcolor="surface_variant",
            border_radius=8, visible=False,
        )

        # ===== 步骤 1：预检结果 =====
        self.precheck_panel = ft.Container(
            content=ft.Column([ft.Text("步骤 1：时空预检", size=16, weight=ft.FontWeight.BOLD)]),
            bgcolor="surface_variant", border_radius=8, padding=16, visible=False,
        )

        # ===== 步骤 2：流式生成 =====
        self.streaming_viewer = StreamingViewer()

        # ===== 步骤 3：审校 =====
        self.review_panel = ft.Container(
            content=ft.Column([
                ft.Text("步骤 3：ai 审校", size=16, weight=ft.FontWeight.BOLD),
                self._build_review_header(),
                self._build_radar_area(),
                self._build_violation_area(),
            ]),
            bgcolor="surface_variant", border_radius=8, padding=16, visible=False,
        )

        # ===== 版本历史面板 =====
        self.version_panel = ft.Container(
            content=ft.Column([
                ft.Text("📜 版本历史", size=14, weight=ft.FontWeight.BOLD),
                ft.Text("将在定稿后自动快照", color="grey_500", size=12),
                ft.Column([], ref=ft.Ref()),  # placeholder for version list
            ]),
            bgcolor="surface_variant", border_radius=8, padding=12,
            visible=False,
        )

        # ===== 步骤 4：定稿确认 =====
        self.finalize_panel = ft.Container(
            content=ft.Column([
                ft.Text("步骤 4：定稿", size=16, weight=ft.FontWeight.BOLD),
                ft.Text("✅ 已完成！", color="green", size=18),
                ft.Divider(),
                self._build_finalize_summary(),
                self.version_panel,
                ft.Row([
                    ft.FilledTonalButton("📝 写下一章", on_click=self._write_next),
                    ft.OutlinedButton("📜 查看历史版本", on_click=self._show_versions),
                    ft.OutlinedButton("🏠 返回工作台", on_click=self._go_dashboard),
                ]),
            ]),
            bgcolor="green_900", border_radius=8, padding=16, visible=False,
        )

        # ===== 错误横幅 =====
        self.error_banner = ErrorBanner()

        # ===== 构建布局 =====
        self.controls = [
            ft.Text("✍️ 写作管线", size=22, weight=ft.FontWeight.BOLD),
            self.step_pipeline,
            ft.Divider(height=8),
            ft.Row([self.chapter_selector, self.write_button, self.batch_switch, self.batch_end], spacing=12),
            self.chapter_info,
            self.precheck_panel,
            self.streaming_viewer,
            self.review_panel,
            self.finalize_panel,
            self.error_banner,
        ]

    def did_mount(self):
        try:
            self._refresh_chapters()
        except RuntimeError:
            pass
        if getattr(self.state, '_pending_auto_write', False):
            self.state._pending_auto_write = False
            import threading, asyncio, time
            def delayed_start():
                time.sleep(0.3)
                asyncio.run(self._start_write_pipeline(None))
            threading.Thread(target=delayed_start, daemon=True).start()

    # ==================== 章节选择 ====================

    def _refresh_chapters(self):
        plan = self.state.chapter_plan
        if not plan:
            self.chapter_selector.options = [ft.DropdownOption("", "暂无章节数据")]
            self.chapter_selector.value = ""
            self.update()
            return
        existing = self._get_existing_chapters()
        options = []
        for ch in plan:
            ch_num = ch.get("chapter", 0)
            title = ch.get("title", "")
            done = ch_num in existing
            label = f"第{ch_num}章 {title}"
            if done:
                label += " ✅"
            options.append(ft.DropdownOption(key=str(ch_num), text=label))
        self.chapter_selector.options = options
        # 优先选择外部传入的章节（如从时间线点击），否则选下一未写章节
        preferred = self.state.current_chapter
        if preferred is not None and any(str(c.get("chapter")) == str(preferred) for c in plan):
            self.chapter_selector.value = str(preferred)
            self.state.current_chapter = None  # 消费后清除
        else:
            next_ch = self._find_next_chapter(existing, plan)
            if next_ch:
                self.chapter_selector.value = str(next_ch)
        self._update_chapter_info()
        self.update()

    def _get_existing_chapters(self):
        import glob
        from pathlib import Path
        if not self.state._ctx:
            return set()
        files = glob.glob(str(self.state._ctx.chapters_dir / "chapter_*.md"))
        nums = set()
        for f in files:
            stem = Path(f).stem
            try:
                nums.add(int(stem.split("_")[1]))
            except (IndexError, ValueError):
                pass
        return nums

    def _find_next_chapter(self, existing, plan):
        for ch in plan:
            num = ch.get("chapter", 0)
            if num not in existing:
                return num
        return None

    def _on_chapter_change(self, e):
        self._update_chapter_info()

    def _update_chapter_info(self):
        if not self.chapter_selector.value:
            self.chapter_info.visible = False
            self.update()
            return
        try:
            ch_num = int(self.chapter_selector.value)
        except (ValueError, TypeError):
            self.chapter_info.visible = False
            self.update()
            return
        ch_data = self._get_chapter_data(ch_num)
        if not ch_data:
            self.chapter_info.visible = False
        else:
            chars = ", ".join(ch_data.get("characters", []))
            self.chapter_info.content = ft.Column([
                ft.Text(f"第{ch_num}章 {ch_data.get('title', '')}", size=16, weight=ft.FontWeight.BOLD),
                ft.Text(f"时间: {ch_data.get('time', ch_data.get('time_tag', ''))}   地点: {ch_data.get('location', '')}"),
                ft.Text(f"角色: {chars}"),
                ft.Text(f"概要: {ch_data.get('summary', '')[:120]}"),
            ])
            self.chapter_info.visible = True
        self.update()

    def _get_chapter_data(self, chapter):
        for c in self.state.chapter_plan:
            if c.get("chapter") == chapter:
                return c
        return None

    # ==================== 写作管线主流程 ====================

    def _on_write_click(self, e):
        import asyncio, threading
        threading.Thread(target=lambda: asyncio.run(self._start_write_pipeline(e)), daemon=True).start()

    async def _start_write_pipeline(self, e):
        if not self.chapter_selector.value:
            self.error_banner.show("请先选择章节")
            self.update()
            return

        try:
            selected_chapter = int(self.chapter_selector.value)
        except (ValueError, TypeError):
            self.error_banner.show("请选择有效的章节")
            self.update()
            return

        # 批量模式：获取起始和结束章节
        if self.batch_switch.value:
            start_ch = selected_chapter
            end_str = self.batch_end.value
            end_ch = int(end_str) if end_str.isdigit() else len(self.state.chapter_plan)
            chapters_to_write = [c.get("chapter") for c in self.state.chapter_plan
                                 if start_ch <= c.get("chapter", 0) <= end_ch]
            already_done = self._get_existing_chapters()
            chapters_to_write = [c for c in chapters_to_write if c not in already_done]
            if not chapters_to_write:
                self.error_banner.show("所选范围内没有待写的章节", "info")
                self.update()
                return

            self.state.pipeline_step = 0
            self.state.is_writing = True
            self.write_button.disabled = True
            self.write_button.text = f"⏳ 批量写作中... (0/{len(chapters_to_write)})"
            self._reset_panels()
            self.error_banner.hide()
            self.update()

            # 显示批量进度面板
            batch_progress_text = ft.Text("", size=13)
            self.controls.insert(4, batch_progress_text)
            self.update()

            success_count = 0
            for i, ch in enumerate(chapters_to_write):
                batch_progress_text.value = f"📝 批量进度: {i+1}/{len(chapters_to_write)}  当前: 第{ch}章"
                self.write_button.text = f"⏳ 批量写作中... ({i}/{len(chapters_to_write)})"
                self.chapter_selector.value = str(ch)
                self._update_chapter_info()
                self.update()

                try:
                    await self._run_all_steps(ch)
                    success_count += 1
                except Exception as ex:
                    msg = ErrorHandler.user_message(ex)
                    self.error_banner.show(f"第{ch}章失败: {msg}", "warning")
                    # 继续下一章

            self.controls.remove(batch_progress_text)
            self.error_banner.show(f"✅ 批量完成: {success_count}/{len(chapters_to_write)} 章成功", "success")
            self._refresh_chapters()
        else:
            # 单章模式
            chapter = selected_chapter
            self.state.pipeline_step = 0
            self.state.is_writing = True
            self.write_button.disabled = True
            self.write_button.text = "⏳ 写作中..."
            self._reset_panels()
            self.error_banner.hide()
            self.update()

            try:
                await self._run_all_steps(chapter)
                self.error_banner.show("✅ 写作完成！", "success")
            except Exception as ex:
                msg = ErrorHandler.user_message(ex)
                self.error_banner.show(msg, "error")

        self.state.is_writing = False
        self.write_button.disabled = False
        self.write_button.text = "🚀 开始写作"
        self.update()

    async def _run_all_steps(self, chapter):
        memory, continuity, foreshadow, rag = self.state.get_services()
        if not memory:
            self.error_banner.show("请先选择项目", "warning")
            return

        # ===== 步骤 1：预检 =====
        self.step_pipeline.set_current(0)
        self.precheck_panel.visible = True
        self.update()
        await self._run_precheck(chapter, memory, continuity)
        self.step_pipeline.complete(0)
        self.update()

        # ===== 步骤 2：生成 =====
        self.step_pipeline.set_current(1)
        self.streaming_viewer.visible = True
        self.update()
        await self._run_generation(chapter, memory, continuity, foreshadow, rag)
        self.step_pipeline.complete(1)
        self.update()

        # ===== 步骤 3：审校（最多 3 轮） =====
        self.step_pipeline.set_current(2)
        self.review_panel.visible = True
        self.update()
        for attempt in range(3):
            await self._run_review(chapter, memory, continuity, foreshadow)
            if self.state.review_passed:
                break
            if attempt < 2:
                await self._auto_revise(chapter, memory, continuity, foreshadow, rag)
        self.step_pipeline.complete(2)
        self.update()

        # ===== 步骤 4：定稿 =====
        self.step_pipeline.set_current(3)
        self.update()
        await self._run_finalize(chapter, memory, continuity, foreshadow, rag)
        self.step_pipeline.complete(3)
        self.finalize_panel.visible = True
        self._update_finalize_summary(chapter)
        self.update()

        # 定稿后处理：重建 novel.md + 更新 MEMORY.md（失败不阻断流程）
        ctx = self.state._ctx
        project_name = self.state.current_project
        if ctx and project_name:
            try:
                from novel_agent.cli.commands import rebuild_novel_md, update_project_memory
                rebuild_novel_md(str(ctx.output_dir))
                update_project_memory(project_name, memory, continuity, foreshadow, str(ctx.output_dir))
            except Exception as ex:
                logger.error("post-finalize error: %s", ex)

        # 刷新章节列表
        self._refresh_chapters()

    # ==================== 步骤 1：预检 ====================

    async def _run_precheck(self, chapter, memory, continuity):
        ch_data = self._get_chapter_data(chapter)
        if not ch_data:
            raise ValueError(f"大纲中没有第 {chapter} 章的数据")

        from novel_agent.core.spacetime_guard import SpacetimeGuard
        guard = SpacetimeGuard(memory, continuity)
        result = guard.pre_check(
            chapter=chapter,
            time_tag=ch_data.get("time_tag", ch_data.get("time", "")),
            location=ch_data.get("location", ""),
            characters=ch_data.get("characters", []),
        )

        logs = []
        for err in result.fatal_errors:
            logs.append(ft.Text(f"❌ {err}", color="red"))
        for ch_fix in result.auto_fix_channels:
            logs.append(ft.Text(f"🔗 自动修复通道: {ch_fix.from_location}↔{ch_fix.to_location}",
                                color="orange"))
            guard.auto_fix_spacemap(continuity, result.auto_fix_channels)
        for w in result.warnings:
            logs.append(ft.Text(f"⚠️ {w}", color="amber"))
        if not result.fatal_errors and not result.warnings:
            logs.append(ft.Text("✅ 预检全部通过", color="green"))

        self.precheck_panel.content = ft.Column([
            ft.Text("步骤 1：时空预检", size=16, weight=ft.FontWeight.BOLD),
            *logs,
        ])
        self.update()

        if result.fatal_errors:
            raise RuntimeError("时空守卫拒绝生成，请修复后重试")

    # ==================== 步骤 2：生成 ====================

    async def _run_generation(self, chapter, memory, continuity, foreshadow, rag):
        ch_data = self._get_chapter_data(chapter)
        ctx = self.state._ctx

        from novel_agent.core.logic_guard import LogicGuard
        logic_guard = LogicGuard(memory, continuity)
        logic_constraints = logic_guard.build_constraints(
            chapter=chapter,
            characters=ch_data.get("characters", []),
            location=ch_data.get("location", ""),
        )

        from novel_agent.agents.writer import WriterAgent
        from novel_agent.llm.client import check_api_key
        check_api_key()

        meta = self.state.outline.get("meta", {}) if self.state.outline else {}
        writer = WriterAgent(memory, continuity, foreshadow, ctx=ctx, rag_store=rag,
                             genre=meta.get("genre", "玄幻"),
                             style=meta.get("style", "热血"))

        target_words = int(self.streaming_viewer.target_words.value or "5000")
        self.state.write_target_words = target_words
        self.state.write_word_count = 0
        self.state.write_stream_content = ""

        _token_queue = queue.Queue()
        _DONE = object()

        def on_token(token: str):
            _token_queue.put(token)

        result_container = [None, None]
        error_container = [None]

        def do_generate():
            try:
                content, settings_json = writer.write_chapter(
                    chapter=chapter,
                    title=ch_data.get("title", ""),
                    summary=ch_data.get("summary", ""),
                    time_tag=ch_data.get("time_tag", ch_data.get("time", "")),
                    location=ch_data.get("location", ""),
                    characters=ch_data.get("characters", []),
                    logic_constraints=logic_constraints,
                    on_token=on_token,
                )
                result_container[0], result_container[1] = content, settings_json
            except Exception as ex:
                error_container[0] = ex
            finally:
                _token_queue.put(_DONE)

        thread = threading.Thread(target=do_generate, daemon=True)
        thread.start()

        _last_update = 0
        import time
        while thread.is_alive() or not _token_queue.empty():
            try:
                token = _token_queue.get(timeout=0.1)
                if token is _DONE:
                    break
                self.state.write_stream_content += token
                self.state.write_word_count += len(token)
                now = time.monotonic()
                if now - _last_update >= 0.15:
                    self.state.write_progress = min(
                        self.state.write_word_count / max(target_words, 1), 1.0
                    )
                    self.streaming_viewer.update_content(
                        self.state.write_stream_content,
                        self.state.write_word_count,
                        target_words,
                    )
                    self.page_ref.update()
                    _last_update = now
            except queue.Empty:
                await asyncio.sleep(0.05)

        thread.join(timeout=5)
        if thread.is_alive():
            raise TimeoutError("LLM 生成超时，请检查网络或稍后重试")

        if error_container[0]:
            raise error_container[0]

        content = result_container[0]
        self.state._pending_content = content
        self.state._pending_settings = result_container[1]

    # ==================== 步骤 3：审校 ====================

    async def _run_review(self, chapter, memory, continuity, foreshadow):
        ch_data = self._get_chapter_data(chapter)
        content = self.state._pending_content
        if not content:
            raise ValueError("无待审校内容")

        from novel_agent.agents.reviewer import ReviewerAgent
        from novel_agent.llm.client import check_api_key
        check_api_key()

        import concurrent.futures

        def do_review():
            reviewer = ReviewerAgent(memory, continuity, foreshadow)
            return reviewer.review_chapter(
                chapter, ch_data.get("title", ""), content,
                characters=ch_data.get("characters", []),
            )

        loop = asyncio.get_running_loop()
        report = await asyncio.wait_for(
            loop.run_in_executor(None, do_review), timeout=300
        )

        self.state.review_report = report
        self.state.review_passed = report.get("passed", False)
        self._populate_review_panel(report)

    def _populate_review_panel(self, report):
        score = report.get("overall_score", 0)
        passed = report.get("passed", False)
        verdict = report.get("verdict", "")

        header = self.review_panel.content.controls[1]
        header.content.controls[0].value = f"总分: {score}/100"
        header.content.controls[1].content = ft.Text(
            "✅ 通过" if passed else "❌ 未通过", color="white",
        )
        header.content.controls[1].bgcolor = "green" if passed else "red"

        issues = report.get("issues", [])
        violation_col = self.review_panel.content.controls[3]
        violation_col.controls.clear()
        if issues:
            for issue in issues[:10]:
                sev = issue.get("severity", "warning")
                icon = {"critical": "🔴", "major": "🟡", "minor": "🟢"}.get(sev, "⚪")
                violation_col.controls.append(
                    ft.Text(f"{icon} [{sev}] {issue.get('description', '')[:80]}", size=13)
                )
        else:
            violation_col.controls.append(ft.Text("没有发现明显问题", color="green"))
        self.update()

    def _build_review_header(self):
        return ft.Container(
            content=ft.Row([
                ft.Text("总分: --/100", size=18, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=ft.Text("待审校", color="white"),
                    padding=ft.Padding.only(left=12, right=12, top=4, bottom=4),
                    border_radius=8, bgcolor="grey_600",
                ),
                ft.Container(expand=True),
                ft.ElevatedButton("✅ 通过并定稿", on_click=self._manual_pass),
                ft.ElevatedButton("🔄 自动修订", on_click=self._trigger_revise),
                ft.OutlinedButton("✕ 强制定稿", on_click=self._force_pass),
            ]),
        )

    def _build_radar_area(self):
        return ft.Container(
            content=ft.Text("评分详情将在审校后展示", color="grey_500"),
            padding=10, margin=ft.Margin.only(top=8, bottom=8),
        )

    def _build_violation_area(self):
        return ft.Column([])

    async def _auto_revise(self, chapter, memory, continuity, foreshadow, rag):
        ch_data = self._get_chapter_data(chapter)
        content = self.state._pending_content
        report = self.state.review_report
        if not report:
            return
        ctx = self.state._ctx

        import concurrent.futures

        def do_revise():
            from novel_agent.agents.writer import WriterAgent
            writer = WriterAgent(memory, continuity, foreshadow, ctx=ctx, rag_store=rag)
            return writer.revise_chapter(
                chapter=chapter,
                title=ch_data.get("title", ""),
                original_content=content,
                review_report=report,
                summary=ch_data.get("summary", ""),
                time_tag=ch_data.get("time_tag", ch_data.get("time", "")),
                location=ch_data.get("location", ""),
                characters=ch_data.get("characters", []),
            )

        loop = asyncio.get_running_loop()
        try:
            new_content, new_settings = await asyncio.wait_for(
                loop.run_in_executor(None, do_revise), timeout=300
            )
        except asyncio.TimeoutError:
            self.error_banner.show("修订超时（5分钟），请重试", "warning")
            return
        except Exception as ex:
            self.error_banner.show(f"修订失败: {ErrorHandler.user_message(ex)}", "error")
            return

        self.state._pending_content = new_content
        if new_settings:
            self.state._pending_settings = new_settings
        self.streaming_viewer.update_content(
            new_content, len(new_content), self.state.write_target_words,
        )
        self.update()

    def _trigger_revise(self, e):
        memory, continuity, foreshadow, rag = self.state.get_services()
        chapter = int(self.chapter_selector.value) if self.chapter_selector.value else 1
        import threading, asyncio
        threading.Thread(
            target=lambda: asyncio.run(self._auto_revise(chapter, memory, continuity, foreshadow, rag)),
            daemon=True,
        ).start()

    def _manual_pass(self, e):
        self.state.review_passed = True
        self._go_finalize()

    def _force_pass(self, e):
        self.state.review_passed = True
        self._go_finalize()

    def _go_finalize(self):
        self.step_pipeline.set_current(3)
        self.review_panel.visible = False
        self.update()

    # ==================== 步骤 4：定稿 ====================

    async def _run_finalize(self, chapter, memory, continuity, foreshadow, rag):
        content = self.state._pending_content
        settings_json = self.state._pending_settings
        ch_data = self._get_chapter_data(chapter)
        ctx = self.state._ctx
        if not content:
            raise ValueError("没有可定稿的内容")

        # 定稿前自动创建版本快照
        if ctx and ctx.data_dir:
            vman = ChapterVersionManager(ctx.data_dir.parent)
            vman.save_snapshot(chapter, content)

        from novel_agent.agents.writer import WriterAgent
        writer = WriterAgent(memory, continuity, foreshadow, ctx=ctx, rag_store=rag)
        writer.finalize_chapter(
            chapter=chapter,
            content=content,
            summary=ch_data.get("summary", ""),
            time_tag=ch_data.get("time_tag", ch_data.get("time", "")),
            location=ch_data.get("location", ""),
            characters=ch_data.get("characters", []),
            title=ch_data.get("title", ""),
            settings_json=settings_json,
        )

    def _build_finalize_summary(self):
        self._finalize_text = ft.Text("", selectable=True)
        return self._finalize_text

    def _update_finalize_summary(self, chapter):
        wc = self.state.write_word_count
        self._finalize_text.value = f"第 {chapter} 章已保存\n字数: {wc} 字\n文件: chapter_{chapter:03d}.md"
        self.update()

    def _write_next(self, e):
        current = int(self.chapter_selector.value)
        next_ch = current + 1
        if any(c.get("chapter") == next_ch for c in self.state.chapter_plan):
            self.chapter_selector.value = str(next_ch)
            self._update_chapter_info()
            self.finalize_panel.visible = False
        self.step_pipeline.set_current(0)
        self.step_pipeline._completed.clear()
        self.step_pipeline._build()
        self._reset_panels()
        self.update()

    def _go_dashboard(self, e):
        self.state.current_tab = 0
        self.page_ref.navigation_bar.selected_index = 0
        self.page_ref.update()

    # ==================== 版本管理 ====================

    def _show_versions(self, e=None):
        ch = int(self.chapter_selector.value) if self.chapter_selector.value else None
        if not ch or not self.state._ctx:
            return
        vman = ChapterVersionManager(self.state._ctx.data_dir.parent)
        versions = vman.list_versions(ch)

        if not versions:
            self.error_banner.show("暂无版本历史", "info")
            self.update()
            return

        version_rows = []
        for v in versions[:10]:
            version_rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(v["timestamp"], size=12)),
                ft.DataCell(
                    ft.TextButton("恢复到此版本",
                                  data=v["version"],
                                  on_click=lambda e, v_id=v["version"]: self._restore_version(e, ch, v_id))
                ),
            ]))

        dlg = ft.AlertDialog(
            title=ft.Text(f"第{ch}章 版本历史"),
            content=ft.Container(
                content=ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("时间")),
                        ft.DataColumn(ft.Text("操作")),
                    ],
                    rows=version_rows,
                ),
                width=400,
            ),
            actions=[ft.TextButton("关闭", on_click=lambda e: self._close_dlg(dlg))],
        )
        self.page_ref.show_dialog(dlg)
        self.page_ref.update()

    def _restore_version(self, e, chapter, version_id):
        vman = ChapterVersionManager(self.state._ctx.data_dir.parent)
        try:
            content = vman.restore(chapter, version_id)
            self.state._pending_content = content
            self.state.write_word_count = len(content)
            self.state.write_stream_content = content

            self.streaming_viewer.update_content(
                content, len(content), self.state.write_target_words or len(content),
            )
            # 写入磁盘
            from novel_agent.agents.writer import WriterAgent
            memory, continuity, foreshadow, rag = self.state.get_services()
            ch_data = self._get_chapter_data(chapter)
            writer = WriterAgent(memory, continuity, foreshadow, ctx=self.state._ctx, rag_store=rag)
            writer.save_chapter(chapter, ch_data.get("title", "") if ch_data else "", content)

            self.error_banner.show(f"✅ 已恢复到版本 {version_id}", "success")
        except FileNotFoundError:
            self.error_banner.show("版本文件不存在", "error")
        self._close_dlg(None)
        self.update()

    def _close_dlg(self, dlg):
        if dlg:
            dlg.open = False
            self.page_ref.update()

    def _reset_panels(self):
        self.precheck_panel.visible = False
        self.streaming_viewer.visible = False
        self.review_panel.visible = False
        self.finalize_panel.visible = False
        self.state.write_stream_content = ""
        self.state.write_word_count = 0
        self.state.write_progress = 0.0
        self.state.review_report = None
        self.state.review_passed = None
        self.state._pending_content = ""
        self.state._pending_settings = None
