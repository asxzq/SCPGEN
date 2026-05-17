"""
JSON Schema definitions for the two-layer YAML problem description.

Layer 1 — model:  原始最优控制问题（变量、参数、动力学、约束、目标）
Layer 2 — transcription: 如何处理原始问题项（离散化、线性化、SOC转换等）
"""

# ── MODEL SCHEMA ───────────────────────────────────────────────────────────

MODEL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["name", "discretization", "variables", "dynamics"],
    "properties": {
        "name": {"type": "string"},

        "discretization": {
            "type": "object",
            "required": ["node_count"],
            "properties": {
                "node_count": {
                    "oneOf": [
                        {"type": "integer", "minimum": 2},
                        {"type": "object", "required": ["param"],
                         "properties": {"param": {"type": "string"}}}
                    ]
                },
                "method": {"type": "string"}
            }
        },

        "scales": {
            "type": "object",
            "description": "量纲级归一化尺度定义",
            "additionalProperties": {
                "oneOf": [
                    {"type": "number"},
                    {"type": "object", "properties": {
                        "value": {"type": "number"},
                        "unit": {"type": "string"},
                        "derive": {"type": "string"}
                    }}
                ]
            }
        },

        "variables": {
            "type": "object",
            "properties": {
                "state":    {"type": "array", "items": {"$ref": "#/$defs/variable"}},
                "control":  {"type": "array", "items": {"$ref": "#/$defs/variable"}},
                "auxiliary": {"type": "array", "items": {"$ref": "#/$defs/variable_aux"}},
            }
        },

        "expressions": {
            "type": "array",
            "items": {"$ref": "#/$defs/expression_def"}
        },

        "parameters": {
            "type": "array",
            "items": {"$ref": "#/$defs/parameter"}
        },

        "external_functions": {
            "type": "array",
            "items": {"$ref": "#/$defs/external_function"}
        },

        "dynamics": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/dynamics_entry"}
        },

        "equality_constraints": {
            "type": "array",
            "items": {"$ref": "#/$defs/constraint"}
        },

        "inequality_constraints": {
            "type": "array",
            "items": {"$ref": "#/$defs/constraint"}
        },

        "objective": {"$ref": "#/$defs/objective"},
    },

    "$defs": {
        "variable": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "pattern": "^[a-zA-Z_][a-zA-Z0-9_]*$"},
                "dimension": {"type": "string"},
                "description": {"type": "string"},
            }
        },
        "variable_aux": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "expr": {"type": "string"},
                "dimension": {"type": "string"},
            }
        },
        "expression_def": {
            "type": "object",
            "required": ["name", "expr"],
            "properties": {
                "name": {"type": "string"},
                "expr": {"type": "string"},
                "description": {"type": "string"},
            }
        },
        "parameter": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "value": {},
                "description": {"type": "string"},
            }
        },
        "external_function": {
            "type": "object",
            "required": ["name", "signature"],
            "properties": {
                "name": {"type": "string"},
                "signature": {"type": "string"},
                "description": {"type": "string"},
            }
        },
        "dynamics_entry": {
            "type": "object",
            "required": ["state", "rhs"],
            "properties": {
                "state": {"type": "string", "description": "对应的状态变量名"},
                "rhs": {"type": "string", "description": "右端函数表达式（归一化空间中）"},
            }
        },
        "constraint": {
            "type": "object",
            "required": ["name", "type"],
            "properties": {
                "name": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["boundary", "box", "path", "waypoint", "custom"]
                },
                # boundary type
                "bindings": {"type": "array", "items": {"$ref": "#/$defs/binding"}},
                # path type
                "expr": {"type": "string"},
                "lower": {"type": "string"},
                "upper": {"type": "string"},
                "nodes": {"type": "array"},
            }
        },
        "binding": {
            "type": "object",
            "required": ["var"],
            "properties": {
                "var": {"type": "string"},
                "node": {"description": "节点索引，0=初始, N=终端, 或整数"},
                "value": {"type": "string"},
                "lower": {"type": "string"},
                "upper": {"type": "string"},
            }
        },
        "objective": {
            "type": "object",
            "required": ["type", "expr"],
            "properties": {
                "type": {"type": "string", "enum": ["minimize", "maximize"]},
                "expr": {"type": "string"},
            }
        },
    }
}


# ── TRANSCRIPTION SCHEMA ────────────────────────────────────────────────────

TRANSCRIPTION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["variable_layout", "operations"],
    "properties": {
        "variable_layout": {
            "type": "object",
            "required": ["ordering", "groups"],
            "properties": {
                "ordering": {
                    "type": "string",
                    "enum": ["by_node", "by_variable"],
                    "description": "by_node: [state@0,ctrl@0, state@1,ctrl@1,...]; by_variable: [rx@0..N, ry@0..N,...]"
                },
                "groups": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/var_group"}
                }
            }
        },

        "operations": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/operation"}
        }
    },

    "$defs": {
        "var_group": {
            "type": "object",
            "required": ["vars", "nodes"],
            "properties": {
                "vars": {"type": "array", "items": {"type": "string"}},
                "nodes": {
                    "type": "array",
                    "minItems": 2, "maxItems": 2,
                    "items": {"description": "起始/结束节点, 可用整数或参数引用"}
                }
            }
        },
        "operation": {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {"type": "string"},
                "export": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["target"],
                        "properties": {
                            "target": {"type": "string", "enum": ["A_b", "G_h", "G_h_q", "c", "Q_c"]}
                        }
                    }
                }
            },
            # 其余属性由各 operation type 自行定义，用 additionalProperties: true 开放
            "additionalProperties": True,
        }
    }
}


# ── UNIFIED ORIGINAL PROBLEM SCHEMA ─────────────────────────────────────────

UNIFIED_ORIGINAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["meta", "grid", "model", "transcription"],
    "properties": {
        "meta": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "version": {"type": "string"},
                "macro_prefix": {"type": "string"},
                "function_prefix": {"type": "string"},
                "scalar_type": {"type": "string"},
                "index_type": {"type": "string"},
            }
        },
        "grid": {
            "type": "object",
            "required": ["N"],
            "properties": {
                "N": {"type": "integer", "minimum": 2},
                "state_grid": {"type": "string", "enum": ["node", "interval"]},
                "control_grid": {"type": "string", "enum": ["node", "interval"]},
                "time": {
                    "type": "object",
                    "required": ["interval_mode"],
                    "properties": {
                        "interval_mode": {
                            "type": "string",
                            "enum": ["fixed_interval", "optimizable_uniform_interval"]
                        },
                        "interval_symbol": {"type": "string"},
                        "perturbation_symbol": {"type": "string"},
                        "total_time": {"type": "string"},
                        "bounds": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2, "maxItems": 2
                        },
                    }
                }
            }
        },
        "scale": {
            "type": "object",
            "description": "Flat scale definitions: dimension_name → numeric_value",
            "additionalProperties": {"type": "number"}
        },
        "model": {
            "type": "object",
            "required": ["variables"],
            "properties": {
                "variables": {
                    "type": "object",
                    "properties": {
                        "states": {
                            "type": "object",
                            "description": "state_name → scale_name",
                            "additionalProperties": {"type": "string"}
                        },
                        "controls": {
                            "type": "object",
                            "description": "control_name → scale_name",
                            "additionalProperties": {"type": "string"}
                        },
                    }
                },
                "parameters": {
                    "type": "object",
                    "description": "parameter_name → scale_name",
                    "additionalProperties": {"type": "string"}
                },
                "expressions": {"type": "array"},
                "dynamics": {"type": "array"},
                "equalities": {"type": "array"},
                "inequalities": {"type": "array"},
                "objective": {"type": "array"},
            }
        },
        "transcription": {
            "type": "object",
            "required": ["discretization_mode", "operations"],
            "properties": {
                "discretization_mode": {
                    "type": "string",
                    "enum": ["perturbation", "direct"]
                },
                "time": {"type": "object"},
                "operations": {"type": "array", "minItems": 1},
            }
        },
        "codegen": {"type": "object"},
    }
}


# ── SUBPROBLEM SCHEMA ───────────────────────────────────────────────────────

SUBPROBLEM_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["meta", "dimensions", "scale_table", "variables", "parameters",
                 "expressions", "dynamics", "time",
                 "equalities", "inequalities", "objective", "validation"],
    "properties": {
        "meta": {
            "type": "object",
            "required": ["name", "version", "generated_from", "discretization_mode"],
            "properties": {
                "name": {"type": "string"},
                "version": {"type": "string"},
                "generated_from": {"type": "string"},
                "discretization_mode": {
                    "type": "string",
                    "enum": ["perturbation", "direct"]
                },
            }
        },
        "dimensions": {
            "type": "object",
            "required": [
                "N", "n_nodes", "final_node", "n_states", "n_controls",
                "vars_per_node", "n_node_variables", "n_extra_variables",
                "nvar", "neq", "nineq", "objective_terms"
            ],
            "properties": {
                "N": {"type": "integer"},
                "n_nodes": {"type": "integer"},
                "final_node": {"type": "integer"},
                "n_states": {"type": "integer"},
                "n_controls": {"type": "integer"},
                "vars_per_node": {"type": "integer"},
                "n_node_variables": {"type": "integer"},
                "n_extra_variables": {"type": "integer"},
                "nvar": {"type": "integer"},
                "neq": {"type": "integer"},
                "nineq": {"type": "integer"},
                "objective_terms": {"type": "integer"},
            }
        },
        "scale_table": {"type": "object"},
        "variables": {
            "type": "object",
            "required": ["node_order", "node_variables", "extra_variables"],
            "properties": {
                "node_order": {
                    "type": "object",
                    "properties": {
                        "states": {"type": "array", "items": {"type": "string"}},
                        "controls": {"type": "array", "items": {"type": "string"}},
                    }
                },
                "node_variables": {"type": "array"},
                "extra_variables": {"type": "array"},
            }
        },
        "parameters": {"type": "object"},
        "expressions": {"type": "array"},
        "dynamics": {"type": "array"},
        "time": {
            "type": "object",
            "required": ["interval_mode", "interval_symbol"],
            "properties": {
                "interval_mode": {"type": "string"},
                "interval_symbol": {"type": "string"},
                "reference_interval_symbol": {"type": "string"},
                "perturbation_variable": {"type": ["string", "null"]},
                "perturbed_interval_expr": {"type": ["string", "null"]},
                "total_time_expr": {"type": "string"},
                "bounds": {"type": "array", "items": {"type": "string"}},
            }
        },
        "equalities": {
            "type": "object",
            "required": ["total_rows", "blocks"],
            "properties": {
                "total_rows": {"type": "integer"},
                "blocks": {"type": "array"},
            }
        },
        "inequalities": {
            "type": "object",
            "required": ["total_rows", "blocks"],
            "properties": {
                "total_rows": {"type": "integer"},
                "blocks": {"type": "array"},
            }
        },
        "objective": {
            "type": "object",
            "required": ["terms"],
            "properties": {
                "terms": {"type": "array"},
            }
        },
        "validation": {
            "type": "object",
            "required": ["row_convention", "required_checks"],
            "properties": {
                "row_convention": {"type": "object"},
                "required_checks": {"type": "array", "items": {"type": "string"}},
            }
        },
    }
}
