"""
Module 2 解析器 — 从 input dict 解析 equality_constraints

完成：
- apply_to 归一化
- 表达式解析（3 种写法）
- variable_mode 一致性校验
"""

from __future__ import annotations

from typing import Dict, Any, List

from scpgen.common.apply_to import normalize_apply_to
from scpgen.common.constraint_parser import (
    parse_equality_expressions,
    get_original_expression_form,
)
from scpgen.common.expression_utils import build_safe_symbol_table

from .models import (
    EqualityConstraintDef,
    EqualityTranscriptionConfig,
    Module2InputDef,
)


def parse_equality_constraints(
    input_dict: Dict[str, Any],
) -> Module2InputDef:
    """
    从 input dict 解析所有等式约束。

    Args:
        input_dict: 完整的 problem input dict（含 states, controls, parameters,
                    auxiliaries, mesh, equality_constraints,
                    dynamics_transcription_config,
                    equality_transcription_config 等）

    Returns:
        Module2InputDef
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

    # dynamics variable_mode（默认）
    dyn_cfg = input_dict.get("dynamics_transcription_config", {})
    dynamics_variable_mode = dyn_cfg.get("variable_mode", "perturbation")

    # equality_transcription_config
    eq_cfg_dict = input_dict.get("equality_transcription_config", {})
    eq_config = EqualityTranscriptionConfig(
        variable_mode=eq_cfg_dict.get("variable_mode", None),
    )

    # 校验 variable_mode 一致性
    _validate_variable_mode(dynamics_variable_mode, eq_config)

    # 解析等式约束
    raw_constraints = input_dict.get("equality_constraints", [])
    constraints = []
    for c_dict in raw_constraints:
        c = _parse_single_equality(c_dict, name_to_safe, mesh_N)
        constraints.append(c)

    module_input = Module2InputDef(
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
        config=eq_config,
    )

    errors = module_input.validate()
    if errors:
        raise ValueError("Module 2 输入校验失败:\n  " + "\n  ".join(errors))

    return module_input


def _parse_single_equality(
    c_dict: Dict[str, Any],
    name_to_safe: Dict[str, str],
    mesh_N: int,
) -> EqualityConstraintDef:
    """解析单条等式约束"""
    name = c_dict.get("name", "unnamed_equality")

    # apply_to 归一化
    apply_to_raw = c_dict.get("apply_to")
    apply_to_normalized = normalize_apply_to(apply_to_raw, mesh_N)

    # 表达式解析
    scalar_expressions = parse_equality_expressions(c_dict, name_to_safe)

    # 原始形式
    original_form = get_original_expression_form(c_dict)

    # 对于 equations 形式，保留原始 {lhs: rhs} 映射
    equations_dict = None
    if original_form == "equations":
        eqs = c_dict.get("equations", {})
        if isinstance(eqs, dict):
            equations_dict = dict(eqs)

    return EqualityConstraintDef(
        name=name,
        apply_to_raw=apply_to_raw,
        apply_to_normalized=apply_to_normalized,
        scalar_expressions=scalar_expressions,
        original_form=original_form,
        equations_dict=equations_dict,
    )


def _validate_variable_mode(
    dynamics_mode: str,
    eq_config: EqualityTranscriptionConfig,
) -> None:
    """
    校验 variable_mode 一致性。
    如果 equality_transcription_config 显式写了 variable_mode，
    必须和 dynamics_transcription_config 一致。
    """
    if eq_config.variable_mode is not None:
        if eq_config.variable_mode != dynamics_mode:
            raise ValueError(
                f"variable_mode 不一致: equality_transcription_config 指定为 "
                f"'{eq_config.variable_mode}'，但 dynamics_transcription_config 为 "
                f"'{dynamics_mode}'。两者必须一致。"
            )
