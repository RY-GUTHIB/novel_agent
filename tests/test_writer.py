"""tests/test_writer.py - WriterAgent Layer1 纯函数测试（零 mock LLM）"""

import re
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import config
from novel_agent.agents.writer import WriterAgent


# ========== Fixtures ==========

@pytest.fixture
def mock_ctx():
    """返回一个临时目录的 ProjectContext mock"""
    ctx = MagicMock()
    ctx.output_dir = Path(tempfile.mkdtemp())
    ctx.chapters_dir = ctx.output_dir / "chapters"
    ctx.chapters_dir.mkdir(parents=True, exist_ok=True)
    return ctx


@pytest.fixture
def memory(mock_ctx):
    m = MagicMock()
    m.outline = {}
    m.characters = {}
    return m


@pytest.fixture
def writer(memory, mock_ctx):
    cg = MagicMock()
    fs = MagicMock()
    return WriterAgent(memory, cg, fs, ctx=mock_ctx, genre="玄幻", style="热血")


# ================================================================
# Layer 1: _clean_content
# ================================================================

class TestCleanContent:
    def test_strips_hard_constraint_check_section(self, writer):
        text = "正常正文。\n### 硬约束\n🔴 规则：不违反\n✅ 全部通过\n继续正常正文。"
        result = writer._clean_content(text)
        assert "正常正文" in result
        assert "### 硬约束" not in result
        assert "🔴 规则" not in result

    def test_strips_repair_confirmation(self, writer):
        text = "正常段落。\n修复确认：\n- ✅ 问题1已修复\n- ✅ 问题2已修复\n下一段正文。"
        result = writer._clean_content(text)
        assert "修复确认" not in result
        assert "✅ 问题1" not in result
        assert "下一段正文" in result

    def test_preserves_plain_text(self, writer):
        text = "叶青云走在山路上。\n\n阳光洒落。"
        assert writer._clean_content(text) == text

    def test_mixed_check_and_normal(self, writer):
        text = ("开头。\n### 写作中注意\n🟡 情节推进：已确认\n"
                "正常段落。\n### 硬约束\n🔴 规则检查\n✅ 全部通过\n结尾。")
        result = writer._clean_content(text)
        assert "开头" in result
        assert "正常段落" in result
        assert "结尾" in result
        assert "### 写作中注意" not in result
        assert "🟡 情节推进" not in result

    def test_only_normal_content(self, writer):
        text = "纯正文内容。\n没有标记。"
        assert writer._clean_content(text) == text

    def test_empty_string(self, writer):
        assert writer._clean_content("") == ""

    def test_check_exit_on_non_check_line(self, writer):
        """自检段内遇到非检查行退出自检模式"""
        text = "### 硬约束\n🔴 检查项\n这是正文\n### 修复确认\n- ✅ 修复项\n更多正文。"
        result = writer._clean_content(text)
        assert "这是正文" in result
        assert "更多正文" in result
        assert "🔴 检查项" not in result


# ================================================================
# Layer 1: _split_output_and_settings
# ================================================================

class TestSplitOutputAndSettings:
    def test_strips_flight_marker(self, writer):
        raw = ("无关前言。\n===PRE_FLIGHT_CHECK===\n"
               "### 硬约束\n🔴 规则：不违反\n✅ 全部通过，开始正文\n"
               "正文开始。")
        result = writer._split_output_and_settings(raw)
        assert "正文开始" in result
        assert "===PRE_FLIGHT_CHECK===" not in result
        assert "无关前言" not in result
        assert "硬约束" not in result

    def test_strips_settings_marker(self, writer):
        raw = "正文内容。\n===SETTINGS_JSON===\n{\"key\":\"value\"}"
        result = writer._split_output_and_settings(raw)
        assert "正文内容" in result
        assert "===SETTINGS_JSON===" not in result

    def test_no_markers_passthrough(self, writer):
        raw = "纯正文。\n第二段。"
        assert writer._split_output_and_settings(raw) == "纯正文。\n第二段。"

    def test_empty_input(self, writer):
        assert writer._split_output_and_settings("") == ""

    def test_all_markers(self, writer):
        raw = ("开头被丢弃。\n===PRE_FLIGHT_CHECK===\n### 硬约束\n🔴 检查\n✅ 全部通过，开始正文\n"
               "正文内容。\n===SETTINGS_JSON===\n{}")
        result = writer._split_output_and_settings(raw)
        assert "正文内容" in result
        assert "开头被丢弃" not in result  # flight_marker 之前的内容被丢弃
        assert "硬约束" not in result

    def test_flight_regex_fallback(self, writer):
        """无 ===PRE_FLIGHT_CHECK=== 标记时用正则匹配"""
        raw = ("### 硬约束\n🔴 规则检查\n✅ 全部通过，开始正文\n正文内容。\n"
               "更多内容。")
        result = writer._split_output_and_settings(raw)
        assert "正文内容" in result
        assert "### 硬约束" not in result

    def test_whitespace_only(self, writer):
        assert writer._split_output_and_settings("   \n  ") == ""


# ================================================================
# Layer 1: _extract_foreshadows
# ================================================================

class TestExtractForeshadows:
    def test_fs_bracket_marker(self, writer):
        content = "正文[FS: 古卷残页闪烁]正文"
        result = writer._extract_foreshadows(content, 1)
        assert "古卷残页闪烁" in result

    def test_fs_colon_prefix(self, writer):
        content = "FS：隐藏身份\n下一行"
        result = writer._extract_foreshadows(content, 1)
        assert "隐藏身份" in result

    def test_fs_bracket_colon(self, writer):
        content = "[FS：上古秘境]"
        result = writer._extract_foreshadows(content, 1)
        assert "上古秘境" in result

    def test_multiple_foreshadows(self, writer):
        content = ("[FS: 铜钱]正文[FS: 玉佩]正文"
                   "FS：身世之谜")
        result = writer._extract_foreshadows(content, 1)
        assert len(result) == 3
        assert "铜钱" in result
        assert "玉佩" in result
        assert "身世之谜" in result

    def test_dedup(self, writer):
        content = "[FS: 重复]正文[FS: 重复]"
        result = writer._extract_foreshadows(content, 1)
        assert len(result) == 1

    def test_no_matches(self, writer):
        assert writer._extract_foreshadows("纯正文无伏笔", 1) == []

    def test_short_foreshadow(self, writer):
        """至少 2 个中文字符的短伏笔"""
        content = "[FS: 破局]"
        result = writer._extract_foreshadows(content, 1)
        assert "破局" in result


# ================================================================
# Layer 1: _get_rhythm_for_chapter / _get_beat_type / _get_hook_type
# ================================================================

OUTLINE_WITH_VOLUMES = {
    "volumes": [{
        "volume": 1,
        "title": "初入宗门",
        "chapters": [
            {"chapter": 1, "title": "入门", "summary": "主角突破炼气三层"},
            {"chapter": 2, "title": "战斗", "summary": "战斗妖兽追杀"},
            {"chapter": 3, "title": "秘密", "summary": "发现秘密真相调查"},
            {"chapter": 4, "title": "感情", "summary": "表白感情决裂"},
            {"chapter": 5, "title": "身份", "summary": "隐藏身份揭露"},
            {"chapter": 6, "title": "收获", "summary": "收获机缘得到"},
            {"chapter": 7, "title": "日常", "summary": "平淡过渡章节"},
        ]
    }]
}


class TestChapterMeta:
    def test_found_in_volumes(self, writer):
        writer.memory.outline = OUTLINE_WITH_VOLUMES
        meta = writer._get_chapter_meta(1)
        assert meta["title"] == "入门"

    def test_found_in_chapter_plan(self, writer):
        writer.memory.outline = {
            "chapter_plan": [
                {"chapter": 1, "title": "旧格式", "summary": "兼容"}
            ]
        }
        meta = writer._get_chapter_meta(1)
        assert meta["title"] == "旧格式"

    def test_not_found(self, writer):
        writer.memory.outline = OUTLINE_WITH_VOLUMES
        meta = writer._get_chapter_meta(99)
        assert meta == {}


class TestRhythmForChapter:
    @pytest.fixture(autouse=True)
    def setup(self, writer):
        writer.memory.outline = OUTLINE_WITH_VOLUMES

    def test_breakthrough_keyword(self, writer):
        r = writer._get_rhythm_for_chapter(1)
        assert "突破" in r

    def test_battle_keyword(self, writer):
        r = writer._get_rhythm_for_chapter(2)
        assert "过山车" in r

    def test_mystery_keyword(self, writer):
        r = writer._get_rhythm_for_chapter(3)
        assert "悬疑" in r

    def test_emotion_keyword(self, writer):
        r = writer._get_rhythm_for_chapter(4)
        assert "情感曲线" in r

    def test_fallback_cycle(self, writer):
        results = [writer._get_rhythm_for_chapter(i) for i in range(7, 12)]
        assert len(set(results)) > 1  # 轮询产生不同结果

    def test_empty_summary(self, writer):
        writer.memory.outline = {
            "volumes": [{"volume": 1, "title": "v1",
                         "chapters": [{"chapter": 99, "title": "无摘要",
                                       "summary": ""}]}]
        }
        r = writer._get_rhythm_for_chapter(99)  # 空摘要走轮询
        assert isinstance(r, str) and len(r) > 5


class TestBeatTypeForChapter:
    @pytest.fixture(autouse=True)
    def setup(self, writer):
        writer.memory.outline = OUTLINE_WITH_VOLUMES

    def test_face_slapping(self, writer):
        # 没有直接匹配"打脸"的，手动设
        writer.memory.outline = {
            "volumes": [{"volume": 1, "chapters": [{"chapter": 10, "summary": "打脸碾压教训"}]}]
        }
        b = writer._get_beat_type_for_chapter(10)
        assert "打脸时刻" in b

    def test_breakthrough(self, writer):
        b = writer._get_beat_type_for_chapter(1)
        assert "突破时刻" in b

    def test_identity(self, writer):
        b = writer._get_beat_type_for_chapter(5)
        assert "身份反转" in b

    def test_harvest(self, writer):
        b = writer._get_beat_type_for_chapter(6)
        assert "收获时刻" in b

    def test_emotion(self, writer):
        b = writer._get_beat_type_for_chapter(4)
        assert "感情推进" in b

    def test_fallback_cycle(self, writer):
        results = [writer._get_beat_type_for_chapter(i) for i in range(7, 12)]
        assert len(set(results)) > 1


class TestHookTypeForChapter:
    @pytest.fixture(autouse=True)
    def setup(self, writer):
        writer.memory.outline = OUTLINE_WITH_VOLUMES

    def test_mystery(self, writer):
        h = writer._get_hook_type_for_chapter(3)
        assert "信息炸弹" in h

    def test_breakthrough(self, writer):
        h = writer._get_hook_type_for_chapter(1)
        assert "悬念式" in h

    def test_battle(self, writer):
        h = writer._get_hook_type_for_chapter(2)
        assert "动作未完成" in h

    def test_reversal(self, writer):
        writer.memory.outline = {
            "volumes": [{"volume": 1, "chapters": [{"chapter": 20, "summary": "反转推翻认知"}]}]
        }
        h = writer._get_hook_type_for_chapter(20)
        assert "反转式" in h

    def test_fallback_cycle(self, writer):
        results = [writer._get_hook_type_for_chapter(i) for i in range(7, 14)]
        assert len(set(results)) > 1

    def test_empty_summary(self, writer):
        writer.memory.outline = {
            "volumes": [{"volume": 1, "chapters": [{"chapter": 99, "summary": ""}]}]
        }
        h = writer._get_hook_type_for_chapter(99)
        assert isinstance(h, str) and len(h) > 5


# ================================================================
# Layer 1: _build_anti_ai_rules
# ================================================================

class TestBuildAntiAIRules:
    def test_enabled(self, writer):
        with patch.object(config, "ENABLE_ANTI_AI_MODE", True), \
             patch.object(config, "ANTI_AI_CONFIG", {
                 "check_window": 500, "density_limit": 2,
                 "high_stakes_words": ["瞳孔", "眼底"],
             }):
            result = writer._build_anti_ai_rules()
            assert "密度红线" in result
            assert "500" in result
            assert "瞳孔" in result

    def test_disabled(self, writer):
        with patch.object(config, "ENABLE_ANTI_AI_MODE", False):
            assert writer._build_anti_ai_rules() == ""


# ================================================================
# Layer 1: _build_existing_tasks_text
# ================================================================

class TestBuildExistingTasksText:
    def test_no_tasks(self, writer):
        writer.memory.get_active_tasks.return_value = []
        result = writer._build_existing_tasks_text(5)
        assert result == "（无）"

    def test_one_active_task(self, writer):
        from novel_agent.core.models import TaskProfile
        t = TaskProfile(id="T_001", name="寻找灵药", description="去后山找灵芝",
                        chapter_created=1, status="active", progress=0.5,
                        related_characters=["主角"])
        writer.memory.get_active_tasks.return_value = [t]
        result = writer._build_existing_tasks_text(5)
        assert "T_001" in result
        assert "寻找灵药" in result
        assert "主角" in result

    def test_multiple_tasks_with_items(self, writer):
        from novel_agent.core.models import TaskProfile
        tasks = [
            TaskProfile(id="T_001", name="任务一", description="",
                        chapter_created=1, status="active", progress=0.3),
            TaskProfile(id="T_002", name="任务二", description="",
                        chapter_created=2, status="completed", progress=1.0,
                        related_items=["玉佩"]),
        ]
        writer.memory.get_active_tasks.return_value = tasks
        result = writer._build_existing_tasks_text(5)
        assert "T_001" in result
        assert "T_002" in result
        assert "玉佩" in result


# ================================================================
# Layer 1: _build_char_summary
# ================================================================

class TestBuildCharSummary:
    def test_character_not_in_memory(self, writer):
        writer.memory.characters = {}
        result = writer._build_char_summary(["无名氏"])
        assert result == "（无）"

    def test_single_character(self, writer):
        from novel_agent.core.models import CharacterProfile
        c = CharacterProfile(name="叶青云", gender="男", age="18岁",
                             cultivation="炼气三层", current_location="青云宗",
                             core_values="家族为重", core_desire="变强",
                             core_fear="被抛弃", flaw="冲动",
                             alignment="守序善良", status="活跃",
                             abilities=["天孤剑诀"], relationships={"师父": "传功"},
                             learned_skills=[{"skill": "基础剑法", "progress": 0.8}])
        writer.memory.characters = {"叶青云": c}
        result = writer._build_char_summary(["叶青云"])
        assert "叶青云" in result
        assert "炼气三层" in result

    def test_multiple_characters(self, writer):
        from novel_agent.core.models import CharacterProfile
        c1 = CharacterProfile(name="主角", gender="男", age="18",
                              abilities=["剑法"], cultivation="筑基")
        c2 = CharacterProfile(name="配角", gender="女", age="17",
                              abilities=["医术"], cultivation="炼气")
        writer.memory.characters = {"主角": c1, "配角": c2}
        writer.memory.characters = {"主角": c1, "配角": c2}
        result = writer._build_char_summary(["主角", "配角"])
        assert "主角" in result
        assert "配角" in result


# ================================================================
# Layer 1: _merge_foreshadows
# ================================================================

class TestMergeForeshadows:
    def test_explicit_only(self, writer):
        result = writer._merge_foreshadows(["伏笔A", "伏笔B"], [], 1)
        assert len(result) == 2
        assert all(fs["source"] == "显式标记" for fs in result)

    def test_implicit_only(self, writer):
        implicit = [{"content": "隐式伏笔", "type": "mystery", "importance": 3}]
        result = writer._merge_foreshadows([], implicit, 1)
        assert len(result) == 1
        assert result[0]["source"] == "设定提取"

    def test_dedup_across_sources(self, writer):
        explicit = ["重复伏笔"]
        implicit = [{"content": "重复伏笔", "type": "mystery", "importance": 2}]
        result = writer._merge_foreshadows(explicit, implicit, 1)
        assert len(result) == 1

    def test_dedup_whitespace(self, writer):
        """去重忽略空白差异"""
        explicit = ["相同 内容"]
        implicit = [{"content": "相同内容", "type": "mystery", "importance": 2}]
        result = writer._merge_foreshadows(explicit, implicit, 1)
        assert len(result) == 1

    def test_empty_both(self, writer):
        assert writer._merge_foreshadows([], [], 1) == []

    def test_implicit_empty_content_skipped(self, writer):
        implicit = [{"content": "", "type": "mystery", "importance": 2}]
        result = writer._merge_foreshadows([], implicit, 1)
        assert len(result) == 0


# ================================================================
# Layer 1: patch_chapter fail path
# ================================================================

class TestPatchChapterFail:
    def test_empty_patches_returns_original(self, writer):
        original = "原始正文内容。"
        result = writer.patch_chapter(1, "章", original, [], "摘要", ["人物"])
        assert result == original

    def test_no_keyword_match_returns_none(self, writer):
        original = "原始正文。\n\n第二段。"
        patches = [{"severity": "高", "description": "需要修改",
                     "location_keyword": "不存在的关键词"}]
        result = writer.patch_chapter(1, "章", original, patches, "摘要", ["人物"])
        assert result is None

    def test_empty_patches_list(self, writer):
        result = writer.patch_chapter(1, "章", "正文", None, "摘要", ["人物"])
        assert result == "正文"


# ================================================================
# Layer 1: save_chapter / load_chapter
# ================================================================

class TestSaveLoadChapter:
    def test_save_and_load(self, writer, mock_ctx):
        writer.save_chapter(1, "第一章", "叶青云修炼。", output_dir=str(mock_ctx.output_dir))
        saved = mock_ctx.chapters_dir / "chapter_001.md"
        assert saved.exists()
        content = saved.read_text(encoding="utf-8")
        assert "第一章" in content
        assert "叶青云修炼" in content

    def test_load_nonexistent(self, writer, mock_ctx):
        result = writer.load_chapter(99, output_dir=str(mock_ctx.output_dir))
        assert result == ""

    def test_load_existing(self, writer, mock_ctx):
        writer.save_chapter(3, "第三章", "正文", output_dir=str(mock_ctx.output_dir))
        result = writer.load_chapter(3, output_dir=str(mock_ctx.output_dir))
        assert "正文" in result

    def test_load_chapter_not_found(self, writer):
        result = writer.load_chapter(99)
        assert result == ""
