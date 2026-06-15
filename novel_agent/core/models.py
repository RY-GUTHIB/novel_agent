"""
models.py - 所有数据模型（dataclass）

从 memory.py / continuity.py / foreshadow.py 中提取的纯数据结构，
不依赖任何业务逻辑，可独立 import。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ============ 人物相关 ============

@dataclass
class RelationshipRecord:
    """人物关系详细记录"""
    type: str
    stance: str = "neutral"           # friendly/neutral/hostile/adversarial
    met_chapter: int = 0
    met_context: str = ""
    key_events: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class CharacterProfile:
    """人物档案"""
    name: str
    gender: str = ""
    age: str = ""
    appearance: str = ""
    personality: str = ""
    background: str = ""
    goals: str = ""
    speaking_style: str = ""
    abilities: List[str] = field(default_factory=list)
    relationships: Dict[str, str] = field(default_factory=dict)
    relationships_detail: Dict[str, dict] = field(default_factory=dict)
    cultivation: str = ""
    status: str = "alive"
    first_appeared: int = 1
    arc: str = ""
    notes: str = ""


@dataclass
class CharacterKnowledge:
    """角色认知记录"""
    character: str
    chapter_learned: int
    knowledge: str
    source: str
    detail: str = ""


# ============ 地点相关 ============

@dataclass
class LocationProfile:
    """地点档案（合并原 SpaceNode，统一地点数据）"""
    name: str
    description: str = ""
    type: str = "city"
    connected_to: List[str] = field(default_factory=list)
    travel_time: Dict[str, str] = field(default_factory=dict)
    first_appeared: int = 1
    notable_characters: List[str] = field(default_factory=list)
    notes: str = ""


# ============ 世界观相关 ============

@dataclass
class WorldSetting:
    """世界观设定条目"""
    key: str
    value: str
    chapter_introduced: int = 1


@dataclass
class PlotRule:
    """剧情规则（IF-THEN）"""
    condition: str
    consequence: str
    rule_text: str
    chapter_introduced: int = 1
    source_character: str = ""
    overridden: bool = False
    override_reason: str = ""


@dataclass
class SectFaction:
    """势力/宗派档案"""
    name: str
    type: str = ""
    description: str = ""
    strength: str = ""
    hierarchy: List[str] = field(default_factory=list)
    key_members: List[str] = field(default_factory=list)
    allies: List[str] = field(default_factory=list)
    enemies: List[str] = field(default_factory=list)
    location: str = ""
    rules: List[str] = field(default_factory=list)
    first_appeared: int = 1
    notes: str = ""


# ============ 事件相关 ============

@dataclass
class SceneEvent:
    """场景事件记录"""
    chapter: int
    location: str
    scene: str = ""
    event: str = ""
    characters: List[str] = field(default_factory=list)
    importance: int = 1


@dataclass
class TimelineEvent:
    """时间线事件"""
    chapter: int
    time_tag: str
    event: str
    characters: List[str]
    location: str = ""
    importance: int = 1


@dataclass
class CharacterLocation:
    """某章节某人物的位置记录"""
    chapter: int
    character: str
    location: str
    scene: str = ""
    note: str = ""


# ============ 伏笔相关 ============

@dataclass
class Foreshadow:
    """伏笔记录"""
    id: str
    chapter_planted: int
    type: str = "mystery"
    content: str = ""
    related_characters: List[str] = field(default_factory=list)
    related_items: List[str] = field(default_factory=list)
    planted_how: str = ""
    chapter_resolved: Optional[int] = None
    resolution: str = ""
    importance: int = 1
    status: str = "planted"
