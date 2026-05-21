"""
表达式预处理 — 语法标准化，不处理量纲

职责：
- ^ → ** 转换
- 移除变量/函数后的节点引用 [k]、[k+1]、[k-1]、[i] 和参数 (k)、(k+1) 等
- Python 关键字安全映射（如 lambda → lambda_）
- 全局重名检查
"""

import re
import keyword as _keyword

# Python 关键字集合
_PYTHON_KEYWORDS = set(_keyword.kwlist)

# 数学函数保留名 — 不能用作变量名
_MATH_RESERVED_NAMES = {
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "exp", "log", "sqrt", "abs", "sign", "pow",
}


# ── 节点索引模式 — 只匹配变量/函数名后紧跟的索引 ─────────────────
# [k], [k+1], [k-1], [i], [0], [N] 等 → 捕获变量名，替换时保留
_NODE_BRACKET = re.compile(r'([a-zA-Z_]\w*)\s*\[[^\]]*\]')
# (k), (k+1), (k-1) 等辅助函数调用参数 → 捕获函数名，替换时保留
_NODE_PAREN = re.compile(r'([a-zA-Z_]\w*)\s*\(\s*k\s*(?:[+-]\s*\d+)?\s*\)')


def python_safe_name(user_name: str) -> str:
    """将用户变量名映射为 Python/SymPy 安全名称"""
    if user_name in _PYTHON_KEYWORDS:
        return f"{user_name}_"
    return user_name


def is_python_keyword(name: str) -> bool:
    return name in _PYTHON_KEYWORDS


def preprocess_expression(expr_str: str) -> str:
    """
    语法标准化（不做量纲处理）:
    1. ^ → **
    2. 移除变量/函数名后的节点索引 [k]、[k+1]、[k-1]、[i] 等
    3. 移除辅助函数调用参数 (k)、(k+1) 等

    注意：不删除数学表达式中的方括号（如无变量名前置的括号），
    也不删除不是紧跟变量名后的括号内容。
    """
    s = expr_str.strip()
    # ^ → **
    s = s.replace("^", "**")
    # 移除变量/函数名后的节点索引 [k]、[k+1] 等 → 保留变量名
    s = _NODE_BRACKET.sub(r"\1", s)
    # 移除辅助函数调用参数 (k)、(k+1) 等 → 保留函数名
    s = _NODE_PAREN.sub(r"\1", s)
    return s


def build_safe_symbol_table(
    states, controls, parameters, auxiliaries=None
):
    """
    构建 用户名称 → 安全名称 和 安全名称 → 原始名称 映射。

    对所有变量类型做 Python 关键字安全映射，并检查全局重名。
    如果 safe_name 冲突，直接抛出 ValueError。

    返回 (name_to_safe, safe_to_original)
    """
    auxiliaries = auxiliaries or []
    name_to_safe: dict = {}
    safe_to_original: dict = {}

    # 收集所有变量名及其类别，用于冲突检查
    all_vars: list = []  # (name, category)

    def _get_name(v):
        return v.name if hasattr(v, "name") else v["name"]

    for sv in states:
        name = _get_name(sv)
        all_vars.append((name, "state"))
        safe = python_safe_name(name)
        name_to_safe[name] = safe
        safe_to_original[safe] = name

    for cv in controls:
        name = _get_name(cv)
        all_vars.append((name, "control"))
        safe = python_safe_name(name)
        name_to_safe[name] = safe
        safe_to_original[safe] = name

    for pv in parameters:
        name = _get_name(pv)
        all_vars.append((name, "parameter"))
        safe = python_safe_name(name)
        name_to_safe[name] = safe
        safe_to_original[safe] = name

    for av in auxiliaries:
        name = _get_name(av)
        all_vars.append((name, "auxiliary"))
        safe = python_safe_name(name)
        name_to_safe[name] = safe
        safe_to_original[safe] = name

    # ── 同类变量重名检查 ─────────────────────────────────────
    _check_duplicates_within_category("state", [n for n, c in all_vars if c == "state"])
    _check_duplicates_within_category("control", [n for n, c in all_vars if c == "control"])
    _check_duplicates_within_category("parameter", [n for n, c in all_vars if c == "parameter"])
    _check_duplicates_within_category("auxiliary", [n for n, c in all_vars if c == "auxiliary"])

    # ── 跨类别重名检查 ────────────────────────────────────────
    _check_cross_category_duplicates(all_vars)

    # ── 数学函数保留名检查 ───────────────────────────────────
    for orig_name, category in all_vars:
        if orig_name in _MATH_RESERVED_NAMES:
            raise ValueError(
                f"变量名冲突：'{orig_name}' ({category}) 与数学函数 '{orig_name}' 同名，"
                f"请使用其他名称"
            )

    # ── 全局重名检查（安全名称映射后） ────────────────────────
    # 检查 safe_name 是否被多个不同的原始名共享
    safe_to_originals: dict = {}
    for orig_name, category in all_vars:
        safe = name_to_safe[orig_name]
        if safe not in safe_to_originals:
            safe_to_originals[safe] = []
        safe_to_originals[safe].append((orig_name, category))

    for safe, entries in safe_to_originals.items():
        if len(entries) > 1:
            # 是同一个原始名在不同类别中出现，还是完全不同名？
            unique_originals = set(e[0] for e in entries)
            if len(unique_originals) > 1:
                raise ValueError(
                    f"变量名冲突：以下变量映射到了同一个安全名称 '{safe}'："
                    + ", ".join(f"{n}({c})" for n, c in entries)
                )
            # 同一原始名出现在多个类别中（如 state 和 auxiliary 都叫 "v"）
            # 这也是一种冲突
            categories = set(c for _, c in entries)
            if len(categories) > 1:
                raise ValueError(
                    f"变量名冲突：'{entries[0][0]}' 同时出现在多个类别中："
                    + ", ".join(sorted(categories))
                )

    return name_to_safe, safe_to_original


def _check_duplicates_within_category(category: str, names: list) -> None:
    """检查同一类别内是否有重名"""
    from collections import Counter
    dupes = [n for n, c in Counter(names).items() if c > 1]
    if dupes:
        raise ValueError(
            f"变量名冲突：{category} 类别中存在重复名称: "
            + ", ".join(sorted(dupes))
        )


def _check_cross_category_duplicates(all_vars: list) -> None:
    """检查同一原始名称是否出现在多个类别中 (state/control/parameter/auxiliary)"""
    name_to_categories: dict = {}
    for name, category in all_vars:
        if name not in name_to_categories:
            name_to_categories[name] = set()
        name_to_categories[name].add(category)
    for name, categories in name_to_categories.items():
        if len(categories) > 1:
            cat_list = sorted(categories)
            raise ValueError(
                f"变量名冲突：'{name}' 同时出现在多个类别中: "
                + ", ".join(cat_list)
            )


def replace_variable_names_in_expr(expr_str: str, name_to_safe: dict) -> str:
    """
    将表达式中的用户变量名替换为安全名称。
    使用词边界匹配，避免部分匹配（如 V 不应匹配 VS0）。
    """
    # 按名称长度降序排列，优先替换长名称（避免 "V" 先匹配到 "VS0" 中的 V）
    sorted_names = sorted(name_to_safe.keys(), key=len, reverse=True)
    for name in sorted_names:
        safe = name_to_safe[name]
        # 使用词边界匹配
        expr_str = re.sub(rf"\b{re.escape(name)}\b", safe, expr_str)
    return expr_str
