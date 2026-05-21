"""
目标规范化器 — 将 Module 4 的符号化代价项转换为 ECOS c 向量计划

处理:
1. 线性代价项 → c 向量中的条目（objective_vector_plan）
2. 二次代价项 → epigraph 变量标记（c[t] += 1）
"""

from __future__ import annotations

from typing import Dict, List, Any

from .models import ObjectivePlanEntry


def canonicalize_objective(
    m4_ir: Dict[str, Any],
    var_ext: Dict[str, Any],
) -> Dict[str, Any]:
    """将 Module 4 代价项转换为 ECOS 目标。

    Args:
        m4_ir: Module 4 subproblem IR dict
        var_ext: variable_extender 的输出

    Returns:
        目标部分 dict:
        {
            "form": "c^T y",
            "c_dimension_concrete": dim_y,
            "linear_terms": [...],
            "quadratic_terms_canonicalized": [...],
            "objective_vector_plan": {"entries": [...]},
            "warnings": [...],
        }
    """
    dim_y = var_ext["dim_y"]
    ecos_blocks = var_ext["ecos_blocks"]
    epi_blocks = var_ext.get("epigraph_blocks", [])

    # 构建 name → EcosVariableBlock 的映射
    block_by_name: Dict[str, Any] = {b.name: b for b in ecos_blocks}

    cost_terms = m4_ir.get("cost_terms", {})
    merged_terms = cost_terms.get("merged", [])

    linear_terms: List[Dict[str, Any]] = []
    quadratic_terms: List[Dict[str, Any]] = []
    plan_entries: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for term in merged_terms:
        term_type = term.get("type", "")

        if term_type == "linear":
            entry, term_warnings = _process_linear_term(term, block_by_name)
            linear_terms.append(term)
            if entry:
                plan_entries.extend(entry)
            warnings.extend(term_warnings)

        elif term_type == "quadratic":
            entry, term_warnings = _process_quadratic_term(term, var_ext)
            quadratic_terms.append(entry)
            warnings.extend(term_warnings)

        else:
            raise ValueError(
                f"未知的代价项类型 '{term_type}'，项名称为 '{term.get('name', '?')}'"
            )

    # 为每个 epigraph 变量添加 c[t] = 1 的 plan entry
    # quadratic_terms_canonicalized 仅作为解释/追踪信息，不允许成为 Module6 填 c 的唯一依据
    for eb in epi_blocks:
        # 找到对应的源代价项名称
        source_name = eb.name
        if source_name.startswith("t_"):
            source_name = source_name[2:]
        plan_entries.append({
            "source_cost_term": source_name,
            "variable_block": eb.name,
            "coefficient": 1,
            "applies_to": "single",
            "is_epigraph": True,
            "variable_dimension_concrete": eb.dimension_concrete,
            "variable_column_start": eb.column_start_concrete,
            "variable_column_end": eb.column_end_concrete,
        })

    # ── 一致性校验 ──
    _validate_quadratic_epigraph_consistency(
        quadratic_terms, epi_blocks, plan_entries, cost_terms
    )

    return {
        "form": "c^T y",
        "c_dimension_concrete": dim_y,
        "linear_terms": linear_terms,
        "quadratic_terms_canonicalized": quadratic_terms,
        "objective_vector_plan": {
            "entries": plan_entries,
        },
        "warnings": warnings,
    }


def _process_linear_term(
    term: Dict[str, Any],
    block_by_name: Dict[str, Any],
) -> tuple:
    """处理单个线性代价项 → c 向量计划条目。

    Args:
        term: 合并的代价项 dict
        block_by_name: 变量名 → EcosVariableBlock 映射

    Returns:
        (objective_vector_plan 条目列表, warnings 列表)

    Raises:
        ValueError: 变量或表达式模板无法识别时抛出
    """
    name = term.get("name", "?")
    variables = term.get("variables", [])
    expr_template = term.get("expression_template", "")

    if not variables:
        raise ValueError(
            f"线性代价项 '{name}' 缺少 'variables' 字段。"
            f"expression_template: {expr_template}"
        )

    # 提取系数符号（优先显式字段，fallback 时产生 warning）
    coefficient, coeff_warning = _extract_linear_coefficient(expr_template, term)
    warnings = []
    if coeff_warning:
        warnings.append(coeff_warning)

    entries = []
    for var_name in variables:
        if var_name not in block_by_name:
            raise ValueError(
                f"线性代价项 '{name}' 引用了未知变量 '{var_name}'。"
                f"可用变量: {list(block_by_name.keys())}"
            )

        block = block_by_name[var_name]
        entries.append({
            "source_cost_term": name,
            "variable_block": var_name,
            "coefficient": coefficient,
            "applies_to": "all_elements",
            "variable_dimension_concrete": block.dimension_concrete,
            "variable_column_start": block.column_start_concrete,
            "variable_column_end": block.column_end_concrete,
        })

    return entries, warnings


def _extract_linear_coefficient(expr_template: str, term: Dict[str, Any]) -> tuple:
    """从线性代价项中提取系数符号（优先显式字段）。

    优先级:
    1. term["coefficient"] — Module4 显式给出
    2. 从 expression_template 正则提取（fallback，产生 warning）

    例如:
    - "rho_vc * sum(vc_plus + vc_minus)" → ("rho_vc", warning_if_fallback)
    - term with coefficient="rho_heat" → ("rho_heat", None)
    """
    # 优先使用显式字段
    explicit = term.get("coefficient")
    if explicit:
        return explicit, None

    # fallback: 正则提取
    import re
    m = re.search(r'(rho_\w+)\s*\*', expr_template)
    if m:
        val = m.group(1)
        return val, (
            f"[fallback] 线性代价项 '{term.get('name', '?')}' 缺少显式 'coefficient' 字段，"
            f"从 expression_template 正则提取为 '{val}'。"
            f"请 Module4 cost_terms.merged 中提供 'coefficient' 字段。"
        )

    # 尝试从 metadata 中获取
    meta = term.get("metadata", {})
    meta_expr = meta.get("expression_ascii", "")
    m = re.search(r'(rho_\w+)\s*\*', meta_expr)
    if m:
        val = m.group(1)
        return val, (
            f"[fallback] 线性代价项 '{term.get('name', '?')}' 缺少显式 'coefficient' 字段，"
            f"从 metadata.expression_ascii 正则提取为 '{val}'。"
            f"请 Module4 cost_terms.merged 中提供 'coefficient' 字段。"
        )

    # 最后后备
    return "rho", (
        f"[fallback] 线性代价项 '{term.get('name', '?')}' 缺少显式 'coefficient' 字段，"
        f"且无法从 expression_template 提取，使用默认值 'rho'。"
        f"请 Module4 cost_terms.merged 中提供 'coefficient' 字段。"
    )


def _process_quadratic_term(
    term: Dict[str, Any],
    var_ext: Dict[str, Any],
) -> tuple:
    """处理单个二次代价项 → 标记 epigraph 变量。

    Args:
        term: 合并的代价项 dict
        var_ext: variable_extender 的输出

    Returns:
        (二次代价规范化信息 dict, warnings 列表)
    """
    name = term.get("name", "?")

    # 查找匹配的 epigraph 变量
    epi_name = f"t_{name}"
    epi_blocks = var_ext.get("epigraph_blocks", [])
    epi_block = None
    for eb in epi_blocks:
        if eb.name == epi_name:
            epi_block = eb
            break

    if epi_block is None:
        raise ValueError(
            f"二次代价项 '{name}' 未找到对应的 epigraph 变量 '{epi_name}'"
        )

    rho_symbol, rho_warning = _extract_rho_from_quadratic(term)
    warnings = []
    if rho_warning:
        warnings.append(rho_warning)

    return {
        "source_cost_term": name,
        "epigraph_variable": epi_name,
        "coefficient_in_c": 1,
        "epigraph_column": epi_block.column_start_concrete,
        "rho_symbol": rho_symbol,
    }, warnings


def _extract_rho_from_quadratic(term: Dict[str, Any]) -> tuple:
    """从二次代价项中提取 rho 符号（优先显式字段）。

    优先级:
    1. term["weight_symbol"] — Module4 显式给出
    2. term["coefficient"] — 兼容旧字段
    3. 从 expression_template 正则提取（fallback，产生 warning）

    例如:
    - "0.5 * rho_vc * sum_squares(vc)" → ("rho_vc", None) 若显式给出
    """
    # 优先使用显式字段
    explicit = term.get("weight_symbol") or term.get("coefficient")
    if explicit:
        return explicit, None

    # fallback: 正则提取
    import re
    expr = term.get("expression_template", "")
    m = re.search(r'(rho_\w+)', expr)
    if m:
        val = m.group(1)
        return val, (
            f"[fallback] 二次代价项 '{term.get('name', '?')}' 缺少显式 'weight_symbol' 字段，"
            f"从 expression_template 正则提取为 '{val}'。"
            f"请 Module4 cost_terms.merged 中提供 'weight_symbol' 字段。"
        )

    meta = term.get("metadata", {})
    meta_expr = meta.get("expression_ascii", "")
    m = re.search(r'(rho_\w+)', meta_expr)
    if m:
        val = m.group(1)
        return val, (
            f"[fallback] 二次代价项 '{term.get('name', '?')}' 缺少显式 'weight_symbol' 字段，"
            f"从 metadata.expression_ascii 正则提取为 '{val}'。"
            f"请 Module4 cost_terms.merged 中提供 'weight_symbol' 字段。"
        )

    return "rho", (
        f"[fallback] 二次代价项 '{term.get('name', '?')}' 缺少显式 'weight_symbol' 字段，"
        f"且无法从 expression_template 提取，使用默认值 'rho'。"
        f"请 Module4 cost_terms.merged 中提供 'weight_symbol' 字段。"
    )


def _validate_quadratic_epigraph_consistency(
    quadratic_terms: List[Dict[str, Any]],
    epi_blocks: List[Any],
    plan_entries: List[Dict[str, Any]],
    cost_terms: Dict[str, Any],
) -> None:
    """校验二次代价项与 epigraph 变量之间的一致性。

    检查项：
    1. quadratic_terms_canonicalized 数量 == epigraph_blocks 数量
    2. 每个 quadratic cost term 必须有唯一的 t_<cost_name>
    3. 每个 epigraph objective entry 必须能对应一个 quadratic term

    Raises:
        ValueError: 任何不一致
    """
    n_quad = len(quadratic_terms)
    n_epi = len(epi_blocks)

    # 1. 数量一致
    if n_quad != n_epi:
        quad_names = [qt.get("source_cost_term", "?") for qt in quadratic_terms]
        epi_names = [eb.name for eb in epi_blocks]
        raise ValueError(
            f"quadratic_terms_canonicalized 数量 ({n_quad}: {quad_names}) "
            f"与 epigraph_blocks 数量 ({n_epi}: {epi_names}) 不一致。"
            f"每个二次代价项必须对应唯一的 epigraph 变量 t_<cost_name>。"
        )

    # 2. 每个 quadratic term 必须有唯一 t_<cost_name>
    seen_t_names: set = set()
    for qt in quadratic_terms:
        src_name = qt.get("source_cost_term", "")
        t_name = f"t_{src_name}"
        if t_name in seen_t_names:
            raise ValueError(
                f"重复的二次代价项名称 '{src_name}'，"
                f"每个 quadratic cost term 必须有唯一的 t_<cost_name>"
            )
        seen_t_names.add(t_name)

    # 3. 每个 epigraph plan entry 能对应 quadratic term
    epi_entries = [e for e in plan_entries if e.get("is_epigraph")]
    epi_source_names = {e.get("source_cost_term", "") for e in epi_entries}
    quad_source_names = {qt.get("source_cost_term", "") for qt in quadratic_terms}

    if epi_source_names != quad_source_names:
        only_epi = epi_source_names - quad_source_names
        only_quad = quad_source_names - epi_source_names
        msg_parts = []
        if only_epi:
            msg_parts.append(
                f"objective_vector_plan 中 epigraph entry 引用了不存在的二次项: {only_epi}"
            )
        if only_quad:
            msg_parts.append(
                f"二次项 {only_quad} 在 objective_vector_plan 中缺少 epigraph entry"
            )
        raise ValueError("; ".join(msg_parts))

    # 4. 确保 merged 中的 quadratic 项也数量一致
    merged = cost_terms.get("merged", [])
    merged_quad = [t for t in merged if t.get("type") == "quadratic"]
    if len(merged_quad) != n_quad:
        quad_names_from_cost = [t.get("name", "?") for t in merged_quad]
        raise ValueError(
            f"cost_terms.merged 中 quadratic 项数量 ({len(merged_quad)}: {quad_names_from_cost}) "
            f"与 quadratic_terms_canonicalized 数量 ({n_quad}) 不一致"
        )
