"""Module6 文件写入器 — 将生成的 C 代码写入磁盘。"""

from __future__ import annotations

import os
from typing import Dict


def write_generated_files(code_dir: str, files: Dict[str, str]) -> None:
    """将生成的 C 代码文件写入目标目录。

    Args:
        code_dir: 目标目录路径
        files: Dict[文件名, C 源码内容]
    """
    os.makedirs(code_dir, exist_ok=True)

    for filename, content in files.items():
        filepath = os.path.join(code_dir, filename)
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    # 确保换行符一致
    for filename in files:
        filepath = os.path.join(code_dir, filename)
        # 读取并写回以规范化换行符
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
