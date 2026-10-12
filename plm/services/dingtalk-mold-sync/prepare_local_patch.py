"""Produce a private offline candidate; never edit or restart the live dingtalk_all.

AST guards are based on the read-only inspected three-argument mold task and its
two callback dispatches. Unknown service shapes require manual review instead.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path
import re


def prepare(source: str) -> str:
    if "configure_mold_sync(" in source:
        raise ValueError("This candidate already contains a dual-write hook")
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    task, sender, callback = (functions.get(name) for name in ("task_mould_code_sync", "push_to_erp", "callback"))
    if not task or not sender or not callback or [arg.arg for arg in task.args.args] != ["item_code_raw", "item_name_raw", "notify_users"] or task.args.defaults:
        raise ValueError("Unexpected mold task signature; manual review required")
    calls = [n for n in ast.walk(task) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "push_to_erp"]
    if len(calls) != 1 or len(calls[0].args) != 1 or ast.unparse(calls[0].args[0]) != "payload":
        raise ValueError("Unexpected ERP mold sender seam")
    sender_options = ""
    for keyword in calls[0].keywords:
        if keyword.arg != "label" or not isinstance(keyword.value, ast.Constant) or not isinstance(keyword.value.value, str):
            raise ValueError("Unexpected ERP sender options; preserve manually")
        sender_options = ", label=" + repr(keyword.value.value)
    threads = [n for n in ast.walk(callback) if isinstance(n, ast.Call) and any(k.arg == "target" and isinstance(k.value, ast.Name) and k.value.id == "task_mould_code_sync" for k in n.keywords)]
    if len(threads) != 2 or any(any(k.arg == "kwargs" for k in node.keywords) for node in threads):
        raise ValueError("Expected the two existing callback mold dispatches without kwargs")
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    def position(line, column):
        # Python AST columns are UTF-8 bytes, unlike Python string offsets.
        return offsets[line - 1] + len(lines[line - 1].encode()[:column].decode())
    def bounds(node):
        return position(node.lineno, node.col_offset), position(node.end_lineno, node.end_col_offset)
    edits = []
    signature = re.search(r"def\s+task_mould_code_sync\s*\([^)]*\)\s*:", source[offsets[task.lineno - 1]:])
    if not signature or signature.start() != 0:
        raise ValueError("Unexpected task definition layout")
    start = offsets[task.lineno - 1]
    edits.append((start, start + signature.end(), "def task_mould_code_sync(item_code_raw, item_name_raw, notify_users, event_context=None):"))
    start, end = bounds(calls[0])
    edits.append((start, end, "dual_write_mold(payload, context=event_context)"))
    for thread in threads:
        thread.keywords.append(ast.keyword(arg="kwargs", value=ast.Dict(keys=[ast.Constant("event_context")], values=[ast.Name(id="data", ctx=ast.Load())])))
        start, end = bounds(thread)
        edits.append((start, end, ast.unparse(thread)))
    insert = offsets[sender.end_lineno]
    hook = "\nfrom plm_mold_dual_write import configure_mold_sync, dual_write_mold\nconfigure_mold_sync(lambda payload: push_to_erp(payload" + sender_options + "))\n"
    edits.append((insert, insert, hook))
    for start, end, value in sorted(edits, reverse=True):
        source = source[:start] + value + source[end:]
    ast.parse(source)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not args.output.is_absolute() or args.output.parent.stat().st_mode & 0o077:
        raise ValueError("Output must be an absolute path in a private directory (0700)")
    original = args.source.read_text(encoding="utf-8")
    candidate = prepare(original)
    # Exclusive create and private mode prevent accidental overwrite or disclosure.
    import os
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(candidate)
    print("Private candidate prepared; source unchanged; SHA256=" + hashlib.sha256(candidate.encode()).hexdigest())


if __name__ == "__main__":
    main()
