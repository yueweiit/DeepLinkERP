"""一次性修复：为缺失 ``stable_line_key`` 的物料行补生成身份键。

背景：OA 骨架行（import_oa_logistics）此前不写 ``stable_line_key``，工作台按该键
匹配行结构操作（装箱组合并/解除合并、批量软排除，materialRowIsStructurable），
缺键行做不了这些动作；字段写入（项目归属、供应商）按行 name 定位，不受影响。
2026-09-30 起新导入行已带键（见 import_oa_logistics 同日变更），本脚本只补存量。

安全边界（照 repair_* 惯例）：
- 只处理 ``writeback_status == "Not Started"`` 的批次——已尝试回写的批次
  （如 vno4sb614j，writeback_status=Failed）远端行可能已按空键落库，补键会让
  ``custom_overseas_stable_line_key`` 行匹配错位，严禁脚本自动处理；
- 只处理 ``confirm_status == "Pending"`` 且未锁定的当前活动版本行；
- 幂等：只填空键，已有键不动；默认 dry-run，``--apply`` 才写库。

用法（bench 容器内）：
    bench execute overseas_costing.scripts.backfill_stable_line_keys.plan
    bench execute overseas_costing.scripts.backfill_stable_line_keys.apply
"""

from __future__ import annotations

import json

import frappe

from overseas_costing.services.material_input_service import ensure_stable_line_key


def _candidate_batches() -> list[str]:
    return frappe.get_all(
        "Overseas Cost Batch",
        filters={"writeback_status": "Not Started", "confirm_status": "Pending", "is_locked": 0},
        pluck="name",
        order_by="modified desc",
    ) or []


def _empty_key_rows(batch_name: str) -> list[dict]:
    version = frappe.db.get_value("Overseas Cost Batch", batch_name, "current_version")
    if not version:
        return []
    if frappe.db.get_value("Overseas Cost Version", version, "status") != "Active":
        return []
    return frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": batch_name, "version": version, "stable_line_key": ("in", ("", None))},
        fields=["name", "row_no", "material_code"],
        order_by="row_no asc",
        limit_page_length=100000,
    )


def plan() -> dict:
    """只读预检：列出将要补键的批次与行数。"""

    out = []
    for batch_name in _candidate_batches():
        rows = _empty_key_rows(batch_name)
        if rows:
            out.append({"batch": batch_name, "rows": len(rows)})
    summary = {"batches": out, "total_rows": sum(row["rows"] for row in out)}
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def apply() -> dict:
    """补键并写审计日志；仅限预检通过、未被回写/确认/锁定的批次。"""

    fixed = []
    for batch_name in _candidate_batches():
        rows = _empty_key_rows(batch_name)
        if not rows:
            continue
        for row in rows:
            frappe.db.set_value(
                "Overseas Cost Item",
                row["name"],
                "stable_line_key",
                ensure_stable_line_key({}),
                update_modified=False,
            )
        _insert_audit_log(batch_name=batch_name, count=len(rows))
        fixed.append({"batch": batch_name, "rows": len(rows)})
    frappe.db.commit()
    summary = {"batches": fixed, "total_rows": sum(row["rows"] for row in fixed)}
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def _insert_audit_log(*, batch_name: str, count: int) -> None:
    from overseas_costing.scripts.import_oa_logistics import _insert_batch_audit_log

    _insert_batch_audit_log(
        batch_name=batch_name,
        field_name="stable_line_key_backfill",
        old_value={"missing": count},
        new_value={"backfilled": count},
        remark="为 OA 骨架行补生成 stable_line_key，恢复工作台行选择能力",
    )
