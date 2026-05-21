"""Module6 运行器 — 读取 Module5 输出，生成 C 代码。"""

from __future__ import annotations

import os
from typing import Dict, Any, Optional

from scpgen.common.yaml_io import read_yaml, write_yaml
from scpgen.module6_codegen.models import parse_module5_output, Module6IR
from scpgen.module6_codegen.input_loader import load_module5_output, load_bundle
from scpgen.module6_codegen.codegen import generate_all
from scpgen.module6_codegen.writer import write_generated_files
from scpgen.module6_codegen.validator import validate_module6_ir


def run_module6(
    input_path: str,
    output_code_dir: str,
    write_report: bool = False,
) -> Dict[str, Any]:
    """Module6 主运行器: 读取 Module5 输出，生成 C 代码。

    Args:
        input_path: Module5 ECOS canonical IR YAML 文件路径
        output_code_dir: C 代码输出目录
        write_report: 是否输出调试报告

    Returns:
        生成结果摘要 dict
    """
    # 1. 加载 Module5 输出
    ir = load_module5_output(input_path)

    # 1.5 校验输入一致性
    errors = validate_module6_ir(ir)
    if errors:
        raise ValueError(
            f"Module6IR 校验失败 ({len(errors)} 个错误):\n" +
            "\n".join(f"  - {e}" for e in errors)
        )

    # 2. 生成 C 代码
    files = generate_all(ir)

    # 3. 写入磁盘
    write_generated_files(output_code_dir, files)

    result = {
        "module": "module6_codegen",
        "version": 1,
        "input": input_path,
        "output_code_dir": output_code_dir,
        "problem_name": ir.problem_name,
        "dims": {
            "n": ir.dims.n,
            "p": ir.dims.p,
            "m": ir.dims.m,
            "l": ir.dims.l,
            "q": ir.dims.q,
        },
        "files_generated": sorted(files.keys()),
        "file_count": len(files),
    }

    if write_report:
        report_path = os.path.join(output_code_dir, "module6_report.yaml")
        write_yaml(result, report_path)

    return result


def run_module6_from_bundle(
    bundle_path: str,
    write_report: bool = False,
) -> Dict[str, Any]:
    """从 bundle YAML 运行 Module6。

    Args:
        bundle_path: Module6 bundle YAML 文件路径
        write_report: 是否输出调试报告

    Returns:
        生成结果摘要 dict
    """
    info = load_bundle(bundle_path)
    return run_module6(
        input_path=info["m5_path"],
        output_code_dir=info["output_code_dir"],
        write_report=write_report,
    )
