from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from typing import Any


def get_time() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {"utc": now.isoformat(), "timestamp": now.timestamp()}


def json_validate(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"valid": False, "error": str(exc), "line": exc.lineno, "column": exc.colno}
    return {"valid": True, "type": type(value).__name__}


def format_json(text: str, *, indent: int = 2, sort_keys: bool = False) -> dict[str, Any]:
    value = json.loads(text)
    formatted = json.dumps(value, indent=max(0, min(int(indent), 8)), sort_keys=sort_keys, ensure_ascii=False)
    return {"content": formatted}


def calculate(expression: str) -> dict[str, Any]:
    tree = ast.parse(expression, mode="eval")
    result = eval_math_node(tree.body)
    return {"expression": expression, "result": result}


def eval_math_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = eval_math_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = eval_math_node(node.left)
        right = eval_math_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left**right
    raise ValueError("expression may only contain numeric literals and arithmetic operators")
