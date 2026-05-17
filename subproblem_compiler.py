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
        validation = self._build_validation_section()

        # Copy scale table, expressions, and dynamics from original problem
        scale_table = dict(self.problem.scales)
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
        # Time effects
        for _ in p.transcription.time_effects.introduces_variables:
            n_extra += 1
        # Operation effects
        for op in p.transcription.operations:
            if op.effects:
                for _ in op.effects.introduces_variables:
                    n_extra += 1

        # Count objective terms
        n_obj_terms = 0
        for op in p.transcription.operations:
            if op.operation == "discretize_objective_integral":
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
        """Allocate extra variables from time effects and operation effects."""
        entries: List[ExtraVarEntry] = []
        p = self.problem

        # ── Time perturbation variable ──
        time_eff = p.transcription.time_effects
        for iv in time_eff.introduces_variables:
            entries.append(ExtraVarEntry(
                name=iv.name, role=iv.role, grid=iv.grid,
                scale=iv.scale, col=self._next_extra_col,
                source="transcription.time",
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

        src_model = op.source or (op.all_sources[0] if op.all_sources else "")

        return EqualityBlock(
            id=op.id,
            source_model=src_model,
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
            source_model=", ".join(op.all_sources),
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

        # ── Time constraints (if optimizable) ──
        time_eff = p.transcription.time_effects
        if time_eff.new_constraints:
            for nc in time_eff.new_constraints:
                blk = self._ineq_scalar_constraint(nc, source_operation="transcription.time")
                if blk:
                    blocks.append(blk)

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

        rng = self._format_range(nc.range, self.problem.final_node, nc.grid)

        return InequalityBlock(
            id=nc.id,
            source_model="",
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

    def _ineq_affine_bounds(self, op: OperationDecl,
                             dims: SubDimensions) -> List[InequalityBlock]:
        """Affine bounds: box constraints split into lower/upper, simple inequalities."""
        p = self.problem
        blocks: List[InequalityBlock] = []

        for src_path in op.all_sources:
            ineq = self._resolve_inequality_source(src_path)
            if ineq is None:
                continue

            nodes = self._resolve_range(ineq.range, p.final_node)
            n_nodes_in_range = len(nodes)

            expr = ineq.expr
            is_box = ("<=" in expr and "=" not in expr.replace("<=", "")) and \
                     expr.count("<=") == 2

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
                    source_model=src_path,
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
                    source_model=src_path,
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
                    source_model=src_path,
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
                    nodes = self._resolve_range(rc.range, p.final_node)
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
                    source_model=src_path,
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
                nodes = self._resolve_range(ineq.range, p.final_node)
                n_nodes = len(nodes)
                row_count = n_nodes
                rng = [nodes[0], nodes[-1]]

                row_start = self._next_G_row
                self._next_G_row += row_count
                row_end = row_start + row_count - 1

                blocks.append(InequalityBlock(
                    id=ineq.inequality_id,
                    source_model=src_path,
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

    def _process_objective_terms(self) -> SubObjective:
        """Collect objective terms from model and transcription effects."""
        p = self.problem
        terms: List[ObjectiveTerm] = []

        for op in p.transcription.operations:
            if op.operation == "discretize_objective_integral":
                for src_path in op.all_sources:
                    obj = self._resolve_objective_source(src_path)
                    if obj:
                        expr_str = f"{obj.weight} * ({obj.integrand})" if obj.weight else obj.integrand
                        nodes = self._resolve_range(obj.range, p.final_node)
                        rng = [nodes[0], nodes[-1]] if nodes else None
                        terms.append(ObjectiveTerm(
                            id=obj.objective_id,
                            source_model=src_path,
                            source_operation=op.id,
                            type="integral_quadratic" if "^2" in obj.integrand else "integral_linear",
                            grid=obj.grid,
                            range=rng,
                            expr=expr_str,
                        ))

            if op.effects and op.effects.adds_objective_terms:
                for ao in op.effects.adds_objective_terms:
                    term_type = "scalar_quadratic" if "^2" in ao.expr else "linear"
                    terms.append(ObjectiveTerm(
                        id=f"{op.id}_penalty",
                        source_model="",
                        source_operation=op.id,
                        type=term_type,
                        grid="scalar",
                        range=None,
                        expr=ao.expr,
                    ))

        return SubObjective(terms=terms)

    # ══════════════════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════════════════

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
    def _resolve_range(range_spec, final_node: int) -> List[int]:
        """Resolve range spec → list of node indices."""
        if range_spec is None or range_spec == "all":
            return list(range(final_node + 1))
        if isinstance(range_spec, list) and len(range_spec) == 2:
            start = range_spec[0]
            end = range_spec[1]
            if isinstance(start, str) and start.upper() == "N":
                start = final_node
            if isinstance(end, str) and end.upper() == "N":
                end = final_node
            start = int(start)
            end = int(end)
            return list(range(start, end + 1))
        return list(range(final_node + 1))

    @staticmethod
    def _format_range(range_spec, final_node: int, grid: str = "node") -> Optional[List[int]]:
        """Format range as concrete [start, end] list for output. Never returns 'all'."""
        if grid == "scalar":
            return None
        if range_spec is None or range_spec == "all":
            return [0, final_node]
        if isinstance(range_spec, list) and len(range_spec) == 2:
            s, e = range_spec[0], range_spec[1]
            if isinstance(s, str) and s.upper() == "N":
                s = final_node
            if isinstance(e, str) and e.upper() == "N":
                e = final_node
            return [int(s), int(e)]
        return None

    @staticmethod
    def _split_box_expr(expr: str) -> tuple:
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
        """Build the time section for subproblem YAML."""
        p = self.problem
        grid_time = p.grid.time
        time_eff = p.transcription.time_effects

        # Determine if there's a perturbation variable
        pert_var = None
        for iv in time_eff.introduces_variables:
            if iv.role == "time_perturbation":
                pert_var = iv.name
                break

        is_optimizable = grid_time.interval_mode == "optimizable_uniform_interval"

        return SubTime(
            interval_mode=grid_time.interval_mode,
            interval_symbol=grid_time.interval_symbol,
            reference_interval_symbol="T_ref",
            perturbation_variable=pert_var,
            perturbed_interval_expr="T_ref + dT" if is_optimizable else None,
            total_time_expr=grid_time.total_time_expr,
            bounds=list(grid_time.bounds),
        )

    # ══════════════════════════════════════════════════════════════════════
    # Validation Section
    # ══════════════════════════════════════════════════════════════════════

    def _build_validation_section(self) -> SubValidation:
        """Build the validation metadata section."""
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
                "no_solver_specific_objective_rewrite_in_subproblem",
                "time_perturbation_variable_present_if_optimizable",
                "no_time_perturbation_variable_if_fixed_interval",
                "row_end_matches_row_start_plus_count_minus_one",
            ],
        )
