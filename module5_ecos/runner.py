"""Module 5 Runner — ECOS Canonicalizer 主入口

用法:
    from scpgen.module5_ecos.runner import run_module5
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Callable
import os

from .input_loader import load_module4_ir
from .variable_extender import extend_variables
from .objective_canonicalizer import canonicalize_objective
from .equality_canonicalizer import canonicalize_equalities
from .inequality_canonicalizer import canonicalize_inequalities
from .cone_canonicalizer import build_cones
from .matrix_plan_builder import build_assembly_plan
from .output_builder import build
from .yaml_writer import YamlWriter


def run_module5(
    input_path: Optional[str] = None,
    output_path: Optional[str] = None,
    write_report: bool = False,
    logger: Optional[Callable[[str], None]] = None,
    report_path: Optional[str] = None,
    _m4_dict: Optional[Dict[str, Any]] = None,  # 测试用：直接传入 dict
) -> Dict[str, Any]:
    """
    Module 5 主流程：将 Module 4 subproblem IR 转换为 ECOS canonical IR。

    Args:
        input_path: Module 4 输出 YAML 路径
        output_path: 输出 YAML 路径
        write_report: 是否输出 debug report
        logger: 日志回调
        report_path: report 输出路径
        _m4_dict: 测试用：直接传入 Module 4 IR dict（跳过文件读取）

    Returns:
        生成的 output dict
    """
    log = logger or (lambda _: None)

    # Step 1: 加载 Module 4 IR
    if _m4_dict is not None:
        log("Module 5: using in-memory Module 4 IR...")
        m4_ir = _m4_dict
        source_path = "(memory)"
    elif input_path:
        log(f"Module 5: loading Module 4 IR from {input_path}...")
        m4_ir = load_module4_ir(input_path)
        source_path = input_path
    else:
        raise ValueError("Either input_path or _m4_dict must be provided")

    problem = m4_ir.get("problem", {})
    log(f"  problem={problem.get('problem_name', '?')}, "
        f"variable_mode={problem.get('variable_mode', '?')}")

    # Step 1.5: 输入一致性校验
    log("Module 5: validating input consistency...")
    _validate_m4_input_consistency(m4_ir)

    # Step 2: 扩展变量 z → y
    log("Module 5: extending variables (z → y)...")
    var_ext = extend_variables(m4_ir)
    log(f"  dim_z={var_ext['dim_z']}, dim_y={var_ext['dim_y']}, "
        f"epigraph_vars={len(var_ext['epigraph_blocks'])}")

    # Step 3: 规范化目标
    log("Module 5: canonicalizing objective...")
    obj_info = canonicalize_objective(m4_ir, var_ext)
    log(f"  linear_terms={len(obj_info['linear_terms'])}, "
        f"quadratic_terms={len(obj_info['quadratic_terms_canonicalized'])}")

    # Step 4: 规范化等式
    log("Module 5: canonicalizing equalities...")
    eq_info = canonicalize_equalities(m4_ir, var_ext)
    log(f"  A_shape={eq_info['A_shape_concrete']}")

    # Step 5: 规范化不等式
    log("Module 5: canonicalizing inequalities...")
    ineq_info = canonicalize_inequalities(m4_ir, var_ext)
    log(f"  total_linear_rows={ineq_info['total_linear_rows']}")

    # Step 6: 构建锥体结构
    log("Module 5: building cone structure...")
    cone_info = build_cones(m4_ir, var_ext, obj_info, ineq_info)
    dim_l = cone_info["linear"]["dim_l"]
    q_dims = [qb["dim"] for qb in cone_info["second_order"]["q"]]
    log(f"  dim_l={dim_l}, q={q_dims}")

    # Step 7: 构建矩阵装配计划
    log("Module 5: building matrix assembly plan...")
    assembly_plan = build_assembly_plan(m4_ir, var_ext, eq_info, ineq_info, cone_info)

    # Step 8: 构建输出
    log("Module 5: building output dict...")
    output_dict = build(m4_ir, var_ext, obj_info, eq_info, ineq_info, cone_info,
                        assembly_plan, source_path)

    # Step 9: 写入 YAML（仅当 output_path 指定时）
    if output_path:
        log(f"Module 5: writing YAML to {output_path}...")
        writer = YamlWriter()
        writer.write(output_dict, output_path)

    # Step 10: 可选 report（仅当 output_path 指定时）
    if write_report and output_path:
        if not report_path:
            report_path = os.path.join(
                os.path.dirname(os.path.abspath(output_path)),
                "module5_report.yaml"
            )
        log(f"Module 5: writing report to {report_path}...")
        report_data = {
            "debug_summary": output_dict.get("debug_summary", {}),
            "ecos_dims": output_dict.get("ecos_problem", {}).get("dimensions", {}),
        }
        report_writer = YamlWriter()
        report_writer.write(report_data, report_path)

    log("Module 5: done.")
    return output_dict


def _validate_m4_input_consistency(m4_ir: Dict[str, Any]) -> None:
    """校验 Module 4 IR 的关键字段一致性。

    检测以下不一致：
    1. decision_variable_registry.total_dimension_concrete == sum(block.dimension_concrete)
    2. 变量列索引连续、不重叠
    3. 每个 block 的 column_end - column_start + 1 == dimension_concrete
    4. equality_constraint_registry total_rows 与 block 行数累计一致
    5. inequality_constraint_registry total_rows 与 block 行数累计一致

    Raises:
        ValueError: 任何一致性校验失败
    """
    # ── 变量注册表校验 ──
    dvr = m4_ir.get("decision_variable_registry", {})
    blocks = dvr.get("blocks", [])
    if not blocks:
        return  # 无变量，跳过校验

    declared_total = dvr.get("total_dimension_concrete", None)

    # 1. total_dimension_concrete 一致性
    computed_total = sum(b.get("dimension_concrete", 0) for b in blocks)
    if declared_total is not None and declared_total != computed_total:
        raise ValueError(
            f"decision_variable_registry.total_dimension_concrete={declared_total} "
            f"但 sum(block.dimension_concrete)={computed_total}"
        )

    # 2 & 3. 列索引连续、不重叠、长度一致
    prev_end = -1
    for i, b in enumerate(blocks):
        start = b.get("column_start_concrete")
        end = b.get("column_end_concrete")
        dim = b.get("dimension_concrete", 0)
        name = b.get("name", f"block[{i}]")

        if start is None or end is None:
            raise ValueError(
                f"变量块 '{name}' 缺少 column_start_concrete 或 column_end_concrete"
            )

        # 3. 列范围长度 == dimension
        expected_len = end - start + 1
        if expected_len != dim:
            raise ValueError(
                f"变量块 '{name}': column_end({end}) - column_start({start}) + 1 = "
                f"{expected_len}，但 dimension_concrete={dim}"
            )

        # 2. 列索引不重叠、连续
        if start != prev_end + 1:
            raise ValueError(
                f"变量块 '{name}' column_start={start}，但上一个块结束于 {prev_end}，"
                f"期望从 {prev_end + 1} 开始（列索引不连续或重叠）"
            )
        prev_end = end

    # 校验最后一个块的 end+1 == total_dimension（若声明）
    if declared_total is not None and prev_end + 1 != declared_total:
        raise ValueError(
            f"最后一个变量块结束于 {prev_end}，但 "
            f"decision_variable_registry.total_dimension_concrete={declared_total}，"
            f"期望 {prev_end + 1} == {declared_total}"
        )

    # ── 等式注册表校验 ──
    _validate_row_registry(
        m4_ir, "equality_constraint_registry", "等式的"
    )

    # ── 不等式注册表校验 ──
    _validate_row_registry(
        m4_ir, "inequality_constraint_registry", "不等式的"
    )


def _validate_row_registry(
    m4_ir: Dict[str, Any],
    registry_key: str,
    label: str,
) -> None:
    """校验等式/不等式注册表的行数一致性。"""
    reg = m4_ir.get(registry_key, {})
    blocks = reg.get("blocks", [])
    if not blocks:
        return

    declared_total = reg.get("total_rows_concrete", None)
    computed_total = sum(b.get("rows_concrete", 0) for b in blocks)

    if declared_total is not None and declared_total != computed_total:
        raise ValueError(
            f"{registry_key}.total_rows_concrete={declared_total} "
            f"但 sum(block.rows_concrete)={computed_total}"
        )

    # 行范围连续性校验
    prev_end = -1
    for i, b in enumerate(blocks):
        start = b.get("row_start_concrete")
        end = b.get("row_end_concrete")
        rows = b.get("rows_concrete", 0)
        name = b.get("name", f"block[{i}]")

        if start is None or end is None:
            raise ValueError(
                f"{label}块 '{name}' 缺少 row_start_concrete 或 row_end_concrete"
            )

        expected_len = end - start + 1
        if expected_len != rows:
            raise ValueError(
                f"{label}块 '{name}': row_end({end}) - row_start({start}) + 1 = "
                f"{expected_len}，但 rows_concrete={rows}"
            )

        if start != prev_end + 1:
            raise ValueError(
                f"{label}块 '{name}' row_start={start}，但上一个块结束于 {prev_end}，"
                f"期望从 {prev_end + 1} 开始（行索引不连续或重叠）"
            )
        prev_end = end

    if declared_total is not None and prev_end + 1 != declared_total:
        raise ValueError(
            f"{label}最后一个块结束于 {prev_end}，但 "
            f"{registry_key}.total_rows_concrete={declared_total}，"
            f"期望 {prev_end + 1} == {declared_total}"
        )
