"""
公式生成器 — 八种动力学情形 + 虚拟控制模板

严格按说明书第九节/第十节生成，不做自行推导。
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from .models import DynamicsTranscriptionConfig


# ── 辅助: 结构化公式描述 ──────────────────────────────────────────

def _coeff_block(name: str, formula_ascii: str, latex_str: str, description: str = "") -> Dict[str, Any]:
    return {"name": name, "formula": formula_ascii, "latex": latex_str, "description": description}


def _residual_block(name: str, formula_ascii: str, latex_str: str, description: str = "") -> Dict[str, Any]:
    return {"name": name, "formula": formula_ascii, "latex": latex_str, "description": description}


def _rhs_block(name: str, formula_ascii: str, latex_str: str, description: str = "") -> Dict[str, Any]:
    return {"name": name, "formula": formula_ascii, "latex": latex_str, "description": description}


# ── CaseFormula ───────────────────────────────────────────────────

@dataclass
class CaseFormula:
    case_id: str
    time_mode: str
    discretization: str
    variable_mode: str
    description: str = ""
    midpoint_def: Optional[Dict[str, Any]] = None
    residual: Optional[Dict[str, Any]] = None
    coefficient_blocks: List[Dict[str, Any]] = field(default_factory=list)
    rhs: Optional[Dict[str, Any]] = None
    variables: List[str] = field(default_factory=list)


# ── FormulaGenerator ──────────────────────────────────────────────

class FormulaGenerator:
    """八种动力学情形公式生成器"""

    def __init__(self, config: DynamicsTranscriptionConfig):
        self._cfg = config

    def generate_all_cases(self) -> List[CaseFormula]:
        return [
            self._case_1(), self._case_2(),
            self._case_3(), self._case_4(),
            self._case_5(), self._case_6(),
            self._case_7(), self._case_8(),
        ]

    # ── Case 1: fixed_time + trapezoidal + perturbation ───────────

    def _case_1(self) -> CaseFormula:
        return CaseFormula(
            case_id="case_1_fixed_trapezoidal_perturbation",
            time_mode="fixed_time", discretization="trapezoidal", variable_mode="perturbation",
            description="fixed_time + trapezoidal + perturbation",
            residual=_residual_block(
                "residual_k",
                "residual_k = xR - xL - 0.5 * dt[k] * (fL + fR)",
                r"\mathbf{r}_k = \mathbf{x}_R - \mathbf{x}_L - \frac{1}{2} \Delta t_k \, (\mathbf{f}_L + \mathbf{f}_R)",
                "Trapezoidal defect for interval k",
            ),
            coefficient_blocks=[
                _coeff_block("C_xL", "C_xL = -I - 0.5 * dt[k] * AL", r"\mathbf{C}_{x_L} = -\mathbf{I} - \frac{1}{2}\Delta t_k \mathbf{A}_L"),
                _coeff_block("C_uL", "C_uL = -0.5 * dt[k] * BL", r"\mathbf{C}_{u_L} = -\frac{1}{2}\Delta t_k \mathbf{B}_L"),
                _coeff_block("C_xR", "C_xR = I - 0.5 * dt[k] * AR", r"\mathbf{C}_{x_R} = \mathbf{I} - \frac{1}{2}\Delta t_k \mathbf{A}_R"),
                _coeff_block("C_uR", "C_uR = -0.5 * dt[k] * BR", r"\mathbf{C}_{u_R} = -\frac{1}{2}\Delta t_k \mathbf{B}_R"),
            ],
            rhs=_rhs_block("rhs", "rhs = -residual_k", r"\mathbf{b} = -\mathbf{r}_k", "Perturbation mode: rhs = -residual"),
            variables=["delta_x[k]", "delta_u[k]", "delta_x[k+1]", "delta_u[k+1]"],
        )

    # ── Case 2: fixed_time + trapezoidal + direct ─────────────────

    def _case_2(self) -> CaseFormula:
        return CaseFormula(
            case_id="case_2_fixed_trapezoidal_direct",
            time_mode="fixed_time", discretization="trapezoidal", variable_mode="direct",
            description="fixed_time + trapezoidal + direct",
            residual=_residual_block(
                "residual_k",
                "residual_k = xR - xL - 0.5 * dt[k] * (fL + fR)",
                r"\mathbf{r}_k = \mathbf{x}_R - \mathbf{x}_L - \frac{1}{2} \Delta t_k \, (\mathbf{f}_L + \mathbf{f}_R)",
                "Trapezoidal defect for interval k",
            ),
            coefficient_blocks=[
                _coeff_block("C_xL", "C_xL = -I - 0.5 * dt[k] * AL", r"\mathbf{C}_{x_L} = -\mathbf{I} - \frac{1}{2}\Delta t_k \mathbf{A}_L"),
                _coeff_block("C_uL", "C_uL = -0.5 * dt[k] * BL", r"\mathbf{C}_{u_L} = -\frac{1}{2}\Delta t_k \mathbf{B}_L"),
                _coeff_block("C_xR", "C_xR = I - 0.5 * dt[k] * AR", r"\mathbf{C}_{x_R} = \mathbf{I} - \frac{1}{2}\Delta t_k \mathbf{A}_R"),
                _coeff_block("C_uR", "C_uR = -0.5 * dt[k] * BR", r"\mathbf{C}_{u_R} = -\frac{1}{2}\Delta t_k \mathbf{B}_R"),
            ],
            rhs=_rhs_block(
                "rhs",
                "rhs = C_xL * xL + C_uL * uL + C_xR * xR + C_uR * uR - residual_k",
                r"\mathbf{b} = \mathbf{C}_{x_L}\mathbf{x}_L + \mathbf{C}_{u_L}\mathbf{u}_L + \mathbf{C}_{x_R}\mathbf{x}_R + \mathbf{C}_{u_R}\mathbf{u}_R - \mathbf{r}_k",
                "Direct mode: reference shift RHS",
            ),
            variables=["x[k]", "u[k]", "x[k+1]", "u[k+1]"],
        )

    # ── Case 3: fixed_time + midpoint + perturbation ──────────────

    def _case_3(self) -> CaseFormula:
        return CaseFormula(
            case_id="case_3_fixed_midpoint_perturbation",
            time_mode="fixed_time", discretization="midpoint", variable_mode="perturbation",
            description="fixed_time + midpoint + perturbation",
            midpoint_def={
                "xM": "xM = 0.5 * (xL + xR)", "uM": "uM = 0.5 * (uL + uR)",
                "fM": "fM = eval_f(xM, uM, p)", "AM": "AM = eval_fx(xM, uM, p)", "BM": "BM = eval_fu(xM, uM, p)",
                "latex": r"\mathbf{x}_M = \frac{1}{2}(\mathbf{x}_L + \mathbf{x}_R),\;\mathbf{u}_M = \frac{1}{2}(\mathbf{u}_L + \mathbf{u}_R)",
            },
            residual=_residual_block(
                "residual_k", "residual_k = xR - xL - dt[k] * fM",
                r"\mathbf{r}_k = \mathbf{x}_R - \mathbf{x}_L - \Delta t_k \, \mathbf{f}_M",
                "Midpoint defect for interval k",
            ),
            coefficient_blocks=[
                _coeff_block("C_xL", "C_xL = -I - 0.5 * dt[k] * AM", r"\mathbf{C}_{x_L} = -\mathbf{I} - \frac{1}{2}\Delta t_k \mathbf{A}_M"),
                _coeff_block("C_uL", "C_uL = -0.5 * dt[k] * BM", r"\mathbf{C}_{u_L} = -\frac{1}{2}\Delta t_k \mathbf{B}_M"),
                _coeff_block("C_xR", "C_xR = I - 0.5 * dt[k] * AM", r"\mathbf{C}_{x_R} = \mathbf{I} - \frac{1}{2}\Delta t_k \mathbf{A}_M"),
                _coeff_block("C_uR", "C_uR = -0.5 * dt[k] * BM", r"\mathbf{C}_{u_R} = -\frac{1}{2}\Delta t_k \mathbf{B}_M"),
            ],
            rhs=_rhs_block("rhs", "rhs = -residual_k", r"\mathbf{b} = -\mathbf{r}_k", "Perturbation mode: rhs = -residual"),
            variables=["delta_x[k]", "delta_u[k]", "delta_x[k+1]", "delta_u[k+1]"],
        )

    # ── Case 4: fixed_time + midpoint + direct ────────────────────

    def _case_4(self) -> CaseFormula:
        return CaseFormula(
            case_id="case_4_fixed_midpoint_direct",
            time_mode="fixed_time", discretization="midpoint", variable_mode="direct",
            description="fixed_time + midpoint + direct",
            midpoint_def={
                "xM": "xM = 0.5 * (xL + xR)", "uM": "uM = 0.5 * (uL + uR)",
                "fM": "fM = eval_f(xM, uM, p)", "AM": "AM = eval_fx(xM, uM, p)", "BM": "BM = eval_fu(xM, uM, p)",
                "latex": r"\mathbf{x}_M = \frac{1}{2}(\mathbf{x}_L + \mathbf{x}_R),\;\mathbf{u}_M = \frac{1}{2}(\mathbf{u}_L + \mathbf{u}_R)",
            },
            residual=_residual_block(
                "residual_k", "residual_k = xR - xL - dt[k] * fM",
                r"\mathbf{r}_k = \mathbf{x}_R - \mathbf{x}_L - \Delta t_k \, \mathbf{f}_M",
                "Midpoint defect for interval k",
            ),
            coefficient_blocks=[
                _coeff_block("C_xL", "C_xL = -I - 0.5 * dt[k] * AM", r"\mathbf{C}_{x_L} = -\mathbf{I} - \frac{1}{2}\Delta t_k \mathbf{A}_M"),
                _coeff_block("C_uL", "C_uL = -0.5 * dt[k] * BM", r"\mathbf{C}_{u_L} = -\frac{1}{2}\Delta t_k \mathbf{B}_M"),
                _coeff_block("C_xR", "C_xR = I - 0.5 * dt[k] * AM", r"\mathbf{C}_{x_R} = \mathbf{I} - \frac{1}{2}\Delta t_k \mathbf{A}_M"),
                _coeff_block("C_uR", "C_uR = -0.5 * dt[k] * BM", r"\mathbf{C}_{u_R} = -\frac{1}{2}\Delta t_k \mathbf{B}_M"),
            ],
            rhs=_rhs_block(
                "rhs",
                "rhs = C_xL * xL + C_uL * uL + C_xR * xR + C_uR * uR - residual_k",
                r"\mathbf{b} = \mathbf{C}_{x_L}\mathbf{x}_L + \mathbf{C}_{u_L}\mathbf{u}_L + \mathbf{C}_{x_R}\mathbf{x}_R + \mathbf{C}_{u_R}\mathbf{u}_R - \mathbf{r}_k",
                "Direct mode: reference shift RHS",
            ),
            variables=["x[k]", "u[k]", "x[k+1]", "u[k+1]"],
        )

    # ── Case 5: free_final_time + trapezoidal + perturbation ──────

    def _case_5(self) -> CaseFormula:
        return CaseFormula(
            case_id="case_5_free_trapezoidal_perturbation",
            time_mode="free_final_time", discretization="trapezoidal", variable_mode="perturbation",
            description="free_final_time + trapezoidal + perturbation",
            residual=_residual_block(
                "residual_k",
                "residual_k = xR - xL - 0.5 * d_tau[k] * T_ref * (fL + fR)",
                r"\mathbf{r}_k = \mathbf{x}_R - \mathbf{x}_L - \frac{1}{2} \Delta\tau_k \, T_{\text{ref}} \, (\mathbf{f}_L + \mathbf{f}_R)",
                "Free-final-time trapezoidal defect",
            ),
            coefficient_blocks=[
                _coeff_block("C_xL", "C_xL = -I - 0.5 * d_tau[k] * T_ref * AL", r"\mathbf{C}_{x_L} = -\mathbf{I} - \frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{A}_L"),
                _coeff_block("C_uL", "C_uL = -0.5 * d_tau[k] * T_ref * BL", r"\mathbf{C}_{u_L} = -\frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{B}_L"),
                _coeff_block("C_xR", "C_xR = I - 0.5 * d_tau[k] * T_ref * AR", r"\mathbf{C}_{x_R} = \mathbf{I} - \frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{A}_R"),
                _coeff_block("C_uR", "C_uR = -0.5 * d_tau[k] * T_ref * BR", r"\mathbf{C}_{u_R} = -\frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{B}_R"),
                _coeff_block("C_T", "C_T = -0.5 * d_tau[k] * (fL + fR)", r"\mathbf{C}_T = -\frac{1}{2}\Delta\tau_k (\mathbf{f}_L + \mathbf{f}_R)", "Coefficient for T/delta_T"),
            ],
            rhs=_rhs_block("rhs", "rhs = -residual_k", r"\mathbf{b} = -\mathbf{r}_k", "Perturbation mode: rhs = -residual"),
            variables=["delta_x[k]", "delta_u[k]", "delta_x[k+1]", "delta_u[k+1]", "delta_T"],
        )

    # ── Case 6: free_final_time + trapezoidal + direct ────────────

    def _case_6(self) -> CaseFormula:
        return CaseFormula(
            case_id="case_6_free_trapezoidal_direct",
            time_mode="free_final_time", discretization="trapezoidal", variable_mode="direct",
            description="free_final_time + trapezoidal + direct",
            residual=_residual_block(
                "residual_k",
                "residual_k = xR - xL - 0.5 * d_tau[k] * T_ref * (fL + fR)",
                r"\mathbf{r}_k = \mathbf{x}_R - \mathbf{x}_L - \frac{1}{2} \Delta\tau_k \, T_{\text{ref}} \, (\mathbf{f}_L + \mathbf{f}_R)",
                "Free-final-time trapezoidal defect",
            ),
            coefficient_blocks=[
                _coeff_block("C_xL", "C_xL = -I - 0.5 * d_tau[k] * T_ref * AL", r"\mathbf{C}_{x_L} = -\mathbf{I} - \frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{A}_L"),
                _coeff_block("C_uL", "C_uL = -0.5 * d_tau[k] * T_ref * BL", r"\mathbf{C}_{u_L} = -\frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{B}_L"),
                _coeff_block("C_xR", "C_xR = I - 0.5 * d_tau[k] * T_ref * AR", r"\mathbf{C}_{x_R} = \mathbf{I} - \frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{A}_R"),
                _coeff_block("C_uR", "C_uR = -0.5 * d_tau[k] * T_ref * BR", r"\mathbf{C}_{u_R} = -\frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{B}_R"),
                _coeff_block("C_T", "C_T = -0.5 * d_tau[k] * (fL + fR)", r"\mathbf{C}_T = -\frac{1}{2}\Delta\tau_k (\mathbf{f}_L + \mathbf{f}_R)", "Coefficient for T"),
            ],
            rhs=_rhs_block(
                "rhs",
                "rhs = C_xL * xL + C_uL * uL + C_xR * xR + C_uR * uR + C_T * T_ref - residual_k",
                r"\mathbf{b} = \mathbf{C}_{x_L}\mathbf{x}_L + \mathbf{C}_{u_L}\mathbf{u}_L + \mathbf{C}_{x_R}\mathbf{x}_R + \mathbf{C}_{u_R}\mathbf{u}_R + \mathbf{C}_T T_{\text{ref}} - \mathbf{r}_k",
                "Direct mode with free-final-time: reference shift RHS",
            ),
            variables=["x[k]", "u[k]", "x[k+1]", "u[k+1]", "T"],
        )

    # ── Case 7: free_final_time + midpoint + perturbation ─────────

    def _case_7(self) -> CaseFormula:
        return CaseFormula(
            case_id="case_7_free_midpoint_perturbation",
            time_mode="free_final_time", discretization="midpoint", variable_mode="perturbation",
            description="free_final_time + midpoint + perturbation",
            midpoint_def={
                "xM": "xM = 0.5 * (xL + xR)", "uM": "uM = 0.5 * (uL + uR)",
                "fM": "fM = eval_f(xM, uM, p)", "AM": "AM = eval_fx(xM, uM, p)", "BM": "BM = eval_fu(xM, uM, p)",
                "latex": r"\mathbf{x}_M = \frac{1}{2}(\mathbf{x}_L + \mathbf{x}_R),\;\mathbf{u}_M = \frac{1}{2}(\mathbf{u}_L + \mathbf{u}_R)",
            },
            residual=_residual_block(
                "residual_k", "residual_k = xR - xL - d_tau[k] * T_ref * fM",
                r"\mathbf{r}_k = \mathbf{x}_R - \mathbf{x}_L - \Delta\tau_k \, T_{\text{ref}} \, \mathbf{f}_M",
                "Free-final-time midpoint defect",
            ),
            coefficient_blocks=[
                _coeff_block("C_xL", "C_xL = -I - 0.5 * d_tau[k] * T_ref * AM", r"\mathbf{C}_{x_L} = -\mathbf{I} - \frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{A}_M"),
                _coeff_block("C_uL", "C_uL = -0.5 * d_tau[k] * T_ref * BM", r"\mathbf{C}_{u_L} = -\frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{B}_M"),
                _coeff_block("C_xR", "C_xR = I - 0.5 * d_tau[k] * T_ref * AM", r"\mathbf{C}_{x_R} = \mathbf{I} - \frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{A}_M"),
                _coeff_block("C_uR", "C_uR = -0.5 * d_tau[k] * T_ref * BM", r"\mathbf{C}_{u_R} = -\frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{B}_M"),
                _coeff_block("C_T", "C_T = -d_tau[k] * fM", r"\mathbf{C}_T = -\Delta\tau_k \, \mathbf{f}_M", "Coefficient for T/delta_T"),
            ],
            rhs=_rhs_block("rhs", "rhs = -residual_k", r"\mathbf{b} = -\mathbf{r}_k", "Perturbation mode: rhs = -residual"),
            variables=["delta_x[k]", "delta_u[k]", "delta_x[k+1]", "delta_u[k+1]", "delta_T"],
        )

    # ── Case 8: free_final_time + midpoint + direct ───────────────

    def _case_8(self) -> CaseFormula:
        return CaseFormula(
            case_id="case_8_free_midpoint_direct",
            time_mode="free_final_time", discretization="midpoint", variable_mode="direct",
            description="free_final_time + midpoint + direct",
            midpoint_def={
                "xM": "xM = 0.5 * (xL + xR)", "uM": "uM = 0.5 * (uL + uR)",
                "fM": "fM = eval_f(xM, uM, p)", "AM": "AM = eval_fx(xM, uM, p)", "BM": "BM = eval_fu(xM, uM, p)",
                "latex": r"\mathbf{x}_M = \frac{1}{2}(\mathbf{x}_L + \mathbf{x}_R),\;\mathbf{u}_M = \frac{1}{2}(\mathbf{u}_L + \mathbf{u}_R)",
            },
            residual=_residual_block(
                "residual_k", "residual_k = xR - xL - d_tau[k] * T_ref * fM",
                r"\mathbf{r}_k = \mathbf{x}_R - \mathbf{x}_L - \Delta\tau_k \, T_{\text{ref}} \, \mathbf{f}_M",
                "Free-final-time midpoint defect",
            ),
            coefficient_blocks=[
                _coeff_block("C_xL", "C_xL = -I - 0.5 * d_tau[k] * T_ref * AM", r"\mathbf{C}_{x_L} = -\mathbf{I} - \frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{A}_M"),
                _coeff_block("C_uL", "C_uL = -0.5 * d_tau[k] * T_ref * BM", r"\mathbf{C}_{u_L} = -\frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{B}_M"),
                _coeff_block("C_xR", "C_xR = I - 0.5 * d_tau[k] * T_ref * AM", r"\mathbf{C}_{x_R} = \mathbf{I} - \frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{A}_M"),
                _coeff_block("C_uR", "C_uR = -0.5 * d_tau[k] * T_ref * BM", r"\mathbf{C}_{u_R} = -\frac{1}{2}\Delta\tau_k T_{\text{ref}} \mathbf{B}_M"),
                _coeff_block("C_T", "C_T = -d_tau[k] * fM", r"\mathbf{C}_T = -\Delta\tau_k \, \mathbf{f}_M", "Coefficient for T"),
            ],
            rhs=_rhs_block(
                "rhs",
                "rhs = C_xL * xL + C_uL * uL + C_xR * xR + C_uR * uR + C_T * T_ref - residual_k",
                r"\mathbf{b} = \mathbf{C}_{x_L}\mathbf{x}_L + \mathbf{C}_{u_L}\mathbf{u}_L + \mathbf{C}_{x_R}\mathbf{x}_R + \mathbf{C}_{u_R}\mathbf{u}_R + \mathbf{C}_T T_{\text{ref}} - \mathbf{r}_k",
                "Direct mode with free-final-time: reference shift RHS",
            ),
            variables=["x[k]", "u[k]", "x[k+1]", "u[k+1]", "T"],
        )


# ── VirtualControlGenerator ───────────────────────────────────────

@dataclass
class VirtualControlTemplate:
    form: str
    enabled: bool = False
    introduced_variables: List[Dict[str, Any]] = field(default_factory=list)
    equality_extra_terms: List[Dict[str, Any]] = field(default_factory=list)
    equality_template_ascii: str = ""
    equality_template_latex: str = ""
    cost_terms: List[Dict[str, Any]] = field(default_factory=list)


class VirtualControlGenerator:
    """虚拟控制模板生成器"""

    def __init__(self, config: DynamicsTranscriptionConfig):
        self._cfg = config

    def generate(self) -> VirtualControlTemplate:
        vc = self._cfg.virtual_control
        if not vc.enabled:
            return self._generate_disabled()
        if vc.form == "signed":
            return self._generate_signed(vc.penalty_weight_symbol)
        if vc.form == "split_nonnegative":
            return self._generate_split_nonnegative(vc.penalty_weight_symbol)
        return self._generate_disabled()

    def _generate_disabled(self) -> VirtualControlTemplate:
        return VirtualControlTemplate(
            form="disabled", enabled=False,
            equality_template_ascii="C_xL * var_xL + C_uL * var_uL + C_xR * var_xR + C_uR * var_uR + C_T * var_T_if_free_time = rhs",
            equality_template_latex=r"\mathbf{C}_{x_L}\delta\mathbf{x}_k + \mathbf{C}_{u_L}\delta\mathbf{u}_k + \mathbf{C}_{x_R}\delta\mathbf{x}_{k+1} + \mathbf{C}_{u_R}\delta\mathbf{u}_{k+1}\;[+\;\mathbf{C}_T\delta T]\;=\;\mathbf{b}",
        )

    def _generate_signed(self, w: str) -> VirtualControlTemplate:
        return VirtualControlTemplate(
            form="signed", enabled=True,
            introduced_variables=[{
                "name": "vc", "shape_symbolic": ["N_minus_1", "nx"], "domain": "free",
                "role": "dynamics_virtual_control",
                "description": "Signed virtual control for dynamics defect relaxation",
            }],
            equality_extra_terms=[{
                "term": "+ vc[k]", "latex": r"+\;\mathbf{v}_c^{(k)}",
                "coefficient": "Identity matrix (I_nx)",
                "description": "Virtual control added to LHS",
            }],
            equality_template_ascii="C_xL * var_xL + C_uL * var_uL + C_xR * var_xR + C_uR * var_uR + C_T * var_T_if_free_time + vc[k] = rhs",
            equality_template_latex=r"\mathbf{C}_{x_L}\delta\mathbf{x}_k + \mathbf{C}_{u_L}\delta\mathbf{u}_k + \mathbf{C}_{x_R}\delta\mathbf{x}_{k+1} + \mathbf{C}_{u_R}\delta\mathbf{u}_{k+1}\;[+\;\mathbf{C}_T\delta T]\;+\;\mathbf{v}_c^{(k)}\;=\;\mathbf{b}",
            cost_terms=[{
                "name": "virtual_control_quadratic_penalty", "type": "quadratic",
                "expression_ascii": f"0.5 * {w} * sum_squares(vc)",
                "expression_latex": r"\frac{1}{2}" + w + r"\sum_{k} \|\mathbf{v}_c^{(k)}\|_2^2",
                "generated_by": "module1_dynamics",
            }],
        )

    def _generate_split_nonnegative(self, w: str) -> VirtualControlTemplate:
        return VirtualControlTemplate(
            form="split_nonnegative", enabled=True,
            introduced_variables=[
                {"name": "vc_plus", "shape_symbolic": ["N_minus_1", "nx"], "domain": "nonnegative", "role": "dynamics_virtual_control", "description": "Positive part of split virtual control"},
                {"name": "vc_minus", "shape_symbolic": ["N_minus_1", "nx"], "domain": "nonnegative", "role": "dynamics_virtual_control", "description": "Negative part of split virtual control"},
            ],
            equality_extra_terms=[{
                "term": "+ vc_plus[k] - vc_minus[k]", "latex": r"+\;\mathbf{v}_{c,+}^{(k)}\;-\;\mathbf{v}_{c,-}^{(k)}",
                "coefficient": "I_nx for vc_plus, -I_nx for vc_minus",
                "description": "Split virtual control added to LHS",
            }],
            equality_template_ascii="C_xL * var_xL + C_uL * var_uL + C_xR * var_xR + C_uR * var_uR + C_T * var_T_if_free_time + vc_plus[k] - vc_minus[k] = rhs",
            equality_template_latex=r"\mathbf{C}_{x_L}\delta\mathbf{x}_k + \mathbf{C}_{u_L}\delta\mathbf{u}_k + \mathbf{C}_{x_R}\delta\mathbf{x}_{k+1} + \mathbf{C}_{u_R}\delta\mathbf{u}_{k+1}\;[+\;\mathbf{C}_T\delta T]\;+\;\mathbf{v}_{c,+}^{(k)} - \mathbf{v}_{c,-}^{(k)}\;=\;\mathbf{b}",
            cost_terms=[{
                "name": "virtual_control_l1_penalty", "type": "linear",
                "expression_ascii": f"{w} * sum(vc_plus + vc_minus)",
                "expression_latex": w + r"\sum_{k} \sum_{i} (v_{c,+,i}^{(k)} + v_{c,-,i}^{(k)})",
                "generated_by": "module1_dynamics",
            }],
        )
