"""tests/test_layer3.py - 三层 Agent Layer3 集成测试（mock 全部外部依赖）"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY

import pytest

import config
from novel_agent.agents.writer import WriterAgent
from novel_agent.agents.planner import PlannerAgent
from novel_agent.agents.reviewer import ReviewerAgent


# ========== 测试数据 ==========

LONG_CHAPTER = ("叶青云站在山巅，眺望远方。" * 200) + "\n[FS: 古卷残页]\n"

MOCK_CHAPTER_OUTPUT = (
    "===PRE_FLIGHT_CHECK===\n"
    "### 硬约束\n✅ 全部通过，开始正文\n"
    + LONG_CHAPTER + "\n"
)

MOCK_VALID_OUTLINE = json.dumps({
    "meta": {"title": "修仙传", "setting": "修仙世界"},
    "volumes": [],
    "characters": [], "locations": [],
    "factions": [], "key_items": [], "foreshadows": [],
})

MOCK_EXTEND_JSON = json.dumps({
    "volumes": [{"volume": 2, "title": "v2",
                  "chapters": [{"chapter": 2, "title": "新章", "summary": "剧情推进"}],
                  "arc": {"setback_chapter": 5, "insight_chapter": 8,
                          "breakthrough_chapter": 12, "new_challenge_chapter": 15}}],
    "characters": [], "locations": [],
    "factions": [], "key_items": [], "foreshadows": [],
})

LONG_CONTENT = "叶青云在修炼。" * 500

MOCK_REVIEW_PASS = """```json
{
    "continuity": 8, "character": 7, "plot": 7, "writing": 8,
    "foreshadow": 8, "rules": 8, "knowledge": 8,
    "overall": 8, "verdict": "通过"
}
```"""

MOCK_REVIEW_FAIL = """```json
{
    "continuity": 4, "character": 5, "plot": 5, "writing": 6,
    "foreshadow": 8, "rules": 8, "knowledge": 8,
    "overall": 5, "verdict": "需修改"
}
```"""


# ==================== Fixtures ====================

@pytest.fixture
def tmp_dir():
    d = Path(tempfile.mkdtemp())
    (d / "chapters").mkdir(exist_ok=True)
    (d / "reviews").mkdir(exist_ok=True)
    return d


# ================================================================
# WriterAgent Layer3 — 完整写作+终审流程
# ================================================================

class TestWriterIntegration:
    @pytest.fixture
    def writer(self, tmp_dir):
        ctx = MagicMock()
        ctx.output_dir = tmp_dir
        ctx.chapters_dir = tmp_dir / "chapters"

        memory = MagicMock()
        memory.outline = {"volumes": [{"volume": 1, "chapters": [{"chapter": 1}]}]}
        memory.characters = {}
        memory.get_active_tasks.return_value = []
        memory.build_state_snapshot.return_value = "state_snapshot"

        cg = MagicMock()
        cg.character_locations = []
        cg.timeline = []
        cg.check_continuity.return_value = []
        cg.get_events_for_chapter.return_value = []

        fs = MagicMock()
        fs.foreshadows = []
        fs.plant.return_value = "FS_001"
        fs.auto_resolve.return_value = 0
        fs.exists.return_value = False

        w = WriterAgent(memory, cg, fs, ctx=ctx, genre="玄幻", style="热血")
        # _applier 也 mock
        w._applier = MagicMock()
        w.validator = MagicMock()
        w.validator.validate.return_value = []
        w.rag = MagicMock()
        return w

    def test_write_and_finalize_full_flow(self, writer, tmp_dir):
        with patch("novel_agent.agents.writer.generate", return_value=MOCK_CHAPTER_OUTPUT):
            content, settings = writer.write_chapter(
                chapter=1, title="第一章", summary="主角修炼",
                time_tag="第一天", location="宗门", characters=["叶青云"],
            )
        assert "叶青云站在山巅" in content

        writer.finalize_chapter(
            chapter=1, content=content, summary="主角修炼",
            time_tag="第一天", location="宗门", characters=["叶青云"],
            title="第一章",
            settings_json='{"foreshadows":[{"content":"古卷残页","type":"mystery","importance":3,"related_characters":["叶青云"]}]}',
        )

        # 验证：章节文件已保存
        saved_path = tmp_dir / "chapters" / "chapter_001.md"
        assert saved_path.exists()

        # 验证：时间线事件已添加
        writer.continuity.add_event.assert_called_once()

        # 验证：伏笔已种植（来自 settings_json 的 foreshadows）
        writer.foreshadow.plant.assert_called()

        # 验证：人物位置已记录
        writer.continuity.add_character_location.assert_called()

        # 验证：RAG 已存储
        writer.rag.add_chapter.assert_called_once()

    def test_review_loop_passes_first_time(self, writer, tmp_dir):
        with patch("novel_agent.agents.writer.generate", return_value=MOCK_CHAPTER_OUTPUT):
            content, settings = writer.write_chapter(
                chapter=2, title="第二章", summary="修炼",
                time_tag="第二天", location="后山", characters=["叶青云"],
            )

        reviewer = MagicMock()
        reviewer.review_chapter.return_value = {
            "scores": {}, "overall_score": 8, "issues": [],
            "patches": [], "verdict": "通过", "passed": True,
            "raw_text": MOCK_REVIEW_PASS,
        }

        writer.review_loop(
            reviewer=reviewer, chapter=2, title="第二章",
            content=content, summary="修炼",
            time_tag="第二天", location="后山",
            characters=["叶青云"],
        )

        # 只审校了一次（因为通过了）
        reviewer.review_chapter.assert_called_once()

    def test_review_loop_revises_then_passes(self, writer, tmp_dir):
        with patch("novel_agent.agents.writer.generate", return_value=MOCK_CHAPTER_OUTPUT):
            content, settings = writer.write_chapter(
                chapter=3, title="第三章", summary="修炼",
                time_tag="第三天", location="大殿", characters=["叶青云"],
            )

        reviewer = MagicMock()
        reviewer.review_chapter.side_effect = [
            {"scores": {}, "overall_score": 5, "issues": [{"severity": "高", "description": "修正"}],
             "patches": [], "verdict": "需修改", "passed": False, "raw_text": MOCK_REVIEW_FAIL},
            {"scores": {}, "overall_score": 8, "issues": [],
             "patches": [], "verdict": "通过", "passed": True, "raw_text": MOCK_REVIEW_PASS},
        ]

        with patch("novel_agent.agents.writer.generate", return_value=MOCK_CHAPTER_OUTPUT):
            writer.review_loop(
                reviewer=reviewer, chapter=3, title="第三章",
                content=content, summary="修炼",
                time_tag="第三天", location="大殿",
                characters=["叶青云"],
            )

        # 审校两次：第一次不通过，第二次通过
        assert reviewer.review_chapter.call_count == 2

    def test_finalize_with_valid_settings(self, writer, tmp_dir):
        settings_json = json.dumps({
            "character_updates": [{"name": "叶青云", "cultivation": "筑基"}],
        })
        content = "正文内容。" * 300

        writer.finalize_chapter(
            chapter=5, content=content, summary="突破",
            time_tag="第五天", location="密室",
            characters=["叶青云"], title="第五章",
            settings_json=settings_json,
        )

        # 验证设定被应用
        writer._applier.apply_all.assert_called_once()

        # 验证章节已保存
        saved = tmp_dir / "chapters" / "chapter_005.md"
        assert saved.exists()


# ================================================================
# PlannerAgent Layer3 — 完整大纲生成+扩展流程
# ================================================================

class TestPlannerIntegration:
    @pytest.fixture
    def planner(self, tmp_dir):
        memory = MagicMock()
        memory.characters = {}
        memory.data_dir = tmp_dir

        cg = MagicMock()
        cg.timeline = []
        cg.spacemap = {}
        cg.character_locations = []
        cg.absolute_day = 0
        cg._time_updated_chapters = set()

        fs = MagicMock()
        fs.foreshadows = []

        ctx = MagicMock()
        ctx.data_dir = tmp_dir

        p = PlannerAgent(memory, cg, fs, ctx)
        return p

    def test_generate_outline_full_flow(self, planner, tmp_dir):
        with patch("novel_agent.agents.planner.generate", return_value=MOCK_VALID_OUTLINE):
            result = planner.generate_outline("修仙故事")
        assert isinstance(result, dict)
        assert result["meta"]["title"] == "修仙传"

        # verify memory/continuity/foreshadow save were called
        planner.memory.save_all.assert_called_once()
        planner.continuity.save_all.assert_called_once()
        planner.foreshadow.save.assert_called_once()

    def test_extend_outline_full_flow(self, planner, tmp_dir):
        existing = {
            "meta": {"title": "t"},
            "volumes": [{"volume": 1, "title": "v1", "arc": {"setback_chapter": 1},
                          "chapters": [{"chapter": 1}]}],
            "characters": [], "locations": [],
            "factions": [], "key_items": [], "foreshadows": [],
        }
        with patch("novel_agent.agents.planner.generate", return_value=MOCK_EXTEND_JSON), \
             patch.object(planner, '_run_self_check', return_value=[]):
            result, added = planner.extend_outline(existing, volumes_to_add=1)
        assert added == 1
        assert len(result["volumes"]) == 2

        # 验证合并后的大纲已保存
        outline_path = tmp_dir / "outline.json"
        assert outline_path.exists()

    def test_refine_outline_full_flow(self, planner):
        existing = {"meta": {"title": "t"}, "volumes": [],
                    "characters": [], "locations": [],
                    "factions": [], "key_items": [], "foreshadows": []}
        with patch("novel_agent.agents.planner.generate", return_value=MOCK_VALID_OUTLINE):
            result = planner.refine_outline(existing, "加情节")
        assert result["meta"]["title"] == "修仙传"


# ================================================================
# ReviewerAgent Layer3 — 完整审校流程
# ================================================================

class TestReviewerIntegration:
    @pytest.fixture
    def reviewer(self, tmp_dir):
        memory = MagicMock()
        memory.characters = {}
        memory.build_state_snapshot.return_value = "快照"
        memory.get_active_rules_prompt.return_value = "规则"
        memory.get_character_knowledge_prompt.return_value = "认知"
        memory.get_all_characters_prompt.return_value = "所有角色"
        memory.get_sect_factions_prompt.return_value = "势力"
        memory.get_scene_events_prompt.return_value = "场景事件"
        memory.get_style_prompt.return_value = "风格"
        memory.get_outline_context_prompt.return_value = "大纲上下文"

        cg = MagicMock()
        cg.character_locations = []
        cg.timeline = []
        cg.generate_continuity_prompt.return_value = "连续性prompt"
        cg.get_spacemap_prompt.return_value = "空间地图"

        fs = MagicMock()
        fs.summarize.return_value = "伏笔摘要"

        r = ReviewerAgent(memory, cg, fs)
        return r

    def test_review_with_full_context(self, reviewer):
        with patch("novel_agent.agents.reviewer.generate", return_value=MOCK_REVIEW_PASS):
            report = reviewer.review_chapter(
                chapter=1, title="第一章", content=LONG_CONTENT,
                characters=["叶青云", "配角"],
            )
        assert report["verdict"] == "通过"
        assert report["passed"] is True

    def test_review_and_fails(self, reviewer):
        with patch("novel_agent.agents.reviewer.generate", return_value=MOCK_REVIEW_FAIL):
            report = reviewer.review_chapter(
                chapter=2, title="第二章", content=LONG_CONTENT,
                characters=["叶青云"],
            )
        assert report["verdict"] == "需修改"
        assert report["passed"] is False
        assert report["overall_score"] == 5

    def test_review_saves_report(self, reviewer, tmp_dir):
        with patch("novel_agent.agents.reviewer.generate", return_value=MOCK_REVIEW_PASS):
            report = reviewer.review_chapter(
                chapter=3, title="第三章", content=LONG_CONTENT,
            )
        reviewer.save_review_report(3, report, str(tmp_dir / "reviews"))
        report_path = tmp_dir / "reviews" / "review_chapter_003.md"
        assert report_path.exists()
        assert "第3章" in report_path.read_text(encoding="utf-8")
