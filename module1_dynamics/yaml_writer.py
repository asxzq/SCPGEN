"""
YAML 序列化器 — 将输出 dict 写入 YAML 文件

委托给 scpgen.common.yaml_io，确保 clone_no_alias + NoAliasDumper 保护。
"""

from __future__ import annotations

from typing import Dict, Any

from scpgen.common.yaml_io import write_yaml, yaml_dumps


class YamlWriter:
    """将 Python dict 序列化为 YAML 文件（零锚点/别名输出）"""

    @staticmethod
    def write(output_dict: Dict[str, Any], filepath: str) -> None:
        write_yaml(output_dict, filepath)

    @staticmethod
    def dumps(output_dict: Dict[str, Any]) -> str:
        return yaml_dumps(output_dict)
