from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

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


@pytest.mark.parametrize("label", ["清关税费", "aduana impuesto", "despacho arancel"])
def test_mixed_payment_fee_scopes_require_review(label):
    from overseas_costing.services.logistics_settlement.freight_lines import fee_scope, logical_fee_key
    assert fee_scope(label) == "review"
    assert logical_fee_key(fee_scope(label), "AIR") is None


@pytest.mark.parametrize("title", ["Budget Approval", "Business Travel", "BUY request", "buccaneer"])
def test_bu_fallback_rejects_incidental_letter_sequences(title):
    from overseas_costing.services.logistics_settlement.freight_lines import financial_candidate
    assert financial_candidate({"title": title}, {}) is False


@pytest.mark.parametrize("title", ["TiffanyBU", "NellyBU", "墨西哥BU费用"])
def test_bu_fallback_accepts_registered_business_suffix(title):
    from overseas_costing.services.logistics_settlement.freight_lines import financial_candidate
    assert financial_candidate({"title": title}, {}) is True


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


@pytest.mark.parametrize(
    "title",
    ["采购支出", "费用支出", "运营支出", "付款", "报销", "月结", "TiffanyBU", "NellyBU", "欧洲BU日常支出"],
)
def test_registered_financial_flow_names_do_not_require_logistics_body_keywords(title):
    import sqlite3

    row = _financial("registered-name", title, text="日常费用结算")
    store = Store.sqlite(sqlite3.connect(":memory:"))
    store.install()
    logistics = store.ingest(parse_source(source("registered-logistics", "logistics", text="本票装箱"), logistics_codes={"logistics"}))
    expense = store.ingest(parse_source(row, logistics_codes={"logistics"}))

    assert expense["kind"] == "expense"
    from overseas_costing.services.logistics_settlement.freight_matching import payment_pool
    assert expense["id"] in {item["id"] for item in payment_pool(store, logistics["id"])["sources"]}


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


def test_payment_pool_queries_only_same_corp_expenses_and_installs_compound_index(monkeypatch):
    from overseas_costing.services.logistics_settlement.freight_matching import payment_pool
    import sqlite3
    store = Store.sqlite(sqlite3.connect(":memory:")); store.install()
    logistics = store.ingest(parse_source(source("L", "logistics"), logistics_codes={"logistics"}))
    store.ingest(parse_source(_financial("E", "付款"), logistics_codes={"logistics"}))
    original = store.find
    def observed(table, **filters):
        if table == "source" and filters.get("kind") == "expense":
            assert filters.get("corp") == logistics["corp"]
        return original(table, **filters)
    monkeypatch.setattr(store, "find", observed)
    assert payment_pool(store, logistics["id"])["total"] == 1
    indexed = store.sql("PRAGMA index_info('oc_ls_source_corp_kind')")
    assert [row["name"] for row in indexed] == ["corp", "kind"]


def test_unrelated_payment_does_not_stale_rule_fingerprint():
    from overseas_costing.services.logistics_settlement import freight_matching
    store, _ledger, _batch, _version, _item, logistics, _monthly = setup_cost()
    assert freight_matching.record_rule_pass(store, logistics["id"], "user")["status"] == "completed"
    store.ingest(parse_source(_financial("unrelated", "付款", text="日常办公用品"), logistics_codes={"logistics"}))
    assert freight_matching.rule_status(store, logistics["id"])["status"] == "completed"


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
    assert "pool_snapshot" not in calls[0][1]["content"]
    assert result["response"]["matches"][0]["model"] == "deepseek-test"
    assert result["response"]["matches"][0]["source_revision"] == expense["snapshot"]
    candidate = next(c for c in store.find("freight_candidate") if c["expense_id"] == expense["id"])
    assert candidate["method"] == "deepseek" and candidate["model"] == "deepseek-test"
    assert candidate["confidence"] == "0.91" and candidate["reason"] == "项目和供应商说明一致"
    assert candidate["source_revision"] == expense["snapshot"]
    assert store.count("freight_claim") == 0 and store.count("freight_application") == 0
    assert freight_matching.rule_status(store, logistics["id"])["status"] == "completed"
    assert payment_ai_matching.status(store, logistics["id"], current_version=lambda _batch: version["name"])["status"] == "completed"
    actions={row['action'] for row in store.find('audit',binding_id=batch['name'])}
    assert {'payment_ai_matching_started','payment_ai_matching_completed'} <= actions

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


def test_payment_ai_discards_response_when_active_candidate_changes():
    from overseas_costing.services.logistics_settlement import freight_matching, payment_ai_matching
    store, _ledger, batch, version, _item, logistics, _monthly = setup_cost()
    expense = store.ingest(parse_source(_financial("loose", "付款"), logistics_codes={"logistics"}))
    job = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user")
    def changed_response(_messages):
        freight_matching.save_candidate(store, logistics, expense, [], "manual", "人工先行核对")
        return {"matches": [{"expense_id": expense["id"], "confidence": 1, "reason": "旧 AI", "line_ids": []}]}
    result = payment_ai_matching.run(store, job["id"], changed_response, current_version=lambda _batch: version["name"])
    assert result["status"] == "stale"
    assert store.find("freight_candidate", expense_id=expense["id"])[0]["method"] == "manual"


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


def test_deepseek_rejected_pair_stays_rejected_when_rules_find_new_evidence():
    from overseas_costing.services.logistics_settlement import freight_matching

    store, _ledger, _batch, _version, _item, logistics, expense = setup_cost()
    own_line = next(line for line in freight_matching.current_lines(store, expense) if line["waybill"] == "1234567890")
    candidate = freight_matching.save_candidate(
        store, logistics, expense, [own_line], "deepseek", "AI 先前建议", model="deepseek-test", confidence="0.9"
    )
    store.put("freight_candidate", {"id": candidate["id"], "status": "rejected"})

    assert freight_matching.rule_pass(store, logistics["id"]) == []
    current = store.get("freight_candidate", candidate["id"])
    assert current["status"] == "rejected"
    assert current["method"] == "deepseek"


def test_candidate_authority_and_revision_cas_are_enforced():
    from overseas_costing.services.logistics_settlement import freight_matching
    store, _ledger, _batch, _version, _item, logistics, expense = setup_cost()
    line = freight_matching.current_lines(store, expense)[0]
    ai = freight_matching.save_candidate(store, logistics, expense, [line], "deepseek", "AI")
    manual = freight_matching.save_candidate(store, logistics, expense, [line], "manual", "人工")
    ignored = freight_matching.save_candidate(store, logistics, expense, [], "identifier", "标识", expected_revision=manual["revision"])
    assert manual["method"] == ignored["method"] == "manual"
    with pytest.raises(ValueError, match="变化"):
        freight_matching.save_candidate(store, logistics, expense, [], "manual", "新人工", expected_revision=ai["revision"])


def test_equal_manual_candidate_update_requires_revision_cas():
    from overseas_costing.services.logistics_settlement import freight_matching
    store, _ledger, _batch, _version, _item, logistics, expense = setup_cost()
    first=freight_matching.save_candidate(store,logistics,expense,[],"manual","第一次",expected_revision='')
    with pytest.raises(ValueError,match="版本"):
        freight_matching.save_candidate(store,logistics,expense,[],"manual","第二次")
    updated=freight_matching.save_candidate(store,logistics,expense,[],"manual","第二次",expected_revision=first['revision'])
    assert updated['reason']=='第二次' and updated['revision']!=first['revision']


def test_one_active_payment_ai_job_is_reused_and_timeout_is_persisted(monkeypatch):
    from overseas_costing.services.logistics_settlement import payment_ai_matching
    store, _ledger, batch, version, _item, logistics, _monthly = setup_cost()
    first = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user", hints={"project":"A"})
    second = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user", hints={"project":"B"}, offset=1)
    assert second["id"] == first["id"] and second["enqueue_required"] is False
    stored = store.get("state", first["id"]); stored["started_at"] = (datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat()
    from overseas_costing.services.logistics_settlement.ai_matching import save
    save(store, stored)
    assert payment_ai_matching.status(store, logistics["id"])["status"] == "failed"
    assert store.get("state", first["id"])["status"] == "failed"
    retry = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user")
    assert retry["id"] != first["id"] and retry["status"] == "queued" and retry["enqueue_required"] is True
    assert retry["attempt_nonce"] != first["attempt_nonce"]


def test_timed_out_worker_cannot_revive_or_write_after_retry_starts():
    from overseas_costing.services.logistics_settlement import ai_matching, freight_matching, payment_ai_matching
    store, _ledger, batch, version, _item, logistics, _monthly = setup_cost()
    expense=store.ingest(parse_source(_financial('loose-timeout','付款'),logistics_codes={'logistics'}))
    job=payment_ai_matching.start(store,logistics['id'],batch['name'],version['name'],'user')
    retry_ids=[]
    def delayed(_messages):
        current=store.get('state',job['id']);current['started_at']=(datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat();ai_matching.save(store,current)
        assert payment_ai_matching.status(store,logistics['id'])['status']=='failed'
        retry_ids.append(payment_ai_matching.start(store,logistics['id'],batch['name'],version['name'],'user')['id'])
        return {'matches':[{'expense_id':expense['id'],'confidence':1,'reason':'超时旧结果','line_ids':[]}]}
    payment_ai_matching.run(store,job['id'],delayed,current_version=lambda _batch:version['name'])
    assert retry_ids and retry_ids[0]!=job['id']
    assert store.get('state',job['id'])['status']=='failed'
    assert not [c for c in store.find('freight_candidate',expense_id=expense['id']) if c.get('reason')=='超时旧结果']


@pytest.mark.parametrize("secret", ["12345678901", "GB82WEST12345698765432", "BOFAUS3NXXX"])
def test_sensitive_source_labels_drop_the_entire_value_from_ai_payload(secret):
    from overseas_costing.services.logistics_settlement import payment_ai_matching

    store, _ledger, batch, version, _item, logistics, _monthly = setup_cost()
    row = _financial("sensitive", "付款", text="安全说明")
    row["financial_scope"] = True
    row["raw_payload"]["formComponentValues"].extend([
        {"name": "供应商银行账号", "value": secret},
        {"name": "项目说明", "value": "可公开的项目甲"},
    ])
    row["raw_payload"]["api_token"] = "RAW_PRIVATE_TOKEN"
    row["attachments"] = [{"file_id": "private", "private_url": "https://private.example/secret"}]
    expense = store.ingest(parse_source(row, logistics_codes={"logistics"}))
    job = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user")

    payload = dumps(store.get("state", job["id"])["input"])
    assert expense["id"] in payload and "可公开的项目甲" in payload
    assert secret not in payload
    assert "供应商银行账号" not in payload
    assert "RAW_PRIVATE_TOKEN" not in payload and "private.example" not in payload


@pytest.mark.parametrize("secret", ["6222 0212-3456_7890", "GB82 WEST-1234_5698.7654 32", "BOFA US-3N_XXX", "sk - live - SECRET123"])
def test_sensitive_values_are_removed_even_under_harmless_business_labels(secret):
    from overseas_costing.services.logistics_settlement import payment_ai_matching
    from overseas_costing.services.logistics_settlement.freight_matching import sanitize_hints
    store, _ledger, batch, version, _item, logistics, _monthly = setup_cost()
    row = _financial("hidden-secret", "付款", text="安全说明")
    row["raw_payload"]["formComponentValues"].append({"name":"项目说明", "value":secret})
    store.ingest(parse_source(row, logistics_codes={"logistics"}))
    job = payment_ai_matching.start(store, logistics["id"], batch["name"], version["name"], "user")
    assert secret not in dumps(store.get("state", job["id"])["input"])
    assert sanitize_hints({"description": secret})["description"] == ""


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
    assert public["active_claimed_amount"] == "2600" and public["stale_claimed_amount"] == "0"
    assert public["claim_status"] == "current"


def test_payment_public_view_marks_old_snapshot_and_mixed_currency_claims_for_review():
    from overseas_costing.services.logistics_settlement import freight_matching, freight_runtime
    store, _ledger, _batch, _version, _item, logistics, expense = setup_cost()
    candidate = freight_matching.rule_pass(store, logistics["id"])[0]
    base = {'batch':'B','logistics_id':logistics['id'],'source_id':expense['id'],'line_id':candidate['line_ids'][0]}
    for cid, snapshot, currency, amount in [('old','old-snapshot','RMB','100'),('mixed',expense['snapshot'],'USD','5')]:
        claim={**base,'id':cid,'charge_key':cid,'source_snapshot':snapshot,'currency':currency,'amount':amount}
        store.put('freight_claim',{k:claim[k] for k in ('id','batch','logistics_id','source_id','line_id','charge_key')}|{'data':dumps(claim)})
    public=freight_runtime.candidate_view(store,candidate)
    assert public['active_claimed_amount']=='0'
    assert public['stale_claimed_amount'] is None
    assert public['remaining_amount'] is None and public['claim_status']=='stale_review'


def test_payment_public_view_never_labels_foreign_currency_stale_claim_as_approval_currency():
    from overseas_costing.services.logistics_settlement import freight_matching, freight_runtime
    store, _ledger, _batch, _version, _item, logistics, expense = setup_cost()
    candidate=freight_matching.rule_pass(store,logistics['id'])[0]
    claim={'id':'usd','batch':'B','logistics_id':logistics['id'],'source_id':expense['id'],'line_id':candidate['line_ids'][0],
           'charge_key':'usd','source_snapshot':expense['snapshot'],'currency':'USD','amount':'5'}
    store.put('freight_claim',{k:claim[k] for k in ('id','batch','logistics_id','source_id','line_id','charge_key')}|{'data':dumps(claim)})
    public=freight_runtime.candidate_view(store,candidate)
    assert public['stale_claimed_amount'] is None
    assert public['stale_claimed_by_currency']=={'USD':'5'}
    assert public['remaining_amount'] is None and public['claim_status']=='stale_review'


def test_reopen_payment_candidate_requires_revision_and_allows_regeneration():
    from overseas_costing.services.logistics_settlement import freight_matching, freight_runtime
    store, ledger, batch, _version, _item, logistics, expense = setup_cost()
    candidate=freight_matching.rule_pass(store,logistics['id'])[0]
    candidate.update(status='rejected');store.put('freight_candidate',{k:candidate[k] for k in ('id','logistics_id','expense_id','status')}|{'data':dumps(candidate)})
    with pytest.raises(ValueError,match='原因'):
        freight_runtime.reopen_candidate(store,ledger,batch['name'],candidate['id'],candidate['revision'],'','user')
    with pytest.raises(ValueError,match='变化'):
        freight_runtime.reopen_candidate(store,ledger,batch['name'],candidate['id'],'wrong','重新核对','user')
    reopened=freight_runtime.reopen_candidate(store,ledger,batch['name'],candidate['id'],candidate['revision'],'重新核对','user')
    assert reopened['status']=='reopened' and reopened['revision']!=candidate['revision']
    regenerated=freight_matching.rule_pass(store,logistics['id'])[0]
    assert regenerated['status']=='pending' and regenerated['method'] in {'explicit','identifier'}
    assert store.find('audit',binding_id=batch['name'])[-1]['action']=='payment_candidate_reopened'


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
    duplicate = runtime.start_payment_ai_matching(batch["name"], version["name"], {"project": "不同页"}, offset=1)
    assert duplicate["payment_matching"]["id"] == explicit["payment_matching"]["id"]
    assert len(queued) == 1
    from overseas_costing.services.logistics_settlement import ai_matching, payment_ai_matching
    timed_out=store.get('state',explicit['payment_matching']['id'])
    timed_out['started_at']=(datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat();ai_matching.save(store,timed_out)
    assert payment_ai_matching.status(store,logistics['id'])['status']=='failed'
    retried=runtime.start_payment_ai_matching(batch['name'],version['name'],{'project':'重试'})
    assert retried['payment_matching']['id']!=explicit['payment_matching']['id']
    assert retried['payment_matching']['status']=='queued' and len(queued)==2


def test_rule_runtime_locks_match_state_before_batch(monkeypatch):
    from overseas_costing.services.logistics_settlement import runtime
    store, ledger, batch, version, _item, logistics, _expense = setup_cost();events=[]
    original_store_get=store.get;original_ledger_get=ledger.get
    def store_get(table,key,lock=False):
        if table=='state' and key=='match_lock' and lock:events.append('match_lock')
        return original_store_get(table,key,lock=lock)
    def ledger_get(table,key,lock=False):
        if table=='batch' and lock:events.append('batch_lock')
        return original_ledger_get(table,key,lock=lock)
    monkeypatch.setattr(store,'get',store_get);monkeypatch.setattr(ledger,'get',ledger_get)
    monkeypatch.setattr(runtime,'freight_enabled',lambda:True);monkeypatch.setattr(runtime,'store',lambda:store)
    monkeypatch.setattr(runtime,'FrappeLedger',lambda:ledger);monkeypatch.setattr(runtime,'ensure_batch_source',lambda _db,_batch:logistics)
    monkeypatch.setattr(runtime,'frappe',SimpleNamespace(session=SimpleNamespace(user='user')))
    runtime.run_payment_rule_matching(batch['name'],version['name'])
    assert events.index('match_lock') < events.index('batch_lock')


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
