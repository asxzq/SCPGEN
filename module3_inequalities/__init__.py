"""
Module 3 — 原始不等式约束离散化-线性化符号模板生成器

将 inequality_constraints 转为线性化符号模板（含 slack 变量支持）。
不做数值计算，不装配 SOCP，不调用 ECOS。
"""

from .runner import run_module3, run_module3_from_yaml
from .models import (
    SlackConfig,
    InequalityConstraintDef,
    InequalityTranscriptionConfig,
    Module3InputDef,
)
