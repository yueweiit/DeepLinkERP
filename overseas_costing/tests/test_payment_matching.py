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


def _payment_ai_material_scope_context(*, include_own=True):
    from overseas_costing.tests.test_payment_adoption import payment_setup

    context = payment_setup(structured=True, scope="freight", amount="3414.19", mode="EXPRESS")
    store, _ledger, _batch, _version, logistics, source, _candidate = context
    logistics.update(
        identifiers=[("material", "MWV101144")],
        goods=[{"material_code": "MWV101144", "product_name": "薇武士 IP17 PRO"}],
    )
    store.put("source", {"id": logistics["id"], "data": dumps(logistics)})
    first = store.get("freight_line", "payment-line-1")
    first.update(
        waybill="", approval_no="",
        cargo_text=("MWV101144 薇武士 IP17 PRO" if include_own
                    else "ABC999 薇武士 IP17 PRO"),
        packing={"material_code_hints": ["MWV101144" if include_own else "ABC999"]},
    )
    store.put("freight_line", {
        "id": first["id"], "waybill": "", "approval_no": "", "data": dumps(first),
    })
    if include_own:
        unrelated = {
            **first,
            "id": "payment-line-2",
            "line_key": "line-key-2",
            "charge_key": "economic-charge-2",
            "cargo_text": "ABC999 薇武士 IP17 PRO",
            "packing": {"material_code_hints": ["ABC999"]},
        }
        store.insert("freight_line", {
            "id": unrelated["id"], "source_id": source["id"], "snapshot": source["snapshot"],
            "line_key": unrelated["line_key"], "waybill": "", "approval_no": "",
            "charge_key": unrelated["charge_key"], "data": dumps(unrelated),
        })
    store.sql("DELETE FROM oc_ls_freight_candidate WHERE logistics_id=%s", (logistics["id"],))
    return context


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


@pytest.mark.parametrize("title", ["Budget Approval", "Business Travel", "BUY request", "buccaneer", "Malibu", "Cebu", "Caribu", "Zebu"])
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


def test_payment_pool_materializes_only_requested_page_across_thousand_sources(monkeypatch):
    from overseas_costing.services.logistics_settlement.freight_matching import payment_pool, payment_pool_fresh
    from overseas_costing.services.logistics_settlement.model import digest
    import sqlite3
    store=Store.sqlite(sqlite3.connect(':memory:'));store.install()
    logistics=store.ingest(parse_source(source('large-pool','logistics'),logistics_codes={'logistics'}))
    expense_ids=set();candidate_ids=set()
    for index in range(1005):
        sid=digest('bulk-expense',index);snapshot=digest('bulk-snapshot',index)
        expense_ids.add(sid)
        data={'id':sid,'corp':'C','instance':f'E{index:04}','kind':'expense','snapshot':snapshot,'approved':True,'invalid':False,
              'title':'付款','fields':{'项目说明':f'P{index:04}'},'identifiers':[],'status':'COMPLETED','amount':'1','currency':'RMB'}
        store.insert('source',{'id':sid,'corp':'C','instance':data['instance'],'kind':'expense','snapshot':snapshot,
                     'match_hash':snapshot,'updated_at':'2026-01-01','data':dumps(data)})
        cid=digest('bulk-candidate',index);candidate_ids.add(cid)
        candidate={'id':cid,'logistics_id':logistics['id'],'expense_id':sid,'status':'pending','revision':digest(cid,'r'),'method':'identifier'}
        store.insert('freight_candidate',{'id':cid,'logistics_id':logistics['id'],'expense_id':sid,'status':'pending','data':dumps(candidate)})
    unpacked=[];original=store.unpack
    monkeypatch.setattr(store,'unpack',lambda row:unpacked.append(row['id']) or original(row))
    page=payment_pool(store,logistics['id'],hints={'project':'P0999'},offset=100,limit=17)
    assert page['total']==1005 and len(page['sources'])==17 and page['has_more']
    assert len([sid for sid in unpacked if sid in expense_ids])<=17
    assert len([sid for sid in unpacked if sid in candidate_ids])<=17
    unpacked.clear()
    assert payment_pool_fresh(store,logistics['id'],page['pool_snapshot'])
    assert len([sid for sid in unpacked if sid in expense_ids])<=17
    assert len([sid for sid in unpacked if sid in candidate_ids])<=17
    seen=[]
    for offset in range(0,1005,50):
        seen.extend(row['id'] for row in payment_pool(store,logistics['id'],offset=offset,limit=50)['sources'])
    assert len(seen)==len(set(seen))==1005


def test_sql_page_ranking_normalizes_hint_separators_before_limit():
    from overseas_costing.services.logistics_settlement.freight_matching import payment_pool
    import sqlite3
    store=Store.sqlite(sqlite3.connect(':memory:'));store.install()
    logistics=store.ingest(parse_source(source('ranked-pool','logistics'),logistics_codes={'logistics'}))
    for index in range(60):
        sid=f'{index:064x}';snapshot=f'{index+100:064x}'
        data={'id':sid,'corp':'C','instance':f'low-{index}','kind':'expense','snapshot':snapshot,'approved':True,'invalid':False,
              'title':'付款','fields':{'项目说明':'unrelated'},'identifiers':[],'status':'COMPLETED'}
        store.insert('source',{'id':sid,'corp':'C','instance':data['instance'],'kind':'expense','snapshot':snapshot,
                     'match_hash':snapshot,'updated_at':'2026-01-01','data':dumps(data)})
    high_id='f'*64;high={**data,'id':high_id,'instance':'high','snapshot':'e'*64,'fields':{'项目说明':'DHL 123'}}
    store.insert('source',{'id':high_id,'corp':'C','instance':'high','kind':'expense','snapshot':high['snapshot'],
                 'match_hash':high['snapshot'],'updated_at':'2026-01-01','data':dumps(high)})
    page=payment_pool(store,logistics['id'],hints={'waybill':'DHL-123'},limit=5)
    assert page['sources'][0]['id']==high_id


def test_sql_page_ranking_does_not_truncate_exact_reference_sources():
    from overseas_costing.services.logistics_settlement.freight_matching import _rule_source_ids, payment_pool
    from overseas_costing.services.logistics_settlement.model import digest
    import sqlite3
    store=Store.sqlite(sqlite3.connect(':memory:'));store.install()
    logistics=store.ingest(parse_source(source('many-exact','logistics'),logistics_codes={'logistics'}))
    for index in range(101):
        sid=digest('exact-expense',index);snapshot=digest('exact-snapshot',index)
        data={'id':sid,'corp':'C','instance':f'exact-{index}','kind':'expense','snapshot':snapshot,'approved':True,'invalid':False,
              'title':'付款','fields':{},'identifiers':[],'related':[logistics['instance']],'status':'COMPLETED'}
        store.insert('source',{'id':sid,'corp':'C','instance':data['instance'],'kind':'expense','snapshot':snapshot,
                     'match_hash':snapshot,'updated_at':'2020-01-01','data':dumps(data)})
        store.insert('reference',{'id':digest('exact-reference',index),'source_id':sid,'corp':'C',
                     'target_instance':logistics['instance'],'data':'{}'})
    # Reproduce the former arbitrary list(set)[:100] boundary: the omitted exact
    # source should rank first by recency among equally authoritative references.
    omitted=list(_rule_source_ids(store,logistics))[100]
    store.sql("UPDATE oc_ls_source SET updated_at='2030-01-01' WHERE id=%s",(omitted,))

    page=payment_pool(store,logistics['id'],limit=50)

    assert page['sources'][0]['id']==omitted


def test_rule_source_ids_exclude_the_logistics_source_itself():
    from overseas_costing.services.logistics_settlement.freight_matching import _rule_source_ids
    import sqlite3
    store=Store.sqlite(sqlite3.connect(':memory:'));store.install()
    logistics=store.ingest(parse_source(source('self-reference-boundary','logistics'),logistics_codes={'logistics'}))

    source_ids=_rule_source_ids(store,logistics)

    assert logistics['id'] not in source_ids


def test_explicit_reference_ranks_above_ordinary_shared_identifier_with_matching_public_score():
    from overseas_costing.services.logistics_settlement.freight_matching import payment_pool
    from overseas_costing.services.logistics_settlement.model import digest
    import sqlite3
    store=Store.sqlite(sqlite3.connect(':memory:'));store.install()
    parsed_logistics=parse_source(source('ranking-authority','logistics'),logistics_codes={'logistics'})
    parsed_logistics['identifiers']=[('material','SKU12345')]
    logistics=store.ingest(parsed_logistics)
    weak_parsed=parse_source(_financial('weak-shared','付款',text='日常结算'),logistics_codes={'logistics'})
    weak_parsed['identifiers']=[('material','SKU12345')]
    weak=store.ingest(weak_parsed)
    explicit=store.ingest(parse_source(_financial('explicit-reference','付款',text='日常结算'),logistics_codes={'logistics'}))
    store.insert('reference',{'id':digest('ranking-reference'),'source_id':explicit['id'],'corp':'C',
                 'target_instance':logistics['instance'],'data':'{}'})

    page=payment_pool(store,logistics['id'],limit=2)

    assert [row['id'] for row in page['sources']]==[explicit['id'],weak['id']]
    assert [row['local_match_score'] for row in page['sources']]==[3000,1000]


def test_identifierless_payment_rows_require_unique_current_logistics_material_match():
    from overseas_costing.services.logistics_settlement.freight_matching import _shipment_material_lines

    logistics = {
        'goods': [{'material_code': 'MWV101144', 'product_name': '薇武士 IP17 PRO'}],
        'identifiers': [('material', 'MWV101144')],
    }
    own = {
        'id': 'OWN', 'waybill': '', 'approval_no': '',
        'cargo_text': 'MWV101144 IP17PRO TPU',
        'packing': {'material_code_hints': ['MWV101144']},
    }
    sibling = {
        'id': 'SIBLING', 'waybill': '', 'approval_no': '',
        'cargo_text': 'MWV101145 IP17 PRO MAX TPU',
        'packing': {'material_code_hints': ['MWV101145']},
    }

    assert [row['id'] for row in _shipment_material_lines(logistics, [own, sibling])] == ['OWN']

    ambiguous = {**own, 'id': 'OWN-2'}
    assert _shipment_material_lines(logistics, [own, ambiguous]) == []

    name_only = {
        'id': 'NAME', 'waybill': '', 'approval_no': '',
        'cargo_text': '薇武士 IP17 PRO 手机壳', 'packing': {'material_code_hints': []},
    }
    assert _shipment_material_lines(logistics, [name_only, sibling]) == [name_only]

    foreign_code_same_name = {
        'id': 'FOREIGN-CODE', 'waybill': '', 'approval_no': '',
        'cargo_text': 'ABC999 薇武士 IP17 PRO 手机壳',
        'packing': {'material_code_hints': ['ABC999']},
    }
    assert _shipment_material_lines(logistics, [foreign_code_same_name]) == []

    short_name_logistics = {
        'goods': [{'material_code': '', 'product_name': 'PRO'}],
        'identifiers': [],
    }
    sibling_variant = {
        'id': 'PRO-MAX', 'waybill': '', 'approval_no': '',
        'cargo_text': 'IP17 PRO MAX 手机壳', 'packing': {'material_code_hints': []},
    }
    assert _shipment_material_lines(short_name_logistics, [sibling_variant]) == []

    full_name_logistics = {
        'goods': [{'material_code': '', 'product_name': '薇武士 IP17 PRO'}],
        'identifiers': [],
    }
    assert _shipment_material_lines(full_name_logistics, [name_only]) == [name_only]


def test_stale_freight_line_snapshot_is_not_an_exact_source_or_payment_score():
    from overseas_costing.services.logistics_settlement import freight_matching
    from overseas_costing.tests.test_freight_lines import monthly
    import sqlite3
    store=Store.sqlite(sqlite3.connect(':memory:'));store.install()
    old_logistics=store.ingest(parse_source(source('old-waybill','logistics',text='DHL运单号1234567890'),logistics_codes={'logistics'}))
    new_logistics=store.ingest(parse_source(source('new-waybill','logistics',text='DHL运单号1234567892'),logistics_codes={'logistics'}))
    raw=monthly()
    first=store.ingest(parse_source(raw,logistics_codes={'logistics'}))
    raw['settlement_documents'][0]['freight_tables'][0]['rows'][0]['fields']['运单号']='1234567892'
    raw['updated_at']='2026-09-16T00:00:00+00:00'
    current=store.ingest(parse_source(raw,logistics_codes={'logistics'}))
    assert first['snapshot']!=current['snapshot']
    unrelated_raw=_financial('newer-unrelated','付款',text='办公用品')
    unrelated_raw['updated_at']='2026-09-17T00:00:00+00:00'
    unrelated=store.ingest(parse_source(unrelated_raw,logistics_codes={'logistics'}))

    old_sources=freight_matching.payment_pool(store,old_logistics['id'],limit=2)['sources']
    old_page=next(row for row in old_sources if row['id']==current['id'])
    new_page=freight_matching.payment_pool(store,new_logistics['id'],limit=1)['sources'][0]

    assert old_sources[0]['id']==unrelated['id']
    assert old_page['local_match_score']==0
    assert 'exact' not in ' '.join(old_page['local_match_reasons']).lower()
    assert current['id'] not in freight_matching._rule_source_ids(store,old_logistics)
    assert freight_matching.rule_pass(store,old_logistics['id'])==[]
    assert new_page['local_match_score']>=3000
    assert current['id'] in freight_matching._rule_source_ids(store,new_logistics)
    assert freight_matching.rule_pass(store,new_logistics['id'])[0]['expense_id']==current['id']


def test_unrelated_payment_does_not_stale_rule_fingerprint():
    from overseas_costing.services.logistics_settlement import freight_matching
    store, _ledger, _batch, _version, _item, logistics, _monthly = setup_cost()
    assert freight_matching.record_rule_pass(store, logistics["id"], "user")["status"] == "completed"
    store.ingest(parse_source(_financial("unrelated", "付款", text="日常办公用品"), logistics_codes={"logistics"}))
    assert freight_matching.rule_status(store, logistics["id"])["status"] == "completed"


def test_explicit_payment_ai_job_is_isolated_safe_candidate_only_and_stale_on_version_change():
    from overseas_costing.services.logistics_settlement import payment_ai_matching

    store, _ledger, batch, version, _logistics, expense, _candidate = (
        _payment_ai_material_scope_context()
    )
    hints = {"description": "运输说明", "supplier": "密码 PRIVATE_PASSWORD"}
    job = payment_ai_matching.start(store, "logistics-1", batch["name"], version["name"], "user", hints=hints)
    stored = store.get("state", job["id"])
    assert stored["kind"] == "payment_ai" and "PRIVATE_PASSWORD" not in dumps(stored["input"])
    calls = []

    result = payment_ai_matching.run(
        store,
        job["id"],
        lambda messages: calls.append(messages) or {
            "matches": [{"expense_id": expense["id"], "confidence": 0.91, "reason": "项目和供应商说明一致", "line_ids": ["payment-line-1"]}]
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
    assert payment_ai_matching.status(store, "logistics-1", current_version=lambda _batch: version["name"])["status"] == "completed"
    actions={row['action'] for row in store.find('audit',binding_id=batch['name'])}
    assert {'payment_ai_matching_started','payment_ai_matching_completed'} <= actions

    stale = payment_ai_matching.start(store, "logistics-1", batch["name"], version["name"], "user", hints={"project": "next"})
    stale_result = payment_ai_matching.run(
        store,
        stale["id"],
        lambda _messages: pytest.fail("stale version was sent to DeepSeek"),
        current_version=lambda _batch: "V2",
    )
    assert stale_result["status"] == "stale"


def test_payment_ai_rejects_unrelated_identifierless_line_outside_shipment_scope():
    from overseas_costing.services.logistics_settlement import payment_ai_matching

    store, _ledger, batch, version, _logistics, source, _candidate = (
        _payment_ai_material_scope_context()
    )
    job = payment_ai_matching.start(
        store, "logistics-1", batch["name"], version["name"], "user"
    )
    prepared = store.get("state", job["id"])["input"]["sources"]
    scoped = next(row for row in prepared if row["id"] == source["id"])
    assert [line["id"] for line in scoped["lines"]] == ["payment-line-1"]

    result = payment_ai_matching.run(
        store,
        job["id"],
        lambda _messages: {"matches": [{
            "expense_id": source["id"], "confidence": 1,
            "reason": "试图选择兄弟票物料", "line_ids": ["payment-line-2"],
        }]},
        current_version=lambda _batch: version["name"],
    )

    assert result["status"] == "partial" and result["failed"] == 1
    assert not store.find("freight_candidate", expense_id=source["id"])


def test_payment_ai_can_save_the_unique_authorized_identifierless_material_line():
    from overseas_costing.services.logistics_settlement import payment_ai_matching

    store, _ledger, batch, version, _logistics, source, _candidate = (
        _payment_ai_material_scope_context()
    )
    job = payment_ai_matching.start(
        store, "logistics-1", batch["name"], version["name"], "user"
    )
    result = payment_ai_matching.run(
        store,
        job["id"],
        lambda _messages: {"matches": [{
            "expense_id": source["id"], "confidence": 1,
            "reason": "当前物料号唯一命中", "line_ids": ["payment-line-1"],
        }]},
        current_version=lambda _batch: version["name"],
    )

    saved = store.find("freight_candidate", expense_id=source["id"])[0]
    assert result["status"] == "completed" and result["recommended"] == 1
    assert saved["line_ids"] == ["payment-line-1"]


def test_payment_ai_high_confidence_empty_line_selection_is_not_recommended():
    from overseas_costing.services.logistics_settlement import payment_ai_matching

    store, _ledger, batch, version, logistics, source, _candidate = (
        _payment_ai_material_scope_context()
    )
    job = payment_ai_matching.start(
        store, logistics["id"], batch["name"], version["name"], "user"
    )

    result = payment_ai_matching.run(
        store,
        job["id"],
        lambda _messages: {"matches": [{
            "expense_id": source["id"], "confidence": 1,
            "reason": "只判断流程相关但未选明细", "line_ids": [],
        }]},
        current_version=lambda _batch: version["name"],
    )

    assert result["recommended"] == 0
    assert not store.find("freight_candidate", expense_id=source["id"])


def test_payment_ai_has_no_work_when_source_has_no_shipment_scoped_lines():
    from overseas_costing.services.logistics_settlement import payment_ai_matching

    store, _ledger, batch, version, logistics, _source, _candidate = (
        _payment_ai_material_scope_context(include_own=False)
    )

    result = payment_ai_matching.start(
        store, logistics["id"], batch["name"], version["name"], "user"
    )

    assert result["status"] == "no_work"
    assert not store.find("freight_candidate", logistics_id=logistics["id"])


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
    manual = freight_matching.save_candidate(store, logistics, expense, [line], "manual", "人工", expected_revision=ai['revision'])
    ignored = freight_matching.save_candidate(store, logistics, expense, [], "identifier", "标识", expected_revision=manual["revision"])
    assert manual["method"] == ignored["method"] == "manual"
    with pytest.raises(ValueError, match="变化"):
        freight_matching.save_candidate(store, logistics, expense, [], "manual", "新人工", expected_revision=ai["revision"])


def test_existing_identifier_candidate_requires_revision_before_manual_upgrade():
    from overseas_costing.services.logistics_settlement import freight_matching, freight_runtime
    store,ledger,batch,_version,_item,logistics,_expense=setup_cost()
    identifier=freight_matching.rule_pass(store,logistics['id'])[0]
    with pytest.raises(ValueError,match='版本'):
        freight_runtime.manual_candidate(store,ledger,batch['name'],identifier['expense_id'],'人工升级')
    manual=freight_runtime.manual_candidate(store,ledger,batch['name'],identifier['expense_id'],'人工升级',expected_revision=identifier['revision'])
    assert manual['method']=='manual'


def test_manual_candidate_only_admits_unique_current_material_identifierless_line():
    from overseas_costing.services.logistics_settlement import freight_runtime
    from overseas_costing.tests.test_payment_adoption import payment_setup

    store, ledger, batch, _version, logistics, source, _candidate = payment_setup(
        structured=True, scope="freight", amount="3414.19", mode="EXPRESS"
    )
    logistics.update(
        identifiers=[("material", "MWV101144")],
        goods=[{"material_code": "MWV101144", "product_name": "薇武士 IP17 PRO"}],
    )
    store.put("source", {"id": logistics["id"], "data": dumps(logistics)})
    own = store.get("freight_line", "payment-line-1")
    own.update(
        waybill="", approval_no="", cargo_text="MWV101144 薇武士 IP17 PRO",
        packing={"material_code_hints": ["MWV101144"]},
    )
    store.put("freight_line", {
        "id": own["id"], "waybill": "", "approval_no": "", "data": dumps(own),
    })
    unrelated = {
        **own,
        "id": "payment-line-2",
        "line_key": "line-key-2",
        "charge_key": "economic-charge-2",
        "cargo_text": "ABC999 薇武士 IP17 PRO",
        "packing": {"material_code_hints": ["ABC999"]},
    }
    store.insert("freight_line", {
        "id": unrelated["id"], "source_id": source["id"], "snapshot": source["snapshot"],
        "line_key": unrelated["line_key"], "waybill": "", "approval_no": "",
        "charge_key": unrelated["charge_key"], "data": dumps(unrelated),
    })
    store.sql("DELETE FROM oc_ls_freight_candidate WHERE logistics_id=%s", (logistics["id"],))

    freight_runtime.manual_candidate(
        store, ledger, batch["name"], source["id"], "人工选择付款流程", expected_revision=""
    )

    saved = store.find("freight_candidate", logistics_id=logistics["id"])[0]
    assert saved["line_scope_policy"] == freight_runtime.matching.CANDIDATE_SCOPE_POLICY
    assert saved["line_ids"] == ["payment-line-1"]


def test_manual_candidate_does_not_guess_between_multiple_current_material_lines():
    from overseas_costing.services.logistics_settlement import freight_runtime
    from overseas_costing.tests.test_payment_adoption import payment_setup

    store, ledger, batch, _version, logistics, source, _candidate = payment_setup(
        structured=True, scope="freight", amount="3414.19", mode="EXPRESS"
    )
    logistics.update(
        identifiers=[("material", "MWV101144")],
        goods=[{"material_code": "MWV101144", "product_name": "薇武士 IP17 PRO"}],
    )
    store.put("source", {"id": logistics["id"], "data": dumps(logistics)})
    first = store.get("freight_line", "payment-line-1")
    first.update(
        waybill="", approval_no="", cargo_text="MWV101144 薇武士 IP17 PRO",
        packing={"material_code_hints": ["MWV101144"]},
    )
    store.put("freight_line", {
        "id": first["id"], "waybill": "", "approval_no": "", "data": dumps(first),
    })
    second = {
        **first,
        "id": "payment-line-2",
        "line_key": "line-key-2",
        "charge_key": "economic-charge-2",
    }
    store.insert("freight_line", {
        "id": second["id"], "source_id": source["id"], "snapshot": source["snapshot"],
        "line_key": second["line_key"], "waybill": "", "approval_no": "",
        "charge_key": second["charge_key"], "data": dumps(second),
    })
    store.sql("DELETE FROM oc_ls_freight_candidate WHERE logistics_id=%s", (logistics["id"],))

    freight_runtime.manual_candidate(
        store, ledger, batch["name"], source["id"], "人工选择付款流程", expected_revision=""
    )

    saved = store.find("freight_candidate", logistics_id=logistics["id"])[0]
    assert saved["line_ids"] == []


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

    store, _ledger, batch, version, logistics, expense, _candidate = (
        _payment_ai_material_scope_context()
    )
    expense.update(
        fields={"供应商银行账号": secret, "项目说明": "可公开的项目甲"},
        raw_payload={"api_token": "RAW_PRIVATE_TOKEN"},
        attachments=[{"file_id": "private", "private_url": "https://private.example/secret"}],
    )
    store.put("source", {"id": expense["id"], "data": dumps(expense)})
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


@pytest.mark.parametrize('secret',[
    '6222‑0212/3456.7890','IBAN: GB82 WEST/1234-5698_7654.32','SWIFT: BOFA-US-3N/XXX','BIC: DEUT DE FF',
    'AKIAIOSFODNN7EXAMPLE','sk / live / SECRET123','-----BEGIN PRIVATE KEY----- ABC','access / token = PRIVATE123',
    '6222(0212)3456(7890)','6222\u200b0212\u200b3456\u200b7890',
    'DE89\u200b3704\u200b0044\u200b0532\u200b0130\u200b00','-----BEGIN PRIVATE\u200bKEY----- ABC',
])
def test_payment_sanitizer_blocks_unicode_separators_and_common_credentials(secret):
    from overseas_costing.services.logistics_settlement.ai_matching import safe_text
    from overseas_costing.services.logistics_settlement.freight_matching import sanitize_hints
    from overseas_costing.services.logistics_settlement.payment_ai_matching import _line_summary
    assert safe_text(secret)==''
    assert sanitize_hints({'description':secret})['description']==''
    assert _line_summary({'cargo_text':secret})['cargo_text']==''


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


def test_payment_candidate_decision_requires_lease_current_version_and_cas():
    from overseas_costing.services.logistics_settlement import freight_matching, freight_runtime
    store, ledger, batch, version, _item, logistics, _expense = setup_cost()
    ledger.put('batch', batch['name'], {'modified': 'm1'})
    candidate = freight_matching.rule_pass(store, logistics['id'])[0]

    with pytest.raises(ValueError, match='编辑租约'):
        freight_runtime.decide_payment_candidate(
            store, ledger, batch['name'], version['name'], candidate['id'], candidate['revision'],
            'reject', '人工否决', 'user', edit_token='', expected_modified='m1')

    def lease(batch_name, *, edit_token, expected_modified):
        assert (batch_name, edit_token, expected_modified) == (batch['name'], 'token', 'm1')
        return ledger.get('batch', batch_name, lock=True)

    ledger.put('batch', batch['name'], {'current_version': 'other-version'})
    with pytest.raises(ValueError, match='当前版本'):
        freight_runtime.decide_payment_candidate(
            store, ledger, batch['name'], version['name'], candidate['id'], candidate['revision'],
            'reject', '人工否决', 'user', lease_check=lease, edit_token='token', expected_modified='m1')

    ledger.put('batch', batch['name'], {'current_version': version['name']})
    rejected = freight_runtime.decide_payment_candidate(
        store, ledger, batch['name'], version['name'], candidate['id'], candidate['revision'],
        'reject', '人工否决', 'user', lease_check=lease, edit_token='token', expected_modified='m1')
    assert rejected['candidate']['status'] == 'rejected'
    assert rejected['candidate']['revision'] != candidate['revision']
    assert rejected['batch_modified'] == 'm1'

    reopened = freight_runtime.decide_payment_candidate(
        store, ledger, batch['name'], version['name'], candidate['id'], rejected['candidate']['revision'],
        'reopen', '重新核对', 'user', lease_check=lease, edit_token='token', expected_modified='m1')
    assert reopened['candidate']['status'] == 'reopened'
    with pytest.raises(ValueError, match='变化'):
        freight_runtime.decide_payment_candidate(
            store, ledger, batch['name'], version['name'], candidate['id'], rejected['candidate']['revision'],
            'reject', '并发旧请求', 'user', lease_check=lease, edit_token='token', expected_modified='m1')


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


def test_legacy_freight_worker_never_revives_failed_job_or_consumes_payment_job(monkeypatch):
    from overseas_costing.services.logistics_settlement import ai_matching, freight_matching, payment_ai_matching, runtime
    store,ledger,batch,version,_item,logistics,_expense=setup_cost()
    monkeypatch.setattr(runtime,'freight_enabled',lambda:True);monkeypatch.setattr(runtime,'store',lambda:store)
    monkeypatch.setattr(runtime,'FrappeLedger',lambda:ledger)
    _,_,fingerprint=freight_matching.input_state(store,logistics['id'])
    failed={'id':'failed-legacy','status':'failed','logistics_id':logistics['id'],'fingerprint':fingerprint,'actor':'user'};ai_matching.save(store,failed)
    before=store.find('freight_candidate')
    runtime.run_batch_matching(failed['id'])
    assert store.get('state',failed['id'])['status']=='failed' and store.find('freight_candidate')==before
    payment=payment_ai_matching.start(store,logistics['id'],batch['name'],version['name'],'user')
    runtime.run_batch_matching(payment['id'])
    assert store.get('state',payment['id'])['status']=='queued' and store.find('freight_candidate')==before


def test_payment_ai_transactions_lock_batch_before_job_and_candidates(monkeypatch):
    from overseas_costing.services.logistics_settlement import payment_ai_matching
    store,ledger,batch,version,_item,logistics,_expense=setup_cost();events=[]
    job=payment_ai_matching.start(store,logistics['id'],batch['name'],version['name'],'user')
    original=store.get
    def observed(table,key,lock=False):
        if lock and table=='state' and key=='match_lock':events.append('match')
        elif lock and table=='state' and key==job['id']:events.append('job')
        elif lock and table=='freight_candidate':events.append('candidate')
        return original(table,key,lock=lock)
    monkeypatch.setattr(store,'get',observed)
    def current(_batch,lock=False):
        if lock:events.append('batch')
        return (ledger.get('batch',batch['name'],lock=lock) or {}).get('current_version')
    payment_ai_matching.run(store,job['id'],lambda _messages:{'matches':[]},current_version=current)
    assert events[:3]==['match','batch','job']
    final_match=max(i for i,value in enumerate(events) if value=='match')
    assert events[final_match:final_match+3]==['match','batch','job']


def test_payment_ai_version_change_during_model_call_is_stale_without_candidate_write():
    from overseas_costing.services.logistics_settlement import payment_ai_matching
    store,ledger,batch,version,_item,logistics,_expense=setup_cost()
    expense=store.ingest(parse_source(_financial('version-race','付款'),logistics_codes={'logistics'}))
    job=payment_ai_matching.start(store,logistics['id'],batch['name'],version['name'],'user')
    def response(_messages):
        ledger.put('batch',batch['name'],{'current_version':'changed-version'})
        return {'matches':[{'expense_id':expense['id'],'confidence':1,'reason':'旧版本结果','line_ids':[]}]}
    result=payment_ai_matching.run(store,job['id'],response,
        current_version=lambda name,lock=False:(ledger.get('batch',name,lock=lock) or {}).get('current_version'))
    assert result['status']=='stale'
    assert not store.find('freight_candidate',expense_id=expense['id'])


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
