"""tests/test_foreshadow.py - 伏笔追踪器单元测试"""

import tempfile
from pathlib import Path
from novel_agent.core.foreshadow import ForeshadowTracker


def _make_tracker():
    tmp = tempfile.mkdtemp()
    return ForeshadowTracker(tmp), tmp


def test_plant_and_get_pending():
    ft, _ = _make_tracker()
    fid = ft.plant(1, "主角身世之谜", type="mystery")
    assert fid.startswith("FS_")
    pending = ft.get_pending()
    assert len(pending) == 1
    assert pending[0].id == fid
    assert pending[0].content == "主角身世之谜"


def test_resolve():
    ft, _ = _make_tracker()
    fid = ft.plant(1, "一个伏笔")
    ft.resolve(fid, 10, "谜底揭晓")
    resolved = [fs for fs in ft.foreshadows if fs.status == "resolved"]
    assert len(resolved) == 1
    assert resolved[0].chapter_resolved == 10
    assert resolved[0].resolution == "谜底揭晓"


def test_resolve_unknown_id():
    ft, _ = _make_tracker()
    import pytest
    with pytest.raises(ValueError):
        ft.resolve("FS_999", 5, "不存在")


def test_drop():
    ft, _ = _make_tracker()
    fid = ft.plant(1, "废弃伏笔")
    ft.drop(fid, "放弃原因")
    pending = ft.get_pending()
    assert len(pending) == 0
    dropped = [fs for fs in ft.foreshadows if fs.status == "dropped"]
    assert len(dropped) == 1


def test_get_pending_before_chapter():
    ft, _ = _make_tracker()
    ft.plant(1, "第1章伏笔")
    ft.plant(3, "第3章伏笔")
    pending = ft.get_pending(before_chapter=2)
    assert len(pending) == 1
    assert pending[0].content == "第1章伏笔"


def test_get_for_chapter():
    ft, _ = _make_tracker()
    ft.plant(1, "第1章伏笔A")
    ft.plant(1, "第1章伏笔B")
    ft.plant(2, "第2章伏笔")
    ch1 = ft.get_for_chapter(1)
    assert len(ch1) == 2
    ch2 = ft.get_for_chapter(2)
    assert len(ch2) == 1
    ch3 = ft.get_for_chapter(3)
    assert len(ch3) == 0


def test_get_resolved_in_chapter():
    ft, _ = _make_tracker()
    f1 = ft.plant(1, "伏笔A")
    f2 = ft.plant(1, "伏笔B")
    ft.resolve(f1, 5, "回收A")
    resolved = ft.get_resolved_in_chapter(5)
    assert len(resolved) == 1
    assert resolved[0].id == f1


def test_auto_resolve_explicit_mark():
    ft, _ = _make_tracker()
    fid = ft.plant(1, "显式回收伏笔")
    content = f"谜底揭晓。[FS_RESOLVE: {fid}]"
    count = ft.auto_resolve(content, 5)
    assert count == 1
    resolved = [fs for fs in ft.foreshadows if fs.status == "resolved"]
    assert len(resolved) == 1


def test_auto_resolve_fuzzy_match():
    ft, _ = _make_tracker()
    ft._counter = 5
    fid = ft.plant(1, "模糊匹配测试")  # FS_006
    content = "[FS_RESOLVE: FS_007]"  # 写错ID
    count = ft.auto_resolve(content, 5)
    assert count == 1


def test_generate_foreshadow_prompt_no_pending():
    ft, _ = _make_tracker()
    prompt = ft.generate_foreshadow_prompt(1)
    assert "无待回收伏笔" in prompt


def test_generate_foreshadow_prompt_with_pending():
    ft, _ = _make_tracker()
    ft.plant(1, "待回收测试", importance=3)
    prompt = ft.generate_foreshadow_prompt(5)
    assert "待回收伏笔" in prompt
    assert "待回收测试" in prompt


def test_summarize():
    ft, _ = _make_tracker()
    fid = ft.plant(1, "摘要测试")
    ft.resolve(fid, 5, "已回收")
    summary = ft.summarize()
    assert "伏笔总览" in summary
    assert "已兑现：1" in summary
    assert "待回收：0" in summary


def test_export_for_viz():
    ft, _ = _make_tracker()
    ft.plant(1, "可视化导出")
    data = ft.export_for_viz()
    assert len(data) == 1
    assert data[0]["content"] == "可视化导出"
    assert data[0]["status"] == "planted"


def test_plant_with_related():
    ft, _ = _make_tracker()
    fid = ft.plant(1, "涉及人物物品",
                   type="cross_volume",
                   related_characters=["主角", "配角"],
                   related_items=["玉佩"],
                   planted_how="对话中暗示",
                   importance=3)
    fs = [f for f in ft.foreshadows if f.id == fid][0]
    assert fs.type == "cross_volume"
    assert "主角" in fs.related_characters
    assert "玉佩" in fs.related_items
    assert "对话中暗示" in fs.planted_how
    assert fs.importance == 3
