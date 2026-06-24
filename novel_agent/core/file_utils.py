"""
file_utils.py - 文件操作工具（原子写入）
"""
import json
import os
import re
import tempfile
from pathlib import Path, PurePath
from typing import Any


def atomic_write_json(path: PurePath, data: Any, indent: int = 2):
    """原子写入 JSON 文件：先写临时文件，再 os.replace 原子替换。
    防止写入中途崩溃导致文件截断/损坏。"""
    path = Path(path)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(path.parent), delete=False, suffix=".tmp",
            mode="w", encoding="utf-8",
        ) as tmp:
            tmp_path = tmp.name
            json.dump(data, tmp, ensure_ascii=False, indent=indent)
        os.replace(tmp_path, str(path))
    except Exception:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def atomic_write_text(path: PurePath, text: str):
    """原子写入文本文件。"""
    path = Path(path)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(path.parent), delete=False, suffix=".tmp",
            mode="w", encoding="utf-8",
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(text)
        os.replace(tmp_path, str(path))
    except Exception:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


class JsonRepositoryMixin:
    """JSON 持久化 mixin——统一 _save_json / _load_json 模式。
    子类需设置 self.data_dir (Path)。"""
    def _save_json(self, filename: str, data):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.data_dir / filename, data)

    def _load_json(self, filename: str, default=None):
        path = self.data_dir / filename
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError, OSError):
                pass
        return default if default is not None else {}


# 中文数字映射表
_CN_DIGIT_MAP = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100, "千": 1000,
}


def parse_travel_time(time_str: str) -> float:
    """解析通行时间/时间间隔字符串为天数，支持中文数字和多种格式。
    用于 spacetime_guard._parse_travel_days 和 continuity._parse_time_elapsed 的统一实现。"""
    if not time_str:
        return 0
    # "三日后""3日后""两日后"
    m = re.search(r'([一两三四五六七八九十百零\d]+)\s*[日天]后', time_str)
    if m:
        return float(parse_chinese_number(m.group(1)))
    # "第1天""第N天"（兼容 "炼气三层·第1天" 格式）
    m = re.search(r'第\s*([\d零一二三四五六七八九十百千]+)\s*[日天]', time_str)
    if m:
        return float(parse_chinese_number(m.group(1)))
    # "2日""3日骑马""2天"（裸数字+日/天）
    m = re.match(r'(\d+)\s*[日天]', time_str.strip())
    if m:
        return float(m.group(1))
    # "半日后""半日""半天"
    if '半' in time_str:
        return 0.5
    # "翌日""次日""第二天"
    if any(kw in time_str for kw in ["翌日", "次日", "第二天"]):
        return 1
    # "一个时辰后""两个时辰""3时辰"
    m = re.search(r'([一两三四五六七八九十百零\d]+)\s*个?时辰', time_str)
    if m:
        return float(parse_chinese_number(m.group(1))) * 0.125
    # "片刻""少顷" — 忽略
    if any(kw in time_str for kw in ["片刻", "少顷", "须臾", "弹指"]):
        return 0.01
    # "3日骑马" → 3（兜底数字提取）
    m = re.match(r'(\d+)', time_str.strip())
    if m:
        return float(m.group(1))
    return 0


def parse_chinese_number(num_str: str) -> int:
    """解析中文数字字符串为整数，支持 '十二'=12, '二十一'=21, '一百二十三'=123 等。
    纯阿拉伯数字字符串也支持（直接 int 转换）。"""
    if not num_str:
        return 0
    if num_str.isdigit():
        return int(num_str)
    total = 0
    curr = 0
    for ch in num_str:
        val = _CN_DIGIT_MAP.get(ch)
        if val is None:
            return 0
        if val >= 10:
            if curr == 0:
                curr = val
            else:
                curr *= val
            total += curr
            curr = 0
        else:
            curr = val
    return total + curr
