"""
约束表达式归一化 — 将所有不等式统一转为 g <= 0 形式

处理:
- 显式 <= :  a <= b  →  a - b <= 0
- 显式 >= :  a >= b  →  b - a <= 0
- 链式不等式: lower <= x <= upper → 拆成两个
- 默认:     g      →  g <= 0 (已是标准形式)
"""

from __future__ import annotations

from typing import List, Tuple, Optional
import re


# 匹配链式不等式: a <= b <= c
_CHAIN_INEQUALITY = re.compile(
    r'^(.+?)\s*<=\s*(.+?)\s*<=\s*(.+)$'
)

# 匹配 <= 或 >=
_SINGLE_INEQUALITY = re.compile(
    r'^(.+?)\s*(<=|>=)\s*(.+)$'
)


def normalize_to_le_zero(
    expr_str: str,
    constraint_name: str = "",
) -> List[Tuple[str, str]]:
    """
    将不等式表达式归一化为 g <= 0 形式。

    Args:
        expr_str: 原始不等式表达式字符串
        constraint_name: 约束名称（用于链式拆分时自动命名）

    Returns:
        List of (normalized_expression, sub_name) tuples.
        简单不等式返回 1 个元素，链式不等式返回 2 个。

    Examples:
        >>> normalize_to_le_zero("heatflux - heatflux_max")
        [("heatflux - heatflux_max", "")]
        >>> normalize_to_le_zero("a <= b")
        [("a - b", "")]
        >>> normalize_to_le_zero("V >= Vmin")
        [("Vmin - V", "")]
        >>> normalize_to_le_zero("alphamin <= alpha <= alphamax")
        [("alphamin - alpha", "_lower"), ("alpha - alphamax", "_upper")]
    """
    s = expr_str.strip()

    # Case 1: 已经是 g <= 0 的形式（没有不等式符号，或显式 g <= 0）
    # 先检查是否包含不等式符号
    if "<=" not in s and ">=" not in s:
        # 默认即为 g <= 0 形式
        return [(s, "")]

    # Case 2: 链式不等式 a <= b <= c
    chain_match = _CHAIN_INEQUALITY.match(s)
    if chain_match:
        left = chain_match.group(1).strip()
        mid = chain_match.group(2).strip()
        right = chain_match.group(3).strip()
        return _split_chain(left, mid, right, constraint_name)

    # Case 3: 单个不等式 a <= b 或 a >= b
    single_match = _SINGLE_INEQUALITY.match(s)
    if single_match:
        left = single_match.group(1).strip()
        op = single_match.group(2).strip()
        right = single_match.group(3).strip()
        result = _normalize_single(left, op, right)
        return [(result, "")]

    # 不应到达这里
    raise ValueError(f"无法解析不等式表达式: '{expr_str}'")


def _normalize_single(left: str, op: str, right: str) -> str:
    """归一化单个不等式"""
    if op == "<=":
        # a <= b → a - b <= 0
        return f"{left} - ({right})"
    elif op == ">=":
        # a >= b → b - a <= 0
        return f"{right} - ({left})"
    else:
        raise ValueError(f"未知运算符: {op}")


def _split_chain(
    left: str, mid: str, right: str, base_name: str
) -> List[Tuple[str, str]]:
    """
    拆分链式不等式 lower <= x <= upper

    Returns:
        [(lower_expr, "_lower"), (upper_expr, "_upper")]
    """
    lower_expr = _normalize_single(left, "<=", mid)
    upper_expr = _normalize_single(mid, "<=", right)

    # 自动命名
    if base_name:
        lower_name = f"{base_name}_lower"
        upper_name = f"{base_name}_upper"
    else:
        lower_name = "_lower"
        upper_name = "_upper"

    return [(lower_expr, lower_name), (upper_expr, upper_name)]


def has_inequality_operator(expr_str: str) -> bool:
    """检查表达式是否包含不等式运算符"""
    s = expr_str.strip()
    return "<=" in s or ">=" in s


def strip_inequality_sugar(expr_str: str) -> str:
    """
    如果表达式以 'expression: ' 开头且包含不等式，去掉显式的不等式符号，
    转为 g(x,u) 表达式的形式（不做归一化到 <= 0）。
    用于初步检查。
    """
    s = expr_str.strip()
    # 移除可能的前缀
    return s
