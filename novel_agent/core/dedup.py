"""
dedup.py - 伏笔/任务去重工具
统一去重入口，供 SETTINGS_JSON 路径、正则路径、review 路径共用。
"""

import logging
from typing import List, Dict, Set, Tuple
from .models import TaskProfile

logger = logging.getLogger(__name__)


def dedup_tasks(new_tasks: List[TaskProfile], existing_tasks: Dict[str, TaskProfile]) -> List[TaskProfile]:
    """按 name + chapter_created 去重"""
    seen: Set[Tuple[str, int]] = {(t.name, t.chapter_created) for t in existing_tasks.values()}
    result = []
    for t in new_tasks:
        key = (t.name, t.chapter_created)
        if key not in seen:
            seen.add(key)
            result.append(t)
        else:
            logger.debug("跳过重复任务：%s（第%d章）", t.name, t.chapter_created)
    return result


def dedup_foreshadows_by_content(new_items: List[dict], existing_contents: Set[str]) -> List[dict]:
    """按 content 去重（用于 review 路径的伏笔提取）"""
    result = []
    for item in new_items:
        content = item.get("content", "")
        normalized = "".join(content.split())
        if normalized and normalized not in existing_contents:
            existing_contents.add(normalized)
            result.append(item)
        else:
            logger.debug("跳过重复伏笔内容：%s", content[:40])
    return result
