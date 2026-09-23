from overseas_costing.services import erp_sync_plan_service as plans
from types import SimpleNamespace


def test_preview_site_sync_plan_blocks_before_reading_routes_when_batch_is_not_confirmed(monkeypatch) -> None:
    monkeypatch.setattr(
        plans.batch_service,
        "check_writeback_ready",
        lambda batch_name, version_name, **kwargs: {
            "ready": False,
            "batch_name": batch_name,
            "version_name": version_name,
            "blocking_reasons": ["当前批次还没有确认。"],
        },
    )
    monkeypatch.setattr(plans, "_active_routes", lambda: (_ for _ in ()).throw(AssertionError("must not read routes")))

    result = plans.preview_site_sync_plan("B1", "V1")

    assert result["ready"] is False
    assert result["blocking"] == [{"code": "WRITEBACK_READINESS_REQUIRED", "message": "当前批次还没有确认。"}]


def test_save_site_sync_plan_only_saves_server_recomputed_ready_plan(monkeypatch) -> None:
    monkeypatch.setattr(
        plans,
        "preview_site_sync_plan",
        lambda *args: {"ready": True, "batch_name": "B1", "version_name": "V1", "request_specs": {"ready": True, "requests": []}},
    )
    from overseas_costing.services import erp_sync_ledger_service

    captured = {}
    monkeypatch.setattr(
        erp_sync_ledger_service,
        "save_sync_request_specs",
        lambda specs, version: captured.update({"specs": specs, "version": version}) or {"ok": True, "requests": []},
    )
    audit = {}
    monkeypatch.setattr(plans, "_insert_plan_audit_log", lambda plan, saved: audit.update({"plan": plan, "saved": saved}))

    result = plans.save_site_sync_plan("B1", "V1", "intent-1")

    assert result["saved"] is True
    assert captured == {"specs": {"ready": True, "requests": []}, "version": "V1"}
    assert audit["saved"]["ok"] is True


def test_save_site_sync_plan_never_calls_ledger_for_blocked_plan(monkeypatch) -> None:
    monkeypatch.setattr(plans, "preview_site_sync_plan", lambda *args: {"ready": False, "blocking": [{"code": "ITEM_ROUTE_REQUIRED"}]})
    from overseas_costing.services import erp_sync_ledger_service

    monkeypatch.setattr(
        erp_sync_ledger_service,
        "save_sync_request_specs",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not save blocked plan")),
    )

    result = plans.save_site_sync_plan("B1", "V1")

    assert result["saved"] is False


def test_get_site_sync_requests_resolves_server_batch_before_listing(monkeypatch) -> None:
    monkeypatch.setattr(
        plans.batch_service,
        "_load_erp_push_context",
        lambda batch, version: {"ok": True, "batch_doc_name": "B-REAL", "version_name": "V-REAL"},
    )
    from overseas_costing.services import erp_sync_ledger_service

    monkeypatch.setattr(
        erp_sync_ledger_service,
        "list_sync_requests",
        lambda batch, version, limit: {"ok": True, "items": [{"batch": batch, "version": version}], "total": 1},
    )

    result = plans.get_site_sync_requests("B-alias", "V-alias", limit=20)

    assert result["batch_name"] == "B-REAL"
    assert result["items"] == [{"batch": "B-REAL", "version": "V-REAL"}]


def test_project_route_options_use_batch_candidates_and_return_revision_token(monkeypatch) -> None:
    monkeypatch.setattr(
        plans,
        "_active_routes",
        lambda: [
            {"project_collection": "P1", "subsidiary_code": "COMPANY-1", "erp_site": "", "revision": 2},
            {"project_collection": "P2", "subsidiary_code": "COMPANY-2", "erp_site": "S2", "revision": 1},
            {"project_collection": "P2", "subsidiary_code": "COMPANY-X", "erp_site": "S2"},
            {"project_collection": "P3", "subsidiary_code": "COMPANY-3", "erp_site": "", "revision": 4, "ai_match_hint": "宠物用品"},
        ],
    )
    seen = []
    monkeypatch.setattr(
        plans,
        "_batch_project_candidate_names",
        lambda batch_name: seen.append(batch_name) or ["P3"],
    )

    result = plans.list_project_route_options("BATCH-1")

    assert seen == ["BATCH-1"]
    assert [row["project_collection"] for row in result["options"]] == ["P3", "P1"]
    assert result["options"][0] == {
        "project_collection": "P3",
        "subsidiary_code": "COMPANY-3",
        "site_code": "DEEPLINKERP",
        "revision": 4,
        "ai_match_hint": "宠物用品",
        "is_approval_candidate": True,
    }
    assert result["options"][1]["is_approval_candidate"] is False
    assert result["conflicts"] == ["P2"]
    assert len(result["route_revision"]) == 64


def test_project_route_revision_changes_with_hint(monkeypatch) -> None:
    route = {
        "project_collection": "LatinGo拉丁购",
        "subsidiary_code": "LATIN",
        "erp_site": "",
        "revision": 3,
        "ai_match_hint": "宠物用品",
    }
    monkeypatch.setattr(plans, "_active_routes", lambda: [dict(route)])
    monkeypatch.setattr(plans, "_batch_project_candidate_names", lambda _batch: ["LatinGo拉丁购"])
    before = plans.list_project_route_options("B1")["route_revision"]
    route["ai_match_hint"] = "宠物用品、户外用品"
    after = plans.list_project_route_options("B1")["route_revision"]

    assert before != after


def test_batch_project_candidates_read_only_current_version_rows(monkeypatch) -> None:
    calls = []

    class DB:
        def get_value(self, doctype, name, fieldname):
            calls.append((doctype, name, fieldname))
            return "VERSION-2"

    def get_all(doctype, **kwargs):
        calls.append((doctype, kwargs["filters"], tuple(kwargs["fields"])))
        return [
            {"extra_json": '{"project_candidates":[{"id":"D1","name":"P2"},{"id":"D2","name":"P1"}]}'},
            {"extra_json": '{"project_candidates":[{"id":"D3","name":"P2"}]}'},
        ]

    monkeypatch.setattr(plans.batch_service, "_resolve_batch_name", lambda name: "BATCH-REAL")
    monkeypatch.setattr(plans, "frappe", SimpleNamespace(db=DB(), get_all=get_all))

    assert plans._batch_project_candidate_names("BATCH-ALIAS") == ["P2", "P1"]
    assert calls[1][1] == {
        "batch": "BATCH-REAL",
        "version": "VERSION-2",
        "is_excluded": 0,
    }


def test_insert_plan_audit_log_records_created_reused_and_sites(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        plans.batch_service,
        "_insert_batch_audit_log",
        lambda **values: captured.update(values),
    )

    plans._insert_plan_audit_log(
        {
            "batch_name": "B1",
            "version_name": "V1",
            "request_specs": {
                "requests": [
                    {"site_code": "DEEPLINKERP"},
                    {"site_code": "MEXICO"},
                ]
            },
        },
        {
            "requests": [
                {"action": "CREATE"},
                {"action": "REUSE"},
            ]
        },
    )

    assert captured["batch_doc_name"] == "B1"
    assert captured["field_name"] == "erp_site_sync_plan"
    assert '"created_count": 1' in captured["new_value"]
    assert '"reused_count": 1' in captured["new_value"]
    assert '"sites": ["DEEPLINKERP", "MEXICO"]' in captured["new_value"]
