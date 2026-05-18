"""
Stage 1 Subproblem Compiler.

Reads an OriginalProblemDef and produces a fully-expanded SubProblemDef
(subproblem.yaml) with:
  - All variables (node + extra) with column indices
  - All equality/inequality blocks with row ranges
  - All objective terms in mathematical form
  - No solver-specific fields (no Q_c, G_h_q, soc_epigraph)

Lifecycle:
  1. parse_original_problem()  →  OriginalProblemDef
  2. SubproblemCompiler.compile()  →  SubProblemDef
  3. subproblem_to_dict()  →  dict for YAML serialization
"""

import re
from typing import Dict, List, Optional, Tuple

from .original_problem import (
    OriginalProblemDef, OrigModelDef, OrigTranscriptionDef,
    OrigDynamicsDef, OrigEqualityDef, OrigInequalityDef, OrigObjectiveDef,
    OperationDecl, OperationEffects, ReplacedConstraint,
)
from .subproblem_models import (
    SubProblemDef, SubMetaDef, SubDimensions, SubVariables,
    NodeVarEntry, ExtraVarEntry, SubTime,
    SubEqualities, SubInequalities, EqualityBlock, InequalityBlock,
    SubObjective, ObjectiveTerm, SubValidation, ValidationRule,
)


class SubproblemCompiler:
    """
    Stage 1 compiler: OriginalProblemDef → SubProblemDef.

    Produces a fully-expanded, solver-agnostic subproblem description.
    """

    def __init__(self, problem: OriginalProblemDef):
        self.problem = problem
        self._subproblem: Optional[SubProblemDef] = None

        # ── Guard: only node control grid is currently supported ──
        if problem.grid.control_grid != "node":
            raise ValueError(
                f"control_grid='{problem.grid.control_grid}' is not yet supported. "
                "Currently only control_grid='node' is implemented."
            )

        # Internal state during compilation
        self._next_extra_col: int = 0
        self._next_A_row: int = 0
        self._next_G_row: int = 0

    # ── Main entry ──────────────────────────────────────────────────────

    def compile(self) -> SubProblemDef:
        """Run all compilation stages and return the SubProblemDef."""
        dims = self._compute_dimensions()
        variables = self._allocate_all_variables(dims)
        time_info = self._build_time_info()
        equalities = self._allocate_equality_rows(dims)
        inequalities = self._allocate_inequality_rows(dims)
        objective = self._process_objective_terms()

        # Update dimensions with actual objective term count (post-processing)
        dims.objective_terms = len(objective.terms)

        validation = self._build_validation_section()

        # Copy scale table (resolved to numeric values), expressions, and dynamics from original problem
        scale_table = self.problem.scales.resolve_all()
        expressions = [
            {"name": e.name, "expr": e.expr}
            for e in self.problem.model.expressions
        ]
        dynamics = [
            {
                "dynamics_id": d.dynamics_id,
                "states": list(d.states),
                "controls": list(d.controls),
                "rhs": dict(d.rhs),
            }
            for d in self.problem.model.dynamics
        ]

        self._subproblem = SubProblemDef(
            meta=SubMetaDef(
                name=self.problem.meta.name,
                generated_from="",  # filled by caller
                discretization_mode=self.problem.transcription.discretization_mode,
            ),
            dimensions=dims,
            scale_table=scale_table,
            variables=variables,
            parameters=dict(self.problem.model.parameters),
            expressions=expressions,
            dynamics=dynamics,
            time=time_info,
            equalities=equalities,
            inequalities=inequalities,
            objective=objective,
            validation=validation,
        )
        return self._subproblem

    # ══════════════════════════════════════════════════════════════════════
    # Phase 1: Dimensions & Variables
    # ══════════════════════════════════════════════════════════════════════

    def _compute_dimensions(self) -> SubDimensions:
        """Compute all problem sizes."""
        p = self.problem
        n_node_vars = p.n_node_variables

        # Count extra variables
        n_extra = 0

        # ── Time variable (compiler built-in rule) ──
        # Based on grid.time.interval_mode + transcription.discretization_mode
        if self._time_is_optimizable():
            n_extra += 1

        # Operation effects
        for op in p.transcription.operations:
            if op.effects:
                for _ in op.effects.introduces_variables:
                    n_extra += 1

        # Count objective terms (all operations with export="objective")
        n_obj_terms = 0
        for op in p.transcription.operations:
            if op.export == "objective":
                n_obj_terms += len(op.all_sources)
            if op.effects:
                n_obj_terms += len(op.effects.adds_objective_terms)

        return SubDimensions(
            N=p.N,
            n_nodes=p.n_nodes,
            final_node=p.final_node,
            n_states=p.n_states,
            n_controls=p.n_controls,
            vars_per_node=p.vars_per_node,
            n_node_variables=n_node_vars,
            n_extra_variables=n_extra,
            nvar=n_node_vars + n_extra,
            neq=0,   # filled after row allocation
            nineq=0,
            objective_terms=n_obj_terms,
        )

    def _allocate_all_variables(self, dims: SubDimensions) -> SubVariables:
        """Allocate all node and extra variables."""
        self._next_extra_col = dims.n_node_variables

        node_vars = self._allocate_node_variables()
        extra_vars = self._allocate_extra_variables()

        return SubVariables(
            node_order={
                "states": self.problem.model.variables.state_names,
                "controls": self.problem.model.variables.control_names,
            },
            node_variables=node_vars,
            extra_variables=extra_vars,
        )

    def _allocate_node_variables(self) -> List[NodeVarEntry]:
        """Expand node variables in model.variables.states/controls order."""
        p = self.problem
        vars_per_node = p.vars_per_node
        entries: List[NodeVarEntry] = []

        # States first (offsets 0..n_states-1)
        for offset, name in enumerate(p.model.variables.state_names):
            scale = p.model.variables.states[name]
            entries.append(NodeVarEntry(
                name=name, kind="state", grid="node",
                scale=scale, node_offset=offset,
                col=f"k * VARS_PER_NODE + {offset}",
            ))

        # Controls next (offsets n_states..vars_per_node-1)
        for i, name in enumerate(p.model.variables.control_names):
            offset = p.n_states + i
            scale = p.model.variables.controls[name]
            entries.append(NodeVarEntry(
                name=name, kind="control", grid="node",
                scale=scale, node_offset=offset,
                col=f"k * VARS_PER_NODE + {offset}",
            ))

        return entries

    def _allocate_extra_variables(self) -> List[ExtraVarEntry]:
        """Allocate extra variables from compiler built-in rules and operation effects."""
        entries: List[ExtraVarEntry] = []
        p = self.problem

        # ── Time variable (compiler built-in rule) ──
        # Based on grid.time.interval_mode + transcription.discretization_mode:
        #   fixed_interval:              no time variable
        #   optimizable_uniform_interval + perturbation: dT (time_perturbation)
        #   optimizable_uniform_interval + direct:       T  (time_interval)
        if self._time_is_optimizable():
            grid_time = p.grid.time
            disc_mode = p.transcription.discretization_mode
            if disc_mode == "perturbation":
                var_name = grid_time.perturbation_symbol  # "dT"
                role = "time_perturbation"
            else:  # direct
                var_name = grid_time.interval_symbol  # "T"
                role = "time_interval"

            entries.append(ExtraVarEntry(
                name=var_name, role=role, grid="scalar",
                scale="time", col=self._next_extra_col,
                source="compiler.time",
            ))
            self._next_extra_col += 1

        # ── Operation-introduced variables (slacks, etc.) ──
        for op in p.transcription.operations:
            if op.effects:
                for iv in op.effects.introduces_variables:
                    entries.append(ExtraVarEntry(
                        name=iv.name, role=iv.role, grid=iv.grid,
                        scale=iv.scale, col=self._next_extra_col,
                        source=f"transcription.operations.{op.id}",
                    ))
                    self._next_extra_col += 1

        return entries

    # ══════════════════════════════════════════════════════════════════════
    # Phase 2: Row Allocation
    # ══════════════════════════════════════════════════════════════════════

    def _allocate_equality_rows(self, dims: SubDimensions) -> SubEqualities:
        """Process all operations that export A_b, allocate A rows sequentially."""
        p = self.problem
        blocks: List[EqualityBlock] = []
        self._next_A_row = 0

        for op in p.transcription.operations:
            if op.export != "A_b":
                continue

            if op.operation == "dynamics_defect":
                blk = self._eq_dynamics_defect(op, dims)
                if blk:
                    blocks.append(blk)
            elif op.operation == "boundary_equalities":
                blk = self._eq_boundary_equalities(op, dims)
                if blk:
                    blocks.append(blk)
            else:
                # Generic: skip unknown
                pass

        total_rows = self._next_A_row
        dims.neq = total_rows
        return SubEqualities(total_rows=total_rows, blocks=blocks)

    def _eq_dynamics_defect(self, op: OperationDecl,
                            dims: SubDimensions) -> Optional[EqualityBlock]:
        """Dynamics defect: n_states rows per interval."""
        p = self.problem
        N = p.N
        n_states = p.n_states
        row_count = n_states * N

        if row_count == 0:
            return None

        row_start = self._next_A_row
        self._next_A_row += row_count
        row_end = row_start + row_count - 1

        src_models = [op.source] if op.source else list(op.all_sources)

        return EqualityBlock(
            id=op.id,
            source_models=src_models,
            source_operation=op.operation,
            export="A_b",
            row_start=row_start,
            row_count=row_count,
            row_end=row_end,
            grid="interval",
            range=[0, N - 1],
            processor="dynamics_defect",
            A_rows=[row_start, row_end],
        )

    def _eq_boundary_equalities(self, op: OperationDecl,
                                 dims: SubDimensions) -> Optional[EqualityBlock]:
        """Boundary equalities: one row per equation (var@node = value).

        Generates per-row detail (boundary_rows) so C backend knows exactly
        which variable, at which node, equals which parameter.
        """
        p = self.problem
        boundary_rows: List[dict] = []
        current_row = self._next_A_row

        for src_path in op.all_sources:
            eq = self._resolve_equality_source(src_path)
            if eq is None:
                continue
            # Resolve node: 'at' can be int or 'N'
            node_val = eq.at
            if isinstance(node_val, str) and node_val.upper() == "N":
                node_val = p.final_node
            else:
                node_val = int(node_val)

            for var_name, rhs_expr in eq.equations.items():
                boundary_rows.append({
                    "row": current_row,
                    "variable": var_name,
                    "node": node_val,
                    "rhs_param": str(rhs_expr),
                })
                current_row += 1

        total_count = len(boundary_rows)
        if total_count == 0:
            return None

        row_start = self._next_A_row
        self._next_A_row += total_count
        row_end = row_start + total_count - 1

        return EqualityBlock(
            id=op.id,
            source_models=list(op.all_sources),
            source_operation=op.operation,
            export="A_b",
            row_start=row_start,
            row_count=total_count,
            row_end=row_end,
            grid="node",
            range=[0, p.final_node],
            processor="boundary_equalities",
            A_rows=[row_start, row_end],
            boundary_rows=boundary_rows,
        )

    # ── Inequality Rows ─────────────────────────────────────────────────

    def _allocate_inequality_rows(self, dims: SubDimensions) -> SubInequalities:
        """Process all operations that export G_h, allocate G rows sequentially."""
        p = self.problem
        blocks: List[InequalityBlock] = []
        self._next_G_row = 0

        # ── Time bounds: compiler auto-generated total_time constraints ──
        # Based on grid.time.bounds + transcription.discretization_mode.
        # The bounds [tf_min, tf_max] in grid.time are parameter names.
        if self._time_is_optimizable() and p.grid.time.bounds:
            blks = self._ineq_time_bounds_auto()
            blocks.extend(blks)

        for op in p.transcription.operations:
            if op.export != "G_h":
                continue

            if op.operation == "affine_bounds":
                blks = self._ineq_affine_bounds(op, dims)
                blocks.extend(blks)
            elif op.operation == "linearize_path_ineq":
                blks = self._ineq_linearize_path(op, dims)
                blocks.extend(blks)
            else:
                pass

        total_rows = self._next_G_row
        dims.nineq = total_rows
        return SubInequalities(total_rows=total_rows, blocks=blocks)

    def _ineq_scalar_constraint(self, nc: ReplacedConstraint,
                                 source_operation: str = "transcription.time") -> Optional[InequalityBlock]:
        """A scalar inequality constraint (1 row)."""
        row_start = self._next_G_row
        self._next_G_row += 1
        row_end = row_start

        rng = self._format_range(nc.range, nc.grid, self.problem.N)

        return InequalityBlock(
            id=nc.id,
            source_models=[],
            source_operation=source_operation,
            export="G_h",
            row_start=row_start,
            row_count=1,
            row_end=row_end,
            grid=nc.grid,
            range=rng,
            processor="time_bounds" if "time" in source_operation else "scalar_constraint",
            expr=nc.expr,
            G_rows=[row_start, row_end],
        )

    def _ineq_time_bounds_auto(self) -> List[InequalityBlock]:
        """
        Auto-generate total time G constraints from grid.time.bounds.

        Called when interval_mode == "optimizable_uniform_interval" and bounds are given.

        The constraints depend on discretization_mode:
          - perturbation: tf_min - N*(T_ref + dT) <= 0   and   N*(T_ref + dT) - tf_max <= 0
          - direct:       tf_min - N*T <= 0               and   N*T - tf_max <= 0

        Returns two InequalityBlocks (lower + upper), each with 1 scalar row.
        """
        p = self.problem
        grid_time = p.grid.time
        disc_mode = p.transcription.discretization_mode
        bounds = grid_time.bounds  # [tf_min_param, tf_max_param]
        N = p.N

        if disc_mode == "perturbation":
            ref_sym = grid_time.reference_interval_symbol   # "T_ref"
            pert_sym = grid_time.perturbation_symbol         # "dT"
            total_expr = f"{N} * ({ref_sym} + {pert_sym})"
        else:  # direct
            int_sym = grid_time.interval_symbol              # "T"
            total_expr = f"{N} * {int_sym}"

        tf_min = bounds[0] if len(bounds) > 0 else "tf_min"
        tf_max = bounds[1] if len(bounds) > 1 else "tf_max"

        blocks: List[InequalityBlock] = []

        # Lower bound: tf_min - total_expr <= 0
        lower_start = self._next_G_row
        self._next_G_row += 1
        blocks.append(InequalityBlock(
            id="total_time_lower",
            source_models=["grid.time"],
            source_operation="compiler.time",
            export="G_h",
            row_start=lower_start,
            row_count=1,
            row_end=lower_start,
            grid="scalar",
            range=None,
            processor="total_time_bounds",
            bound_type="lower",
            expr=f"{tf_min} - {total_expr} <= 0",
            G_rows=[lower_start, lower_start],
        ))

        # Upper bound: total_expr - tf_max <= 0
        upper_start = self._next_G_row
        self._next_G_row += 1
        blocks.append(InequalityBlock(
            id="total_time_upper",
            source_models=["grid.time"],
            source_operation="compiler.time",
            export="G_h",
            row_start=upper_start,
            row_count=1,
            row_end=upper_start,
            grid="scalar",
            range=None,
            processor="total_time_bounds",
            bound_type="upper",
            expr=f"{total_expr} - {tf_max} <= 0",
            G_rows=[upper_start, upper_start],
        ))

        return blocks

    def _ineq_affine_bounds(self, op: OperationDecl,
                             dims: SubDimensions) -> List[InequalityBlock]:
        """Affine bounds: box constraints split into lower/upper, simple inequalities."""
        p = self.problem
        blocks: List[InequalityBlock] = []

        for src_path in op.all_sources:
            ineq = self._resolve_inequality_source(src_path)
            if ineq is None:
                continue

            nodes = self._resolve_range(ineq.range, ineq.grid, p.N)
            n_nodes_in_range = len(nodes)

            expr = ineq.expr
            is_box = bool(re.match(
                r'^[\w\.\[\]]+\s*<=\s*[\w\.\[\]]+\[k\]\s*<=\s*[\w\.\[\]]+$',
                expr.replace(' ', '')
            ))

            if is_box:
                # Split into two canonical blocks: lower first, then upper
                lower_expr, upper_expr = self._split_box_expr(expr)
                rng = [nodes[0], nodes[-1]]

                # Lower block
                lower_count = n_nodes_in_range
                lower_start = self._next_G_row
                self._next_G_row += lower_count
                lower_end = lower_start + lower_count - 1
                blocks.append(InequalityBlock(
                    id=f"{ineq.inequality_id}_lower",
                    source_models=[src_path],
                    source_operation=op.operation,
                    export="G_h",
                    row_start=lower_start,
                    row_count=lower_count,
                    row_end=lower_end,
                    grid=ineq.grid,
                    range=rng,
                    processor="affine_bounds",
                    bound_type="lower",
                    expr=lower_expr,
                    G_rows=[lower_start, lower_end],
                ))

                # Upper block
                upper_count = n_nodes_in_range
                upper_start = self._next_G_row
                self._next_G_row += upper_count
                upper_end = upper_start + upper_count - 1
                blocks.append(InequalityBlock(
                    id=f"{ineq.inequality_id}_upper",
                    source_models=[src_path],
                    source_operation=op.operation,
                    export="G_h",
                    row_start=upper_start,
                    row_count=upper_count,
                    row_end=upper_end,
                    grid=ineq.grid,
                    range=rng,
                    processor="affine_bounds",
                    bound_type="upper",
                    expr=upper_expr,
                    G_rows=[upper_start, upper_end],
                ))
            else:
                # Simple inequality: 1 row per node
                row_count = n_nodes_in_range
                if row_count == 0:
                    continue
                row_start = self._next_G_row
                self._next_G_row += row_count
                row_end = row_start + row_count - 1
                rng = [nodes[0], nodes[-1]]

                blocks.append(InequalityBlock(
                    id=ineq.inequality_id,
                    source_models=[src_path],
                    source_operation=op.operation,
                    export="G_h",
                    row_start=row_start,
                    row_count=row_count,
                    row_end=row_end,
                    grid=ineq.grid,
                    range=rng,
                    processor="affine_bounds",
                    expr=expr,
                    G_rows=[row_start, row_end],
                ))

        return blocks

    def _ineq_linearize_path(self, op: OperationDecl,
                              dims: SubDimensions) -> List[InequalityBlock]:
        """Linearized path constraints, possibly with replacement + slack."""
        p = self.problem
        blocks: List[InequalityBlock] = []

        src_path = op.source or (op.all_sources[0] if op.all_sources else "")
        ineq = self._resolve_inequality_source(src_path)

        if op.effects and op.effects.replaces_source_with_constraints:
            for rc in op.effects.replaces_source_with_constraints:
                if rc.grid == "scalar":
                    row_count = 1
                    nodes = []
                    rng = None
                else:
                    nodes = self._resolve_range(rc.range, rc.grid, p.N)
                    row_count = len(nodes)
                    rng = [nodes[0], nodes[-1]]

                row_start = self._next_G_row
                self._next_G_row += row_count
                row_end = row_start + row_count - 1

                processor = "linearize_path_ineq"
                if "nonnegative" in rc.id or "slack" in rc.id.lower():
                    processor = "slack_nonnegative"

                blocks.append(InequalityBlock(
                    id=rc.id,
                    source_models=[src_path],
                    source_operation=op.id,
                    export="G_h",
                    row_start=row_start,
                    row_count=row_count,
                    row_end=row_end,
                    grid=rc.grid,
                    range=rng,
                    processor=processor,
                    expr=rc.expr,
                    G_rows=[row_start, row_end],
                ))
        else:
            if ineq:
                nodes = self._resolve_range(ineq.range, ineq.grid, p.N)
                n_nodes = len(nodes)
                row_count = n_nodes
                rng = [nodes[0], nodes[-1]]

                row_start = self._next_G_row
                self._next_G_row += row_count
                row_end = row_start + row_count - 1

                blocks.append(InequalityBlock(
                    id=ineq.inequality_id,
                    source_models=[src_path],
                    source_operation=op.id,
                    export="G_h",
                    row_start=row_start,
                    row_count=row_count,
                    row_end=row_end,
                    grid=ineq.grid,
                    range=rng,
                    processor="linearize_path_ineq",
                    expr=ineq.expr,
                    G_rows=[row_start, row_end],
                ))

        return blocks

    # ══════════════════════════════════════════════════════════════════════
    # Phase 2.3: Objective Terms
    # ══════════════════════════════════════════════════════════════════════

    # ── Operation → ObjectiveTerm semantics mapping ──
    _OBJECTIVE_OP_TABLE = {
        "linearize_objective": {
            "role": "original_cost",
            "expression_type": "nonlinear",
            "approximation": "first_order",
            "output_form": "linear_cost",
            "reference_dependent": True,
            "stage2_action": "linearize_objective",
            "stage3_action": "keep_linear_cost",
        },
        "keep_quadratic_penalty": {
            "role": "smoothing_penalty",
            "expression_type": "quadratic",
            "approximation": "exact_quadratic",
            "output_form": "quadratic_penalty",
            "reference_dependent": False,
            "stage2_action": "discretize_objective",
            "stage3_action": "convert_quadratic_to_socp",
        },
        "add_trust_region_penalty": {
            "role": "trust_region_penalty",
            "expression_type": "quadratic",
            "approximation": "exact_quadratic",
            "output_form": "quadratic_penalty",
            "reference_dependent": True,
            "stage2_action": "keep_as_is",
            "stage3_action": "convert_quadratic_to_socp",
        },
        "keep_linear_term": {
            "role": "original_cost",
            "expression_type": "affine",
            "approximation": "exact_affine",
            "output_form": "linear_cost",
            "reference_dependent": False,
            "stage2_action": "keep_as_is",
            "stage3_action": "keep_linear_cost",
        },
    }

    def _process_objective_terms(self) -> SubObjective:
        """Collect objective terms from model objectives and transcription effects.

        For each operation with export="objective":
          - Use op.operation + op.approximation to determine semantics
          - Resolve model.objective.<id> sources for expr, weight, grid, range
          - If op.role_override is set, it overrides the table's default role.
          - Strict: missing approximation raises ValueError.

        For each operation's effects.adds_objective_terms:
          - Use AddedObjectiveTerm's own role/expression_type fields.
          - Automatically set source_effect and source_model for traceability.
        """
        p = self.problem
        terms: List[ObjectiveTerm] = []

        for op in p.transcription.operations:
            # ── Model-level objective terms (export="objective") ──
            if op.export == "objective" and op.all_sources:
                semantics = self._OBJECTIVE_OP_TABLE.get(op.operation)
                if semantics is None:
                    raise ValueError(
                        f"Operation '{op.id}' has export='objective' but unknown "
                        f"operation='{op.operation}'. Supported: "
                        f"{list(self._OBJECTIVE_OP_TABLE.keys())}"
                    )
                if op.approximation is None:
                    raise ValueError(
                        f"Operation '{op.id}' (export=objective) is missing required "
                        f"'approximation' sub-block (method, about, output_form)."
                    )

                # ── Role: explicit override > table default ──
                role = op.role_override or semantics["role"]

                for src_path in op.all_sources:
                    obj = self._resolve_objective_source(src_path)
                    if obj:
                        expr_str = (
                            f"{obj.weight} * ({obj.expr})" if obj.weight else obj.expr
                        )
                        nodes = self._resolve_range(obj.range, obj.grid, p.N)
                        rng = [nodes[0], nodes[-1]] if nodes else None

                        # ── Quadrature: explicit override > inferred from grid ──
                        quad, agg, twp = self._infer_quadrature(
                            obj.grid, semantics, op.approximation
                        )

                        stage2 = semantics["stage2_action"]
                        stage3 = semantics["stage3_action"]
                        next_stage = f"{stage2}_then_{stage3}"

                        terms.append(ObjectiveTerm(
                            id=obj.objective_id,
                            source_model=src_path,
                            source_operation=op.id,
                            source_effect="",
                            role=role,
                            expression_type=semantics["expression_type"],
                            approximation=(
                                op.approximation.method or semantics["approximation"]
                            ),
                            reference_dependent=semantics["reference_dependent"],
                            output_form=(
                                op.approximation.output_form or semantics["output_form"]
                            ),
                            stage2_action=stage2,
                            stage3_action=stage3,
                            next_stage_action=next_stage,
                            quadrature=quad,
                            aggregation=agg,
                            time_weight_policy=twp,
                            grid=obj.grid,
                            range=rng,
                            expr=expr_str,
                        ))

            # ── Added objective terms from effects (slack penalties, etc.) ──
            if op.effects and op.effects.adds_objective_terms:
                for ao in op.effects.adds_objective_terms:
                    source_effect = f"{op.id}.effects.adds_objective_terms.{ao.id}"
                    terms.append(ObjectiveTerm(
                        id=ao.id,
                        source_model=op.source,
                        source_operation=op.id,
                        source_effect=source_effect,
                        role=ao.role,
                        expression_type=ao.expression_type or "quadratic",
                        approximation=ao.approximation,
                        reference_dependent=False,
                        output_form=ao.output_form or "quadratic_penalty",
                        stage2_action="keep_as_is",
                        stage3_action="convert_quadratic_to_socp",
                        next_stage_action="keep_as_is_then_convert_quadratic_to_socp",
                        quadrature="none",
                        aggregation="none",
                        time_weight_policy="none",
                        grid="scalar",
                        range=None,
                        expr=ao.expr,
                    ))

        return SubObjective(terms=terms)

    @staticmethod
    def _infer_quadrature(
        grid: str,
        semantics: dict,
        approx,
    ) -> tuple:
        """Infer quadrature/aggregation/time_weight_policy defaults from grid type.

        Explicit overrides from approx (ApproximationDecl) take precedence.
        """
        # Start with explicit overrides from approximation block
        quad = approx.quadrature if approx and approx.quadrature else ""
        agg = approx.aggregation if approx and approx.aggregation else ""
        twp = approx.time_weight_policy if approx and approx.time_weight_policy else ""

        # If no explicit override, infer from grid
        if not quad:
            if grid in ("node", "interval"):
                quad = "trapezoidal"
            else:
                quad = "none"

        if not agg:
            if grid in ("node", "interval"):
                agg = "integral"
            else:
                agg = "none"

        if not twp:
            if grid in ("node", "interval"):
                twp = "T_ref_plus_dT"
            else:
                twp = "none"

        return (quad, agg, twp)

    # ══════════════════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════════════════

    def _time_is_optimizable(self) -> bool:
        """Check if time interval is an optimization variable.

        Returns True for optimizable_uniform_interval (both perturbation and direct modes).
        Returns False for fixed_interval.
        """
        return self.problem.grid.time.interval_mode == "optimizable_uniform_interval"

    def _resolve_equality_source(self, src_path: str) -> Optional[OrigEqualityDef]:
        """Resolve 'model.equalities.<id>' → OrigEqualityDef."""
        parts = src_path.split(".")
        if len(parts) >= 3 and parts[0] == "model" and parts[1] == "equalities":
            eq_id = parts[2]
            return self.problem.model.get_equality(eq_id)
        return None

    def _resolve_inequality_source(self, src_path: str) -> Optional[OrigInequalityDef]:
        """Resolve 'model.inequalities.<id>' → OrigInequalityDef."""
        parts = src_path.split(".")
        if len(parts) >= 3 and parts[0] == "model" and parts[1] == "inequalities":
            ineq_id = parts[2]
            return self.problem.model.get_inequality(ineq_id)
        return None

    def _resolve_dynamics_source(self, src_path: str) -> Optional[OrigDynamicsDef]:
        """Resolve 'model.dynamics.<id>' → OrigDynamicsDef."""
        parts = src_path.split(".")
        if len(parts) >= 3 and parts[0] == "model" and parts[1] == "dynamics":
            dyn_id = parts[2]
            return self.problem.model.get_dynamics(dyn_id)
        return None

    def _resolve_objective_source(self, src_path: str) -> Optional[OrigObjectiveDef]:
        """Resolve 'model.objective.<id>' → OrigObjectiveDef."""
        parts = src_path.split(".")
        if len(parts) >= 3 and parts[0] == "model" and parts[1] == "objective":
            obj_id = parts[2]
            return self.problem.model.get_objective(obj_id)
        return None

    @staticmethod
    def _resolve_range(range_spec, grid: str, N: int) -> List[int]:
        """Resolve range spec → list of node/interval indices, grid-aware.

        grid="node":     "all" or None → [0, 1, ..., N]       (N+1 nodes)
        grid="interval": "all" or None → [0, 1, ..., N-1]     (N intervals)
        grid="scalar":   → []  (no expansion)
        """
        if grid == "scalar":
            return []
        if range_spec is None or range_spec == "all":
            if grid in ("interval", "edge"):
                return list(range(N))
            else:
                return list(range(N + 1))  # node grid
        if isinstance(range_spec, list) and len(range_spec) == 2:
            start = range_spec[0]
            end = range_spec[1]
            if isinstance(start, str) and start.upper() == "N":
                start = N
            if isinstance(end, str) and end.upper() == "N":
                end = N
            start = int(start)
            end = int(end)
            return list(range(start, end + 1))
        # Fallback
        if grid in ("interval", "edge"):
            return list(range(N))
        return list(range(N + 1))

    @staticmethod
    def _format_range(range_spec, grid: str, N: int) -> Optional[List[int]]:
        """Format range as concrete [start, end] list for output. Never returns 'all'.

        grid="node":     "all" → [0, N]
        grid="interval": "all" → [0, N-1]
        grid="scalar":   → None
        """
        if grid == "scalar":
            return None
        if range_spec is None or range_spec == "all":
            if grid in ("interval", "edge"):
                return [0, N - 1]
            return [0, N]
        if isinstance(range_spec, list) and len(range_spec) == 2:
            s, e = range_spec[0], range_spec[1]
            if isinstance(s, str) and s.upper() == "N":
                s = N
            if isinstance(e, str) and e.upper() == "N":
                e = N
            return [int(s), int(e)]
        return None

    @staticmethod
    def _split_box_expr(expr: str) -> Tuple[str, str]:
        """Split 'lower <= var[k] <= upper' into (lower_expr, upper_expr).

        Returns:
            ("lower - var[k] <= 0", "var[k] - upper <= 0")
        """
        # Find the two '<=' separators
        parts = expr.split("<=")
        if len(parts) != 3:
            return (expr, expr)  # fallback

        lower = parts[0].strip()
        var_expr = parts[1].strip()
        upper = parts[2].strip()

        # Canonical form: lower - var <= 0  and  var - upper <= 0
        lower_canon = f"{lower} - {var_expr} <= 0"
        upper_canon = f"{var_expr} - {upper} <= 0"
        return (lower_canon, upper_canon)

    # ══════════════════════════════════════════════════════════════════════
    # Time Info
    # ══════════════════════════════════════════════════════════════════════

    def _build_time_info(self) -> SubTime:
        """
        Build the time section for subproblem YAML.

        Uses compiler built-in rules based on:
          - grid.time.interval_mode
          - transcription.discretization_mode (perturbation | direct)

        fixed_interval:
          No perturbation variable, no perturbed interval, total_time = N * T.

        optimizable_uniform_interval + perturbation:
          perturbation_variable = dT (from TimeDef.perturbation_symbol)
          perturbed_interval_expr = "T_ref + dT"
          total_time_expr = "N * (T_ref + dT)"

        optimizable_uniform_interval + direct:
          No perturbation variable.
          interval_symbol = T is the optimization variable.
          total_time_expr = "N * T"
        """
        p = self.problem
        grid_time = p.grid.time
        disc_mode = p.transcription.discretization_mode
        is_optimizable = grid_time.interval_mode == "optimizable_uniform_interval"

        interval_sym = grid_time.interval_symbol
        ref_sym = grid_time.reference_interval_symbol
        pert_sym = grid_time.perturbation_symbol
        bounds = list(grid_time.bounds) if grid_time.bounds else []

        if is_optimizable and disc_mode == "perturbation":
            pert_var = pert_sym
            pert_expr = f"{ref_sym} + {pert_sym}"
            total_expr = f"{p.N} * ({ref_sym} + {pert_sym})"
            bound_ids = ["total_time_lower", "total_time_upper"] if bounds else []
        elif is_optimizable and disc_mode == "direct":
            pert_var = None
            pert_expr = None
            total_expr = f"{p.N} * {interval_sym}"
            bound_ids = ["total_time_lower", "total_time_upper"] if bounds else []
        else:
            # fixed_interval
            pert_var = None
            pert_expr = None
            total_expr = grid_time.total_time_expr
            bound_ids = []

        # Determine unified time_variable and role
        if is_optimizable and disc_mode == "perturbation":
            time_var = pert_sym
            time_role = "time_perturbation"
        elif is_optimizable and disc_mode == "direct":
            time_var = interval_sym
            time_role = "time_interval"
        else:
            time_var = None
            time_role = None

        return SubTime(
            interval_mode=grid_time.interval_mode,
            interval_symbol=interval_sym,
            reference_interval_symbol=ref_sym,
            time_variable=time_var,
            time_variable_role=time_role,
            perturbation_variable=pert_var,
            perturbed_interval_expr=pert_expr,
            total_time_expr=total_expr,
            bound_parameters=bounds,
            bound_constraint_ids=bound_ids,
        )

    # ══════════════════════════════════════════════════════════════════════
    # Validation Section
    # ══════════════════════════════════════════════════════════════════════

    def _build_validation_section(self) -> SubValidation:
        """Build the validation metadata section.

        The required_checks list MUST match the actual check names registered
        in subproblem_validator.validate_subproblem().
        """
        return SubValidation(
            row_convention=ValidationRule(),
            required_checks=[
                "all_variables_have_unique_columns",
                "all_extra_variables_have_columns",
                "all_parameters_declared",
                "all_sources_exist",
                "equality_rows_are_contiguous",
                "inequality_rows_are_contiguous",
                "equality_total_rows_match_neq",
                "inequality_total_rows_match_nineq",
                "scalar_slacks_not_expanded_as_node_variables",
                "no_solver_specific_fields",
                "time_variable_three_way",
                "objective_terms_have_role",
                "nonlinear_objective_has_approximation",
                "quadratic_not_mislabeled_as_linear",
                "slack_penalty_references_exist",
                "trust_region_penalty_has_scope",
                "row_end_matches_row_start_plus_count_minus_one",
                "all_scale_references_resolved",
                "scale_table_all_values_finite",
            ],
        )
