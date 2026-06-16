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
