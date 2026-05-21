"""
模块1 Runner — 动力学离散化-线性化符号模板生成器入口

用法:
    from scpgen.module1_dynamics.runner import run_module1, run_module1_from_yaml
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Callable

from .models import ProblemDef
from .symengine import SymEngine
from .formula_generator import FormulaGenerator, VirtualControlGenerator
from .output_builder import OutputBuilder
from .yaml_writer import YamlWriter


def run_module1(
    input_dict: Dict[str, Any],
    output_path: str = "dynamics_module1_output.yaml",
    simplify_level: str = "none",
    logger: Optional[Callable[[str], None]] = None,
    output_debug_expressions: bool = False,
    output_c_code_expressions: bool = False,
    output_latex_expressions: bool = False,
    report_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    模块1主流程。

    Args:
        input_dict: 已解析的问题 dict
        output_path: 输出 YAML 路径
        simplify_level: "none" | "basic" | "full"
        logger: 日志回调
        output_debug_expressions: 是否输出展开表达式（默认否）
        output_c_code_expressions: 是否输出 C 代码（默认否）
        output_latex_expressions: 是否输出 LaTeX（默认否）
        report_path: 性能统计报告路径（默认不输出）

    Returns:
        生成的 output dict
    """
    log = logger or (lambda _: None)

    # Step 1: 解析输入
    log("Module 1: parsing input...")
    problem_def = ProblemDef.from_dict(input_dict, simplify_level=simplify_level)
    errors = problem_def.validate()
    if errors:
        raise ValueError("输入校验失败:\n  " + "\n  ".join(errors))

    log(f"  states={problem_def.nx}, controls={problem_def.nu}, params={problem_def.np}")
    log(f"  aux total={len(problem_def.auxiliaries)}, "
        f"used_by_dynamics={len(problem_def.dynamics_aux_closure)}, "
        f"ignored={len(problem_def.ignored_auxiliaries)}")
    if problem_def.ignored_auxiliaries:
        log(f"  ignored aux: {problem_def.ignored_auxiliaries}")

    # Step 2: 构建符号引擎
    log("Module 1: building symbolic engine...")
    sym_engine = SymEngine(problem_def, simplify_level=simplify_level, logger=log)
    sym_engine.build_all()

    # Step 3: 生成公式和虚拟控制模板
    log("Module 1: generating formula templates...")
    formula_gen = FormulaGenerator(problem_def.config)
    vc_gen = VirtualControlGenerator(problem_def.config)

    # Step 4: 组装输出
    log("Module 1: building output...")
    builder = OutputBuilder(
        output_debug_expressions=output_debug_expressions,
        output_c_code_expressions=output_c_code_expressions,
        output_latex_expressions=output_latex_expressions,
    )
    output_dict = builder.build(problem_def, sym_engine, formula_gen, vc_gen)

    # Step 5: 写入 YAML
    log(f"Module 1: writing YAML to {output_path}...")
    writer = YamlWriter()
    writer.write(output_dict, output_path)

    # Step 6: 写入性能报告（单独文件）
    if report_path:
        log(f"Module 1: writing report to {report_path}...")
        report = OutputBuilder.build_debug_report(sym_engine)
        writer.write(report, report_path)

    log(f"Module 1: done in {sym_engine.stats.get('total', 0):.2f}s")
    return output_dict


def run_module1_from_yaml(
    input_yaml_path: str,
    output_path: Optional[str] = None,
    simplify_level: str = "none",
    logger: Optional[Callable[[str], None]] = None,
    output_debug_expressions: bool = False,
    output_c_code_expressions: bool = False,
    output_latex_expressions: bool = False,
    write_report: bool = False,
    report_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从 YAML 文件运行模块1。

    Args:
        input_yaml_path: 输入 YAML 文件路径
        output_path: 输出路径（默认 runs/module1/<problem_name>/dynamics_module1_output.yaml）
        simplify_level: 简化级别
        logger: 日志回调
        output_debug_expressions: 是否输出展开表达式
        output_c_code_expressions: 是否输出 C 代码
        output_latex_expressions: 是否输出 LaTeX
        write_report: 是否写入性能统计报告（默认否）
        report_path: 自定义报告路径（仅在 write_report=True 时生效）
    """
    from scpgen.common.yaml_io import read_yaml
    from scpgen.common.paths import ensure_dir, runs_dir
    import os

    log = logger or print
    raw = read_yaml(input_yaml_path)

    if "input_yaml" not in raw:
        raw["input_yaml"] = os.path.basename(input_yaml_path)

    if output_path is None:
        problem_name = raw.get("problem_name", "unnamed")
        output_dir = ensure_dir(runs_dir("module1", problem_name))
        output_path = os.path.join(output_dir, "dynamics_module1_output.yaml")

    # report 路径：仅在 write_report 时确定
    actual_report_path = None
    if write_report:
        actual_report_path = report_path or os.path.join(
            os.path.dirname(output_path), "module1_report.yaml"
        )

    return run_module1(
        raw, output_path,
        simplify_level=simplify_level,
        logger=log,
        output_debug_expressions=output_debug_expressions,
        output_c_code_expressions=output_c_code_expressions,
        output_latex_expressions=output_latex_expressions,
        report_path=actual_report_path,
    )
