"""站点级 ERP 待办与状态摘要（计划 Task 8）。

输入是同步请求账本行，取真实字段名（``cost_result_hash`` / ``creation`` / ``status``），
不从别的投影里另造一套别名。
"""

from overseas_costing.services import fee_status_service
from overseas_costing.services.fee_status_service import (
    ERP_WORK_SITE_STATES,
    TODO_DEFINITIONS,
    build_erp_site_state,
    build_erp_work_state,
    summarize_fee_statuses,
)


def _site(site_code: str, **overrides) -> dict:
    row = {
        "site_code": site_code,
        "status": "SUCCESS",
        "cost_result_hash": "H2",
        "creation": "2026-09-28 10:00:00.000000",
    }
    row.update(overrides)
    return row


def _by_site(work: dict) -> dict:
    return {row["site_code"]: row for row in work["sites"]}


def test_current_result_closes_only_successful_site_todo() -> None:
    work = build_erp_work_state(
        current_hash="H2",
        sites=[
            _site("PROD", cost_result_hash="H2"),
            _site("ECOM", cost_result_hash="H1"),
        ],
    )

    by_site = _by_site(work)
    assert by_site["PROD"]["todo"] is None
    assert by_site["PROD"]["state"] == "SYNCED"
    assert by_site["ECOM"]["todo"]["code"] == "ERP_UPDATE_REQUIRED"
    assert by_site["ECOM"]["state"] == "UPDATE_REQUIRED"
    assert by_site["ECOM"]["cost_result_hash"] == "H1"
    assert work["overall"] == "UPDATE_REQUIRED"
    assert work["todo_count"] == 1


def test_late_old_receipt_cannot_close_the_newer_site_todo() -> None:
    """H1 推送失败、很久以后才核对成 SUCCESS，不能把 H2 的待办一起清掉。

    这是账本按 ``creation``（为哪份成本结果开的请求）而不是 ``modified``（什么时候最后动过）
    排序的理由：迟到回执的 modified 最新，拿它当站点状态就等于用旧成本的成功回执关掉新版本。
    """

    work = build_erp_work_state(
        current_hash="H2",
        sites=[
            _site(
                "PROD",
                status="SUCCESS",
                cost_result_hash="H1",
                creation="2026-09-01 09:00:00.000000",
                modified="2026-09-28 23:59:00.000000",
            ),
            _site(
                "PROD",
                status="UNCERTAIN",
                cost_result_hash="H2",
                creation="2026-09-20 09:00:00.000000",
                modified="2026-09-20 09:00:05.000000",
            ),
        ],
    )

    row = _by_site(work)["PROD"]
    assert row["state"] == "ATTENTION_REQUIRED"
    assert row["todo"]["code"] == "ERP_RECONCILE_REQUIRED"
    assert row["status"] == "UNCERTAIN"


def test_fee_todos_and_erp_receipts_do_not_close_each_other() -> None:
    """费用待办与 ERP 回执是两条独立的线：任一侧齐备都不代表另一侧齐备。"""

    fee_summary = summarize_fee_statuses(
        [
            {
                "amount_state": "ACTUAL",
                "currency": "CNY",
                "amount": "100",
                "todos": [{"code": "EVIDENCE_REQUIRED"}],
                "evidence_state": "MISSING",
            }
        ]
    )
    work = build_erp_work_state(current_hash="H2", sites=[_site("PROD", cost_result_hash="H2")])

    # 费用还缺凭证，但 ERP 站点已经同步到位 —— 两边各说各的。
    assert fee_summary["all_requirements_satisfied"] is False
    assert work["todo_count"] == 0
    assert work["overall"] == "SYNCED"
    # 反过来，ERP 待办也不出现在费用汇总里。
    behind = build_erp_work_state(current_hash="H2", sites=[_site("PROD", cost_result_hash="H1")])
    assert behind["todo_count"] == 1
    assert fee_summary["todo_count"] == 1


def test_unknown_current_hash_never_invents_an_update_todo() -> None:
    """拿不到当前结果哈希时只报「推送过没有」，不凭空说站点同步的是旧成本。"""

    work = build_erp_work_state(sites=[_site("PROD", cost_result_hash="H1")])

    assert work["current_cost_result_hash"] == ""
    assert _by_site(work)["PROD"]["state"] == "SYNCED"
    assert work["todo_count"] == 0


def test_site_only_gains_a_sync_todo_when_it_has_never_been_pushed() -> None:
    work = build_erp_work_state(
        current_hash="H2",
        sites=[_site("PROD", cost_result_hash="H2")],
        planned_sites=["PROD", "MXSITE"],
    )

    by_site = _by_site(work)
    assert by_site["MXSITE"]["state"] == "NOT_PUSHED"
    assert by_site["MXSITE"]["todo"]["code"] == "ERP_SYNC_REQUIRED"
    assert by_site["MXSITE"]["todo"]["action"] == "preview_site_sync"
    assert by_site["MXSITE"]["cost_result_hash"] == ""
    assert work["overall"] == "PARTIAL"
    assert work["counts"]["SYNCED"] == 1 and work["counts"]["NOT_PUSHED"] == 1


def test_batch_where_nothing_was_ever_pushed_is_not_started() -> None:
    work = build_erp_work_state(current_hash="H2", planned_sites=["PROD", "ECOM"])

    assert work["overall"] == "NOT_STARTED"
    assert work["counts"]["NOT_PUSHED"] == 2
    assert work["todo_count"] == 2
    assert [row["site_code"] for row in work["sites"]] == ["ECOM", "PROD"]


def test_in_flight_push_is_not_reported_as_a_failure_or_a_todo() -> None:
    assert build_erp_site_state(_site("PROD", status="PENDING")) == ("IN_PROGRESS", "")
    assert build_erp_site_state(_site("PROD", status="RUNNING")) == ("IN_PROGRESS", "")
    work = build_erp_work_state(
        current_hash="H2",
        sites=[_site("PROD", status="RUNNING"), _site("ECOM", cost_result_hash="H2")],
    )
    assert work["overall"] == "IN_PROGRESS"
    assert work["todo_count"] == 0


def test_failed_and_uncertain_sites_ask_for_a_remote_recheck() -> None:
    for status in ("FAILED", "UNCERTAIN"):
        work = build_erp_work_state(current_hash="H2", sites=[_site("PROD", status=status)])

        row = _by_site(work)["PROD"]
        assert row["state"] == "ATTENTION_REQUIRED"
        assert row["todo"]["code"] == "ERP_RECONCILE_REQUIRED"
        assert row["todo"]["action"] == "reconcile_erp"
        assert row["status"] == status
        assert work["counts"]["ATTENTION_REQUIRED"] == 1


def test_failed_and_uncertain_sites_are_counted_once_each() -> None:
    work = build_erp_work_state(
        current_hash="H2",
        sites=[_site("PROD", status="FAILED"), _site("ECOM", status="UNCERTAIN")],
    )

    assert work["counts"]["ATTENTION_REQUIRED"] == 2
    assert work["overall"] == "ATTENTION_REQUIRED"


def test_manual_required_stays_visible_and_asks_for_an_human() -> None:
    work = build_erp_work_state(
        current_hash="H2",
        sites=[
            _site(
                "PROD",
                status="MANUAL_REQUIRED",
                cost_result_hash="H2",
                error_code="AMBIGUOUS_REMOTE_BUSINESS_KEY",
                error_message="稳定业务键在远端命中多张采购单，请人工核对后处理。",
            )
        ],
    )

    row = _by_site(work)["PROD"]
    assert row["state"] == "ATTENTION_REQUIRED"
    assert row["todo"]["code"] == "ERP_MANUAL_REQUIRED"
    assert row["todo"]["severity"] == "error"
    assert work["overall"] == "ATTENTION_REQUIRED"
    assert row["error_code"] == "AMBIGUOUS_REMOTE_BUSINESS_KEY"
    assert "人工核对" in row["error_message"]


def test_superseded_request_counts_as_still_needing_a_push() -> None:
    """被取代的请求没有落地的单据，站点等于还没推。”"""

    work = build_erp_work_state(current_hash="H2", sites=[_site("PROD", status="SUPERSEDED")])

    row = _by_site(work)["PROD"]
    assert row["state"] == "NOT_PUSHED"
    assert row["todo"]["code"] == "ERP_SYNC_REQUIRED"


def test_overall_rollup_prefers_attention_over_everything_else() -> None:
    work = build_erp_work_state(
        current_hash="H2",
        sites=[
            _site("PROD", status="SUCCESS", cost_result_hash="H2"),
            _site("ECOM", status="RUNNING"),
            _site("MXSITE", cost_result_hash="H1"),
            _site("LATAM", status="FAILED"),
        ],
        planned_sites=["PROD", "ECOM", "MXSITE", "LATAM", "NUEVO"],
    )

    assert work["overall"] == "ATTENTION_REQUIRED"
    assert work["counts"] == {
        "SYNCED": 1,
        "UPDATE_REQUIRED": 1,
        "IN_PROGRESS": 1,
        "ATTENTION_REQUIRED": 1,
        "NOT_PUSHED": 1,
    }


def test_empty_batch_reports_empty_instead_of_success() -> None:
    work = build_erp_work_state(current_hash="H2", sites=[])
    assert work["overall"] == "EMPTY"
    assert work["sites"] == [] and work["todo_count"] == 0


def test_every_emitted_todo_code_is_registered() -> None:
    emitted = {
        build_erp_site_state(None)[1],
        build_erp_site_state(_site("P", status="FAILED"))[1],
        build_erp_site_state(_site("P", cost_result_hash="H1"), current_hash="H2")[1],
        build_erp_site_state(_site("P", status="SUPERSEDED"))[1],
    }

    assert "" not in emitted
    assert emitted.issubset(TODO_DEFINITIONS)
    assert set(ERP_WORK_SITE_STATES) == {
        "SYNCED", "UPDATE_REQUIRED", "IN_PROGRESS", "ATTENTION_REQUIRED", "NOT_PUSHED",
    }

    for code in emitted:
        severity, action, label = TODO_DEFINITIONS[code]
        assert severity in {"warning", "error"} and action and label


def test_site_states_only_ever_use_the_declared_vocabulary() -> None:
    """状态词表只有这五个：多一个就是在页面里造第二套语义。"""

    latest_rows = [
        None,
        _site("P", status="PENDING"),
        _site("P", status="RUNNING"),
        _site("P", status="SUCCESS"),
        _site("P", status="SUCCESS", cost_result_hash="H1"),
        _site("P", status="FAILED"),
        _site("P", status="UNCERTAIN"),
        _site("P", status="MANUAL_REQUIRED"),
        _site("P", status="SUPERSEDED"),
        _site("P", status="WHATEVER"),
    ]
    for latest in latest_rows:
        state, _todo_code = build_erp_site_state(latest, current_hash="H2")
        assert state in ERP_WORK_SITE_STATES
        # 认不出的状态不猜成功，落到「需要人工处理」。
        if latest is not None and latest["status"] == "WHATEVER":
            assert state == "ATTENTION_REQUIRED"


def test_rows_without_a_site_code_are_ignored() -> None:
    work = build_erp_work_state(current_hash="H2", sites=[{"status": "SUCCESS"}, {"site_code": "  "}])
    assert work["sites"] == [] and work["overall"] == "EMPTY"


def test_the_projection_is_read_only() -> None:
    """纯函数：不改传入的行，也不碰批次级 writeback 投影。"""

    rows = [_site("PROD", status="FAILED")]
    snapshot = [dict(row) for row in rows]
    build_erp_work_state(current_hash="H2", sites=rows)

    assert rows == snapshot
    assert not hasattr(fee_status_service, "writeback_status")
