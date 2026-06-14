"""
memory.py - 世界观/人物档案管理

负责维护：
1. 人物档案（姓名、性别、性格、经历、当前状态、语言风格）
2. 世界观设定（修炼体系、魔法规则、社会结构等）
3. 地点档案（描述、首次出现章节、拓扑关系）

所有数据持久化到 data/ 目录下的 JSON 文件。
"""

import json
import config
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field


# ============ 数据结构定义 ============

@dataclass
class RelationshipRecord:
    """人物关系详细记录"""
    type: str                         # 关系类型（对手/师徒/盟友/宿敌/亲友/上下级/陌生人…）
    stance: str = "neutral"           # 立场：friendly(友好)/neutral(中立)/hostile(敌对)/adversarial(对立)
    met_chapter: int = 0              # 认识的章节
    met_context: str = ""             # 在什么情况下认识的
    key_events: List[str] = field(default_factory=list)  # 关键事件列表（如"第3章挑衅并败北"）
    notes: str = ""                   # 补充说明


@dataclass
class CharacterProfile:
    """人物档案"""
    name: str                          # 姓名
    gender: str = ""                   # 性别
    age: str = ""                     # 年龄/修炼年龄
    appearance: str = ""              # 外貌描述
    personality: str = ""             # 性格
    background: str = ""              # 出身背景
    goals: str = ""                   # 目标/动机
    speaking_style: str = ""           # 语言风格（口头禅、说话方式）
    abilities: List[str] = field(default_factory=list)  # 能力/功法
    relationships: Dict[str, str] = field(default_factory=dict)  # {人物名: 关系} (兼容旧格式)
    relationships_detail: Dict[str, dict] = field(default_factory=dict)  # {人物名: RelationshipRecord详情}
    cultivation: str = ""             # 修为境界（如：炼气圆满、筑基初期、金丹中期）
    status: str = "alive"             # 状态：alive/dead/missing
    first_appeared: int = 1          # 首次出现章节
    arc: str = ""                     # 人物弧光（成长轨迹）
    notes: str = ""                   # 备注（作者笔记）


@dataclass
class LocationProfile:
    """地点档案"""
    name: str
    description: str = ""             # 地点描述
    type: str = "city"               # 类型：city/mountain/sect/forest/dungeon
    connected_to: List[str] = field(default_factory=list)  # 相邻地点
    first_appeared: int = 1
    notable_characters: List[str] = field(default_factory=list)  # 常驻人物
    notes: str = ""


@dataclass
class PlotRule:
    """剧情规则（IF-THEN 条件规则，防止角色行为违反已声明规则）"""
    condition: str        # 触发条件（如"在天剑碑前领悟剑意"）
    consequence: str      # 结果（如"直接入内门"）
    rule_text: str        # 原文引用（如"凡能在天剑碑前领悟剑意者，可直接入内门"）
    chapter_introduced: int = 1  # 首次声明章节
    source_character: str = ""   # 声明此规则的角色/来源
    overridden: bool = False     # 是否已被后续规则覆盖
    override_reason: str = ""    # 覆盖原因


@dataclass
class CharacterKnowledge:
    """角色认知记录（谁在第几章知道了什么，防止角色认知前后矛盾）"""
    character: str        # 角色名
    chapter_learned: int  # 第几章知道的
    knowledge: str        # 知道的内容（如"叶青云是叶无痕的儿子"）
    source: str           # 怎么知道的（亲眼看到/听人说/推理得出/自我发现）
    detail: str = ""      # 补充说明（如"在演武场看到叶青云施展天孤剑诀后推断"）


@dataclass
class WorldSetting:
    """世界观设定条目"""
    key: str               # 设定名（如"修炼等级"、"魔法体系"）
    value: str              # 设定内容
    chapter_introduced: int = 1  # 首次引入章节


@dataclass
class SectFaction:
    """势力/宗派档案"""
    name: str                         # 势力名
    type: str = ""                    # 类型（宗门/家族/王朝/教派/组织等）
    description: str = ""             # 描述
    strength: str = ""                # 整体实力
    hierarchy: List[str] = field(default_factory=list)  # 层级结构（如["宗主", "长老", "内门弟子", "外门弟子"]）
    key_members: List[str] = field(default_factory=list)  # 核心成员
    allies: List[str] = field(default_factory=list)       # 盟友
    enemies: List[str] = field(default_factory=list)      # 敌对势力
    location: str = ""                # 所在地
    rules: List[str] = field(default_factory=list)        # 势力规矩/门规
    first_appeared: int = 1           # 首次出现章节
    notes: str = ""


@dataclass
class SceneEvent:
    """场景事件记录（在哪个地点发生了什么）"""
    chapter: int                      # 章节号
    location: str                     # 地点名
    scene: str = ""                   # 场景标识（开场/中段/结尾）
    event: str = ""                   # 发生了什么
    characters: List[str] = field(default_factory=list)  # 参与人物
    importance: int = 1               # 重要性 1-5


# ============ 主管理类 ============

class MemoryManager:
    """世界观与人物档案管理器"""

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or config.DATA_DIR)
        self.characters: Dict[str, CharacterProfile] = {}
        self.locations: Dict[str, LocationProfile] = {}
        self.world_settings: Dict[str, WorldSetting] = {}
        self.plot_rules: Dict[str, PlotRule] = {}
        self.character_knowledge: Dict[str, List[CharacterKnowledge]] = {}  # {角色名: [Knowledge...]}
        self.sect_factions: Dict[str, SectFaction] = {}
        self.scene_events: List[SceneEvent] = []
        self._load_all()

    # ---------- 持久化 ----------
    def _load_all(self):
        self._load_characters()
        self._load_locations()
        self._load_world_settings()
        self._load_plot_rules()
        self._load_character_knowledge()
        self._load_sect_factions()
        self._load_scene_events()

    def save_all(self):
        self._save_characters()
        self._save_locations()
        self._save_world_settings()
        self._save_plot_rules()
        self._save_character_knowledge()
        self._save_sect_factions()
        self._save_scene_events()

    def _save_json(self, filename: str, data: dict):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.data_dir / filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_json(self, filename: str) -> dict:
        path = self.data_dir / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    # ---------- 人物 ----------
    def _save_characters(self):
        data = {k: asdict(v) for k, v in self.characters.items()}
        self._save_json("characters.json", data)

    def _load_characters(self):
        data = self._load_json("characters.json")
        for name, d in data.items():
            # 兼容旧数据：过滤掉 CharacterProfile 中不存在的字段
            import dataclasses
            valid_fields = {f.name for f in dataclasses.fields(CharacterProfile)}
            filtered = {k: v for k, v in d.items() if k in valid_fields}
            self.characters[name] = CharacterProfile(**filtered)

    def add_character(self, profile: CharacterProfile):
        self.characters[profile.name] = profile
        self.save_all()

    def update_character_status(self, name: str, **kwargs):
        """更新人物状态（如位置、状态、关系）"""
        if name not in self.characters:
            return
        char = self.characters[name]
        for k, v in kwargs.items():
            if hasattr(char, k):
                setattr(char, k, v)
        self._save_characters()

    def get_character_prompt(self, name: str) -> str:
        """生成人物描述文本（用于注入LLM prompt）"""
        if name not in self.characters:
            return ""
        c = self.characters[name]
        lines = [
            f"【人物：{c.name}】",
            f"性别：{c.gender}，年龄：{c.age}" + (f"，修为：{c.cultivation}" if c.cultivation else ""),
            f"外貌：{c.appearance}",
            f"性格：{c.personality}",
            f"背景：{c.background}",
            f"目标：{c.goals}",
            f"语言风格：{c.speaking_style}",
            f"能力：{', '.join(c.abilities)}",
        ]
        # 关系：优先展示详细关系，兼容旧格式
        if c.relationships_detail:
            lines.append("人物关系（详细）：")
            stance_map = {"friendly": "🟢友好", "neutral": "⚪中立", "hostile": "🔴敌对", "adversarial": "🟠对立"}
            for other, detail in c.relationships_detail.items():
                rel_type = detail.get("type", detail.get("relation", ""))
                stance = detail.get("stance", "neutral")
                stance_tag = stance_map.get(stance, stance)
                met_ch = detail.get("met_chapter", detail.get("chapter_met", 0))
                met_ctx = detail.get("met_context", detail.get("how_met", ""))
                key_events = detail.get("key_events", [])
                parts = [f"{other}（{rel_type}·{stance_tag}）"]
                if met_ch > 0:
                    parts.append(f"第{met_ch}章认识")
                if met_ctx:
                    parts.append(f"「{met_ctx}」")
                if key_events:
                    parts.append("事件：" + "；".join(key_events))
                lines.append(f"  - {'，'.join(parts)}")
        elif c.relationships:
            lines.append(f"人物关系：{c.relationships}")
        lines.append(f"当前状态：{c.status}")
        return "\n".join(lines)

    def add_relationship(self, char_name: str, related_to: str, type: str,
                         stance: str = "neutral", met_chapter: int = 0,
                         met_context: str = "", key_events: List[str] = None,
                         notes: str = ""):
        """添加或更新人物关系（含详细上下文）"""
        if char_name not in self.characters:
            return
        char = self.characters[char_name]
        # 更新简略关系（兼容）
        char.relationships[related_to] = type
        # 更新详细关系
        detail = {
            "type": type,
            "stance": stance,
            "met_chapter": met_chapter,
            "met_context": met_context,
            "key_events": key_events or [],
            "notes": notes,
        }
        char.relationships_detail[related_to] = detail
        self._save_characters()

    def update_relationship_event(self, char_name: str, related_to: str, event: str):
        """追加关系关键事件"""
        if char_name not in self.characters:
            return
        char = self.characters[char_name]
        if related_to not in char.relationships_detail:
            return
        events = char.relationships_detail[related_to].get("key_events", [])
        if event not in events:
            events.append(event)
            char.relationships_detail[related_to]["key_events"] = events
            self._save_characters()

    def get_all_relationships_prompt(self) -> str:
        """生成所有人物关系的详细上下文文本（用于审校时判断角色是否认识、立场是否正确）"""
        stance_map = {"friendly": "🟢友好", "neutral": "⚪中立", "hostile": "🔴敌对", "adversarial": "🟠对立"}
        lines = ["【人物关系详细记录（审校时用于判断角色是否应该认识、关系立场是否正确）】"]
        has_detail = False
        for name, char in self.characters.items():
            if not char.relationships_detail:
                continue
            for other, detail in char.relationships_detail.items():
                has_detail = True
                rel_type = detail.get("type", detail.get("relation", "未知"))
                stance = detail.get("stance", "neutral")
                stance_tag = stance_map.get(stance, stance)
                met_ch = detail.get("met_chapter", detail.get("chapter_met", 0))
                met_ctx = detail.get("met_context", detail.get("how_met", ""))
                key_events = detail.get("key_events", [])
                parts = [f"  {name} ↔ {other}（{rel_type}·{stance_tag}）"]
                if met_ch > 0:
                    parts.append(f"：第{met_ch}章")
                if met_ctx:
                    parts.append(f"，在「{met_ctx}」中认识")
                if key_events:
                    parts.append(f"，关键事件：「{'」「'.join(key_events)}」")
                lines.append("".join(parts))
        if not has_detail:
            lines.append("  （暂无详细关系记录）")
        lines.append("")
        lines.append("⚠️ 审校时必须检查：")
        lines.append("  1. 如果角色A和角色B在关系记录中已认识，则后续章节中双方不应表现出互不认识。")
        lines.append("  2. 如果关系记录中两个角色的立场是「敌对/对立」，则后续章节中不应突然表现亲密无间，除非有充分剧情转折。")
        lines.append("  3. 如果关系记录中两个角色的立场是「友好」，则后续章节中不应突然反目成仇，除非有充分剧情铺垫。")
        lines.append("  4. 如果正文中出现了密切互动但关系记录中未记载，需标记为中/低严重性问题并建议补充关系记录。")
        return "\n".join(lines)

    def get_all_characters_prompt(self) -> str:
        """生成所有人物档案文本"""
        return "\n\n".join(
            self.get_character_prompt(name)
            for name in self.characters
        )

    # ---------- 地点 ----------
    def _save_locations(self):
        data = {k: asdict(v) for k, v in self.locations.items()}
        self._save_json("locations.json", data)

    def _load_locations(self):
        data = self._load_json("locations.json")
        for name, d in data.items():
            self.locations[name] = LocationProfile(**d)

    def add_location(self, profile: LocationProfile):
        self.locations[profile.name] = profile
        self.save_all()

    def get_location_prompt(self, name: str) -> str:
        if name not in self.locations:
            return ""
        loc = self.locations[name]
        return f"【地点：{loc.name}】\n类型：{loc.type}\n描述：{loc.description}\n相邻地点：{', '.join(loc.connected_to)}"

    # ---------- 世界观 ----------
    def _save_world_settings(self):
        data = {k: asdict(v) for k, v in self.world_settings.items()}
        self._save_json("world_settings.json", data)

    def _load_world_settings(self):
        data = self._load_json("world_settings.json")
        for key, d in data.items():
            self.world_settings[key] = WorldSetting(**d)

    def add_world_setting(self, setting: WorldSetting):
        self.world_settings[setting.key] = setting
        self.save_all()

    def get_world_settings_prompt(self) -> str:
        lines = ["【世界观设定】"]
        for key, s in self.world_settings.items():
            lines.append(f"- {key}：{s.value}")
        return "\n".join(lines)

    # ---------- 剧情规则 ----------
    def _save_plot_rules(self):
        data = {k: asdict(v) for k, v in self.plot_rules.items()}
        self._save_json("plot_rules.json", data)

    def _load_plot_rules(self):
        data = self._load_json("plot_rules.json")
        # 兼容空/旧格式
        if isinstance(data, list):
            data = {r.get("condition", f"rule_{i}"): r for i, r in enumerate(data) if isinstance(r, dict)}
        self.plot_rules = {}
        for key, d in data.items():
            self.plot_rules[key] = PlotRule(**d)

    def add_plot_rule(self, rule: PlotRule):
        """添加或更新剧情规则（按 condition 去重）"""
        self.plot_rules[rule.condition] = rule
        self._save_plot_rules()

    def get_active_rules_prompt(self) -> str:
        """生成当前生效的剧情规则文本（用于注入写作/审校 prompt）"""
        active_rules = [r for r in self.plot_rules.values() if not r.overridden]
        if not active_rules:
            return "（无特殊剧情规则）"
        lines = ["【当前生效的剧情规则（角色行为必须遵守）】"]
        for r in active_rules:
            source = f"（{r.source_character}于第{r.chapter_introduced}章声明）" if r.source_character else f"（第{r.chapter_introduced}章声明）"
            lines.append(f"  ⚖️ IF「{r.condition}」→ THEN「{r.consequence}」{source}")
            lines.append(f"     原文：「{r.rule_text}」")
        lines.append("\n⚠️ 以上规则已被正文明确声明，后续章节中角色行为必须遵守，不得违反。如需修改规则，必须在正文中给出合理解释并标记覆盖。")
        return "\n".join(lines)

    # ---------- 角色认知 ----------
    def _save_character_knowledge(self):
        data = {}
        for char_name, knowledge_list in self.character_knowledge.items():
            data[char_name] = [asdict(k) for k in knowledge_list]
        self._save_json("character_knowledge.json", data)

    def _load_character_knowledge(self):
        data = self._load_json("character_knowledge.json")
        self.character_knowledge = {}
        for char_name, items in data.items():
            if isinstance(items, list):
                self.character_knowledge[char_name] = [
                    CharacterKnowledge(**item) for item in items if isinstance(item, dict)
                ]

    def add_character_knowledge(self, knowledge: CharacterKnowledge):
        """添加角色认知记录（同一角色同一知识点不重复）"""
        if knowledge.character not in self.character_knowledge:
            self.character_knowledge[knowledge.character] = []
        # 去重：同一角色+同一知识点不重复添加
        existing = self.character_knowledge[knowledge.character]
        for k in existing:
            if k.knowledge == knowledge.knowledge:
                return  # 已存在，跳过
        existing.append(knowledge)
        self._save_character_knowledge()

    def get_character_knowledge_prompt(self, chapter: int = 0) -> str:
        """生成角色已知信息文本（用于注入写作/审校 prompt）"""
        if not self.character_knowledge:
            return "（无角色认知记录）"
        lines = ["【角色已知信息（写作时必须遵守——角色不能对已知信息表现惊讶）】"]
        for char_name, knowledge_list in self.character_knowledge.items():
            # 如果指定了章节，只显示该章节之前已知的信息
            if chapter > 0:
                known_by_chapter = [k for k in knowledge_list if k.chapter_learned < chapter]
            else:
                known_by_chapter = knowledge_list
            if not known_by_chapter:
                continue
            lines.append(f"\n  🧠 {char_name} 已知：")
            for k in known_by_chapter:
                source_tag = f"（{k.source}，第{k.chapter_learned}章）"
                detail_tag = f" —— {k.detail}" if k.detail else ""
                lines.append(f"    - {k.knowledge}{source_tag}{detail_tag}")
        if len(lines) == 1:
            return "（无角色认知记录）"
        lines.append("\n⚠️ 以上角色已在正文中获知这些信息。后续章节中，角色对这些信息不应再表现出惊讶、好奇或首次获知的反应。角色只能基于已知信息做决策，不能使用未知信息。")
        return "\n".join(lines)

    # ---------- 势力/宗派 ----------
    def _save_sect_factions(self):
        data = {k: asdict(v) for k, v in self.sect_factions.items()}
        self._save_json("sect_factions.json", data)

    def _load_sect_factions(self):
        data = self._load_json("sect_factions.json")
        if isinstance(data, list):
            data = {}
        self.sect_factions = {}
        for name, d in data.items():
            if isinstance(d, dict):
                import dataclasses
                valid_fields = {f.name for f in dataclasses.fields(SectFaction)}
                filtered = {k: v for k, v in d.items() if k in valid_fields}
                self.sect_factions[name] = SectFaction(**filtered)

    def add_sect_faction(self, faction: SectFaction):
        """添加势力/宗派"""
        self.sect_factions[faction.name] = faction
        self._save_sect_factions()

    def update_sect_faction(self, name: str, **kwargs):
        """更新势力/宗派信息"""
        if name not in self.sect_factions:
            return
        faction = self.sect_factions[name]
        for k, v in kwargs.items():
            if hasattr(faction, k):
                if isinstance(getattr(faction, k), list) and isinstance(v, list):
                    # 列表类型：追加去重
                    existing = getattr(faction, k)
                    for item in v:
                        if item not in existing:
                            existing.append(item)
                elif v:
                    setattr(faction, k, v)
        self._save_sect_factions()

    def get_sect_factions_prompt(self) -> str:
        """生成势力/宗派信息文本"""
        if not self.sect_factions:
            return "（无势力/宗派记录）"
        lines = ["【势力/宗派档案】"]
        for name, f in self.sect_factions.items():
            lines.append(f"\n  🏛️ {name}（{f.type}）")
            if f.description:
                lines.append(f"    描述：{f.description}")
            if f.strength:
                lines.append(f"    实力：{f.strength}")
            if f.hierarchy:
                lines.append(f"    层级：{' → '.join(f.hierarchy)}")
            if f.key_members:
                lines.append(f"    核心成员：{', '.join(f.key_members)}")
            if f.allies:
                lines.append(f"    盟友：{', '.join(f.allies)}")
            if f.enemies:
                lines.append(f"    敌对：{', '.join(f.enemies)}")
            if f.location:
                lines.append(f"    所在地：{f.location}")
            if f.rules:
                lines.append(f"    门规：{'；'.join(f.rules)}")
        return "\n".join(lines)

    # ---------- 场景事件 ----------
    def _save_scene_events(self):
        data = [asdict(e) for e in self.scene_events]
        self._save_json("scene_events.json", data)

    def _load_scene_events(self):
        data = self._load_json("scene_events.json")
        self.scene_events = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    import dataclasses
                    valid_fields = {f.name for f in dataclasses.fields(SceneEvent)}
                    filtered = {k: v for k, v in item.items() if k in valid_fields}
                    self.scene_events.append(SceneEvent(**filtered))

    def add_scene_event(self, event: SceneEvent):
        """添加场景事件"""
        self.scene_events.append(event)
        self._save_scene_events()

    def get_scene_events_prompt(self, chapter: int = 0) -> str:
        """生成场景事件文本（用于审校时检查场景一致性）"""
        if not self.scene_events:
            return "（无场景事件记录）"
        events = self.scene_events
        if chapter > 0:
            events = [e for e in events if e.chapter < chapter]
        if not events:
            return "（无场景事件记录）"
        lines = ["【场景事件记录（审校时用于检查事件发生地点是否正确）】"]
        # 按章节倒序，只显示最近10章
        recent = sorted(events, key=lambda e: e.chapter, reverse=True)[:20]
        for e in recent:
            chars = f"（{', '.join(e.characters)}）" if e.characters else ""
            lines.append(f"  第{e.chapter}章·{e.location}：{e.event}{chars}")
        return "\n".join(lines)

    # ---------- 导出（给可视化用）----------
    def export_character_relations(self) -> List[Dict]:
        """
        导出人物关系数据（供 character_map.html 可视化）
        返回 [{"from": "张三", "to": "李四", "relation": "师徒"}, ...]
        每条关系都是独立的有向边（不去重，保留方向性）
        """
        edges = []
        for name, char in self.characters.items():
            for other, relation in char.relationships.items():
                # 只保留两端都在人物档案中的边
                if other in self.characters:
                    edges.append({
                        "from": name,
                        "to": other,
                        "relation": relation,
                    })
        return edges

    def export_characters_for_viz(self) -> List[Dict]:
        """导出人物节点数据（供可视化）"""
        return [
            {
                "id": name,
                "label": name,
                "status": char.status,
                "importance": self._calc_importance(char),
            }
            for name, char in self.characters.items()
        ]

    def _calc_importance(self, char: CharacterProfile) -> int:
        """计算人物重要性（1-5，供可视化节点大小用）"""
        score = 0
        if char.first_appeared <= 3:
            score += 2
        if char.arc:
            score += 1
        if len(char.relationships) >= 3:
            score += 1
        return min(max(score, 1), 5)
