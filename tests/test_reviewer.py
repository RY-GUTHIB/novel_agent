"""tests/test_reviewer.py - ReviewerAgent Layer1 纯函数测试（零 mock LLM）"""

import config
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from novel_agent.agents.reviewer import ReviewerAgent


# ========== Fixtures ==========

@pytest.fixture
def memory():
    return MagicMock()


@pytest.fixture
def continuity():
    return MagicMock()


@pytest.fixture
def foreshadow():
    return MagicMock()


@pytest.fixture
def reviewer(memory, continuity, foreshadow):
    return ReviewerAgent(memory, continuity, foreshadow)


# ================================================================
# Layer 1: _build_anti_ai_rules
# ================================================================

class TestBuildAntiAIRules:
    def test_enabled(self, reviewer):
        with patch.object(config, "ENABLE_ANTI_AI_MODE", True), \
             patch.object(config, "ANTI_AI_CONFIG", {
                 "check_window": 500, "density_limit": 2,
                 "high_stakes_words": ["瞳孔", "眼底"],
             }):
            result = reviewer._build_anti_ai_rules()
            assert "密度红线" in result
            assert "500" in result
            assert "瞳孔" in result

    def test_disabled(self, reviewer):
        with patch.object(config, "ENABLE_ANTI_AI_MODE", False):
            assert reviewer._build_anti_ai_rules() == "（未启用）"


# ================================================================
# Layer 1: _parse_review
# ================================================================

class TestParseReview:
    def test_json_block_scores(self, reviewer):
        text = """其他内容。
```json
{
    "continuity": 8, "character": 7, "plot": 6, "writing": 9,
    "overall": 7, "verdict": "通过"
}
```"""
        result = reviewer._parse_review(text)
        assert result["scores"]["连续性"] == 8
        assert result["scores"]["人物一致性"] == 7
        assert result["overall_score"] == 7
        assert result["verdict"] == "通过"
        assert result["passed"] is True

    def test_regex_fallback(self, reviewer):
        text = "- 连续性：7分\n- 文笔质量：8分\n"
        with patch.object(config, "ENABLE_ANTI_AI_MODE", False):
            result = reviewer._parse_review(text)
        assert result["scores"]["连续性"] == 7
        assert result["scores"]["文笔质量"] == 8

    def test_issues_from_severity_markers(self, reviewer):
        text = (
            "⚠️ [严重性：高] 时间线矛盾\n定位关键词「第3段」\n"
            "⚠️ 严重性：中 人物性格偏移\n"
        )
        result = reviewer._parse_review(text)
        assert len(result["issues"]) == 2
        assert any(i["severity"] == "高" for i in result["issues"])
        assert any(i["severity"] == "中" for i in result["issues"])

    def test_patches_from_location_keyword(self, reviewer):
        text = (
            "⚠️ [严重性：高] 需要修改\n"
            "定位：关键词「不存在的关键词」\n"
        )
        result = reviewer._parse_review(text)
        assert len(result["patches"]) == 1
        assert result["patches"][0]["location_keyword"] == "不存在的关键词"

    def test_issues_fallback_lines(self, reviewer):
        text = "⚠️ 问题1\n一些内容\n警告：问题2"
        result = reviewer._parse_review(text)
        assert len(result["issues"]) == 2

    def test_verdict_pass_from_text(self, reviewer):
        text = "总体评价：通过"
        result = reviewer._parse_review(text)
        assert result["verdict"] == "通过"
        assert result["passed"] is True

    def test_verdict_rewrite_from_text(self, reviewer):
        text = "需重写：结构性问题严重"
        result = reviewer._parse_review(text)
        assert result["verdict"] == "需重写"

    def test_verdict_default_modify(self, reviewer):
        text = "一些普通评价"
        result = reviewer._parse_review(text)
        assert result["verdict"] == "需修改"
        assert result["passed"] is False

    def test_overall_from_average(self, reviewer):
        text = "- 连续性：8分\n- 文笔质量：6分\n"
        with patch.object(config, "ENABLE_ANTI_AI_MODE", False):
            result = reviewer._parse_review(text)
        # JSON未解析，overall应为0，然后回退到平均值
        assert result["overall_score"] == 7

    def test_empty_text(self, reviewer):
        result = reviewer._parse_review("")
        assert result["scores"] == {}
        assert result["verdict"] == "需修改"
        assert result["passed"] is False


# ================================================================
# Layer 1: save_review_report
# ================================================================

class TestSaveReviewReport:
    def test_saves_report_file(self, reviewer):
        out_dir = Path(tempfile.mkdtemp())
        report = {"raw_text": "测试审校内容"}
        reviewer.save_review_report(5, report, str(out_dir))
        report_path = out_dir / "review_chapter_005.md"
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "第5章" in content
        assert "测试审校内容" in content

    def test_creates_output_dir(self, reviewer):
        out_dir = Path(tempfile.mkdtemp()) / "nested" / "dir"
        report = {"raw_text": "test"}
        reviewer.save_review_report(1, report, str(out_dir))
        assert out_dir.exists()
        assert (out_dir / "review_chapter_001.md").exists()
