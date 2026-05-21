"""
变量扩展器 — 将 Module 4 的 z 向量扩展为 ECOS 的 y 向量

核心逻辑:
1. 从 Module 4 的 decision_variable_registry 复制所有原始变量块
2. 遍历 cost_terms.merged，为每个二次代价项创建 epigraph 变量
3. 重新分配列索引：原始 z 变量保持不变，epigraph 变量追加到末尾
"""

from __future__ import annotations

from typing import Dict, List, Any, Tuple

from .models import EcosVariableBlock


def extend_variables(m4_ir: Dict[str, Any]) -> Dict[str, Any]:
    """将 Module 4 的 z 向量扩展为 ECOS 的 y 向量。

    Args:
        m4_ir: Module 4 subproblem IR dict

    Returns:
        {
            "original_blocks": List[EcosVariableBlock],   # z 中的变量
            "epigraph_blocks": List[EcosVariableBlock],   # 新增的 epigraph 变量
            "ecos_blocks": List[EcosVariableBlock],       # y = [z; epigraph] 中的所有变量
            "dim_z": int,                                  # z 的维度
            "dim_y": int,                                  # y 的维度
        }
    """
    # 1. 解析原始变量
    dvr = m4_ir.get("decision_variable_registry", {})
    m4_blocks = dvr.get("blocks", [])

    original_blocks: List[EcosVariableBlock] = []
    for mb in m4_blocks:
        original_blocks.append(EcosVariableBlock(
            name=mb["name"],
            role=mb.get("role", ""),
            source_module=mb.get("source_module", ""),
            domain=mb.get("domain", "free"),
            dimension_concrete=mb.get("dimension_concrete", 0),
            dimension_symbolic=mb.get("dimension_symbolic", ""),
            column_start_concrete=mb.get("column_start_concrete", 0),
            column_end_concrete=mb.get("column_end_concrete", 0),
            in_original_z=True,
        ))

    dim_z = sum(b.dimension_concrete for b in original_blocks)

    # 2. 为二次代价项创建 epigraph 变量
    cost_terms = m4_ir.get("cost_terms", {})
    merged_terms = cost_terms.get("merged", [])

    epigraph_blocks: List[EcosVariableBlock] = []
    quadratic_info: List[Dict[str, Any]] = []
    warnings: List[str] = []

    next_col = dim_z  # epigraph 变量从 dim_z 开始

    for term in merged_terms:
        if term.get("type") != "quadratic":
            continue

        name = term["name"]
        epi_name = f"t_{name}"

        block = EcosVariableBlock(
            name=epi_name,
            role="quadratic_cost_epigraph",
            source_module="module5_ecos",
            domain="free",
            dimension_concrete=1,
            dimension_symbolic="1",
            column_start_concrete=next_col,
            column_end_concrete=next_col,
            in_original_z=False,
        )
        epigraph_blocks.append(block)

        # 记录二次代价信息以供后续 SOC 构造使用
        # 变量选择优先级：norm_variable > variables[0]
        norm_var = term.get("norm_variable")
        variables = term.get("variables", [])

        # 检查 Module4 传来的 norm_variable warning
        m4_warning = term.get("_norm_variable_warning")
        if m4_warning:
            warnings.append(m4_warning)

        if norm_var and norm_var != "unknown":
            vector_var = norm_var
        elif variables:
            if len(variables) == 1:
                vector_var = variables[0]
            else:
                # 多变量且无 norm_variable → 尝试从 expression_template 解析
                vector_var = _parse_vector_variable_from_expr(term, name, warnings)
                if not vector_var:
                    vector_var = variables[0] if variables else ""
        else:
            vector_var = ""
            warnings.append(
                f"二次代价项 '{name}' 没有 variables 也没有 norm_variable"
            )

        quadratic_info.append({
            "source_cost_term": name,
            "epigraph_variable": epi_name,
            "epigraph_column": next_col,
            "variables": variables,
            "norm_variable": norm_var or vector_var,
            "vector_variable": vector_var,
            "rho_symbol": _extract_rho_symbol(term),
        })

        next_col += 1

    dim_y = dim_z + len(epigraph_blocks)

    # 3. 组装完整的 ecos_blocks
    ecos_blocks = list(original_blocks) + list(epigraph_blocks)

    return {
        "original_blocks": original_blocks,
        "epigraph_blocks": epigraph_blocks,
        "ecos_blocks": ecos_blocks,
        "dim_z": dim_z,
        "dim_y": dim_y,
        "quadratic_info": quadratic_info,
        "warnings": warnings,
    }


def _extract_rho_symbol(term: Dict[str, Any]) -> str:
    """从二次代价项中提取惩罚权重符号。

    检查 expression_template 和 metadata 中的模式:
    - "0.5 * rho_vc * sum_squares(vc)" → "rho_vc"
    - "0.5 * rho_heat * sum_squares(s_heat_rate)" → "rho_heat"

    Args:
        term: 合并的代价项 dict

    Returns:
        惩罚权重符号字符串
    """
    expr = term.get("expression_template", "")

    # 尝试从表达式模板中提取
    import re
    # 匹配模式: rho_xxx (后面跟 * sum_squares 或直接在表达式中)
    m = re.search(r'(rho_\w+)', expr)
    if m:
        return m.group(1)

    # 尝试从 metadata 中提取
    meta = term.get("metadata", {})
    meta_expr = meta.get("expression_ascii", "")
    m = re.search(r'(rho_\w+)', meta_expr)
    if m:
        return m.group(1)

    # 后备方案：使用通用名称
    return "rho"


def _parse_vector_variable_from_expr(
    term: Dict[str, Any],
    name: str,
    warnings: List[str],
) -> str:
    """从 expression_template 解析 sum_squares(xxx) 或 ||xxx||² 中的变量名。

    当 norm_variable 未显式指定且 variables 长度 > 1 时调用。
    若解析失败，产生 warning。

    Returns:
        解析出的变量名，或空字符串
    """
    import re

    expr = term.get("expression_template", "") or term.get("expression_ascii", "")

    # 匹配 sum_squares(variable_name)
    m = re.search(r'sum_squares\(\s*(\w+)\s*\)', expr)
    if m:
        return m.group(1)

    # 匹配 ||variable_name||² 或 ||variable_name||^2
    m = re.search(r'\|\|\s*(\w+)\s*\|\|\s*[²\^2]', expr)
    if m:
        return m.group(1)

    # 解析失败
    variables = term.get("variables", [])
    warnings.append(
        f"二次代价项 '{name}' 有 {len(variables)} 个变量 ({variables})，"
        f"无法从 expression_template 解析 sum_squares(target) 或 ||target||²，"
        f"且未显式指定 'norm_variable'。"
        f"请 Module4 cost_terms.merged 中提供 'norm_variable' 字段。"
    )
    return ""
