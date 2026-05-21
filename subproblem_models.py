"""
Data structures for the intermediate subproblem YAML.

This is the output of Stage 1 compilation — a fully-expanded,
row-allocated description of the convex subproblem that is
solver-agnostic (no ECOS-specific cone layout, no SOC epigraph).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# Meta
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SubMetaDef:
    name: str
    version: str = "scp_subproblem_v0.1"
    generated_from: str = ""
    discretization_mode: str = "perturbation"


# ═══════════════════════════════════════════════════════════════════════════════
# Dimensions
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SubDimensions:
    N: int = 0
    n_nodes: int = 0
    final_node: int = 0
    n_states: int = 0
    n_controls: int = 0
    vars_per_node: int = 0
    n_node_variables: int = 0
    n_extra_variables: int = 0
    nvar: int = 0
    neq: int = 0
    nineq: int = 0
    objective_terms: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Variables
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class NodeVarEntry:
    """A node-distributed variable with its per-node column expression."""
    name: str
    kind: str                          # "state" | "control"
    grid: str = "node"
    scale: str = ""
    node_offset: int = 0               # offset within one node's variable block
    col: str = ""                      # column expression, e.g. "k * VARS_PER_NODE + 0"


@dataclass
class ExtraVarEntry:
    """An extra variable (slack, virtual control, time perturbation, etc.)."""
    name: str
    role: str                          # "time_perturbation" | "scalar_nonnegative_slack" | ...
    grid: str                          # "scalar" | "node" | "interval"
    scale: str = ""
    col: int = -1                      # concrete column index
    source: str = ""                   # which operation or time effect introduced it


@dataclass
class SubVariables:
    node_order: Dict[str, List[str]] = field(default_factory=dict)  # states: [...], controls: [...]
    node_variables: List[NodeVarEntry] = field(default_factory=list)
    extra_variables: List[ExtraVarEntry] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Time
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SubTime:
    interval_mode: str = "fixed_interval"
    interval_symbol: str = "T"
    reference_interval_symbol: str = "T_ref"

    # ── Unified time variable (canonical indicator; replaces perturbation_variable) ──
    time_variable: Optional[str] = None          # "dT" | "T" | None
    time_variable_role: Optional[str] = None     # "time_perturbation" | "time_interval" | None

    # ── DEPRECATED: retained for backward compatibility ──
    perturbation_variable: Optional[str] = None  # "dT" or None (use time_variable)

    perturbed_interval_expr: Optional[str] = None   # "T_ref + dT" or None
    total_time_expr: str = ""

    # ── Time bounds: parameter names vs auto-generated constraint IDs ──
    bound_parameters: List[str] = field(default_factory=list)      # ["tf_min", "tf_max"]
    bound_constraint_ids: List[str] = field(default_factory=list)  # ["total_time_lower", "total_time_upper"]

    # ── DEPRECATED: old combined field ──
    bounds: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Equality / Inequality Blocks
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EqualityBlock:
    """One contiguous block of equality constraint rows in A."""
    id: str
    source_models: List[str] = field(default_factory=list)  # e.g. ["model.dynamics.reentry"] or multiple sources
    source_operation: str = ""         # e.g. "dynamics_defect"
    export: str = "A_b"
    row_start: int = 0
    row_count: int = 0
    row_end: int = 0
    grid: str = ""                     # "node" | "interval" | "scalar"
    range: Any = None                  # concrete [start, end] list, never "all"
    processor: str = ""                # "dynamics_defect" | "boundary_equalities"
    A_rows: List[int] = field(default_factory=list)  # [row_start, row_end]
    boundary_rows: Optional[List[dict]] = None  # per-row detail for boundary blocks: [{variable, node, rhs_param}]

    @property
    def source_model(self) -> str:
        """Backward-compatible: return first source or empty string."""
        return self.source_models[0] if self.source_models else ""


@dataclass
class InequalityBlock:
    """One contiguous block of inequality constraint rows in G."""
    id: str
    source_models: List[str] = field(default_factory=list)  # e.g. ["model.inequalities.alpha_bounds"]
    source_operation: str = ""         # e.g. "affine_bounds"
    export: str = "G_h"
    row_start: int = 0
    row_count: int = 0
    row_end: int = 0
    grid: str = ""
    range: Any = None                  # concrete [start, end] list, never "all"
    processor: str = ""
    bound_type: Optional[str] = None   # "lower" | "upper" | None (for split box constraints)
    expr: str = ""                     # constraint expression after transcription
    G_rows: List[int] = field(default_factory=list)

    @property
    def source_model(self) -> str:
        """Backward-compatible: return first source or empty string."""
        return self.source_models[0] if self.source_models else ""


@dataclass
class SubEqualities:
    total_rows: int = 0
    blocks: List[EqualityBlock] = field(default_factory=list)


@dataclass
class SubInequalities:
    total_rows: int = 0
    blocks: List[InequalityBlock] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Objective
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ObjectiveTerm:
    """One objective term in mathematical form (no SOC epigraph rewriting).

    Stage 1 does NOT generate linearization coefficients or SOC cones —
    it only annotates the strategy.  Stage 2 uses these annotations to
    produce discretized (linearized) problem data.
    """
    id: str
    source_model: str = ""             # e.g. "model.objective.smooth_theta"
    source_operation: str = ""         # e.g. "objective_smooth_theta"
    source_effect: str = ""            # e.g. "path_constraint_dynamic_pressure.effects.adds_objective_terms.dynamic_pressure_slack_penalty"

    # ── Semantic fields (Stage1 objective refactoring) ──
    role: str = ""                     # "original_cost" | "trust_region_penalty" | "slack_penalty"
                                        # | "virtual_control_penalty" | "smoothing_penalty"
    expression_type: str = ""          # "nonlinear" | "affine" | "quadratic" | "l1" | "norm"
    approximation: str = ""            # "first_order" | "exact_affine" | "exact_quadratic" | "none"
    reference_dependent: bool = False
    output_form: str = ""              # "linear_cost" | "quadratic_penalty" | "l1_penalty" | "norm_penalty"

    # ── Stage pipeline actions (replaces combined next_stage_action) ──
    stage2_action: str = ""            # "discretize_objective" | "linearize_objective" | "keep_as_is"
    stage3_action: str = ""            # "keep_linear_cost" | "convert_quadratic_to_socp" | "none"

    # ── Discretization metadata (for grid=node/interval terms) ──
    quadrature: str = ""               # "none" | "trapezoidal" | "simpson"
    aggregation: str = ""              # "sum" | "mean" | "integral" | "none"
    time_weight_policy: str = ""       # "none" | "T_ref" | "T_ref_plus_dT" | "dT"

    # ── DEPRECATED: retained for backward compatibility ──
    next_stage_action: str = ""        # old combined form, replaced by stage2_action + stage3_action
    type: str = ""                     # old style: "integral_quadratic" | "linear" | "scalar_quadratic"

    grid: str = ""
    range: Any = None                  # concrete [start, end] list, never "all"
    expr: str = ""


@dataclass
class SubObjective:
    terms: List[ObjectiveTerm] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationRule:
    """A single validation convention."""
    A_rows: str = "0 ... neq-1"
    G_rows: str = "0 ... nineq-1"
    row_end_rule: str = "row_end = row_start + row_count - 1"


@dataclass
class VirtualControlInfo:
    """Virtual control configuration for Stage2 dynamics discretization."""
    enabled: bool = False
    name: str = "v"
    dimension: int = 0
    penalty_weight: float = 0.0
    penalty_type: str = "quadratic"
    location: str = "interval"  # "interval" | "node"


@dataclass
class DynamicsInfo:
    """Dynamics configuration for Stage2 discretization.

    This struct provides Stage2 with the information needed to:
    - Select discretization method (trapezoidal)
    - Handle virtual control variables if enabled
    """
    discretization: str = "trapezoidal"  # currently only trapezoidal is supported
    virtual_control: VirtualControlInfo = field(default_factory=VirtualControlInfo)


@dataclass
class SubValidation:
    row_convention: ValidationRule = field(default_factory=ValidationRule)
    required_checks: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Top-level SubProblem
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SubProblemDef:
    """Complete intermediate subproblem description."""
    meta: SubMetaDef = field(default_factory=SubMetaDef)
    dimensions: SubDimensions = field(default_factory=SubDimensions)
    scale_table: Dict[str, float] = field(default_factory=dict)  # dimension → numeric value
    variables: SubVariables = field(default_factory=SubVariables)
    parameters: Dict[str, str] = field(default_factory=dict)   # name → scale
    expressions: List[dict] = field(default_factory=list)       # [{name, expr}]
    dynamics: List[dict] = field(default_factory=list)          # [{dynamics_id, states, controls, rhs}]
    dynamics_config: DynamicsInfo = field(default_factory=DynamicsInfo)  # Stage2 config
    time: SubTime = field(default_factory=SubTime)
    equalities: SubEqualities = field(default_factory=SubEqualities)
    inequalities: SubInequalities = field(default_factory=SubInequalities)
    objective: SubObjective = field(default_factory=SubObjective)
    validation: SubValidation = field(default_factory=SubValidation)


# ═══════════════════════════════════════════════════════════════════════════════
# Serialization helpers
# ═══════════════════════════════════════════════════════════════════════════════

def subproblem_to_dict(sp: SubProblemDef) -> dict:
    """Convert SubProblemDef to a plain dict suitable for YAML serialization."""

    def _format_range(rng):
        """Always output range as concrete [start, end] list, never 'all'."""
        if rng is None or rng == "all" or rng == "":
            return None  # caller decides whether to omit
        if isinstance(rng, list) and len(rng) == 2:
            return [int(rng[0]), int(rng[1])]
        return rng

    def _eq_block_to_dict(blk):
        d = {
            "id": blk.id,
            "source_models": list(blk.source_models),  # always output as list
            "source_operation": blk.source_operation,
            "export": blk.export,
            "row_start": blk.row_start,
            "row_count": blk.row_count,
            "row_end": blk.row_end,
            "grid": blk.grid,
            "processor": blk.processor,
            "A_rows": [blk.row_start, blk.row_end],
        }
        rng = _format_range(blk.range)
        if rng is not None:
            d["range"] = rng
        if blk.boundary_rows:
            d["boundary_rows"] = blk.boundary_rows
        return d

    def _ineq_block_to_dict(blk):
        d = {
            "id": blk.id,
            "source_models": list(blk.source_models),  # always output as list
            "source_operation": blk.source_operation,
            "export": blk.export,
            "row_start": blk.row_start,
            "row_count": blk.row_count,
            "row_end": blk.row_end,
            "grid": blk.grid,
            "processor": blk.processor,
            "expr": blk.expr,
            "G_rows": [blk.row_start, blk.row_end],
        }
        rng = _format_range(blk.range)
        if rng is not None:
            d["range"] = rng
        if blk.bound_type:
            d["bound_type"] = blk.bound_type
        return d

    result = {
        "meta": {
            "name": sp.meta.name,
            "version": sp.meta.version,
            "generated_from": sp.meta.generated_from,
            "discretization_mode": sp.meta.discretization_mode,
        },
        "dimensions": {
            "N": sp.dimensions.N,
            "n_nodes": sp.dimensions.n_nodes,
            "final_node": sp.dimensions.final_node,
            "n_states": sp.dimensions.n_states,
            "n_controls": sp.dimensions.n_controls,
            "vars_per_node": sp.dimensions.vars_per_node,
            "n_node_variables": sp.dimensions.n_node_variables,
            "n_extra_variables": sp.dimensions.n_extra_variables,
            "nvar": sp.dimensions.nvar,
            "neq": sp.dimensions.neq,
            "nineq": sp.dimensions.nineq,
            "objective_terms": sp.dimensions.objective_terms,
        },
        "scale_table": dict(sp.scale_table),
        "variables": {
            "node_order": sp.variables.node_order,
            "node_variables": [
                {
                    "name": v.name,
                    "kind": v.kind,
                    "grid": v.grid,
                    "scale": v.scale,
                    "node_offset": v.node_offset,
                    "col": v.col,
                }
                for v in sp.variables.node_variables
            ],
            "extra_variables": [
                {
                    "name": v.name,
                    "role": v.role,
                    "grid": v.grid,
                    "scale": v.scale,
                    "col": v.col,
                    "source": v.source,
                }
                for v in sp.variables.extra_variables
            ],
        },
        "parameters": sp.parameters,
        "expressions": [
            {"name": e["name"], "expr": e["expr"]}
            for e in sp.expressions
        ],
        "dynamics": [
            {
                "dynamics_id": d["dynamics_id"],
                "states": d["states"],
                "controls": d["controls"],
                "rhs": d["rhs"],
            }
            for d in sp.dynamics
        ],
        # Stage2 dynamics configuration
        "dynamics_config": {
            "discretization": sp.dynamics_config.discretization,
            "virtual_control": {
                "enabled": sp.dynamics_config.virtual_control.enabled,
                "name": sp.dynamics_config.virtual_control.name,
                "dimension": sp.dynamics_config.virtual_control.dimension,
                "penalty_weight": sp.dynamics_config.virtual_control.penalty_weight,
                "penalty_type": sp.dynamics_config.virtual_control.penalty_type,
                "location": sp.dynamics_config.virtual_control.location,
            },
        },
        "time": {
            "interval_mode": sp.time.interval_mode,
            "interval_symbol": sp.time.interval_symbol,
            "reference_interval_symbol": sp.time.reference_interval_symbol,
            "time_variable": sp.time.time_variable,
            "time_variable_role": sp.time.time_variable_role,
            "perturbation_variable": sp.time.perturbation_variable,
            "perturbed_interval_expr": sp.time.perturbed_interval_expr,
            "total_time_expr": sp.time.total_time_expr,
            "bound_parameters": sp.time.bound_parameters,
            "bound_constraint_ids": sp.time.bound_constraint_ids,
        },
        "equalities": {
            "total_rows": sp.equalities.total_rows,
            "blocks": [_eq_block_to_dict(b) for b in sp.equalities.blocks],
        },
        "inequalities": {
            "total_rows": sp.inequalities.total_rows,
            "blocks": [_ineq_block_to_dict(b) for b in sp.inequalities.blocks],
        },
        "objective": {
            "terms": [
                {
                    "id": t.id,
                    "source_model": t.source_model,
                    "source_operation": t.source_operation,
                    "source_effect": t.source_effect,
                    "role": t.role,
                    "expression_type": t.expression_type,
                    "approximation": t.approximation,
                    "reference_dependent": t.reference_dependent,
                    "output_form": t.output_form,
                    "stage2_action": t.stage2_action,
                    "stage3_action": t.stage3_action,
                    "next_stage_action": t.next_stage_action,
                    "quadrature": t.quadrature,
                    "aggregation": t.aggregation,
                    "time_weight_policy": t.time_weight_policy,
                    "grid": t.grid,
                    "range": _format_range(t.range),
                    "expr": t.expr,
                }
                for t in sp.objective.terms
            ],
        },
        "validation": {
            "row_convention": {
                "A_rows": sp.validation.row_convention.A_rows,
                "G_rows": sp.validation.row_convention.G_rows,
                "row_end_rule": sp.validation.row_convention.row_end_rule,
            },
            "required_checks": sp.validation.required_checks,
        },
    }
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Deserialization helpers
# ═══════════════════════════════════════════════════════════════════════════════

def subproblem_from_dict(d: dict) -> SubProblemDef:
    """Reconstruct a SubProblemDef from a plain dict (reverse of subproblem_to_dict).

    This is the canonical deserializer used by validate-subproblem and
    by Stage 2 to read the intermediate subproblem YAML.
    """

    # ── Meta ──
    meta_d = d.get("meta", {})
    meta = SubMetaDef(
        name=meta_d.get("name", ""),
        version=meta_d.get("version", "scp_subproblem_v0.1"),
        generated_from=meta_d.get("generated_from", ""),
        discretization_mode=meta_d.get("discretization_mode", "perturbation"),
    )

    # ── Dimensions ──
    dims_d = d.get("dimensions", {})
    dims = SubDimensions(
        N=dims_d.get("N", 0),
        n_nodes=dims_d.get("n_nodes", 0),
        final_node=dims_d.get("final_node", 0),
        n_states=dims_d.get("n_states", 0),
        n_controls=dims_d.get("n_controls", 0),
        vars_per_node=dims_d.get("vars_per_node", 0),
        n_node_variables=dims_d.get("n_node_variables", 0),
        n_extra_variables=dims_d.get("n_extra_variables", 0),
        nvar=dims_d.get("nvar", 0),
        neq=dims_d.get("neq", 0),
        nineq=dims_d.get("nineq", 0),
        objective_terms=dims_d.get("objective_terms", 0),
    )

    # ── Scale table ──
    scale_table = {str(k): float(v) for k, v in d.get("scale_table", {}).items()}

    # ── Variables ──
    vars_d = d.get("variables", {})
    node_order = vars_d.get("node_order", {})
    node_variables = [
        NodeVarEntry(
            name=v.get("name", ""),
            kind=v.get("kind", ""),
            grid=v.get("grid", "node"),
            scale=v.get("scale", ""),
            node_offset=v.get("node_offset", 0),
            col=v.get("col", ""),
        )
        for v in vars_d.get("node_variables", [])
    ]
    extra_variables = [
        ExtraVarEntry(
            name=v.get("name", ""),
            role=v.get("role", ""),
            grid=v.get("grid", "scalar"),
            scale=v.get("scale", ""),
            col=v.get("col", -1),
            source=v.get("source", ""),
        )
        for v in vars_d.get("extra_variables", [])
    ]
    variables = SubVariables(
        node_order=node_order,
        node_variables=node_variables,
        extra_variables=extra_variables,
    )

    # ── Parameters ──
    parameters = {str(k): str(v) for k, v in d.get("parameters", {}).items()}

    # ── Expressions ──
    expressions = [
        {"name": str(e["name"]), "expr": str(e["expr"])}
        for e in d.get("expressions", [])
    ]

    # ── Dynamics ──
    dynamics = [
        {
            "dynamics_id": str(dyn.get("dynamics_id", "")),
            "states": list(dyn.get("states", [])),
            "controls": list(dyn.get("controls", [])),
            "rhs": {str(k): str(v) for k, v in dyn.get("rhs", {}).items()},
        }
        for dyn in d.get("dynamics", [])
    ]

    # ── Dynamics Config (for Stage2) ──
    dyn_cfg_d = d.get("dynamics_config", {})
    vc_d = dyn_cfg_d.get("virtual_control", {})
    virtual_control = VirtualControlInfo(
        enabled=vc_d.get("enabled", False),
        name=vc_d.get("name", "v"),
        dimension=vc_d.get("dimension", 0),
        penalty_weight=float(vc_d.get("penalty_weight", 0.0)),
        penalty_type=vc_d.get("penalty_type", "quadratic"),
        location=vc_d.get("location", "interval"),
    )
    dynamics_config = DynamicsInfo(
        discretization=dyn_cfg_d.get("discretization", "trapezoidal"),
        virtual_control=virtual_control,
    )

    # ── Time ──
    time_d = d.get("time", {})
    time = SubTime(
        interval_mode=time_d.get("interval_mode", "fixed_interval"),
        interval_symbol=time_d.get("interval_symbol", "T"),
        reference_interval_symbol=time_d.get("reference_interval_symbol", "T_ref"),
        time_variable=time_d.get("time_variable"),
        time_variable_role=time_d.get("time_variable_role"),
        perturbation_variable=time_d.get("perturbation_variable"),
        perturbed_interval_expr=time_d.get("perturbed_interval_expr"),
        total_time_expr=time_d.get("total_time_expr", ""),
        bound_parameters=time_d.get("bound_parameters", []),
        bound_constraint_ids=time_d.get("bound_constraint_ids", time_d.get("bounds", [])),
    )

    # ── Equalities ──
    eq_d = d.get("equalities", {})
    eq_blocks = []
    for blk in eq_d.get("blocks", []):
        eq_blocks.append(EqualityBlock(
            id=blk.get("id", ""),
            source_models=list(blk.get("source_models", [])),
            source_operation=blk.get("source_operation", ""),
            export=blk.get("export", "A_b"),
            row_start=blk.get("row_start", 0),
            row_count=blk.get("row_count", 0),
            row_end=blk.get("row_end", 0),
            grid=blk.get("grid", ""),
            range=blk.get("range"),
            processor=blk.get("processor", ""),
            A_rows=list(blk.get("A_rows", [])),
            boundary_rows=blk.get("boundary_rows"),
        ))
    equalities = SubEqualities(
        total_rows=eq_d.get("total_rows", 0),
        blocks=eq_blocks,
    )

    # ── Inequalities ──
    ineq_d = d.get("inequalities", {})
    ineq_blocks = []
    for blk in ineq_d.get("blocks", []):
        ineq_blocks.append(InequalityBlock(
            id=blk.get("id", ""),
            source_models=list(blk.get("source_models", [])),
            source_operation=blk.get("source_operation", ""),
            export=blk.get("export", "G_h"),
            row_start=blk.get("row_start", 0),
            row_count=blk.get("row_count", 0),
            row_end=blk.get("row_end", 0),
            grid=blk.get("grid", ""),
            range=blk.get("range"),
            processor=blk.get("processor", ""),
            bound_type=blk.get("bound_type"),
            expr=blk.get("expr", ""),
            G_rows=list(blk.get("G_rows", [])),
        ))
    inequalities = SubInequalities(
        total_rows=ineq_d.get("total_rows", 0),
        blocks=ineq_blocks,
    )

    # ── Objective ──
    obj_d = d.get("objective", {})
    obj_terms = [
        ObjectiveTerm(
            id=t.get("id", ""),
            source_model=t.get("source_model", ""),
            source_operation=t.get("source_operation", ""),
            source_effect=t.get("source_effect", ""),
            role=t.get("role", ""),
            expression_type=t.get("expression_type", ""),
            approximation=t.get("approximation", ""),
            reference_dependent=t.get("reference_dependent", False),
            output_form=t.get("output_form", ""),
            stage2_action=t.get("stage2_action", ""),
            stage3_action=t.get("stage3_action", ""),
            next_stage_action=t.get("next_stage_action", ""),
            quadrature=t.get("quadrature", ""),
            aggregation=t.get("aggregation", ""),
            time_weight_policy=t.get("time_weight_policy", ""),
            type=t.get("type", ""),
            grid=t.get("grid", ""),
            range=t.get("range"),
            expr=t.get("expr", ""),
        )
        for t in obj_d.get("terms", [])
    ]
    objective = SubObjective(terms=obj_terms)

    # ── Validation ──
    val_d = d.get("validation", {})
    rc_d = val_d.get("row_convention", {})
    validation = SubValidation(
        row_convention=ValidationRule(
            A_rows=rc_d.get("A_rows", "0 ... neq-1"),
            G_rows=rc_d.get("G_rows", "0 ... nineq-1"),
            row_end_rule=rc_d.get("row_end_rule", "row_end = row_start + row_count - 1"),
        ),
        required_checks=list(val_d.get("required_checks", [])),
    )

    return SubProblemDef(
        meta=meta,
        dimensions=dims,
        scale_table=scale_table,
        variables=variables,
        parameters=parameters,
        expressions=expressions,
        dynamics=dynamics,
        dynamics_config=dynamics_config,
        time=time,
        equalities=equalities,
        inequalities=inequalities,
        objective=objective,
        validation=validation,
    )
