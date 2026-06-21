"""
全局状态管理。所有视图共享同一个 AppState 实例。
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict
import flet as ft
import config
from novel_agent.cli.commands import init_services


@dataclass
class AppState:
    page: ft.Page = field(default=None)

    # 项目状态
    projects: List[Dict] = field(default_factory=list)
    current_project: Optional[str] = None
    current_chapter: Optional[int] = None
    outline: Optional[Dict] = None
    chapter_plan: List[Dict] = field(default_factory=list)
    novel_title: str = ""

    # 写作管线状态
    pipeline_step: int = 0  # 0=空闲, 1=预检, 2=生成, 3=审校, 4=定稿
    is_writing: bool = False
    write_progress: float = 0.0
    write_word_count: int = 0
    write_target_words: int = 0
    write_stream_content: str = ""
    write_error: Optional[str] = None

    # 审校状态
    review_report: Optional[Dict] = None
    review_passed: Optional[bool] = None

    # 服务实例（懒加载）
    _memory: any = None
    _continuity: any = None
    _foreshadow: any = None
    _rag: any = None
    _ctx: Optional[config.ProjectContext] = None

    # 待管线内共享的数据
    _pending_content: str = ""
    _pending_settings: Optional[Dict] = None

    # UI 控制
    current_tab: int = 0
    route_control: Optional[ft.AnimatedSwitcher] = None

    def refresh_projects(self):
        from novel_agent.project import list_projects
        self.projects = list_projects()
        if self.projects and not self.current_project:
            from novel_agent.cli.commands import get_current_project_name
            name = get_current_project_name()
            if name and any(p["name"] == name for p in self.projects):
                self.switch_project(name)

    def switch_project(self, name: str):
        from novel_agent.cli.commands import set_current_project
        set_current_project(name)
        self._ctx = config.set_project(name)
        self.current_project = name
        self._memory = self._continuity = self._foreshadow = self._rag = None
        self._load_outline()
        self._update_title()

    def get_services(self):
        if not self._memory and self._ctx:
            svc = init_services(self._ctx)
            self._memory = svc.memory
            self._continuity = svc.continuity
            self._foreshadow = svc.foreshadow
            self._rag = svc.rag
        return self._memory, self._continuity, self._foreshadow, self._rag

    def _load_outline(self):
        if not self._ctx:
            self.outline = None
            self.chapter_plan = []
            self.novel_title = ""
            return
        outline_path = self._ctx.data_dir / "outline.json"
        if outline_path.exists():
            import json
            with open(outline_path, encoding="utf-8") as f:
                self.outline = json.load(f)
            from novel_agent.cli.commands import _get_chapter_plan
            self.chapter_plan = _get_chapter_plan(self.outline)
            meta = self.outline.get("meta", {})
            self.novel_title = meta.get("title", self.outline.get("title", self.current_project or ""))
        else:
            self.outline = None
            self.chapter_plan = []
            self.novel_title = self.current_project or ""

    def _update_title(self):
        if self.page and hasattr(self.page, "appbar") and self.page.appbar:
            title = self.novel_title or self.current_project or "无"
            if len(self.page.appbar.actions) > 0:
                self.page.appbar.actions[0] = ft.Text(f"项目: 《{title}》", size=14)
                self.page.update()
