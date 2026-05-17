"""
Unified original problem dataclasses for the new YAML format.

Top-level sections: meta, grid, scale, model, transcription, codegen.

This module defines the immutable data structures parsed from the
original problem YAML.  These are consumed by SubproblemCompiler
(Stage 1) and later by the C code generator (Stage 2).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


# ═══════════════════════════════════════════════════════════════════════════════
# Meta
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class MetaDef:
    """Top-level metadata."""
    name: str
    version: str = "scp_original_problem_v0.1"
    macro_prefix: str = ""
    function_prefix: str = ""
    scalar_type: str = "double"
    index_type: str = "idxint"


# ═══════════════════════════════════════════════════════════════════════════════
# Grid / Time
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TimeDef:
    """Time discretization policy."""
    interval_mode: str          # "fixed_interval" | "optimizable_uniform_interval"
    interval_symbol: str = "T"
    perturbation_symbol: str = "dT"
    total_time_expr: str = "N * T"
    bounds: List[str] = field(default_factory=list)  # e.g. ["tf_min", "tf_max"]


@dataclass(frozen=True)
class GridDef:
    """Discrete mesh definition."""
    N: int                      # number of intervals
    state_grid: str = "node"    # "node" | "interval"
    control_grid: str = "node"
    time: TimeDef = field(default_factory=TimeDef)

    @property
    def n_nodes(self) -> int:
        return self.N + 1

    @property
    def final_node(self) -> int:
        return self.N


# ═══════════════════════════════════════════════════════════════════════════════
# Scale
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FlatScaleDef:
    """A single dimensional scale: name → numeric value."""
    name: str
    value: float


# ═══════════════════════════════════════════════════════════════════════════════
# Model
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class OrigVarDecl:
    """Declaration of a variable with its scale reference."""
    name: str
    scale: str                 # references a scale dimension name


@dataclass(frozen=True)
class OrigVariablesDef:
    """Variable declarations in the model layer."""
    states: Dict[str, str] = field(default_factory=dict)   # name → scale
    controls: Dict[str, str] = field(default_factory=dict)

    @property
    def state_names(self) -> List[str]:
        return list(self.states.keys())

    @property
    def control_names(self) -> List[str]:
        return list(self.controls.keys())

    @property
    def n_states(self) -> int:
        return len(self.states)

    @property
    def n_controls(self) -> int:
        return len(self.controls)

    @property
    def vars_per_node(self) -> int:
        return self.n_states + self.n_controls


@dataclass(frozen=True)
class OrigExpressionDef:
    """Named expression alias, e.g. L(k) = q_dyn(k) * S * CL(k)."""
    name: str
    expr: str
    description: str = ""


@dataclass(frozen=True)
class OrigDynamicsDef:
    """One dynamics system: states, controls, and RHS expressions."""
    dynamics_id: str
    states: List[str]
    controls: List[str]
    rhs: Dict[str, str]         # state_name → expression string


@dataclass(frozen=True)
class OrigEqualityDef:
    """Endpoint equality constraint: var@at = value."""
    equality_id: str
    at: Union[int, str]         # 0, N, or integer
    equations: Dict[str, str]   # var_or_expr → value_expression


@dataclass(frozen=True)
class OrigInequalityDef:
    """Inequality constraint (box, path, or scalar)."""
    inequality_id: str
    grid: str                   # "node" | "interval" | "scalar"
    expr: str
    # 'range' is optional; "all" means [0, N], otherwise [start, end] or [N, N]
    range: Any = "all"


@dataclass(frozen=True)
class OrigObjectiveDef:
    """Objective term in the model layer."""
    objective_id: str
    grid: str                   # "node" | "interval" | "scalar"
    range: Any = "all"
    integrand: str = ""
    weight: str = ""


@dataclass(frozen=True)
class OrigModelDef:
    """The model layer of the original problem."""
    variables: OrigVariablesDef = field(default_factory=OrigVariablesDef)
    parameters: Dict[str, str] = field(default_factory=dict)    # name → scale
    expressions: List[OrigExpressionDef] = field(default_factory=list)
    dynamics: List[OrigDynamicsDef] = field(default_factory=list)
    equalities: List[OrigEqualityDef] = field(default_factory=list)
    inequalities: List[OrigInequalityDef] = field(default_factory=list)
    objective: List[OrigObjectiveDef] = field(default_factory=list)

    def get_expression(self, name: str) -> Optional[OrigExpressionDef]:
        for e in self.expressions:
            if e.name == name:
                return e
        return None

    def get_parameter_scale(self, name: str) -> Optional[str]:
        return self.parameters.get(name)

    def get_variable_scale(self, name: str) -> Optional[str]:
        if name in self.variables.states:
            return self.variables.states[name]
        if name in self.variables.controls:
            return self.variables.controls[name]
        return None

    def get_equality(self, eq_id: str) -> Optional[OrigEqualityDef]:
        for e in self.equalities:
            if e.equality_id == eq_id:
                return e
        return None

    def get_inequality(self, ineq_id: str) -> Optional[OrigInequalityDef]:
        for e in self.inequalities:
            if e.inequality_id == ineq_id:
                return e
        return None

    def get_dynamics(self, dyn_id: str) -> Optional[OrigDynamicsDef]:
        for d in self.dynamics:
            if d.dynamics_id == dyn_id:
                return d
        return None

    def get_objective(self, obj_id: str) -> Optional[OrigObjectiveDef]:
        for o in self.objective:
            if o.objective_id == obj_id:
                return o
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Transcription
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IntroducedVarEffect:
    """An extra variable introduced by a transcription operation or time effect."""
    name: str
    role: str                   # "time_perturbation" | "scalar_nonnegative_slack" | ...
    grid: str                   # "scalar" | "node" | "interval"
    scale: str


@dataclass(frozen=True)
class ReplacedConstraint:
    """A replacement constraint produced by a transcription effect."""
    id: str
    grid: str
    range: Any = "all"
    expr: str = ""
    export: str = "G_h"


@dataclass(frozen=True)
class AddedObjectiveTerm:
    """An objective term added by a transcription effect."""
    expr: str


@dataclass(frozen=True)
class OperationEffects:
    """Side-effects declared by a transcription operation."""
    introduces_variables: List[IntroducedVarEffect] = field(default_factory=list)
    replaces_source_with_constraints: List[ReplacedConstraint] = field(default_factory=list)
    adds_objective_terms: List[AddedObjectiveTerm] = field(default_factory=list)


@dataclass(frozen=True)
class OperationDecl:
    """A single processing operation declared in transcription.operations."""
    id: str
    source: str = ""            # e.g. "model.dynamics.reentry"
    sources: List[str] = field(default_factory=list)
    operation: str = ""         # "dynamics_defect" | "boundary_equalities" | ...
    export: str = ""            # "A_b" | "G_h" | "objective"
    effects: Optional[OperationEffects] = None

    @property
    def all_sources(self) -> List[str]:
        if self.sources:
            return self.sources
        if self.source:
            return [self.source]
        return []


@dataclass(frozen=True)
class TimeEffectsDef:
    """How the time mode affects the subproblem."""
    source: str = "grid.time"
    introduces_variables: List[IntroducedVarEffect] = field(default_factory=list)
    new_constraints: List[ReplacedConstraint] = field(default_factory=list)
    dynamics_uses_time_perturbation: bool = False


@dataclass(frozen=True)
class OrigTranscriptionDef:
    """The transcription layer of the original problem."""
    discretization_mode: str = "perturbation"   # "perturbation" | "direct"
    time_effects: TimeEffectsDef = field(default_factory=TimeEffectsDef)
    operations: List[OperationDecl] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Codegen
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CodegenDef:
    """Code generation pipeline configuration."""
    pipeline: List[str] = field(default_factory=lambda: ["original_yaml", "subproblem_yaml", "c_code"])
    subproblem_output: str = ""
    c_output_dir: str = ""
    checks: Dict[str, bool] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Top-level container
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class OriginalProblemDef:
    """Complete original problem description."""
    meta: MetaDef
    grid: GridDef
    scales: Dict[str, float] = field(default_factory=dict)    # dimension → value
    model: OrigModelDef = field(default_factory=OrigModelDef)
    transcription: OrigTranscriptionDef = field(default_factory=OrigTranscriptionDef)
    codegen: CodegenDef = field(default_factory=CodegenDef)

    @property
    def N(self) -> int:
        return self.grid.N

    @property
    def n_nodes(self) -> int:
        return self.grid.n_nodes

    @property
    def final_node(self) -> int:
        return self.grid.final_node

    @property
    def n_states(self) -> int:
        return self.model.variables.n_states

    @property
    def n_controls(self) -> int:
        return self.model.variables.n_controls

    @property
    def vars_per_node(self) -> int:
        return self.model.variables.vars_per_node

    @property
    def n_node_variables(self) -> int:
        return self.n_nodes * self.vars_per_node
