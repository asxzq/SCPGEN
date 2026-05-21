"""Module6 输入一致性校验器。

在校验失败时返回清晰的错误列表，不静默生成错误的 C 代码。
"""

from __future__ import annotations

from typing import List
from scpgen.module6_codegen.models import Module6IR, VariableBlock


def validate_module6_ir(ir: Module6IR) -> List[str]:
    """校验 Module6IR 的一致性。

    Args:
        ir: 从 Module5 输出解析得到的 Module6IR

    Returns:
        错误消息列表。空列表表示校验通过。
    """
    errors: List[str] = []

    # ── 1. 维度一致性 ──
    d = ir.dims
    if d.n <= 0:
        errors.append(f"n (ECOS 变量维度) 必须 > 0，当前为 {d.n}")
    if d.p < 0:
        errors.append(f"p (等式约束行数) 必须 >= 0，当前为 {d.p}")
    if d.m < 0:
        errors.append(f"m (锥约束总行数) 必须 >= 0，当前为 {d.m}")
    if d.l < 0:
        errors.append(f"l (非负锥维度) 必须 >= 0，当前为 {d.l}")

    # sum(q) + l == m
    q_sum = sum(d.q) if d.q else 0
    if q_sum + d.l != d.m:
        errors.append(
            f"锥维度不一致: sum(q)={q_sum} + l={d.l} = {q_sum + d.l}, "
            f"但 m={d.m}"
        )

    # A_shape == [p, n]
    if ir.equalities.A_rows != d.p or ir.equalities.A_cols != d.n:
        errors.append(
            f"A 矩阵形状不一致: A_shape=[{ir.equalities.A_rows}, {ir.equalities.A_cols}], "
            f"期望 [{d.p}, {d.n}]"
        )

    # G_shape == [m, n]
    if ir.inequalities.G_rows != d.m or ir.inequalities.G_cols != d.n:
        errors.append(
            f"G 矩阵形状不一致: G_shape=[{ir.inequalities.G_rows}, {ir.inequalities.G_cols}], "
            f"期望 [{d.m}, {d.n}]"
        )

    # ── 2. dim_z 与 dim_y 分离 ──
    if ir.dim_y <= 0:
        errors.append(f"dim_y 必须 > 0，当前为 {ir.dim_y}")
    if ir.dim_z <= 0:
        errors.append(f"dim_z 必须 > 0，当前为 {ir.dim_z}")
    if ir.dim_z > ir.dim_y:
        errors.append(f"dim_z ({ir.dim_z}) 不应大于 dim_y ({ir.dim_y})")
    if ir.dim_y != d.n:
        errors.append(
            f"dim_y ({ir.dim_y}) 应等于 ECOS n ({d.n})"
        )

    # ── 3. 变量块一致性 ──
    _validate_variable_blocks(ir, errors)

    # ── 4. 行范围校验 ──
    _validate_row_ranges(ir, errors)

    # ── 5. objective_vector_plan 校验 ──
    _validate_objective_plan(ir, errors)

    # ── 6. SOC 校验 ──
    _validate_soc(ir, errors)

    return errors


def _validate_variable_blocks(ir: Module6IR, errors: List[str]) -> None:
    """校验变量块一致性。"""
    blocks = ir.variable_blocks
    if not blocks:
        errors.append("变量块列表为空")
        return

    # 检查每个块
    for i, vb in enumerate(blocks):
        prefix = f"变量块[{i}] '{vb.name}'"

        if vb.dimension_concrete <= 0:
            errors.append(f"{prefix}: dimension_concrete={vb.dimension_concrete} 必须 > 0")

        if vb.column_start_concrete < 0:
            errors.append(f"{prefix}: column_start_concrete={vb.column_start_concrete} 必须 >= 0")

        if vb.column_end_concrete >= ir.dims.n:
            errors.append(
                f"{prefix}: column_end_concrete={vb.column_end_concrete} "
                f"超出范围 n={ir.dims.n}"
            )

        expected_dim = vb.column_end_concrete - vb.column_start_concrete + 1
        if expected_dim != vb.dimension_concrete:
            errors.append(
                f"{prefix}: 列范围 [{vb.column_start_concrete}, {vb.column_end_concrete}] "
                f"跨度 {expected_dim} 与 dimension_concrete={vb.dimension_concrete} 不一致"
            )

    # 检查块之间不重叠
    sorted_blocks = sorted(blocks, key=lambda b: b.column_start_concrete)
    for i in range(len(sorted_blocks) - 1):
        a = sorted_blocks[i]
        b = sorted_blocks[i + 1]
        if a.column_end_concrete >= b.column_start_concrete:
            errors.append(
                f"变量块重叠: '{a.name}' [{a.column_start_concrete}, {a.column_end_concrete}] "
                f"与 '{b.name}' [{b.column_start_concrete}, {b.column_end_concrete}] 重叠"
            )

    # 检查覆盖范围: 第一个块的 start 应为 0
    if sorted_blocks[0].column_start_concrete != 0:
        errors.append(
            f"第一个变量块 '{sorted_blocks[0].name}' 的 column_start 应为 0, "
            f"当前为 {sorted_blocks[0].column_start_concrete}"
        )


def _validate_row_ranges(ir: Module6IR, errors: List[str]) -> None:
    """校验行范围一致性。"""
    # 等式行
    for rb in ir.equalities.row_blocks:
        rr = rb.row_range_exclusive
        if rr and len(rr) >= 2:
            if rr[0] < 0 or rr[1] > ir.dims.p:
                errors.append(
                    f"等式行块 '{rb.name}' 行范围 [{rr[0]}, {rr[1]}) "
                    f"超出 A 行范围 [0, {ir.dims.p})"
                )
            if rr[1] <= rr[0]:
                errors.append(
                    f"等式行块 '{rb.name}' 行范围 [{rr[0]}, {rr[1]}) 无效"
                )

    # 不等式行（线性部分）
    for rb in ir.inequalities.row_blocks:
        rr = rb.row_range_exclusive
        if rr and len(rr) >= 2:
            if rr[0] < 0 or rr[1] > ir.dims.m:
                errors.append(
                    f"不等式行块 '{rb.name}' 行范围 [{rr[0]}, {rr[1]}) "
                    f"超出 G 行范围 [0, {ir.dims.m})"
                )
            if rr[1] <= rr[0]:
                errors.append(
                    f"不等式行块 '{rb.name}' 行范围 [{rr[0]}, {rr[1]}) 无效"
                )


def _validate_objective_plan(ir: Module6IR, errors: List[str]) -> None:
    """校验 objective_vector_plan。"""
    for i, entry in enumerate(ir.objective_plan.entries):
        prefix = f"objective_entry[{i}] '{entry.source_cost_term}'"

        if entry.variable_column_start < 0 or entry.variable_column_start >= ir.dims.n:
            errors.append(
                f"{prefix}: variable_column_start={entry.variable_column_start} "
                f"超出范围 [0, {ir.dims.n})"
            )
        if entry.variable_column_end < 0 or entry.variable_column_end >= ir.dims.n:
            errors.append(
                f"{prefix}: variable_column_end={entry.variable_column_end} "
                f"超出范围 [0, {ir.dims.n})"
            )
        if entry.variable_column_end < entry.variable_column_start:
            errors.append(
                f"{prefix}: column_end ({entry.variable_column_end}) < "
                f"column_start ({entry.variable_column_start})"
            )

        if entry.is_epigraph and entry.variable_dimension_concrete != 1:
            errors.append(
                f"{prefix}: epigraph entry 的 dimension 应为 1, "
                f"当前为 {entry.variable_dimension_concrete}"
            )


def _validate_soc(ir: Module6IR, errors: List[str]) -> None:
    """校验 SOC 块。"""
    for i, sb in enumerate(ir.cones.soc_blocks):
        prefix = f"SOC[{i}] '{sb.name}'"
        rr = sb.row_range_exclusive

        if rr and len(rr) >= 2:
            length = rr[1] - rr[0]
            if length != sb.dim:
                errors.append(
                    f"{prefix}: row_range_exclusive 长度 {length} "
                    f"与 dim={sb.dim} 不一致"
                )
            if rr[0] < 0 or rr[1] > ir.dims.m:
                errors.append(
                    f"{prefix}: 行范围 [{rr[0]}, {rr[1]}) "
                    f"超出 G 行范围 [0, {ir.dims.m})"
                )

            # SOC row 不应与 linear cone rows 冲突
            l_rr = ir.cones.l_row_range_exclusive
            if l_rr and len(l_rr) >= 2:
                if rr[0] < l_rr[1] and rr[1] > l_rr[0]:
                    errors.append(
                        f"{prefix}: SOC 行范围 [{rr[0]}, {rr[1]}) "
                        f"与 linear cone 行范围 [{l_rr[0]}, {l_rr[1]}) 重叠"
                    )

    # q dims 与 SOC blocks 数量一致
    if len(ir.dims.q) != len(ir.cones.soc_blocks):
        errors.append(
            f"SOC 维度列表 q ({ir.dims.q}) 与 soc_blocks 数量 "
            f"({len(ir.cones.soc_blocks)}) 不一致"
        )
    for i, (q_dim, sb) in enumerate(zip(ir.dims.q, ir.cones.soc_blocks)):
        if q_dim != sb.dim:
            errors.append(
                f"q[{i}]={q_dim} 与 soc_block[{i}].dim={sb.dim} 不一致"
            )
