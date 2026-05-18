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
    """
    Time discretization policy.

    interval_mode controls the time representation:
      - "fixed_interval": Time is fixed, no optimization variables.
        T is a fixed parameter. No time-related extra variables or G constraints.

      - "optimizable_uniform_interval": Time interval is an optimization variable.
        The exact interpretation depends on transcription.discretization_mode:

        * perturbation mode: introduces a scalar extra variable dT (time perturbation).
          Actual interval = T_ref + dT, total time = N * (T_ref + dT).
          If bounds [tf_min, tf_max] are given, auto-generates two G constraints.

        * direct mode: introduces a scalar extra variable T (time interval).
          Actual interval = T, total time = N * T.
          If bounds [tf_min, tf_max] are given, auto-generates two G constraints.

    Fields:
      - interval_mode: "fixed_interval" | "optimizable_uniform_interval"
      - interval_symbol: name for the time interval (default "T")
      - reference_interval_symbol: fixed reference interval for perturbation mode (default "T_ref")
      - perturbation_symbol: perturbation variable name for perturbation mode (default "dT")
      - total_time_expr: expression for total flight time (default "N * T")
      - bounds: [tf_min_param, tf_max_param] for auto-generating total-time G constraints
    """
    interval_mode: str = "fixed_interval"
    interval_symbol: str = "T"
    reference_interval_symbol: str = "T_ref"
    perturbation_symbol: str = "dT"
    total_time_expr: str = "N * T"
    bounds: List[str] = field(default_factory=list)  # [tf_min_param, tf_max_param]


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
class ScaleEntry:
    """
    A single dimensional scale entry.

    Two forms:
      - Base unit: value is a numeric literal (e.g. length: 10000.0)
      - Derived unit: value is an expression referencing other scale names
        (e.g. velocity: "length / time", acceleration: "velocity / time")
    """
    name: str
    value: Union[float, str]  # numeric for base, expression string for derived
    is_derived: bool = False   # True if value is an expression

    @property
    def numeric_value(self) -> Optional[float]:
        """Return numeric value if this is a base unit, None otherwise."""
        return self.value if isinstance(self.value, (int, float)) and not self.is_derived else None

    @property
    def expression(self) -> Optional[str]:
        """Return expression if this is a derived unit, None otherwise."""
        return self.value if self.is_derived else None


class ScaleDef:
    """
    Collection of scale entries with derived unit resolution.

    Design decisions:
    1. Syntax is restricted to a safe subset: numbers, scale names, +-*/^() sqrt()
       All other tokens (pi, sin, exp, pow, etc.) raise an error to keep the
       evaluator controllable.
    2. Dependencies are extracted once at construction time; a dependency graph
       is built and validated (no missing refs, no cycles) before any evaluation.
    3. Scales are resolved in topological order — each derived scale is evaluated
       exactly once with a simple eval() call.
    """

    # Whitelist of allowed identifiers in derived expressions
    _ALLOWED_IDENTIFIERS: frozenset = frozenset({'sqrt'})

    def __init__(self, entries: List[ScaleEntry]):
        self._entries = {e.name: e for e in entries}
        self._resolved: Dict[str, float] = {}
        self._deps: Dict[str, set] = {}        # name -> set of scale names it references
        self._topo_order: List[str] = []       # resolved in topological order

        self._build_dependency_graph()
        self._topological_sort()

    # ── Dependency graph construction ────────────────────────────────────────

    def _build_dependency_graph(self) -> None:
        """Extract dependencies for every derived scale; check for unknown references."""
        unknown_errors: List[str] = []
        for entry in self._entries.values():
            if entry.is_derived:
                deps = self._extract_scale_names_strict(entry.expression)
                self._deps[entry.name] = deps
                for d in deps:
                    if d not in self._entries:
                        unknown_errors.append(
                            f"Derived scale '{entry.name}' references unknown scale '{d}'"
                        )
            else:
                self._deps[entry.name] = set()

        if unknown_errors:
            raise ValueError("; ".join(unknown_errors))

    def _extract_scale_names_strict(self, expr: str) -> set:
        """
        Extract identifier tokens from an expression, returning only those that
        could be scale names (i.e. identifiers not in the whitelist).

        The expression grammar is intentionally restricted to:
          number | scale_name | (expr) | sqrt(expr) | expr ^ expr
          expr * expr | expr / expr | expr + expr | expr - expr
        So anything that looks like an identifier and is NOT 'sqrt' is treated
        as a scale name reference.
        """
        import re
        tokens = re.findall(r'\b[a-zA-Z_]\w*\b', expr)
        return {t for t in tokens if t not in self._ALLOWED_IDENTIFIERS}

    # ── Topological sort (Kahn's algorithm) ──────────────────────────────────

    def _topological_sort(self) -> None:
        """
        Sort all scale names so that dependencies come before dependents.
        Detects cycles and reports the full cycle path.
        """
        # Build adjacency: dep -> dependents
        dependents: Dict[str, set] = {name: set() for name in self._entries}
        for name, deps in self._deps.items():
            for d in deps:
                dependents[d].add(name)

        # Compute in-degree for each scale
        in_degree: Dict[str, int] = {name: len(self._deps.get(name, set()))
                                      for name in self._entries}

        # Start with all base scales (no dependencies)
        queue = [name for name, deg in in_degree.items() if deg == 0]
        self._topo_order = []

        while queue:
            # Process in alphabetical order for determinism
            queue.sort()
            node = queue.pop(0)
            self._topo_order.append(node)
            for dependent in dependents[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(self._topo_order) != len(self._entries):
            # Find cycle
            remaining = set(self._entries) - set(self._topo_order)
            # Trace one cycle
            cycle_node = next(iter(remaining))
            cycle = [cycle_node]
            cur = cycle_node
            while True:
                for dep in self._deps.get(cur, []):
                    if dep in remaining:
                        cycle.append(dep)
                        cur = dep
                        break
                if cur == cycle_node:
                    break
                if len(cycle) > len(self._entries):
                    break
            raise ValueError(f"Circular reference in scale definitions: {' -> '.join(cycle)}")

    # ── Resolution ─────────────────────────────────────────────────────────────

    def get_numeric(self, name: str) -> float:
        """Get numeric value for a scale, resolving derived units if needed."""
        if name in self._resolved:
            return self._resolved[name]

        if name not in self._entries:
            raise ValueError(f"Scale '{name}' not found")

        # Resolve all — since _topo_order is valid, just evaluate in order
        if not self._resolved:
            self._resolve_all_ordered()

        return self._resolved[name]

    def _resolve_all_ordered(self) -> None:
        """Evaluate all scales in topological order. Safe — no cycles possible."""
        import math
        ns = {'sqrt': math.sqrt}

        for name in self._topo_order:
            entry = self._entries[name]
            if entry.is_derived:
                expr = entry.expression.replace('^', '**')
                deps = self._deps[name]
                local_ns = dict(ns)
                for dep in deps:
                    local_ns[dep] = self._resolved[dep]
                try:
                    self._resolved[name] = float(eval(expr, {"__builtins__": {}}, local_ns))
                except ZeroDivisionError:
                    raise ValueError(f"Derived scale '{name}' expression '{expr}' causes division by zero")
                except Exception as e:
                    raise ValueError(f"Failed to evaluate derived scale '{name}': {e}")
            else:
                self._resolved[name] = float(entry.value)

    def get(self, name: str) -> Optional[ScaleEntry]:
        return self._entries.get(name)

    def resolve_all(self) -> Dict[str, float]:
        """Resolve all scales and return a dict of name -> numeric value."""
        if not self._resolved:
            self._resolve_all_ordered()
        return dict(self._resolved)

    def extract_scale_refs(self, expr: str) -> set:
        """Extract scale names referenced in an expression string."""
        return self._extract_scale_names_strict(expr)

    def resolve_expression(self, expr: str) -> float:
        """Resolve an expression string containing scale names to a numeric value."""
        if not self._resolved:
            self._resolve_all_ordered()
        processed = expr.replace('^', '**')
        deps = self._extract_scale_names_strict(processed)
        local_ns = {'sqrt': __import__('math').sqrt}
        for d in deps:
            local_ns[d] = self._resolved[d]
        return float(eval(processed, {"__builtins__": {}}, local_ns))

    def items(self):
        return self._entries.items()

    def __getitem__(self, name: str) -> ScaleEntry:
        return self._entries[name]

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __iter__(self):
        return iter(self._entries)


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
    """Objective term in the model layer.

    Supports both terminal and integral objectives via the same `expr` field:
      - Terminal cost: grid="terminal", expr="some_nonlinear_terminal_cost"
      - Integral cost:  grid="node", range=..., expr="integrand_expression"
    """
    objective_id: str
    grid: str                   # "node" | "interval" | "scalar" | "terminal"
    range: Any = "all"
    expr: str = ""              # expression (unified; replaces old `integrand`)
    weight: str = ""
    description: str = ""


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
    """An objective term added by a transcription effect
    (slack penalty, trust region penalty, virtual control penalty, etc.).

    Fields:
      - id: unique identifier for this added term (required)
      - expr: mathematical expression string
      - role: "slack_penalty" | "trust_region_penalty" | "virtual_control_penalty" (required)
      - expression_type: "quadratic" | "l1" | "linear"
      - approximation: "exact" | "first_order" | ...
      - output_form: "quadratic_penalty" | "l1_penalty" | "linear_cost"
    """
    id: str = ""
    expr: str = ""
    role: str = ""                 # "slack_penalty" | "trust_region_penalty" | "virtual_control_penalty"
    expression_type: str = ""      # "quadratic" | "l1" | "linear"
    approximation: str = "exact"
    output_form: str = ""


@dataclass(frozen=True)
class OperationEffects:
    """Side-effects declared by a transcription operation."""
    introduces_variables: List[IntroducedVarEffect] = field(default_factory=list)
    replaces_source_with_constraints: List[ReplacedConstraint] = field(default_factory=list)
    adds_objective_terms: List[AddedObjectiveTerm] = field(default_factory=list)


@dataclass(frozen=True)
class ApproximationDecl:
    """How a transcription operation approximates a model-level expression.

    Fields:
      - method: "first_order" | "exact_affine" | "exact_quadratic" | "none"
      - about: what the approximation is centered on: "reference" | "nominal" | ""
      - output_form: what form enters the subproblem:
          "linear_cost" | "quadratic_penalty" | "l1_penalty" | "norm_penalty"
    """
    method: str = ""            # "first_order" | "exact_affine" | "exact_quadratic" | "none"
    about: str = ""             # "reference" | "nominal" | ""
    output_form: str = ""       # "linear_cost" | "quadratic_penalty" | "l1_penalty" | "norm_penalty"
    # ── Discretization overrides (optional; compiler infers defaults from grid) ──
    quadrature: str = ""        # "none" | "trapezoidal" | "simpson"
    aggregation: str = ""       # "sum" | "mean" | "integral" | "none"
    time_weight_policy: str = ""  # "none" | "T_ref" | "T_ref_plus_dT" | "dT"


@dataclass(frozen=True)
class OperationDecl:
    """A single processing operation declared in transcription.operations."""
    id: str
    source: str = ""            # e.g. "model.dynamics.reentry"
    sources: List[str] = field(default_factory=list)
    operation: str = ""         # "dynamics_defect" | "boundary_equalities" | "linearize_objective" | ...
    export: str = ""            # "A_b" | "G_h" | "objective"
    approximation: Optional[ApproximationDecl] = None
    effects: Optional[OperationEffects] = None
    role_override: str = ""     # if non-empty, overrides _OBJECTIVE_OP_TABLE default role

    @property
    def all_sources(self) -> List[str]:
        if self.sources:
            return self.sources
        if self.source:
            return [self.source]
        return []


@dataclass(frozen=True)
class TimeEffectsDef:
    """
    DEPRECATED — time variable generation is now a compiler built-in rule.

    The SubproblemCompiler auto-generates time variables and constraints
    based on grid.time.interval_mode + transcription.discretization_mode.
    This dataclass is retained for backward compatibility but its fields
    are no longer used by the compiler.
    """
    source: str = "grid.time"
    introduces_variables: List[IntroducedVarEffect] = field(default_factory=list)
    new_constraints: List[ReplacedConstraint] = field(default_factory=list)


@dataclass(frozen=True)
class OrigTranscriptionDef:
    """The transcription layer of the original problem.

    Time variables and total-time constraints are now compiler built-in rules
    based on grid.time.interval_mode + discretization_mode.
    The deprecated transcription.time section is ignored (warning only).
    """
    discretization_mode: str = "perturbation"   # "perturbation" | "direct"
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
    scales: ScaleDef        # dimension → numeric value (with derived unit resolution)
    model: OrigModelDef
    transcription: OrigTranscriptionDef
    codegen: CodegenDef

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
