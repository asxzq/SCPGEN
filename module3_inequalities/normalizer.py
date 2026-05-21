"""
Module 3 归一化器 — 不等式约束专用归一化

委托 common 模块处理 apply_to 和表达式解析。
Module 3 特有：链式不等式拆分后的子名称管理，slack 配置合并。
"""

from __future__ import annotations

from typing import Dict, Any, List, Tuple

from scpgen.common.constraint_normalizer import normalize_to_le_zero
from scpgen.common.apply_to import normalize_apply_to

from .models import SlackConfig, InequalityConstraintDef


def normalize_inequality_expression(
    expr_str: str,
    constraint_name: str,
) -> List[Tuple[str, str]]:
    """
    归一化单条不等式表达式为 g <= 0 形式。

    委托 common/constraint_normalizer。
    额外处理：自动命名链式拆分的子约束。

    Returns:
        List of (normalized_expression, sub_name)
    """
    return normalize_to_le_zero(expr_str, constraint_name)


def resolve_slack_config(
    constraint_slack_dict: Dict[str, Any],
    global_slack: SlackConfig,
) -> SlackConfig:
    """
    解析逐约束 slack 配置，合并全局默认值。

    规则：
    1. 如果 constraint 自己写了 slack 配置，优先使用 constraint 配置
    2. 否则使用全局 slack 配置
    """
    if constraint_slack_dict:
        return SlackConfig(
            enabled=constraint_slack_dict.get("enabled", global_slack.enabled),
            penalty_type=constraint_slack_dict.get("penalty_type", global_slack.penalty_type),
            penalty_weight_symbol=constraint_slack_dict.get(
                "penalty_weight_symbol", global_slack.penalty_weight_symbol
            ),
        )
    return SlackConfig(
        enabled=global_slack.enabled,
        penalty_type=global_slack.penalty_type,
        penalty_weight_symbol=global_slack.penalty_weight_symbol,
    )


def get_slack_variable_name(constraint_name: str) -> str:
    """生成 slack 变量名"""
    return f"s_{constraint_name}"


def get_slack_penalty_name(constraint_name: str) -> str:
    """生成 slack 惩罚项名称"""
    return f"slack_l1_penalty_{constraint_name}"
