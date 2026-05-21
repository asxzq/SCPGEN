"""
Module 2 — 原始等式约束离散化-线性化符号模板生成器

将 equality_constraints 转为线性化符号模板。
不做数值计算，不装配 SOCP，不调用 ECOS。
"""

from .runner import run_module2, run_module2_from_yaml
from .models import (
    EqualityConstraintDef,
    EqualityTranscriptionConfig,
    Module2InputDef,
)
