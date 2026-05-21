"""Module 5 example data — 最小化 Module 4 风格 IR 构造工厂

供测试 (tests/module5/conftest.py) 和脚本 (scripts/run_module5_minimal.py) 共用。
这些函数生成的是 Module 4 风格的 subproblem IR dict，可直接传给 run_module5(_m4_dict=...).
"""

from __future__ import annotations

from typing import Dict, Any


# ═══════════════════════════════════════════════════════════════
# 最小化 Module 4 风格 IR — 仅线性代价 (split_nonnegative VC, L1 penalty)
# ═══════════════════════════════════════════════════════════════

def make_minimal_m4_ir_linear() -> Dict[str, Any]:
    """构造最小化 Module 4 风格 IR，仅包含线性代价项。

    - perturbation mode, fixed_time
    - N=10, nx=1, nu=1
    - split_nonnegative VC (vc_plus, vc_minus) with L1 penalty
    - 无二次代价 → 无 epigraph 变量
    - 1 个等式块 (dynamics), 2 个不等式块 (1 original + 2 domain)
    """
    N = 10
    n_intervals = N - 1
    nx = 1
    nu = 1

    return {
        "module": {"name": "subproblem_ir_assembler", "version": 1},
        "source_modules": {
            "module1_dynamics": {"path": "m1.yaml", "variable_mode": "perturbation"},
            "module2_equalities": {"enabled": False},
            "module3_inequalities": {"enabled": False},
        },
        "problem": {
            "problem_name": "minimal_linear_test",
            "variable_mode": "perturbation",
            "mesh": {
                "N_symbol": "N",
                "N_concrete": N,
                "nx": nx,
                "nu": nu,
                "np": 0,
                "variable_mode": "perturbation",
                "time_mode": "fixed_time",
            },
        },
        "symbol_table": {
            "states": [{"index": 0, "original_name": "x", "safe_name": "x", "internal_symbol": "x_0"}],
            "controls": [{"index": 0, "original_name": "u", "safe_name": "u", "internal_symbol": "u_0"}],
            "parameters": [],
            "auxiliaries": [],
        },
        "decision_variable_registry": {
            "blocks": [
                {
                    "name": "delta_x",
                    "role": "state_perturbation",
                    "source_module": "module1_dynamics",
                    "domain": "free",
                    "shape_symbolic": ["N", "nx"],
                    "shape_concrete": [N, nx],
                    "dimension_symbolic": "N * nx",
                    "dimension_concrete": N * nx,
                    "column_start_concrete": 0,
                    "column_end_concrete": N * nx - 1,
                    "indexing_rule": {"element": "delta_x[k,i]", "flat_index": "k*nx + i"},
                },
                {
                    "name": "delta_u",
                    "role": "control_perturbation",
                    "source_module": "module1_dynamics",
                    "domain": "free",
                    "shape_symbolic": ["N", "nu"],
                    "shape_concrete": [N, nu],
                    "dimension_symbolic": "N * nu",
                    "dimension_concrete": N * nu,
                    "column_start_concrete": N * nx,
                    "column_end_concrete": N * nx + N * nu - 1,
                    "indexing_rule": {"element": "delta_u[k,i]", "flat_index": "k*nu + i"},
                },
                {
                    "name": "vc_plus",
                    "role": "dynamics_virtual_control",
                    "source_module": "module1_dynamics",
                    "domain": "nonnegative",
                    "shape_symbolic": ["N_minus_1", "nx"],
                    "shape_concrete": [n_intervals, nx],
                    "dimension_symbolic": "(N-1) * nx",
                    "dimension_concrete": n_intervals * nx,
                    "column_start_concrete": N * nx + N * nu,
                    "column_end_concrete": N * nx + N * nu + n_intervals * nx - 1,
                    "indexing_rule": {"element": "vc_plus[k,i]", "flat_index": "k*nx + i"},
                },
                {
                    "name": "vc_minus",
                    "role": "dynamics_virtual_control",
                    "source_module": "module1_dynamics",
                    "domain": "nonnegative",
                    "shape_symbolic": ["N_minus_1", "nx"],
                    "shape_concrete": [n_intervals, nx],
                    "dimension_symbolic": "(N-1) * nx",
                    "dimension_concrete": n_intervals * nx,
                    "column_start_concrete": N * nx + N * nu + n_intervals * nx,
                    "column_end_concrete": N * nx + N * nu + 2 * n_intervals * nx - 1,
                    "indexing_rule": {"element": "vc_minus[k,i]", "flat_index": "k*nx + i"},
                },
            ],
            "total_dimension_symbolic": "N * nx + N * nu + (N-1) * nx + (N-1) * nx",
            "total_dimension_concrete": N * nx + N * nu + 2 * n_intervals * nx,
            "column_order": ["delta_x", "delta_u", "vc_plus", "vc_minus"],
        },
        "equality_constraint_registry": {
            "blocks": [
                {
                    "name": "dynamics_defect",
                    "source_module": "module1_dynamics",
                    "type": "dynamics",
                    "rows_symbolic": "(N-1) * nx",
                    "rows_concrete": n_intervals * nx,
                    "row_start_concrete": 0,
                    "row_end_concrete": n_intervals * nx - 1,
                },
            ],
            "total_rows_symbolic": "(N-1) * nx",
            "total_rows_concrete": n_intervals * nx,
        },
        "inequality_constraint_registry": {
            "blocks": [
                {
                    "name": "domain_vc_plus_nonnegative",
                    "source_module": "module1_dynamics",
                    "type": "variable_domain",
                    "rows_symbolic": "(N-1) * nx",
                    "rows_concrete": n_intervals * nx,
                    "row_start_concrete": 0,
                    "row_end_concrete": n_intervals * nx - 1,
                    "variable": "vc_plus",
                    "domain": "nonnegative",
                    "canonical_inequality": "-vc_plus <= 0",
                    "matrix_blocks": [
                        {
                            "name": "C_domain",
                            "variable_block": "vc_plus",
                            "coefficient_value": "-I",
                            "shape": [n_intervals * nx, n_intervals * nx],
                            "structure": "negative_identity",
                            "is_diagonal": True,
                        },
                    ],
                    "rhs_block": {"name": "zero", "value": 0},
                    "row_layout": {"loop_order": ["flat_variable_index"], "rows_per_variable": 1},
                    "template_reference": {},
                },
                {
                    "name": "domain_vc_minus_nonnegative",
                    "source_module": "module1_dynamics",
                    "type": "variable_domain",
                    "rows_symbolic": "(N-1) * nx",
                    "rows_concrete": n_intervals * nx,
                    "row_start_concrete": n_intervals * nx,
                    "row_end_concrete": 2 * n_intervals * nx - 1,
                    "variable": "vc_minus",
                    "domain": "nonnegative",
                    "canonical_inequality": "-vc_minus <= 0",
                    "matrix_blocks": [
                        {
                            "name": "C_domain",
                            "variable_block": "vc_minus",
                            "coefficient_value": "-I",
                            "shape": [n_intervals * nx, n_intervals * nx],
                            "structure": "negative_identity",
                            "is_diagonal": True,
                        },
                    ],
                    "rhs_block": {"name": "zero", "value": 0},
                    "row_layout": {"loop_order": ["flat_variable_index"], "rows_per_variable": 1},
                    "template_reference": {},
                },
            ],
            "total_rows_symbolic": "(N-1) * nx + (N-1) * nx",
            "total_rows_concrete": 2 * n_intervals * nx,
        },
        "introduced_variables": {"by_module1": [], "by_module2": [], "by_module3": [], "merged": []},
        "cost_terms": {
            "by_module1": [
                {
                    "name": "virtual_control_l1_penalty",
                    "type": "linear",
                    "expression_ascii": "rho_vc * sum(vc_plus + vc_minus)",
                    "generated_by": "module1_dynamics",
                    "source_module": "module1_dynamics",
                    "_vc_form": "split_nonnegative",
                },
            ],
            "by_module2": [],
            "by_module3": [],
            "merged": [
                {
                    "name": "virtual_control_l1_penalty",
                    "source_module": "module1_dynamics",
                    "type": "linear",
                    "coefficient": "rho_vc",
                    "expression_template": "rho_vc * sum(vc_plus + vc_minus)",
                    "variables": ["vc_plus", "vc_minus"],
                    "role": "virtual_control_penalty",
                    "metadata": {
                        "expression_ascii": "rho_vc * sum(vc_plus + vc_minus)",
                        "generated_by": "module1_dynamics",
                        "_vc_form": "split_nonnegative",
                    },
                },
            ],
        },
        "subproblem_template": {
            "variable_vector": "z",
            "equalities": {"form": "A_eq * z = b_eq", "blocks": []},
            "inequalities": {"form": "G_ineq * z <= h_ineq", "blocks": []},
            "cost": {"linear_terms": [], "quadratic_terms": [], "other_terms": []},
        },
        "matrix_assembly_plan": {
            "equality": {
                "matrix_name": "A_eq",
                "rhs_name": "b_eq",
                "row_blocks": [
                    {
                        "name": "dynamics_defect",
                        "row_start_concrete": 0,
                        "row_end_concrete": n_intervals * nx - 1,
                        "source_module": "module1_dynamics",
                        "variable_stencil": ["delta_x[k]", "delta_u[k]", "delta_x[k+1]", "delta_u[k+1]", "vc_plus[k]", "vc_minus[k]"],
                        "matrix_blocks": [],
                        "rhs_block": {},
                        "row_layout": {},
                        "template_reference": {},
                    },
                ],
            },
            "inequality": {
                "matrix_name": "G_ineq",
                "rhs_name": "h_ineq",
                "row_blocks": [
                    {
                        "name": "domain_vc_plus_nonnegative",
                        "row_start_concrete": 0,
                        "row_end_concrete": n_intervals * nx - 1,
                        "source_module": "module1_dynamics",
                        "type": "variable_domain",
                        "variable_stencil": ["vc_plus"],
                        "matrix_blocks": [],
                        "rhs_block": {},
                        "row_layout": {},
                        "template_reference": {},
                    },
                    {
                        "name": "domain_vc_minus_nonnegative",
                        "row_start_concrete": n_intervals * nx,
                        "row_end_concrete": 2 * n_intervals * nx - 1,
                        "source_module": "module1_dynamics",
                        "type": "variable_domain",
                        "variable_stencil": ["vc_minus"],
                        "matrix_blocks": [],
                        "rhs_block": {},
                        "row_layout": {},
                        "template_reference": {},
                    },
                ],
            },
        },
        "debug_summary": {
            "total_variable_dimension": N * nx + N * nu + 2 * n_intervals * nx,
            "total_equality_rows": n_intervals * nx,
            "total_inequality_rows": 2 * n_intervals * nx,
            "variable_block_count": 4,
            "equality_block_count": 1,
            "inequality_block_count": 2,
            "cost_term_count": 1,
        },
    }


# ═══════════════════════════════════════════════════════════════
# 最小化 Module 4 风格 IR — 二次代价 (signed VC, quadratic penalty)
# ═══════════════════════════════════════════════════════════════

def make_minimal_m4_ir_quadratic() -> Dict[str, Any]:
    """构造最小化 Module 4 风格 IR，包含二次代价项。

    - perturbation mode, fixed_time
    - N=10, nx=1, nu=1
    - signed VC (single vc) with quadratic penalty
    - 1 个二次代价 → 1 个 epigraph 变量 + 1 个 SOC block
    """
    N = 10
    n_intervals = N - 1
    nx = 1
    nu = 1

    return {
        "module": {"name": "subproblem_ir_assembler", "version": 1},
        "source_modules": {
            "module1_dynamics": {"path": "m1.yaml", "variable_mode": "perturbation"},
            "module2_equalities": {"enabled": False},
            "module3_inequalities": {"enabled": False},
        },
        "problem": {
            "problem_name": "minimal_quadratic_test",
            "variable_mode": "perturbation",
            "mesh": {
                "N_symbol": "N",
                "N_concrete": N,
                "nx": nx,
                "nu": nu,
                "np": 0,
                "variable_mode": "perturbation",
                "time_mode": "fixed_time",
            },
        },
        "symbol_table": {
            "states": [{"index": 0, "original_name": "x", "safe_name": "x", "internal_symbol": "x_0"}],
            "controls": [{"index": 0, "original_name": "u", "safe_name": "u", "internal_symbol": "u_0"}],
            "parameters": [],
            "auxiliaries": [],
        },
        "decision_variable_registry": {
            "blocks": [
                {
                    "name": "delta_x",
                    "role": "state_perturbation",
                    "source_module": "module1_dynamics",
                    "domain": "free",
                    "shape_symbolic": ["N", "nx"],
                    "shape_concrete": [N, nx],
                    "dimension_symbolic": "N * nx",
                    "dimension_concrete": N * nx,
                    "column_start_concrete": 0,
                    "column_end_concrete": N * nx - 1,
                    "indexing_rule": {"element": "delta_x[k,i]", "flat_index": "k*nx + i"},
                },
                {
                    "name": "delta_u",
                    "role": "control_perturbation",
                    "source_module": "module1_dynamics",
                    "domain": "free",
                    "shape_symbolic": ["N", "nu"],
                    "shape_concrete": [N, nu],
                    "dimension_symbolic": "N * nu",
                    "dimension_concrete": N * nu,
                    "column_start_concrete": N * nx,
                    "column_end_concrete": N * nx + N * nu - 1,
                    "indexing_rule": {"element": "delta_u[k,i]", "flat_index": "k*nu + i"},
                },
                {
                    "name": "vc",
                    "role": "dynamics_virtual_control",
                    "source_module": "module1_dynamics",
                    "domain": "free",
                    "shape_symbolic": ["N_minus_1", "nx"],
                    "shape_concrete": [n_intervals, nx],
                    "dimension_symbolic": "(N-1) * nx",
                    "dimension_concrete": n_intervals * nx,
                    "column_start_concrete": N * nx + N * nu,
                    "column_end_concrete": N * nx + N * nu + n_intervals * nx - 1,
                    "indexing_rule": {"element": "vc[k,i]", "flat_index": "k*nx + i"},
                },
            ],
            "total_dimension_symbolic": "N * nx + N * nu + (N-1) * nx",
            "total_dimension_concrete": N * nx + N * nu + n_intervals * nx,
            "column_order": ["delta_x", "delta_u", "vc"],
        },
        "equality_constraint_registry": {
            "blocks": [
                {
                    "name": "dynamics_defect",
                    "source_module": "module1_dynamics",
                    "type": "dynamics",
                    "rows_symbolic": "(N-1) * nx",
                    "rows_concrete": n_intervals * nx,
                    "row_start_concrete": 0,
                    "row_end_concrete": n_intervals * nx - 1,
                },
            ],
            "total_rows_symbolic": "(N-1) * nx",
            "total_rows_concrete": n_intervals * nx,
        },
        "inequality_constraint_registry": {
            "blocks": [],
            "total_rows_symbolic": "0",
            "total_rows_concrete": 0,
        },
        "introduced_variables": {"by_module1": [], "by_module2": [], "by_module3": [], "merged": []},
        "cost_terms": {
            "by_module1": [
                {
                    "name": "virtual_control_quadratic_penalty",
                    "type": "quadratic",
                    "expression_ascii": "0.5 * rho_vc * sum_squares(vc)",
                    "generated_by": "module1_dynamics",
                    "source_module": "module1_dynamics",
                },
            ],
            "by_module2": [],
            "by_module3": [],
            "merged": [
                {
                    "name": "virtual_control_quadratic_penalty",
                    "source_module": "module1_dynamics",
                    "type": "quadratic",
                    "weight_symbol": "rho_vc",
                    "norm_variable": "vc",
                    "quadratic_form_type": "sum_squares",
                    "expression_template": "0.5 * rho_vc * sum_squares(vc)",
                    "variables": ["vc"],
                    "role": "virtual_control_penalty",
                    "metadata": {
                        "expression_ascii": "0.5 * rho_vc * sum_squares(vc)",
                        "generated_by": "module1_dynamics",
                    },
                },
            ],
        },
        "subproblem_template": {
            "variable_vector": "z",
            "equalities": {"form": "A_eq * z = b_eq", "blocks": []},
            "inequalities": {"form": "G_ineq * z <= h_ineq", "blocks": []},
            "cost": {"linear_terms": [], "quadratic_terms": [], "other_terms": []},
        },
        "matrix_assembly_plan": {
            "equality": {
                "matrix_name": "A_eq",
                "rhs_name": "b_eq",
                "row_blocks": [
                    {
                        "name": "dynamics_defect",
                        "row_start_concrete": 0,
                        "row_end_concrete": n_intervals * nx - 1,
                        "source_module": "module1_dynamics",
                        "variable_stencil": ["delta_x[k]", "delta_u[k]", "delta_x[k+1]", "delta_u[k+1]", "vc[k]"],
                        "matrix_blocks": [],
                        "rhs_block": {},
                        "row_layout": {},
                        "template_reference": {},
                    },
                ],
            },
            "inequality": {
                "matrix_name": "G_ineq",
                "rhs_name": "h_ineq",
                "row_blocks": [],
            },
        },
        "debug_summary": {
            "total_variable_dimension": N * nx + N * nu + n_intervals * nx,
            "total_equality_rows": n_intervals * nx,
            "total_inequality_rows": 0,
            "variable_block_count": 3,
            "equality_block_count": 1,
            "inequality_block_count": 0,
            "cost_term_count": 1,
        },
    }


# ═══════════════════════════════════════════════════════════════
# 最小化 Module 4 风格 IR — 多个代价项 (linear + quadratic)
# ═══════════════════════════════════════════════════════════════

def make_minimal_m4_ir_multi_cost():
    """构造最小化 Module 4 风格 IR，包含多个代价项（线性 + 二次）。

    模拟同时有 M1 虚拟控制 L1 惩罚和 M3 松弛 L1 惩罚的场景。
    """
    N = 10
    n_intervals = N - 1
    nx = 1
    nu = 1

    return {
        "module": {"name": "subproblem_ir_assembler", "version": 1},
        "source_modules": {
            "module1_dynamics": {"path": "m1.yaml", "variable_mode": "perturbation"},
            "module2_equalities": {"enabled": False},
            "module3_inequalities": {"enabled": True},
        },
        "problem": {
            "problem_name": "minimal_multi_cost_test",
            "variable_mode": "perturbation",
            "mesh": {
                "N_symbol": "N",
                "N_concrete": N,
                "nx": nx,
                "nu": nu,
                "np": 0,
                "variable_mode": "perturbation",
                "time_mode": "fixed_time",
            },
        },
        "symbol_table": {
            "states": [{"index": 0, "original_name": "x", "safe_name": "x", "internal_symbol": "x_0"}],
            "controls": [{"index": 0, "original_name": "u", "safe_name": "u", "internal_symbol": "u_0"}],
            "parameters": [],
            "auxiliaries": [],
        },
        "decision_variable_registry": {
            "blocks": [
                {
                    "name": "delta_x", "role": "state_perturbation",
                    "source_module": "module1_dynamics", "domain": "free",
                    "shape_concrete": [N, nx], "dimension_symbolic": "N * nx",
                    "dimension_concrete": N * nx, "column_start_concrete": 0,
                    "column_end_concrete": N * nx - 1,
                    "indexing_rule": {},
                },
                {
                    "name": "delta_u", "role": "control_perturbation",
                    "source_module": "module1_dynamics", "domain": "free",
                    "shape_concrete": [N, nu], "dimension_symbolic": "N * nu",
                    "dimension_concrete": N * nu, "column_start_concrete": N * nx,
                    "column_end_concrete": N * nx + N * nu - 1,
                    "indexing_rule": {},
                },
                {
                    "name": "vc", "role": "dynamics_virtual_control",
                    "source_module": "module1_dynamics", "domain": "free",
                    "shape_concrete": [n_intervals, nx], "dimension_symbolic": "(N-1) * nx",
                    "dimension_concrete": n_intervals * nx,
                    "column_start_concrete": N * nx + N * nu,
                    "column_end_concrete": N * nx + N * nu + n_intervals * nx - 1,
                    "indexing_rule": {},
                },
                {
                    "name": "s_heat_rate", "role": "inequality_slack",
                    "source_module": "module3_inequalities", "domain": "nonnegative",
                    "shape_concrete": [N, 1], "dimension_symbolic": "N",
                    "dimension_concrete": N,
                    "column_start_concrete": N * nx + N * nu + n_intervals * nx,
                    "column_end_concrete": N * nx + N * nu + n_intervals * nx + N - 1,
                    "indexing_rule": {},
                },
            ],
            "total_dimension_concrete": N * nx + N * nu + n_intervals * nx + N,
            "column_order": ["delta_x", "delta_u", "vc", "s_heat_rate"],
        },
        "equality_constraint_registry": {
            "blocks": [
                {
                    "name": "dynamics_defect", "source_module": "module1_dynamics",
                    "type": "dynamics", "rows_concrete": n_intervals * nx,
                    "row_start_concrete": 0, "row_end_concrete": n_intervals * nx - 1,
                },
            ],
            "total_rows_concrete": n_intervals * nx,
        },
        "inequality_constraint_registry": {
            "blocks": [
                {
                    "name": "domain_s_heat_rate_nonnegative",
                    "source_module": "module3_inequalities", "type": "variable_domain",
                    "rows_concrete": N, "row_start_concrete": 0, "row_end_concrete": N - 1,
                    "variable": "s_heat_rate", "domain": "nonnegative",
                    "canonical_inequality": "-s_heat_rate <= 0",
                    "matrix_blocks": [], "rhs_block": {}, "row_layout": {},
                    "template_reference": {},
                },
            ],
            "total_rows_concrete": N,
        },
        "introduced_variables": {"by_module1": [], "by_module2": [], "by_module3": [], "merged": []},
        "cost_terms": {
            "by_module1": [
                {"name": "virtual_control_quadratic_penalty", "type": "quadratic",
                 "expression_ascii": "0.5 * rho_vc * sum_squares(vc)",
                 "generated_by": "module1_dynamics", "source_module": "module1_dynamics"},
            ],
            "by_module2": [],
            "by_module3": [
                {"name": "slack_l1_penalty_heat_rate", "type": "linear",
                 "expression_ascii": "rho_heat * sum(s_heat_rate)",
                 "generated_by": "module3_inequalities", "source_module": "module3_inequalities"},
            ],
            "merged": [
                {
                    "name": "virtual_control_quadratic_penalty",
                    "source_module": "module1_dynamics", "type": "quadratic",
                    "weight_symbol": "rho_vc",
                    "norm_variable": "vc",
                    "quadratic_form_type": "sum_squares",
                    "expression_template": "0.5 * rho_vc * sum_squares(vc)",
                    "variables": ["vc"], "role": "virtual_control_penalty",
                    "metadata": {},
                },
                {
                    "name": "slack_l1_penalty_heat_rate",
                    "source_module": "module3_inequalities", "type": "linear",
                    "coefficient": "rho_heat",
                    "expression_template": "rho_heat * sum(s_heat_rate)",
                    "variables": ["s_heat_rate"], "role": "slack_penalty",
                    "metadata": {},
                },
            ],
        },
        "subproblem_template": {
            "variable_vector": "z",
            "equalities": {"form": "A_eq * z = b_eq", "blocks": []},
            "inequalities": {"form": "G_ineq * z <= h_ineq", "blocks": []},
            "cost": {"linear_terms": [], "quadratic_terms": [], "other_terms": []},
        },
        "matrix_assembly_plan": {
            "equality": {
                "matrix_name": "A_eq", "rhs_name": "b_eq",
                "row_blocks": [
                    {"name": "dynamics_defect", "row_start_concrete": 0,
                     "row_end_concrete": n_intervals * nx - 1,
                     "source_module": "module1_dynamics", "variable_stencil": [],
                     "matrix_blocks": [], "rhs_block": {}, "row_layout": {}, "template_reference": {}},
                ],
            },
            "inequality": {
                "matrix_name": "G_ineq", "rhs_name": "h_ineq",
                "row_blocks": [
                    {"name": "domain_s_heat_rate_nonnegative", "row_start_concrete": 0,
                     "row_end_concrete": N - 1, "source_module": "module3_inequalities",
                     "type": "variable_domain", "variable_stencil": [],
                     "matrix_blocks": [], "rhs_block": {}, "row_layout": {}, "template_reference": {}},
                ],
            },
        },
        "debug_summary": {
            "total_variable_dimension": N * nx + N * nu + n_intervals * nx + N,
            "total_equality_rows": n_intervals * nx,
            "total_inequality_rows": N,
            "variable_block_count": 4,
            "cost_term_count": 2,
        },
    }
