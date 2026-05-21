"""
Module 3 Runner — 不等式约束离散化-线性化符号模板生成器入口

用法:
    from scpgen.module3_inequalities.runner import run_module3, run_module3_from_yaml
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Callable

from .parser import parse_inequality_constraints
from .symengine import InequalitySymEngine
from .formula_generator import InequalityFormulaGenerator
from .output_builder import OutputBuilder
from .yaml_writer import YamlWriter


def run_module3(
    input_dict: Dict[str, Any],
    output_path: str = "inequality_module3_output.yaml",
    simplify_level: str = "none",
    logger: Optional[Callable[[str], None]] = None,
    output_debug_expressions: bool = False,
    output_c_code_expressions: bool = False,
    output_latex_expressions: bool = False,
    report_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Module 3 主流程。

    Args:
        input_dict: 已解析的问题 dict
        output_path: 输出 YAML 路径
        simplify_level: "none" | "basic" | "full"
        logger: 日志回调
        output_debug_expressions: 是否输出展开表达式
        output_c_code_expressions: 是否输出 C 代码
        output_latex_expressions: 是否输出 LaTeX
        report_path: 性能统计报告路径

    Returns:
        生成的 output dict
    """
    log = logger or (lambda _: None)

    # Step 1: 解析输入
    log("Module 3: parsing input...")
    module_input = parse_inequality_constraints(input_dict)
    log(f"  constraints={module_input.constraint_count}, "
        f"scalar_total={module_input.total_scalar_count}")
    log(f"  variable_mode={module_input.variable_mode}")
    slack_count = sum(1 for c in module_input.constraints if c.slack_enabled)
    log(f"  slack_enabled_count={slack_count}")

    writer = YamlWriter()

    # 空约束集合 → 直接生成空输出（仍需生成公式情形）
    if module_input.constraint_count == 0:
        log("Module 3: empty constraints, generating empty output...")
        formula_gen = InequalityFormulaGenerator(module_input)
        output_dict = OutputBuilder.build_empty(module_input, formula_gen)
        log(f"Module 3: writing YAML to {output_path}...")
        writer.write(output_dict, output_path)
        if report_path:
            log(f"Module 3: writing report to {report_path}...")
            report = OutputBuilder.build_report(module_input, None)
            writer.write(report, report_path)
        log("Module 3: done (empty) in 0.00s")
        return output_dict

    # Step 2: 构建符号引擎
    log("Module 3: building symbolic engine...")
    sym_engine = InequalitySymEngine(module_input, simplify_level=simplify_level, logger=log)
    sym_engine.build_all()

    # Step 3: 生成公式
    log("Module 3: generating formula templates...")
    formula_gen = InequalityFormulaGenerator(module_input)

    # Step 4: 组装输出
    log("Module 3: building output...")
    builder = OutputBuilder(
        output_debug_expressions=output_debug_expressions,
        output_c_code_expressions=output_c_code_expressions,
        output_latex_expressions=output_latex_expressions,
    )
    output_dict = builder.build(module_input, sym_engine, formula_gen)

    # Step 5: 写入 YAML
    log(f"Module 3: writing YAML to {output_path}...")
    writer = YamlWriter()
    writer.write(output_dict, output_path)

    # Step 6: 写入性能报告
    if report_path:
        log(f"Module 3: writing report to {report_path}...")
        report = OutputBuilder.build_report(module_input, sym_engine)
        writer.write(report, report_path)

    log(f"Module 3: done in {sym_engine.stats.get('total', 0):.2f}s")
    return output_dict


def run_module3_from_yaml(
    input_yaml_path: str,
    output_path: Optional[str] = None,
    simplify_level: str = "none",
    write_report: bool = False,
    output_debug_expressions: bool = False,
    output_c_code_expressions: bool = False,
    output_latex_expressions: bool = False,
) -> Dict[str, Any]:
    """
    从 YAML 文件运行 Module 3。

    Args:
        input_yaml_path: 输入 YAML 文件路径
        output_path: 输出路径（默认推导）
        simplify_level: 简化级别
        write_report: 是否写入性能报告
    """
    import os
    from scpgen.common.yaml_io import read_yaml
    from scpgen.common.paths import runs_dir, ensure_dir

    raw = read_yaml(input_yaml_path)
    raw["input_yaml"] = os.path.basename(input_yaml_path)

    if output_path is None:
        problem_name = raw.get("problem_name", "unnamed")
        output_dir = ensure_dir(runs_dir("module3", problem_name))
        output_path = os.path.join(output_dir, "inequality_module3_output.yaml")

    report_path = None
    if write_report:
        report_dir = os.path.dirname(output_path)
        report_path = os.path.join(report_dir, "module3_report.yaml")

    return run_module3(
        raw, output_path,
        simplify_level=simplify_level,
        logger=print,
        output_debug_expressions=output_debug_expressions,
        output_c_code_expressions=output_c_code_expressions,
        output_latex_expressions=output_latex_expressions,
        report_path=report_path,
    )
