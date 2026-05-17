"""
二阶锥约束 & 信赖域操作。

  - trust_region:  ||dx_k|| <= rho  变换为 SOC 约束
  - virtual_control: 虚拟控制变量的锥约束  ||zeta|| <= t
"""

from .base import ProcessingOp, register_op


@register_op("trust_region")
class TrustRegionOp(ProcessingOp):
    """
    信赖域约束: ||x_k - x_k^ref||_2 ≤ rho

    转换为二阶锥: (rho, dx_k) ∈ Q^{n+1}
    即: rho ≥ ||dx_k||
    导出到 G_h_q（锥约束部分）
    """

    op_type = "trust_region"

    def analyze_sparsity(self, index_map, sparsity):
        params = self.params
        scope = params.get("scope", ["state"])
        model = index_map.model
        N_NODES = model.N_NODES

        # Count cols per cone
        cone_dim = 0
        if "state" in scope:
            cone_dim += len(model.states)
        if "control" in scope:
            cone_dim += len(model.controls)
        cone_size = cone_dim + 1  # apex row + variable rows

        # Store starting cone index for fill code generation
        self._cone_index_base = index_map.num_cones
        self._cone_size = cone_size
        # First cone row = linear rows + current cone offset (before any cone alloc)
        self._cone_row_start = index_map.num_G_linear_rows + index_map._cone_row_next

        # Each node gets one SOC constraint
        for k in range(N_NODES):
            # Register cone dimension
            index_map.register_cone_size(cone_size, f"trust_region_node{k}")

            cols = []
            if "state" in scope:
                for s in model.states:
                    cols.append(index_map.var_col(s.name, k))
            if "control" in scope:
                for c in model.controls:
                    cols.append(index_map.var_col(c.name, k))
            # Allocate cone rows
            cone_rows = index_map.allocate_cone_rows(cone_size)
            for col in cols:
                sparsity.register_G_nz(cone_rows + 1, col)  # rows 1..cone_dim-1 for variable cols

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        params = self.params
        radius = params.get("radius", {}).get("param", "eps")
        scope = params.get("scope", ["state"])
        model = index_map.model
        N_NODES = model.N_NODES

        # Compute cone dimension
        cone_dim = 0
        if "state" in scope:
            cone_dim += len(model.states)
        if "control" in scope:
            cone_dim += len(model.controls)
        cone_size = cone_dim + 1

        # Store starting cone index for fill code generation
        self._cone_index_base = index_map.num_cones
        self._cone_size = cone_size

        lines = ["", "  /* ── Trust Region (SOC) radius=" + radius + " ── */"]
        lines.append("  /* SOC cone: rho >= ||dx_k||_2, cone dim = " + str(cone_size) + " */")
        lines.append("  {")
        lines.append("    int k, j;")
        lines.append("    int g_row = " + str(self._cone_row_start) + ";")
        lines.append("    for (k = 0; k < N_NODES; k++) {")
        lines.append("      /* Apex row: h = rho (trust region radius) */")
        lines.append("      h_buf[g_row] = " + radius + ";")
        lines.append("      /* Apex row: h = rho (trust region radius) */")
        lines.append("      h_buf[cone_base] = " + radius + ";")
        lines.append("      /* Variable rows: G[g_row+1+j][col] = -1 (for -dx_j <= 0) */")
        if "state" in scope:
            lines.append("      for (j = 0; j < N_STATES; j++) {")
            lines.append("        int col = k * VARS_PER_NODE + j;")
            lines.append("        G_buf[g_row + 1 + j][col] = -1.0;")
            lines.append("      }")
        if "control" in scope:
            offset = len(model.states) if "state" in scope else 0
            lines.append("      for (j = 0; j < N_CONTROLS; j++) {")
            lines.append("        int col = k * VARS_PER_NODE + N_STATES + j;")
            lines.append("        G_buf[g_row + 1 + " + str(offset) + " + j][col] = -1.0;")
            lines.append("      }")
        lines.append("      g_row += " + str(cone_size) + ";")
        lines.append("    }")
        lines.append("  }")
        lines.append("")
        return "\n".join(lines)


@register_op("objective")
class ObjectiveOp(ProcessingOp):
    """
    目标函数操作:
      - 解析原始目标表达式，对 alias 表达式展开后在终端节点线性化
      - 将梯度填入 c 向量
      - 处理增广惩罚项
    """

    op_type = "objective"

    def analyze_sparsity(self, index_map, sparsity):
        pass

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        params = self.params
        model = index_map.model

        lines = ["", "  /* ── Objective Function ── */"]
        if model.objective:
            obj_expr = model.objective.expr
            sense = model.objective.sense
            lines.append(f"  /* Original: {sense.value} {obj_expr} */")

            import re
            from ..symengine import expand_aliases, parse_expr, sympy_to_c, compute_jacobian

            # Parse: extract "var[N]" patterns from objective expression
            # e.g. "-overload[N]" → target = "overload", sign = -1
            matches = re.findall(r'(-?\s*\w+)\[N\]', obj_expr)
            
            if matches:
                for match in matches:
                    target = match.strip().lstrip('-').strip()
                    sign = -1.0 if match.strip().startswith('-') else 1.0
                    if sense.value == "maximize":
                        sign = -sign  # maximize → minimize negative
                    
                    # Try as direct variable first
                    try:
                        col = index_map.var_col(target, model.FINAL_NODE)
                        lines.append(f"  c_buf[{col}] += {sign};  /* {sense.value} {target}[N] */")
                        continue
                    except KeyError:
                        pass
                    
                    # Try as alias expression — expand and compute gradient
                    if sym_ctx is not None and target in [e.name for e in model.expressions]:
                        try:
                            alias_def = next(e for e in model.expressions if e.name == target)
                            expanded = expand_aliases(alias_def.expr, model)
                            g_expr = parse_expr(expanded, sym_ctx, node=model.FINAL_NODE, expand=False)
                            
                            # Compute gradient w.r.t all state & control variables at FINAL_NODE
                            state_syms = [sym_ctx.get_node_symbol(s.name, model.FINAL_NODE) for s in model.states]
                            ctrl_syms = [sym_ctx.get_node_symbol(c.name, model.FINAL_NODE) for c in model.controls]
                            all_wrt = state_syms + ctrl_syms
                            
                            grad = compute_jacobian(g_expr, all_wrt)
                            
                            # Build C name map for gradient conversion
                            c_name_map = {}
                            for s in model.states:
                                c_name_map[f"{s.name}@{model.FINAL_NODE}"] = f"x_ref[{index_map.var_col(s.name, model.FINAL_NODE)}]"
                            for c in model.controls:
                                c_name_map[f"{c.name}@{model.FINAL_NODE}"] = f"x_ref[{index_map.var_col(c.name, model.FINAL_NODE)}]"
                            for p in model.parameters:
                                c_name_map[p.name] = f"p->{p.name}"
                            
                            lines.append(f"  /* Gradient of '{target}' at FINAL_NODE: */")
                            for j in range(grad.cols):
                                grad_c = sympy_to_c(grad[0, j], c_name_map)
                                col = index_map.var_col(
                                    model.states[j].name if j < len(model.states) else model.controls[j - len(model.states)].name,
                                    model.FINAL_NODE
                                )
                                lines.append(f"  c_buf[{col}] += {sign} * ({grad_c});")
                        except Exception as e:
                            lines.append(f"  /* ERROR: failed to linearize '{target}': {e} */")
                    else:
                        lines.append(f"  /* ERROR: '{target}' is neither a variable nor an alias — cannot linearize */")
            else:
                lines.append("  /* WARNING: objective expression could not be parsed */")

        augmented = params.get("augmented_terms", [])
        if augmented:
            lines.append("  /* Augmented penalty terms (placeholder — handled by slack/virtual_control ops): */")
            for term in augmented:
                lines.append("  /*   " + term.get("expr", "?") + " */")

        lines.append("")
        return "\n".join(lines)


@register_op("soc_constraints")
class SOCConstraintsOp(ProcessingOp):
    """
    范数约束 → 二阶锥转换。
    """

    op_type = "soc_constraints"

    def analyze_sparsity(self, index_map, sparsity):
        pass

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        lines = ["", "  /* ── SOC Constraints (norm → cone) ── */"]
        lines.append("  /* TODO: implement SOC constraint fill from YAML sources */")
        lines.append("")
        return "\n".join(lines)


@register_op("quadratic_penalty_to_soc")
class QuadraticPenaltyToSOCOp(ProcessingOp):
    """
    二次型惩罚 → SOC 锥转换（ECOS 没有二次目标）。

    对每个惩罚项 omega * ||x_i||²：
      → 添加变量 t_i（锥顶）
      → 添加 SOC 锥： ||sqrt(omega) * x_i|| ≤ t_i
      → 目标中 min t_i

    YAML 格式:
      - type: "quadratic_penalty_to_soc"
        terms:
          - { name: "t_ctrl", weight: "omega_u1", vars: ["u1"], nodes: [0,"N"] }
    """

    op_type = "quadratic_penalty_to_soc"

    def analyze_sparsity(self, index_map, sparsity):
        params = self.params
        terms = params.get("terms", [])
        model = index_map.model
        FINAL_NODE = model.FINAL_NODE

        for term in terms:
            var_names = term.get("vars", [])
            raw_nodes = term.get("nodes", [0, "N"])
            start = raw_nodes[0] if isinstance(raw_nodes[0], int) else 0
            end = raw_nodes[1] if isinstance(raw_nodes[1], int) else (FINAL_NODE if str(raw_nodes[1]).upper() == "N" else int(raw_nodes[1]))
            node_count = end - start + 1

            # Each node: 1 cone (t) + len(var_names) rows (scaled vars)
            rows_per_cone = 1 + len(var_names)
            total_rows = node_count * rows_per_cone
            cone_row_start = index_map.allocate_cone_rows(total_rows)

            # Register cone sizes
            for k in range(start, end + 1):
                index_map.register_cone_size(rows_per_cone, f"quad_pen_{term.get('name','?')}_node{k}")

            # Register nonzeros: each cone row touches its var columns
            for k in range(start, end + 1):
                cone_base = cone_row_start + (k - start) * rows_per_cone
                for vi, vname in enumerate(var_names):
                    col = index_map.var_col(vname, k)
                    sparsity.register_G_nz(cone_base + 1 + vi, col)

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        params = self.params
        terms = params.get("terms", [])
        model = index_map.model
        FINAL_NODE = model.FINAL_NODE

        lines = ["", "  /* ── Quadratic Penalty → SOC Cone ── */"]
        lines.append("  /* ECOS has no QP: omega*||x||^2 → ||sqrt(omega)*x|| <= t, min t */")
        lines.append("")

        # Compute cone base offset (before trust region cones)
        cone_start = 0
        lines.append("  int qp_cone = " + str(cone_start) + ";")

        for term in terms:
            var_names = term.get("vars", [])
            weight = term.get("weight", "1.0")
            sqrt_w = "sqrt(" + weight + ")"
            raw_nodes = term.get("nodes", [0, "N"])
            start = raw_nodes[0] if isinstance(raw_nodes[0], int) else 0
            end = raw_nodes[1] if isinstance(raw_nodes[1], int) else (FINAL_NODE if str(raw_nodes[1]).upper() == "N" else int(raw_nodes[1]))

            lines.append("  /* Quadratic penalty: " + weight + " * ||" + ",".join(var_names) + "||^2 */")
            lines.append("  for (k = " + str(start) + "; k <= " + str(end) + "; k++) {")
            lines.append("    int cbase = qp_cone + k * " + str(1 + len(var_names)) + ";")
            lines.append("    h_buf[cbase] = 0.0;  /* t >= 0 */")
            for vi, vname in enumerate(var_names):
                col = index_map.var_col(vname, start)
                stride = index_map.var_col(vname, start + 1) - col if start < N else 1
                lines.append("    G_buf[cbase + " + str(1 + vi) + "][k * " + str(stride) + " + " + str(col - start * stride) + "] = -" + sqrt_w + ";")
            lines.append("    c_buf[cbase] = 1.0;  /* min t */")
            lines.append("  }")

        lines.append("")
        return "\n".join(lines)
