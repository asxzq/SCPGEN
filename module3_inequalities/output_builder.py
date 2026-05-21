"""
输出构建器 — 组装完整的 inequality_module3_output YAML dict

按用户说明书第十节组装所有字段。
不包含 assumptions / boundary_constraints / path_constraints 字段。
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional

from .models import Module3InputDef, InequalityConstraintDef
from .symengine import InequalitySymEngine
from .formula_generator import InequalityFormulaGenerator, InequalityCaseFormula


# ── 辅助：计算行数信息 ────────────────────────────────────────────

def _compute_row_info(mi: "Module3InputDef", c: "InequalityConstraintDef") -> Dict[str, Any]:
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
    def build_empty(mi: Module3InputDef, formula_gen: "InequalityFormulaGenerator") -> Dict[str, Any]:
        """生成空约束的 Module 3 输出"""
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
                "in_inequality_closure": False,
            })

        cases = formula_gen.generate_all_cases()
        case_formulas = OutputBuilder._format_case_formulas(cases)

        return {
            "module": {
                "name": "inequality_constraints_symbolic_transcription",
                "version": 1,
                "description": (
                    "Symbolic templates for linearized inequality constraints. "
                    "Module 3 of SCPGEN. No numerical computation. "
                    "Empty — no inequality constraints defined."
                ),
            },
            "source_problem": {"problem_name": mi.problem_name, "input_yaml": mi.input_yaml},
            "configuration": {
                "variable_mode": mi.variable_mode,
                "mesh": {"N_symbol": "N", "node_range_symbolic": "0:N"},
                "supported_apply_to": ["nodes"],
                "constraint_count": 0,
                "total_scalar_count": 0,
                "slack_policy": {
                    "global_enabled": mi.global_slack_config.enabled,
                    "penalty_type": mi.global_slack_config.penalty_type,
                    "penalty_weight_symbol": mi.global_slack_config.penalty_weight_symbol,
                },
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
            "inequality_case_formulas": case_formulas,
            "constraint_templates": [],
            "introduced_variables": [],
            "introduced_cost_terms": [],
        }

    @staticmethod
    def build_report(
        mi: Module3InputDef,
        sym_engine: Optional[InequalitySymEngine],
    ) -> Dict[str, Any]:
        """生成性能统计报告"""
        stats = sym_engine.stats if sym_engine is not None else {}
        return {
            "module": "inequality_constraints_symbolic_transcription",
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
        module_input: Module3InputDef,
        sym_engine: InequalitySymEngine,
        formula_gen: InequalityFormulaGenerator,
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
        output["inequality_case_formulas"] = self._build_case_formulas(cases)
        output["constraint_templates"] = self._build_constraint_templates(module_input, sym_engine)
        output["introduced_variables"] = self._build_introduced_variables(module_input)
        output["introduced_cost_terms"] = self._build_introduced_cost_terms(module_input)

        return output

    # ── 各字段构建 ────────────────────────────────────────────────

    def _build_module_meta(self) -> Dict[str, Any]:
        return {
            "name": "inequality_constraints_symbolic_transcription",
            "version": 1,
            "description": (
                "Symbolic templates for linearized inequality constraints. "
                "Module 3 of SCPGEN. No numerical computation."
            ),
        }

    def _build_source_problem(self, mi: Module3InputDef) -> Dict[str, Any]:
        return {"problem_name": mi.problem_name, "input_yaml": mi.input_yaml}

    def _build_configuration(self, mi: Module3InputDef) -> Dict[str, Any]:
        gs = mi.global_slack_config
        return {
            "variable_mode": mi.variable_mode,
            "mesh": {
                "N_symbol": "N",
                "node_range_symbolic": "0:N",
            },
            "supported_apply_to": ["nodes"],
            "constraint_count": mi.constraint_count,
            "total_scalar_count": mi.total_scalar_count,
            "slack_policy": {
                "global_enabled": gs.enabled,
                "penalty_type": gs.penalty_type,
                "penalty_weight_symbol": gs.penalty_weight_symbol,
            },
        }

    def _build_symbol_table(self, mi: Module3InputDef, engine: InequalitySymEngine) -> Dict[str, Any]:
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
                "in_inequality_closure": in_closure,
            })

        return {
            "states": states,
            "controls": controls,
            "parameters": parameters,
            "auxiliaries": auxiliaries,
        }

    def _build_auxiliary_functions(self, mi: Module3InputDef, engine: InequalitySymEngine) -> List[Dict[str, Any]]:
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

    def _build_constraint_functions(self, mi: Module3InputDef, engine: InequalitySymEngine) -> List[Dict[str, Any]]:
        result = []
        for c in mi.constraints:
            engine_exprs = engine.constraint_exprs.get(c.name, [])
            template_exprs = [str(e) for e in engine_exprs] if engine_exprs else list(c.normalized_expressions)
            entry: Dict[str, Any] = {
                "name": f"eval_g_{c.name}",
                "role": "inequality_constraint",
                "apply_to_normalized": dict(c.apply_to_normalized),
                "inputs": ["x", "u", "parameters"],
                "outputs": ["g"],
                "output_shape": [c.scalar_count],
                "original_expressions": [c.original_expression],
                "normalized_expressions_original": c.normalized_expressions,
                "normalized_expressions_template": template_exprs,
                "slack_enabled": c.slack_enabled,
                "generate_c_function": True,
                "reuse_across_nodes": True,
            }
            if self._debug_expr:
                entry["expressions_expanded"] = template_exprs
            result.append(entry)
        return result

    def _build_derivative_functions(self, mi: Module3InputDef) -> List[Dict[str, Any]]:
        result = []
        for c in mi.constraints:
            result.append({
                "name": f"eval_gx_{c.name}",
                "role": "inequality_jacobian_wrt_state",
                "parent_constraint": c.name,
                "definition": "Gx = dg/dx",
                "inputs": ["x", "u", "parameters"],
                "outputs": ["Gx"],
                "output_shape": [c.scalar_count, mi.nx],
                "generate_c_function": True,
                "reuse_across_nodes": True,
            })
            result.append({
                "name": f"eval_gu_{c.name}",
                "role": "inequality_jacobian_wrt_control",
                "parent_constraint": c.name,
                "definition": "Gu = dg/du",
                "inputs": ["x", "u", "parameters"],
                "outputs": ["Gu"],
                "output_shape": [c.scalar_count, mi.nu],
                "generate_c_function": True,
                "reuse_across_nodes": True,
            })
        return result

    @staticmethod
    def _format_case_formulas(cases: Dict[str, InequalityCaseFormula]) -> Dict[str, Any]:
        result = {}
        for case_id, case in cases.items():
            result[case_id] = {
                "case_id": case.case_id,
                "variable_mode": case.variable_mode,
                "slack_enabled": case.slack_enabled,
                "description": case.description,
                "residual": case.residual,
                "coefficient_blocks": case.coefficient_blocks,
                "rhs": case.rhs,
                "variables": case.variables,
            }
        return result

    def _build_case_formulas(self, cases: Dict[str, InequalityCaseFormula]) -> Dict[str, Any]:
        return self._format_case_formulas(cases)

    def _build_constraint_templates(self, mi: Module3InputDef, engine: InequalitySymEngine) -> List[Dict[str, Any]]:
        templates = []
        for c in mi.constraints:
            var_prefix = "delta_" if mi.is_perturbation else ""
            slack_suffix = "_with_slack" if c.slack_enabled else "_no_slack"
            active_case = f"inequality_{'perturbation' if mi.is_perturbation else 'direct'}{slack_suffix}"
            row_info = _compute_row_info(mi, c)

            # 获取 SymPy 模板表达式
            engine_exprs = engine.constraint_exprs.get(c.name, [])
            template_exprs = [str(e) for e in engine_exprs] if engine_exprs else list(c.normalized_expressions)

            lhs_terms = [
                {"coefficient": "C_x", "variable": f"{var_prefix}x[k]"},
                {"coefficient": "C_u", "variable": f"{var_prefix}u[k]"},
            ]
            matrix_blocks = [
                {"name": "C_x", "variable_block": f"{var_prefix}x", "node": "k", "shape": [c.scalar_count, mi.nx]},
                {"name": "C_u", "variable_block": f"{var_prefix}u", "node": "k", "shape": [c.scalar_count, mi.nu]},
            ]
            var_stencil = [f"{var_prefix}x[k]", f"{var_prefix}u[k]"]

            if c.slack_enabled:
                # slack 启用：直接输出 slack 项，无 enabled_if
                lhs_terms.append({
                    "coefficient": "-I",
                    "variable": f"s_{c.name}[k]",
                })
                matrix_blocks.append({
                    "name": "C_s",
                    "variable_block": f"s_{c.name}",
                    "node": "k",
                    "shape": [c.scalar_count, c.scalar_count],
                    "value": "-I",
                })
                var_stencil.append(f"s_{c.name}[k]")

            # 构建 scalar_constraints（链式拆分后的子约束列表，含 original + template）
            scalar_constraints = []
            sub_names = getattr(c, 'sub_names', [])
            normalized_exprs = c.normalized_expressions
            # 过滤掉空字符串的 sub_names（如简单不等式的 normalize_to_le_zero 返回空名）
            real_sub_names = [sn for sn in sub_names if sn]
            if real_sub_names and len(real_sub_names) == len(normalized_exprs):
                for i, sn in enumerate(real_sub_names):
                    scalar_constraints.append({
                        "name": sn,
                        "normalized_expression_original": normalized_exprs[i],
                        "normalized_expression_template": template_exprs[i] if i < len(template_exprs) else normalized_exprs[i],
                    })
            else:
                for i, ne in enumerate(normalized_exprs):
                    scalar_constraints.append({
                        "name": c.name if len(normalized_exprs) == 1 else f"{c.name}_{i}",
                        "normalized_expression_original": ne,
                        "normalized_expression_template": template_exprs[i] if i < len(template_exprs) else ne,
                    })

            template: Dict[str, Any] = {
                "name": c.name,
                "original_expression_original": c.original_expression,
                "normalized_expression_original": c.normalized_expressions,
                "normalized_expression_template": template_exprs,
                "apply_to_normalized": dict(c.apply_to_normalized),
                "sub_names": sub_names,
                "scalar_constraints": scalar_constraints,
                "scalar_constraint_count": c.scalar_count,
                "applied_node_count_symbolic": row_info["applied_node_count_symbolic"],
                "applied_node_count_concrete": row_info["applied_node_count_concrete"],
                "applied_node_count_reference": row_info.get("applied_node_count_reference"),
                "rows_per_node": row_info["rows_per_node"],
                "total_rows_symbolic": row_info["total_rows_symbolic"],
                "total_rows_concrete": row_info["total_rows_concrete"],
                "variable_mode": mi.variable_mode,
                "slack_enabled": c.slack_enabled,
                "active_formula_case": active_case,
                "variable_stencil": var_stencil,
                "lhs_terms": lhs_terms,
                "rhs": "rhs",
                "matrix_fill_template": {
                    "row_layout": {
                        "loop_order": ["node", "scalar_constraint"],
                        "local_row_index": "node_local_index * scalar_constraint_count + scalar_index",
                        "rows_per_node": c.scalar_count,
                    },
                    "matrix_blocks": matrix_blocks,
                    "rhs_block": {"name": "rhs", "node": "k"},
                },
            }
            templates.append(template)
        return templates

    def _build_introduced_variables(self, mi: "Module3InputDef") -> List[Dict[str, Any]]:
        """如果启用 slack，列出 s_<constraint_name> 变量"""
        result = []
        for c in mi.constraints:
            if not c.slack_enabled:
                continue
            at = c.apply_to_normalized
            nodes_sym = at.get("nodes_symbolic", [])
            nodes_con = at.get("nodes_concrete", [])

            # shape_symbolic 区分 all_nodes / terminal / custom
            if nodes_sym == "all_nodes":
                shape_sym = ["N", c.scalar_count]
                shape_con = [mi.mesh_N, c.scalar_count]
            elif nodes_sym == ["N"]:
                # terminal: 单个终端节点
                shape_sym = [1, c.scalar_count]
                shape_con = [1, c.scalar_count]
            else:
                # custom nodes: nodes_concrete 是整数列表
                node_count = len(nodes_con) if isinstance(nodes_con, list) else mi.mesh_N
                shape_sym = [node_count, c.scalar_count]
                shape_con = [node_count, c.scalar_count]

            result.append({
                "name": f"s_{c.name}",
                "domain": "nonnegative",
                "shape_symbolic": shape_sym,
                "shape_concrete": shape_con,
                "role": "inequality_slack",
                "parent_constraint": c.name,
            })
        return result

    def _build_introduced_cost_terms(self, mi: Module3InputDef) -> List[Dict[str, Any]]:
        """如果启用 slack，列出 l1 惩罚项"""
        result = []
        for c in mi.constraints:
            if not c.slack_enabled:
                continue
            rho = c.slack_config.penalty_weight_symbol
            result.append({
                "name": f"slack_l1_penalty_{c.name}",
                "type": "linear",
                "expression_template": f"{rho} * sum(s_{c.name})",
                "penalty_weight_symbol": rho,
                "generated_by": "module3_inequality",
                "parent_constraint": c.name,
            })
        return result
