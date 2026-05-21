"""
输出构建器 — 组装完整的 dynamics_module1_output YAML dict

按用户说明书第五节/第十一节组装所有字段。
不包含 assumptions 字段。
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional

from .models import ProblemDef, DynamicsTranscriptionConfig
from .symengine import SymEngine
from .formula_generator import (
    FormulaGenerator, VirtualControlGenerator,
    CaseFormula, VirtualControlTemplate,
)


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

    def build(
        self,
        problem_def: ProblemDef,
        sym_engine: SymEngine,
        formula_gen: FormulaGenerator,
        vc_gen: VirtualControlGenerator,
    ) -> Dict[str, Any]:
        cases = formula_gen.generate_all_cases()
        vc_template = vc_gen.generate()

        output: Dict[str, Any] = {}
        output["module"] = self._build_module_meta()
        output["source_problem"] = self._build_source_problem(problem_def)
        output["configuration"] = self._build_configuration(problem_def)
        output["dimensions"] = self._build_dimensions(problem_def)
        output["symbol_table"] = self._build_symbol_table(problem_def, sym_engine)
        output["auxiliary_functions"] = self._build_auxiliary_functions(problem_def, sym_engine)
        output["dynamics_functions"] = self._build_dynamics_functions(problem_def, sym_engine)
        output["derivative_functions"] = self._build_derivative_functions(problem_def, sym_engine)
        output["symbolic_placeholders"] = self._build_symbolic_placeholders()
        output["decision_variable_templates"] = self._build_decision_variable_templates(problem_def)
        output["introduced_variable_templates"] = self._build_introduced_variable_templates(problem_def, vc_template)
        output["introduced_cost_term_templates"] = self._build_introduced_cost_term_templates(vc_template)
        output["active_dynamics_case"] = self._build_active_dynamics_case(problem_def)
        output["dynamics_case_formulas"] = self._build_dynamics_case_formulas(cases)
        output["active_equality_template"] = self._build_active_equality_template(problem_def, vc_template)
        output["equality_template"] = self._build_equality_template(problem_def, vc_template)
        output["matrix_fill_template"] = self._build_matrix_fill_template(problem_def)

        return output

    # ── 各字段构建 ────────────────────────────────────────────────

    def _build_module_meta(self) -> Dict[str, Any]:
        return {
            "name": "dynamics_symbolic_transcription",
            "version": 1,
            "description": (
                "Symbolic templates for discretized and linearized dynamics. "
                "Module 1 of SCPGEN. No numerical computation."
            ),
        }

    def _build_source_problem(self, pd: ProblemDef) -> Dict[str, Any]:
        return {"problem_name": pd.problem_name, "input_yaml": pd.input_yaml}

    def _build_configuration(self, pd: ProblemDef) -> Dict[str, Any]:
        cfg = pd.config
        vc = cfg.virtual_control
        return {
            "time_mode": cfg.time_mode,
            "discretization": cfg.discretization,
            "variable_mode": cfg.variable_mode,
            "simplify_level": cfg.simplify_level,
            "derive_jacobian_expressions": cfg.derive_jacobian_expressions,
            "output_debug_expressions": self._debug_expr,
            "output_c_code_expressions": self._debug_ccode,
            "output_latex_expressions": self._debug_latex,
            "mesh": {
                "N_symbol": "N",
                "interval_count_symbol": "N_minus_1",
                "grid_type": pd.mesh.grid_type,
            },
            "midpoint_policy": {
                "state_midpoint": cfg.midpoint_policy or "node_average",
                "control_midpoint": cfg.midpoint_policy or "node_average",
            },
            "virtual_control": {
                "enabled": vc.enabled,
                "form": vc.form,
                "penalty_type": vc.penalty_type,
                "penalty_weight_symbol": vc.penalty_weight_symbol,
            },
        }

    def _build_dimensions(self, pd: ProblemDef) -> Dict[str, Any]:
        return {
            "nx_symbol": "nx",
            "nu_symbol": "nu",
            "np_symbol": "np",
            "N_symbol": "N",
            "n_intervals_symbol": "N_minus_1",
            "rows_per_interval_symbol": "nx",
            "total_dynamics_rows_symbol": "N_minus_1 * nx",
            "concrete": {
                "nx": pd.nx, "nu": pd.nu, "np": pd.np,
                "N": pd.mesh.N,
                "n_intervals": pd.mesh.interval_count,
                "rows_per_interval": pd.nx,
                "total_dynamics_rows": pd.mesh.interval_count * pd.nx,
            },
        }

    def _build_symbol_table(self, pd: ProblemDef, engine: SymEngine) -> Dict[str, Any]:
        """构建符号映射表：让后续模块知道 x_0, u_1 等内部符号对应什么变量"""
        states = []
        for i, sv in enumerate(pd.states):
            safe_name = sv.name
            original_name = pd.safe_to_original.get(safe_name, safe_name)
            states.append({
                "index": i,
                "original_name": original_name,
                "safe_name": safe_name,
                "internal_symbol": f"x_{i}",
            })

        controls = []
        for i, cv in enumerate(pd.controls):
            safe_name = cv.name
            original_name = pd.safe_to_original.get(safe_name, safe_name)
            controls.append({
                "index": i,
                "original_name": original_name,
                "safe_name": safe_name,
                "internal_symbol": f"u_{i}",
            })

        parameters = []
        for i, pv in enumerate(pd.parameters):
            safe_name = pv.name
            original_name = pd.safe_to_original.get(safe_name, safe_name)
            parameters.append({
                "index": i,
                "original_name": original_name,
                "safe_name": safe_name,
                "internal_symbol": f"p_{i}",
            })

        auxiliaries = []
        for a in pd.auxiliaries:
            safe_name = a.name
            original_name = pd.safe_to_original.get(safe_name, safe_name)
            in_closure = safe_name in engine.aux_names if engine.aux_names else False
            auxiliaries.append({
                "original_name": original_name,
                "safe_name": safe_name,
                "internal_name": safe_name,
                "function_name": f"calc_{safe_name}",
                "output_name": safe_name,
                "in_dynamics_closure": in_closure,
            })

        return {
            "states": states,
            "controls": controls,
            "parameters": parameters,
            "auxiliaries": auxiliaries,
        }

    def _build_auxiliary_functions(self, pd: ProblemDef, engine: SymEngine) -> List[Dict[str, Any]]:
        if not engine.aux_names:
            return []

        aux_map = {a.name: a for a in pd.auxiliaries}
        declared_deps = getattr(pd, '_declared_deps', {})
        inferred_deps = getattr(pd, '_inferred_deps', {})
        final_deps = getattr(pd, '_final_deps', {})
        result = []
        for name in engine.aux_names:
            a = aux_map[name]
            original_name = pd.safe_to_original.get(name, name)
            entry: Dict[str, Any] = {
                "name": f"calc_{name}",
                "internal_name": name,
                "original_name": original_name,
                "role": "auxiliary",
                "inputs": ["x", "u", "parameters"],
                "outputs": [name],
                "expression": a.expr,
                "dependencies_declared": declared_deps.get(name, []),
                "dependencies_inferred": inferred_deps.get(name, []),
                "dependencies_used": final_deps.get(name, []),
                "generate_c_function": True,
                "reuse_across_nodes": True,
            }
            # 仅当 debug 模式开启时才输出展开/LaTeX/C 代码
            if self._debug_expr:
                expanded = engine.aux_exprs.get(name)
                entry["expression_expanded"] = str(expanded) if expanded else ""
            if self._debug_latex:
                expanded = engine.aux_exprs.get(name)
                entry["expression_latex"] = engine.get_latex(expanded) if expanded else ""
            if self._debug_ccode:
                expanded = engine.aux_exprs.get(name)
                entry["expression_c_code"] = engine.get_c_code(expanded) if expanded else ""
            result.append(entry)
        return result

    def _build_dynamics_functions(self, pd: ProblemDef, engine: SymEngine) -> List[Dict[str, Any]]:
        entry: Dict[str, Any] = {
            "name": "eval_f",
            "role": "dynamics_rhs",
            "inputs": ["x", "u", "parameters"],
            "outputs": ["f"],
            "output_shape": [pd.nx],
            "expressions": [
                {
                    "state": pd.safe_to_original.get(pd.states[i].name, pd.states[i].name),
                    "rhs": engine.f_original_rhs[i] if i < len(engine.f_original_rhs) and engine.f_original_rhs[i] else str(engine.f_exprs[i]),
                }
                for i in range(pd.nx)
            ],
            "generate_c_function": True,
            "reuse_across_nodes": True,
        }
        # 展开的 RHS 仅在 debug 模式输出
        if self._debug_expr:
            for i in range(pd.nx):
                entry["expressions"][i]["rhs_expanded"] = str(engine.f_exprs[i])
        if self._debug_latex:
            for i in range(pd.nx):
                entry["expressions"][i]["latex"] = engine.get_latex(engine.f_exprs[i])
        if self._debug_ccode:
            for i in range(pd.nx):
                entry["expressions"][i]["c_code"] = engine.get_c_code(engine.f_exprs[i])
        return [entry]

    def _build_derivative_functions(self, pd: ProblemDef, engine: SymEngine) -> List[Dict[str, Any]]:
        result = [
            {
                "name": "eval_fx", "role": "dynamics_jacobian_wrt_state",
                "inputs": ["x", "u", "parameters"], "outputs": ["A"],
                "output_shape": [pd.nx, pd.nx], "definition": "A = df/dx",
                "generate_c_function": True, "reuse_across_nodes": True,
            },
            {
                "name": "eval_fu", "role": "dynamics_jacobian_wrt_control",
                "inputs": ["x", "u", "parameters"], "outputs": ["B"],
                "output_shape": [pd.nx, pd.nu], "definition": "B = df/du",
                "generate_c_function": True, "reuse_across_nodes": True,
            },
        ]
        if pd.config.derive_jacobian_expressions and engine.A_mat is not None:
            if self._debug_latex:
                result[0]["matrix_latex"] = engine.get_matrix_latex(engine.A_mat)
            if self._debug_ccode:
                result[0]["matrix_c_code"] = engine.get_matrix_c_code(engine.A_mat)
            if self._debug_expr:
                result[0]["matrix_structured"] = engine.get_matrix_structured(engine.A_mat)
        if pd.config.derive_jacobian_expressions and engine.B_mat is not None:
            if self._debug_latex:
                result[1]["matrix_latex"] = engine.get_matrix_latex(engine.B_mat)
            if self._debug_ccode:
                result[1]["matrix_c_code"] = engine.get_matrix_c_code(engine.B_mat)
            if self._debug_expr:
                result[1]["matrix_structured"] = engine.get_matrix_structured(engine.B_mat)
        return result

    def _build_symbolic_placeholders(self) -> Dict[str, Any]:
        return {
            "interval": ["k", "xL", "uL", "xR", "uR"],
            "reference": ["x_ref[k]", "u_ref[k]", "x_ref[k+1]", "u_ref[k+1]"],
            "mesh": ["dt[k]", "d_tau[k]"],
            "free_time": ["T_ref", "T", "delta_T"],
            "dynamics_values": ["fL", "fR", "fM"],
            "jacobians": ["AL", "BL", "AR", "BR", "AM", "BM"],
            "coefficient_blocks": ["C_xL", "C_uL", "C_xR", "C_uR", "C_T"],
            "residual": ["residual_k"],
        }

    def _build_decision_variable_templates(self, pd: ProblemDef) -> List[Dict[str, Any]]:
        cfg = pd.config
        N = pd.mesh.N
        result = []
        if cfg.variable_mode == "perturbation":
            result.append({"name": "delta_x", "enabled_if": "variable_mode == perturbation",
                          "shape_symbolic": ["N", "nx"], "shape_concrete": [N, pd.nx]})
            result.append({"name": "delta_u", "enabled_if": "variable_mode == perturbation",
                          "shape_symbolic": ["N", "nu"], "shape_concrete": [N, pd.nu]})
        else:
            result.append({"name": "x", "enabled_if": "variable_mode == direct",
                          "shape_symbolic": ["N", "nx"], "shape_concrete": [N, pd.nx]})
            result.append({"name": "u", "enabled_if": "variable_mode == direct",
                          "shape_symbolic": ["N", "nu"], "shape_concrete": [N, pd.nu]})
        if cfg.time_mode == "free_final_time":
            if cfg.variable_mode == "perturbation":
                result.append({"name": "delta_T", "enabled_if": "time_mode == free_final_time and variable_mode == perturbation",
                              "shape_symbolic": [1], "shape_concrete": [1]})
            else:
                result.append({"name": "T", "enabled_if": "time_mode == free_final_time and variable_mode == direct",
                              "shape_symbolic": [1], "shape_concrete": [1]})
        return result

    def _build_introduced_variable_templates(self, pd: ProblemDef, vc: VirtualControlTemplate) -> List[Dict[str, Any]]:
        result = []
        for v in vc.introduced_variables:
            entry = dict(v)
            sym_shape = entry.get("shape_symbolic", [])
            concrete = []
            for s in sym_shape:
                if s == "N_minus_1":
                    concrete.append(pd.mesh.interval_count)
                elif s == "nx":
                    concrete.append(pd.nx)
                elif s == "nu":
                    concrete.append(pd.nu)
                else:
                    concrete.append(s)
            entry["shape_concrete"] = concrete
            result.append(entry)
        return result

    def _build_introduced_cost_term_templates(self, vc: VirtualControlTemplate) -> List[Dict[str, Any]]:
        return vc.cost_terms

    def _build_active_dynamics_case(self, pd: ProblemDef) -> Dict[str, Any]:
        cfg = pd.config
        case_id = self._determine_case_id(cfg)
        return {
            "id": case_id,
            "time_mode": cfg.time_mode,
            "discretization": cfg.discretization,
            "variable_mode": cfg.variable_mode,
        }

    @staticmethod
    def _determine_case_id(cfg: DynamicsTranscriptionConfig) -> str:
        mapping = {
            ("fixed_time", "trapezoidal", "perturbation"): "case_1_fixed_trapezoidal_perturbation",
            ("fixed_time", "trapezoidal", "direct"): "case_2_fixed_trapezoidal_direct",
            ("fixed_time", "midpoint", "perturbation"): "case_3_fixed_midpoint_perturbation",
            ("fixed_time", "midpoint", "direct"): "case_4_fixed_midpoint_direct",
            ("free_final_time", "trapezoidal", "perturbation"): "case_5_free_trapezoidal_perturbation",
            ("free_final_time", "trapezoidal", "direct"): "case_6_free_trapezoidal_direct",
            ("free_final_time", "midpoint", "perturbation"): "case_7_free_midpoint_perturbation",
            ("free_final_time", "midpoint", "direct"): "case_8_free_midpoint_direct",
        }
        return mapping[(cfg.time_mode, cfg.discretization, cfg.variable_mode)]

    def _build_dynamics_case_formulas(self, cases: List[CaseFormula]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for c in cases:
            entry: Dict[str, Any] = {}
            if c.midpoint_def:
                entry["midpoint"] = c.midpoint_def
            if c.residual:
                entry["residual"] = c.residual
            entry["coefficient_blocks"] = {}
            for blk in c.coefficient_blocks:
                entry["coefficient_blocks"][blk["name"]] = {
                    "formula_ascii": blk["formula"], "latex": blk["latex"],
                    "description": blk.get("description", ""),
                }
            if c.rhs:
                entry["rhs"] = c.rhs
            entry["variables"] = c.variables
            entry["description"] = c.description
            result[c.case_id] = entry
        return result

    def _build_equality_template(self, pd: ProblemDef, vc: VirtualControlTemplate) -> Dict[str, Any]:
        cfg = pd.config
        return {
            "role": "generic_template_for_human_reference",
            "name": "dynamics_defect_linearized", "type": "equality",
            "applies_to": "all_intervals",
            "rows_per_interval_symbol": "nx", "total_rows_symbol": "N_minus_1 * nx",
            "ascii_form": vc.equality_template_ascii,
            "latex_form": vc.equality_template_latex,
            "variable_stencil": self._make_variable_stencil(cfg),
            "virtual_control_extra_terms": vc.equality_extra_terms,
        }

    def _build_active_equality_template(self, pd: ProblemDef, vc: VirtualControlTemplate) -> Dict[str, Any]:
        """根据当前配置实际展开的等式模板，与 active_dynamics_case 对应"""
        cfg = pd.config
        vc_cfg = cfg.virtual_control

        # 变量名
        if cfg.variable_mode == "perturbation":
            var_xL, var_uL, var_xR, var_uR = "delta_x[k]", "delta_u[k]", "delta_x[k+1]", "delta_u[k+1]"
            var_T = "delta_T"
        else:
            var_xL, var_uL, var_xR, var_uR = "x[k]", "u[k]", "x[k+1]", "u[k+1]"
            var_T = "T"

        base = f"C_xL * {var_xL} + C_uL * {var_uL} + C_xR * {var_xR} + C_uR * {var_uR}"

        extra_parts: List[str] = []
        if cfg.time_mode == "free_final_time":
            extra_parts.append(f"C_T * {var_T}")

        if vc_cfg.enabled:
            if vc_cfg.form == "signed":
                extra_parts.append("vc[k]")
            elif vc_cfg.form == "split_nonnegative":
                extra_parts.append("vc_plus[k] - vc_minus[k]")

        if extra_parts:
            ascii_form = " + ".join([base] + extra_parts) + " = rhs"
        else:
            ascii_form = base + " = rhs"

        # 构建结构化 lhs_terms
        lhs_terms: List[Dict[str, Any]] = [
            {"coefficient": "C_xL", "variable": var_xL},
            {"coefficient": "C_uL", "variable": var_uL},
            {"coefficient": "C_xR", "variable": var_xR},
            {"coefficient": "C_uR", "variable": var_uR},
        ]
        if cfg.time_mode == "free_final_time":
            lhs_terms.append({
                "coefficient": "C_T", "variable": var_T,
            })
        if vc_cfg.enabled:
            if vc_cfg.form == "signed":
                lhs_terms.append({
                    "coefficient": "+I_nx", "variable": "vc[k]",
                })
            elif vc_cfg.form == "split_nonnegative":
                lhs_terms.append({
                    "coefficient": "+I_nx", "variable": "vc_plus[k]",
                })
                lhs_terms.append({
                    "coefficient": "-I_nx", "variable": "vc_minus[k]",
                })

        return {
            "role": "machine_readable_template_for_downstream_modules",
            "name": "dynamics_defect_linearized_active",
            "type": "equality",
            "applies_to": "all_intervals",
            "ascii_form": ascii_form,
            "lhs_terms": lhs_terms,
            "rhs": "rhs",
            "time_mode": cfg.time_mode,
            "variable_mode": cfg.variable_mode,
            "virtual_control_form": vc_cfg.form if vc_cfg.enabled else "disabled",
        }

    def _make_variable_stencil(self, cfg: DynamicsTranscriptionConfig) -> List[str]:
        vc = cfg.virtual_control
        if cfg.variable_mode == "perturbation":
            stencil = ["delta_x[k]", "delta_u[k]", "delta_x[k+1]", "delta_u[k+1]"]
        else:
            stencil = ["x[k]", "u[k]", "x[k+1]", "u[k+1]"]
        if cfg.time_mode == "free_final_time":
            stencil.append("delta_T" if cfg.variable_mode == "perturbation" else "T")
        if vc.enabled:
            if vc.form == "signed":
                stencil.append("vc[k]")
            else:
                stencil.extend(["vc_plus[k]", "vc_minus[k]"])
        return stencil

    def _build_matrix_fill_template(self, pd: ProblemDef) -> Dict[str, Any]:
        cfg = pd.config
        vc = cfg.virtual_control
        col_rule = {
            "xL": "variable_index(x_or_delta_x, k)",
            "uL": "variable_index(u_or_delta_u, k)",
            "xR": "variable_index(x_or_delta_x, k+1)",
            "uR": "variable_index(u_or_delta_u, k+1)",
        }
        if cfg.time_mode == "free_final_time":
            col_rule["T"] = "variable_index(T_or_delta_T)"

        # Virtual control column rules: 按 form 区分
        if vc.enabled:
            if vc.form == "signed":
                col_rule["vc"] = "variable_index(vc, k)"
            elif vc.form == "split_nonnegative":
                col_rule["vc_plus"] = "variable_index(vc_plus, k)"
                col_rule["vc_minus"] = "variable_index(vc_minus, k)"

        # matrix_blocks（不含 rhs）
        matrix_blocks = ["C_xL", "C_uL", "C_xR", "C_uR"]
        if cfg.time_mode == "free_final_time":
            matrix_blocks.append("C_T")

        result: Dict[str, Any] = {
            "row_index_rule": {
                "interval_k_start": "k * nx",
                "interval_k_end": "(k + 1) * nx - 1",
            },
            "column_block_rule": col_rule,
            "matrix_blocks": matrix_blocks,
            "rhs_block": {"name": "rhs"},
        }

        # 虚拟控制填充规则（独立字段，按 form 展开）
        if vc.enabled:
            if vc.form == "signed":
                result["virtual_control_fill_blocks"] = [
                    {"variable": "vc[k]", "coefficient": "+I_nx"}
                ]
            elif vc.form == "split_nonnegative":
                result["virtual_control_fill_blocks"] = [
                    {"variable": "vc_plus[k]", "coefficient": "+I_nx"},
                    {"variable": "vc_minus[k]", "coefficient": "-I_nx"},
                ]

        return result

    @staticmethod
    def build_debug_report(sym_engine: SymEngine) -> Dict[str, Any]:
        """构建性能统计报告（单独输出，不进入核心 IR）"""
        return {
            "module": "dynamics_symbolic_transcription",
            "report_type": "performance_stats",
            "total_time_s": sym_engine.stats.get("total", 0),
            "parse_auxiliaries_s": sym_engine.stats.get("parse_auxiliaries", 0),
            "build_dynamics_s": sym_engine.stats.get("build_dynamics", 0),
            "jacobian_df_dx_s": sym_engine.stats.get("jacobian_df_dx", 0),
            "jacobian_df_du_s": sym_engine.stats.get("jacobian_df_du", 0),
            "aux_used_count": sym_engine.aux_used_count,
            "aux_ignored_count": sym_engine.aux_ignored_count,
        }
