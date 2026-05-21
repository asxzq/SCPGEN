"""
公式生成器 — Module 2 等式约束的 2 种公式情形

E1: perturbation: C_x*δx + C_u*δu = -h_ref
E2: direct:      C_x*x + C_u*u = C_x*x_ref + C_u*u_ref - h_ref

严格按用户说明书第六节生成。
"""

from __future__ import annotations

from typing import Dict, List, Any
from dataclasses import dataclass, field

from .models import Module2InputDef


# ── 辅助: 结构化公式描述 ──────────────────────────────────────────

def _coeff_block(name: str, formula_ascii: str, latex_str: str = "", description: str = "") -> Dict[str, Any]:
    return {"name": name, "formula": formula_ascii, "latex": latex_str or formula_ascii, "description": description}


def _residual_block(name: str, formula_ascii: str, latex_str: str = "", description: str = "") -> Dict[str, Any]:
    return {"name": name, "formula": formula_ascii, "latex": latex_str or formula_ascii, "description": description}


def _rhs_block(name: str, formula_ascii: str, latex_str: str = "", description: str = "") -> Dict[str, Any]:
    return {"name": name, "formula": formula_ascii, "latex": latex_str or formula_ascii, "description": description}


# ── EqualityCaseFormula ───────────────────────────────────────────

@dataclass
class EqualityCaseFormula:
    case_id: str
    variable_mode: str
    description: str = ""
    residual: Dict[str, Any] = field(default_factory=dict)
    coefficient_blocks: List[Dict[str, Any]] = field(default_factory=list)
    rhs: Dict[str, Any] = field(default_factory=dict)
    variables: List[str] = field(default_factory=list)


# ── EqualityFormulaGenerator ──────────────────────────────────────

class EqualityFormulaGenerator:
    """等式约束公式生成器 — 2 种情形"""

    def __init__(self, module_input: Module2InputDef):
        self._mi = module_input

    def generate_all_cases(self) -> Dict[str, EqualityCaseFormula]:
        return {
            "equality_perturbation": self._case_perturbation(),
            "equality_direct": self._case_direct(),
        }

    # ── E1: perturbation ──────────────────────────────────────────

    def _case_perturbation(self) -> EqualityCaseFormula:
        return EqualityCaseFormula(
            case_id="equality_perturbation",
            variable_mode="perturbation",
            description="Equality constraint + perturbation mode",
            residual=_residual_block(
                "h_ref",
                "h_ref = h(x_ref[k], u_ref[k], p)",
                r"h_{\text{ref}} = h(\mathbf{x}_{\text{ref}}[k], \mathbf{u}_{\text{ref}}[k], \mathbf{p})",
                "Reference constraint value at node k",
            ),
            coefficient_blocks=[
                _coeff_block("C_x", "C_x = Hx", r"\mathbf{C}_x = \mathbf{H}_x",
                            "Jacobian of h w.r.t. state"),
                _coeff_block("C_u", "C_u = Hu", r"\mathbf{C}_u = \mathbf{H}_u",
                            "Jacobian of h w.r.t. control"),
            ],
            rhs=_rhs_block(
                "rhs",
                "rhs = -h_ref",
                r"\mathbf{b} = -h_{\text{ref}}",
                "Perturbation mode: rhs = -residual",
            ),
            variables=["delta_x[k]", "delta_u[k]"],
        )

    # ── E2: direct ────────────────────────────────────────────────

    def _case_direct(self) -> EqualityCaseFormula:
        return EqualityCaseFormula(
            case_id="equality_direct",
            variable_mode="direct",
            description="Equality constraint + direct mode",
            residual=_residual_block(
                "h_ref",
                "h_ref = h(x_ref[k], u_ref[k], p)",
                r"h_{\text{ref}} = h(\mathbf{x}_{\text{ref}}[k], \mathbf{u}_{\text{ref}}[k], \mathbf{p})",
                "Reference constraint value at node k",
            ),
            coefficient_blocks=[
                _coeff_block("C_x", "C_x = Hx", r"\mathbf{C}_x = \mathbf{H}_x",
                            "Jacobian of h w.r.t. state"),
                _coeff_block("C_u", "C_u = Hu", r"\mathbf{C}_u = \mathbf{H}_u",
                            "Jacobian of h w.r.t. control"),
            ],
            rhs=_rhs_block(
                "rhs",
                "rhs = C_x * x_ref[k] + C_u * u_ref[k] - h_ref",
                r"\mathbf{b} = \mathbf{C}_x \mathbf{x}_{\text{ref}}[k] + \mathbf{C}_u \mathbf{u}_{\text{ref}}[k] - h_{\text{ref}}",
                "Direct mode: reference shift RHS",
            ),
            variables=["x[k]", "u[k]"],
        )
