"""
等式规范化器 — 将 Module 4 的 A_eq z = b_eq 转换为 ECOS 的 A y = b

如果 y 包含 epigraph 变量（dim_y > dim_z），则 A 矩阵需要补零列。
"""

from __future__ import annotations

from typing import Dict, List, Any


def canonicalize_equalities(
    m4_ir: Dict[str, Any],
    var_ext: Dict[str, Any],
) -> Dict[str, Any]:
    """将 Module 4 等式转换为 ECOS 形式。

    Args:
        m4_ir: Module 4 subproblem IR dict
        var_ext: variable_extender 的输出

    Returns:
        等式部分 dict:
        {
            "form": "A * y = b",
            "A_shape_concrete": [n_rows, dim_y],
            "b_shape_concrete": [n_rows],
            "epigraph_columns_are_zero": bool,
            "source_blocks": [...],
            "assembly_plan": {...},
        }
    """
    dim_y = var_ext["dim_y"]
    dim_z = var_ext["dim_z"]

    eq_registry = m4_ir.get("equality_constraint_registry", {})
    m4_blocks = eq_registry.get("blocks", [])
    total_rows = eq_registry.get("total_rows_concrete", 0)

    # 转换每个块
    source_blocks = []
    for mb in m4_blocks:
        source_blocks.append({
            "name": mb["name"],
            "source_module": mb.get("source_module", ""),
            "type": mb.get("type", ""),
            "rows_concrete": mb.get("rows_concrete", 0),
            "row_start_concrete": mb.get("row_start_concrete", 0),
            "row_end_concrete": mb.get("row_end_concrete", 0),
            "variable_stencil": mb.get("variable_stencil", []),
            "matrix_blocks": mb.get("matrix_blocks", []),
            "rhs_block": mb.get("rhs_block", {}),
            "row_layout": mb.get("row_layout", {}),
            "template_reference": mb.get("template_reference", {}),
        })

    has_epigraph = dim_y > dim_z

    return {
        "form": "A * y = b",
        "A_shape_concrete": [total_rows, dim_y],
        "A_shape_symbolic": [eq_registry.get("total_rows_symbolic", "?"), _dim_y_symbolic(var_ext)],
        "b_shape_concrete": [total_rows],
        "epigraph_columns_are_zero": has_epigraph,
        "source_blocks": source_blocks,
        "assembly_plan": {
            "description": (
                "A 矩阵的行块从 Module 4 的 equality_constraint_registry 复制而来。"
                + (" 如果 dim_y > dim_z，则 epigraph 列为零。" if has_epigraph else "")
            ),
            "row_blocks": _build_equality_assembly_plan(m4_ir, var_ext),
        },
        "total_rows_concrete": total_rows,
    }


def _build_equality_assembly_plan(
    m4_ir: Dict[str, Any],
    var_ext: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """构建等式装配计划。

    从 Module 4 的 matrix_assembly_plan.equality 复制行块信息。
    """
    plan = m4_ir.get("matrix_assembly_plan", {})
    eq_plan = plan.get("equality", {})
    m4_row_blocks = eq_plan.get("row_blocks", [])

    row_blocks = []
    for rb in m4_row_blocks:
        row_blocks.append({
            "name": rb.get("name", ""),
            "row_start_concrete": rb.get("row_start_concrete", 0),
            "row_end_concrete": rb.get("row_end_concrete", 0),
            "source_module": rb.get("source_module", ""),
            "variable_stencil": rb.get("variable_stencil", []),
            "matrix_blocks": rb.get("matrix_blocks", []),
            "rhs_block": rb.get("rhs_block", {}),
            "row_layout": rb.get("row_layout", {}),
            "template_reference": rb.get("template_reference", {}),
            "epigraph_columns_are_zero": var_ext["dim_y"] > var_ext["dim_z"],
        })

    return row_blocks


def _dim_y_symbolic(var_ext: Dict[str, Any]) -> str:
    """生成 dim_y 的符号表达式。"""
    orig = var_ext.get("original_blocks", [])
    epi = var_ext.get("epigraph_blocks", [])

    parts = []
    for b in orig:
        if b.dimension_symbolic:
            parts.append(b.dimension_symbolic)
    for b in epi:
        parts.append("1")

    return " + ".join(parts) if parts else "0"
