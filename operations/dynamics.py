"""
动力学离散化 + 线性化操作。

核心公式 (perturbation 模式, 中点 Jacobian):

  在区间 [k, k+1] 的中点处求 Jacobian:
    x_mid = (X*(k) + X*(k+1)) / 2,  u_mid = (U*(k) + U*(k+1)) / 2
    A* = ∂f/∂x |_{(x_mid, u_mid)}
    B* = ∂f/∂u |_{(x_mid, u_mid)}
    f* = f(x_mid, u_mid)

  Trapezoidal 离散 + 一阶 Taylor 展开:
    [T/2·A* + I,  T/2·B*,  T/2·A* - I,  T/2·B*] · [δX(k), δU(k), δX(k+1), δU(k+1)]^T
        = [X*(k+1) - X*(k)] - f*·T

  δT (总时间变量) 列: 对每个区间, 填 f*/N_INTERVALS

  direct 模式下, 约束形式相同但 b 不同:
    b = T/2·A*·(X*(k)+X*(k+1)) + T/2·B*·(U*(k)+U*(k+1)) - f*·T

Exports: A_b (defect equality)
"""

from .base import ProcessingOp, register_op


@register_op("dynamics_linearize")
class DynamicsLinearizeOp(ProcessingOp):
    """
    将连续时间动力学 xdot = f(x,u) 转化为离散缺陷等式约束。

    使用中点 Jacobian 进行线性化 (用户指定公式)。
    支持 perturbation (δx) 和 direct (x) 两种 variable_mode。
    支持可选的 δT (总时间) 变量。
    """

    op_type = "dynamics_linearize"

    def analyze_sparsity(self, index_map, sparsity):
        params = self.params
        discretization = params.get("discretization", "trapezoidal")

        model = index_map.model
        n_states = len(model.states)
        n_ctrl = len(model.controls)
        N_INTERVALS = model.N_INTERVALS

        # Validate control grid: midpoint linearization requires control at nodes
        for ctrl in model.controls:
            for k in range(N_INTERVALS + 1):
                try:
                    index_map.var_col(ctrl.name, k)
                except KeyError:
                    raise ValueError(
                        f"midpoint_linearized_defect requires control '{ctrl.name}' "
                        f"at node {k}. Controls must be on node grid (0..N_INTERVALS), "
                        f"not interval grid. Check variable_layout in YAML."
                    )

        # Each interval k=0..N_INTERVALS-1 gives n_states defect equations
        row_start = index_map.allocate_A_rows("dynamics_defects", n_states * N_INTERVALS)

        # Check if δT variable is allocated (time optimization)
        self._has_delta_T = False
        self._delta_T_col = -1
        try:
            self._delta_T_col = index_map.extra_var_col("delta_T")
            self._has_delta_T = True
        except KeyError:
            pass

        for k in range(N_INTERVALS):
            row_base = row_start + k * n_states

            cols_state_k = [index_map.var_col(s.name, k) for s in model.states]
            cols_ctrl_k = [index_map.var_col(c.name, k) for c in model.controls]
            cols_state_k1 = [index_map.var_col(s.name, k + 1) for s in model.states]
            cols_ctrl_k1 = [index_map.var_col(c.name, k + 1) for c in model.controls]

            rows = list(range(row_base, row_base + n_states))
            sparsity.register_A_nz_block(rows, cols_state_k)
            sparsity.register_A_nz_block(rows, cols_ctrl_k)
            sparsity.register_A_nz_block(rows, cols_state_k1)
            sparsity.register_A_nz_block(rows, cols_ctrl_k1)

            # δT column: register nonzero for each defect row
            if self._has_delta_T:
                for i in range(n_states):
                    sparsity.register_A_nz(row_base + i, self._delta_T_col)

    def generate_fill_code(self, index_map, sparsity, sym_ctx=None) -> str:
        model = index_map.model
        n_states = len(model.states)
        n_ctrl = len(model.controls)
        N_INTERVALS = model.N_INTERVALS
        params = self.params
        discretization = params.get("discretization", "trapezoidal")

        # Determine variable mode
        var_mode = index_map.transcription.scp_params.variable_mode
        is_perturbation = var_mode.value == "perturbation"

        # Find dynamics A block start
        a_dyn_start = 0
        for label, start, end in index_map._A_blocks:
            if label == "dynamics_defects":
                a_dyn_start = start
                break

        # δT column
        has_dT = getattr(self, '_has_delta_T', False)
        dT_col = getattr(self, '_delta_T_col', -1)

        # Use prefixed macro name
        guard = model.name.upper()
        lines = []
        mode_label = "PERTURBATION (δx)" if is_perturbation else "DIRECT (x)"
        lines.append(f"  /* ── Dynamics Defect Constraints ({discretization}) [{mode_label}] ── */")
        lines.append(f"  /* Midpoint Jacobian: A*,B*,f* evaluated at (x_mid, u_mid) between k and k+1 */")
        lines.append(f"  /* A_row = {guard}_ROW_DYNAMICS_DEFECTS_START + k*{n_states} + i */")
        lines.append("  {")
        lines.append(f"    int i, j, k, row_base, col_k, col_k1;")
        lines.append(f"    double x_mid[{n_states}];")
        lines.append(f"    double u_mid[{n_ctrl}];")
        lines.append(f"    double A_loc[{n_states}][{n_states}];")
        lines.append(f"    double B_loc[{n_states}][{n_ctrl}];")
        lines.append(f"    double f_loc[{n_states}];")
        lines.append(f"    double dt, half_dt;")
        lines.append("")
        lines.append(f"    for (k = 0; k < N_INTERVALS; k++) {{")
        lines.append("      dt = dt_seq[k];")
        lines.append("      half_dt = 0.5 * dt;")
        lines.append(f"      row_base = {guard}_ROW_DYNAMICS_DEFECTS_START + k * {n_states};")
        lines.append(f"      col_k = {guard}_COL_STATE(k, 0);  /* k * VARS_PER_NODE */")
        lines.append(f"      col_k1 = {guard}_COL_STATE(k+1, 0);  /* (k+1) * VARS_PER_NODE */")
        lines.append("")

        # ── Midpoint computation and _norm Jacobian call ──

        lines.append("      /* ── Compute midpoint (NORMALIZED ref → stays normalized for _norm call) ── */")
        lines.append(f"      for (i = 0; i < {n_states}; i++)")
        lines.append("        x_mid[i] = 0.5 * (x_ref[col_k + i] + x_ref[col_k1 + i]);")
        if n_ctrl > 0:
            lines.append(f"      for (i = 0; i < {n_ctrl}; i++)")
            lines.append(f"        u_mid[i] = 0.5 * (x_ref[{guard}_COL_CTRL(k, i)] + x_ref[{guard}_COL_CTRL(k+1, i)]);")
        lines.append("")
        lines.append("      /* ── Evaluate Jacobian at midpoint (NORMALIZED space) ── */")
        lines.append(f"      {{problem_name}}_compute_dynamics_jacobian_norm(x_mid, u_mid, /* t */ 0.0,")
        lines.append("                                &A_loc[0][0], &B_loc[0][0], &f_loc[0], p);")
        lines.append("")

        if discretization == "trapezoidal":
            lines.append("      /* ── Trapezoidal defect linearization ── */")
            lines.append("      /* A-blocks: [T/2*A* + I, T/2*B*, T/2*A* - I, T/2*B*] */")
            lines.append("      /*            δX(k),       δU(k),   δX(k+1),       δU(k+1)   */")
            lines.append(f"      for (i = 0; i < {n_states}; i++) {{")
            lines.append("        int ri = row_base + i;")
            lines.append("")
            # Block 1: δX(k) → T/2 * A* + I
            lines.append("        /* δX(k) block: half_dt * A* + I */")
            lines.append(f"        for (j = 0; j < {n_states}; j++)")
            lines.append("          A_buf[ri][col_k + j] = (i == j ? 1.0 : 0.0) + half_dt * A_loc[i][j];")
            lines.append("")
            # Block 2: δU(k) → T/2 * B*
            if n_ctrl > 0:
                lines.append("        /* δU(k) block: half_dt * B* */")
                lines.append(f"        for (j = 0; j < {n_ctrl}; j++)")
                lines.append(f"          A_buf[ri][{guard}_COL_CTRL(k, j)] = half_dt * B_loc[i][j];")
            lines.append("")
            # Block 3: δX(k+1) → T/2 * A* - I
            lines.append("        /* δX(k+1) block: half_dt * A* - I */")
            lines.append(f"        for (j = 0; j < {n_states}; j++)")
            lines.append("          A_buf[ri][col_k1 + j] = (i == j ? -1.0 : 0.0) + half_dt * A_loc[i][j];")
            lines.append("")
            # Block 4: δU(k+1) → T/2 * B*
            if n_ctrl > 0:
                lines.append("        /* δU(k+1) block: half_dt * B* */")
                lines.append(f"        for (j = 0; j < {n_ctrl}; j++)")
                lines.append(f"          A_buf[ri][{guard}_COL_CTRL(k+1, j)] = half_dt * B_loc[i][j];")
            lines.append("")

            # δT column: f*/N_INTERVALS (since T* is total time, dt = T*/N_INTERVALS)
            if has_dT:
                lines.append(f"        /* δT column: f*[i] / N_INTERVALS */")
                lines.append(f"        A_buf[ri][{dT_col}] = f_loc[i] / N_INTERVALS;")
                lines.append("")

            # RHS (b vector)
            if is_perturbation:
                lines.append("        /* b = X*(k+1)[i] - X*(k)[i] - f*[i] * dt */")
                lines.append("        b_buf[ri] = x_ref[col_k1 + i] - x_ref[col_k + i] - f_loc[i] * dt;")
            else:
                lines.append("        /* b = T/2*A*·(X*(k)+X*(k+1)) + T/2*B*·(U*(k)+U*(k+1)) - f* * T */")
                lines.append("        {")
                lines.append("          double b_sum = 0.0;")
                lines.append(f"          for (j = 0; j < {n_states}; j++)")
                lines.append("            b_sum += half_dt * A_loc[i][j] * (x_ref[col_k + j] + x_ref[col_k1 + j]);")
                if n_ctrl > 0:
                    lines.append(f"          for (j = 0; j < {n_ctrl}; j++)")
                    lines.append(f"            b_sum += half_dt * B_loc[i][j] * (x_ref[{guard}_COL_CTRL(k, j)] + x_ref[{guard}_COL_CTRL(k+1, j)]);")
                lines.append("          b_buf[ri] = b_sum - f_loc[i] * dt;")
                lines.append("        }")
            lines.append("      }")

        lines.append("    }")
        lines.append("  }")
        lines.append("")

        # Replace template variable in generated code
        result = "\n".join(lines)
        result = result.replace("{problem_name}", model.name)
        return result
