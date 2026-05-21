"""Module6 代码生成核心 — 协调 C 代码生成流程。"""

from __future__ import annotations

from typing import Dict
from scpgen.module6_codegen.models import Module6IR
from scpgen.module6_codegen.c_templates import (
    generate_types_h,
    generate_dims_h,
    generate_indices_h,
    generate_problem_h,
    generate_problem_c,
    generate_fill_h,
    generate_fill_c,
    generate_callbacks_h,
    generate_callbacks_stub_c,
    generate_csc_h,
    generate_csc_c,
    generate_ecos_setup_h,
    generate_ecos_setup_c,
    generate_readme,
    generate_cmake,
)


def generate_all(ir: Module6IR) -> Dict[str, str]:
    """从 Module6IR 生成所有 C 源文件。

    Args:
        ir: 从 Module5 输出解析得到的 Module6IR

    Returns:
        Dict[文件名, C 源码内容]
    """
    files: Dict[str, str] = {}

    files["scpgen_types.h"] = generate_types_h(ir)
    files["scpgen_dims.h"] = generate_dims_h(ir)
    files["scpgen_indices.h"] = generate_indices_h(ir)
    files["scpgen_problem.h"] = generate_problem_h(ir)
    files["scpgen_problem.c"] = generate_problem_c(ir)
    files["scpgen_fill.h"] = generate_fill_h(ir)
    files["scpgen_fill.c"] = generate_fill_c(ir)
    files["scpgen_callbacks.h"] = generate_callbacks_h(ir)
    files["scpgen_callbacks_stub.c"] = generate_callbacks_stub_c(ir)
    files["scpgen_csc.h"] = generate_csc_h(ir)
    files["scpgen_csc.c"] = generate_csc_c(ir)
    files["scpgen_ecos_setup.h"] = generate_ecos_setup_h(ir)
    files["scpgen_ecos_setup.c"] = generate_ecos_setup_c(ir)
    files["README.md"] = generate_readme(ir)
    files["CMakeLists.txt"] = generate_cmake(ir)

    return files
