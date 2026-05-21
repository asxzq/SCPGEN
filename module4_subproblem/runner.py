"""
Module 4 Runner — Subproblem IR Assembler 主入口

用法:
    from scpgen.module4_subproblem.runner import run_module4
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Callable

from .input_loader import load_bundle, load_from_paths
from .assembler import assemble
from .output_builder import build
from .yaml_writer import YamlWriter


def run_module4(
    bundle_path: Optional[str] = None,
    m1_path: Optional[str] = None,
    m2_path: Optional[str] = None,
    m2_enabled: bool = True,
    m3_path: Optional[str] = None,
    m3_enabled: bool = True,
    output_path: Optional[str] = None,
    logger: Optional[Callable[[str], None]] = None,
    write_report: bool = False,
    report_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Module 4 主流程。

    可通过 bundle YAML 或直接指定三个模块输出路径来调用。

    Args:
        bundle_path: Bundle YAML 路径（与 m1_path 互斥）
        m1_path: Module 1 输出 YAML 路径
        m2_path: Module 2 输出 YAML 路径
        m2_enabled: Module 2 是否启用
        m3_path: Module 3 输出 YAML 路径
        m3_enabled: Module 3 是否启用
        output_path: 输出 YAML 路径
        logger: 日志回调
        write_report: 是否输出 debug report
        report_path: report 输出路径

    Returns:
        生成的 output dict
    """
    log = logger or (lambda _: None)

    # Step 1: 加载输入
    log("Module 4: loading inputs...")
    if bundle_path:
        module_input = load_bundle(bundle_path)
    elif m1_path:
        module_input = load_from_paths(
            m1_path=m1_path,
            m2_path=m2_path or "",
            m2_enabled=m2_enabled,
            m3_path=m3_path or "",
            m3_enabled=m3_enabled,
            output_path=output_path or "subproblem_ir_module4_output.yaml",
        )
    else:
        raise ValueError("Either bundle_path or m1_path must be provided")

    if output_path:
        module_input.output_path = output_path

    log(f"  problem={module_input.problem_name}, "
        f"m2_enabled={module_input.m2_enabled}, m3_enabled={module_input.m3_enabled}")

    # Step 2: 装配 IR
    log("Module 4: assembling subproblem IR...")
    ir = assemble(module_input)
    log(f"  variables={len(ir.variable_blocks)}, "
        f"equalities={len(ir.equality_blocks)}, "
        f"inequalities={len(ir.inequality_blocks)}")

    # Step 3: 构建输出
    log("Module 4: building output...")
    output_dict = build(ir)

    # Step 4: 写入 YAML
    log(f"Module 4: writing YAML to {module_input.output_path}...")
    writer = YamlWriter()
    writer.write(output_dict, module_input.output_path)

    # Step 5: 可选 report
    if write_report:
        if not report_path:
            import os
            report_path = os.path.join(
                os.path.dirname(os.path.abspath(module_input.output_path)),
                "module4_report.yaml"
            )
        log(f"Module 4: writing report to {report_path}...")
        report_data = {
            "debug_summary": ir.debug_summary,
            "source_modules": ir.source_modules,
            "problem_name": ir.problem_name,
            "total_variable_dimension": ir.debug_summary.get("total_variable_dimension", 0),
            "total_equality_rows": ir.debug_summary.get("total_equality_rows", 0),
            "total_inequality_rows": ir.debug_summary.get("total_inequality_rows", 0),
        }
        writer.write(report_data, report_path)

    log(f"Module 4: done")
    return output_dict
