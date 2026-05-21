"""输出构建器 — 组装完整的 equality_module2_output YAML dict

按用户说明书第九节组装所有字段。
不包含 assumptions / boundary_constraints / path_constraints 字段。
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional

from .models import Module2InputDef, EqualityConstraintDef
from .symengine import EqualitySymEngine
from .formula_generator import EqualityFormulaGenerator, EqualityCaseFormula


# ── 辅助：计算行数信息 ────────────────────────────────────────────

def _compute_row_info(mi: "Module2InputDef", c: "EqualityConstraintDef") -> Dict[str, Any]:
    """根据 apply_to_normalized 计算结构化行数信息"""
    at = c.apply_to_normalized
    nodes_sym = at.get("nodes_symbolic", [])
    nodes_con = at.get("nodes_concrete", [])

    if nodes_sym == "all_nodes":
        app_node_sym = "N"
        real_node_count = mi.mesh_N
        app_node_con = real_node_count
        app_node_ref = "mesh.N"
    else:
        app_node_sym = len(nodes_sym) if isinstance(nodes_sym, list) else 1
        app_node_con = len(nodes_con)
        real_node_count = app_node_con
        app_node_ref = None

    rows_per = c.scalar_count
    total_sym = f"N * {rows_per}" if nodes_sym == "all_nodes" else app_node_sym * rows_per
    total_con = real_node_count * rows_per

    return {
        "applied_node_count_symbolic": app_node_sym,
        "applied_node_count_concrete": app_node_con,
        "applied_node_count_reference": app_node_ref,
        "rows_per_node": rows_per,
        "total_rows_symbolic": total_sym,
        "total_rows_concrete": total_con,
    }


class OutputBuilder:
    """将各组件输出组装成完整的 YAML-ready dict"""

    def __init__(
        self,
        output_debug_expressions: bool = False,
        output_c_code_expressions: bool = False,
        output_latex_expressions: bool = False,
    ):
        self._debug_expr = output_debug_expressions
        self._debug_ccode = output_c_code_expressions
        self._debug_latex = output_latex_expressions

    # ── 类方法：空输出 / 报告 ─────────────────────────────────────

    @staticmethod
    def build_empty(mi: Module2InputDef, formula_gen: "EqualityFormulaGenerator") -> Dict[str, Any]:
        """生成空约束的 Module 2 输出"""
        # 构造完整 symbol_table（空约束时所有 aux 不在闭包中）
        states = []
        for i, sv in enumerate(mi.states):
            name = sv["name"] if isinstance(sv, dict) else sv.name
            safe_name = mi.name_to_safe.get(name, name)
            states.append({
                "index": i, "original_name": name, "safe_name": safe_name,
                "internal_symbol": f"x_{i}",
            })
        controls = []
        for i, cv in enumerate(mi.controls):
            name = cv["name"] if isinstance(cv, dict) else cv.name
            safe_name = mi.name_to_safe.get(name, name)
            controls.append({
                "index": i, "original_name": name, "safe_name": safe_name,
                "internal_symbol": f"u_{i}",
            })
        parameters = []
        for i, pv in enumerate(mi.parameters):
            name = pv["name"] if isinstance(pv, dict) else pv.name
            safe_name = mi.name_to_safe.get(name, name)
            parameters.append({
                "index": i, "original_name": name, "safe_name": safe_name,
                "internal_symbol": f"p_{i}",
            })
        auxiliaries = []
        for a in mi.auxiliaries:
            name = a["name"] if isinstance(a, dict) else a.name
            safe_name = mi.name_to_safe.get(name, name)
            auxiliaries.append({
                "original_name": name, "safe_name": safe_name,
                "internal_name": safe_name,
                "function_name": f"calc_{safe_name}",
                "output_name": safe_name,
                "in_equality_closure": False,
            })

        cases = formula_gen.generate_all_cases()
        case_formulas = OutputBuilder._format_case_formulas(cases)

        return {
            "module": {
                "name": "equality_constraints_symbolic_transcription",
                "version": 1,
                "description": (
                    "Symbolic templates for linearized equality constraints. "
                    "Module 2 of SCPGEN. No numerical computation. "
                    "Empty — no equality constraints defined."
                ),
            },
            "source_problem": {"problem_name": mi.problem_name, "input_yaml": mi.input_yaml},
            "configuration": {
                "variable_mode": mi.variable_mode,
                "mesh": {"N_symbol": "N", "node_range_symbolic": "0:N"},
                "supported_apply_to": ["nodes"],
                "constraint_count": 0,
                "total_scalar_count": 0,
            },
            "symbol_table": {
                "states": states,
                "controls": controls,
                "parameters": parameters,
                "auxiliaries": auxiliaries,
            },
            "auxiliary_functions": [],
            "constraint_functions": [],
            "derivative_functions": [],
            "equality_case_formulas": case_formulas,
            "constraint_templates": [],
            "introduced_variables": [],
            "introduced_cost_terms": [],
        }

    @staticmethod
    def build_report(
        mi: Module2InputDef,
        sym_engine: Optional[EqualitySymEngine],
    ) -> Dict[str, Any]:
        """生成性能统计报告"""
        stats = sym_engine.stats if sym_engine is not None else {}
        return {
            "module": "equality_constraints_symbolic_transcription",
            "problem_name": mi.problem_name,
            "constraint_count": mi.constraint_count,
            "total_scalar_count": mi.total_scalar_count,
            "elapsed_time_sec": stats.get("total", 0.0),
            "symengine_stats": {
                "parse_auxiliaries_sec": stats.get("parse_auxiliaries", 0.0),
                "build_constraints_sec": stats.get("build_constraints", 0.0),
                "jacobian_total_sec": stats.get("jacobian_total", 0.0),
                "total_sec": stats.get("total", 0.0),
            },
        }

    # ── build ─────────────────────────────────────────────────────

    def build(
        self,
        module_input: Module2InputDef,
        sym_engine: EqualitySymEngine,
        formula_gen: EqualityFormulaGenerator,
    ) -> Dict[str, Any]:
        cases = formula_gen.generate_all_cases()

        output: Dict[str, Any] = {}
        output["module"] = self._build_module_meta()
        output["source_problem"] = self._build_source_problem(module_input)
        output["configuration"] = self._build_configuration(module_input)
        output["symbol_table"] = self._build_symbol_table(module_input, sym_engine)
        output["auxiliary_functions"] = self._build_auxiliary_functions(module_input, sym_engine)
        output["constraint_functions"] = self._build_constraint_functions(module_input, sym_engine)
        output["derivative_functions"] = self._build_derivative_functions(module_input)
        output["equality_case_formulas"] = self._build_case_formulas(cases)
        output["constraint_templates"] = self._build_constraint_templates(module_input, sym_engine)
        output["introduced_variables"] = []
        output["introduced_cost_terms"] = []

        return output

    # ── 各字段构建 ────────────────────────────────────────────────

    def _build_module_meta(self) -> Dict[str, Any]:
        return {
            "name": "equality_constraints_symbolic_transcription",
            "version": 1,
            "description": (
                "Symbolic templates for linearized equality constraints. "
                "Module 2 of SCPGEN. No numerical computation."
            ),
        }

    def _build_source_problem(self, mi: Module2InputDef) -> Dict[str, Any]:
        return {"problem_name": mi.problem_name, "input_yaml": mi.input_yaml}

    def _build_configuration(self, mi: Module2InputDef) -> Dict[str, Any]:
        return {
            "variable_mode": mi.variable_mode,
            "mesh": {
                "N_symbol": "N",
                "node_range_symbolic": "0:N",
            },
            "supported_apply_to": ["nodes"],
            "constraint_count": mi.constraint_count,
            "total_scalar_count": mi.total_scalar_count,
        }

    def _build_symbol_table(self, mi: Module2InputDef, engine: EqualitySymEngine) -> Dict[str, Any]:
        states = []
        for i, sv in enumerate(mi.states):
            name = sv["name"] if isinstance(sv, dict) else sv.name
            safe_name = mi.name_to_safe.get(name, name)
            states.append({
                "index": i,
                "original_name": name,
                "safe_name": safe_name,
                "internal_symbol": f"x_{i}",
            })

        controls = []
        for i, cv in enumerate(mi.controls):
            name = cv["name"] if isinstance(cv, dict) else cv.name
            safe_name = mi.name_to_safe.get(name, name)
            controls.append({
                "index": i,
                "original_name": name,
                "safe_name": safe_name,
                "internal_symbol": f"u_{i}",
            })

        parameters = []
        for i, pv in enumerate(mi.parameters):
            name = pv["name"] if isinstance(pv, dict) else pv.name
            safe_name = mi.name_to_safe.get(name, name)
            parameters.append({
                "index": i,
                "original_name": name,
                "safe_name": safe_name,
                "internal_symbol": f"p_{i}",
            })

        auxiliaries = []
        aux_names_set = set(engine.aux_names)
        for a in mi.auxiliaries:
            name = a["name"] if isinstance(a, dict) else a.name
            safe_name = mi.name_to_safe.get(name, name)
            in_closure = safe_name in aux_names_set
            auxiliaries.append({
                "original_name": name,
                "safe_name": safe_name,
                "internal_name": safe_name,
                "function_name": f"calc_{safe_name}",
                "output_name": safe_name,
                "in_equality_closure": in_closure,
            })

        return {
            "states": states,
            "controls": controls,
            "parameters": parameters,
            "auxiliaries": auxiliaries,
        }

    def _build_auxiliary_functions(self, mi: Module2InputDef, engine: EqualitySymEngine) -> List[Dict[str, Any]]:
        if not engine.aux_names:
            return []

        # aux_map 使用 safe_name 作为 key（匹配 symengine.aux_names）
        aux_map = {}
        for a in mi.auxiliaries:
            name = a["name"] if isinstance(a, dict) else a.name
            safe_name = mi.name_to_safe.get(name, name)
            aux_map[safe_name] = a

        result = []
        for safe_name in engine.aux_names:
            a = aux_map.get(safe_name)
            if a is None:
                continue
            expr_str = a["expr"] if isinstance(a, dict) else a.expr
            original_name = mi.safe_to_original.get(safe_name, safe_name)
            # 获取 SymPy 预处理后的模板表达式
            sym_expr = engine.aux_exprs.get(safe_name)
            entry: Dict[str, Any] = {
                "name": f"calc_{safe_name}",
                "internal_name": safe_name,
                "original_name": original_name,
                "safe_name": safe_name,
                "role": "auxiliary",
                "inputs": ["x", "u", "parameters"],
                "outputs": [safe_name],
                "expression_original": expr_str,
                "expression_template": str(sym_expr) if sym_expr is not None else expr_str,
                "generate_c_function": True,
                "reuse_across_nodes": True,
            }
            if self._debug_expr:
                entry["expression_expanded"] = str(sym_expr) if sym_expr is not None else ""
            result.append(entry)
        return result

    def _build_constraint_functions(self, mi: Module2InputDef, engine: EqualitySymEngine) -> List[Dict[str, Any]]:
        result = []
        for c in mi.constraints:
            engine_exprs = engine.constraint_exprs.get(c.name, [])
            template_exprs = [str(e) for e in engine_exprs] if engine_exprs else list(c.scalar_expressions)
            entry: Dict[str, Any] = {
                "name": f"eval_h_{c.name}",
                "role": "equality_constraint",
                "apply_to_normalized": dict(c.apply_to_normalized),
                "inputs": ["x", "u", "parameters"],
                "outputs": ["h"],
                "output_shape": [c.scalar_count],
                "scalar_expressions_canonical": c.scalar_expressions,
                "scalar_expressions_template": template_exprs,
                "generate_c_function": True,
                "reuse_across_nodes": True,
            }
            if self._debug_expr:
                entry["expressions_expanded"] = template_exprs
            result.append(entry)
        return result

    def _build_derivative_functions(self, mi: Module2InputDef) -> List[Dict[str, Any]]:
        result = []
        for c in mi.constraints:
            result.append({
                "name": f"eval_hx_{c.name}",
                "role": "equality_jacobian_wrt_state",
                "parent_constraint": c.name,
                "definition": "Hx = dh/dx",
                "inputs": ["x", "u", "parameters"],
                "outputs": ["Hx"],
                "output_shape": [c.scalar_count, mi.nx],
                "generate_c_function": True,
                "reuse_across_nodes": True,
            })
            result.append({
                "name": f"eval_hu_{c.name}",
                "role": "equality_jacobian_wrt_control",
                "parent_constraint": c.name,
                "definition": "Hu = dh/du",
                "inputs": ["x", "u", "parameters"],
                "outputs": ["Hu"],
                "output_shape": [c.scalar_count, mi.nu],
                "generate_c_function": True,
                "reuse_across_nodes": True,
            })
        return result

    @staticmethod
    def _format_case_formulas(cases: Dict[str, EqualityCaseFormula]) -> Dict[str, Any]:
        result = {}
        for case_id, case in cases.items():
            result[case_id] = {
                "case_id": case.case_id,
                "variable_mode": case.variable_mode,
                "description": case.description,
                "residual": case.residual,
                "coefficient_blocks": case.coefficient_blocks,
                "rhs": case.rhs,
                "variables": case.variables,
            }
        return result

    def _build_case_formulas(self, cases: Dict[str, EqualityCaseFormula]) -> Dict[str, Any]:
        return self._format_case_formulas(cases)

    def _build_constraint_templates(self, mi: Module2InputDef, engine: EqualitySymEngine) -> List[Dict[str, Any]]:
        templates = []
        for c in mi.constraints:
            active_case = "equality_perturbation" if mi.is_perturbation else "equality_direct"
            var_prefix = "delta_" if mi.is_perturbation else ""
            row_info = _compute_row_info(mi, c)

            # 获取 SymPy 模板表达式
            engine_exprs = engine.constraint_exprs.get(c.name, [])
            template_exprs = [str(e) for e in engine_exprs] if engine_exprs else list(c.scalar_expressions)

            # 构建 scalar_constraints（每条标量表达式一行，含 canonical + template）
            scalar_constraints = []
            exprs = c.scalar_expressions
            if len(exprs) == 1:
                entry: Dict[str, Any] = {
                    "name": c.name,
                    "expression_canonical": exprs[0],
                    "expression_template": template_exprs[0] if template_exprs else exprs[0],
                }
                # equations 形式：附加 lhs/rhs 原始字段
                if c.original_form == "equations" and c.equations_dict:
                    for lhs, rhs in c.equations_dict.items():
                        entry["lhs_original"] = lhs
                        entry["rhs_original"] = rhs
                        break  # 单标量只取第一对
                scalar_constraints.append(entry)
            else:
                eq_items = list(c.equations_dict.items()) if (c.original_form == "equations" and c.equations_dict) else []
                for i, e in enumerate(exprs):
                    entry_i: Dict[str, Any] = {
                        "name": f"{c.name}_{i}",
                        "expression_canonical": e,
                        "expression_template": template_exprs[i] if i < len(template_exprs) else e,
                    }
                    if i < len(eq_items):
                        entry_i["lhs_original"] = eq_items[i][0]
                        entry_i["rhs_original"] = eq_items[i][1]
                    scalar_constraints.append(entry_i)

            template: Dict[str, Any] = {
                "name": c.name,
                "original_name": c.name,
                "source_form": c.original_form,
                "apply_to_normalized": dict(c.apply_to_normalized),
                "scalar_constraints": scalar_constraints,
                "scalar_constraint_count": c.scalar_count,
                "applied_node_count_symbolic": row_info["applied_node_count_symbolic"],
                "applied_node_count_concrete": row_info["applied_node_count_concrete"],
                "applied_node_count_reference": row_info.get("applied_node_count_reference"),
                "rows_per_node": row_info["rows_per_node"],
                "total_rows_symbolic": row_info["total_rows_symbolic"],
                "total_rows_concrete": row_info["total_rows_concrete"],
                "variable_mode": mi.variable_mode,
                "active_formula_case": active_case,
                "variable_stencil": [
                    f"{var_prefix}x[k]",
                    f"{var_prefix}u[k]",
                ],
                "lhs_terms": [
                    {"coefficient": "C_x", "variable": f"{var_prefix}x[k]"},
                    {"coefficient": "C_u", "variable": f"{var_prefix}u[k]"},
                ],
                "rhs": "rhs",
                "matrix_fill_template": {
                    "row_layout": {
                        "loop_order": ["node", "scalar_constraint"],
                        "local_row_index": "node_local_index * scalar_constraint_count + scalar_index",
                        "rows_per_node": c.scalar_count,
                    },
                    "matrix_blocks": [
                        {"name": "C_x", "variable_block": f"{var_prefix}x", "node": "k", "shape": [c.scalar_count, mi.nx]},
                        {"name": "C_u", "variable_block": f"{var_prefix}u", "node": "k", "shape": [c.scalar_count, mi.nu]},
                    ],
                    "rhs_block": {"name": "rhs", "node": "k"},
                },
            }
            templates.append(template)
        return templates
