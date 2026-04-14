"""AST-based static pattern matcher for detecting lookahead bias in trading strategies (Step 22)."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from enum import Enum


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class Finding:
    pattern: str
    line: int
    col: int
    severity: str
    explanation: str

    def to_dict(self) -> dict:
        return asdict(self)


def scan(code: str) -> list[Finding]:
    tree = ast.parse(code)
    findings: list[Finding] = []
    for checker in _CHECKERS:
        checker(tree, findings)
    findings.sort(key=lambda f: (f.line, f.col))
    return findings


def report(findings: list[Finding]) -> dict:
    return {
        "total_findings": len(findings),
        "findings": [f.to_dict() for f in findings],
        "by_severity": {
            sev.value: [f.to_dict() for f in findings if f.severity == sev.value]
            for sev in Severity
        },
    }


def _check_negative_shift(tree: ast.AST, findings: list[Finding]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "shift"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)) and arg.value < 0:
            findings.append(Finding(
                pattern="negative_shift",
                line=node.lineno,
                col=node.col_offset,
                severity=Severity.HIGH.value,
                explanation=f"shift({arg.value}) accesses future bars — classic lookahead bias.",
            ))
        if isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
            if isinstance(arg.operand, ast.Constant) and isinstance(arg.operand.value, (int, float)) and arg.operand.value > 0:
                findings.append(Finding(
                    pattern="negative_shift",
                    line=node.lineno,
                    col=node.col_offset,
                    severity=Severity.HIGH.value,
                    explanation=f"shift(-{arg.operand.value}) accesses future bars — classic lookahead bias.",
                ))


def _check_negative_indexing(tree: ast.AST, findings: list[Finding]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        sl = node.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, int) and sl.value < 0:
            findings.append(Finding(
                pattern="negative_index",
                line=node.lineno,
                col=node.col_offset,
                severity=Severity.MEDIUM.value,
                explanation=f"Negative index [{sl.value}] may access future bars if applied to a time-series column.",
            ))
        if isinstance(sl, ast.UnaryOp) and isinstance(sl.op, ast.USub):
            if isinstance(sl.operand, ast.Constant) and isinstance(sl.operand.value, (int, float)) and sl.operand.value > 0:
                findings.append(Finding(
                    pattern="negative_index",
                    line=node.lineno,
                    col=node.col_offset,
                    severity=Severity.MEDIUM.value,
                    explanation=f"Negative index [-{sl.operand.value}] may access future bars if applied to a time-series column.",
                ))


_PRICE_COLS = {"close", "high", "low", "open"}


def _check_current_bar_price_in_condition(tree: ast.AST, findings: list[Finding]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Compare, ast.BoolOp)):
            continue
        price_nodes = _find_bare_price_refs(node)
        for pnode, name in price_nodes:
            findings.append(Finding(
                pattern="current_bar_price",
                line=pnode.lineno,
                col=pnode.col_offset,
                severity=Severity.MEDIUM.value,
                explanation=(
                    f"'{name}' used in a condition without .shift() — current-bar price "
                    "is unknown at decision time for entry signals. Verify this is not "
                    "used to decide the current bar's entry."
                ),
            ))


def _find_bare_price_refs(node: ast.AST) -> list:
    results = []
    for child in ast.walk(node):
        if isinstance(child, ast.Subscript):
            sl = child.slice
            col_name = _extract_string_constant(sl)
            if col_name and col_name.lower() in _PRICE_COLS:
                if not _parent_is_shift(child, node):
                    results.append((child, col_name))
        if isinstance(child, ast.Attribute) and child.attr.lower() in _PRICE_COLS:
            if not _parent_is_shift(child, node):
                results.append((child, child.attr))
    return results


def _extract_string_constant(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _parent_is_shift(target: ast.AST, root: ast.AST) -> bool:
    for node in ast.walk(root):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "shift":
                if _node_contains(func.value, target):
                    return True
    return False


def _node_contains(haystack: ast.AST, needle: ast.AST) -> bool:
    if haystack is needle:
        return True
    for child in ast.walk(haystack):
        if child is needle:
            return True
    return False


def _check_unwindowed_normalization(tree: ast.AST, findings: list[Finding]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in ("mean", "std"):
            continue
        if _chain_has_windowing(func.value):
            continue
        findings.append(Finding(
            pattern="unwindowed_normalization",
            line=node.lineno,
            col=node.col_offset,
            severity=Severity.HIGH.value,
            explanation=(
                f".{func.attr}() called without .rolling() or .expanding() — "
                "this computes over the full dataset, leaking future information."
            ),
        ))


def _chain_has_windowing(node: ast.AST) -> bool:
    current = node
    while True:
        if isinstance(current, ast.Call):
            if isinstance(current.func, ast.Attribute):
                if current.func.attr in ("rolling", "expanding"):
                    return True
                current = current.func.value
                continue
        if isinstance(current, ast.Attribute):
            if current.attr in ("rolling", "expanding"):
                return True
            current = current.value
            continue
        break
    return False


def _check_merge_without_date_guard(tree: ast.AST, findings: list[Finding]) -> None:
    _DATE_HINTS = {"date", "datetime", "timestamp", "time", "dt", "trade_date", "bar_time"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_merge = False
        if isinstance(func, ast.Attribute) and func.attr == "merge":
            is_merge = True
        if isinstance(func, ast.Name) and func.id == "merge":
            is_merge = True
        if not is_merge:
            continue
        on_value = None
        for kw in node.keywords:
            if kw.arg == "on":
                on_value = kw.value
                break
        if on_value is not None:
            col_name = _extract_string_constant(on_value)
            if col_name and col_name.lower() in _DATE_HINTS:
                continue
        findings.append(Finding(
            pattern="merge_without_date_guard",
            line=node.lineno,
            col=node.col_offset,
            severity=Severity.MEDIUM.value,
            explanation=(
                "merge() without a date-alignment guard — rows from different time "
                "periods may be joined, leaking future data."
            ),
        ))


def _check_global_fit(tree: ast.AST, findings: list[Finding]) -> None:
    _TRAIN_HINTS = {"train", "x_train", "y_train", "train_x", "train_y", "train_df", "train_data"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "fit"):
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Name) and first_arg.id.lower() in _TRAIN_HINTS:
            continue
        findings.append(Finding(
            pattern="global_fit",
            line=node.lineno,
            col=node.col_offset,
            severity=Severity.HIGH.value,
            explanation=(
                ".fit() called on what appears to be the full dataset — "
                "the model should only be fit on the training split to avoid leakage."
            ),
        ))


_TARGET_NAMES = {"target", "label", "labels", "y_true", "y", "y_pred"}


def _check_target_access_outside_assignment(tree: ast.AST, findings: list[Finding]) -> None:
    assign_targets: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else ([node.target] if node.target else [])
            for t in targets:
                if isinstance(t, ast.Name) and t.id.lower() in _TARGET_NAMES:
                    assign_targets.add(t.id)
                if isinstance(t, ast.Subscript):
                    col = _extract_string_constant(t.slice)
                    if col and col.lower() in _TARGET_NAMES:
                        assign_targets.add(col)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.lower() in _TARGET_NAMES:
            if isinstance(node.ctx, ast.Load) and node.id not in assign_targets:
                findings.append(Finding(
                    pattern="target_access",
                    line=node.lineno,
                    col=node.col_offset,
                    severity=Severity.HIGH.value,
                    explanation=(
                        f"Variable '{node.id}' (target/label) read without a local "
                        "assignment — may be accessing the answer key outside training."
                    ),
                ))


_CHECKERS = [
    _check_negative_shift,
    _check_negative_indexing,
    _check_current_bar_price_in_condition,
    _check_unwindowed_normalization,
    _check_merge_without_date_guard,
    _check_global_fit,
    _check_target_access_outside_assignment,
]
