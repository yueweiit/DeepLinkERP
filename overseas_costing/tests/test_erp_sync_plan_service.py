from overseas_costing.services import erp_sync_plan_service as plans


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


def test_project_route_options_only_include_unambiguous_company_routes(monkeypatch) -> None:
    monkeypatch.setattr(
        plans,
        "_active_routes",
        lambda: [
            {"project_collection": "P1", "subsidiary_code": "COMPANY-1", "erp_site": ""},
            {"project_collection": "P2", "subsidiary_code": "COMPANY-2", "erp_site": "S2"},
            {"project_collection": "P2", "subsidiary_code": "COMPANY-X", "erp_site": "S2"},
        ],
    )

    result = plans.list_project_route_options()

    assert result["options"] == [{"project_collection": "P1", "subsidiary_code": "COMPANY-1", "site_code": "DEEPLINKERP"}]
    assert result["conflicts"] == ["P2"]


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
