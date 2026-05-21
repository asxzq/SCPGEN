"""
apply_to 统一归一化

将输入 YAML 中的各种 apply_to 写法归一化为统一格式。
核心原则：initial / terminal 仅作为输入语法糖，解析后立即转为 nodes 集合。
核心 IR 中不保留 initial / terminal 特殊分支。
"""

from __future__ import annotations

from typing import Dict, Any, List, Union


def normalize_apply_to(
    apply_to_raw: Union[str, Dict[str, Any], List[int], None],
    mesh_N: int,
) -> Dict[str, Any]:
    """
    将任意 apply_to 输入归一化为统一格式。

    Args:
        apply_to_raw: 原始 apply_to 值，可以是:
            - 字符串: "initial", "terminal", "all_nodes"
            - dict: {"type": "nodes", "nodes": [0, 5, "N"]}
            - 未提供: None → 默认 all_nodes
        mesh_N: 网格节点总数

    Returns:
        归一化后的 apply_to dict:
        {
            "type": "nodes",
            "nodes_symbolic": [...] | "all_nodes",
            "nodes_concrete": [...] | "all_nodes",
            # 仅 all_nodes:
            "node_range_symbolic": "0:N",
            "node_range_concrete": {"start": 0, "end": <int>, "inclusive": true},
        }
    """
    if apply_to_raw is None:
        return _normalize_all_nodes(mesh_N)

    if isinstance(apply_to_raw, str):
        return _normalize_string(apply_to_raw, mesh_N)

    if isinstance(apply_to_raw, dict):
        return _normalize_dict(apply_to_raw, mesh_N)

    if isinstance(apply_to_raw, list):
        # 直接给节点列表: [0, 5, "N"]
        return _normalize_node_list(apply_to_raw, mesh_N)

    raise ValueError(
        f"不支持的 apply_to 格式: {apply_to_raw!r}。"
        f"支持的格式: 'initial', 'terminal', 'all_nodes', "
        f"{{type: nodes, nodes: [...]}}"
    )


def _normalize_string(label: str, mesh_N: int) -> Dict[str, Any]:
    """处理字符串形式的 apply_to"""
    label_lower = label.lower().strip()

    if label_lower == "initial":
        return {
            "type": "nodes",
            "nodes_symbolic": [0],
            "nodes_concrete": [0],
        }

    if label_lower == "terminal":
        return {
            "type": "nodes",
            "nodes_symbolic": ["N"],
            "nodes_concrete": [mesh_N - 1],
        }

    if label_lower == "all_nodes":
        return _normalize_all_nodes(mesh_N)

    raise ValueError(
        f"不支持的 apply_to 字符串: '{label}'。"
        f"支持的字符串: 'initial', 'terminal', 'all_nodes'"
    )


def _normalize_all_nodes(mesh_N: int) -> Dict[str, Any]:
    """归一化 all_nodes — 紧凑表示，不展开完整 nodes_concrete 列表"""
    return {
        "type": "nodes",
        "nodes_symbolic": "all_nodes",
        "nodes_concrete": "all_nodes",
        "node_range_symbolic": "0:N",
        "node_range_concrete": {
            "start": 0,
            "end": mesh_N - 1,
            "inclusive": True,
        },
    }


def _normalize_dict(d: Dict[str, Any], mesh_N: int) -> Dict[str, Any]:
    """处理 dict 形式的 apply_to"""
    apply_type = d.get("type", "")

    if apply_type == "nodes":
        nodes = d.get("nodes", [])
        return _normalize_node_list(nodes, mesh_N)

    if apply_type == "intervals":
        raise ValueError(
            "Interval constraints are not supported by Module 2/3 MVP. "
            "Only type 'nodes' is supported in this version."
        )

    if apply_type == "all_intervals":
        raise ValueError(
            "Interval constraints are not supported by Module 2/3 MVP. "
            "Only type 'nodes' is supported in this version."
        )

    raise ValueError(
        f"不支持的 apply_to type: '{apply_type}'。"
        f"支持的 type: 'nodes'"
    )


def _normalize_node_list(
    nodes: List[Union[int, str]],
    mesh_N: int,
) -> Dict[str, Any]:
    """归一化节点列表，将 symbolic 索引（如 "N"）转为 concrete 索引"""
    if not nodes:
        raise ValueError("apply_to nodes 列表不能为空")

    symbolic: List[Union[int, str]] = []
    concrete: List[int] = []

    for n in nodes:
        if isinstance(n, int):
            _validate_concrete_node(n, mesh_N)
            symbolic.append(n)
            concrete.append(n)
        elif isinstance(n, str):
            n_clean = n.strip()
            symbolic.append(n_clean)
            resolved = _resolve_symbolic_node(n_clean, mesh_N)
            _validate_concrete_node(resolved, mesh_N)
            concrete.append(resolved)
        else:
            raise ValueError(f"无效的节点索引: {n!r}")

    return {
        "type": "nodes",
        "nodes_symbolic": symbolic,
        "nodes_concrete": concrete,
    }


def _validate_concrete_node(node: int, mesh_N: int) -> None:
    """校验 concrete 节点索引在有效范围内"""
    if node < 0:
        raise ValueError(
            f"节点索引 {node} 为负数，暂不支持。"
            f"请使用 0..{mesh_N - 1} 范围内的非负整数，"
            f"或符号 'N' (末节点, ={mesh_N - 1})。"
        )
    if node >= mesh_N:
        raise ValueError(
            f"节点索引 {node} 超出范围 [0, {mesh_N - 1}]。"
            f"mesh.N = {mesh_N}，有效范围是 0..{mesh_N - 1}。"
        )


def _resolve_symbolic_node(sym: str, mesh_N: int) -> int:
    """将 symbolic 节点索引转为 concrete 整数"""
    sym_lower = sym.lower().strip()

    if sym_lower == "n":
        return mesh_N - 1
    if sym_lower == "n_minus_1":
        return mesh_N - 1

    # 尝试作为整数解析
    try:
        return int(sym)
    except ValueError:
        pass

    raise ValueError(
        f"无法解析 symbolic 节点索引: '{sym}'。"
        f"支持的值: 整数, 'N' (末节点, =N-1), 'N_minus_1'"
    )


def get_apply_to_summary(normalized: Dict[str, Any]) -> Dict[str, Any]:
    """
    生成 apply_to 的可读摘要，用于输出 YAML。
    提取关键字段，去除冗余。
    """
    return {
        "type": normalized["type"],
        "nodes_symbolic": normalized["nodes_symbolic"],
    }
