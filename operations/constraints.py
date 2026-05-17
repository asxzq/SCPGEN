"""
约束处理操作：

  - boundary_constraints: 端点等式约束 → A_b
  - box_constraints:      盒约束 → G_h
  - path_constraint_linearize: 路径约束线性化 + 松弛 → G_h, G_h_q, Q_c
"""

from .base import ProcessingOp, register_op


@register_op("boundary_constraints")
class BoundaryConstraintsOp(ProcessingOp):
    """
    处理边界等式约束（初始条件、终端条件）。

    Perturbation 模式: A_buf[row][col] = 1.0; b_buf[row] = value - x_ref[col]
    Direct 模式:      A_buf[row][col] = 1.0; b_buf[row] = value
    """

    op_type = "boundary_constraints"

    def analyze_sparsity(self, index_map, sparsity):
        params = self.params
        sources = params.get("sources", [])
        model = index_map.model

        total = 0
        for src_name in sources:
            for c in model.eq_constraints:
                if c.name == src_name:
                    total += len(c.bindings)

        row_start = index_map.allocate_A_rows("boundary", total)

        row = row_start
        for src_name in sources:
            for c in model.eq_constraints:
                if c.name == src_name:
                    for b in c.bindings:
                        node = index_map._resolve_node(b.node, model.N_NODES)
                        col = index_map.var_col(b.var, node)
                        sparsity.register_A_nz(row, col)
                        row += 1

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        params = self.params
        sources = params.get("sources", [])
        model = index_map.model
        is_perturbation = index_map.transcription.scp_params.is_perturbation

        lines = ["", "  /* ── Boundary Constraints ── */"]

        a_boundary_start = 0
        for label, start, end in index_map._A_blocks:
            if label == "boundary":
                a_boundary_start = start
                break

        row = a_boundary_start
        guard = model.name.upper()
        for src_name in sources:
            for c in model.eq_constraints:
                if c.name == src_name:
                    lines.append("  /* " + c.name + " */")
                    for b in c.bindings:
                        node = index_map._resolve_node(b.node, model.N_NODES)
                        col = index_map.var_col(b.var, node)
                        col_macro = f"{guard}_COL_{b.var.upper()}"
                        # Resolve value name: e.g. "r0"→INIT_R, "lambdaf"→FINAL_LAMBDA
                        val_name = b.value
                        if val_name.endswith("0") and len(val_name) > 1:
                            val_name = f"{guard}_INIT_{val_name[:-1].upper()}"
                        elif val_name.endswith("f") and len(val_name) > 1:
                            val_name = f"{guard}_FINAL_{val_name[:-1].upper()}"
                        if is_perturbation:
                            lines.append(
                                "  A_buf[" + str(row) + "][" + col_macro + "(" + str(node) + ")] = 1.0;"
                                + "  b_buf[" + str(row) + "] = " + val_name
                                + " - x_ref[" + col_macro + "(" + str(node) + ")];"
                                + "  /* " + b.var + "@" + str(node) + " (perturbation) */"
                            )
                        else:
                            lines.append(
                                "  A_buf[" + str(row) + "][" + col_macro + "(" + str(node) + ")] = 1.0;"
                                + "  b_buf[" + str(row) + "] = " + val_name
                                + ";  /* " + b.var + "@" + str(node) + " */"
                            )
                        row += 1

        lines.append("")
        return "\n".join(lines)


@register_op("box_constraints")
class BoxConstraintsOp(ProcessingOp):
    """
    处理盒约束: lower <= var@nodes <= upper。

    每个节点产生2个不等式（上下界），导出到 G_h。
    """

    op_type = "box_constraints"

    def analyze_sparsity(self, index_map, sparsity):
        params = self.params
        sources = params.get("sources", [])
        model = index_map.model

        total = 0
        for src_name in sources:
            for c in model.ineq_constraints:
                if c.name == src_name and c.ctype.value == "box":
                    for b in c.bindings:
                        nodes = self._resolve_node_range(
                            c.nodes if c.nodes else [0, "N"], model.FINAL_NODE
                        )
                        total += len(nodes) * 2  # upper + lower

        row_start = index_map.allocate_G_rows("box", total)

        row = row_start
        for src_name in sources:
            for c in model.ineq_constraints:
                if c.name == src_name and c.ctype.value == "box":
                    for b in c.bindings:
                        nodes = self._resolve_node_range(
                            c.nodes if c.nodes else [0, "N"], model.FINAL_NODE
                        )
                        for node in nodes:
                            col = index_map.var_col(b.var, node)
                            sparsity.register_G_nz(row, col)      # upper
                            sparsity.register_G_nz(row + 1, col)  # lower
                            row += 2

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        params = self.params
        sources = params.get("sources", [])
        model = index_map.model

        lines = ["", "  /* ── Box Constraints ── */"]

        # Find G block start for box constraints
        g_box_start = 0
        for label, start, end in index_map._G_blocks:
            if label == "box":
                g_box_start = start
                break

        row_offset = g_box_start
        for src_name in sources:
            for c in model.ineq_constraints:
                if c.name == src_name and c.ctype.value == "box":
                    lines.append("  /* " + c.name + " */")
                    for b in c.bindings:
                        nodes = self._resolve_node_range(
                            c.nodes if c.nodes else [0, "N"], model.FINAL_NODE
                        )
                        guard = model.name.upper()
                        col_macro = f"{guard}_COL_{b.var.upper()}"
                        # Resolve parameter names to p->xxx
                        upper_val = b.upper
                        lower_val = b.lower
                        for pm in model.parameters:
                            if pm.name == upper_val: upper_val = f"p->{upper_val}"
                            if pm.name == lower_val: lower_val = f"p->{lower_val}"
                        lines.append("  {")
                        lines.append("    int k;")
                        lines.append("    int row = " + str(row_offset) + ";")
                        lines.append("    for (k = " + str(nodes[0]) + "; k <= " + str(nodes[-1]) + "; k++) {")
                        lines.append("      int col = " + col_macro + "(k);")
                        lines.append("      G_buf[row][col] = 1.0;    h_buf[row] = " + upper_val + " - x_ref[col];")
                        lines.append("      G_buf[row+1][col] = -1.0;  h_buf[row+1] = -(" + lower_val + ") + x_ref[col];")
                        lines.append("      row += 2;")
                        lines.append("    }")
                        lines.append("  }")
                        row_offset += len(nodes) * 2

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _resolve_node_range(raw, FINAL_NODE: int):
        """Resolve [start, end] → list of node indices.
        FINAL_NODE is the max node index (N_INTERVALS).
        """
        if not raw or len(raw) < 2:
            return list(range(FINAL_NODE + 1))
        start = raw[0] if isinstance(raw[0], int) else (FINAL_NODE if str(raw[0]).upper() == "N" else 0)
        end = raw[1] if isinstance(raw[1], int) else (FINAL_NODE if str(raw[1]).upper() == "N" else FINAL_NODE)
        return list(range(start, end + 1))


@register_op("path_constraint_linearize")
class PathConstraintLinearizeOp(ProcessingOp):
    """
    将路径约束 g(x,u) <= g_max 在每个离散点处一阶 Taylor 展开:

        g(x_ref, u_ref) + ∇g·dx ≤ g_max

    可选松弛变量: g(x_ref) + ∇g·dx - s ≤ g_max,  s ≥ 0 (锥约束)
    """

    op_type = "path_constraint_linearize"

    def analyze_sparsity(self, index_map, sparsity):
        params = self.params
        sources = params.get("sources", [])
        relaxation = params.get("relaxation", {})
        slack_enabled = bool(relaxation.get("slack_prefix"))
        model = index_map.model

        # Count = num_path_constraints × N_NODES (one inequality per node)
        total = 0
        for src_name in sources:
            for c in model.ineq_constraints:
                if c.name == src_name:
                    nodes = self._resolve_nodes(c, model.FINAL_NODE)
                    total += len(nodes)

        row_start = index_map.allocate_G_rows("path", total)

        # ── Auto-allocate slack variables if relaxation is configured ──
        self._slack_col_base = {}  # src_name → starting column
        self._slack_cone_row = {}  # src_name → starting cone row (for s≥0)
        self._slack_nodes = {}     # src_name → node list

        if slack_enabled:
            for src_name in sources:
                for c in model.ineq_constraints:
                    if c.name == src_name:
                        nodes = self._resolve_nodes(c, model.FINAL_NODE)
                        slack_name = f"s_{src_name}"
                        col_base = index_map.num_vars
                        for node in nodes:
                            index_map.allocate_extra_var(slack_name, node_start=node, node_end=node)
                        self._slack_col_base[src_name] = col_base
                        self._slack_nodes[src_name] = nodes

                        # Register R+ cone (1-dim SOC) for each node's slack
                        cone_row_start = index_map.allocate_cone_rows(len(nodes))
                        self._slack_cone_row[src_name] = cone_row_start
                        for ki, node in enumerate(nodes):
                            index_map.register_cone_size(1, f"slack_{src_name}@node{node}")
                            try:
                                s_col = index_map.extra_var_col(slack_name, node=node)
                                sparsity.register_G_nz(cone_row_start + ki, s_col)
                            except KeyError:
                                pass
                        break

        # For each path constraint at each node, the gradient touches
        # all states and controls at that node, plus the slack column if present
        row = row_start
        for src_name in sources:
            for c in model.ineq_constraints:
                if c.name == src_name:
                    nodes = self._resolve_nodes(c, model.FINAL_NODE)
                    for node in nodes:
                        # Touch all state & control columns at this node
                        for s in model.states:
                            sparsity.register_G_nz(row, index_map.var_col(s.name, node))
                        for ctrl in model.controls:
                            sparsity.register_G_nz(row, index_map.var_col(ctrl.name, node))
                        # Touch slack variable column if allocated
                        if slack_enabled:
                            slack_name = f"s_{src_name}"
                            try:
                                s_col = index_map.extra_var_col(slack_name, node=node)
                                sparsity.register_G_nz(row, s_col)
                            except KeyError:
                                pass
                        row += 1

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        params = self.params
        sources = params.get("sources", [])
        model = index_map.model
        relaxation = params.get("relaxation", {})
        slack_enabled = bool(relaxation.get("slack_prefix"))

        # Import here to avoid circular
        from ..symengine import generate_path_constraint_gradient, sympy_to_c

        lines = ["", "  /* ── Path Constraint Linearization ── */"]

        # Find G block start for path constraints
        g_path_start = 0
        for label, start, end in index_map._G_blocks:
            if label == "path":
                g_path_start = start
                break

        # Build C name map for this context
        c_name_map = {}
        for s in model.states:
            c_name_map[f"{s.name}@0"] = f"x_ref[col + {model.states.index(s)}]"
        for ctrl in model.controls:
            c_name_map[f"{ctrl.name}@0"] = f"x_ref[col + N_STATES + {model.controls.index(ctrl)}]"
        for p in model.parameters:
            c_name_map[p.name] = f"p->{p.name}"

        row_offset = g_path_start
        for src_name in sources:
            for c in model.ineq_constraints:
                if c.name == src_name:
                    nodes = self._resolve_nodes(c, model.FINAL_NODE)

                    # Compute symbolic gradient at node 0 (representative)
                    grad = None
                    g_val_c = c.upper  # fallback
                    if sym_ctx is not None and c.expr:
                        try:
                            grad = generate_path_constraint_gradient(sym_ctx, c.expr, 0)
                            g_val_c = sympy_to_c(grad["g"], c_name_map)
                            g_val_c = g_val_c.replace("x_ref[col + ", "x_ref[k * VARS_PER_NODE + ")
                        except Exception as e:
                            lines.append("  /* WARNING: gradient failed for " + c.name + ": " + str(e) + " */")
                            grad = None

                    # Check if slack variable exists for this constraint (auto-allocated above)
                    slack_name = f"s_{src_name}"
                    has_slack = (src_name in getattr(self, '_slack_nodes', {}))
                    s_col_base = getattr(self, '_slack_col_base', {}).get(src_name, -1)

                    lines.append("  /* " + c.name + ": " + c.expr + " <= " + c.upper + " */")
                    lines.append("  {")
                    lines.append("    int k;")
                    lines.append("    int row = " + str(row_offset) + ";")
                    lines.append("    for (k = " + str(nodes[0]) + "; k <= " + str(nodes[-1]) + "; k++) {")
                    lines.append("      int col = k * VARS_PER_NODE;")

                    if grad is not None:
                        # Fill state gradient entries
                        for i, s in enumerate(model.states):
                            dg_c = sympy_to_c(grad["dg_dx"][i], c_name_map)
                            dg_c = dg_c.replace("x_ref[col + ", "x_ref[k * VARS_PER_NODE + ")
                            col_idx = index_map.var_col(s.name, 0)  # col offset at node 0
                            lines.append("      G_buf[row][k * VARS_PER_NODE + " + str(col_idx) + "] = " + dg_c + ";")
                        # Fill control gradient entries
                        for i, ctrl in enumerate(model.controls):
                            dg_c = sympy_to_c(grad["dg_du"][i], c_name_map)
                            dg_c = dg_c.replace("x_ref[col + ", "x_ref[k * VARS_PER_NODE + ")
                            col_idx = index_map.var_col(ctrl.name, 0)
                            lines.append("      G_buf[row][k * VARS_PER_NODE + " + str(col_idx) + "] = " + dg_c + ";")
                        # Resolve upper/lower bound: if it's a param name, prefix with p->
                        upper_val = c.upper
                        for pm in model.parameters:
                            if pm.name == upper_val:
                                upper_val = f"p->{upper_val}"
                                break
                        lower_val = c.lower
                        for pm in model.parameters:
                            if pm.name == lower_val:
                                lower_val = f"p->{lower_val}"
                                break
                        lines.append("      h_buf[row] = " + upper_val + " - (" + g_val_c + ");")

                        if has_slack and s_col_base >= 0:
                            lines.append("      G_buf[row][" + str(s_col_base) + " + (k - " + str(nodes[0]) + ")] = -1.0;  /* -s */")
                    else:
                        lines.append("      int j;")
                        lines.append("      for (j = 0; j < VARS_PER_NODE; j++) {")
                        lines.append("        G_buf[row][col + j] = 0.0;  /* TODO: gradient */")
                        lines.append("      }")
                        upper_val = c.upper
                        for pm in model.parameters:
                            if pm.name == upper_val:
                                upper_val = f"p->{upper_val}"
                                break
                        lines.append("      h_buf[row] = " + upper_val + ";  /* TODO: eval g(x_ref) */")
                        if has_slack and s_col_base >= 0:
                            lines.append("      G_buf[row][" + str(s_col_base) + " + (k - " + str(nodes[0]) + ")] = -1.0;  /* -s */")

                    lines.append("      row++;")
                    lines.append("    }")
                    lines.append("  }")
                    row_offset += len(nodes)

        # ── Slack non-negativity & penalty (auto-generated when relaxation configured) ──
        slack_col_base = getattr(self, '_slack_col_base', {})
        slack_cone_row = getattr(self, '_slack_cone_row', {})
        slack_nodes = getattr(self, '_slack_nodes', {})
        penalty_prefix = relaxation.get("penalty_weight_prefix", "omega_")

        for src_name in sources:
            if src_name in slack_col_base:
                col_base = slack_col_base[src_name]
                cone_row = slack_cone_row[src_name]
                nodes = slack_nodes[src_name]
                # Strip "_limit" suffix and other common suffixes from penalty param name
                penalty_name = src_name
                for suffix in ["_limit", "_bound", "_max", "_min"]:
                    if penalty_name.endswith(suffix):
                        penalty_name = penalty_name[:-len(suffix)]
                        break
                penalty_param = f"{penalty_prefix}{penalty_name}"
                # Check if the param exists; if not, use 0.0 (no penalty)
                param_exists = any(pm.name == penalty_param for pm in model.parameters)
                penalty_value = f"p->{penalty_param}" if param_exists else "0.0 /* no matching weight param */"
                lines.append(f"  /* Slack for '{src_name}': s >= 0 (R+ cone), penalty = {penalty_value} */")
                lines.append("  {")
                lines.append("    int k;")
                lines.append(f"    int s_col = {col_base};")
                lines.append(f"    int g_row = {cone_row};")
                lines.append(f"    for (k = {nodes[0]}; k <= {nodes[-1]}; k++) {{")
                lines.append("      G_buf[g_row][s_col] = -1.0;  /* -s ≤ 0 → s ≥ 0 */")
                lines.append("      h_buf[g_row] = 0.0;")
                lines.append(f"      c_buf[s_col] += {penalty_value};  /* penalty in objective */")
                lines.append("      s_col++;")
                lines.append("      g_row++;")
                lines.append("    }")
                lines.append("  }")
                lines.append("")

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _resolve_nodes(constraint, FINAL_NODE: int):
        raw = constraint.nodes if constraint.nodes else [0, "N"]
        if len(raw) >= 2:
            start = raw[0] if isinstance(raw[0], int) else (FINAL_NODE if str(raw[0]).upper() == "N" else 0)
            end = raw[1] if isinstance(raw[1], int) else (FINAL_NODE if str(raw[1]).upper() == "N" else FINAL_NODE)
            return list(range(start, end + 1))
        return list(range(FINAL_NODE + 1))


@register_op("auxiliary_linkage")
class AuxiliaryLinkageOp(ProcessingOp):
    """
    Auto-generate linkage equality constraints for auxiliary variables
    that have corresponding base variables with a "dot" suffix.

    Example: if model has auxiliary "alphadot" and control "alpha",
    generate for each interval k:
        alpha[k+1] - alpha[k] - dt * 0.5 * (alphadot[k] + alphadot[k+1]) = 0

    The linkage uses trapezoidal integration to relate the derivative
    auxiliary to its base variable.
    """

    op_type = "auxiliary_linkage"

    def analyze_sparsity(self, index_map, sparsity):
        model = index_map.model
        N_INTERVALS = model.N_INTERVALS
        n_states = len(model.states)

        # Auto-detect dot-pairs: auxiliary "xxxdot" ↔ base "xxx"
        dot_pairs = self._find_dot_pairs(model)

        total_rows = len(dot_pairs) * N_INTERVALS
        if total_rows == 0:
            return

        row_start = index_map.allocate_A_rows("aux_linkage", total_rows)

        row = row_start
        for base_name, dot_name in dot_pairs:
            for k in range(N_INTERVALS):
                # Touch columns: base@k, base@k+1, dot@k, dot@k+1
                cols = [
                    index_map.var_col(base_name, k),
                    index_map.var_col(base_name, k + 1),
                    index_map.var_col(dot_name, k),
                    index_map.var_col(dot_name, k + 1),
                ]
                for c in cols:
                    sparsity.register_A_nz(row, c)
                row += 1

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        model = index_map.model
        N_INTERVALS = model.N_INTERVALS
        dot_pairs = self._find_dot_pairs(model)

        if not dot_pairs:
            return "  /* No auxiliary linkage needed */\n"

        # Find A block start
        a_link_start = 0
        for label, start, end in index_map._A_blocks:
            if label == "aux_linkage":
                a_link_start = start
                break

        lines = ["", "  /* ── Auxiliary Linkage Constraints (dot variables) ── */"]
        lines.append("  /* alpha[k+1] - alpha[k] - dt*0.5*(alphadot[k] + alphadot[k+1]) = 0 */")

        row = a_link_start
        for base_name, dot_name in dot_pairs:
            lines.append(f"  /* Linkage: {dot_name} → {base_name} */")
            lines.append("  {")
            lines.append("    int k;")
            lines.append(f"    int r = {row};")
            lines.append("    for (k = 0; k < N_INTERVALS; k++) {")
            base_col_k = index_map.var_col(base_name, 0)
            base_col_k1 = index_map.var_col(base_name, 1)
            base_stride = base_col_k1 - base_col_k
            dot_col_k = index_map.var_col(dot_name, 0)
            dot_col_k1 = index_map.var_col(dot_name, 1)
            dot_stride = dot_col_k1 - dot_col_k
            lines.append(f"      int col_bk = {base_col_k} + k * {base_stride};")
            lines.append(f"      int col_bk1 = {base_col_k1} + k * {base_stride};")
            lines.append(f"      int col_dk = {dot_col_k} + k * {dot_stride};")
            lines.append(f"      int col_dk1 = {dot_col_k1} + k * {dot_stride};")
            lines.append(f"      double dt = dt_seq[k];")
            lines.append("")
            lines.append("      /* Coefficients: -dx_bk + dx_bk1 - dt*0.5*dx_dk - dt*0.5*dx_dk1 */")
            lines.append("      A_buf[r][col_bk] = -1.0;")
            lines.append("      A_buf[r][col_bk1] = 1.0;")
            lines.append("      A_buf[r][col_dk] = -0.5 * dt;")
            lines.append("      A_buf[r][col_dk1] = -0.5 * dt;")
            lines.append("")
            lines.append("      /* b = -(x_ref[col_bk1] - x_ref[col_bk]) + dt*0.5*(x_ref[col_dk] + x_ref[col_dk1]) */")
            lines.append("      b_buf[r] = -(x_ref[col_bk1] - x_ref[col_bk]) + 0.5 * dt * (x_ref[col_dk] + x_ref[col_dk1]);")
            lines.append("      r++;")
            lines.append("    }")
            lines.append("  }")
            row += N_INTERVALS

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _find_dot_pairs(model):
        """Find auxiliary variables ending with 'dot' and their base var."""
        pairs = []
        for aux in model.auxiliaries:
            name = aux.name
            if name.endswith("dot"):
                base = name[:-3]  # remove "dot" suffix
                # Check if base exists as state or control
                for v in model.all_variables:
                    if v.name == base and v.role.value in ("state", "control"):
                        pairs.append((base, name))
                        break
        return pairs
