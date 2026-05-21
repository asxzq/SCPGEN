"""
约束表达式解析器

解析 equality_constraints 和 inequality_constraints 中的表达式字段。
支持 expression / expressions / equations 多种输入形式。
"""

from __future__ import annotations

from typing import Dict, Any, List, Tuple

from .expression_utils import preprocess_expression, replace_variable_names_in_expr
from .constraint_normalizer import normalize_to_le_zero


def parse_equality_expressions(
    constraint_dict: Dict[str, Any],
    name_to_safe: Dict[str, str],
) -> List[str]:
    """
    解析等式约束的表达式，支持 3 种写法。

    写法 1: expression: "h - hf"
    写法 2: expressions: ["r - rf", "V - Vf"]
    写法 3: equations: {r: r0, V: V0} → 转为 "r - r0"

    Returns:
        预处理后的表达式字符串列表（每个元素代表一个标量等式 h = 0）
    """
    expressions: List[str] = []

    # 写法 3: equations 字典
    if "equations" in constraint_dict:
        eqs = constraint_dict["equations"]
        if isinstance(eqs, dict):
            for lhs, rhs in eqs.items():
                expr = f"{lhs} - ({rhs})"
                expressions.append(expr)
        elif isinstance(eqs, list):
            for item in eqs:
                if isinstance(item, dict) and len(item) == 1:
                    for lhs, rhs in item.items():
                        expr = f"{lhs} - ({rhs})"
                        expressions.append(expr)
                else:
                    expressions.append(str(item))
        else:
            raise ValueError(f"不支持的 equations 格式: {type(eqs)}")

    # 写法 1: 单个 expression
    elif "expression" in constraint_dict:
        expressions.append(constraint_dict["expression"])

    # 写法 2: expressions 列表
    elif "expressions" in constraint_dict:
        raw = constraint_dict["expressions"]
        if isinstance(raw, list):
            expressions.extend(raw)
        else:
            expressions.append(str(raw))

    else:
        raise ValueError(
            f"等式约束 '{constraint_dict.get('name', '?')}' 缺少表达式字段。"
            f"请使用 expression / expressions / equations 之一。"
        )

    # 预处理：语法标准化 + 变量名替换
    processed = []
    for expr in expressions:
        e = preprocess_expression(str(expr))
        e = replace_variable_names_in_expr(e, name_to_safe)
        processed.append(e)

    return processed


def parse_inequality_expressions(
    constraint_dict: Dict[str, Any],
    name_to_safe: Dict[str, str],
) -> List[Tuple[str, str]]:
    """
    解析不等式约束的表达式，支持多种写法，并归一化为 g <= 0。

    写法 1: expression: "heatflux - heatflux_max" (默认 g <= 0)
    写法 2: expression: "heatflux <= heatflux_max"
    写法 3: expression: "V >= Vmin"
    写法 4: expression: "alphamin <= alpha <= alphamax" (链式，拆成两个)
    写法 5: expressions: [...]

    Returns:
        List of (normalized_expression_string, sub_name) tuples.
        每个元素的表达式已归一化为 g <= 0 形式。
    """
    constraint_name = constraint_dict.get("name", "")

    # 收集原始表达式
    raw_expressions: List[str] = []

    if "expression" in constraint_dict:
        raw_expressions.append(constraint_dict["expression"])
    elif "expressions" in constraint_dict:
        raw = constraint_dict["expressions"]
        if isinstance(raw, list):
            raw_expressions.extend(str(r) for r in raw)
        else:
            raw_expressions.append(str(raw))
    else:
        raise ValueError(
            f"不等式约束 '{constraint_name}' 缺少表达式字段。"
            f"请使用 expression 或 expressions。"
        )

    # 归一化每条表达式
    result: List[Tuple[str, str]] = []
    for expr_str in raw_expressions:
        normalized = normalize_to_le_zero(expr_str, constraint_name)
        result.extend(normalized)

    # 预处理：语法标准化 + 变量名替换
    processed = []
    for expr, sub_name in result:
        e = preprocess_expression(expr)
        e = replace_variable_names_in_expr(e, name_to_safe)
        processed.append((e, sub_name))

    return processed


def get_original_expression_form(constraint_dict: Dict[str, Any]) -> str:
    """
    获取约束的原始表达式形式描述，用于输出 YAML 的 traceability。
    """
    if "equations" in constraint_dict:
        return "equations"
    if "expression" in constraint_dict:
        return "expression"
    if "expressions" in constraint_dict:
        return "expressions"
    return "unknown"
