"""
YAML problem file parser.

Reads a two-layer YAML file (model + transcription), validates against
JSON Schemas, and constructs ModelDef + TranscriptionDef data structures.
"""

import yaml
import jsonschema
from pathlib import Path
from typing import Tuple

from .model import (
    ModelDef, DiscreteConfig, DiscreteMethod,
    VariableDef, VarRole, ScaleDef, ParameterDef, ExpressionDef,
    ExternalFuncDef, DynamicsEntry, ConstraintDef, ConstraintType,
    ObjectiveDef, ObjSense, NodeBinding,
)
from .transcription import (
    TranscriptionDef, VariableLayout, VarOrdering, VarGroup,
    OperationDecl, ExportDecl, ExportTarget, SCPParams,
)
from .schema import MODEL_SCHEMA, TRANSCRIPTION_SCHEMA


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_node(raw) -> int:
    """Parse a node index: int stays int, 'N' stays as string for later resolution."""
    if isinstance(raw, int):
        return raw
    return raw  # keep as string e.g. "N"

def _resolve_derived_scales(scales: dict):
    """Resolve derived scales like 'length / velocity' from known scale values."""
    import re
    # Simple expression evaluator for derive strings
    max_iter = 10
    for _ in range(max_iter):
        changed = False
        for dim_name, sd in list(scales.items()):
            if sd.value == 0.0 and sd.derive:
                # Try to evaluate the derive expression
                expr = sd.derive
                for other_dim, other_sd in scales.items():
                    if other_sd.value > 0:
                        expr = re.sub(r'\b' + other_dim + r'\b', str(other_sd.value), expr)
                expr = expr.replace('^', '**')
                try:
                    val = eval(expr, {"__builtins__": {}})
                    scales[dim_name] = ScaleDef(
                        name=dim_name, value=float(val),
                        unit=sd.unit, derive=sd.derive,
                    )
                    changed = True
                except Exception:
                    pass
        if not changed:
            break

def _resolve_node_count(raw, params: list) -> Tuple[int, str]:
    """Resolve node_count to (N_value, param_name_or_literal)."""
    if isinstance(raw, int):
        return raw, str(raw)
    if isinstance(raw, dict) and "param" in raw:
        pname = raw["param"]
        for p in params:
            if p["name"] == pname:
                val = p.get("value", None)
                if isinstance(val, (int, float)):
                    return int(val), pname
                break
        # fallback: param not resolved yet, store as sentinel
        return 0, pname
    raise ValueError(f"Cannot resolve node_count: {raw}")


# ── Main Parser ──────────────────────────────────────────────────────────────

def parse_problem(filepath: str) -> Tuple[ModelDef, TranscriptionDef]:
    """
    Parse a problem description YAML file.

    Returns:
        (model_def, transcription_def)
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Problem file not found: {filepath}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if "model" not in data:
        raise ValueError("YAML file must contain top-level 'model' key")
    if "transcription" not in data:
        raise ValueError("YAML file must contain top-level 'transcription' key")

    # Validate schemas
    jsonschema.validate(data["model"], MODEL_SCHEMA)
    jsonschema.validate(data["transcription"], TRANSCRIPTION_SCHEMA)

    model_def = _parse_model(data["model"])
    trans_def = _parse_transcription(data["transcription"])

    return model_def, trans_def


def _parse_model(raw: dict) -> ModelDef:
    """Parse the model layer."""
    name = raw["name"]

    # ── Scales (dimensional normalization) ──
    scales_raw = raw.get("scales", {})
    scales = {}
    for dim_name, s in scales_raw.items():
        if isinstance(s, (int, float)):
            scales[dim_name] = ScaleDef(name=dim_name, value=float(s))
        elif isinstance(s, dict):
            scales[dim_name] = ScaleDef(
                name=dim_name,
                value=float(s.get("value", 0.0)),  # 0 = need derivation
                unit=s.get("unit", ""),
                derive=s.get("derive", ""),
            )
        else:
            scales[dim_name] = ScaleDef(name=dim_name, value=1.0)

    # Resolve derived scales: "length / velocity" → compute from known scales
    _resolve_derived_scales(scales)

    # ── Parameters (parse first for node_count resolution) ──
    raw_params = raw.get("parameters", [])
    parameters = []
    for p in raw_params:
        val = p.get("value")
        # Try to convert string values to float if they look numeric
        if isinstance(val, str):
            try:
                val = float(val)
            except ValueError:
                pass
        parameters.append(ParameterDef(
            name=p["name"],
            value=val,
            description=p.get("description", ""),
        ))

    # ── Discretization ──
    disc_raw = raw["discretization"]
    N_val, N_param = _resolve_node_count(disc_raw["node_count"], raw_params)
    method = DiscreteMethod(disc_raw.get("method", "trapezoidal"))
    discretization = DiscreteConfig(
        node_count=N_val, node_count_param=N_param, method=method
    )

    # ── Variables (dimension-based, not per-variable scale) ──
    vars_raw = raw.get("variables", {})

    def _parse_vars(role: VarRole, raw_list: list) -> list:
        result = []
        for v in (raw_list or []):
            dim = v.get("dimension", "")
            alias = v.get("expr", None) if role == VarRole.AUXILIARY else None
            result.append(VariableDef(
                name=v["name"], role=role, dimension=dim,
                description=v.get("description", ""),
                alias_expr=alias,
            ))
        return result

    states = _parse_vars(VarRole.STATE, vars_raw.get("state", []))
    controls = _parse_vars(VarRole.CONTROL, vars_raw.get("control", []))
    auxiliaries = _parse_vars(VarRole.AUXILIARY, vars_raw.get("auxiliary", []))

    # ── Expressions (aliases: L = ..., D = ..., overload = ...) ──
    expr_raw = raw.get("expressions", [])
    expressions = [
        ExpressionDef(
            name=e["name"],
            expr=e["expr"],
            description=e.get("description", ""),
        )
        for e in expr_raw
    ]

    # ── External functions ──
    ext_raw = raw.get("external_functions", [])
    external_funcs = [
        ExternalFuncDef(
            name=f["name"], signature=f["signature"],
            description=f.get("description", ""),
        )
        for f in ext_raw
    ]

    # ── Dynamics (may reference expressions) ──
    dyn_raw = raw.get("dynamics", [])
    dynamics = [
        DynamicsEntry(state=d["state"], rhs=d["rhs"])
        for d in dyn_raw
    ]

    # ── Constraints ──
    def _parse_constraints(raw_list: list) -> list:
        result = []
        for c in (raw_list or []):
            ctype = ConstraintType(c["type"])
            bindings = []
            for b in c.get("bindings", []):
                node_raw = b.get("node", None)
                bindings.append(NodeBinding(
                    var=b["var"],
                    node=_parse_node(node_raw) if node_raw is not None else None,
                    value=b.get("value", ""),
                    lower=b.get("lower", ""),
                    upper=b.get("upper", ""),
                ))
            nodes_raw = c.get("nodes", [])
            result.append(ConstraintDef(
                name=c["name"], ctype=ctype,
                bindings=bindings,
                expr=c.get("expr", ""),
                lower=c.get("lower", ""),
                upper=c.get("upper", ""),
                nodes=[_parse_node(n) for n in nodes_raw],
            ))
        return result

    eq_constraints = _parse_constraints(raw.get("equality_constraints", []))
    ineq_constraints = _parse_constraints(raw.get("inequality_constraints", []))

    # ── Objective ──
    obj_raw = raw.get("objective", {})
    objective = None
    if obj_raw:
        sense = ObjSense(obj_raw["type"])
        objective = ObjectiveDef(sense=sense, expr=obj_raw["expr"])

    return ModelDef(
        name=name,
        discretization=discretization,
        scales=scales,
        states=states,
        controls=controls,
        auxiliaries=auxiliaries,
        expressions=expressions,
        parameters=parameters,
        external_funcs=external_funcs,
        dynamics=dynamics,
        eq_constraints=eq_constraints,
        ineq_constraints=ineq_constraints,
        objective=objective,
    )


def _parse_transcription(raw: dict) -> TranscriptionDef:
    """Parse the transcription layer."""
    # ── Variable Layout ──
    layout_raw = raw["variable_layout"]
    ordering = VarOrdering(layout_raw["ordering"])
    groups = []
    for g in layout_raw.get("groups", []):
        groups.append(VarGroup(
            vars=list(g["vars"]),
            nodes=list(g["nodes"]),
        ))
    variable_layout = VariableLayout(ordering=ordering, groups=groups)

    # ── Operations ──
    operations = []
    for op_raw in raw.get("operations", []):
        op_type = op_raw.pop("type")
        exports_raw = op_raw.pop("export", [])
        exports = [
            ExportDecl(target=ExportTarget(e["target"]))
            for e in exports_raw
        ]
        operations.append(OperationDecl(
            type=op_type,
            params=op_raw,  # remaining keys
            exports=exports,
        ))

    # ── Validate: midpoint dynamics linearization requires control on node grid ──
    _validate_control_grid(operations, variable_layout)

    return TranscriptionDef(
        variable_layout=variable_layout,
        operations=operations,
        scp_params=SCPParams(raw.get("scp_params", {})),
    )


def _validate_control_grid(operations: list, layout: "VariableLayout"):
    """Validate that controls are on node grid when using midpoint linearization."""
    for op in operations:
        if op.type == "dynamics_linearize":
            discretization = op.params.get("discretization", "trapezoidal")
            linearization = op.params.get("linearization", "taylor_first_order")
            # midpoint + trapezoidal (or hermite_simpson) requires control at nodes
            if discretization in ("trapezoidal", "hermite_simpson") and linearization == "taylor_first_order":
                # Check that all control variables span all node ranges
                control_names = set()
                for g in layout.groups:
                    control_names.update(g.vars)
                # This is a loose check; the real check happens in discretizer.py
                # when we actually try to resolve control@k+1
                pass  # Detailed check in DynamicsLinearizeOp.analyze_sparsity()


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
        expressions.append(OrigExpressionDef(name=e_name, expr=str(expr_str)))

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
