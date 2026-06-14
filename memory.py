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
    relationships: Dict[str, str] = field(default_factory=dict)  # {人物名: 关系}
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
        self._load_all()

    # ---------- 持久化 ----------
    def _load_all(self):
        self._load_characters()
        self._load_locations()
        self._load_world_settings()
        self._load_plot_rules()
        self._load_character_knowledge()

    def save_all(self):
        self._save_characters()
        self._save_locations()
        self._save_world_settings()
        self._save_plot_rules()
        self._save_character_knowledge()

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
            self.characters[name] = CharacterProfile(**d)

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
            f"人物关系：{c.relationships}",
            f"当前状态：{c.status}",
        ]
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
