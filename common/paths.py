"""路径工具 — 项目内路径解析"""

import os

# 项目根目录 (02test/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def project_root() -> str:
    return _PROJECT_ROOT


def examples_dir(*parts) -> str:
    return os.path.join(_PROJECT_ROOT, "examples", *parts)


def runs_dir(*parts) -> str:
    return os.path.join(_PROJECT_ROOT, "runs", *parts)


def ensure_dir(path: str) -> str:
    """确保目录存在，返回路径"""
    os.makedirs(path, exist_ok=True)
    return path
