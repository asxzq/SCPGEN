"""
输入加载器 — 读取 bundle YAML 或直接路径，加载 Module 1/2/3 的输出
并进行 variable_mode 和 symbol_table 一致性校验。
"""

from __future__ import annotations

from typing import Dict, Any, Tuple, List

from scpgen.common.yaml_io import read_yaml
from .models import Module4Input


def load_bundle(bundle_path: str) -> Module4Input:
    """从 bundle YAML 加载所有模块输出。

    支持两种输入格式：

    1. 字符串路径（简洁形式）:
       inputs:
         module1_dynamics: runs/m1.yaml

    2. 字典形式（可显式 enabled）:
       inputs:
         module1_dynamics:
           path: runs/m1.yaml
         module2_equalities:
           enabled: true
           path: runs/m2.yaml
    """
    bundle = read_yaml(bundle_path)

    inputs = bundle.get("inputs", {})
    output_cfg = bundle.get("output", {})

    m1_cfg_raw = inputs.get("module1_dynamics", {})
    m2_cfg_raw = inputs.get("module2_equalities", {})
    m3_cfg_raw = inputs.get("module3_inequalities", {})

    # 归一化：字符串 → enabled=True 的 dict
    m1_cfg = _normalize_bundle_input(m1_cfg_raw, required=True)
    m2_cfg = _normalize_bundle_input(m2_cfg_raw)
    m3_cfg = _normalize_bundle_input(m3_cfg_raw)

    m1_path = m1_cfg["path"]
    m1_output = _read_module_output(m1_path)

    m2_enabled = m2_cfg["enabled"]
    m2_path = m2_cfg["path"]
    m2_output = _read_module_output(m2_path) if (m2_enabled and m2_path) else {}

    m3_enabled = m3_cfg["enabled"]
    m3_path = m3_cfg["path"]
    m3_output = _read_module_output(m3_path) if (m3_enabled and m3_path) else {}

    # 校验
    _validate_variable_mode(m1_output, m2_output, m3_output, m2_enabled, m3_enabled)
    _validate_symbol_table(m1_output, m2_output, m3_output, m2_enabled, m3_enabled)

    return Module4Input(
        problem_name=bundle.get("problem_name", m1_output.get("source_problem", {}).get("problem_name", "unnamed")),
        m1_output=m1_output,
        m2_output=m2_output,
        m3_output=m3_output,
        m2_enabled=m2_enabled,
        m3_enabled=m3_enabled,
        m1_path=m1_path,
        m2_path=m2_path,
        m3_path=m3_path,
        output_path=output_cfg.get("subproblem_ir", "subproblem_ir_module4_output.yaml"),
    )


def load_from_paths(
    m1_path: str,
    m2_path: str = "",
    m2_enabled: bool = True,
    m3_path: str = "",
    m3_enabled: bool = True,
    output_path: str = "subproblem_ir_module4_output.yaml",
) -> Module4Input:
    """从直接文件路径加载所有模块输出"""
    if not m1_path:
        raise ValueError("Module 1 dynamics path is required")

    m1_output = _read_module_output(m1_path)
    m2_output = _read_module_output(m2_path) if (m2_enabled and m2_path) else {}
    m3_output = _read_module_output(m3_path) if (m3_enabled and m3_path) else {}

    # 校验
    _validate_variable_mode(m1_output, m2_output, m3_output, m2_enabled, m3_enabled)
    _validate_symbol_table(m1_output, m2_output, m3_output, m2_enabled, m3_enabled)

    return Module4Input(
        problem_name=m1_output.get("source_problem", {}).get("problem_name", "unnamed"),
        m1_output=m1_output,
        m2_output=m2_output,
        m3_output=m3_output,
        m2_enabled=m2_enabled,
        m3_enabled=m3_enabled,
        m1_path=m1_path,
        m2_path=m2_path,
        m3_path=m3_path,
        output_path=output_path,
    )


def _read_module_output(path: str) -> Dict[str, Any]:
    """读取单个模块输出 YAML"""
    return read_yaml(path)


def _normalize_bundle_input(raw, required: bool = False):
    """归一化 bundle 输入配置。

    输入可以是：
      - 字符串: "path/to/file.yaml" → {"path": "...", "enabled": True}
      - 字典:  {"path": "...", "enabled": true/false}

    返回 {"path": str, "enabled": bool}
    """
    if isinstance(raw, str):
        if required and not raw:
            raise ValueError("Module 1 dynamics path is required in bundle YAML")
        return {"path": raw, "enabled": True}

    if isinstance(raw, dict):
        path = raw.get("path", "")
        if required and not path:
            raise ValueError("Module 1 dynamics path is required in bundle YAML")
        return {"path": path, "enabled": raw.get("enabled", True)}

    # raw 为空字典（默认值）的情况
    if required:
        raise ValueError("Module 1 dynamics path is required in bundle YAML")
    return {"path": "", "enabled": False}


def _validate_variable_mode(
    m1_output: Dict[str, Any],
    m2_output: Dict[str, Any],
    m3_output: Dict[str, Any],
    m2_enabled: bool,
    m3_enabled: bool,
) -> None:
    """检查 variable_mode 一致性。M1 为基准。"""
    m1_mode = m1_output.get("configuration", {}).get("variable_mode", "")
    if not m1_mode:
        raise ValueError("Module 1 output missing variable_mode in configuration")

    if m2_enabled and m2_output:
        m2_mode = m2_output.get("configuration", {}).get("variable_mode", "")
        if m2_mode and m2_mode != m1_mode:
            raise ValueError(
                f"Variable mode mismatch: Module 1 has '{m1_mode}', "
                f"Module 2 has '{m2_mode}'"
            )

    if m3_enabled and m3_output:
        m3_mode = m3_output.get("configuration", {}).get("variable_mode", "")
        if m3_mode and m3_mode != m1_mode:
            raise ValueError(
                f"Variable mode mismatch: Module 1 has '{m1_mode}', "
                f"Module 3 has '{m3_mode}'"
            )


def _validate_symbol_table(
    m1_output: Dict[str, Any],
    m2_output: Dict[str, Any],
    m3_output: Dict[str, Any],
    m2_enabled: bool,
    m3_enabled: bool,
) -> None:
    """检查 symbol_table 中 states/controls/parameters 的一致性"""
    m1_st = m1_output.get("symbol_table", {})

    for label, enabled, output in [
        ("Module 2", m2_enabled, m2_output),
        ("Module 3", m3_enabled, m3_output),
    ]:
        if not enabled or not output:
            continue
        st = output.get("symbol_table", {})
        if not st:
            continue

        _validate_symbol_list(m1_st.get("states", []), st.get("states", []), label, "states")
        _validate_symbol_list(m1_st.get("controls", []), st.get("controls", []), label, "controls")
        _validate_symbol_list(m1_st.get("parameters", []), st.get("parameters", []), label, "parameters")


def _validate_symbol_list(
    m1_list: List[Dict[str, Any]],
    other_list: List[Dict[str, Any]],
    module_label: str,
    category: str,
) -> None:
    """检查 other_list 是否与 m1_list 完全一致。

    states、controls、parameters 都必须与 M1 完全匹配（数量和顺序）。
    不允许 M2/M3 只保留自己用到的参数子集，因为所有模块的输入
    必须来自同一个全局 problem definition。
    """
    # 所有类别都必须完全一致
    if len(m1_list) != len(other_list):
        raise ValueError(
            f"Symbol table mismatch in {module_label}: "
            f"M1 has {len(m1_list)} {category}, {module_label} has {len(other_list)}"
        )
    _check_subset_match(m1_list, other_list, module_label, category, strict=True)


def _check_subset_match(
    m1_list: List[Dict[str, Any]],
    other_list: List[Dict[str, Any]],
    module_label: str,
    category: str,
    strict: bool,
) -> None:
    """检查 other_list 元素是否与 m1_list 中对应元素匹配。

    按 index 匹配，要求所有关键字段完全一致。
    """
    # 按 index 匹配
    m1_by_index = {item.get("index", i): item for i, item in enumerate(m1_list)}
    for i, other_item in enumerate(other_list):
        other_idx = other_item.get("index", i)
        m1_item = m1_by_index.get(other_idx)
        if m1_item is None:
            raise ValueError(
                f"Symbol table mismatch in {module_label} {category}: "
                f"item at index {other_idx} not found in M1"
            )
        _check_item_match(m1_item, other_item, module_label, category, other_idx)


def _check_item_match(
    m1_item: Dict[str, Any],
    other_item: Dict[str, Any],
    module_label: str,
    category: str,
    idx: int,
) -> None:
    """检查两个 symbol item 的关键字段是否匹配"""
    for field in ["original_name", "safe_name", "internal_symbol"]:
        m1_val = m1_item.get(field, "")
        other_val = other_item.get(field, "")
        if m1_val != other_val:
            raise ValueError(
                f"Symbol table mismatch in {module_label} {category}[{idx}]: "
                f"M1 {field} '{m1_val}', {module_label} {field} '{other_val}'"
            )


def merge_symbol_table(
    m1_output: Dict[str, Any],
    m2_output: Dict[str, Any],
    m3_output: Dict[str, Any],
    m2_enabled: bool,
    m3_enabled: bool,
) -> Dict[str, Any]:
    """合并 symbol_table：states/controls/parameters 来自 M1，auxiliaries 为 union"""
    m1_st = m1_output.get("symbol_table", {})

    merged_aux = list(m1_st.get("auxiliaries", []))
    seen_aux = {a.get("safe_name", a.get("original_name", "")) for a in merged_aux}

    for enabled, output in [(m2_enabled, m2_output), (m3_enabled, m3_output)]:
        if not enabled or not output:
            continue
        st = output.get("symbol_table", {})
        for a in st.get("auxiliaries", []):
            key = a.get("safe_name", a.get("original_name", ""))
            if key not in seen_aux:
                merged_aux.append(a)
                seen_aux.add(key)
            else:
                # 检查一致性
                existing = next((x for x in merged_aux if x.get("safe_name", x.get("original_name", "")) == key), None)
                if existing:
                    for field in ["original_name", "function_name", "output_name"]:
                        if existing.get(field) != a.get(field):
                            raise ValueError(
                                f"Auxiliary '{key}' has conflicting '{field}': "
                                f"'{existing.get(field)}' vs '{a.get(field)}'"
                            )

    return {
        "states": m1_st.get("states", []),
        "controls": m1_st.get("controls", []),
        "parameters": m1_st.get("parameters", []),
        "auxiliaries": merged_aux,
    }
