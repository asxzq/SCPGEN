"""
输入加载器 — 读取并验证 Module 4 subproblem IR YAML
"""

from __future__ import annotations

from typing import Dict, Any

from scpgen.common.yaml_io import read_yaml


# Module 4 输出中必须存在的顶级键
_REQUIRED_TOP_KEYS = [
    "cost_terms",
    "decision_variable_registry",
    "equality_constraint_registry",
    "inequality_constraint_registry",
    "problem",
    "symbol_table",
    "subproblem_template",
    "matrix_assembly_plan",
    "debug_summary",
]


def load_module4_ir(path: str) -> Dict[str, Any]:
    """从文件路径加载并验证 Module 4 subproblem IR。

    Args:
        path: Module 4 输出 YAML 文件路径

    Returns:
        解析后的 dict

    Raises:
        ValueError: 缺少必需的顶级键时抛出
        FileNotFoundError: 文件不存在时抛出
    """
    data = read_yaml(path)

    # 验证必需的顶级键
    missing = [k for k in _REQUIRED_TOP_KEYS if k not in data]
    if missing:
        raise ValueError(
            f"Module 4 IR 缺少必需的顶级键: {missing}. "
            f"请确保输入是有效的 subproblem_ir_module4_output.yaml"
        )

    # 验证 cost_terms.merged 存在
    ct = data.get("cost_terms", {})
    if "merged" not in ct:
        raise ValueError(
            "Module 4 IR 中 cost_terms 缺少 'merged' 键"
        )

    return data


def load_bundle(bundle_path: str) -> Dict[str, Any]:
    """从 bundle YAML 加载 Module 5 输入配置。

    Bundle 格式:
        problem_name: gliding
        inputs:
          module4_subproblem_ir:
            path: runs/module4/gliding/subproblem_ir_module4_output.yaml
        output:
          ecos_canonical_ir: runs/module5/gliding/ecos_canonical_module5_output.yaml

    Args:
        bundle_path: Bundle YAML 文件路径

    Returns:
        {"module4_path": str, "output_path": str, "problem_name": str}
    """
    data = read_yaml(bundle_path)

    inputs = data.get("inputs", {})
    m4_cfg = inputs.get("module4_subproblem_ir", {})
    if isinstance(m4_cfg, str):
        module4_path = m4_cfg
    else:
        module4_path = m4_cfg.get("path", "")

    if not module4_path:
        raise ValueError("Bundle 中未指定 module4_subproblem_ir.path")

    output_cfg = data.get("output", {})
    output_path = output_cfg.get("ecos_canonical_ir", "")

    return {
        "module4_path": module4_path,
        "output_path": output_path,
        "problem_name": data.get("problem_name", ""),
    }
