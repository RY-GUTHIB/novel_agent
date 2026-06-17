"""
file_utils.py - 文件操作工具（原子写入）
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: Any, indent: int = 2):
    """原子写入 JSON 文件：先写临时文件，再 os.replace 原子替换。
    防止写入中途崩溃导致文件截断/损坏。"""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(path.parent), delete=False, suffix=".tmp",
            mode="w", encoding="utf-8",
        ) as tmp:
            tmp_path = tmp.name
            json.dump(data, tmp, ensure_ascii=False, indent=indent)
        os.replace(tmp_path, str(path))
    except BaseException:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def atomic_write_text(path: Path, text: str):
    """原子写入文本文件。"""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(path.parent), delete=False, suffix=".tmp",
            mode="w", encoding="utf-8",
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(text)
        os.replace(tmp_path, str(path))
    except BaseException:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
