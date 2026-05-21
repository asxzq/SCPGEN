"""
锥体规范化器 — 构建 ECOS 锥体结构 (K = R₊ˡ × Q₁ × Q₂ × ...)

ECOS 锥体:
- 非负正交锥 R₊ˡ: 对应所有线性不等式行 (l = total_linear_rows)
- 二阶锥 Q: 对应二次代价项的 SOC epigraph 约束

行排序: 线性锥行在前，SOC 行在后
"""

from __future__ import annotations

from typing import Dict, List, Any


def build_cones(
    m4_ir: Dict[str, Any],
    var_ext: Dict[str, Any],
    obj_info: Dict[str, Any],
    ineq_info: Dict[str, Any],
) -> Dict[str, Any]:
    """构建 ECOS 锥体结构。

    Args:
        m4_ir: Module 4 subproblem IR dict
        var_ext: variable_extender 的输出
        obj_info: objective_canonicalizer 的输出
        ineq_info: inequality_canonicalizer 的输出

    Returns:
        锥体部分 dict:
        {
            "linear": {"dim_l": int, "row_range_exclusive": ..., "source_blocks": [...]},
            "second_order": {"q": [...], "soc_blocks": [...]},
            "warnings": [...],
        }
    """
    warnings: List[str] = []

    # 线性锥: 所有 Module 4 的不等式行
    total_linear_rows = ineq_info.get("total_linear_rows", 0)

    if total_linear_rows > 0:
        linear_cone = {
            "dim_l": total_linear_rows,
            "row_range_exclusive": [0, total_linear_rows],  # 半开区间 [start, end_exclusive)
            "description": "非负正交锥 R₊ˡ — 对应所有线性不等式 G_ineq z <= h_ineq → s >= 0",
            "source_blocks": _build_linear_source_blocks(m4_ir),
        }
    else:
        linear_cone = {
            "dim_l": 0,
            "row_range_exclusive": None,
            "description": "无非负正交锥行 (dim_l=0)",
            "source_blocks": [],
        }

    # 二阶锥: 每个二次代价项生成一个 SOC block
    quadratic_terms = obj_info.get("quadratic_terms_canonicalized", [])
    epi_blocks = var_ext.get("epigraph_blocks", [])

    soc_blocks = []
    q_list = []

    next_row = total_linear_rows  # SOC 行从线性行之后开始

    for qt in quadratic_terms:
        source_name = qt["source_cost_term"]
        epi_var = qt["epigraph_variable"]
        rho_sym = qt.get("rho_symbol", "rho")

        # 找到对应的向量变量
        vector_var, vector_dim, vv_warning = _find_vector_variable(m4_ir, source_name)
        if vv_warning:
            warnings.append(vv_warning)

        soc_dim = vector_dim + 2  # head + tail_scaled(v) + tail_epigraph
        row_start = next_row
        row_end = next_row + soc_dim - 1

        soc_block = {
            "name": f"soc_{source_name}",
            "type": "second_order",
            "dim": soc_dim,
            "row_start_concrete": row_start,
            "row_end_concrete": row_end,
            "row_range_exclusive": [row_start, row_end + 1],  # 半开区间 [start, end_exclusive)
            "source_cost_term": source_name,
            "epigraph_variable": epi_var,
            "vector_variable": vector_var,
            "vector_dimension_concrete": vector_dim,
            "rho_symbol": rho_sym,
            "cone_expression": {
                "head": f"{epi_var} + 1",
                "tail_scaled": f"sqrt(2*{rho_sym}) * {vector_var}",
                "tail_epigraph": f"{epi_var} - 1",
            },
            "soc_assembly": _build_soc_assembly(
                epi_var, vector_var, vector_dim, rho_sym
            ),
        }

        soc_blocks.append(soc_block)
        q_list.append({
            "name": soc_block["name"],
            "dim": soc_dim,
            "row_range_exclusive": [row_start, row_end + 1],  # 半开区间
        })

        next_row = row_end + 1

    second_order = {
        "q": q_list,
        "soc_blocks": soc_blocks,
        "description": "二阶锥 Q — 每个二次代价项对应一个 SOC epigraph 约束",
    }

    return {
        "linear": linear_cone,
        "second_order": second_order,
        "warnings": warnings,
    }


def _find_vector_variable(
    m4_ir: Dict[str, Any],
    cost_term_name: str,
) -> tuple:
    """从 Module 4 IR 中查找二次代价项对应的向量变量及其维度。

    变量选择优先级：
    1. term["norm_variable"] — Module4 显式给出（优先使用）
    2. term["variables"][0] — fallback（产生 warning）

    Args:
        m4_ir: Module 4 subproblem IR dict
        cost_term_name: 代价项名称

    Returns:
        (vector_variable_name: str, vector_dimension: int, warning: str or None)
    """
    # 从 cost_terms.merged 中查找
    cost_terms = m4_ir.get("cost_terms", {})
    merged = cost_terms.get("merged", [])

    for term in merged:
        if term.get("name") == cost_term_name:
            # 优先使用 norm_variable
            norm_var = term.get("norm_variable")
            variables = term.get("variables", [])

            if norm_var:
                var_name = norm_var
                warning = None
            elif variables:
                var_name = variables[0]
                warning = (
                    f"[fallback] 二次代价项 '{cost_term_name}' 缺少显式 'norm_variable' 字段，"
                    f"使用 variables[0]='{var_name}'。"
                    f"请 Module4 cost_terms.merged 中提供 'norm_variable' 字段。"
                )
            else:
                return "unknown", 0, (
                    f"二次代价项 '{cost_term_name}' 没有 variables 也没有 norm_variable"
                )

            # 查找变量维度
            dvr = m4_ir.get("decision_variable_registry", {})
            for vb in dvr.get("blocks", []):
                if vb["name"] == var_name:
                    return var_name, vb.get("dimension_concrete", 0), warning
            # 也可能在 introduced_variables 中
            iv = m4_ir.get("introduced_variables", {})
            for module_key in ["by_module1", "by_module2", "by_module3"]:
                for v in iv.get(module_key, []):
                    if v.get("name") == var_name:
                        shape = v.get("shape_concrete", [1])
                        dim = 1
                        for s in shape:
                            dim *= s
                        return var_name, dim, warning
            return var_name, 0, warning

    return "unknown", 0, (
        f"二次代价项 '{cost_term_name}' 在 cost_terms.merged 中未找到"
    )


def _build_soc_assembly(
    epi_var: str,
    vector_var: str,
    vector_dim: int,
    rho_sym: str,
) -> List[Dict[str, Any]]:
    """构造 SOC 块的 G 矩阵装配规则。

    ECOS 形式: s = h - G y,  s ∈ Q
    其中 s = [t+1; sqrt(2ρ)*v; t-1]

    Row 0 (head):
        s₀ = t + 1 = 1 - (-t)  →  h₀ = 1,  G₀[t] = -1
    Rows 1..dim_v (tail_scaled):
        sᵢ = sqrt(2ρ) * vᵢ = 0 - (-sqrt(2ρ)*vᵢ)  →  hᵢ = 0,  Gᵢ[vᵢ] = -sqrt(2ρ)
    Row last (tail_epigraph):
        s_last = t - 1 = -1 - (-t)  →  h_last = -1,  G_last[t] = -1
    """
    return [
        {
            "role": "head",
            "local_row": 0,
            "h_value": 1,
            "entries": [
                {
                    "variable": epi_var,
                    "coefficient_in_G": -1,
                },
            ],
        },
        {
            "role": "tail_scaled_variable",
            "local_row_start": 1,
            "local_row_end": vector_dim,
            "h_value": 0,
            "repeated_for": f"{vector_var} elements (dim={vector_dim})",
            "entries": [
                {
                    "variable_block": vector_var,
                    "coefficient_in_G": f"-sqrt(2*{rho_sym})",
                },
            ],
        },
        {
            "role": "tail_epigraph_shift",
            "local_row": vector_dim + 1,
            "h_value": -1,
            "entries": [
                {
                    "variable": epi_var,
                    "coefficient_in_G": -1,
                },
            ],
        },
    ]


def _build_linear_source_blocks(m4_ir: Dict[str, Any]) -> List[Dict[str, Any]]:
    """构建线性锥的源块列表。"""
    ineq_registry = m4_ir.get("inequality_constraint_registry", {})
    blocks = ineq_registry.get("blocks", [])

    source = []
    for b in blocks:
        source.append({
            "name": b["name"],
            "source_module": b.get("source_module", ""),
            "type": b.get("type", ""),
            "rows_concrete": b.get("rows_concrete", 0),
            "row_start_concrete": b.get("row_start_concrete", 0),
            "row_end_concrete": b.get("row_end_concrete", 0),
        })

    return source
