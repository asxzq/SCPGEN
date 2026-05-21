"""
成本项注册表 — 统一收集 M1/M2/M3 的目标惩罚项

来源：
  - M1: introduced_cost_term_templates (virtual control penalty)
  - M2: 第一版无 cost terms
  - M3: introduced_cost_terms (slack penalty)

merged 中的每个 cost term 使用统一 schema：
  name, source_module, type, expression_template, variables, role
"""

from __future__ import annotations

from typing import List, Dict, Any


def build_cost_registry(
    m1_output: Dict[str, Any],
    m2_output: Dict[str, Any],
    m3_output: Dict[str, Any],
    m2_enabled: bool,
    m3_enabled: bool,
) -> Dict[str, Any]:
    """构建成本项注册表，返回 {by_module1, by_module2, by_module3, merged}"""

    by_m1: List[Dict[str, Any]] = []
    by_m2: List[Dict[str, Any]] = []
    by_m3: List[Dict[str, Any]] = []
    merged: List[Dict[str, Any]] = []

    # ── M1 virtual control penalty ──
    m1_vc_cfg = m1_output.get("configuration", {}).get("virtual_control", {})
    m1_vc_form = m1_vc_cfg.get("form", "signed")
    m1_ct = m1_output.get("introduced_cost_term_templates", [])
    for ct in m1_ct:
        entry = dict(ct)
        entry["source_module"] = "module1_dynamics"
        # 传递 VC form 信息用于推断
        entry["_vc_form"] = m1_vc_form
        by_m1.append(entry)

        # 归一化 merged 条目
        normalized = _normalize_cost_term(entry, ct)
        merged.append(normalized)

    # ── M2: 第一版无 cost terms ──
    # by_m2 保持空

    # ── M3 slack penalty ──
    if m3_enabled and m3_output:
        m3_ct = m3_output.get("introduced_cost_terms", [])
        for ct in m3_ct:
            entry = dict(ct)
            entry["source_module"] = "module3_inequalities"
            by_m3.append(entry)

            # 归一化 merged 条目
            normalized = _normalize_cost_term(entry, ct)
            merged.append(normalized)

    return {
        "by_module1": by_m1,
        "by_module2": by_m2,
        "by_module3": by_m3,
        "merged": merged,
    }


def _normalize_cost_term(
    entry: Dict[str, Any],
    raw_ct: Dict[str, Any],
) -> Dict[str, Any]:
    """将原始 cost term 归一化为统一 schema。

    统一字段：
      name, source_module, type, expression_template, variables, role

    同时保留原始字段在 metadata 中（如 expression_ascii, generated_by 等）。
    """
    name = entry.get("name", "unknown")
    source_module = entry.get("source_module", "unknown")
    ct_type = entry.get("type", "linear")

    # 推断 expression_template
    expr_template = entry.get("expression_template", "")
    if not expr_template:
        expr_template = entry.get("expression_ascii", "")
    if not expr_template:
        expr_template = entry.get("expression_template_ascii", "")

    # 推断 variables
    variables = entry.get("variables", [])
    if not variables:
        variables = list(entry.get("involved_variables", []))

    # 推断 role
    role = entry.get("role", "")
    if not role:
        role = _infer_role(name, source_module)

    # 自动推导 variables（如果仍未确定）
    if not variables:
        variables = _infer_variables(name, source_module, entry)
    if not expr_template:
        expr_template = _infer_expression_template(name, entry)

    normalized = {
        "name": name,
        "source_module": source_module,
        "type": ct_type,
        "expression_template": expr_template,
        "variables": variables,
        "role": role,
    }

    # ── 显式提取系数/权重字段（供 Module5 直接使用，避免 fallback warning）──
    if ct_type == "linear":
        normalized["coefficient"] = _extract_coefficient(entry, name)
    elif ct_type == "quadratic":
        normalized["weight_symbol"] = _extract_weight_symbol(entry, name)
        nv = _extract_norm_variable(entry, variables)
        if nv == "":
            # 多变量且无法从 expression_template 推断 norm_variable
            normalized["_norm_variable_warning"] = (
                f"二次代价项 '{name}' 有 {len(variables)} 个变量 ({variables})，"
                f"且 expression_template 无法解析出 sum_squares(target_var) 或 ||target_var||²。"
                f"请显式提供 'norm_variable' 字段。"
            )
            nv = variables[0] if variables else "unknown"
        normalized["norm_variable"] = nv
        normalized["quadratic_form_type"] = _extract_quadratic_form_type(entry, expr_template)

    # metadata 保留原始字段（排除已归一化的）
    meta = {}
    for k, v in entry.items():
        if k not in normalized:
            meta[k] = v
    if meta:
        normalized["metadata"] = meta

    return normalized


def _extract_coefficient(entry: Dict[str, Any], name: str) -> str:
    """从线性代价项中提取 coefficient 符号。

    优先级：
    1. entry["coefficient"] — 显式给出
    2. entry["penalty_weight_symbol"]
    3. metadata["penalty_weight_symbol"]
    4. 从 expression_ascii 正则提取
    """
    import re

    # 显式字段
    explicit = entry.get("coefficient") or entry.get("penalty_weight_symbol")
    if explicit:
        return explicit

    meta = entry.get("metadata", {})
    explicit = meta.get("penalty_weight_symbol")
    if explicit:
        return explicit

    # 正则 fallback
    expr = entry.get("expression_ascii", "") or entry.get("expression_template", "")
    m = re.search(r'(rho_\w+)\s*\*', expr)
    if m:
        return m.group(1)

    return "rho"


def _extract_weight_symbol(entry: Dict[str, Any], name: str) -> str:
    """从二次代价项中提取 weight_symbol。

    优先级：
    1. entry["weight_symbol"]
    2. entry["coefficient"]
    3. entry["penalty_weight_symbol"]
    4. metadata["penalty_weight_symbol"]
    5. 从 expression_ascii 正则提取
    """
    import re

    for key in ["weight_symbol", "coefficient", "penalty_weight_symbol"]:
        val = entry.get(key)
        if val:
            return val

    meta = entry.get("metadata", {})
    val = meta.get("penalty_weight_symbol")
    if val:
        return val

    # 正则 fallback
    expr = entry.get("expression_ascii", "") or entry.get("expression_template", "")
    m = re.search(r'(rho_\w+)', expr)
    if m:
        return m.group(1)

    return "rho"


def _extract_norm_variable(entry: Dict[str, Any], variables: List[str]) -> str:
    """从二次代价项中提取 norm_variable。

    优先级：
    1. entry["norm_variable"] — 显式给出，直接使用
    2. 从 expression_template 解析 sum_squares(xxx) 或 ||xxx||²
    3. 若 variables 长度 == 1，fallback 到 variables[0]（无 warning）
    4. 若 variables 长度 > 1 且解析失败 → 返回 "" 并在调用方产生 warning
    5. 若 variables 为空 → 返回 "unknown"
    """
    import re

    # 1. 显式指定
    explicit = entry.get("norm_variable") or entry.get("norm_variable_name")
    if explicit:
        return explicit

    # 2. 从 expression_template 解析
    expr = entry.get("expression_template", "") or entry.get("expression_ascii", "")
    if expr:
        # 匹配 sum_squares(variable_name) 或 sum_squares(var1 + var2 + ...)
        m = re.search(r'sum_squares\(\s*(\w+)\s*\)', expr)
        if m:
            return m.group(1)
        # 匹配 ||variable_name||² 或 ||variable_name||^2
        m = re.search(r'\|\|\s*(\w+)\s*\|\|\s*[²\^2]', expr)
        if m:
            return m.group(1)

    # 3. fallback：只有唯一变量才允许
    if len(variables) == 1:
        return variables[0]

    # 4. 无变量 → unknown
    if len(variables) == 0:
        return "unknown"

    # 5. 多变量且无法推断 → 返回空字符串，触发调用方 warning
    return ""


def _extract_quadratic_form_type(entry: Dict[str, Any], expr_template: str) -> str:
    """从二次代价项中提取 quadratic_form_type。"""
    explicit = entry.get("quadratic_form_type")
    if explicit:
        return explicit

    # 从表达式推断
    expr_lower = expr_template.lower()
    if "sum_squares" in expr_lower or "||" in expr_lower:
        return "sum_squares"
    if "l2" in expr_lower or "quadratic" in expr_lower:
        return "l2_squared"

    return "sum_squares"


def _infer_role(name: str, source_module: str) -> str:
    """根据名称和来源推断 cost term 的语义角色"""
    name_lower = name.lower()
    if "virtual_control" in name_lower or "vc_" in name_lower:
        return "virtual_control_penalty"
    if "slack" in name_lower:
        return "slack_penalty"
    if source_module == "module1_dynamics":
        return "virtual_control_penalty"
    if source_module == "module3_inequalities":
        return "slack_penalty"
    return "other_penalty"


def _infer_variables(
    name: str,
    source_module: str,
    entry: Dict[str, Any],
) -> List[str]:
    """根据名称和来源推导涉及的变量"""
    name_lower = name.lower()
    vc_form = entry.get("_vc_form", "")
    parent = entry.get("parent_constraint", "")

    if "virtual_control" in name_lower:
        if vc_form == "split_nonnegative" or "l1" in name_lower:
            return ["vc_plus", "vc_minus"]
        else:
            return ["vc"]
    if "slack" in name_lower and parent:
        return [f"s_{parent}"]
    if source_module == "module3_inequalities":
        return [f"s_{parent}"] if parent else []

    return []


def _infer_expression_template(name: str, entry: Dict[str, Any]) -> str:
    """推导表达式模板"""
    name_lower = name.lower()
    weight = entry.get("penalty_weight_symbol", "rho")

    if "virtual_control" in name_lower:
        if "l1" in name_lower:
            return f"{weight} * sum(vc_plus + vc_minus)"
        elif "quadratic" in name_lower:
            return f"0.5 * {weight} * sum_squares(vc)"
        else:
            return f"{weight} * sum(vc)"
    if "slack" in name_lower:
        parent = entry.get("parent_constraint", "constraint")
        return f"{weight} * sum(s_{parent})"

    return ""
