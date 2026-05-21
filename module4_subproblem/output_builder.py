"""
输出构建器 — 将 SubproblemIR 转换为 YAML-ready dict

不包含 assumptions / boundary_constraints / path_constraints / ECOS canonical form。
"""

from __future__ import annotations

from typing import Dict, List, Any

from .models import SubproblemIR, VariableBlock, EqualityBlock, InequalityBlock


def build(ir: SubproblemIR) -> Dict[str, Any]:
    """构建完整的 subproblem_ir_module4_output.yaml dict"""

    output: Dict[str, Any] = {}

    output["module"] = _build_module_meta()
    output["source_modules"] = _build_source_modules(ir)
    output["problem"] = _build_problem(ir)
    output["symbol_table"] = ir.symbol_table
    output["decision_variable_registry"] = _build_variable_registry(ir)
    output["equality_constraint_registry"] = _build_equality_registry(ir)
    output["inequality_constraint_registry"] = _build_inequality_registry(ir)
    output["introduced_variables"] = ir.introduced_variables
    output["cost_terms"] = ir.cost_terms
    output["subproblem_template"] = _build_subproblem_template(ir)
    output["matrix_assembly_plan"] = _build_matrix_assembly_plan(ir)
    output["debug_summary"] = ir.debug_summary

    # 确保禁止字段不存在
    for forbidden in ["assumptions", "boundary_constraints", "path_constraints"]:
        output.pop(forbidden, None)

    return output


def _build_module_meta() -> Dict[str, Any]:
    return {
        "name": "subproblem_ir_assembler",
        "version": 1,
        "description": (
            "Solver-agnostic subproblem IR assembled from Module 1/2/3 outputs. "
            "No ECOS canonicalization. No C code generation."
        ),
    }


def _build_source_modules(ir: SubproblemIR) -> Dict[str, Any]:
    return ir.source_modules


def _build_problem(ir: SubproblemIR) -> Dict[str, Any]:
    return {
        "problem_name": ir.problem_name,
        "variable_mode": ir.variable_mode,
        "mesh": ir.mesh,
    }


def _build_variable_registry(ir: SubproblemIR) -> Dict[str, Any]:
    blocks = []
    for vb in ir.variable_blocks:
        blocks.append({
            "name": vb.name,
            "role": vb.role,
            "source_module": vb.source_module,
            "domain": vb.domain,
            "shape_symbolic": vb.shape_symbolic,
            "shape_concrete": vb.shape_concrete,
            "dimension_symbolic": vb.dimension_symbolic,
            "dimension_concrete": vb.dimension_concrete,
            "column_start_concrete": vb.column_start_concrete,
            "column_end_concrete": vb.column_end_concrete,
            "indexing_rule": vb.indexing_rule,
        })

    total_dim = sum(vb.dimension_concrete for vb in ir.variable_blocks)
    total_dim_sym = _format_total_dim_symbolic(ir.variable_blocks)

    return {
        "blocks": blocks,
        "total_dimension_symbolic": total_dim_sym,
        "total_dimension_concrete": total_dim,
        "column_order": [vb.name for vb in ir.variable_blocks],
    }


def _format_total_dim_symbolic(blocks: List[VariableBlock]) -> str:
    """生成总维度的符号表达式"""
    parts = []
    for vb in blocks:
        if vb.dimension_symbolic:
            parts.append(vb.dimension_symbolic)
    return " + ".join(parts) if parts else "0"


def _build_equality_registry(ir: SubproblemIR) -> Dict[str, Any]:
    blocks = []
    for eb in ir.equality_blocks:
        entry: Dict[str, Any] = {
            "name": eb.name,
            "source_module": eb.source_module,
            "type": eb.type,
            "rows_symbolic": eb.rows_symbolic,
            "rows_concrete": eb.rows_concrete,
            "row_start_concrete": eb.row_start_concrete,
            "row_end_concrete": eb.row_end_concrete,
        }
        if eb.variable_stencil:
            entry["variable_stencil"] = eb.variable_stencil
        if eb.matrix_blocks:
            entry["matrix_blocks"] = eb.matrix_blocks
        if eb.rhs_block:
            entry["rhs_block"] = eb.rhs_block
        if eb.row_layout:
            entry["row_layout"] = eb.row_layout
        if eb.template_reference:
            entry["template_reference"] = eb.template_reference
        blocks.append(entry)

    total_rows = sum(eb.rows_concrete for eb in ir.equality_blocks)

    return {
        "blocks": blocks,
        "total_rows_symbolic": _format_total_rows_symbolic(ir.equality_blocks),
        "total_rows_concrete": total_rows,
        "row_order": [eb.name for eb in ir.equality_blocks],
    }


def _build_inequality_registry(ir: SubproblemIR) -> Dict[str, Any]:
    blocks = []
    for ib in ir.inequality_blocks:
        entry: Dict[str, Any] = {
            "name": ib.name,
            "source_module": ib.source_module,
            "type": ib.type,
            "rows_symbolic": ib.rows_symbolic,
            "rows_concrete": ib.rows_concrete,
            "row_start_concrete": ib.row_start_concrete,
            "row_end_concrete": ib.row_end_concrete,
        }
        if ib.type == "original_inequality":
            if ib.variable_stencil:
                entry["variable_stencil"] = ib.variable_stencil
            if ib.matrix_blocks:
                entry["matrix_blocks"] = ib.matrix_blocks
            if ib.rhs_block:
                entry["rhs_block"] = ib.rhs_block
            if ib.row_layout:
                entry["row_layout"] = ib.row_layout
            if ib.template_reference:
                entry["template_reference"] = ib.template_reference
        elif ib.type == "variable_domain":
            entry["variable"] = ib.variable
            entry["domain"] = ib.domain
            entry["canonical_inequality"] = ib.canonical_inequality
            if ib.matrix_blocks:
                entry["matrix_blocks"] = ib.matrix_blocks
            if ib.rhs_block:
                entry["rhs_block"] = ib.rhs_block
            if ib.row_layout:
                entry["row_layout"] = ib.row_layout
        blocks.append(entry)

    total_rows = sum(ib.rows_concrete for ib in ir.inequality_blocks)

    return {
        "blocks": blocks,
        "total_rows_symbolic": _format_total_rows_symbolic(ir.inequality_blocks),
        "total_rows_concrete": total_rows,
        "row_order": [ib.name for ib in ir.inequality_blocks],
    }


def _format_total_rows_symbolic(blocks: List) -> str:
    """生成总行数的符号表达式"""
    parts = []
    for blk in blocks:
        if hasattr(blk, 'rows_symbolic') and blk.rows_symbolic:
            parts.append(str(blk.rows_symbolic))
    return " + ".join(parts) if parts else "0"


def _build_subproblem_template(ir: SubproblemIR) -> Dict[str, Any]:
    """构建子问题模板的结构化描述"""
    var_names = [vb.name for vb in ir.variable_blocks]

    # 等式形式
    eq_form = "A_eq * z = b_eq"
    eq_summary = []
    for eb in ir.equality_blocks:
        eq_summary.append({
            "block": eb.name,
            "rows": eb.rows_concrete,
            "contributes_to": "A_eq, b_eq",
        })

    # 不等式形式
    ineq_form = "G_ineq * z <= h_ineq"
    ineq_summary = []
    for ib in ir.inequality_blocks:
        ineq_summary.append({
            "block": ib.name,
            "rows": ib.rows_concrete,
            "contributes_to": "G_ineq, h_ineq",
        })

    # 成本项
    linear_terms = []
    quadratic_terms = []
    other_terms = []
    for ct in ir.cost_terms.get("merged", []):
        ct_type = ct.get("type", "linear")
        if ct_type == "linear":
            linear_terms.append(ct)
        elif ct_type == "quadratic":
            quadratic_terms.append(ct)
        else:
            other_terms.append(ct)

    return {
        "variable_vector": "z",
        "equalities": {
            "form": eq_form,
            "blocks": eq_summary,
        },
        "inequalities": {
            "form": ineq_form,
            "blocks": ineq_summary,
        },
        "cost": {
            "linear_terms": linear_terms,
            "quadratic_terms": quadratic_terms,
            "other_terms": other_terms,
        },
    }


def _build_matrix_assembly_plan(ir: SubproblemIR) -> Dict[str, Any]:
    """构建矩阵装配计划 — 自包含，Module 5 无需回查 registry。

    每个 equality row block 包含：
      name, row_start_concrete, row_end_concrete, source_module,
      variable_stencil, matrix_blocks, rhs_block, row_layout, template_reference

    每个 inequality row block 同理。
    """
    eq_plan = []
    for eb in ir.equality_blocks:
        entry = {
            "name": eb.name,
            "row_start_concrete": eb.row_start_concrete,
            "row_end_concrete": eb.row_end_concrete,
            "source_module": eb.source_module,
        }
        if eb.variable_stencil:
            entry["variable_stencil"] = eb.variable_stencil
        if eb.matrix_blocks:
            entry["matrix_blocks"] = eb.matrix_blocks
        if eb.rhs_block:
            entry["rhs_block"] = eb.rhs_block
        if eb.row_layout:
            entry["row_layout"] = eb.row_layout
        if eb.template_reference:
            entry["template_reference"] = eb.template_reference
        eq_plan.append(entry)

    ineq_plan = []
    for ib in ir.inequality_blocks:
        entry = {
            "name": ib.name,
            "row_start_concrete": ib.row_start_concrete,
            "row_end_concrete": ib.row_end_concrete,
            "source_module": ib.source_module,
            "type": ib.type,
        }
        if ib.type == "original_inequality":
            if ib.variable_stencil:
                entry["variable_stencil"] = ib.variable_stencil
            if ib.matrix_blocks:
                entry["matrix_blocks"] = ib.matrix_blocks
            if ib.rhs_block:
                entry["rhs_block"] = ib.rhs_block
            if ib.row_layout:
                entry["row_layout"] = ib.row_layout
            if ib.template_reference:
                entry["template_reference"] = ib.template_reference
        elif ib.type == "variable_domain":
            entry["canonical_inequality"] = ib.canonical_inequality
            if ib.variable_stencil:
                entry["variable_stencil"] = ib.variable_stencil
            if ib.matrix_blocks:
                entry["matrix_blocks"] = ib.matrix_blocks
            if ib.rhs_block:
                entry["rhs_block"] = ib.rhs_block
            if ib.row_layout:
                entry["row_layout"] = ib.row_layout
            if ib.template_reference:
                entry["template_reference"] = ib.template_reference
        ineq_plan.append(entry)

    return {
        "equality": {
            "matrix_name": "A_eq",
            "rhs_name": "b_eq",
            "row_blocks": eq_plan,
        },
        "inequality": {
            "matrix_name": "G_ineq",
            "rhs_name": "h_ineq",
            "row_blocks": ineq_plan,
        },
    }
