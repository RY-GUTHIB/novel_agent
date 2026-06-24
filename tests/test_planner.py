"""tests/test_planner.py - PlannerAgent Layer1 纯函数测试（零 mock LLM）"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import config
from novel_agent.agents.planner import PlannerAgent


# ========== Fixtures ==========

@pytest.fixture
def mock_memory():
    return MagicMock()


@pytest.fixture
def mock_continuity():
    cg = MagicMock()
    cg.timeline = []
    cg.spacemap = {}
    cg.character_locations = []
    cg.absolute_day = 0
    cg._time_updated_chapters = set()
    return cg


@pytest.fixture
def mock_foreshadow():
    fs = MagicMock()
    fs.foreshadows = []
    return fs


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.data_dir = Path(tempfile.mkdtemp())
    return ctx


@pytest.fixture
def planner(mock_memory, mock_continuity, mock_foreshadow, mock_ctx):
    return PlannerAgent(mock_memory, mock_continuity, mock_foreshadow, mock_ctx)


# ================================================================
# Layer 1: _detect_truncation
# ================================================================

class TestDetectTruncation:
    def test_empty_string_truncated(self, planner):
        assert planner._detect_truncation("") is True

    def test_properly_closed_brace(self, planner):
        assert planner._detect_truncation('{"key": "value"}') is False

    def test_properly_closed_bracket(self, planner):
        assert planner._detect_truncation('["a", "b"]') is False

    def test_unclosed_json(self, planner):
        assert planner._detect_truncation('{"key": "value"') is True

    def test_closed_in_last_five_lines(self, planner):
        text = '{"key": "value",\n"key2": "val2"\n}'
        assert planner._detect_truncation(text) is False

    def test_trailing_garbage_after_close(self, planner):
        # 最后一行不是闭合括号，视为截断
        text = '{"key": "value"}\nsome trailing text'
        assert planner._detect_truncation(text) is True

    def test_only_open_brace(self, planner):
        assert planner._detect_truncation('{') is True

    def test_newlines_with_close(self, planner):
        assert planner._detect_truncation('\n\n\n}\n') is False


# ================================================================
# Layer 1: _extract_json
# ================================================================

class TestExtractJson:
    def test_valid_dict(self, planner):
        text = '{"name": "test", "value": 42}'
        result = planner._extract_json(text)
        assert result == {"name": "test", "value": 42}

    def test_json_code_block(self, planner):
        text = "一些文字\n```json\n{\"key\": \"val\"}\n```\n结尾"
        result = planner._extract_json(text)
        assert result == {"key": "val"}

    def test_invalid_json_raises(self, planner):
        with pytest.raises(ValueError, match="JSON 解析失败"):
            planner._extract_json("不是 JSON 内容")

    def test_array_not_dict_raises(self, planner):
        with pytest.raises(ValueError, match="JSON 解析失败"):
            planner._extract_json("[1, 2, 3]")

    def test_empty_string_raises(self, planner):
        with pytest.raises(ValueError, match="JSON 解析失败"):
            planner._extract_json("")

    def test_nested_json(self, planner):
        text = '{"volumes": [{"volume": 1, "chapters": [{"chapter": 1}]}]}'
        result = planner._extract_json(text)
        assert result["volumes"][0]["chapters"][0]["chapter"] == 1


# ================================================================
# Layer 1: _validate_outline_structure
# ================================================================

VALID_OUTLINE = {
    "meta": {"title": "test"},
    "volumes": [{"volume": 1, "arc": {"setback_chapter": 5}, "chapters": [{"chapter": 1}]}],
    "characters": [],
    "locations": [],
    "factions": [],
    "key_items": [],
    "foreshadows": [],
}


class TestValidateOutlineStructure:
    def test_valid_outline_passes(self, planner):
        planner._validate_outline_structure(VALID_OUTLINE)

    def test_meta_not_dict(self, planner):
        with pytest.raises(ValueError, match="类型错误"):
            planner._validate_outline_structure({**VALID_OUTLINE, "meta": "string"})

    def test_volumes_not_list(self, planner):
        with pytest.raises(ValueError, match="类型错误"):
            planner._validate_outline_structure({**VALID_OUTLINE, "volumes": {}})

    def test_volume_element_not_dict(self, planner):
        with pytest.raises(ValueError, match="不是对象"):
            planner._validate_outline_structure({**VALID_OUTLINE, "volumes": ["string"]})

    def test_volume_arc_not_dict(self, planner):
        outline = {**VALID_OUTLINE}
        outline["volumes"] = [{"volume": 1, "arc": "not_dict", "chapters": []}]
        with pytest.raises(ValueError, match="arc 应为对象"):
            planner._validate_outline_structure(outline)

    def test_chapter_not_dict(self, planner):
        outline = {**VALID_OUTLINE}
        outline["volumes"] = [{"volume": 1, "chapters": ["not_dict"]}]
        with pytest.raises(ValueError, match="非对象"):
            planner._validate_outline_structure(outline)

    def test_partial_outline_missing_optional(self, planner):
        partial = {"meta": {"title": "t"}, "volumes": []}
        planner._validate_outline_structure(partial)


# ================================================================
# Layer 1: _load_config_main_character
# ================================================================

class TestLoadConfigMainCharacter:
    def test_config_exists_with_char(self, planner):
        with patch.object(config, "get_project_name", return_value="test_proj"), \
             patch("novel_agent.agents.planner.load_project_config") as mock_load:
            mock_load.return_value = {"main_character": "叶青云"}
            result = planner._load_config_main_character()
            assert result == "叶青云"

    def test_config_no_main_char(self, planner):
        with patch.object(config, "get_project_name", return_value="test_proj"), \
             patch("novel_agent.agents.planner.load_project_config") as mock_load:
            mock_load.return_value = {}
            result = planner._load_config_main_character()
            assert result == ""

    def test_config_not_found(self, planner):
        with patch.object(config, "get_project_name", return_value="nonexistent"), \
             patch("novel_agent.agents.planner.load_project_config", side_effect=FileNotFoundError):
            result = planner._load_config_main_character()
            assert result == ""


# ================================================================
# Layer 1: save_outline_json
# ================================================================

class TestSaveOutlineJson:
    def test_save_default_path(self, planner):
        out_dir = Path(tempfile.mkdtemp())
        planner.memory.data_dir = out_dir
        data = {"test": True}
        planner.save_outline_json(data)
        saved = out_dir / "outline.json"
        assert saved.exists()
        loaded = json.loads(saved.read_text(encoding="utf-8"))
        assert loaded == data

    def test_save_custom_path(self, planner):
        out_dir = Path(tempfile.mkdtemp())
        custom = out_dir / "custom.json"
        data = {"custom": "path"}
        planner.save_outline_json(data, filepath=str(custom))
        assert custom.exists()
        loaded = json.loads(custom.read_text(encoding="utf-8"))
        assert loaded == data


# ================================================================
# Layer 1: _check_chapter_count
# ================================================================

class TestCheckChapterCount:
    def test_valid_chapter_count(self, planner):
        volumes = [{"volume": i, "chapters": [{"chapter": j} for j in range(1, 17)]}
                   for i in range(1, 6)]
        assert planner._check_chapter_count(volumes) == []

    def test_volume_too_few_chapters(self, planner):
        volumes = [{"volume": 1, "chapters": [{"chapter": j} for j in range(1, 10)]}]
        issues = planner._check_chapter_count(volumes)
        assert any("章节数=9" in i for i in issues)

    def test_volume_too_many_chapters(self, planner):
        volumes = [{"volume": 1, "chapters": [{"chapter": j} for j in range(1, 41)]}]
        issues = planner._check_chapter_count(volumes)
        assert any("章节数=40" in i for i in issues)

    def test_total_less_than_50(self, planner):
        volumes = [{"volume": i, "chapters": [{"chapter": j} for j in range(1, 16)]}
                   for i in range(1, 3)]
        issues = planner._check_chapter_count(volumes)
        assert any("70" in i for i in issues)


# ================================================================
# Layer 1: _check_volume_arcs
# ================================================================

class TestCheckVolumeArcs:
    def test_complete_arc_no_issues(self, planner):
        volumes = [{"volume": 1, "arc": {
            "setback_chapter": 5, "insight_chapter": 8,
            "breakthrough_chapter": 12, "new_challenge_chapter": 15,
        }}]
        assert planner._check_volume_arcs(volumes) == []

    def test_missing_setback(self, planner):
        volumes = [{"volume": 1, "arc": {"insight_chapter": 8}}]
        assert planner._check_volume_arcs(volumes) != []

    def test_missing_insight(self, planner):
        volumes = [{"volume": 1, "arc": {"setback_chapter": 5}}]
        assert planner._check_volume_arcs(volumes) != []

    def test_no_comeback_after_setback(self, planner):
        volumes = [{"volume": 1, "arc": {"setback_chapter": 10}}]
        issues = planner._check_volume_arcs(volumes)
        assert any("无反杀" in i for i in issues)


# ================================================================
# Layer 1: _check_power_system
# ================================================================

class TestCheckPowerSystem:
    def test_under_10_levels(self, planner):
        outline = {"power_system": [{"level": i, "name": f"L{i}"} for i in range(1, 8)]}
        assert planner._check_power_system(outline) == []

    def test_over_10_levels(self, planner):
        outline = {"power_system": [{"level": i, "name": f"L{i}"} for i in range(1, 13)]}
        issues = planner._check_power_system(outline)
        assert any(i for i in issues if "12" in i)

    def test_no_power_system(self, planner):
        assert planner._check_power_system({}) == []


# ================================================================
# Layer 1: _check_factions
# ================================================================

class TestCheckFactions:
    def test_no_conflict(self, planner):
        outline = {"factions": [
            {"name": "青云宗", "allies": ["天剑门"], "enemies": ["魔教"]},
        ]}
        assert planner._check_factions(outline) == []

    def test_ally_enemy_conflict(self, planner):
        outline = {"factions": [
            {"name": "青云宗", "allies": ["天剑门"], "enemies": ["天剑门"]},
        ]}
        issues = planner._check_factions(outline)
        assert any("冲突" in i for i in issues)

    def test_empty_factions(self, planner):
        assert planner._check_factions({"factions": []}) == []


# ================================================================
# Layer 1: _check_characters
# ================================================================

class TestCheckCharacters:
    def test_all_required_fields_present(self, planner):
        outline = {"characters": [{
            "name": "叶青云", "exit_point": "第50章", "cultivation": "筑基",
            "gender": "男", "age": "18", "appearance": "英俊", "personality": "沉稳",
            "background": "农家", "goals": "变强", "speaking_style": "简洁",
            "abilities": ["剑法"],
        }]}
        assert planner._check_characters(outline) == []

    def test_missing_required_field(self, planner):
        outline = {"characters": [{"name": "叶青云", "abilities": ["剑法"]}]}
        issues = planner._check_characters(outline)
        assert any("exit_point" in i for i in issues)

    def test_missing_abilities(self, planner):
        outline = {"characters": [{
            "name": "叶青云", "exit_point": "第50章", "cultivation": "筑基",
            "gender": "男", "age": "18", "appearance": "英俊", "personality": "沉稳",
            "background": "农家", "goals": "变强", "speaking_style": "简洁",
        }]}
        issues = planner._check_characters(outline)
        assert any("abilities" in i for i in issues)


# ================================================================
# Layer 1: _check_items
# ================================================================

class TestCheckItems:
    def test_no_duplicates(self, planner):
        outline = {"key_items": [
            {"item_name": "玉佩", "giver": "师父"},
            {"item_name": "宝剑", "giver": "宗主"},
        ]}
        assert planner._check_items(outline) == []

    def test_duplicate_giver(self, planner):
        outline = {"key_items": [
            {"item_name": "玉佩", "giver": "师父"},
            {"item_name": "玉佩", "giver": "师叔"},
        ]}
        assert planner._check_items(outline) != []

    def test_empty_items(self, planner):
        assert planner._check_items({"key_items": []}) == []


# ================================================================
# Layer 1: _check_foreshadows
# ================================================================

class TestCheckForeshadows:
    def test_all_volumes_have_cross(self, planner):
        volumes = [
            {"volume": 1, "chapters": [{"chapter": 1}, {"chapter": 2}]},
            {"volume": 2, "chapters": [{"chapter": 3}, {"chapter": 4}]},
        ]
        outline = {"foreshadows": [
            {"type": "cross_volume", "plant_chapter": 1},
        ]}
        assert planner._check_foreshadows(outline, volumes) == []

    def test_volume_missing_cross(self, planner):
        volumes = [
            {"volume": 1, "chapters": [{"chapter": 1}]},
            {"volume": 2, "chapters": [{"chapter": 10}]},
        ]
        outline = {"foreshadows": [
            {"type": "normal", "plant_chapter": 1},
        ]}
        issues = planner._check_foreshadows(outline, volumes)
        assert any("缺少跨卷伏笔" in i for i in issues)

    def test_foreshadow_exceeds_two_volumes(self, planner):
        volumes = [
            {"volume": 1, "chapters": [{"chapter": 1}]},
            {"volume": 2, "chapters": [{"chapter": 10}]},
            {"volume": 3, "chapters": [{"chapter": 20}]},
        ]
        outline = {"foreshadows": [
            {"plant_chapter": 1, "harvest_chapter": 30, "id": "FS_001"},
        ]}
        issues = planner._check_foreshadows(outline, volumes)
        assert any("超过2卷" in i for i in issues)


# ================================================================
# Layer 1: _check_ending
# ================================================================

class TestCheckEnding:
    def test_normal_ending(self, planner):
        outline = {}
        volumes = [{"volume": 1, "chapters": [{"chapter": 10, "summary": "主角成功登顶"}]}]
        assert planner._check_ending(outline, volumes) == []

    def test_self_destruct_ending(self, planner):
        outline = {}
        volumes = [{"volume": 1, "chapters": [{"chapter": 10, "summary": "主角自爆与敌人同归于尽"}]}]
        issues = planner._check_ending(outline, volumes)
        assert any("自爆" in i for i in issues)

    def test_empty_volumes(self, planner):
        assert planner._check_ending({}, []) == []


# ================================================================
# Layer 1: _check_defeat_recovery
# ================================================================

class TestCheckDefeatRecovery:
    def test_no_defeat_terms(self, planner):
        volumes = [{"volume": 1, "chapters": [
            {"chapter": 1, "summary": "正常剧情"},
            {"chapter": 2, "summary": "继续发展"},
        ]}]
        assert PlannerAgent._check_defeat_recovery({}, volumes) == []

    def test_defeat_then_recovery(self, planner):
        volumes = [{"volume": 1, "chapters": [
            {"chapter": 1, "summary": "经脉尽断"},
            {"chapter": 2, "summary": "获得传承"},
            {"chapter": 5, "summary": "重塑经脉突破至筑基"},
        ]}]
        assert PlannerAgent._check_defeat_recovery({}, volumes) == []

    def test_defeat_no_chance_in_3_chapters(self, planner):
        volumes = [{"volume": 1, "chapters": [
            {"chapter": 1, "summary": "修为被废沦为废人"},
            {"chapter": 2, "summary": "平淡章节"},
            {"chapter": 3, "summary": "日常对话"},
            {"chapter": 4, "summary": "继续日常"},
        ]}]
        issues = PlannerAgent._check_defeat_recovery({}, volumes)
        assert any("3章内未遇到机缘" in i for i in issues)

    def test_defeat_chance_no_recovery_in_7(self, planner):
        volumes = [{"volume": 1, "chapters": [
            {"chapter": 1, "summary": "丹田破碎功力全失"},
            {"chapter": 2, "summary": "偶遇机缘发现秘境"},
            {"chapter": 3, "summary": "探索"},
            {"chapter": 4, "summary": "日常"},
            {"chapter": 5, "summary": "继续日常"},
            {"chapter": 6, "summary": "修炼"},
            {"chapter": 7, "summary": "离开"},
            {"chapter": 8, "summary": "平淡"},
        ]}]
        issues = PlannerAgent._check_defeat_recovery({}, volumes)
        assert any("破而后立" in i for i in issues)


# ================================================================
# Layer 1: _check_side_quests
# ================================================================

class TestCheckSideQuests:
    def test_no_side_quests(self, planner):
        assert planner._check_side_quests({}) == []

    def test_ratio_too_low(self, planner):
        outline = {
            "meta": {"total_chapters": 100},
            "side_quests": [
                {"id": "SQ_1", "start_chapter": 1, "end_chapter": 5, "summary": "",
                 "connects_to_main": "为后续剧情铺垫", "output": {"items": ["宝物"]}},
            ],
        }
        issues = planner._check_side_quests(outline)
        assert any("不足10%" in i for i in issues)

    def test_ratio_too_high(self, planner):
        outline = {
            "meta": {"total_chapters": 20},
            "side_quests": [
                {"id": "SQ_1", "start_chapter": 1, "end_chapter": 10, "summary": "",
                 "connects_to_main": "为后续剧情铺垫", "output": {"items": ["宝物"]}},
            ],
        }
        issues = planner._check_side_quests(outline)
        assert any("超过35%" in i for i in issues)

    def test_missing_connects_to_main(self, planner):
        outline = {
            "meta": {"total_chapters": 50},
            "side_quests": [
                {"id": "SQ_1", "start_chapter": 1, "end_chapter": 10, "summary": "",
                 "output": {"items": ["宝物"]}},
            ],
        }
        issues = planner._check_side_quests(outline)
        assert any("connects_to_main" in i for i in issues)

    def test_no_output(self, planner):
        outline = {
            "meta": {"total_chapters": 50},
            "side_quests": [
                {"id": "SQ_1", "start_chapter": 1, "end_chapter": 10, "summary": "测试",
                 "connects_to_main": "为后续剧情铺垫", "output": {}},
            ],
        }
        issues = planner._check_side_quests(outline)
        assert any("无任何产出物" in i for i in issues)

    def test_large_side_quests_too_close(self, planner):
        outline = {
            "meta": {"total_chapters": 50},
            "side_quests": [
                {"id": "SQ_1", "start_chapter": 1, "end_chapter": 12, "summary": "",
                 "connects_to_main": "为后续剧情铺垫", "output": {"items": ["宝物"]}},
                {"id": "SQ_2", "start_chapter": 14, "end_chapter": 25, "summary": "",
                 "connects_to_main": "为后续剧情铺垫", "output": {"rewards": ["经验"]}},
            ],
        }
        issues = planner._check_side_quests(outline)
        assert any("仅隔" in i for i in issues)
