"""
YAML problem file parser.

Reads a two-layer YAML file (model + transcription), validates against
JSON Schemas, and constructs ModelDef + TranscriptionDef data structures.
"""

import yaml
import jsonschema
import re
from pathlib import Path
from typing import Dict, List, Tuple, Any

# ═══════════════════════════════════════════════════════════════════════════════
# New unified original-problem parser (meta + grid + scale + model +
# transcription + codegen) for Stage 1: Original YAML → SubProblem YAML
# ═══════════════════════════════════════════════════════════════════════════════

from .original_problem import (
    MetaDef, GridDef, TimeDef,
    OrigVariablesDef, OrigExpressionDef, OrigDynamicsDef,
    OrigEqualityDef, OrigInequalityDef, OrigObjectiveDef,
    OrigModelDef, OrigTranscriptionDef, OperationDecl as NewOperationDecl,
    OperationEffects, IntroducedVarEffect, ReplacedConstraint,
    AddedObjectiveTerm, TimeEffectsDef, CodegenDef, OriginalProblemDef,
)


def parse_original_problem(filepath: str) -> OriginalProblemDef:
    """
    Parse a unified original-problem YAML file.

    Reads meta, grid, scale, model, transcription, codegen sections
    and returns an OriginalProblemDef.
    """
    import yaml as _yaml
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Problem file not found: {filepath}")

    with open(path, "r", encoding="utf-8") as f:
        data = _yaml.safe_load(f)

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
    scales: Dict[str, float] = {}
    scale_raw = data.get("scale", {})
    for dim_name, val in scale_raw.items():
        scales[dim_name] = float(val)

    # ── model ──
    model = _parse_new_model(data["model"])

    # ── transcription ──
    transcription = _parse_new_transcription(data["transcription"])

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


def _parse_new_model(raw: dict) -> OrigModelDef:
    """Parse the model section (new flat format: variables as {name: scale} maps)."""
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
        objective.append(OrigObjectiveDef(
            objective_id=obj_id,
            grid=obj_val.get("grid", "node"),
            range=obj_val.get("range", "all"),
            integrand=str(obj_val.get("integrand", "")),
            weight=str(obj_val.get("weight", "")),
        ))

    return OrigModelDef(
        variables=variables, parameters=parameters, expressions=expressions,
        dynamics=dynamics, equalities=equalities,
        inequalities=inequalities, objective=objective,
    )


def _parse_new_transcription(raw: dict) -> OrigTranscriptionDef:
    """Parse the transcription section (new format with effects)."""
    disc_mode = raw.get("discretization_mode", "perturbation")

    # ── Time effects ──
    time_raw = raw.get("time", {})
    time_effects = _parse_time_effects(time_raw)

    # ── Operations ──
    operations = []
    for op_raw in raw.get("operations", []):
        effects = None
        eff_raw = op_raw.get("effects")
        if eff_raw:
            effects = _parse_operation_effects(eff_raw)

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
            effects=effects,
        ))

    return OrigTranscriptionDef(
        discretization_mode=disc_mode,
        time_effects=time_effects,
        operations=operations,
    )


def _parse_time_effects(time_raw: dict) -> TimeEffectsDef:
    """Parse time effects from transcription.time."""
    opt_effects = time_raw.get("optimizable_uniform_interval_effects", {})
    fx_effects = time_raw.get("fixed_interval_effects", {})

    if opt_effects:
        introduces = []
        for iv in opt_effects.get("introduces_variables", []):
            introduces.append(IntroducedVarEffect(
                name=iv["name"], role=iv.get("role", ""),
                grid=iv.get("grid", "scalar"), scale=iv.get("scale", ""),
            ))
        new_constraints = []
        for nc in opt_effects.get("new_constraints", []):
            new_constraints.append(ReplacedConstraint(
                id=nc.get("id", ""), grid=nc.get("grid", "scalar"),
                range=nc.get("range", "all"), expr=nc.get("expr", ""),
                export=nc.get("export", "G_h"),
            ))
        return TimeEffectsDef(
            source=time_raw.get("source", "grid.time"),
            introduces_variables=introduces,
            new_constraints=new_constraints,
            dynamics_uses_time_perturbation=opt_effects.get(
                "dynamics_uses_time_perturbation", False
            ),
        )

    # fixed_interval or default: no extra variables
    return TimeEffectsDef(
        source=time_raw.get("source", "grid.time"),
    )


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
        adds_obj.append(AddedObjectiveTerm(expr=ao.get("expr", "")))

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
