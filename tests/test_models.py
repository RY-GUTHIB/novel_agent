"""tests/test_models.py - 数据模型单元测试"""

from dataclasses import fields
from novel_agent.core.models import (
    SettingsSchema, validate_settings_json,
    generate_settings_json_example, Foreshadow, CharacterProfile,
)
import json


def test_settings_schema_fields():
    """SettingsSchema.FIELDS 必须与 dataclass 字段一一对应"""
    dc_fields = set(f.name for f in fields(SettingsSchema) if f.name != "FIELDS")
    listed = set(SettingsSchema.FIELDS)
    assert dc_fields == listed, (
        f"缺失字段: {dc_fields - listed}, 多余字段: {listed - dc_fields}"
    )


def test_validate_settings_json_missing():
    missing = validate_settings_json({})
    assert len(missing) == len(SettingsSchema.FIELDS)


def test_validate_settings_json_full():
    d = {f: [] for f in SettingsSchema.FIELDS}
    missing = validate_settings_json(d)
    assert missing == []


def test_generate_settings_json_example_valid():
    text = generate_settings_json_example()
    parsed = json.loads(text)
    assert isinstance(parsed, dict)


def test_foreshadow_dataclass():
    fs = Foreshadow(id="FS_001", chapter_planted=1)
    assert fs.status == "planted"
    assert fs.chapter_resolved is None


def test_character_profile_defaults():
    c = CharacterProfile(name="测试")
    assert c.status == "alive"
    assert c.first_appeared == 1
