"""SCPGEN CLI 入口"""

import sys
import os
import argparse

from scpgen.common.yaml_io import read_yaml
from scpgen.module1_dynamics.runner import run_module1_from_yaml
from scpgen.module2_equalities.runner import run_module2_from_yaml
from scpgen.module3_inequalities.runner import run_module3_from_yaml
from scpgen.module4_subproblem.runner import run_module4
from scpgen.module5_ecos.runner import run_module5
from scpgen.module5_ecos.input_loader import load_bundle
from scpgen.module6_codegen.runner import run_module6, run_module6_from_bundle
from scpgen.module6_codegen.input_loader import load_bundle as load_m6_bundle


def _resolve_bundle_input_path(raw_path: str, bundle_dir: str) -> str:
    """解析 bundle 中的输入文件路径。

    优先级：
    1. 绝对路径 → 直接使用
    2. 相对路径 → 先尝试相对 bundle 文件所在目录解析
    3. 相对路径 → 再尝试相对当前工作目录解析
    4. 都不存在 → FileNotFoundError 并列出所有尝试过的路径
    """
    if os.path.isabs(raw_path):
        return raw_path

    candidates = []

    # 尝试 1: 相对 bundle 文件所在目录
    p1 = os.path.normpath(os.path.join(bundle_dir, raw_path))
    candidates.append(p1)
    if os.path.exists(p1):
        return p1

    # 尝试 2: 相对当前工作目录
    cwd = os.getcwd()
    p2 = os.path.normpath(os.path.join(cwd, raw_path))
    candidates.append(p2)
    if os.path.exists(p2):
        return p2

    raise FileNotFoundError(
        f"Bundle 中指定的输入文件未找到: {raw_path}\n"
        + "\n".join(f"  尝试路径: {p}" for p in candidates)
    )


def _resolve_bundle_output_path(raw_path: str, bundle_dir: str) -> str:
    """解析 bundle 中的输出文件路径。

    相对路径按当前工作目录解析（输出为写入路径，不存在"未找到"问题）。
    推荐在工程根目录运行时写 runs/module5/... 这种路径。
    """
    if os.path.isabs(raw_path):
        return raw_path
    return os.path.normpath(os.path.join(os.getcwd(), raw_path))


def main():
    parser = argparse.ArgumentParser(
        description='SCPGEN - Sequential Convex Programming C Code Generator'
    )
    sub = parser.add_subparsers(dest='command')

    # module1
    m1 = sub.add_parser('module1', help='Run Module 1: dynamics symbolic transcription')
    m1.add_argument('input', help='Input YAML file')
    m1.add_argument('-o', '--output', default=None, help='Output YAML path')
    m1.add_argument('--simplify', choices=['none', 'basic', 'full'], default='none',
                    help='Simplification level (default: none)')
    m1.add_argument('--write-report', action='store_true', default=False,
                    help='Write performance report (module1_report.yaml)')

    # module2
    m2 = sub.add_parser('module2', help='Run Module 2: equality constraints symbolic transcription')
    m2.add_argument('input', help='Input YAML file')
    m2.add_argument('-o', '--output', default=None, help='Output YAML path')
    m2.add_argument('--simplify', choices=['none', 'basic', 'full'], default='none',
                    help='Simplification level (default: none)')
    m2.add_argument('--write-report', action='store_true', default=False,
                    help='Write performance report')
    m2.add_argument('--output-debug-expressions', action='store_true', default=False,
                    help='Output expanded expressions')

    # module3
    m3 = sub.add_parser('module3', help='Run Module 3: inequality constraints symbolic transcription')
    m3.add_argument('input', help='Input YAML file')
    m3.add_argument('-o', '--output', default=None, help='Output YAML path')
    m3.add_argument('--simplify', choices=['none', 'basic', 'full'], default='none',
                    help='Simplification level (default: none)')
    m3.add_argument('--write-report', action='store_true', default=False,
                    help='Write performance report')
    m3.add_argument('--output-debug-expressions', action='store_true', default=False,
                    help='Output expanded expressions')

    # module4
    m4 = sub.add_parser('module4', help='Run Module 4: subproblem IR assembler')
    m4.add_argument('bundle', nargs='?', default=None, help='Bundle YAML path (optional if --module1 given)')
    m4.add_argument('--module1', default=None, help='Module 1 output YAML path')
    m4.add_argument('--module2', default=None, help='Module 2 output YAML path')
    m4.add_argument('--module3', default=None, help='Module 3 output YAML path')
    m4.add_argument('--no-module2', action='store_true', default=False, help='Disable Module 2')
    m4.add_argument('--no-module3', action='store_true', default=False, help='Disable Module 3')
    m4.add_argument('-o', '--output', default=None, help='Output YAML path')
    m4.add_argument('--write-report', action='store_true', default=False, help='Write debug report')

    # module5
    m5 = sub.add_parser('module5', help='Run Module 5: ECOS canonicalizer')
    m5.add_argument('input', help='Module 4 output YAML path or Module 5 bundle YAML path')
    m5.add_argument('-o', '--output', default=None,
                    help='Output YAML path (required for direct M4 IR, optional for bundle)')
    m5.add_argument('--write-report', action='store_true', default=False, help='Write debug report')

    # module6
    m6 = sub.add_parser('module6', help='Run Module 6: C code generator')
    m6.add_argument('input', help='Module 5 output YAML path or Module 6 bundle YAML path')
    m6.add_argument('-o', '--output', default=None,
                    help='C code output directory (required for direct M5 IR, optional for bundle)')
    m6.add_argument('--write-report', action='store_true', default=False, help='Write debug report')

    args = parser.parse_args()

    if args.command == 'module1':
        run_module1_from_yaml(
            args.input, args.output,
            simplify_level=args.simplify,
            write_report=args.write_report,
        )
    elif args.command == 'module2':
        run_module2_from_yaml(
            args.input, args.output,
            simplify_level=args.simplify,
            write_report=args.write_report,
            output_debug_expressions=args.output_debug_expressions,
        )
    elif args.command == 'module3':
        run_module3_from_yaml(
            args.input, args.output,
            simplify_level=args.simplify,
            write_report=args.write_report,
            output_debug_expressions=args.output_debug_expressions,
        )
    elif args.command == 'module4':
        try:
            m2_enabled = not args.no_module2
            m3_enabled = not args.no_module3
            run_module4(
                bundle_path=args.bundle,
                m1_path=args.module1,
                m2_path=args.module2,
                m2_enabled=m2_enabled,
                m3_path=args.module3,
                m3_enabled=m3_enabled,
                output_path=args.output,
                write_report=args.write_report,
            )
        except (FileNotFoundError, OSError) as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(2)
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(2)
    elif args.command == 'module5':
        try:
            # 检测输入类型：bundle 或直接 Module 4 IR
            input_data = read_yaml(args.input)
            input_dir = os.path.dirname(os.path.abspath(args.input))

            if 'inputs' in input_data and 'module4_subproblem_ir' in input_data.get('inputs', {}):
                # Bundle 格式：包含 inputs.module4_subproblem_ir
                bundle_info = load_bundle(args.input)
                m4_path = bundle_info['module4_path']

                # 解析输入路径：先相对 bundle 目录，再相对 CWD（方案 B）
                m4_path = _resolve_bundle_input_path(m4_path, input_dir)

                # -o 优先于 bundle 中的 output.ecos_canonical_ir
                output_path = args.output or bundle_info.get('output_path', '')
                if output_path and not os.path.isabs(output_path):
                    output_path = _resolve_bundle_output_path(output_path, input_dir)
                if not output_path:
                    print(
                        "错误: Bundle 中未指定 output.ecos_canonical_ir，且未通过 -o 指定输出路径",
                        file=sys.stderr
                    )
                    sys.exit(2)
            else:
                # 直接 Module 4 IR
                m4_path = args.input
                output_path = args.output
                if not output_path:
                    print(
                        "错误: 直接使用 Module 4 IR 作为输入时，-o 是必填的。\n"
                        "用法: python -m scpgen module5 <m4_output> -o <m5_output>",
                        file=sys.stderr
                    )
                    sys.exit(2)

            run_module5(
                input_path=m4_path,
                output_path=output_path,
                write_report=args.write_report,
            )
        except (FileNotFoundError, OSError) as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(2)
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(2)
    elif args.command == 'module6':
        try:
            input_data = read_yaml(args.input)
        except (FileNotFoundError, OSError) as e:
            print(f"错误: 无法读取输入文件 {args.input}: {e}", file=sys.stderr)
            sys.exit(2)
        except Exception as e:
            print(f"错误: 解析输入文件失败 {args.input}: {e}", file=sys.stderr)
            sys.exit(2)

        input_dir = os.path.dirname(os.path.abspath(args.input))

        if 'inputs' in input_data and 'ecos_canonical_ir' in input_data.get('inputs', {}):
            # Bundle 格式
            bundle_info = load_m6_bundle(args.input)
            m5_path = bundle_info['m5_path']
            output_code_dir = args.output or bundle_info.get('output_code_dir', '')
            if output_code_dir and not os.path.isabs(output_code_dir):
                output_code_dir = _resolve_bundle_output_path(output_code_dir, input_dir)
            if not output_code_dir:
                print("错误: Bundle 中未指定 output.code_dir，且未通过 -o 指定输出目录", file=sys.stderr)
                sys.exit(2)
        else:
            # 直接 Module5 IR
            m5_path = args.input
            output_code_dir = args.output
            if not output_code_dir:
                print(
                    "错误: 直接使用 Module5 IR 作为输入时，-o 是必填的。\n"
                    "用法: python -m scpgen module6 <m5_output> -o <code_dir>",
                    file=sys.stderr
                )
                sys.exit(2)

        try:
            result = run_module6(
                input_path=m5_path,
                output_code_dir=output_code_dir,
                write_report=args.write_report,
            )
        except (FileNotFoundError, OSError) as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(2)
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(2)

        print(f"Module6: 生成了 {result['file_count']} 个文件到 {output_code_dir}")
        for f in result['files_generated']:
            print(f"  - {f}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
