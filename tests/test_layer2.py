"""tests/test_layer2.py - 三层 Agent Layer2 mock-LLM 测试"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from novel_agent.agents.writer import WriterAgent
from novel_agent.agents.planner import PlannerAgent
from novel_agent.agents.reviewer import ReviewerAgent


# ========== 测试数据 ==========

LONG_CHAPTER = "叶青云站在山巅，眺望远方。" * 200

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

MOCK_EXTEND_OUTLINE = json.dumps({
    "volumes": [{"volume": 2, "title": "v2",
                  "chapters": [{"chapter": 2, "title": "新章", "summary": "剧情推进"}],
                  "arc": {"setback_chapter": 5, "insight_chapter": 8,
                          "breakthrough_chapter": 12, "new_challenge_chapter": 15}}],
    "characters": [], "locations": [], "factions": [], "key_items": [], "foreshadows": [],
})

MOCK_REVIEW_JSON = """```json
{
    "continuity": 8, "character": 7, "plot": 6, "writing": 8,
    "overall": 7, "verdict": "通过"
}
```"""


# ==================== Fixtures ====================

@pytest.fixture
def tmp_dir():
    d = Path(tempfile.mkdtemp())
    (d / "chapters").mkdir(exist_ok=True)
    return d


@pytest.fixture
def mock_ctx(tmp_dir):
    ctx = MagicMock()
    ctx.output_dir = tmp_dir
    ctx.chapters_dir = tmp_dir / "chapters"
    return ctx


@pytest.fixture
def mock_all():
    return MagicMock(), MagicMock(), MagicMock()


# ================================================================
# WriterAgent Layer2
# ================================================================

class TestWriterLayer2:
    @pytest.fixture
    def writer(self, mock_all, mock_ctx):
        memory, cg, fs = mock_all
        memory.outline = {}
        memory.characters = {}
        memory.get_active_tasks.return_value = []
        cg.character_locations = []
        w = WriterAgent(memory, cg, fs, ctx=mock_ctx, genre="玄幻", style="热血")
        return w

    def test_write_chapter_normal(self, writer):
        with patch("novel_agent.agents.writer.generate", return_value=MOCK_CHAPTER_OUTPUT):
            content, settings = writer.write_chapter(
                chapter=1, title="第一章", summary="主角修炼",
                time_tag="第一天", location="宗门", characters=["叶青云"],
            )
        assert "叶青云站在山巅" in content

    def test_write_chapter_with_ontoken(self, writer, tmp_dir):
        (tmp_dir / "chapters" / "chapter_001.md").write_text("第一版", encoding="utf-8")
        tokens = []
        def collector(t):
            tokens.append(t)
        stream_tokens = ["叶青云站在山巅。" * 200]  # 够长
        with patch("novel_agent.agents.writer.generate_stream",
                   return_value=stream_tokens):
            content, settings = writer.write_chapter(
                chapter=2, title="第二章", summary="继续",
                time_tag="第二天", location="后山", characters=["叶青云"],
                on_token=collector,
            )
        assert "叶青云站在山巅" in content

    def test_write_chapter_content_too_short_raises(self, writer, tmp_dir):
        (tmp_dir / "chapters" / "chapter_002.md").write_text("前文", encoding="utf-8")
        with patch("novel_agent.agents.writer.generate", return_value="短"):
            with pytest.raises(RuntimeError, match="内容过短"):
                writer.write_chapter(
                    chapter=3, title="第三章", summary="短章",
                    time_tag="第三天", location="密室", characters=["叶青云"],
                )

    def test_revise_chapter_normal(self, writer):
        with patch("novel_agent.agents.writer.generate", return_value=MOCK_CHAPTER_OUTPUT):
            content, settings = writer.revise_chapter(
                chapter=4, title="第四章", original_content="旧版",
                review_report="需要修改", summary="修订",
                time_tag="第四天", location="大殿", characters=["叶青云"],
            )
        assert "叶青云站在山巅" in content

    def test_patch_chapter_with_keyword(self, writer):
        patches = [{"severity": "高", "description": "修正",
                     "location_keyword": "山巅"}]
        original = "叶青云站在山巅。\n\n风吹过。"
        with patch("novel_agent.agents.writer.generate", return_value="修补后的山巅段落。"):
            result = writer.patch_chapter(
                chapter=5, title="第五章", original_content=original,
                patches=patches, summary="修补", characters=["叶青云"],
            )
        assert "修补后的山巅段落" in result
        assert "风吹过" in result


# ================================================================
# PlannerAgent Layer2
# ================================================================

class TestPlannerLayer2:
    @pytest.fixture
    def planner(self, mock_all, tmp_dir):
        memory, cg, fs = mock_all
        memory.characters = {}
        memory.data_dir = tmp_dir
        fs.foreshadows = []
        p = PlannerAgent(memory, cg, fs, MagicMock())
        p.memory = memory
        p.ctx.data_dir = tmp_dir
        return p

    def test_generate_outline_success(self, planner):
        with patch("novel_agent.agents.planner.generate", return_value=MOCK_VALID_OUTLINE):
            result = planner.generate_outline("修仙故事", "玄幻", "热血")
        assert isinstance(result, dict)
        assert result["meta"]["title"] == "修仙传"

    def test_generate_outline_retry_then_success(self, planner):
        side_effects = ["无效内容", MOCK_VALID_OUTLINE]
        with patch("novel_agent.agents.planner.generate", side_effect=side_effects):
            result = planner.generate_outline("测试")
        assert result["meta"]["title"] == "修仙传"

    def test_generate_outline_all_retries_fail(self, planner):
        with patch("novel_agent.agents.planner.generate", return_value="不是 JSON"):
            with pytest.raises(ValueError, match="JSON 解析失败"):
                planner.generate_outline("测试")

    def test_refine_outline(self, planner):
        existing = {"meta": {"title": "t"}, "volumes": [],
                    "characters": [], "locations": [],
                    "factions": [], "key_items": [], "foreshadows": []}
        with patch("novel_agent.agents.planner.generate", return_value=MOCK_VALID_OUTLINE):
            result = planner.refine_outline(existing, "加一个反派")
        assert result["meta"]["title"] == "修仙传"

    def _make_existing_outline(self):
        return {
            "meta": {"title": "t"},
            "volumes": [{"volume": 1, "title": "v1", "arc": {"setback_chapter": 1},
                          "chapters": [{"chapter": 1}]}],
            "characters": [], "locations": [],
            "factions": [], "key_items": [], "foreshadows": [],
        }

    def test_extend_outline_success(self, planner):
        existing = self._make_existing_outline()
        with patch("novel_agent.agents.planner.generate", return_value=MOCK_EXTEND_OUTLINE), \
             patch.object(planner, '_run_self_check', return_value=[]):
            result, added = planner.extend_outline(existing, volumes_to_add=1)
        assert added == 1
        assert len(result["volumes"]) == 2

    def test_extend_outline_truncation_auto_reduce(self, planner):
        existing = self._make_existing_outline()
        truncated = '{"volumes": [{"volume": 2, "title": "v2", "chapters": [{"chapter": 2}],'
        with patch("novel_agent.agents.planner.generate",
                   side_effect=[truncated, MOCK_EXTEND_OUTLINE]), \
             patch.object(planner, '_run_self_check', return_value=[]):
            result, added = planner.extend_outline(existing, volumes_to_add=2)
        assert added == 1
        assert len(result["volumes"]) == 2

    def test_extend_outline_parse_error_auto_reduce(self, planner):
        existing = self._make_existing_outline()
        with patch("novel_agent.agents.planner.generate",
                   side_effect=["不是 JSON", MOCK_EXTEND_OUTLINE]), \
             patch.object(planner, '_run_self_check', return_value=[]):
            result, added = planner.extend_outline(existing, volumes_to_add=2)
        assert added == 1
        assert len(result["volumes"]) == 2

    def test_extend_outline_all_retries_exhausted(self, planner):
        existing = self._make_existing_outline()
        with patch("novel_agent.agents.planner.generate", return_value="无效内容"), \
             patch.object(planner, '_run_self_check', return_value=[]):
            with pytest.raises(ValueError, match="大纲扩展失败"):
                planner.extend_outline(existing, volumes_to_add=1)


# ================================================================
# ReviewerAgent Layer2
# ================================================================

class TestReviewerLayer2:
    @pytest.fixture
    def reviewer(self, mock_all):
        memory, cg, fs = mock_all
        cg.character_locations = []
        cg.timeline = []
        r = ReviewerAgent(memory, cg, fs)
        return r

    def test_review_chapter_normal(self, reviewer):
        with patch("novel_agent.agents.reviewer.generate", return_value=MOCK_REVIEW_JSON):
            report = reviewer.review_chapter(
                chapter=1, title="第一章", content="叶青云修炼。",
            )
        assert report["verdict"] == "通过"
        assert report["passed"] is True
        assert report["scores"]["连续性"] == 8

    def test_review_chapter_with_characters(self, reviewer):
        with patch("novel_agent.agents.reviewer.generate", return_value=MOCK_REVIEW_JSON):
            report = reviewer.review_chapter(
                chapter=2, title="第二章", content="内容",
                characters=["叶青云", "配角"],
            )
        assert report["verdict"] == "通过"

    def test_review_chapter_fallback_verdict(self, reviewer):
        text_output = "本章整体质量良好，通过。"
        with patch("novel_agent.agents.reviewer.generate", return_value=text_output):
            report = reviewer.review_chapter(
                chapter=3, title="第三章", content="内容。",
            )
        assert report["verdict"] == "通过"

    def test_review_not_pass(self, reviewer):
        text_output = "严重问题：时间线矛盾。需重写。"
        with patch("novel_agent.agents.reviewer.generate", return_value=text_output):
            report = reviewer.review_chapter(
                chapter=4, title="第四章", content="内容。",
            )
        assert report["verdict"] == "需重写"
        assert report["passed"] is False
