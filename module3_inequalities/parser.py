"""
Module 3 解析器 — 从 input dict 解析 inequality_constraints

完成：
- apply_to 归一化
- 表达式归一化（转为 g <= 0）
- 链式不等式拆分
- slack 配置解析（逐约束覆盖 > 全局 > 默认）
- variable_mode 一致性校验
"""

from __future__ import annotations

from typing import Dict, Any, List

from scpgen.common.apply_to import normalize_apply_to
from scpgen.common.constraint_parser import parse_inequality_expressions
from scpgen.common.expression_utils import build_safe_symbol_table

from .models import (
    SlackConfig,
    InequalityConstraintDef,
    InequalityTranscriptionConfig,
    Module3InputDef,
)


def parse_inequality_constraints(
    input_dict: Dict[str, Any],
) -> Module3InputDef:
    """
    从 input dict 解析所有不等式约束。

    Args:
        input_dict: 完整的 problem input dict

    Returns:
        Module3InputDef
    """
    problem_name = input_dict.get("problem_name", "unnamed_problem")
    input_yaml = input_dict.get("input_yaml", "")

    # 构建安全名称映射
    states_raw = input_dict.get("states", [])
    controls_raw = input_dict.get("controls", [])
    parameters_raw = input_dict.get("parameters", [])
    auxiliaries_raw = input_dict.get("auxiliaries", [])

    name_to_safe, safe_to_original = build_safe_symbol_table(
        states_raw, controls_raw, parameters_raw, auxiliaries_raw
    )

    # 网格
    mesh_dict = input_dict.get("mesh", {})
    mesh_N = mesh_dict.get("N", 10)

    # dynamics variable_mode
    dyn_cfg = input_dict.get("dynamics_transcription_config", {})
    dynamics_variable_mode = dyn_cfg.get("variable_mode", "perturbation")

    # inequality_transcription_config
    ineq_cfg_dict = input_dict.get("inequality_transcription_config", {})
    global_slack_dict = ineq_cfg_dict.get("slack", {})
    global_slack = SlackConfig(
        enabled=global_slack_dict.get("enabled", False),
        penalty_type=global_slack_dict.get("penalty_type", "l1"),
        penalty_weight_symbol=global_slack_dict.get("penalty_weight_symbol", "rho_slack"),
    )
    ineq_config = InequalityTranscriptionConfig(
        variable_mode=ineq_cfg_dict.get("variable_mode", None),
        slack=global_slack,
    )

    # 校验 variable_mode 一致性
    _validate_variable_mode(dynamics_variable_mode, ineq_config)

    # 解析不等式约束
    raw_constraints = input_dict.get("inequality_constraints", [])
    constraints = []
    for c_dict in raw_constraints:
        c = _parse_single_inequality(c_dict, name_to_safe, mesh_N, global_slack)
        constraints.append(c)

    module_input = Module3InputDef(
        problem_name=problem_name,
        input_yaml=input_yaml,
        states=states_raw,
        controls=controls_raw,
        parameters=parameters_raw,
        auxiliaries=auxiliaries_raw,
        name_to_safe=name_to_safe,
        safe_to_original=safe_to_original,
        mesh_N=mesh_N,
        constraints=constraints,
        dynamics_variable_mode=dynamics_variable_mode,
        config=ineq_config,
    )

    errors = module_input.validate()
    if errors:
        raise ValueError("Module 3 输入校验失败:\n  " + "\n  ".join(errors))

    return module_input


def _parse_single_inequality(
    c_dict: Dict[str, Any],
    name_to_safe: Dict[str, str],
    mesh_N: int,
    global_slack: SlackConfig,
) -> InequalityConstraintDef:
    """解析单条不等式约束"""
    name = c_dict.get("name", "unnamed_inequality")

    # apply_to 归一化
    apply_to_raw = c_dict.get("apply_to")
    apply_to_normalized = normalize_apply_to(apply_to_raw, mesh_N)

    # 表达式解析 + 归一化为 g <= 0
    parsed = parse_inequality_expressions(c_dict, name_to_safe)
    normalized_exprs = [p[0] for p in parsed]
    sub_names = [p[1] for p in parsed]

    # 原始表达式（用于 traceability）
    original_expression = c_dict.get("expression", c_dict.get("expressions", ""))

    # Slack 配置：逐约束覆盖 > 全局
    slack_dict = c_dict.get("slack", {})
    if slack_dict:
        constraint_slack = SlackConfig(
            enabled=slack_dict.get("enabled", global_slack.enabled),
            penalty_type=slack_dict.get("penalty_type", global_slack.penalty_type),
            penalty_weight_symbol=slack_dict.get(
                "penalty_weight_symbol", global_slack.penalty_weight_symbol
            ),
        )
    else:
        constraint_slack = SlackConfig(
            enabled=global_slack.enabled,
            penalty_type=global_slack.penalty_type,
            penalty_weight_symbol=global_slack.penalty_weight_symbol,
        )

    return InequalityConstraintDef(
        name=name,
        apply_to_raw=apply_to_raw,
        apply_to_normalized=apply_to_normalized,
        normalized_expressions=normalized_exprs,
        sub_names=sub_names,
        original_expression=str(original_expression),
        slack_config=constraint_slack,
    )


def _validate_variable_mode(
    dynamics_mode: str,
    ineq_config: InequalityTranscriptionConfig,
) -> None:
    """校验 variable_mode 一致性"""
    if ineq_config.variable_mode is not None:
        if ineq_config.variable_mode != dynamics_mode:
            raise ValueError(
                f"variable_mode 不一致: inequality_transcription_config 指定为 "
                f"'{ineq_config.variable_mode}'，但 dynamics_transcription_config 为 "
                f"'{dynamics_mode}'。两者必须一致。"
            )
