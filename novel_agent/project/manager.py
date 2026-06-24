"""
项目管理模块
负责：列出所有小说项目、创建新项目、切换当前项目、读取/保存项目配置
"""
import json
import re
import config
from novel_agent.core.file_utils import atomic_write_json

CONFIG_FILE = "config.json"

# 支持的小说类型
NOVEL_TYPES = [
    "玄幻修仙", "都市现实", "科幻未来", "历史架空",
    "武侠江湖", "悬疑推理", "言情校园", "奇幻冒险", "其他",
]

# 支持的文风
NOVEL_STYLES = [
    "轻松搞笑", "严肃史诗", "黑暗压抑", "热血激昂",
    "悬疑紧张", "文艺细腻", "快节奏爽文", "慢热深沉",
]


# 项目名安全字符（中英文、数字、下划线、连字符）
_VALID_PROJECT_NAME = re.compile(r'^[\w一-鿿-]+$')


def ensure_projects_root():
    """确保 projects/ 目录存在"""
    config.PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)


def list_projects():
    """列出所有已有项目"""
    ensure_projects_root()
    projects = []
    for d in sorted(config.PROJECTS_ROOT.iterdir()):
        if d.is_dir() and (d / CONFIG_FILE).exists():
            cfg = load_project_config(d.name)
            display_name = d.name
            outline_path = d / "data" / "outline.json"
            if outline_path.exists():
                try:
                    with open(outline_path, "r", encoding="utf-8") as f:
                        outline = json.load(f)
                    title = outline.get("meta", {}).get("title", "") or outline.get("title", "")
                    if title:
                        display_name = title
                except Exception:
                    pass
            projects.append({
                "name": d.name,
                "display_name": display_name,
                "type": cfg.get("type", "未知"),
                "style": cfg.get("style", "未知"),
                "chapters": cfg.get("chapters_written", 0),
                "concept": cfg.get("concept", "")[:50],
            })
    return projects


def load_project_config(project_name: str):
    """读取项目配置"""
    cfg_path = config.PROJECTS_ROOT / project_name / CONFIG_FILE
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_project_config(project_name: str, cfg: dict):
    """保存项目配置"""
    ensure_projects_root()
    project_dir = config.PROJECTS_ROOT / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = project_dir / CONFIG_FILE
    atomic_write_json(cfg_path, cfg)


def create_project(project_name: str, novel_type: str, style: str, concept: str):
    """创建新项目目录和初始配置"""
    if not _VALID_PROJECT_NAME.match(project_name):
        raise ValueError(
            f"项目名包含非法字符: {project_name!r}\n"
            f"项目名仅允许中英文、数字、下划线和连字符"
        )
    ensure_projects_root()
    project_dir = config.PROJECTS_ROOT / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    # 创建子目录
    (project_dir / "data").mkdir(exist_ok=True)
    (project_dir / "output").mkdir(exist_ok=True)
    (project_dir / "output" / "chapters").mkdir(exist_ok=True)

    cfg = {
        "project_name": project_name,
        "type": novel_type,
        "style": style,
        "concept": concept,
        "chapters_written": 0,
        "chapters_planned": 0,
        "created_at": "",
        "updated_at": "",
    }
    save_project_config(project_name, cfg)
    return project_dir


def get_project_paths(project_name: str):
    """返回指定项目的 data/ 和 output/ 路径"""
    project_dir = config.PROJECTS_ROOT / project_name
    return {
        "project_dir": str(project_dir),
        "data_dir": str(project_dir / "data"),
        "output_dir": str(project_dir / "output"),
        "chapters_dir": str(project_dir / "output" / "chapters"),
    }


def update_project_progress(project_name: str, chapters_written: int = None, outline: dict = None):
    """更新项目进度（写完章节后调用）"""
    cfg = load_project_config(project_name)
    if chapters_written is not None:
        cfg["chapters_written"] = max(cfg.get("chapters_written", 0), chapters_written)
    if outline is not None:
        cfg["chapters_planned"] = (outline.get("meta", {})).get("total_chapters", 0)
    from datetime import datetime
    cfg["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_project_config(project_name, cfg)
