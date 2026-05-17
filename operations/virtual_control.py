"""
虚拟控制 & 松弛变量操作。

  - virtual_control: 为动力学缺陷引入虚拟控制 ζ，惩罚项进目标
  - slack_variables: 为路径约束引入松弛变量 s，惩罚项进目标

松弛变量使用 auxiliary 变量机制:
  model 层声明 auxiliary 变量（作为松弛变量的占位），
  transcription 层通过 slack_variables operation 声明映射和惩罚权重。
"""

from .base import ProcessingOp, register_op


@register_op("virtual_control")
class VirtualControlOp(ProcessingOp):
    """
    虚拟控制变量 ζ 用于松弛动力学缺陷等式约束。

    ζ 是 n_states 维向量，在每个区间 k=0..N-2 各有一个。
    A 矩阵中: 对每个区间的第 i 个缺陷等式，添加 -ζ_i 项。
    锥约束: ||ζ_k|| ≤ t_k (SOC), t_k 为辅助锥顶变量。
    目标惩罚: ω · t_k (等价于 ω·||ζ|| 的 SOC 形式)。

    YAML 格式:
      - type: "virtual_control"
        name: "zeta_dyn"            # auxiliary 变量名前缀
        penalty_weight: "omega_vc"  # 惩罚权重参数名
        export:
          - { target: "A_b" }
          - { target: "G_h_q" }
          - { target: "c" }
    """

    op_type = "virtual_control"

    def analyze_sparsity(self, index_map, sparsity):
        params = self.params
        vc_name = params.get("name", "zeta_dyn")
        model = index_map.model
        n_states = len(model.states)
        N_INTERVALS = model.N_INTERVALS

        # Allocate ζ columns: n_states per interval
        self._zeta_col_base = index_map.num_vars
        for k in range(N_INTERVALS):
            for i in range(n_states):
                index_map.allocate_extra_var(f"{vc_name}_{i}", node_start=k, node_end=k)

        # Allocate t_k columns (cone apex): 1 per interval
        self._t_col_base = index_map.num_vars
        for k in range(N_INTERVALS):
            index_map.allocate_extra_var(f"t_{vc_name}", node_start=k, node_end=k)

        # Store cone row start for G matrix
        self._cone_row_start = index_map.num_G_linear_rows + index_map._cone_row_next

        # Register cone sizes: each interval gets one SOC cone of dim (n_states + 1)
        self._cone_index_base = index_map.num_cones
        for k in range(N_INTERVALS):
            index_map.register_cone_size(n_states + 1, f"{vc_name}_interval_{k}")

        # Register nonzeros in A matrix: -ζ_i at defect row i for interval k
        for label, start, end in index_map._A_blocks:
            if label == "dynamics_defects":
                for k in range(N_INTERVALS):
                    row_base = start + k * n_states
                    for i in range(n_states):
                        try:
                            zeta_col = index_map.extra_var_col(f"{vc_name}_{i}", node=k)
                            sparsity.register_A_nz(row_base + i, zeta_col)
                        except KeyError:
                            pass
                break

        # Register nonzeros in G: SOC cone rows for ||ζ|| ≤ t
        for k in range(N_INTERVALS):
            try:
                t_col = index_map.extra_var_col(f"t_{vc_name}", node=k)
            except KeyError:
                continue
            cone_base = self._cone_row_start + k * (n_states + 1)
            # Row 0: G[cone_base][t_col] = -1 (t is cone apex)
            sparsity.register_G_nz(cone_base, t_col)
            # Row 1+i: G[cone_base+1+i][zeta_col] = -1
            for i in range(n_states):
                try:
                    zeta_col = index_map.extra_var_col(f"{vc_name}_{i}", node=k)
                    sparsity.register_G_nz(cone_base + 1 + i, zeta_col)
                except KeyError:
                    pass

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        params = self.params
        vc_name = params.get("name", "zeta_dyn")
        weight = params.get("penalty_weight", "omega_vc")
        model = index_map.model
        n_states = len(model.states)
        N_INTERVALS = model.N_INTERVALS

        zeta_base = getattr(self, '_zeta_col_base', 0)
        t_base = getattr(self, '_t_col_base', 0)
        cone_row = getattr(self, '_cone_row_start', 0)

        lines = ["", f"  /* ── Virtual Control: {vc_name} (penalty={weight}) ── */"]
        lines.append(f"  /* Each interval k: ζ_k ∈ R^{n_states}, cone ||ζ_k|| ≤ t_k */")
        lines.append(f"  /* zeta_col_base={zeta_base}, t_col_base={t_base}, cone_row_start={cone_row} */")
        lines.append("")

        # Find dynamics A block start
        a_dyn_start = 0
        for label, start, end in index_map._A_blocks:
            if label == "dynamics_defects":
                a_dyn_start = start
                break

        lines.append(f"  /* ── A matrix: -ζ_i at defect row i ── */")
        lines.append("  for (k = 0; k < N_INTERVALS; k++) {")
        lines.append(f"    int row_base = {a_dyn_start} + k * {n_states};")
        lines.append("    int i;")
        lines.append("    for (i = 0; i < N_STATES; i++) {")
        lines.append(f"      int zeta_col = {zeta_base} + k * {n_states} + i;")
        lines.append("      A_buf[row_base + i][zeta_col] = -1.0;  /* -ζ_i */")
        lines.append("    }")
        lines.append("  }")
        lines.append("")

        # SOC cone: ||ζ|| ≤ t
        lines.append(f"  /* ── SOC cone: ||ζ_k|| ≤ t_k ── */")
        lines.append("  {")
        lines.append(f"    int g_row = {cone_row};")
        lines.append("    for (k = 0; k < N_INTERVALS; k++) {")
        lines.append(f"      int t_col = {t_base} + k;")
        lines.append("      /* Cone apex row: -t_k (first element of SOC cone) */")
        lines.append("      G_buf[g_row][t_col] = -1.0;")
        lines.append("      h_buf[g_row] = 0.0;")
        lines.append("      /* Cone rows 1..n_states: -ζ_i */")
        lines.append("      int i;")
        lines.append("      for (i = 0; i < N_STATES; i++) {")
        lines.append(f"        int zeta_col = {zeta_base} + k * {n_states} + i;")
        lines.append("        G_buf[g_row + 1 + i][zeta_col] = -1.0;")
        lines.append("      }")
        lines.append(f"      g_row += {n_states + 1};")
        lines.append("    }")
        lines.append("  }")
        lines.append("")

        # Objective penalty: ω * t_k
        lines.append(f"  /* ── Objective penalty: {weight} * t_k ── */")
        lines.append("  for (k = 0; k < N_INTERVALS; k++) {")
        lines.append(f"    int t_col = {t_base} + k;")
        lines.append(f"    c_buf[t_col] += p->{weight};")
        lines.append("  }")
        lines.append("")

        return "\n".join(lines)


@register_op("slack_variables")
class SlackVariablesOp(ProcessingOp):
    """
    松弛变量 s ≥ 0 用于软化不等式约束。

    每个被松弛的约束在每个节点对应一个标量 s ≥ 0。
    s 在 G_h 中用于松弛不等式（由 path_constraint_linearize 操作写入 -s 项）。
    s ≥ 0 本身是锥约束（R+ 锥, 即 1 维 SOC）。
    惩罚项 ω·s 添加到目标 c 中。

    YAML 格式:
      - type: "slack_variables"
        sources: ["overload_limit", "heatflux_limit"]   # 引用的路径约束名
        penalty_weight_prefix: "weight_"                 # 惩罚参数名前缀
        export:
          - { target: "G_h_q" }
          - { target: "c" }
    """

    op_type = "slack_variables"

    def analyze_sparsity(self, index_map, sparsity):
        params = self.params
        sources = params.get("sources", [])
        penalty_prefix = params.get("penalty_weight_prefix", "omega_")
        model = index_map.model
        FINAL_NODE = model.FINAL_NODE
        N_NODES = model.N_NODES

        # Store per-constraint slack info for fill code generation
        self._slack_info = {}  # src_name -> {col_base, cone_row_start, nodes}

        for src_name in sources:
            # Find the constraint to get its node range
            nodes = list(range(N_NODES))  # default: all nodes
            for c in model.ineq_constraints:
                if c.name == src_name:
                    raw_nodes = c.nodes if c.nodes else [0, "N"]
                    if len(raw_nodes) >= 2:
                        start = raw_nodes[0] if isinstance(raw_nodes[0], int) else 0
                        end = raw_nodes[1] if isinstance(raw_nodes[1], int) else (FINAL_NODE if str(raw_nodes[1]).upper() == "N" else int(raw_nodes[1]))
                        nodes = list(range(start, end + 1))
                    break

            slack_name = f"s_{src_name}"
            col_base = index_map.num_vars
            for node in nodes:
                index_map.allocate_extra_var(slack_name, node_start=node, node_end=node)

            # Store cone row start before registering
            cone_row_start = index_map._cone_row_next

            # Register R+ cone (1-dim SOC) for each node's slack variable
            for node in nodes:
                index_map.register_cone_size(1, f"slack_{src_name}@node{node}")

            # Register nonzeros in G: s ≥ 0 → -s ≤ 0 → G=-1, h=0
            for ki, node in enumerate(nodes):
                try:
                    s_col = index_map.extra_var_col(slack_name, node=node)
                    sparsity.register_G_nz(cone_row_start + ki, s_col)
                except KeyError:
                    pass

            self._slack_info[src_name] = {
                'col_base': col_base,
                'cone_row_start': cone_row_start,
                'nodes': nodes,
            }

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        params = self.params
        sources = params.get("sources", [])
        penalty_prefix = params.get("penalty_weight_prefix", "omega_")
        model = index_map.model

        slack_info = getattr(self, '_slack_info', {})

        lines = ["", "  /* ── Slack Variables ── */"]
        lines.append("")

        for src_name in sources:
            info = slack_info.get(src_name, {})
            col_base = info.get('col_base', 0)
            cone_row_start = info.get('cone_row_start', 0)
            nodes = info.get('nodes', list(range(model.N_NODES)))
            penalty_param = f"{penalty_prefix}{src_name}"

            lines.append(f"  /* Slack for '{src_name}': s >= 0, penalty=p->{penalty_param} */")
            lines.append(f"  /*   col_base={col_base}, cone_row_start={cone_row_start} */")
            lines.append("  {")
            lines.append("    int k;")
            lines.append(f"    int s_col = {col_base};")
            lines.append(f"    int g_row = {cone_row_start};")
            lines.append(f"    for (k = {nodes[0]}; k <= {nodes[-1]}; k++) {{")
            lines.append("      /* R+ cone: -s <= 0 → s >= 0 */")
            lines.append("      G_buf[g_row][s_col] = -1.0;")
            lines.append("      h_buf[g_row] = 0.0;")
            lines.append(f"      c_buf[s_col] += p->{penalty_param};  /* penalty in objective */")
            lines.append("      s_col++;")
            lines.append("      g_row++;")
            lines.append("    }")
            lines.append("  }")
            lines.append("")

        return "\n".join(lines)
