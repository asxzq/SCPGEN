"""
约束注册表 — 统一等式和不等式约束块，分配行索引

等式约束来源：
  1. M1 dynamics defect 等式
  2. M2 原始等式约束

不等式约束来源：
  1. M3 原始不等式约束
  2. nonnegative 变量域约束
"""

from __future__ import annotations

from typing import List, Dict, Any

from .models import EqualityBlock, InequalityBlock, VariableBlock


def build_equality_registry(
    m1_output: Dict[str, Any],
    m2_output: Dict[str, Any],
    m2_enabled: bool,
    var_registry: List[VariableBlock],
) -> List[EqualityBlock]:
    """构建等式约束注册表"""
    blocks: List[EqualityBlock] = []

    cfg = m1_output.get("configuration", {})
    var_mode = cfg.get("variable_mode", "perturbation")
    time_mode = cfg.get("time_mode", "fixed_time")
    vc_cfg = cfg.get("virtual_control", {})
    dims = m1_output.get("dimensions", {}).get("concrete", {})
    nx = dims.get("nx", 0)
    nu = dims.get("nu", 0)
    N = dims.get("N", 0)
    n_intervals = dims.get("n_intervals", N - 1)

    # ── 1. M1 dynamics equality ──
    active_eq = m1_output.get("active_equality_template", {})
    matrix_fill = m1_output.get("matrix_fill_template", {})

    dyn_rows = n_intervals * nx
    dyn_var_stencil = active_eq.get("lhs_terms", [])
    dyn_var_stencil_names = [t.get("variable", "") for t in dyn_var_stencil]

    # 从 matrix_fill_template 构建 matrix_blocks
    dyn_matrix_blocks = _build_m1_dynamics_matrix_blocks(
        matrix_fill, var_mode, time_mode, vc_cfg, var_registry, nx, nu
    )

    dyn_row_layout = {
        "loop_order": ["interval"],
        "local_row_index": "k * nx + i",
        "rows_per_interval": nx,
    }

    blocks.append(EqualityBlock(
        name="dynamics_defect",
        source_module="module1_dynamics",
        type="dynamics",
        rows_symbolic=f"(N - 1) * nx",
        rows_concrete=dyn_rows,
        variable_stencil=dyn_var_stencil_names,
        matrix_blocks=dyn_matrix_blocks,
        rhs_block={"name": "rhs"},
        row_layout=dyn_row_layout,
        template_reference={
            "active_equality_template": active_eq.get("name", ""),
            "time_mode": time_mode,
            "variable_mode": var_mode,
        },
    ))

    # ── 2. M2 original equality constraints ──
    if m2_enabled and m2_output:
        m2_ct = m2_output.get("constraint_templates", [])
        for ct in m2_ct:
            m2_var_stencil = ct.get("variable_stencil", [])
            m2_mft = ct.get("matrix_fill_template", {})
            m2_matrix_blocks = m2_mft.get("matrix_blocks", [])
            m2_rhs_block = m2_mft.get("rhs_block", {"name": "rhs"})
            m2_row_layout = m2_mft.get("row_layout", {})

            blocks.append(EqualityBlock(
                name=ct.get("name", "unknown"),
                source_module="module2_equalities",
                type="original_equality",
                rows_symbolic=ct.get("total_rows_symbolic", "0"),
                rows_concrete=ct.get("total_rows_concrete", 0),
                variable_stencil=m2_var_stencil,
                matrix_blocks=m2_matrix_blocks,
                rhs_block=m2_rhs_block,
                row_layout=m2_row_layout,
                template_reference={
                    "constraint_template": ct.get("name", ""),
                    "source_form": ct.get("source_form", ""),
                    "active_formula_case": ct.get("active_formula_case", ""),
                },
            ))

    # ── 分配行索引 ──
    _assign_eq_row_indices(blocks)

    return blocks


def _build_m1_dynamics_matrix_blocks(
    matrix_fill: Dict[str, Any],
    var_mode: str,
    time_mode: str,
    vc_cfg: Dict[str, Any],
    var_registry: List[VariableBlock],
    nx: int,
    nu: int,
) -> List[Dict[str, Any]]:
    """从 M1 matrix_fill_template 构建结构化 matrix_blocks。

    coefficient block shapes 由动力学维度决定，而非变量块自身 shape：
    - C_xL, C_xR: [nx, nx] — 动力学残差对状态的 Jacobian
    - C_uL, C_uR: [nx, nu] — 动力学残差对控制的 Jacobian
    - C_T:        [nx, 1]  — 动力学残差对自由时间的 Jacobian
    - vc 系数:    [nx, nx] — 虚拟控制对动力学残差的贡献
    """
    blocks = []
    prefix = "delta_" if var_mode == "perturbation" else ""

    # 基础四块：shape 由 nx, nu 决定
    for coeff, var_suffix, node, rows, cols in [
        ("C_xL", "x", "k", nx, nx),
        ("C_uL", "u", "k", nx, nu),
        ("C_xR", "x", "k+1", nx, nx),
        ("C_uR", "u", "k+1", nx, nu),
    ]:
        var_name = f"{prefix}{var_suffix}"
        blocks.append({
            "name": coeff,
            "variable_block": var_name,
            "node": node,
            "shape": [rows, cols],
        })

    # free_final_time: C_T 块 shape = [nx, 1]
    if time_mode == "free_final_time":
        var_name = "delta_T" if var_mode == "perturbation" else "T"
        blocks.append({
            "name": "C_T",
            "variable_block": var_name,
            "node": "scalar",
            "shape": [nx, 1],
        })

    # virtual control 块：shape = [nx, nx]
    vc_enabled = vc_cfg.get("enabled", False)
    if vc_enabled:
        vc_form = vc_cfg.get("form", "signed")
        mf_vc = matrix_fill.get("virtual_control_fill_blocks", [])
        if mf_vc:
            for vc_entry in mf_vc:
                var_name = vc_entry.get("variable", "").replace("[k]", "")
                coeff = vc_entry.get("coefficient", "+I_nx")
                blocks.append({
                    "name": coeff,
                    "variable_block": var_name,
                    "node": "k",
                    "coefficient_value": coeff,
                    "shape": [nx, nx],
                })
        else:
            if vc_form == "signed":
                blocks.append({
                    "name": "+I_nx",
                    "variable_block": "vc",
                    "node": "k",
                    "coefficient_value": "+I_nx",
                    "shape": [nx, nx],
                })
            elif vc_form == "split_nonnegative":
                blocks.append({
                    "name": "+I_nx",
                    "variable_block": "vc_plus",
                    "node": "k",
                    "coefficient_value": "+I_nx",
                    "shape": [nx, nx],
                })
                blocks.append({
                    "name": "-I_nx",
                    "variable_block": "vc_minus",
                    "node": "k",
                    "coefficient_value": "-I_nx",
                    "shape": [nx, nx],
                })

    return blocks


def build_inequality_registry(
    m3_output: Dict[str, Any],
    m3_enabled: bool,
    var_registry: List[VariableBlock],
) -> List[InequalityBlock]:
    """构建不等式约束注册表"""
    blocks: List[InequalityBlock] = []

    # ── 1. M3 原始不等式约束 ──
    if m3_enabled and m3_output:
        m3_ct = m3_output.get("constraint_templates", [])
        for ct in m3_ct:
            m3_var_stencil = ct.get("variable_stencil", [])
            m3_mft = ct.get("matrix_fill_template", {})
            m3_matrix_blocks = m3_mft.get("matrix_blocks", [])
            m3_rhs_block = m3_mft.get("rhs_block", {"name": "rhs"})
            m3_row_layout = m3_mft.get("row_layout", {})

            blocks.append(InequalityBlock(
                name=ct.get("name", "unknown"),
                source_module="module3_inequalities",
                type="original_inequality",
                rows_symbolic=ct.get("total_rows_symbolic", "0"),
                rows_concrete=ct.get("total_rows_concrete", 0),
                variable_stencil=m3_var_stencil,
                matrix_blocks=m3_matrix_blocks,
                rhs_block=m3_rhs_block,
                row_layout=m3_row_layout,
                template_reference={
                    "constraint_template": ct.get("name", ""),
                    "slack_enabled": ct.get("slack_enabled", False),
                    "active_formula_case": ct.get("active_formula_case", ""),
                },
            ))

    # ── 2. Variable domain constraints (nonnegative) ──
    for vb in var_registry:
        if vb.domain == "nonnegative":
            dim = vb.dimension_concrete
            blocks.append(InequalityBlock(
                name=f"domain_{vb.name}_nonnegative",
                source_module=vb.source_module,
                type="variable_domain",
                rows_symbolic=vb.dimension_symbolic,
                rows_concrete=dim,
                variable=vb.name,
                domain="nonnegative",
                canonical_inequality=f"-{vb.name} <= 0",
                matrix_blocks=[{
                    "name": "C_domain",
                    "variable_block": vb.name,
                    "coefficient_value": "-I",
                    "shape": [dim, dim],
                    "structure": "negative_identity",
                    "is_diagonal": True,
                }],
                rhs_block={
                    "name": "zero",
                    "value": 0,
                },
                row_layout={
                    "loop_order": ["flat_variable_index"],
                    "local_row_index": "local_index",
                    "rows_per_variable": 1,
                },
            ))

    # ── 分配行索引 ──
    _assign_ineq_row_indices(blocks)

    return blocks


def _assign_eq_row_indices(blocks: List[EqualityBlock]) -> None:
    """按顺序分配等式行索引"""
    offset = 0
    for blk in blocks:
        blk.row_start_concrete = offset
        blk.row_end_concrete = offset + blk.rows_concrete - 1
        offset += blk.rows_concrete


def _assign_ineq_row_indices(blocks: List[InequalityBlock]) -> None:
    """按顺序分配不等式行索引"""
    offset = 0
    for blk in blocks:
        blk.row_start_concrete = offset
        blk.row_end_concrete = offset + blk.rows_concrete - 1
        offset += blk.rows_concrete


def _find_var_block(var_registry: List[VariableBlock], name: str) -> VariableBlock | None:
    """在变量注册表中按名称查找"""
    for vb in var_registry:
        if vb.name == name:
            return vb
    return None
