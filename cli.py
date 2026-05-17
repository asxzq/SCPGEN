"""
scpgen CLI — SCP/SOCP Code Generator Command-Line Interface.

Usage:
    scpgen compile  <problem.yaml> [-o output_dir]
    scpgen generate <problem.yaml> [-o output_dir]
    scpgen validate <problem.yaml>
    scpgen info     <problem.yaml>
"""

import argparse
import sys
import os
from pathlib import Path

import yaml
from .original_parser import parse_problem, parse_original_problem
from .codegen import CodeGenerator
from .subproblem_compiler import SubproblemCompiler
from .subproblem_models import subproblem_to_dict
from .subproblem_validator import validate_subproblem


def cmd_compile(args):
    """
    Stage 1: Compile original YAML → subproblem.yaml.
    Produces the intermediate subproblem description and a validation report.
    """
    print(f"Stage 1: Compiling '{args.input}' → subproblem.yaml ...")
    problem = parse_original_problem(args.input)

    compiler = SubproblemCompiler(problem)
    subproblem = compiler.compile()

    # Set generated_from
    subproblem.meta.generated_from = str(Path(args.input).resolve())

    # Validate
    report = validate_subproblem(subproblem)
    out_dir = args.output or "output"
    os.makedirs(out_dir, exist_ok=True)

    # Write subproblem.yaml
    sp_dict = subproblem_to_dict(subproblem)
    sp_path = os.path.join(out_dir, f"{problem.meta.name}_subproblem.yaml")
    with open(sp_path, "w", encoding="utf-8") as f:
        yaml.dump(sp_dict, f, default_flow_style=False, allow_unicode=True,
                  sort_keys=False, indent=2, width=120)

    # Write validation report
    report_path = os.path.join(out_dir, "subproblem_validation_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report.to_markdown(subproblem.meta.name))

    print(f"  → {sp_path}")
    print(f"  → {report_path}")
    print(f"  Validation: {'ALL PASSED' if report.all_passed else f'{report.failed_count} FAILED'}")
    if not report.all_passed:
        sys.exit(1)


def cmd_generate(args):
    """Generate C source files from a problem description."""
    model, trans = parse_problem(args.input)
    gen = CodeGenerator(model, trans)

    outputs = gen.run_pipeline()

    out_dir = args.output or "output"
    written = gen.write_outputs(out_dir)

    print(f"Generated {len(written)} file(s) in '{out_dir}':")
    for f in written:
        print(f"  {f}")


def cmd_validate(args):
    """Validate a problem description YAML file."""
    try:
        model, trans = parse_problem(args.input)
        print(f"✓ Valid problem: '{model.name}'")
        print(f"  States:      {len(model.states)} ({', '.join(s.name for s in model.states)})")
        print(f"  Controls:    {len(model.controls)} ({', '.join(c.name for c in model.controls)})")
        print(f"  Nodes (N):   {model.N}")
        print(f"  Dynamics:    {len(model.dynamics)} equations")
        print(f"  Eq cons:     {len(model.eq_constraints)}")
        print(f"  Ineq cons:   {len(model.ineq_constraints)}")
        print(f"  Operations:  {len(trans.operations)}")
        print(f"  Ext funcs:   {len(model.external_funcs)}")
    except Exception as e:
        print(f"✗ Validation failed: {e}")
        sys.exit(1)


def cmd_info(args):
    """Print detailed info about a problem description."""
    model, trans = parse_problem(args.input)

    from .discretizer import IndexMap
    from .symengine import SymContext, generate_symbolic_dynamics_jacobian

    idx = IndexMap(model, trans)
    sym = SymContext(model)

    print(f"Problem: {model.name}")
    print(f"{'='*60}")
    print(idx.summary())
    print()

    # Symbolic dynamics Jacobian dimensions
    jac = generate_symbolic_dynamics_jacobian(sym, 0)
    print(f"Dynamics Jacobian (at symbolic node 0):")
    print(f"  A (∂f/∂x): {jac['A'].rows}×{jac['A'].cols}")
    print(f"  B (∂f/∂u): {jac['B'].rows}×{jac['B'].cols}")
    print()

    print("Transcription operations:")
    for op in trans.operations:
        targets = [e.target.value for e in op.exports]
        print(f"  {op.type:30s} → {', '.join(targets)}")


def main():
    parser = argparse.ArgumentParser(
        description="SCP/SOCP Problem Description → C Code Generator"
    )
    sub = parser.add_subparsers(dest="command")

    # compile (Stage 1: original YAML → subproblem.yaml)
    p_comp = sub.add_parser("compile", help="Compile original YAML → subproblem.yaml (Stage 1)")
    p_comp.add_argument("input", help="Original problem description YAML file")
    p_comp.add_argument("-o", "--output", default="output", help="Output directory")
    p_comp.set_defaults(func=cmd_compile)

    # generate
    p_gen = sub.add_parser("generate", help="Generate C source files")
    p_gen.add_argument("input", help="Problem description YAML file")
    p_gen.add_argument("-o", "--output", default="output", help="Output directory")
    p_gen.set_defaults(func=cmd_generate)

    # validate
    p_val = sub.add_parser("validate", help="Validate a problem YAML file")
    p_val.add_argument("input", help="Problem description YAML file")
    p_val.set_defaults(func=cmd_validate)

    # info
    p_info = sub.add_parser("info", help="Print problem summary")
    p_info.add_argument("input", help="Problem description YAML file")
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
