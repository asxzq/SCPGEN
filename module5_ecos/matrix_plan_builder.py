"""
矩阵装配计划构建器 — 构建 ECOS 矩阵装配计划

生成完整的 G/h 行排序和 SOC 装配规则，供 Module 6 用于 C 代码生成。
"""

from __future__ import annotations

from typing import Dict, List, Any


def build_assembly_plan(
    m4_ir: Dict[str, Any],
    var_ext: Dict[str, Any],
    eq_info: Dict[str, Any],
    ineq_info: Dict[str, Any],
    cone_info: Dict[str, Any],
) -> Dict[str, Any]:
    """构建完整的 ECOS 矩阵装配计划。

    Args:
        m4_ir: Module 4 subproblem IR dict
        var_ext: variable_extender 的输出
        eq_info: equality_canonicalizer 的输出
        ineq_info: inequality_canonicalizer 的输出
        cone_info: cone_canonicalizer 的输出

    Returns:
        装配计划 dict:
        {
            "equality_assembly": {...},
            "inequality_assembly": {...},
            "row_order_summary": {...},
        }
    """
    return {
        "equality_assembly": _build_equality_assembly(eq_info, var_ext),
        "inequality_assembly": _build_inequality_assembly(
            m4_ir, ineq_info, cone_info, var_ext
        ),
        "row_order_summary": _build_row_order_summary(cone_info, var_ext),
    }


def _build_equality_assembly(
    eq_info: Dict[str, Any],
    var_ext: Dict[str, Any],
) -> Dict[str, Any]:
    """构建等式矩阵装配计划。"""
    has_epigraph = var_ext["dim_y"] > var_ext["dim_z"]

    return {
        "matrix_name": "A",
        "rhs_name": "b",
        "form": "A * y = b",
        "shape_concrete": eq_info.get("A_shape_concrete", [0, 0]),
        "epigraph_columns_are_zero": has_epigraph,
        "row_blocks": eq_info.get("assembly_plan", {}).get("row_blocks", []),
    }


def _build_inequality_assembly(
    m4_ir: Dict[str, Any],
    ineq_info: Dict[str, Any],
    cone_info: Dict[str, Any],
    var_ext: Dict[str, Any],
) -> Dict[str, Any]:
    """构建不等式矩阵装配计划（含锥体感知行排序）。"""
    has_epigraph = var_ext["dim_y"] > var_ext["dim_z"]
    dim_y = var_ext["dim_y"]

    # 线性行块（来自 Module 4）
    linear_blocks = _build_linear_row_blocks(m4_ir, has_epigraph)

    # SOC 行块
    soc_blocks = _build_soc_row_blocks(cone_info, has_epigraph)

    # 总行数
    total_linear = ineq_info.get("total_linear_rows", 0)
    total_soc = sum(
        sb.get("dim", 0)
        for sb in cone_info.get("second_order", {}).get("soc_blocks", [])
    )
    total_rows = total_linear + total_soc

    return {
        "matrix_name": "G",
        "rhs_name": "h",
        "form": "G * y + s = h",
        "shape_concrete": [total_rows, dim_y],
        "has_epigraph_columns": has_epigraph,
        "row_order": [
            {
                "cone_type": "linear",
                "cone_name": "R_plus^l",
                "row_range_exclusive": [0, total_linear] if total_linear > 0 else None,  # 半开区间 [start, end_exclusive)
                "blocks": linear_blocks,
            },
        ] + [
            {
                "cone_type": "second_order",
                "cone_name": sb.get("name", ""),
                "row_range_exclusive": [sb.get("row_start_concrete", 0), sb.get("row_end_concrete", 0) + 1],  # 半开区间 [start, end_exclusive)
                "epigraph_columns_are_zero": False,
                "epigraph_columns_have_nonzeros": True,
                "soc_assembly": sb.get("soc_assembly", []),
            }
            for sb in cone_info.get("second_order", {}).get("soc_blocks", [])
        ],
    }


def _build_linear_row_blocks(
    m4_ir: Dict[str, Any],
    has_epigraph: bool,
) -> List[Dict[str, Any]]:
    """从 Module 4 构建线性不等式行块。"""
    plan = m4_ir.get("matrix_assembly_plan", {})
    ineq_plan = plan.get("inequality", {})
    m4_row_blocks = ineq_plan.get("row_blocks", [])

    blocks = []
    for rb in m4_row_blocks:
        blocks.append({
            "name": rb.get("name", ""),
            "row_start_concrete": rb.get("row_start_concrete", 0),
            "row_end_concrete": rb.get("row_end_concrete", 0),
            "source_module": rb.get("source_module", ""),
            "type": rb.get("type", ""),
            "variable_stencil": rb.get("variable_stencil", []),
            "matrix_blocks": rb.get("matrix_blocks", []),
            "rhs_block": rb.get("rhs_block", {}),
            "row_layout": rb.get("row_layout", {}),
            "template_reference": rb.get("template_reference", {}),
            "cone_type": "linear",
            "linear_inequality_epigraph_columns_are_zero": has_epigraph,
        })

    return blocks


def _build_soc_row_blocks(
    cone_info: Dict[str, Any],
    has_epigraph: bool,
) -> List[Dict[str, Any]]:
    """构建 SOC 行块。"""
    soc_info = cone_info.get("second_order", {})
    soc_blocks = soc_info.get("soc_blocks", [])

    return [
        {
            "name": sb["name"],
            "source_cost_term": sb["source_cost_term"],
            "dim": sb["dim"],
            "row_start_concrete": sb["row_start_concrete"],
            "row_end_concrete": sb["row_end_concrete"],
            "cone_type": "second_order",
            "epigraph_variable": sb["epigraph_variable"],
            "vector_variable": sb["vector_variable"],
            "rho_symbol": sb["rho_symbol"],
            "soc_assembly": sb["soc_assembly"],
        }
        for sb in soc_blocks
    ]


def _build_row_order_summary(
    cone_info: Dict[str, Any],
    var_ext: Dict[str, Any],
) -> Dict[str, Any]:
    """构建行排序摘要。"""
    linear = cone_info.get("linear", {})
    soc = cone_info.get("second_order", {})

    dim_l = linear.get("dim_l", 0)
    q_list = [qb["dim"] for qb in soc.get("q", [])]

    return {
        "description": "G/h 行排序: 线性锥行 (R₊ˡ) 在前, SOC 行 (Q) 在后",
        "linear_cone_rows": {
            "cone": "R_plus^l",
            "dim": dim_l,
            "row_range_exclusive": [0, dim_l] if dim_l > 0 else None,  # 半开区间 [start, end_exclusive)
        },
        "second_order_cone_rows": [
            {
                "cone": qb.get("name", ""),
                "dim": qb.get("dim", 0),
                "row_range_exclusive": qb.get("row_range_exclusive", [qb.get("row_start", 0), qb.get("row_end", 0) + 1]),
            }
            for qb in soc.get("q", [])
        ],
        "total_cone_rows": dim_l + sum(q_list),
    }
