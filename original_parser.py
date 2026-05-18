"""
Stage 1 parser: Original YAML → OriginalProblemDef.

Reads unified YAML problem descriptions containing:
  - meta: problem metadata (name, version, etc.)
  - grid: mesh definition (N, state/control grids, time policy)
  - scale: physical dimension scaling table
  - model: variables, parameters, expressions, dynamics, constraints, objectives
  - transcription: discretization scheme and operations

This is the first stage of a two-stage compiler:
  Stage 1: Original YAML → SubProblem YAML (this module)
  Stage 2: SubProblem YAML → C code (future)
"""

import re
from pathlib import Path
from typing import Dict, List

import jsonschema
import yaml

from .original_problem import (
    MetaDef, GridDef, TimeDef, ScaleEntry, ScaleDef,
    OrigVariablesDef, OrigExpressionDef, OrigDynamicsDef,
    OrigEqualityDef, OrigInequalityDef, OrigObjectiveDef,
    OrigModelDef, OrigTranscriptionDef, OperationDecl as NewOperationDecl,
    OperationEffects, IntroducedVarEffect, ReplacedConstraint,
    AddedObjectiveTerm, ApproximationDecl, CodegenDef, OriginalProblemDef,
)


def parse_original_problem(filepath: str) -> OriginalProblemDef:
    """
    Parse a unified original-problem YAML file.

    Reads meta, grid, scale, model, transcription, codegen sections
    and returns an OriginalProblemDef.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Problem file not found: {filepath}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # ── JSON Schema validation ──
    from .schema import UNIFIED_ORIGINAL_SCHEMA
    try:
        jsonschema.validate(data, UNIFIED_ORIGINAL_SCHEMA)
    except jsonschema.ValidationError as e:
        raise ValueError(f"YAML schema validation failed: {e.message}") from e

    for key in ("meta", "grid", "model", "transcription"):
        if key not in data:
            raise ValueError(f"YAML file must contain top-level '{key}' key")

    # ── meta ──
    meta_raw = data["meta"]
    meta = MetaDef(
        name=meta_raw["name"],
        version=meta_raw.get("version", "scp_original_problem_v0.1"),
        macro_prefix=meta_raw.get("macro_prefix", meta_raw["name"].upper()),
        function_prefix=meta_raw.get("function_prefix", meta_raw["name"].lower()),
        scalar_type=meta_raw.get("scalar_type", "double"),
        index_type=meta_raw.get("index_type", "idxint"),
    )

    # ── grid ──
    grid_raw = data["grid"]
    time_raw = grid_raw.get("time", {})
    time_def = TimeDef(
        interval_mode=time_raw.get("interval_mode", "fixed_interval"),
        interval_symbol=time_raw.get("interval_symbol", "T"),
        reference_interval_symbol=time_raw.get("reference_interval_symbol", "T_ref"),
        perturbation_symbol=time_raw.get("perturbation_symbol", "dT"),
        total_time_expr=time_raw.get("total_time", "N * T"),
        bounds=time_raw.get("bounds", []),
    )
    grid = GridDef(
        N=int(grid_raw["N"]),
        state_grid=grid_raw.get("state_grid", "node"),
        control_grid=grid_raw.get("control_grid", "node"),
        time=time_def,
    )

    # ── scale ──
    scales = _parse_scales(data.get("scale", {}))

    # ── model ──
    model = _parse_model(data["model"])

    # ── transcription ──
    transcription = _parse_transcription(data["transcription"])

    # ── codegen ──
    cg_raw = data.get("codegen", {})
    codegen = CodegenDef(
        pipeline=cg_raw.get("pipeline", ["original_yaml", "subproblem_yaml", "c_code"]),
        subproblem_output=cg_raw.get("subproblem_output", f"{meta.name}_subproblem.yaml"),
        c_output_dir=cg_raw.get("c_output_dir", f"generated/{meta.name}"),
        checks=cg_raw.get("checks", {}),
    )

    return OriginalProblemDef(
        meta=meta, grid=grid, scales=scales,
        model=model, transcription=transcription, codegen=codegen,
    )


def _parse_model(raw: dict) -> OrigModelDef:
    """Parse the model section (variables as {name: scale} maps)."""
    # ── Variables ──
    vars_raw = raw.get("variables", {})
    variables = OrigVariablesDef(
        states=dict(vars_raw.get("states", {})),
        controls=dict(vars_raw.get("controls", {})),
    )

    # ── Parameters (flat: name → scale) ──
    parameters: Dict[str, str] = {}
    params_raw = raw.get("parameters", {})
    if isinstance(params_raw, dict):
        parameters = {str(k): str(v) for k, v in params_raw.items()}
    elif isinstance(params_raw, list):
        for p in params_raw:
            if isinstance(p, dict) and "name" in p:
                parameters[p["name"]] = p.get("scale", p.get("dimension", "dimensionless"))

    # ── Expressions ──
    expressions = []
    for e_name, e_val in _iter_items(raw.get("expressions", {})):
        expr_str = e_val if isinstance(e_val, str) else e_val.get("expr", str(e_val))
        # Extract expression name, stripping optional (k) suffix
        match = re.match(r'^(\w+)', e_name)
        expr_name = match.group(1) if match else e_name
        expressions.append(OrigExpressionDef(name=expr_name, expr=str(expr_str)))

    # ── Dynamics ──
    dynamics = []
    for d_id, d_val in _iter_items(raw.get("dynamics", {})):
        dynamics.append(OrigDynamicsDef(
            dynamics_id=d_id,
            states=list(d_val.get("states", [])),
            controls=list(d_val.get("controls", [])),
            rhs=dict(d_val.get("rhs", {})),
        ))

    # ── Equalities ──
    equalities = []
    for eq_id, eq_val in _iter_items(raw.get("equalities", {})):
        at_raw = eq_val.get("at", 0)
        equalities.append(OrigEqualityDef(
            equality_id=eq_id,
            at=at_raw if isinstance(at_raw, str) else int(at_raw),
            equations=dict(eq_val.get("equations", {})),
        ))

    # ── Inequalities ──
    inequalities = []
    for ineq_id, ineq_val in _iter_items(raw.get("inequalities", {})):
        inequalities.append(OrigInequalityDef(
            inequality_id=ineq_id,
            grid=ineq_val.get("grid", "node"),
            expr=str(ineq_val.get("expr", "")),
            range=ineq_val.get("range", "all"),
        ))

    # ── Objective ──
    objective = []
    for obj_id, obj_val in _iter_items(raw.get("objective", {})):
        # Unified `expr` field; fallback to old `integrand` with a deprecation warning
        if "integrand" in obj_val and "expr" not in obj_val:
            import warnings
            warnings.warn(
                f"model.objective.{obj_id}: 'integrand' is DEPRECATED, use 'expr' instead.",
                FutureWarning,
            )
        expr_val = str(obj_val.get("expr", obj_val.get("integrand", "")))
        objective.append(OrigObjectiveDef(
            objective_id=obj_id,
            grid=obj_val.get("grid", "node"),
            range=obj_val.get("range", "all"),
            expr=expr_val,
            weight=str(obj_val.get("weight", "")),
            description=str(obj_val.get("description", "")),
        ))

    return OrigModelDef(
        variables=variables, parameters=parameters, expressions=expressions,
        dynamics=dynamics, equalities=equalities,
        inequalities=inequalities, objective=objective,
    )


def _parse_transcription(raw: dict) -> OrigTranscriptionDef:
    """Parse the transcription section (discretization scheme and operations)."""
    disc_mode = raw.get("discretization_mode", "perturbation")

    # ── Time effects (DEPRECATED; compiler auto-generates from grid.time) ──
    time_raw = raw.get("time")
    if time_raw and (time_raw.get("introduces_variables") or time_raw.get("constraints")):
        import warnings
        warnings.warn(
            "transcription.time section is DEPRECATED. "
            "Time variables are now auto-generated by the compiler from "
            "grid.time.interval_mode + discretization_mode.",
            FutureWarning,
        )

    # ── Operations ──
    operations = []
    for op_raw in raw.get("operations", []):
        effects = None
        eff_raw = op_raw.get("effects")
        if eff_raw:
            effects = _parse_operation_effects(eff_raw)

        # Parse approximation sub-block
        approx = None
        approx_raw = op_raw.get("approximation")
        if approx_raw:
            approx = ApproximationDecl(
                method=approx_raw.get("method", ""),
                about=approx_raw.get("about", ""),
                output_form=approx_raw.get("output_form", ""),
                quadrature=approx_raw.get("quadrature", ""),
                aggregation=approx_raw.get("aggregation", ""),
                time_weight_policy=approx_raw.get("time_weight_policy", ""),
            )

        source_raw = op_raw.get("source", "")
        sources_raw = op_raw.get("sources", [])
        if isinstance(sources_raw, str):
            sources_raw = [sources_raw]

        operations.append(NewOperationDecl(
            id=op_raw.get("id", ""),
            source=source_raw if isinstance(source_raw, str) else "",
            sources=sources_raw if isinstance(sources_raw, list) else [],
            operation=op_raw.get("operation", ""),
            export=op_raw.get("export", ""),
            approximation=approx,
            effects=effects,
            role_override=op_raw.get("role", ""),
        ))

    return OrigTranscriptionDef(
        discretization_mode=disc_mode,
        operations=operations,
    )


def _parse_scales(scale_raw: dict) -> ScaleDef:
    """
    Parse the scale section with base + derived format.

    YAML structure:
      scale:
        base:
          length:
            value: 10000.0
            unit: m
        derived:
          velocity: "length / time"
          acceleration: "velocity / time"

    Or legacy flat format (for backward compatibility):
      scale:
        length: 10000.0
        velocity: "length / time"
    """
    entries = []
    seen_names: set = set()

    def _add_entry(name: str, value, is_derived: bool):
        if name in seen_names:
            raise ValueError(f"Duplicate scale name '{name}' in scale section")
        seen_names.add(name)
        entries.append(ScaleEntry(name=name, value=value, is_derived=is_derived))

    # Check for new format with base/derived sections
    if "base" in scale_raw or "derived" in scale_raw:
        # New format
        base_raw = scale_raw.get("base", {})
        for dim_name, val in base_raw.items():
            if isinstance(val, dict):
                # {value: 10000.0, unit: m}
                value = float(val.get("value", val.get("val", 1.0)))
            else:
                value = float(val)
            _add_entry(dim_name, value, is_derived=False)

        derived_raw = scale_raw.get("derived", {})
        for dim_name, expr in derived_raw.items():
            if isinstance(expr, str):
                _add_entry(dim_name, expr.strip(), is_derived=True)
            else:
                raise ValueError(f"Derived scale '{dim_name}' must be a string expression")
    else:
        # Legacy flat format
        for dim_name, val in scale_raw.items():
            if isinstance(val, (int, float)):
                _add_entry(dim_name, float(val), is_derived=False)
            elif isinstance(val, str):
                val_stripped = val.strip()
                if _looks_like_expression(val_stripped):
                    _add_entry(dim_name, val_stripped, is_derived=True)
                else:
                    try:
                        _add_entry(dim_name, float(val_stripped), is_derived=False)
                    except ValueError:
                        _add_entry(dim_name, val_stripped, is_derived=True)
            elif isinstance(val, dict):
                # {value: ..., unit: ...}
                value = float(val.get("value", val.get("val", 1.0)))
                _add_entry(dim_name, value, is_derived=False)

    return ScaleDef(entries)


def _looks_like_expression(s: str) -> bool:
    """Check if a string looks like an expression (contains operators)."""
    operators = ('+', '-', '*', '/', '**', '^', '(')
    return any(op in s for op in operators)


def _parse_operation_effects(eff_raw: dict) -> OperationEffects:
    """Parse effects from a transcription operation."""
    introduces = []
    for iv in eff_raw.get("introduces_variables", []):
        introduces.append(IntroducedVarEffect(
            name=iv["name"], role=iv.get("role", ""),
            grid=iv.get("grid", "scalar"), scale=iv.get("scale", ""),
        ))

    replaces = []
    for rc in eff_raw.get("replaces_source_with_constraints", []):
        replaces.append(ReplacedConstraint(
            id=rc.get("id", ""), grid=rc.get("grid", "node"),
            range=rc.get("range", "all"), expr=rc.get("expr", ""),
            export=rc.get("export", "G_h"),
        ))

    adds_obj = []
    for ao in eff_raw.get("adds_objective_terms", []):
        role = ao.get("role", "")
        if not role:
            raise ValueError(
                f"adds_objective_terms entry '{ao.get('id', '?')}' is missing required 'role' field. "
                f"Must be one of: slack_penalty, trust_region_penalty, virtual_control_penalty"
            )
        ao_id = ao.get("id", "")
        if not ao_id:
            raise ValueError(
                f"adds_objective_terms entry is missing required 'id' field"
            )
        adds_obj.append(AddedObjectiveTerm(
            id=ao_id,
            expr=ao.get("expr", ""),
            role=role,
            expression_type=ao.get("expression_type", ""),
            approximation=ao.get("approximation", "exact"),
            output_form=ao.get("output_form", ""),
        ))

    return OperationEffects(
        introduces_variables=introduces,
        replaces_source_with_constraints=replaces,
        adds_objective_terms=adds_obj,
    )


def _iter_items(obj):
    """Iterate over a dict or list, yielding (key_or_index, value) pairs."""
    if isinstance(obj, dict):
        yield from obj.items()
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, dict) and "name" in item:
                yield item["name"], item
            else:
                yield i, item
