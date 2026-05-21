"""
YAML 读写工具 — 自动适配 ruamel.yaml / PyYAML

输出时使用 clone_no_alias 彻底打破对象共享引用，配合 Dumper 级别禁止 aliases，
确保不产生 YAML anchors / aliases（&id001 / *id001）。
"""

from __future__ import annotations

from typing import Dict, Any, Optional

_HAS_RUAMEL = False
try:
    import ruamel.yaml
    _HAS_RUAMEL = True
except ImportError:
    pass

if not _HAS_RUAMEL:
    import yaml as _pyyaml


# ══════════════════════════════════════════════════════════════
# 递归 clone，不使用 memo，每次出现 list/dict 都创建新对象
# ══════════════════════════════════════════════════════════════

def clone_no_alias(obj):
    """递归克隆，不使用 memo，彻底打破对象图中的共享引用。

    与 deepcopy 不同：deepcopy 使用 memo 保留对象图中的共享结构
    （例如 a=[1,2]; d={'x':a, 'y':a} 克隆后 d['x'] is d['y'] 仍为 True），
    这会导致 PyYAML / ruamel.yaml 产生 &id / *id anchors。

    clone_no_alias 不使用 memo，每次遇到 list/dict 都创建全新对象，
    保证序列化时没有任何引用关系可被追蹤。
    """
    if isinstance(obj, dict):
        return {clone_no_alias(k): clone_no_alias(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clone_no_alias(v) for v in obj]
    return obj


# ══════════════════════════════════════════════════════════════
# PyYAML NoAliasDumper — 即使有共享引用也不输出 anchors
# ══════════════════════════════════════════════════════════════

if not _HAS_RUAMEL:
    class _NoAliasDumper(_pyyaml.SafeDumper):
        def ignore_aliases(self, data):
            return True


# ══════════════════════════════════════════════════════════════
# 公共 API
# ══════════════════════════════════════════════════════════════

def read_yaml(filepath: str) -> Dict[str, Any]:
    """读取 YAML 文件"""
    with open(filepath, "r", encoding="utf-8") as f:
        if _HAS_RUAMEL:
            yaml_inst = ruamel.yaml.YAML(typ="safe")
            return yaml_inst.load(f)
        else:
            return _pyyaml.safe_load(f)


def write_yaml(data: Dict[str, Any], filepath: str) -> None:
    """写入 YAML 文件（禁止 anchors/aliases）"""
    data = clone_no_alias(data)
    with open(filepath, "w", encoding="utf-8") as f:
        if _HAS_RUAMEL:
            yaml_inst = ruamel.yaml.YAML()
            yaml_inst.default_flow_style = False
            yaml_inst.allow_unicode = True
            yaml_inst.width = 120
            # 实例级 representer：禁止 ruamel.yaml 产生 &id / *id anchors
            yaml_inst.representer.ignore_aliases = lambda data: True
            yaml_inst.dump(data, f)
        else:
            _pyyaml.dump(
                data, f,
                Dumper=_NoAliasDumper,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                width=120,
            )


def yaml_dumps(data: Dict[str, Any]) -> str:
    """序列化为 YAML 字符串（禁止 anchors/aliases）"""
    data = clone_no_alias(data)
    import io
    buf = io.StringIO()
    if _HAS_RUAMEL:
        yaml_inst = ruamel.yaml.YAML()
        yaml_inst.default_flow_style = False
        yaml_inst.allow_unicode = True
        yaml_inst.width = 120
        # 实例级 representer：禁止 ruamel.yaml 产生 &id / *id anchors
        yaml_inst.representer.ignore_aliases = lambda data: True
        yaml_inst.dump(data, buf)
    else:
        _pyyaml.dump(
            data, buf,
            Dumper=_NoAliasDumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
    return buf.getvalue()
