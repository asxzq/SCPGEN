"""
LEGACY (pre-Stage1) JSON Schema definitions.

These schemas were used by the original two-layer YAML format
(model + transcription).  Stage 1 uses UNIFIED_ORIGINAL_SCHEMA
exclusively.  These are retained only to support the old parser.py
which may still be referenced by legacy tests.
"""

# ── LEGACY (pre-Stage1): MODEL SCHEMA ──────────────────────────────────────

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


# ── LEGACY (pre-Stage1): TRANSCRIPTION SCHEMA ──────────────────────────────

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
