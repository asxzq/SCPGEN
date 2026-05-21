"""
YAML 输出 — 复用 scpgen/common/yaml_io.py
"""

from __future__ import annotations

from typing import Dict, Any

from scpgen.common.yaml_io import write_yaml


class YamlWriter:
    """Module 4 YAML 输出"""

    @staticmethod
    def write(data: Dict[str, Any], path: str) -> None:
        write_yaml(data, path)
