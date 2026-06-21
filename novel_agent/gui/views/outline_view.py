"""
大纲视图。treeview 展示卷→章节结构，支持生成/续写/重写大纲。
"""
import json
import threading
import flet as ft
from novel_agent.gui.state import AppState
from novel_agent.gui.widgets.error_banner import ErrorBanner


def _show_snackbar(page: ft.Page, message: str, duration: int = 4000):
    page.snack_bar = ft.SnackBar(ft.Text(message), duration=duration)
    page.snack_bar.open = True
    page.update()


class OutlineView(ft.Column):
    def __init__(self, state: AppState, page: ft.Page):
        super().__init__(expand=True, spacing=12, scroll=ft.ScrollMode.AUTO)
        self.state = state
        self.page_ref = page
        self._loading = False

        # ===== 顶部工具栏 =====
        self.refresh_btn = ft.IconButton(ft.Icons.REFRESH, tooltip="刷新",
                                         on_click=lambda e: self.did_mount())
        self.gen_btn = ft.FilledTonalButton("🤖 生成大纲", icon=ft.Icons.AUTO_AWESOME,
                                            on_click=self._on_generate)
        self.extend_btn = ft.FilledTonalButton("📝 续写大纲", icon=ft.Icons.ADD,
                                               on_click=self._on_extend, disabled=True)
        self.rewrite_btn = ft.FilledTonalButton("🔄 重写后续大纲", icon=ft.Icons.REFRESH,
                                                on_click=self._on_rewrite, disabled=True)
        self.title_text = ft.Text("小说标题", size=20, weight=ft.FontWeight.BOLD)

        # ===== 进度条 =====
        self._progress_bar = ft.ProgressBar(visible=False, color="primary")

        # ===== 元信息卡片 =====
        self.meta_card = ft.Container(
            padding=16, border_radius=12, bgcolor="surface_variant",
            visible=False,
        )

        # ===== 卷→章节树 =====
        self.tree_container = ft.Container(
            content=ft.Text("暂无大纲数据，点击「生成大纲」开始", color="grey_500"),
            padding=16, border_radius=12, bgcolor="surface_variant",
        )

        # ===== 选中章节详情 =====
        self.chapter_detail_card = ft.Container(
            padding=16, border_radius=12, bgcolor="surface_variant",
            visible=False,
        )

        # ===== 错误横幅 =====
        self.error = ErrorBanner()

        self.controls = [
            ft.Row([
                ft.Text("📖 大纲管理", size=22, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                self.refresh_btn, self.gen_btn, self.extend_btn, self.rewrite_btn,
            ]),
            self.title_text,
            self.meta_card,
            self.error,
            self._progress_bar,
            ft.Text("章节结构", size=16, weight=ft.FontWeight.BOLD),
            self.tree_container,
            self.chapter_detail_card,
        ]

    def did_mount(self):
        try:
            self._refresh()
        except RuntimeError:
            pass

    def _refresh(self):
        self.state._load_outline()
        outline = self.state.outline
        has_outline = bool(outline)

        if not outline:
            self.title_text.value = "暂无大纲"
            self.meta_card.visible = False
            self.tree_container.content = ft.Column([
                ft.Text("还没有生成大纲", color="grey_500", size=16),
                ft.ElevatedButton("🤖 立即生成大纲", on_click=self._on_generate),
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            self.extend_btn.disabled = True
            self.rewrite_btn.disabled = True
            self.chapter_detail_card.visible = False
            self.update()
            return

        meta = outline.get("meta", {})
        title = meta.get("title", outline.get("title", self.state.current_project))
        genre = meta.get("genre", outline.get("genre", "未知"))
        style = meta.get("style", outline.get("style", "未知"))
        self.title_text.value = f"《{title}》"

        char_count = len(outline.get("characters", []))
        loc_count = len(outline.get("locations", []))
        vol_count = len(outline.get("volumes", []))
        ch_count = len(self.state.chapter_plan)

        self.meta_card.content = ft.Row([
            ft.Column([ft.Text("类型", color="grey_400"), ft.Text(genre)]),
            ft.VerticalDivider(),
            ft.Column([ft.Text("风格", color="grey_400"), ft.Text(style)]),
            ft.VerticalDivider(),
            ft.Column([ft.Text("角色", color="grey_400"), ft.Text(str(char_count))]),
            ft.VerticalDivider(),
            ft.Column([ft.Text("地点", color="grey_400"), ft.Text(str(loc_count))]),
            ft.VerticalDivider(),
            ft.Column([ft.Text("卷数", color="grey_400"), ft.Text(str(vol_count))]),
            ft.VerticalDivider(),
            ft.Column([ft.Text("章节", color="grey_400"), ft.Text(str(ch_count))]),
        ], spacing=12)
        self.meta_card.visible = True

        # 构建树
        tree = self._build_tree(outline)
        self.tree_container.content = tree
        self.extend_btn.disabled = False
        self.rewrite_btn.disabled = False
        self.chapter_detail_card.visible = False
        self.update()

    def _build_tree(self, outline):
        volumes = outline.get("volumes", [])
        if not volumes:
            return ft.Text("大纲无卷信息", color="grey_500")

        items = []
        for vol in volumes:
            vol_num = vol.get("volume", 0)
            vol_name = vol.get("title", "") or vol.get("volume_title", "") or f"第{vol_num}卷"
            vol_arc = vol.get("arc", {})
            chap_list = vol.get("chapters", vol.get("chapter_plan", []))

            # 将 arc 字典转为可读摘要
            arc_text = ""
            if isinstance(vol_arc, dict) and vol_arc:
                parts = []
                if vol_arc.get("setback_chapter"):
                    parts.append(f"挫折:{vol_arc['setback_chapter']}")
                if vol_arc.get("insight_chapter"):
                    parts.append(f"领悟:{vol_arc['insight_chapter']}")
                if vol_arc.get("breakthrough_chapter"):
                    parts.append(f"突破:{vol_arc['breakthrough_chapter']}")
                if vol_arc.get("new_challenge_chapter"):
                    parts.append(f"新挑战:{vol_arc['new_challenge_chapter']}")
                arc_text = " | ".join(parts)
            elif isinstance(vol_arc, str):
                arc_text = vol_arc

            chap_items = []
            for ch in chap_list:
                ch_num = ch.get("chapter", 0)
                ch_title = ch.get("title", "")
                ch_loc = ch.get("location", "")
                chars = ch.get("characters", [])
                existing = self._chapter_exists(ch_num)

                status_icon = "✅" if existing else "⏳"
                chap_items.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(f"{status_icon} 第{ch_num}章 {ch_title}", size=14,
                                    color="primary" if not existing else "green"),
                            ft.Text(f"| {ch_loc}", size=12, color="grey_400"),
                            ft.Text(f"| {', '.join(chars[:3])}", size=12, color="grey_400"),
                        ]),
                        padding=ft.Padding.only(left=24, top=4, bottom=4),
                        border=ft.Border.all(0.5, "grey_800"),
                        border_radius=4,
                        on_click=lambda e, d=ch: self._show_chapter_detail(d),
                        ink=True,
                    )
                )

            vol_header = ft.ExpansionTile(
                title=ft.Text(f"📚 {vol_name}", size=15, weight=ft.FontWeight.BOLD),
                subtitle=ft.Text(f"{len(chap_list)} 章 | {arc_text}" if arc_text else f"{len(chap_list)} 章",
                                 size=12, color="grey_400"),
                controls=chap_items,
                expanded=True,
            )
            items.append(vol_header)

        return ft.Column(items, spacing=4)

    def _chapter_exists(self, chapter_num):
        import glob
        from pathlib import Path
        if not self.state._ctx:
            return False
        pattern = str(self.state._ctx.chapters_dir / f"chapter_{chapter_num:03d}.md")
        return len(glob.glob(pattern)) > 0

    def _show_chapter_detail(self, ch_data):
        ch_num = ch_data.get("chapter", 0)
        title = ch_data.get("title", "")
        summary = ch_data.get("summary", "")
        time_tag = ch_data.get("time", ch_data.get("time_tag", ""))
        location = ch_data.get("location", "")
        characters = ch_data.get("characters", [])
        ch_type = ch_data.get("type", "")
        key_events = ch_data.get("key_events", [])

        existing = self._chapter_exists(ch_num)
        status = "✅ 已写入" if existing else "⏳ 待写入"

        rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text("章节")), ft.DataCell(ft.Text(str(ch_num))),
            ]),
            ft.DataRow(cells=[
                ft.DataCell(ft.Text("标题")), ft.DataCell(ft.Text(title)),
            ]),
            ft.DataRow(cells=[
                ft.DataCell(ft.Text("状态")), ft.DataCell(ft.Text(status)),
            ]),
            ft.DataRow(cells=[
                ft.DataCell(ft.Text("时间")), ft.DataCell(ft.Text(time_tag or "未指定")),
            ]),
            ft.DataRow(cells=[
                ft.DataCell(ft.Text("地点")), ft.DataCell(ft.Text(location or "未指定")),
            ]),
            ft.DataRow(cells=[
                ft.DataCell(ft.Text("角色")), ft.DataCell(ft.Text(", ".join(characters) or "未指定")),
            ]),
        ]
        if ch_type:
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text("类型")), ft.DataCell(ft.Text(ch_type)),
            ]))

        event_rows = []
        for ev in key_events[:5]:
            event_rows.append(ft.Text(f"  · {ev}", size=13))

        self.chapter_detail_card.content = ft.Column([
            ft.Text(f"第{ch_num}章 {title}", size=18, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            ft.DataTable(columns=[
                ft.DataColumn(ft.Text("属性")),
                ft.DataColumn(ft.Text("值")),
            ], rows=rows, heading_row_height=0),
            ft.Text("概要", size=14, weight=ft.FontWeight.BOLD, visible=bool(summary)),
            ft.Text(summary[:200] if summary else "", size=13, visible=bool(summary)),
            ft.Text("关键事件", size=14, weight=ft.FontWeight.BOLD, visible=bool(key_events)),
            ft.Column(event_rows, spacing=2, visible=bool(key_events)),
        ])
        self.chapter_detail_card.visible = True
        self.update()

    def _set_loading(self, loading: bool):
        self._loading = loading
        self.gen_btn.disabled = loading
        self.extend_btn.disabled = loading or not self.state.outline
        self.rewrite_btn.disabled = loading or not self.state.outline
        self.refresh_btn.disabled = loading
        self._progress_bar.visible = loading
        self.error.hide()
        self.update()

    def _get_existing_chapters_summary(self):
        """获取已写章节的摘要，用于重写大纲"""
        import glob
        from pathlib import Path
        if not self.state._ctx:
            return "无"
        files = glob.glob(str(self.state._ctx.chapters_dir / "chapter_*.md"))
        existing = set()
        for f in files:
            stem = Path(f).stem
            parts = stem.split("_")
            if len(parts) > 1 and parts[1].isdigit():
                existing.add(int(parts[1]))
        written_titles = []
        for ch in self.state.chapter_plan:
            if ch.get("chapter") in existing:
                written_titles.append(f"第{ch['chapter']}章 {ch.get('title', '')}")
        return "、".join(written_titles) if written_titles else "无"

    def _on_generate(self, e):
        """首次生成大纲"""
        if not self.state.current_project:
            self.error.show("请先选择项目", "warning")
            self.update()
            return

        from novel_agent.project import load_project_config
        cfg = load_project_config(self.state.current_project)
        genre = cfg.get("type", "玄幻")
        style = cfg.get("style", "热血")
        concept = cfg.get("concept", "")

        if not concept:
            self.error.show("项目缺少构思描述，请在项目设置中补充", "warning")
            self.update()
            return

        _error_msg = [None]
        project_name = self.state.current_project

        def do_generate():
            try:
                memory, continuity, foreshadow, rag = self.state.get_services()
                from novel_agent.llm.client import check_api_key
                check_api_key()
                from novel_agent.cli.commands import generate_outline
                generate_outline(memory, continuity, foreshadow,
                                 project_name, genre, style, concept, gui_mode=True)
            except Exception as ex:
                _error_msg[0] = str(ex)

        self._set_loading(True)
        self.error.show("正在生成大纲（约1-2分钟）...", "info")
        self.update()
        thread = threading.Thread(target=do_generate, daemon=True)
        thread.start()

        def check_done():
            import time
            while thread.is_alive():
                time.sleep(0.5)
            if _error_msg[0]:
                from novel_agent.gui.utils.error_handler import ErrorHandler
                msg = ErrorHandler.user_message(Exception(_error_msg[0]))
                self._set_loading(False)
                self.error.show(msg, "error")
            else:
                self.state._load_outline()
                self.error.hide()
                self._refresh()
                self._save_llm_title()
                self._set_loading(False)
            self.update()

        threading.Thread(target=check_done, daemon=True).start()

    def _on_extend(self, e):
        """续写大纲：在现有大纲基础上追加更多卷"""
        if not self.state.outline:
            self.error.show("请先生成大纲", "warning")
            self.update()
            return

        _error_msg = [None]
        project_name = self.state.current_project

        def do_extend():
            try:
                memory, continuity, foreshadow, rag = self.state.get_services()
                from novel_agent.llm.client import check_api_key
                check_api_key()
                ctx = self.state._ctx
                from novel_agent.agents.planner import PlannerAgent
                planner = PlannerAgent(memory, continuity, foreshadow, ctx=ctx)

                existing = self._get_existing_chapters_summary()
                prompt = (
                    f"当前大纲已有 {len(self.state.outline.get('volumes', []))} 卷。"
                    f"已写章节: {existing}。"
                    f"请在现有大纲基础上追加 1-2 卷新内容（保持原有内容不变），"
                    f"新卷的章节号从已有章节之后续编。"
                )
                new_outline = planner.refine_outline(self.state.outline, prompt)
                planner.save_outline_json(new_outline)
                self.state._load_outline()
            except Exception as ex:
                _error_msg[0] = str(ex)

        self._set_loading(True)
        self.error.show("正在续写大纲...", "info")
        self.update()
        thread = threading.Thread(target=do_extend, daemon=True)
        thread.start()

        def check_done():
            import time
            while thread.is_alive():
                time.sleep(0.5)
            if _error_msg[0]:
                from novel_agent.gui.utils.error_handler import ErrorHandler
                msg = ErrorHandler.user_message(Exception(_error_msg[0]))
                self._set_loading(False)
                self.error.show(msg, "error")
            else:
                self.error.hide()
                self._refresh()
                _show_snackbar(self.page_ref, "大纲续写完成", 3000)
                self._set_loading(False)
            self.update()

        threading.Thread(target=check_done, daemon=True).start()

    def _on_rewrite(self, e):
        """重写后续大纲：根据已写章节重规划剩余内容"""
        if not self.state.outline:
            self.error.show("请先生成大纲", "warning")
            self.update()
            return

        _error_msg = [None]
        project_name = self.state.current_project

        def do_rewrite():
            try:
                memory, continuity, foreshadow, rag = self.state.get_services()
                from novel_agent.llm.client import check_api_key
                check_api_key()
                ctx = self.state._ctx
                from novel_agent.agents.planner import PlannerAgent
                planner = PlannerAgent(memory, continuity, foreshadow, ctx=ctx)

                existing = self._get_existing_chapters_summary()
                prompt = (
                    f"已有以下章节已完成: {existing}。"
                    f"请根据已完成章节的内容走向，重新规划剩余未写章节的大纲"
                    f"（章节号、标题、概要、关键事件），"
                    f"保持已有章节内容不变。如有必要可以调整后续卷的主题弧线。"
                )
                new_outline = planner.refine_outline(self.state.outline, prompt)
                planner.save_outline_json(new_outline)
                self.state._load_outline()
            except Exception as ex:
                _error_msg[0] = str(ex)

        self._set_loading(True)
        self.error.show("正在重写后续大纲...", "info")
        self.update()
        thread = threading.Thread(target=do_rewrite, daemon=True)
        thread.start()

        def check_done():
            import time
            while thread.is_alive():
                time.sleep(0.5)
            if _error_msg[0]:
                from novel_agent.gui.utils.error_handler import ErrorHandler
                msg = ErrorHandler.user_message(Exception(_error_msg[0]))
                self._set_loading(False)
                self.error.show(msg, "error")
            else:
                self.error.hide()
                self._refresh()
                _show_snackbar(self.page_ref, "后续大纲已重写完成", 3000)
                self._set_loading(False)
            self.update()

        threading.Thread(target=check_done, daemon=True).start()

    def _save_llm_title(self):
        """保存 LLM 建议的标题到项目配置"""
        try:
            from novel_agent.project import load_project_config, save_project_config
            outline = self.state.outline
            if not outline:
                return
            llm_title = outline.get("meta", {}).get("title",
                        outline.get("title", ""))
            if llm_title and llm_title != self.state.current_project:
                cfg = load_project_config(self.state.current_project)
                cfg["novel_title"] = llm_title
                save_project_config(self.state.current_project, cfg)
                self.state.novel_title = llm_title
                self.state._update_title()
                _show_snackbar(self.page_ref,
                    f"LLM 建议标题: 《{llm_title}》", 6000)
            else:
                _show_snackbar(self.page_ref, "大纲已生成完成", 3000)
        except Exception:
            _show_snackbar(self.page_ref, "大纲已生成完成", 3000)
