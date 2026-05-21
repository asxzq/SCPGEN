"""
不等式规范化器 — 将 Module 4 的 G_ineq z <= h_ineq 转换为 ECOS 的 G y + s = h, s ∈ K
"""

from __future__ import annotations

from typing import Dict, List, Any


def canonicalize_inequalities(
    m4_ir: Dict[str, Any],
    var_ext: Dict[str, Any],
) -> Dict[str, Any]:
    """将 Module 4 不等式转换为 ECOS 形式。

    Module 4: G_ineq z <= h_ineq
    ECOS:     G y + s = h,  s ∈ K (K = R₊ˡ × Q₁ × Q₂ × ...)

    对于线性不等式，G 和 h 直接复用 Module 4 的值。
    如果 dim_y > dim_z，则 G 矩阵需要补零列。

    Args:
        m4_ir: Module 4 subproblem IR dict
        var_ext: variable_extender 的输出

    Returns:
        不等式部分 dict:
        {
            "form": "G * y + s = h",
            "G_shape_concrete": [n_rows, dim_y],
            "h_shape_concrete": [n_rows],
            "total_linear_rows": int,
            "has_epigraph_columns": bool,
            "source_blocks": [...],
        }
    """
    dim_y = var_ext["dim_y"]
    dim_z = var_ext["dim_z"]

    ineq_registry = m4_ir.get("inequality_constraint_registry", {})
    m4_blocks = ineq_registry.get("blocks", [])
    total_rows = ineq_registry.get("total_rows_concrete", 0)

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
            # variable_domain 专用
            "variable": mb.get("variable", ""),
            "domain": mb.get("domain", ""),
            "canonical_inequality": mb.get("canonical_inequality", ""),
        })

    has_epigraph = dim_y > dim_z

    return {
        "form": "G * y + s = h",
        "G_shape_concrete": [total_rows, dim_y],
        "G_shape_symbolic": [
            ineq_registry.get("total_rows_symbolic", "?"),
            _dim_y_symbolic(var_ext),
        ],
        "h_shape_concrete": [total_rows],
        "total_linear_rows": total_rows,
        "has_epigraph_columns": has_epigraph,
        "source_blocks": source_blocks,
    }


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
