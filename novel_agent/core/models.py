"""
models.py - 所有数据模型（dataclass）

从 memory.py / continuity.py / foreshadow.py 中提取的纯数据结构，
不依赖任何业务逻辑，可独立 import。
"""

import json
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
    current_location: str = ""
    core_values: str = ""       # 核心价值观（如"家族荣耀高于一切"）
    core_desire: str = ""       # 核心欲望/目标（比goals更精确的内驱力）
    core_fear: str = ""         # 核心恐惧（最怕失去/面对什么）
    flaw: str = ""              # 核心缺陷（性格弱点，成长弧光的起点）
    alignment: str = ""         # 阵营倾向（如"守序善良""混乱中立"）
    status: str = "alive"
    first_appeared: int = 1
    arc: str = ""
    notes: str = ""
    learned_skills: List[dict] = field(default_factory=list)  # 技能记录: [{skill, source, level, cost, note}]
    faction: str = ""  # 所属势力
    faction_status: str = ""  # 势力身份（如"白银骑士""流放者"）


@dataclass
class CharacterKnowledge:
    """角色认知记录"""
    character: str
    chapter_learned: int
    knowledge: str
    source: str
    detail: str = ""


# ============ 物品相关 ============

@dataclass
class ItemProfile:
    """物品状态追踪（方案1+2+5：显式状态管理，防止重复赠与/转移）"""
    name: str                         # 物品名（如"独狼令"）
    type: str = ""                    # 类型：信物/武器/法宝/丹药/材料/秘笈/其他
    description: str = ""             # 描述
    first_appeared: int = 1           # 首次出场章节
    first_giver: str = ""             # 首次赋予者（方案2：唯一指定）
    current_holder: str = ""          # 当前持有者
    subsequent_transfers: List[dict] = field(default_factory=list)  # 后续转移 [{from, to, chapter, reason}]
    prohibited_actions: List[str] = field(default_factory=list)     # 禁止操作 ["give_again_by_other", "duplicate"]
    status: str = "active"            # active/lost/destroyed/returned
    notes: str = ""


# ============ 地点相关 ============

@dataclass
class LocationProfile:
    """地点档案（合并原 SpaceNode，统一地点数据）"""
    name: str
    description: str = ""
    type: str = "city"
    connected_to: List[str] = field(default_factory=list)
    travel_time: Dict[str, str] = field(default_factory=dict)
    relative_position: Dict[str, str] = field(default_factory=dict)
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
    season: str = ""          # 季节（春/夏/秋/冬），用于时间一致性校验
    time_elapsed: str = ""    # 与上一章的时间间隔（如"一日""三日""半月"），用于时间一致性校验


@dataclass
class CharacterLocation:
    """某章节某人物的位置记录"""
    chapter: int
    character: str
    location: str
    scene: str = ""
    note: str = ""

@dataclass
class TaskProfile:
    """任务清单（长线任务/目标追踪，跨章节记忆）"""
    id: str
    name: str                         # 任务名，如"救叶无痕"
    description: str = ""             # 任务描述，如"需要集齐天外陨铁、九转还魂丹"
    status: str = "active"            # active / completed / abandoned
    chapter_created: int = 1
    chapter_completed: Optional[int] = None
    progress: str = ""                # 当前进度，如"已找到天外陨铁，还差九转还魂丹"
    related_items: List[str] = field(default_factory=list)
    related_characters: List[str] = field(default_factory=list)


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


# ============ 风格相关 ============

@dataclass
class StyleProfile:
    """风格锚点（贯穿全文的风格约束，防止前后文风不一致）"""
    chapter_introduced: int = 1      # 首次明确风格的章节
    narrative_voice: str = ""        # 叙述视角（第一人称/第三人称有限/第三人称全知）
    sentence_rhythm: str = ""      # 句节奏偏好（如"短句为主，爆发段用3-5字短句"）
    paragraph_pattern: str = ""    # 段落结构（如"每段2-4句，不超8行"）
    rhetorical_devices: List[str] = field(default_factory=list)  # 常用修辞手法（如["排比","反问","对仗"]）
    tone_words: List[str] = field(default_factory=list)       # 语气词偏好（如["——","…","！"]）
    forbidden_words: List[str] = field(default_factory=list)    # 禁用词（如["嗯","哦","啊哈"]）
    dialect_markers: str = ""       # 方言特征（如无/轻微/浓厚）
    example_snippets: List[str] = field(default_factory=list)  # 风格范例片段（2-3段原文）
    notes: str = ""


# ============ SETTINGS_JSON Schema（LLM 输出契约 + 消费方校验）============

@dataclass
class CharacterUpdate:
    """SETTINGS_JSON 中的单个人物条目"""
    name: str = ""
    is_new: bool = False
    updates: dict = field(default_factory=lambda: {
        "gender": "", "age": "", "appearance": "", "personality": "",
        "background": "", "goals": "", "speaking_style": "", "abilities": [],
        "cultivation": "", "current_location": "", "status": "alive",
        "core_values": "", "core_desire": "", "core_fear": "", "flaw": "",
        "alignment": "", "notes": "",
        "relationships": {},
        "relationship_contexts": {},
    })


@dataclass
class SettingsSchema:
    """SETTINGS_JSON 的完整 schema，定义 LLM 输出结构和 _apply_* 消费契约"""
    characters: list = field(default_factory=list)
    world_settings: list = field(default_factory=list)
    sect_factions: list = field(default_factory=list)
    locations: list = field(default_factory=list)
    scene_events: list = field(default_factory=list)
    spatial_movements: list = field(default_factory=list)
    spacemap_updates: list = field(default_factory=list)
    plot_rules: list = field(default_factory=list)
    character_knowledge: list = field(default_factory=list)
    items: list = field(default_factory=list)
    tasks: list = field(default_factory=list)
    timeline_events: list = field(default_factory=list)
    style: dict = field(default_factory=dict)

    # 顶层字段列表，用于校验和生成
    FIELDS = [
        "characters", "world_settings", "sect_factions", "locations",
        "scene_events", "spatial_movements", "spacemap_updates",
        "plot_rules", "character_knowledge", "items", "tasks",
        "timeline_events", "style",
    ]


def generate_settings_json_example() -> str:
    """生成 SETTINGS_JSON 示例字符串（用于注入 LLM prompt）。
    新增字段时只需在 SettingsSchema.FIELDS 中添加 key，
    并在 _apply_* 中添加对应消费方法即可。两者不一致会在校验时发现。
    """
    example = {
        "characters": [{
            "name": "名", "is_new": True,
            "updates": {
                "gender": "性", "age": "龄", "appearance": "貌",
                "personality": "性", "background": "背", "goals": "标",
                "speaking_style": "语", "abilities": [],
                "cultivation": "", "current_location": "", "status": "alive",
                "core_values": "", "core_desire": "", "core_fear": "",
                "flaw": "", "alignment": "", "notes": "",
                "learned_skills": [], "faction": "", "faction_status": "",
                "relationships": {},
                "relationship_contexts": {
                    "他人": {"type": "关系类型", "stance": "friendly/neutral/hostile/adversarial",
                            "met_chapter": 0, "met_context": "认识场景", "key_events": []},
                },
            },
        }],
        "world_settings": [{"key": "设定名", "value": "设定描述"}],
        "sect_factions": [{
            "name": "势力名", "is_new": True,
            "updates": {
                "type": "宗门", "description": "描述", "strength": "实力",
                "hierarchy": [], "key_members": [], "allies": [], "enemies": [],
                "location": "", "rules": [], "notes": "",
            },
        }],
        "locations": [{
            "name": "地名", "is_new": True,
            "updates": {
                "description": "描述", "type": "city",
                "connected_to": [], "notable_characters": [],
            },
        }],
        "scene_events": [{
            "location": "地名", "scene": "开场/中段/结尾", "event": "事件",
            "characters": [], "importance": 3,
        }],
        "spatial_movements": [{
            "character": "人物", "from_location": "A", "to_location": "B",
            "scene": "场景", "travel_method": "方式", "travel_time": "耗时", "note": "",
        }],
        "spacemap_updates": [{
            "from_location": "A", "to_location": "B",
            "travel_time": "时间", "is_bidirectional": True,
            "direction": "from_location 指向 to_location 的方向+距离（如 from=青云宗,to=药王谷 则填'东三百里'），或反之",
        }],
        "plot_rules": [{
            "condition": "条件", "consequence": "结果",
            "rule_text": "原文", "source_character": "角色",
        }],
        "character_knowledge": [{
            "character": "角色", "knowledge": "知道了什么",
            "source": "怎么知道", "detail": "",
        }],
        "items": [{
            "name": "物品名", "is_new": True,
            "updates": {
                "type": "类型", "description": "描述",
                "first_giver": "赋予者", "current_holder": "持有者", "status": "active",
                "subsequent_transfers": [], "prohibited_actions": [], "notes": "",
            },
        }],
        "tasks": [{
            "id": "任务ID", "name": "任务名", "description": "描述",
            "status": "active/completed", "progress": "当前进度",
            "related_characters": [], "related_items": [],
        }],
        "timeline_events": [{
            "time_tag": "三日后/当天/五日后", "event": "事件描述",
            "characters": ["人物"], "location": "地点",
            "importance": 2, "season": "秋",
        }],
        "style": {},
    }
    return json.dumps(example, ensure_ascii=False, indent=None)


def validate_settings_json(parsed: dict) -> List[str]:
    """校验 SETTINGS_JSON 的字段完整性，返回缺失字段列表。
    在 _apply_all_settings 前调用，确保 LLM 输出与 schema 一致。"""
    missing = []
    for field_name in SettingsSchema.FIELDS:
        if field_name not in parsed:
            missing.append(field_name)
    return missing
