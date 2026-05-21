"""Module 6: C Code Generator.

读取 Module 5 输出的 ECOS canonical IR + matrix assembly plan，
生成面向 ECOS 的 C 代码框架和数据填充代码。
"""

__all__ = [
    "run_module6",
    "run_module6_from_bundle",
    "validate_module6_ir",
    "parse_module5_output",
    "Module6IR",
]
