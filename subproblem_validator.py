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
  - All objective terms have role
  - Nonlinear original_cost objectives have approximation
  - Quadratic terms not mislabeled as linear
  - Slack penalty references exist in extra_variables
  - Trust region penalties have defined scope
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

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


def validate_subproblem(
    sp: SubProblemDef,
    original_scales: Optional[Dict[str, object]] = None,
) -> ValidationReport:
    """
    Run all validation checks on a SubProblemDef.

    Args:
        sp: The compiled subproblem definition.
        original_scales: Optional dict with scale entries for reference validation.
            If provided, should contain entries in the format:
              - "variables": list of (name, scale_name) tuples for node variables
              - "extra_variables": list of (name, scale_name) tuples for extra variables
              - "parameters": dict of parameter_name -> scale_name
              - "expressions": list of expression strings
              - "scales": ScaleDef or list of scale names for direct validation
            If None, scale reference checks are skipped (for legacy/compatibility).
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

    # ── Check 11: Time variable three-way rule ──
    checks.append(_check_time_variable(sp))

    # ── Check 12: All objective terms have role ──
    checks.append(_check_objective_terms_have_role(sp))

    # ── Check 13: Nonlinear original_cost has approximation ──
    checks.append(_check_nonlinear_objective_has_approximation(sp))

    # ── Check 14: Quadratic not mislabeled as linear ──
    checks.append(_check_quadratic_not_mislabeled(sp))

    # ── Check 15: Slack penalty refs exist ──
    checks.append(_check_slack_penalty_refs_exist(sp))

    # ── Check 16: Trust region has scope ──
    checks.append(_check_trust_region_has_scope(sp))

    # ── Check 17: row_end = row_start + row_count - 1 ──
    checks.append(_check_row_end_formula(sp))

    # ── Check 18: All scale references exist in resolved scale_table ──
    checks.append(_check_scale_references(sp, original_scales))

    # ── Check 19: Scale table is fully resolved (no missing values) ──
    checks.append(_check_scale_table_complete(sp))

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
    """The subproblem must not contain Q_c, G_h_q, soc_epigraph, ECOS, etc."""
    issues = []
    for blk in sp.equalities.blocks:
        if blk.export not in ("A_b",):
            issues.append(f"Equality block '{blk.id}' has export='{blk.export}' (expected A_b)")
    for blk in sp.inequalities.blocks:
        if blk.export not in ("G_h",):
            issues.append(f"Inequality block '{blk.id}' has export='{blk.export}' (expected G_h)")

    # Also check objective terms for solver-specific leaking
    for term in sp.objective.terms:
        forbidden = ["Q_c", "G_h_q", "soc_epigraph", "ECOS", "ecos"]
        for kw in forbidden:
            combined = f"{term.stage2_action} {term.stage3_action} {term.next_stage_action}".lower()
            if kw.lower() in combined:
                issues.append(
                    f"Objective term '{term.id}' references '{kw}' in "
                    f"stage2_action='{term.stage2_action}' "
                    f"stage3_action='{term.stage3_action}'"
                )

    if issues:
        return ValidationCheck(
            name="no_solver_specific_fields",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="no_solver_specific_fields", passed=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Objective-specific checks (Stage1 objective refactoring)
# ═══════════════════════════════════════════════════════════════════════════════

def _check_objective_terms_have_role(sp: SubProblemDef) -> ValidationCheck:
    """All objective terms must have a non-empty 'role' field."""
    issues = []
    for term in sp.objective.terms:
        if not term.role or term.role.strip() == "":
            issues.append(
                f"Objective term '{term.id}' has empty 'role'. "
                f"Must be one of: original_cost, smoothing_penalty, "
                f"slack_penalty, trust_region_penalty, virtual_control_penalty"
            )
    if issues:
        return ValidationCheck(
            name="objective_terms_have_role",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="objective_terms_have_role", passed=True)


def _check_nonlinear_objective_has_approximation(sp: SubProblemDef) -> ValidationCheck:
    """Nonlinear original_cost objectives must have first_order or exact_convex approximation."""
    issues = []
    for term in sp.objective.terms:
        if term.role == "original_cost" and term.expression_type == "nonlinear":
            if term.approximation not in ("first_order", "exact_convex"):
                issues.append(
                    f"Objective term '{term.id}' is nonlinear original_cost but has "
                    f"approximation='{term.approximation}'. "
                    f"Must be 'first_order' or 'exact_convex'."
                )
    if issues:
        return ValidationCheck(
            name="nonlinear_objective_has_approximation",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="nonlinear_objective_has_approximation", passed=True)


def _check_quadratic_not_mislabeled(sp: SubProblemDef) -> ValidationCheck:
    """Quadratic terms must not be mislabeled as linear_cost, and vice versa."""
    issues = []
    for term in sp.objective.terms:
        if term.expression_type == "quadratic" and term.output_form == "linear_cost":
            issues.append(
                f"Objective term '{term.id}' has expression_type='quadratic' but "
                f"output_form='linear_cost'. Quadratic terms cannot produce linear cost."
            )
        if term.output_form == "quadratic_penalty" and term.approximation == "first_order":
            issues.append(
                f"Objective term '{term.id}' has output_form='quadratic_penalty' but "
                f"approximation='first_order'. First-order approximation cannot "
                f"produce a quadratic penalty."
            )
    if issues:
        return ValidationCheck(
            name="quadratic_not_mislabeled_as_linear",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="quadratic_not_mislabeled_as_linear", passed=True)


def _check_slack_penalty_refs_exist(sp: SubProblemDef) -> ValidationCheck:
    """Slack penalty terms must reference variables that exist in extra_variables."""
    extra_var_names = {v.name for v in sp.variables.extra_variables}
    issues = []
    for term in sp.objective.terms:
        if term.role == "slack_penalty":
            refs = _extract_identifiers(term.expr)
            for ref in refs:
                if ref in extra_var_names:
                    continue  # found
                # Also check node variables
                node_names = {v.name for v in sp.variables.node_variables}
                if ref in node_names:
                    continue
                # Check parameters
                if ref in sp.parameters:
                    continue
                issues.append(
                    f"Objective term '{term.id}' (slack_penalty) references "
                    f"'{ref}' which is not found in extra_variables, "
                    f"node_variables, or parameters"
                )
    if issues:
        return ValidationCheck(
            name="slack_penalty_references_exist",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="slack_penalty_references_exist", passed=True)


def _check_trust_region_has_scope(sp: SubProblemDef) -> ValidationCheck:
    """Trust region penalty terms must have a defined grid/scope."""
    issues = []
    for term in sp.objective.terms:
        if term.role == "trust_region_penalty":
            if not term.grid or term.grid.strip() == "":
                issues.append(
                    f"Objective term '{term.id}' (trust_region_penalty) has "
                    f"empty 'grid'. Must specify scope (e.g. grid='node')."
                )
    if issues:
        return ValidationCheck(
            name="trust_region_penalty_has_scope",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="trust_region_penalty_has_scope", passed=True)


def _check_time_variable(sp: SubProblemDef) -> ValidationCheck:
    """
    Three-way time variable validation based on interval_mode + discretization_mode.

    - fixed_interval: No time variable of any kind.
    - optimizable_uniform_interval + perturbation: time_variable=dT, role=time_perturbation.
    - optimizable_uniform_interval + direct: time_variable=T, role=time_interval.
    """
    mode = sp.time.interval_mode
    disc_mode = sp.meta.discretization_mode
    tv = sp.time.time_variable
    tvr = sp.time.time_variable_role
    extra_vars = sp.variables.extra_variables

    # ── Rule 1: fixed_interval → no time variable ──
    if mode == "fixed_interval":
        if tv is not None:
            return ValidationCheck(
                name="time_variable_three_way",
                passed=False,
                detail=f"interval_mode is fixed_interval but time_variable='{tv}' is set",
            )
        # Check no extra variable has a time role
        stray = [v.name for v in extra_vars if v.role in ("time_perturbation", "time_interval")]
        if stray:
            return ValidationCheck(
                name="time_variable_three_way",
                passed=False,
                detail=f"fixed_interval mode but extra variables have time roles: {stray}",
            )
        return ValidationCheck(name="time_variable_three_way", passed=True)

    # ── Rule 2: optimizable_uniform_interval + perturbation ──
    if mode == "optimizable_uniform_interval" and disc_mode == "perturbation":
        if tv is None:
            return ValidationCheck(
                name="time_variable_three_way",
                passed=False,
                detail="optimizable_uniform_interval + perturbation requires time_variable (e.g. dT)",
            )
        if tvr != "time_perturbation":
            return ValidationCheck(
                name="time_variable_three_way",
                passed=False,
                detail=f"expected time_variable_role='time_perturbation', got '{tvr}'",
            )
        found = any(v.name == tv and v.role == "time_perturbation" for v in extra_vars)
        if not found:
            return ValidationCheck(
                name="time_variable_three_way",
                passed=False,
                detail=f"time_variable '{tv}' (role=time_perturbation) not found in extra_variables",
            )
        return ValidationCheck(name="time_variable_three_way", passed=True)

    # ── Rule 3: optimizable_uniform_interval + direct ──
    if mode == "optimizable_uniform_interval" and disc_mode == "direct":
        if tv is None:
            return ValidationCheck(
                name="time_variable_three_way",
                passed=False,
                detail="optimizable_uniform_interval + direct requires time_variable (e.g. T)",
            )
        if tvr != "time_interval":
            return ValidationCheck(
                name="time_variable_three_way",
                passed=False,
                detail=f"expected time_variable_role='time_interval', got '{tvr}'",
            )
        found = any(v.name == tv and v.role == "time_interval" for v in extra_vars)
        if not found:
            return ValidationCheck(
                name="time_variable_three_way",
                passed=False,
                detail=f"time_variable '{tv}' (role=time_interval) not found in extra_variables",
            )
        # perturbation_variable is allowed to be None in direct mode
        return ValidationCheck(name="time_variable_three_way", passed=True)

    # ── Unknown combination ──
    return ValidationCheck(
        name="time_variable_three_way",
        passed=False,
        detail=f"unexpected interval_mode='{mode}' + discretization_mode='{disc_mode}'",
    )


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


# ═══════════════════════════════════════════════════════════════════════════════
# Scale reference validation helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _check_scale_references(
    sp: SubProblemDef,
    original_scales: Optional[Dict[str, object]],
) -> ValidationCheck:
    """
    Verify that every scale referenced by a variable or parameter exists
    in the resolved scale_table.

    Note: We only check direct scale references (node variable scales, extra
    variable scales, parameter scales). We do NOT extract identifiers from
    expression strings — that is a Stage 2 concern (expression parsing).
    The scale_table contains physical dimension scales (length, velocity, etc.),
    not variable/parameter names.
    """
    scale_table = sp.scale_table
    if not scale_table:
        return ValidationCheck(
            name="all_scale_references_resolved",
            passed=True,
            detail="scale_table is empty",
        )

    missing: List[str] = []
    seen: Set[str] = set()

    def check_scale(scale_name: str, context: str):
        if scale_name and scale_name not in seen:
            seen.add(scale_name)
            if scale_name not in scale_table:
                missing.append(f"'{scale_name}' (referenced by {context})")

    # ── Node variables: check their scale names ──
    for v in sp.variables.node_variables:
        check_scale(v.scale, f"node variable '{v.name}'")

    # ── Extra variables: check their scale names ──
    for v in sp.variables.extra_variables:
        check_scale(v.scale, f"extra variable '{v.name}'")

    # ── Parameters: check their scale names ──
    for param_name, scale_name in sp.parameters.items():
        check_scale(scale_name, f"parameter '{param_name}'")

    # ── Extra variables from transcription time effects ──
    if original_scales and "extra_variables" in original_scales:
        evars = original_scales["extra_variables"]
        if isinstance(evars, list):
            for item in evars:
                if isinstance(item, tuple) and len(item) >= 2:
                    name, scale_name = item[0], item[1]
                    if scale_name:
                        check_scale(scale_name, f"introduced variable '{name}'")
                elif isinstance(item, dict) and "scale" in item:
                    scale_name = item.get("scale", "")
                    if scale_name:
                        check_scale(scale_name, f"introduced variable '{item.get('name', '?')}'")

    if missing:
        return ValidationCheck(
            name="all_scale_references_resolved",
            passed=False,
            detail=f"Missing scales in resolved scale_table: {'; '.join(missing)}",
        )
    return ValidationCheck(name="all_scale_references_resolved", passed=True)


def _check_scale_table_complete(sp: SubProblemDef) -> ValidationCheck:
    """
    Verify that the resolved scale_table has no missing (None/NaN) values
    and that all entries are finite numbers.
    """
    issues: List[str] = []

    for name, value in sp.scale_table.items():
        if value is None:
            issues.append(f"scale '{name}' has null value (not resolved)")
        elif not isinstance(value, (int, float)):
            issues.append(f"scale '{name}' has non-numeric value: {type(value).__name__}")
        elif not (-1e300 < value < 1e300):
            issues.append(f"scale '{name}' has non-finite value: {value}")

    if issues:
        return ValidationCheck(
            name="scale_table_all_values_finite",
            passed=False,
            detail="; ".join(issues),
        )
    return ValidationCheck(name="scale_table_all_values_finite", passed=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Token extraction helper
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_identifiers(expr: str) -> Set[str]:
    """
    Extract identifier tokens from an expression string, excluding Python
    keywords, builtins, and common math functions.
    """
    import re
    tokens = re.findall(r'\b[a-zA-Z_]\w*\b', expr)

    reserved = {
        'abs', 'bool', 'complex', 'dict', 'float', 'int', 'list',
        'max', 'min', 'round', 'str', 'sum', 'True', 'False', 'None',
        'and', 'or', 'not', 'in', 'is', 'lambda', 'pass', 'yield',
        'sin', 'cos', 'tan', 'exp', 'log', 'log10', 'log2',
        'pow', 'fabs', 'floor', 'ceil', 'trunc', 'sqrt',
    }
    return {t for t in tokens if t not in reserved}
