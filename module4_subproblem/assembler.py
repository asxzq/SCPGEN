"""
装配器 — 编排所有注册表，生成完整的 SubproblemIR
"""

from __future__ import annotations

from typing import Dict, Any

from .models import Module4Input, SubproblemIR
from .variable_registry import build_variable_registry
from .constraint_registry import build_equality_registry, build_inequality_registry
from .cost_registry import build_cost_registry
from .input_loader import merge_symbol_table


def assemble(module_input: Module4Input) -> SubproblemIR:
    """装配完整的子问题 IR"""

    m1 = module_input.m1_output
    m2 = module_input.m2_output
    m3 = module_input.m3_output
    m2_enabled = module_input.m2_enabled
    m3_enabled = module_input.m3_enabled

    # 1. 变量注册
    var_blocks = build_variable_registry(m1, m2, m3, m2_enabled, m3_enabled)

    # 2. 等式约束注册
    eq_blocks = build_equality_registry(m1, m2, m2_enabled, var_blocks)

    # 3. 不等式约束注册
    ineq_blocks = build_inequality_registry(m3, m3_enabled, var_blocks)

    # 4. 成本项注册
    cost_terms = build_cost_registry(m1, m2, m3, m2_enabled, m3_enabled)

    # 5. 合并 symbol_table
    sym_table = merge_symbol_table(m1, m2, m3, m2_enabled, m3_enabled)

    # 6. 收集 introduced_variables
    introduced_vars = _collect_introduced_variables(m1, m2, m3, m2_enabled, m3_enabled)

    # 7. 提取 mesh 信息
    cfg = m1.get("configuration", {})
    dims = m1.get("dimensions", {}).get("concrete", {})
    mesh = {
        "N_symbol": "N",
        "N_concrete": dims.get("N", 0),
        "nx": dims.get("nx", 0),
        "nu": dims.get("nu", 0),
        "np": dims.get("np", 0),
        "variable_mode": cfg.get("variable_mode", "perturbation"),
        "time_mode": cfg.get("time_mode", "fixed_time"),
    }

    # 8. 构建 debug_summary
    total_var_dim = sum(vb.dimension_concrete for vb in var_blocks)
    total_eq_rows = sum(eb.rows_concrete for eb in eq_blocks)
    total_ineq_rows = sum(ib.rows_concrete for ib in ineq_blocks)

    debug_summary = {
        "total_variable_dimension": total_var_dim,
        "total_equality_rows": total_eq_rows,
        "total_inequality_rows": total_ineq_rows,
        "variable_block_count": len(var_blocks),
        "equality_block_count": len(eq_blocks),
        "inequality_block_count": len(ineq_blocks),
        "cost_term_count": len(cost_terms.get("merged", [])),
        "m2_enabled": m2_enabled,
        "m3_enabled": m3_enabled,
    }

    # 9. source_modules 信息
    source_modules = {
        "module1_dynamics": {
            "path": module_input.m1_path,
            "variable_mode": cfg.get("variable_mode", ""),
        },
        "module2_equalities": {
            "enabled": m2_enabled,
            "path": module_input.m2_path if m2_enabled else "",
        },
        "module3_inequalities": {
            "enabled": m3_enabled,
            "path": module_input.m3_path if m3_enabled else "",
        },
    }

    return SubproblemIR(
        problem_name=module_input.problem_name,
        variable_mode=cfg.get("variable_mode", "perturbation"),
        mesh=mesh,
        symbol_table=sym_table,
        variable_blocks=var_blocks,
        equality_blocks=eq_blocks,
        inequality_blocks=ineq_blocks,
        introduced_variables=introduced_vars,
        cost_terms=cost_terms,
        source_modules=source_modules,
        debug_summary=debug_summary,
    )


def _collect_introduced_variables(
    m1_output: Dict[str, Any],
    m2_output: Dict[str, Any],
    m3_output: Dict[str, Any],
    m2_enabled: bool,
    m3_enabled: bool,
) -> Dict[str, Any]:
    """收集所有引入的变量"""
    by_m1 = list(m1_output.get("introduced_variable_templates", []))
    by_m2 = list(m2_output.get("introduced_variables", [])) if m2_enabled and m2_output else []
    by_m3 = list(m3_output.get("introduced_variables", [])) if m3_enabled and m3_output else []

    merged = []
    seen = set()
    for iv in by_m1:
        name = iv.get("name", "")
        if name not in seen:
            merged.append(iv)
            seen.add(name)
    for iv in by_m2:
        name = iv.get("name", "")
        if name not in seen:
            merged.append(iv)
            seen.add(name)
    for iv in by_m3:
        name = iv.get("name", "")
        if name not in seen:
            merged.append(iv)
            seen.add(name)

    return {
        "by_module1": by_m1,
        "by_module2": by_m2,
        "by_module3": by_m3,
        "merged": merged,
    }
