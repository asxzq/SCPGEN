"""Module6 输入加载器 — 读取 Module5 输出 YAML 并解析为 Module6IR。"""

from __future__ import annotations

from typing import Dict, Any
from scpgen.common.yaml_io import read_yaml
from scpgen.module6_codegen.models import parse_module5_output, Module6IR


def load_module5_output(path: str) -> Module6IR:
    """加载 Module5 ECOS canonical IR YAML 文件。

    Args:
        path: Module5 输出 YAML 文件路径

    Returns:
        Module6IR 实例

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: YAML 格式无效
    """
    m5_dict = read_yaml(path)
    return parse_module5_output(m5_dict)


def load_bundle(bundle_path: str) -> Dict[str, Any]:
    """加载 Module6 bundle YAML。

    Bundle 格式:
        problem_name: gliding_3dof
        inputs:
          ecos_canonical_ir:
            path: runs/module5/gliding/ecos_canonical_module5_output.yaml
        output:
          code_dir: runs/module6/gliding/generated_c

    Args:
        bundle_path: bundle YAML 文件路径

    Returns:
        包含 m5_path, output_code_dir, problem_name 的 dict
    """
    import os
    bundle = read_yaml(bundle_path)
    bundle_dir = os.path.dirname(os.path.abspath(bundle_path))

    problem_name = bundle.get("problem_name", "")
    inputs = bundle.get("inputs", {})
    ec_input = inputs.get("ecos_canonical_ir", {})

    m5_raw_path = ec_input.get("path", "")
    if os.path.isabs(m5_raw_path):
        m5_path = m5_raw_path
    else:
        # 相对 bundle 目录解析
        m5_path = os.path.normpath(os.path.join(bundle_dir, m5_raw_path))
        if not os.path.exists(m5_path):
            # 回退到 CWD
            m5_path = os.path.normpath(os.path.join(os.getcwd(), m5_raw_path))

    if not os.path.exists(m5_path):
        raise FileNotFoundError(
            f"Bundle 中指定的 Module5 输出文件未找到: {m5_raw_path}\n"
            f"  尝试路径: {m5_path}"
        )

    output = bundle.get("output", {})
    code_dir_raw = output.get("code_dir", "")
    if os.path.isabs(code_dir_raw):
        code_dir = code_dir_raw
    else:
        code_dir = os.path.normpath(os.path.join(os.getcwd(), code_dir_raw))

    return {
        "m5_path": m5_path,
        "output_code_dir": code_dir,
        "problem_name": problem_name,
    }
