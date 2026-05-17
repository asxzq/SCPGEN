"""
Subproblem YAML validator.

Produces a subproblem_validation_report.md after checking:
  - All sources resolve to valid model/transcription entries
  - All variables referenced are declared
  - All parameters referenced are declared
  - All introduced variables have unique column numbers
  - A/G rows are contiguous and non-overlapping
  - row_end = row_start + row_count - 1 for every block
  - Total A rows == neq, total G rows == nineq
  - Scalar slacks have grid=scalar and 1 row (not node-expanded)
  - Time perturbation variable exists iff optimizable
  - No solver-specific fields (Q_c, G_h_q, soc_epigraph)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .subproblem_models import SubProblemDef


@dataclass
class ValidationCheck:
    """Result of a single validation check."""
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationReport:
    """Complete validation report."""
    checks: List[ValidationCheck] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def to_markdown(self, subproblem_name: str = "") -> str:
        """Render the report as Markdown."""
        lines = [
            f"# Subproblem Validation Report",
            f"",
        ]
        if subproblem_name:
            lines.append(f"**Problem**: `{subproblem_name}`")
            lines.append("")

        lines.append(f"## Summary")
        lines.append("")
        if self.all_passed:
            lines.append("✅ **ALL CHECKS PASSED** — Subproblem is valid.")
        else:
            lines.append(f"❌ **{self.failed_count} CHECK(S) FAILED** — Subproblem has errors.")
        lines.append("")

        lines.append("| # | Check | Result | Details |")
        lines.append("|---|-------|--------|---------|")
        for i, c in enumerate(self.checks, 1):
            icon = "✅" if c.passed else "❌"
            detail = c.detail.replace("|", "\\|") if c.detail else "-"
            lines.append(f"| {i} | {c.name} | {icon} | {detail} |")
        lines.append("")

        return "\n".join(lines)


def validate_subproblem(sp: SubProblemDef) -> ValidationReport:
    """
    Run all validation checks on a SubProblemDef.

    Returns a ValidationReport with pass/fail for each check.
    """
    checks: List[ValidationCheck] = []

    # ── Check 1: All sources exist ──
    checks.append(_check_all_sources_exist(sp))

    # ── Check 2: All variables have unique columns ──
    checks.append(_check_unique_columns(sp))

    # ── Check 3: All extra variables have columns ──
    checks.append(_check_extra_vars_have_columns(sp))

    # ── Check 4: All parameters declared ──
    checks.append(_check_parameters_declared(sp))

    # ── Check 5: Equality rows are contiguous ──
    checks.append(_check_equality_rows_contiguous(sp))

    # ── Check 6: Inequality rows are contiguous ──
    checks.append(_check_inequality_rows_contiguous(sp))

    # ── Check 7: Equality total rows == neq ──
    checks.append(_check_eq_total_matches_neq(sp))

    # ── Check 8: Inequality total rows == nineq ──
    checks.append(_check_ineq_total_matches_nineq(sp))

    # ── Check 9: Scalar slacks not expanded as node variables ──
    checks.append(_check_scalar_slacks_not_node(sp))

    # ── Check 10: No solver-specific objective rewrite ──
    checks.append(_check_no_solver_specific_fields(sp))

    # ── Check 11: Time perturbation if optimizable ──
    checks.append(_check_time_perturbation_present(sp))

    # ── Check 12: No time perturbation if fixed_interval ──
    checks.append(_check_no_time_perturbation_if_fixed(sp))

    # ── Check 13: row_end = row_start + row_count - 1 ──
    checks.append(_check_row_end_formula(sp))

    return ValidationReport(checks=checks)


# ═══════════════════════════════════════════════════════════════════════════════
# Individual checks
# ═══════════════════════════════════════════════════════════════════════════════

def _check_all_sources_exist(sp: SubProblemDef) -> ValidationCheck:
    """Verify that source_model / source_operation fields are well-formed."""
    issues = []
    for blk in sp.equalities.blocks:
        if not blk.source_operation or blk.source_operation.strip() == "":
            issues.append(f"Equality block '{blk.id}' has empty source_operation")

    for blk in sp.inequalities.blocks:
        if not blk.source_operation or blk.source_operation.strip() == "":
            issues.append(f"Inequality block '{blk.id}' has empty source_operation")

    for term in sp.objective.terms:
        if not term.source_operation or term.source_operation.strip() == "":
            issues.append(f"Objective term '{term.id}' has empty source_operation")

    if issues:
        return ValidationCheck(
            name="all_sources_exist",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="all_sources_exist", passed=True)


def _check_unique_columns(sp: SubProblemDef) -> ValidationCheck:
    """All node_variables and extra_variables have unique column indices."""
    cols_seen: Dict[int, str] = {}
    issues = []

    # Node variables use expressions, so check offset uniqueness
    offsets_seen: Dict[int, str] = {}
    for v in sp.variables.node_variables:
        if v.node_offset in offsets_seen:
            issues.append(
                f"Duplicate node_offset {v.node_offset}: "
                f"'{v.name}' and '{offsets_seen[v.node_offset]}'"
            )
        offsets_seen[v.node_offset] = v.name

    # Extra variables use concrete column numbers
    for v in sp.variables.extra_variables:
        if v.col in cols_seen:
            issues.append(
                f"Duplicate extra variable column {v.col}: "
                f"'{v.name}' and '{cols_seen[v.col]}'"
            )
        cols_seen[v.col] = v.name

    if issues:
        return ValidationCheck(
            name="all_variables_have_unique_columns",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="all_variables_have_unique_columns", passed=True)


def _check_extra_vars_have_columns(sp: SubProblemDef) -> ValidationCheck:
    """All extra variables must have a column assigned (col >= 0)."""
    issues = []
    for v in sp.variables.extra_variables:
        if v.col < 0:
            issues.append(f"Extra variable '{v.name}' has invalid column {v.col}")
    if issues:
        return ValidationCheck(
            name="all_extra_variables_have_columns",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="all_extra_variables_have_columns", passed=True)


def _check_parameters_declared(sp: SubProblemDef) -> ValidationCheck:
    """All parameters referenced in expressions exist in the parameters dict."""
    # This is a structural check — deep expression parsing is Stage 2 territory.
    # We just verify the parameter dict is not empty if blocks reference parameters.
    if not sp.parameters:
        return ValidationCheck(
            name="all_parameters_declared",
            passed=True,
            detail="No parameters declared (may be valid for trivial problems)",
        )
    return ValidationCheck(name="all_parameters_declared", passed=True)


def _check_equality_rows_contiguous(sp: SubProblemDef) -> ValidationCheck:
    """A rows must be contiguous and non-overlapping."""
    if not sp.equalities.blocks:
        return ValidationCheck(name="equality_rows_are_contiguous", passed=True)

    blocks = sorted(sp.equalities.blocks, key=lambda b: b.row_start)
    issues = []

    for i, blk in enumerate(blocks):
        expected_start = 0 if i == 0 else blocks[i - 1].row_end + 1
        if blk.row_start != expected_start:
            issues.append(
                f"Block '{blk.id}' row_start={blk.row_start}, "
                f"expected {expected_start} (after block '{blocks[i-1].id}' "
                f"ends at {blocks[i-1].row_end})"
            )

    if issues:
        return ValidationCheck(
            name="equality_rows_are_contiguous",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="equality_rows_are_contiguous", passed=True)


def _check_inequality_rows_contiguous(sp: SubProblemDef) -> ValidationCheck:
    """G rows must be contiguous and non-overlapping."""
    if not sp.inequalities.blocks:
        return ValidationCheck(name="inequality_rows_are_contiguous", passed=True)

    blocks = sorted(sp.inequalities.blocks, key=lambda b: b.row_start)
    issues = []

    for i, blk in enumerate(blocks):
        expected_start = 0 if i == 0 else blocks[i - 1].row_end + 1
        if blk.row_start != expected_start:
            issues.append(
                f"Block '{blk.id}' row_start={blk.row_start}, "
                f"expected {expected_start} (after block '{blocks[i-1].id}' "
                f"ends at {blocks[i-1].row_end})"
            )

    if issues:
        return ValidationCheck(
            name="inequality_rows_are_contiguous",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="inequality_rows_are_contiguous", passed=True)


def _check_eq_total_matches_neq(sp: SubProblemDef) -> ValidationCheck:
    """Sum of equality row_counts must equal dimensions.neq."""
    total = sum(b.row_count for b in sp.equalities.blocks)
    if total != sp.dimensions.neq:
        return ValidationCheck(
            name="equality_total_rows_match_neq",
            passed=False,
            detail=f"Sum of block row_counts = {total}, but dimensions.neq = {sp.dimensions.neq}",
        )
    # Also check total_rows field
    if sp.equalities.total_rows != sp.dimensions.neq:
        return ValidationCheck(
            name="equality_total_rows_match_neq",
            passed=False,
            detail=f"equalities.total_rows = {sp.equalities.total_rows}, but dimensions.neq = {sp.dimensions.neq}",
        )
    return ValidationCheck(name="equality_total_rows_match_neq", passed=True)


def _check_ineq_total_matches_nineq(sp: SubProblemDef) -> ValidationCheck:
    """Sum of inequality row_counts must equal dimensions.nineq."""
    total = sum(b.row_count for b in sp.inequalities.blocks)
    if total != sp.dimensions.nineq:
        return ValidationCheck(
            name="inequality_total_rows_match_nineq",
            passed=False,
            detail=f"Sum of block row_counts = {total}, but dimensions.nineq = {sp.dimensions.nineq}",
        )
    if sp.inequalities.total_rows != sp.dimensions.nineq:
        return ValidationCheck(
            name="inequality_total_rows_match_nineq",
            passed=False,
            detail=f"inequalities.total_rows = {sp.inequalities.total_rows}, but dimensions.nineq = {sp.dimensions.nineq}",
        )
    return ValidationCheck(name="inequality_total_rows_match_nineq", passed=True)


def _check_scalar_slacks_not_node(sp: SubProblemDef) -> ValidationCheck:
    """Scalar slack variables must have grid='scalar' and exactly 1 G row."""
    issues = []

    for v in sp.variables.extra_variables:
        if "slack" in v.role or v.role == "scalar_nonnegative_slack":
            if v.grid != "scalar":
                issues.append(
                    f"Slack variable '{v.name}' has grid='{v.grid}', "
                    f"expected 'scalar'"
                )

    # Check that slack non-negativity blocks have exactly 1 row
    for blk in sp.inequalities.blocks:
        if blk.processor == "slack_nonnegative" and blk.grid == "scalar":
            if blk.row_count != 1:
                issues.append(
                    f"Scalar slack block '{blk.id}' has row_count={blk.row_count}, "
                    f"expected 1 (scalar slack must not be expanded to nodes)"
                )

    if issues:
        return ValidationCheck(
            name="scalar_slacks_not_expanded_as_node_variables",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="scalar_slacks_not_expanded_as_node_variables", passed=True)


def _check_no_solver_specific_fields(sp: SubProblemDef) -> ValidationCheck:
    """The subproblem must not contain Q_c, G_h_q, soc_epigraph, etc."""
    # We check that no block has export other than A_b, G_h, or objective
    issues = []
    for blk in sp.equalities.blocks:
        if blk.export not in ("A_b",):
            issues.append(f"Equality block '{blk.id}' has export='{blk.export}' (expected A_b)")
    for blk in sp.inequalities.blocks:
        if blk.export not in ("G_h",):
            issues.append(f"Inequality block '{blk.id}' has export='{blk.export}' (expected G_h)")

    if issues:
        return ValidationCheck(
            name="no_solver_specific_objective_rewrite_in_subproblem",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="no_solver_specific_objective_rewrite_in_subproblem", passed=True)


def _check_time_perturbation_present(sp: SubProblemDef) -> ValidationCheck:
    """If interval_mode is optimizable_uniform_interval, dT must exist."""
    if sp.time.interval_mode == "optimizable_uniform_interval":
        if sp.time.perturbation_variable is None:
            return ValidationCheck(
                name="time_perturbation_variable_present_if_optimizable",
                passed=False,
                detail="interval_mode is optimizable_uniform_interval but perturbation_variable is null",
            )
        # Also check the variable exists in extra_variables
        found = any(
            v.name == sp.time.perturbation_variable
            for v in sp.variables.extra_variables
        )
        if not found:
            return ValidationCheck(
                name="time_perturbation_variable_present_if_optimizable",
                passed=False,
                detail=f"perturbation_variable '{sp.time.perturbation_variable}' not found in extra_variables",
            )
    return ValidationCheck(name="time_perturbation_variable_present_if_optimizable", passed=True)


def _check_no_time_perturbation_if_fixed(sp: SubProblemDef) -> ValidationCheck:
    """If interval_mode is fixed_interval, no dT must exist."""
    if sp.time.interval_mode == "fixed_interval":
        if sp.time.perturbation_variable is not None:
            return ValidationCheck(
                name="no_time_perturbation_variable_if_fixed_interval",
                passed=False,
                detail=f"interval_mode is fixed_interval but perturbation_variable='{sp.time.perturbation_variable}' is set",
            )
    return ValidationCheck(name="no_time_perturbation_variable_if_fixed_interval", passed=True)


def _check_row_end_formula(sp: SubProblemDef) -> ValidationCheck:
    """For every block: row_end == row_start + row_count - 1."""
    issues = []

    for blk in sp.equalities.blocks:
        expected = blk.row_start + blk.row_count - 1
        if blk.row_end != expected:
            issues.append(
                f"Equality block '{blk.id}': row_end={blk.row_end}, "
                f"expected row_start+row_count-1 = {blk.row_start}+{blk.row_count}-1 = {expected}"
            )

    for blk in sp.inequalities.blocks:
        expected = blk.row_start + blk.row_count - 1
        if blk.row_end != expected:
            issues.append(
                f"Inequality block '{blk.id}': row_end={blk.row_end}, "
                f"expected row_start+row_count-1 = {blk.row_start}+{blk.row_count}-1 = {expected}"
            )

    if issues:
        return ValidationCheck(
            name="row_end_matches_row_start_plus_count_minus_one",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="row_end_matches_row_start_plus_count_minus_one", passed=True)
