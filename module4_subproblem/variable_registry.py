"""
变量注册表 — 统一所有优化变量块，分配列索引

变量顺序：
  1. M1 主变量（state/control/time perturbations 或 direct states）
  2. M1 virtual control 变量（vc 或 vc_plus/vc_minus）
  3. M3 slack 变量（s_<constraint_name>）
"""

from __future__ import annotations

from typing import List, Dict, Any

from .models import VariableBlock


def build_variable_registry(
    m1_output: Dict[str, Any],
    m2_output: Dict[str, Any],
    m3_output: Dict[str, Any],
    m2_enabled: bool,
    m3_enabled: bool,
) -> List[VariableBlock]:
    """构建完整的变量注册表，返回有序的 VariableBlock 列表。"""

    blocks: List[VariableBlock] = []
    seen_names: set = set()

    cfg = m1_output.get("configuration", {})
    var_mode = cfg.get("variable_mode", "perturbation")
    time_mode = cfg.get("time_mode", "fixed_time")
    vc_cfg = cfg.get("virtual_control", {})
    vc_enabled = vc_cfg.get("enabled", False)
    vc_form = vc_cfg.get("form", "signed")
    dims = m1_output.get("dimensions", {}).get("concrete", {})
    nx = dims.get("nx", 0)
    nu = dims.get("nu", 0)
    N = dims.get("N", 0)
    n_intervals = dims.get("n_intervals", N - 1)

    # ── 1. M1 主变量 ──
    dvt = m1_output.get("decision_variable_templates", [])
    for dv in dvt:
        name = dv.get("name", "")
        if name in seen_names:
            raise ValueError(f"Duplicate variable block: {name}")
        seen_names.add(name)

        shape_sym = dv.get("shape_symbolic", [])
        shape_con = dv.get("shape_concrete", [])
        dim_con = _prod(shape_con)
        dim_sym = _format_dim_symbolic(shape_sym)

        role = _infer_role(name, var_mode, time_mode)
        if name in ("delta_x", "x"):
            indexing = {
                "element": f"{name}[k, i]",
                "flat_index": f"column_start + k * {shape_con[1] if len(shape_con) > 1 else 1} + i",
            }
        elif name in ("delta_u", "u"):
            indexing = {
                "element": f"{name}[k, j]",
                "flat_index": f"column_start + k * {shape_con[1] if len(shape_con) > 1 else 1} + j",
            }
        else:
            indexing = {
                "element": name,
                "flat_index": "column_start",
            }

        blocks.append(VariableBlock(
            name=name,
            role=role,
            source_module="module1_dynamics",
            domain="free",
            shape_symbolic=shape_sym,
            shape_concrete=shape_con,
            dimension_symbolic=dim_sym,
            dimension_concrete=dim_con,
            indexing_rule=indexing,
        ))

    # ── 2. M1 virtual control ──
    ivt = m1_output.get("introduced_variable_templates", [])
    for iv in ivt:
        name = iv.get("name", "")
        if name in seen_names:
            raise ValueError(f"Duplicate variable block: {name}")
        seen_names.add(name)

        shape_sym = iv.get("shape_symbolic", [])
        shape_con = iv.get("shape_concrete", [])
        dim_con = _prod(shape_con)
        dim_sym = _format_dim_symbolic(shape_sym)
        domain = iv.get("domain", "free")

        role = iv.get("role", "dynamics_virtual_control")
        if shape_con and len(shape_con) >= 2:
            indexing = {
                "element": f"{name}[k, i]",
                "flat_index": f"column_start + k * {shape_con[1]} + i",
            }
        else:
            indexing = {
                "element": name,
                "flat_index": "column_start",
            }

        blocks.append(VariableBlock(
            name=name,
            role=role,
            source_module="module1_dynamics",
            domain=domain,
            shape_symbolic=shape_sym,
            shape_concrete=shape_con,
            dimension_symbolic=dim_sym,
            dimension_concrete=dim_con,
            indexing_rule=indexing,
        ))

    # ── 3. M3 slack 变量 ──
    if m3_enabled and m3_output:
        m3_iv = m3_output.get("introduced_variables", [])
        for iv in m3_iv:
            name = iv.get("name", "")
            if name in seen_names:
                raise ValueError(f"Duplicate variable block: {name}")
            seen_names.add(name)

            shape_sym = iv.get("shape_symbolic", [])
            shape_con = iv.get("shape_concrete", [])
            dim_con = _prod(shape_con)
            dim_sym = _format_dim_symbolic(shape_sym)
            domain = iv.get("domain", "free")
            role = iv.get("role", "inequality_slack")
            parent = iv.get("parent_constraint", "")

            if shape_con and len(shape_con) >= 2:
                indexing = {
                    "element": f"{name}[k, i]",
                    "flat_index": f"column_start + k * {shape_con[1]} + i",
                }
            else:
                indexing = {
                    "element": name,
                    "flat_index": "column_start",
                }

            blocks.append(VariableBlock(
                name=name,
                role=role,
                source_module="module3_inequalities",
                domain=domain,
                shape_symbolic=shape_sym,
                shape_concrete=shape_con,
                dimension_symbolic=dim_sym,
                dimension_concrete=dim_con,
                indexing_rule=indexing,
            ))

    # ── 分配列索引 ──
    _assign_column_indices(blocks)

    return blocks


def _assign_column_indices(blocks: List[VariableBlock]) -> None:
    """按顺序分配 column_start_concrete 和 column_end_concrete"""
    offset = 0
    for blk in blocks:
        blk.column_start_concrete = offset
        blk.column_end_concrete = offset + blk.dimension_concrete - 1
        offset += blk.dimension_concrete


def _prod(values: List[int]) -> int:
    """计算整数列表的乘积"""
    result = 1
    for v in values:
        result *= v
    return result


def _format_dim_symbolic(shape: List[Any]) -> str:
    """将符号形状列表格式化为维度表达式"""
    parts = [str(s) for s in shape]
    return " * ".join(parts) if parts else "0"


def _infer_role(name: str, var_mode: str, time_mode: str) -> str:
    """推断变量块的语义角色"""
    if name in ("delta_x", "x"):
        return "state_perturbation" if var_mode == "perturbation" else "state"
    if name in ("delta_u", "u"):
        return "control_perturbation" if var_mode == "perturbation" else "control"
    if name in ("delta_T", "T"):
        return "time"
    return "unknown"
