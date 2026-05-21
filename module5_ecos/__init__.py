"""Module 5: ECOS Canonicalizer

将 Module 4 的 solver-agnostic subproblem IR 转换为 ECOS canonical form。
不生成 C 代码，不调用 ECOS，不执行数值求解。
"""

from .runner import run_module5
from .example_data import (
    make_minimal_m4_ir_linear,
    make_minimal_m4_ir_quadratic,
    make_minimal_m4_ir_multi_cost,
)

__all__ = [
    "run_module5",
    "make_minimal_m4_ir_linear",
    "make_minimal_m4_ir_quadratic",
    "make_minimal_m4_ir_multi_cost",
]
