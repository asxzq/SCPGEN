"""
输出构建器 — 将 EcosCanonicalIR 转换为 YAML-ready dict

生成 ecos_canonical_module5_output.yaml 的完整结构。
不包含 assumptions / boundary_constraints / path_constraints / ECOS 调用。
"""

from __future__ import annotations

from typing import Dict, List, Any


def build(
    m4_ir: Dict[str, Any],
    var_ext: Dict[str, Any],
    obj_info: Dict[str, Any],
    eq_info: Dict[str, Any],
    ineq_info: Dict[str, Any],
    cone_info: Dict[str, Any],
    assembly_plan: Dict[str, Any],
    source_path: str = "",
) -> Dict[str, Any]:
    """构建完整的 ecos_canonical_module5_output.yaml dict。

    Args:
        m4_ir: Module 4 subproblem IR dict
        var_ext: variable_extender 的输出
        obj_info: objective_canonicalizer 的输出
        eq_info: equality_canonicalizer 的输出
        ineq_info: inequality_canonicalizer 的输出
        cone_info: cone_canonicalizer 的输出
        assembly_plan: matrix_plan_builder 的输出
        source_path: Module 4 输入文件路径

    Returns:
        完整的输出 dict
    """
    output: Dict[str, Any] = {}

    output["module"] = _build_module_meta()
    output["source_module"] = _build_source_module(source_path)
    output["problem"] = _build_problem(m4_ir, var_ext)
    output["symbol_table"] = m4_ir.get("symbol_table", {})
    output["variable_registry"] = _build_variable_registry(var_ext)
    output["objective"] = _build_objective(obj_info, var_ext)
    output["equalities"] = eq_info
    output["cones"] = cone_info
    output["inequalities"] = _build_inequalities_section(ineq_info, cone_info, var_ext)
    output["ecos_problem"] = _build_ecos_problem(var_ext, eq_info, ineq_info, cone_info)
    output["matrix_assembly_plan"] = assembly_plan
    output["debug_summary"] = _build_debug_summary(
        m4_ir, var_ext, obj_info, eq_info, ineq_info, cone_info
    )
    output["module6_contract"] = _build_module6_contract()

    # 确保禁止字段不存在
    for forbidden in [
        "assumptions",
        "boundary_constraints",
        "path_constraints",
    ]:
        output.pop(forbidden, None)

    return output


def _build_module_meta() -> Dict[str, Any]:
    return {
        "name": "ecos_canonicalizer",
        "version": 1,
        "description": (
            "ECOS canonical IR + matrix assembly plan generated from Module 4 subproblem IR. "
            "No ECOS calls. No C code generation. Module 6 handles CSC/array fill."
        ),
    }


def _build_source_module(source_path: str) -> Dict[str, Any]:
    return {
        "module4_subproblem_ir": source_path or "(memory)",
    }


def _build_problem(m4_ir: Dict[str, Any], var_ext: Dict[str, Any]) -> Dict[str, Any]:
    problem = m4_ir.get("problem", {})
    return {
        "problem_name": problem.get("problem_name", ""),
        "variable_mode": problem.get("variable_mode", "perturbation"),
        "source_variable_vector": "z",
        "ecos_variable_vector": "y",
        "dim_z": var_ext["dim_z"],
        "dim_y": var_ext["dim_y"],
        "mesh": problem.get("mesh", {}),
    }


def _build_variable_registry(var_ext: Dict[str, Any]) -> Dict[str, Any]:
    """构建变量注册表。"""
    original = var_ext.get("original_blocks", [])
    epigraph = var_ext.get("epigraph_blocks", [])
    ecos = var_ext.get("ecos_blocks", [])

    def _serialize_block(b, in_original_z=True):
        return {
            "name": b.name,
            "role": b.role,
            "source_module": b.source_module,
            "domain": b.domain,
            "dimension_concrete": b.dimension_concrete,
            "dimension_symbolic": b.dimension_symbolic,
            "column_start_concrete": b.column_start_concrete,
            "column_end_concrete": b.column_end_concrete,
            "in_original_z": b.in_original_z,
        }

    return {
        "original_variables": {
            "description": "Module 4 原始优化变量 (z 向量)",
            "blocks": [_serialize_block(b) for b in original],
            "total_dimension": var_ext["dim_z"],
        },
        "added_variables": {
            "description": "Module 5 新增变量 (epigraph 变量等)",
            "epigraph_variables": [_serialize_block(b) for b in epigraph],
            "total_dimension": sum(b.dimension_concrete for b in epigraph),
        },
        "ecos_variables": {
            "description": "ECOS 优化变量向量 y = [z; epigraph_vars]",
            "blocks": [_serialize_block(b) for b in ecos],
            "total_dimension_concrete": var_ext["dim_y"],
        },
    }


def _build_objective(
    obj_info: Dict[str, Any],
    var_ext: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "form": "c^T y",
        "c_dimension_concrete": var_ext["dim_y"],
        "linear_terms": obj_info.get("linear_terms", []),
        "quadratic_terms_canonicalized": obj_info.get("quadratic_terms_canonicalized", []),
        "objective_vector_plan": obj_info.get("objective_vector_plan", {"entries": []}),
    }


def _build_inequalities_section(
    ineq_info: Dict[str, Any],
    cone_info: Dict[str, Any],
    var_ext: Dict[str, Any],
) -> Dict[str, Any]:
    """构建不等式部分（含锥体感知行排序）。

    G 矩阵层面不再声明 epigraph_columns_are_zero，
    因为 SOC rows 对 epigraph 列有非零项。
    改为 row-block 级别：linear_inequality_epigraph_columns_are_zero。
    """
    linear = cone_info.get("linear", {})
    soc = cone_info.get("second_order", {})

    dim_l = linear.get("dim_l", 0)
    q_dims = [qb["dim"] for qb in soc.get("q", [])]
    total_rows = dim_l + sum(q_dims)

    return {
        "form": "G * y + s = h",
        "G_shape_concrete": [total_rows, var_ext["dim_y"]],
        "h_shape_concrete": [total_rows],
        "has_epigraph_columns": var_ext["dim_y"] > var_ext["dim_z"],
        "row_order": {
            "description": "G/h 行排序: 线性锥行在前, SOC 行在后",
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
        },
        "source_blocks": ineq_info.get("source_blocks", []),
    }


def _build_ecos_problem(
    var_ext: Dict[str, Any],
    eq_info: Dict[str, Any],
    ineq_info: Dict[str, Any],
    cone_info: Dict[str, Any],
) -> Dict[str, Any]:
    """构建 ecos_problem 部分（ECOS 标准形式 + 维度）。"""
    linear = cone_info.get("linear", {})
    soc = cone_info.get("second_order", {})

    n = var_ext["dim_y"]
    p = eq_info.get("A_shape_concrete", [0, 0])[0]
    l = linear.get("dim_l", 0)
    q = [qb["dim"] for qb in soc.get("q", [])]
    m = l + sum(q)

    return {
        "form": {
            "minimize": "c^T y",
            "subject_to": [
                "A * y = b",
                "G * y + s = h",
                "s in K",
            ],
            "K_description": f"K = R_+^{l} × " + " × ".join(
                [f"Q_{{{qb['dim']}}}" for qb in soc.get("q", [])]
            ) if q else f"K = R_+^{l}",
        },
        "dimensions": {
            "n": n,
            "n_description": "ECOS 优化变量 y 的总维度",
            "p": p,
            "p_description": "等式约束行数 (A y = b)",
            "m": m,
            "m_description": "锥约束总行数 (G y + s = h, s ∈ K)",
            "l": l,
            "l_description": "非负正交锥 R_+^l 维度（线性不等式行数）",
            "q": q,
            "q_description": "二阶锥维度列表（每个二次代价项对应一个 SOC）",
        },
    }


def _build_debug_summary(
    m4_ir: Dict[str, Any],
    var_ext: Dict[str, Any],
    obj_info: Dict[str, Any],
    eq_info: Dict[str, Any],
    ineq_info: Dict[str, Any],
    cone_info: Dict[str, Any],
) -> Dict[str, Any]:
    """构建调试摘要。"""
    m4_debug = m4_ir.get("debug_summary", {})

    linear = cone_info.get("linear", {})
    soc = cone_info.get("second_order", {})

    # 收集来自 objective_canonicalizer、cone_canonicalizer 和 variable_extender 的 fallback 警告
    obj_warnings = obj_info.get("warnings", [])
    cone_warnings = cone_info.get("warnings", [])
    var_warnings = var_ext.get("warnings", [])

    return {
        "source_module4_summary": m4_debug,
        "dim_z": var_ext["dim_z"],
        "dim_y": var_ext["dim_y"],
        "epigraph_variable_count": len(var_ext.get("epigraph_blocks", [])),
        "equality_rows": eq_info.get("A_shape_concrete", [0, 0])[0],
        "linear_inequality_rows": ineq_info.get("total_linear_rows", 0),
        "dim_l": linear.get("dim_l", 0),
        "soc_blocks": [
            {
                "name": sb.get("name", ""),
                "dim": sb.get("dim", 0),
            }
            for sb in soc.get("soc_blocks", [])
        ],
        "linear_cost_terms": len(obj_info.get("linear_terms", [])),
        "quadratic_cost_terms": len(obj_info.get("quadratic_terms_canonicalized", [])),
        "total_cost_terms": (
            len(obj_info.get("linear_terms", []))
            + len(obj_info.get("quadratic_terms_canonicalized", []))
        ),
        "warnings": obj_warnings + cone_warnings + var_warnings,
    }


def _build_module6_contract() -> Dict[str, Any]:
    """构建 Module6 使用契约文档。

    定义 Module6（C 代码生成器）读取 Module5 输出时必须遵守的规则。
    """
    return {
        "description": "Module6 读取 Module5 输出时的数据契约",
        "rules": {
            "row_range": {
                "primary_field": "row_range_exclusive",
                "semantics": "半开区间 [start, end_exclusive)，dim_l=0 时值为 null",
                "debug_fields": [
                    "row_start_concrete: 行起始索引（inclusive），仅供调试",
                    "row_end_concrete: 行结束索引（inclusive），仅供调试",
                ],
                "note": (
                    "遍历 G/h 行范围时统一使用 row_range_exclusive，"
                    "row_start_concrete/row_end_concrete 仅作为调试字段，保持 inclusive 语义。"
                ),
            },
            "c_vector_fill": {
                "primary_source": "objective.objective_vector_plan.entries",
                "forbidden_source": "objective.quadratic_terms_canonicalized",
                "rule": (
                    "填 c 向量时只依赖 objective.objective_vector_plan.entries，"
                    "不再读取 quadratic_terms_canonicalized 来填 c。"
                    "每个 entry 包含 coefficient、variable_column_start、variable_column_end。"
                ),
            },
            "epigraph_columns": {
                "declaration_location": "matrix_assembly_plan.inequality_assembly.row_order[*].epigraph_columns_are_zero",
                "rule": (
                    "SOC row block 声明 epigraph_columns_are_zero=false，"
                    "epigraph_columns_have_nonzeros=true。"
                    "普通线性行 block 声明 epigraph_columns_are_zero=true。"
                ),
            },
        },
    }
