from types import SimpleNamespace

import pytest

from overseas_costing.services.logistics_settlement.model import dumps, parse_source
from overseas_costing.services.logistics_settlement.store import Store
from overseas_costing.tests.test_freight_lines import setup_cost
from overseas_costing.tests.test_logistics_settlement import source


def _financial(instance, title, *, corp="C", status="COMPLETED", result="agree", text="DHL 墨西哥 项目甲"):
    row = source(instance, corp=corp)
    row.update(title=title, status=status, result=result)
    row["raw_payload"]["formComponentValues"] = [
        {"name": "付款说明", "value": text},
        {"name": "金额", "value": "100"},
        {"name": "币种", "value": "RMB"},
    ]
    return row


@pytest.mark.parametrize(
    "label,scope,key",
    [
        ("国际空运费", "freight", "international_air_freight"),
        ("进口清关费 aduana", "customs", "customs_clearance_fee"),
        ("关税 arancel", "tax", "import_tax"),
        ("墨西哥末端派送 last mile", "mexico_inland", "destination_delivery"),
        ("DDP 双清包税", "review", None),
        ("服务费", "review", None),
    ],
)
def test_payment_fee_scope_and_logical_key(label, scope, key):
    from overseas_costing.services.logistics_settlement.freight_lines import fee_scope, logical_fee_key

    assert fee_scope(label) == scope
    assert logical_fee_key(scope, "AIR") == key


def test_payment_pool_covers_registered_financial_flows_and_filters_unsafe_sources():
    from overseas_costing.services.logistics_settlement.freight_matching import payment_pool

    import sqlite3

    store = Store.sqlite(sqlite3.connect(":memory:"))
    store.install()
    logistics = store.ingest(parse_source(source("L", "logistics", text="墨西哥 项目甲"), logistics_codes={"logistics"}))
    titles = ["采购支出", "费用支出", "运营支出", "付款", "报销", "月结", "TiffanyBU物流", "NellyBU结算", "欧洲BU费用"]
    expected = []
    for index, title in enumerate(titles):
        parsed = parse_source(_financial(f"E{index}", title), logistics_codes={"logistics"})
        assert parsed["kind"] == "expense"
        expected.append(store.ingest(parsed)["id"])
    # Dynamic upstream registration remains authoritative even when the template name is unfamiliar.
    dynamic = _financial("registered", "完全新的财务流程")
    dynamic["financial_scope"] = True
    expected.append(store.ingest(parse_source(dynamic, logistics_codes={"logistics"}))["id"])
    store.ingest(parse_source(_financial("other", "付款", corp="OTHER"), logistics_codes={"logistics"}))
    store.ingest(parse_source(_financial("pending", "费用支出", status="RUNNING", result=""), logistics_codes={"logistics"}))
    store.ingest(parse_source(_financial("invalid", "报销", status="TERMINATED"), logistics_codes={"logistics"}))

    pool = payment_pool(store, logistics["id"], hints={"project": "项目甲"}, limit=50)

    assert {row["id"] for row in pool["sources"]} == set(expected)
    assert all(row["approved"] and not row["invalid"] and row["corp"] == "C" for row in pool["sources"])


def test_payment_pool_paginates_with_hard_limit_and_sanitizes_hints():
    from overseas_costing.services.logistics_settlement.freight_matching import payment_pool

    import sqlite3

    store = Store.sqlite(sqlite3.connect(":memory:"))
    store.install()
    logistics = store.ingest(parse_source(source("L", "logistics", text="项目甲"), logistics_codes={"logistics"}))
    for index in range(65):
        store.ingest(parse_source(_financial(f"E{index:02}", "付款", text=f"DHL 项目甲 供应商{index:02}"), logistics_codes={"logistics"}))

    first = payment_pool(
        store,
        logistics["id"],
        hints={
            "waybill": "  DHL-123  ",
            "supplier": "银行账号 6222021234567890",
            "project": "项目甲",
            "date": "2026-09-14",
            "description": "access_token=PRIVATE_TOKEN",
            "unknown": "must not escape",
        },
        offset=0,
        limit=999,
    )
    second = payment_pool(store, logistics["id"], hints={"project": "项目甲"}, offset=50, limit=30)

    assert first["limit"] == 50 and len(first["sources"]) == 50 and first["has_more"]
    assert len(second["sources"]) == 15 and not second["has_more"]
    assert first["hints"] == {"waybill": "DHL-123", "supplier": "", "project": "项目甲", "date": "2026-09-14", "description": ""}
    assert not ({row["id"] for row in first["sources"]} & {row["id"] for row in second["sources"]})
    with pytest.raises(ValueError, match="offset"):
        payment_pool(store, logistics["id"], offset=-1)


def test_explicit_payment_ai_job_is_isolated_safe_candidate_only_and_stale_on_version_change():
    from overseas_costing.services.logistics_settlement import payment_ai_matching

    store, ledger, batch, version, _item, logistics, _monthly = setup_cost()
    expense = store.ingest(parse_source(_financial("loose", "付款", text="DHL 墨西哥 项目甲"), logistics_codes={"logistics"}))
    from overseas_costing.services.logistics_settlement import freight_matching
    freight_matching.record_rule_pass(store, logistics["id"], "user")
    hints = {"description": "运输说明", "supplier": "密码 PRIVATE_PASSWORD"}
    job = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user", hints=hints)
    stored = store.get("state", job["id"])
    assert stored["kind"] == "payment_ai" and "PRIVATE_PASSWORD" not in dumps(stored["input"])
    calls = []

    result = payment_ai_matching.run(
        store,
        job["id"],
        lambda messages: calls.append(messages) or {
            "matches": [{"expense_id": expense["id"], "confidence": 0.91, "reason": "项目和供应商说明一致", "line_ids": []}]
        },
        model="deepseek-test",
        current_version=lambda _batch: version["name"],
    )

    assert result["status"] == "completed" and len(calls) == 1
    assert result["response"]["matches"][0]["model"] == "deepseek-test"
    assert result["response"]["matches"][0]["source_revision"] == expense["snapshot"]
    candidate = next(c for c in store.find("freight_candidate") if c["expense_id"] == expense["id"])
    assert candidate["method"] == "deepseek" and candidate["model"] == "deepseek-test"
    assert candidate["confidence"] == "0.91" and candidate["reason"] == "项目和供应商说明一致"
    assert candidate["source_revision"] == expense["snapshot"]
    assert store.count("freight_claim") == 0 and store.count("freight_application") == 0
    assert freight_matching.rule_status(store, logistics["id"])["status"] == "completed"

    stale = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user", hints={"project": "next"}, offset=1)
    stale_result = payment_ai_matching.run(
        store,
        stale["id"],
        lambda _messages: pytest.fail("stale version was sent to DeepSeek"),
        current_version=lambda _batch: "V2",
    )
    assert stale_result["status"] == "stale"


def test_payment_ai_discards_response_when_a_source_changes_during_model_call():
    from overseas_costing.services.logistics_settlement import payment_ai_matching

    store, _ledger, batch, version, _item, logistics, _monthly = setup_cost()
    original = _financial("loose", "付款")
    expense = store.ingest(parse_source(original, logistics_codes={"logistics"}))
    job = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user")

    def changed_response(_messages):
        changed = _financial("loose", "付款", text="DHL 其他项目")
        changed["updated_at"] = "2026-09-14T00:00:00+00:00"
        store.ingest(parse_source(changed, logistics_codes={"logistics"}))
        return {"matches": [{"expense_id": expense["id"], "confidence": 1, "reason": "旧资料", "line_ids": []}]}

    result = payment_ai_matching.run(store, job["id"], changed_response, current_version=lambda _batch: version["name"])

    assert result["status"] == "stale"
    assert not [c for c in store.find("freight_candidate") if c["expense_id"] == expense["id"]]


def test_payment_ai_status_becomes_stale_when_logistics_is_revoked():
    from overseas_costing.services.logistics_settlement import payment_ai_matching

    store, _ledger, batch, version, _item, logistics, _monthly = setup_cost()
    job = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user")
    revoked = source("L", "logistics", text="DHL运单号1234567890")
    revoked.update(status="TERMINATED", updated_at="2026-09-14T00:00:00+00:00")
    store.ingest(parse_source(revoked, logistics_codes={"logistics"}))

    assert payment_ai_matching.status(store, logistics["id"])["status"] == "stale"


def test_rejected_payment_pair_is_not_recommended_again():
    from overseas_costing.services.logistics_settlement import freight_matching, payment_ai_matching

    store, _ledger, batch, version, _item, logistics, _monthly = setup_cost()
    expense = store.ingest(parse_source(_financial("loose", "付款"), logistics_codes={"logistics"}))
    rejected = freight_matching.save_candidate(store, logistics, expense, [], "manual", "人工查找")
    store.put("freight_candidate", {"id": rejected["id"], "status": "rejected"})

    job = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user")
    stored = store.get("state", job["id"])

    assert expense["id"] not in {row["id"] for row in stored["input"]["sources"]}


def test_payment_public_view_is_additive_and_claim_totals_are_real():
    from overseas_costing.services.logistics_settlement import freight_adoption, freight_matching, freight_runtime

    store, ledger, batch, version, _item, logistics, _expense = setup_cost()
    ledger.put("batch", batch["name"], {"transport_mode": "SEA"})
    candidate = freight_matching.rule_pass(store, logistics["id"])[0]
    freight_adoption.confirm(store, ledger, batch["name"], version["name"], candidate["id"], candidate["revision"], candidate["line_ids"], "user")

    result = freight_runtime.batch_status(store, ledger, batch["name"])

    assert [row["id"] for row in result["candidates"]] == [row["id"] for row in result["payment_candidates"]]
    assert result["payment_matching"]["status"] in {"not_started", "completed"}
    public = result["payment_candidates"][0]
    assert public["source_revision"] == public["expense"]["snapshot"]
    assert public["approval_total"] == "9000" and public["approval_currency"] == "RMB"
    assert public["claimed"] == "2600" and public["remaining"] == "6400"
    assert public["lines"][0]["scope"] == "freight"
    assert public["lines"][0]["logical_fee_key"] == "international_sea_freight"


def test_runtime_only_queues_the_explicit_payment_ai_action(monkeypatch):
    from overseas_costing.services import allocation_service
    from overseas_costing.services.logistics_settlement import runtime

    store, ledger, batch, version, _item, logistics, _expense = setup_cost()
    queued = []
    monkeypatch.setattr(runtime, "freight_enabled", lambda: True)
    monkeypatch.setattr(runtime, "store", lambda: store)
    monkeypatch.setattr(runtime, "FrappeLedger", lambda: ledger)
    monkeypatch.setattr(runtime, "ensure_batch_source", lambda _store, _batch: logistics)
    monkeypatch.setattr(runtime, "frappe", SimpleNamespace(session=SimpleNamespace(user="user"), enqueue=lambda method, **kwargs: queued.append((method, kwargs))))
    monkeypatch.setattr(allocation_service, "_call_chat_completions", lambda *_args, **_kwargs: pytest.fail("rule action called DeepSeek"))

    legacy = runtime.start_batch_matching(batch["name"], version["name"])
    direct = runtime.run_payment_rule_matching(batch["name"], version["name"])
    assert legacy["matching"]["status"] == direct["matching"]["status"] == "completed"
    assert queued == []

    explicit = runtime.start_payment_ai_matching(batch["name"], version["name"], {"project": "项目甲"})
    assert explicit["payment_matching"]["kind"] == "payment_ai"
    assert queued == [("overseas_costing.services.logistics_settlement.runtime.run_payment_ai_matching", {
        "queue": "long", "timeout": 600, "payment_ai_job_id": explicit["payment_matching"]["id"], "enqueue_after_commit": True,
    })]


def test_financial_archive_uses_registered_process_scope_not_filenames():
    from overseas_costing.integrations.logistics_settlement_source import SettlementArchive

    statements = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def execute(self, sql, args): statements.append((sql, args))
        def fetchall(self): return []

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def cursor(self): return Cursor()

    archive = SettlementArchive(SimpleNamespace(_connection=lambda: Connection()), logistics_codes={"logistics"}, financial=True)
    archive.page(upper="2026-09-15T00:00:00+00:00")

    sql = statements[0][0]
    assert "costing_read.financial_sources_v1" in sql
    assert "financial_scope" in sql and "filename" not in sql.casefold()
