"""
公式生成器 — Module 3 不等式约束的 4 种公式情形

I1: perturbation + no slack
I2: direct + no slack
I3: perturbation + slack
I4: direct + slack

严格按用户说明书第七节生成。
"""

from __future__ import annotations

from typing import Dict, List, Any
from dataclasses import dataclass, field

from .models import Module3InputDef


# ── 辅助: 结构化公式描述 ──────────────────────────────────────────

def _coeff_block(name: str, formula_ascii: str, latex_str: str = "", description: str = "") -> Dict[str, Any]:
    return {"name": name, "formula": formula_ascii, "latex": latex_str or formula_ascii, "description": description}


def _residual_block(name: str, formula_ascii: str, latex_str: str = "", description: str = "") -> Dict[str, Any]:
    return {"name": name, "formula": formula_ascii, "latex": latex_str or formula_ascii, "description": description}


def _rhs_block(name: str, formula_ascii: str, latex_str: str = "", description: str = "") -> Dict[str, Any]:
    return {"name": name, "formula": formula_ascii, "latex": latex_str or formula_ascii, "description": description}


# ── InequalityCaseFormula ─────────────────────────────────────────

@dataclass
class InequalityCaseFormula:
    case_id: str
    variable_mode: str
    slack_enabled: bool
    description: str = ""
    residual: Dict[str, Any] = field(default_factory=dict)
    coefficient_blocks: List[Dict[str, Any]] = field(default_factory=list)
    rhs: Dict[str, Any] = field(default_factory=dict)
    variables: List[str] = field(default_factory=list)


# ── InequalityFormulaGenerator ────────────────────────────────────

class InequalityFormulaGenerator:
    """不等式约束公式生成器 — 4 种情形"""

    def __init__(self, module_input: Module3InputDef):
        self._mi = module_input

    def generate_all_cases(self) -> Dict[str, InequalityCaseFormula]:
        return {
            "inequality_perturbation_no_slack": self._case_perturbation_no_slack(),
            "inequality_direct_no_slack": self._case_direct_no_slack(),
            "inequality_perturbation_with_slack": self._case_perturbation_with_slack(),
            "inequality_direct_with_slack": self._case_direct_with_slack(),
        }

    # ── I1: perturbation + no slack ───────────────────────────────

    def _case_perturbation_no_slack(self) -> InequalityCaseFormula:
        return InequalityCaseFormula(
            case_id="inequality_perturbation_no_slack",
            variable_mode="perturbation",
            slack_enabled=False,
            description="Inequality constraint + perturbation mode + no slack",
            residual=_residual_block(
                "g_ref",
                "g_ref = g(x_ref[k], u_ref[k], p)",
                r"g_{\text{ref}} = g(\mathbf{x}_{\text{ref}}[k], \mathbf{u}_{\text{ref}}[k], \mathbf{p})",
                "Reference constraint value at node k",
            ),
            coefficient_blocks=[
                _coeff_block("C_x", "C_x = Gx", r"\mathbf{C}_x = \mathbf{G}_x",
                            "Jacobian of g w.r.t. state"),
                _coeff_block("C_u", "C_u = Gu", r"\mathbf{C}_u = \mathbf{G}_u",
                            "Jacobian of g w.r.t. control"),
            ],
            rhs=_rhs_block(
                "rhs",
                "rhs = -g_ref",
                r"\mathbf{b} = -g_{\text{ref}}",
                "Perturbation mode: rhs = -residual",
            ),
            variables=["delta_x[k]", "delta_u[k]"],
        )

    # ── I2: direct + no slack ─────────────────────────────────────

    def _case_direct_no_slack(self) -> InequalityCaseFormula:
        return InequalityCaseFormula(
            case_id="inequality_direct_no_slack",
            variable_mode="direct",
            slack_enabled=False,
            description="Inequality constraint + direct mode + no slack",
            residual=_residual_block(
                "g_ref",
                "g_ref = g(x_ref[k], u_ref[k], p)",
                r"g_{\text{ref}} = g(\mathbf{x}_{\text{ref}}[k], \mathbf{u}_{\text{ref}}[k], \mathbf{p})",
                "Reference constraint value at node k",
            ),
            coefficient_blocks=[
                _coeff_block("C_x", "C_x = Gx", r"\mathbf{C}_x = \mathbf{G}_x"),
                _coeff_block("C_u", "C_u = Gu", r"\mathbf{C}_u = \mathbf{G}_u"),
            ],
            rhs=_rhs_block(
                "rhs",
                "rhs = C_x * x_ref[k] + C_u * u_ref[k] - g_ref",
                r"\mathbf{b} = \mathbf{C}_x \mathbf{x}_{\text{ref}}[k] + \mathbf{C}_u \mathbf{u}_{\text{ref}}[k] - g_{\text{ref}}",
                "Direct mode: reference shift RHS",
            ),
            variables=["x[k]", "u[k]"],
        )

    # ── I3: perturbation + slack ──────────────────────────────────

    def _case_perturbation_with_slack(self) -> InequalityCaseFormula:
        return InequalityCaseFormula(
            case_id="inequality_perturbation_with_slack",
            variable_mode="perturbation",
            slack_enabled=True,
            description="Inequality constraint + perturbation mode + slack",
            residual=_residual_block(
                "g_ref",
                "g_ref = g(x_ref[k], u_ref[k], p)",
                r"g_{\text{ref}} = g(\mathbf{x}_{\text{ref}}[k], \mathbf{u}_{\text{ref}}[k], \mathbf{p})",
                "Reference constraint value at node k",
            ),
            coefficient_blocks=[
                _coeff_block("C_x", "C_x = Gx", r"\mathbf{C}_x = \mathbf{G}_x",
                            "Jacobian of g w.r.t. state"),
                _coeff_block("C_u", "C_u = Gu", r"\mathbf{C}_u = \mathbf{G}_u",
                            "Jacobian of g w.r.t. control"),
                _coeff_block("C_s", "C_s = -I", r"\mathbf{C}_s = -\mathbf{I}",
                            "Slack coefficient (negative identity)"),
            ],
            rhs=_rhs_block(
                "rhs",
                "rhs = -g_ref",
                r"\mathbf{b} = -g_{\text{ref}}",
                "Perturbation mode: rhs = -residual",
            ),
            variables=["delta_x[k]", "delta_u[k]", "s_g[k]"],
        )

    # ── I4: direct + slack ────────────────────────────────────────

    def _case_direct_with_slack(self) -> InequalityCaseFormula:
        return InequalityCaseFormula(
            case_id="inequality_direct_with_slack",
            variable_mode="direct",
            slack_enabled=True,
            description="Inequality constraint + direct mode + slack",
            residual=_residual_block(
                "g_ref",
                "g_ref = g(x_ref[k], u_ref[k], p)",
                r"g_{\text{ref}} = g(\mathbf{x}_{\text{ref}}[k], \mathbf{u}_{\text{ref}}[k], \mathbf{p})",
                "Reference constraint value at node k",
            ),
            coefficient_blocks=[
                _coeff_block("C_x", "C_x = Gx", r"\mathbf{C}_x = \mathbf{G}_x"),
                _coeff_block("C_u", "C_u = Gu", r"\mathbf{C}_u = \mathbf{G}_u"),
                _coeff_block("C_s", "C_s = -I", r"\mathbf{C}_s = -\mathbf{I}",
                            "Slack coefficient (negative identity)"),
            ],
            rhs=_rhs_block(
                "rhs",
                "rhs = C_x * x_ref[k] + C_u * u_ref[k] - g_ref",
                r"\mathbf{b} = \mathbf{C}_x \mathbf{x}_{\text{ref}}[k] + \mathbf{C}_u \mathbf{u}_{\text{ref}}[k] - g_{\text{ref}}",
                "Direct mode: reference shift RHS",
            ),
            variables=["x[k]", "u[k]", "s_g[k]"],
        )
