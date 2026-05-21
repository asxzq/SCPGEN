"""
YAML 写入器 — 使用 common/yaml_io 确保零锚点/别名输出
"""

from __future__ import annotations

from typing import Dict, Any

from scpgen.common.yaml_io import write_yaml


class YamlWriter:
    """YAML 写入器，确保输出无锚点/别名。"""

    def write(self, data: Dict[str, Any], path: str) -> None:
        """将 dict 写入 YAML 文件。

        Args:
            data: 要序列化的 dict
            path: 输出文件路径
        """
        write_yaml(data, path)
