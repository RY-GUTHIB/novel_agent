"""tests/test_continuity.py - 时间线+空间线守卫单元测试"""

import tempfile
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.models import LocationProfile, TimelineEvent


def _make_guard():
    tmp = tempfile.mkdtemp()
    return ContinuityGuard(tmp, enable_continuity_check=True), tmp


def test_add_event_and_get():
    cg, _ = _make_guard()
    cg.add_event(1, "第1天", "主角入门", ["主角"], "青云宗", 2)
    events = cg.get_events_for_chapter(1)
    assert len(events) == 1
    assert events[0].event == "主角入门"
    assert events[0].importance == 2


def test_get_events_for_character():
    cg, _ = _make_guard()
    cg.add_event(1, "第1天", "事件A", ["主角", "配角"], "地点", 1)
    cg.add_event(2, "第2天", "事件B", ["配角"], "地点", 1)
    chars = cg.get_events_for_character("主角")
    assert len(chars) == 1
    assert chars[0].event == "事件A"


def test_spacemap_add_location():
    cg, _ = _make_guard()
    loc = LocationProfile(name="青云宗", type="sect", description="山门")
    cg.add_location(loc)
    assert "青云宗" in cg.spacemap
    assert cg.spacemap["青云宗"].type == "sect"


def test_spacemap_connect_locations():
    cg, _ = _make_guard()
    cg.add_location(LocationProfile(name="青云宗", type="sect"))
    cg.add_location(LocationProfile(name="后山", type="wild"))
    cg.spacemap["青云宗"].connected_to.append("后山")
    cg.spacemap["后山"].connected_to.append("青云宗")
    cg.save_spacemap()
    assert "后山" in cg.spacemap["青云宗"].connected_to


def test_character_location_basic():
    cg, _ = _make_guard()
    cg.add_character_location(1, "主角", "青云宗")
    cg.add_character_location(2, "主角", "后山")
    loc = cg.get_character_location("主角", 2)
    assert loc == "后山"


def test_character_location_earlier_chapter():
    cg, _ = _make_guard()
    cg.add_character_location(1, "主角", "青云宗")
    cg.add_character_location(3, "主角", "后山")
    loc = cg.get_character_location("主角", 2)
    assert loc == "青云宗"


def test_character_location_nonexistent():
    cg, _ = _make_guard()
    loc = cg.get_character_location("不存在", 1)
    assert loc == ""


def test_get_location_characters():
    cg, _ = _make_guard()
    cg.add_character_location(1, "主角", "青云宗")
    cg.add_character_location(1, "配角", "青云宗")
    chars = cg.get_location_characters("青云宗", 2)
    assert "主角" in chars
    assert "配角" in chars


def test_continuity_check_same_location():
    cg, _ = _make_guard()
    cg.add_character_location(1, "主角", "青云宗")
    cg.add_location(LocationProfile(name="青云宗", type="sect"))
    warnings = cg.check_continuity(2, {"主角": "青云宗"})
    assert len(warnings) == 0


def test_continuity_check_different_location_no_connection():
    cg, _ = _make_guard()
    cg.add_character_location(1, "主角", "青云宗")
    cg.add_location(LocationProfile(name="青云宗", type="sect"))
    cg.add_location(LocationProfile(name="魔渊", type="dungeon"))
    warnings = cg.check_continuity(2, {"主角": "魔渊"})
    assert len(warnings) >= 1
    assert "空间矛盾" in warnings[0]


def test_continuity_check_connected_locations():
    cg, _ = _make_guard()
    cg.add_character_location(1, "主角", "青云宗")
    cg.add_location(LocationProfile(name="青云宗", type="sect",
                                     connected_to=["后山"]))
    cg.add_location(LocationProfile(name="后山", type="wild",
                                     connected_to=["青云宗"]))
    warnings = cg.check_continuity(2, {"主角": "后山"})
    assert len(warnings) == 0


def test_scan_final_positions():
    cg, _ = _make_guard()
    cg.add_location(LocationProfile(name="山谷", type="wild"))
    text = "赵刚走出了山谷。"
    result = cg.scan_final_positions(text, ["山谷"])
    assert "赵刚" in result
    assert result["赵刚"]["direction"] == "out"
    assert result["赵刚"]["location"] == "山谷"


def test_generate_continuity_prompt():
    cg, _ = _make_guard()
    cg.add_event(1, "第1天", "主角入门", ["主角"], "青云宗")
    cg.add_event(2, "第2天", "主角突破", ["主角"], "后山")
    prompt = cg.generate_continuity_prompt(3)
    assert "前文连续性摘要" in prompt
    assert "主角入门" in prompt
    assert "主角突破" in prompt


def test_export_timeline_for_viz():
    cg, _ = _make_guard()
    cg.add_event(1, "第1天", "测试", ["主角"], "地点")
    data = cg.export_timeline_for_viz()
    assert len(data) == 1
    assert data[0]["chapter"] == 1
    assert data[0]["event"] == "测试"


def test_export_spacemap_for_viz():
    cg, _ = _make_guard()
    cg.add_location(LocationProfile(name="A地", type="city",
                                     connected_to=["B地"]))
    cg.add_location(LocationProfile(name="B地", type="sect",
                                     connected_to=["A地"]))
    data = cg.export_spacemap_for_viz()
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 2


def test_update_absolute_day():
    cg, _ = _make_guard()
    cg.add_event(1, "一日后", "", [""])
    assert cg.absolute_day >= 1


def test_get_spacemap_prompt():
    cg, _ = _make_guard()
    cg.add_location(LocationProfile(name="青云宗", type="sect",
                                     description="山门所在",
                                     connected_to=["后山"]))
    prompt = cg.get_spacemap_prompt()
    assert "青云宗" in prompt
    assert "空间地图" in prompt
