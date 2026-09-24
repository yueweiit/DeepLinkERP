import pytest

import oa_purchase_request.latingo_backfill as service
from oa_purchase_request.latingo_backfill import (
	analyze_backfill_state,
	apply_latingo_purchase_backfill,
	assert_apply_safe,
	collect_backfill_plans,
	preview_latingo_purchase_backfill,
	sync_latingo_purchase_order_review_flags,
	validate_latingo_purchase_order_submission,
)
from oa_purchase_request.latingo_backfill_domain import (
	GENERIC_PURCHASE_PROCESS_CODE,
	LATINGO_COMPANY,
	LATINGO_PURCHASE_PROCESS_CODE,
	build_approval_plan,
)


class FakeSource:
	def __init__(self, rows_by_process):
		self.rows_by_process = rows_by_process
		self.calls = []

	def list_instances(self, *, process_code, start, end, limit):
		self.calls.append((process_code, str(start), str(end), limit))
		return {
			"items": list(self.rows_by_process.get(process_code, [])),
			"source_updated_at": "2026-09-24T10:00:00Z",
			"source_lag_seconds": 5,
		}


def approval(instance_id, process_code, *, organization="拉丁购", detail_rows=None, apply_date="2026-07-12"):
	return {
		"processInstanceId": instance_id,
		"businessId": f"OA-{instance_id}",
		"processCode": process_code,
		"status": "COMPLETED",
		"result": "agree",
		"form": {
			"申请日期": apply_date,
			"申请部门/组织": organization,
			"币种": "RMB",
			"金额": "20",
			"收款人": "供应商 A",
			"说明": "说明",
		},
		"rows": detail_rows or [],
	}


def test_collect_backfill_plans_reads_each_process_in_month_windows_and_deduplicates():
	duplicate = approval("PI-LATIN", LATINGO_PURCHASE_PROCESS_CODE)
	source = FakeSource(
		{
			LATINGO_PURCHASE_PROCESS_CODE: [duplicate, duplicate],
			GENERIC_PURCHASE_PROCESS_CODE: [
				approval(
					"PI-GENERIC",
					GENERIC_PURCHASE_PROCESS_CODE,
					organization="OBG 线上业务组Grupo de negocios en línea",
				)
			],
		}
	)

	result = collect_backfill_plans(
		"2026-07-01",
		"2026-09-24",
		source=source,
		extract_form_fields=lambda row: row["form"],
		extract_purchase_rows=lambda row: row["rows"],
		map_purchase_row=lambda row: row,
	)

	assert len(source.calls) == 10
	assert source.calls[0][1:3] == ("2026-06-01", "2026-06-30")
	assert source.calls[-1][1:3] == ("2026-10-01", "2026-10-31")
	assert {row["process_instance_id"] for row in result["plans"]} == {"PI-LATIN", "PI-GENERIC"}
	assert result["duplicate_source_ids"] == ["PI-GENERIC", "PI-LATIN"]
	assert result["source_updated_at"] == "2026-09-24T10:00:00Z"
	assert result["source_lag_seconds"] == 5


def test_collect_backfill_plans_maps_existing_purchase_parser_rows():
	row = {
		"物品编码": "CW001",
		"物品名称": "玩具",
		"数量": 2,
		"单位": "只",
		"金额": 20,
	}
	source = FakeSource(
		{
			LATINGO_PURCHASE_PROCESS_CODE: [
				approval("PI-ITEM", LATINGO_PURCHASE_PROCESS_CODE, detail_rows=[row])
			]
		}
	)

	result = collect_backfill_plans(
		"2026-07-01",
		"2026-07-31",
		source=source,
		extract_form_fields=lambda value: value["form"],
		extract_purchase_rows=lambda value: value["rows"],
		map_purchase_row=lambda value: {
			"material_code": value["物品编码"],
			"product_name": value["物品名称"],
			"quantity": value["数量"],
			"unit": value["单位"],
			"goods_value": value["金额"],
		},
	)

	item = result["plans"][0]["items"][0]
	assert item["item_code"] == "CW001"
	assert item["qty"] == 2.0
	assert item["rate"] == 10.0
	assert item["stock_uom"] == "个：pieza"


def test_collect_backfill_plans_omits_generic_non_obg_sources_from_scoped_preview():
	source = FakeSource(
		{
			GENERIC_PURCHASE_PROCESS_CODE: [
				approval("PI-OUT", GENERIC_PURCHASE_PROCESS_CODE, organization="其他组织")
			]
		}
	)
	result = collect_backfill_plans(
		"2026-07-01",
		"2026-07-31",
		source=source,
		extract_form_fields=lambda value: value["form"],
		extract_purchase_rows=lambda value: value["rows"],
		map_purchase_row=lambda value: value,
	)
	assert result["plans"] == []
	assert result["out_of_scope_count"] == 1


def test_collect_backfill_plans_filters_by_application_date_not_archive_create_window():
	class WindowSource(FakeSource):
		def list_instances(self, *, process_code, start, end, limit):
			self.calls.append((process_code, str(start), str(end), limit))
			if process_code == LATINGO_PURCHASE_PROCESS_CODE and str(start) == "2026-06-01":
				return {
					"items": [
						approval("PI-IN", process_code, apply_date="2026-07-01"),
						approval("PI-OUT", process_code, apply_date="2026-06-30"),
					],
				}
			return {"items": []}

	result = collect_backfill_plans(
		"2026-07-01",
		"2026-09-24",
		source=WindowSource({}),
		extract_form_fields=lambda value: value["form"],
		extract_purchase_rows=lambda value: value["rows"],
		map_purchase_row=lambda value: value,
	)

	assert [plan["process_instance_id"] for plan in result["plans"]] == ["PI-IN"]
	assert result["out_of_date_count"] == 1


def test_analyze_backfill_state_reports_create_update_reuse_and_conflict():
	plans = []
	for instance_id, item_code in (("A", "NEW"), ("B", "BLANK"), ("C", "OWNED"), ("D", "OTHER")):
		plans.append(
			build_approval_plan(
				{
					"process_instance_id": instance_id,
					"business_id": f"OA-{instance_id}",
					"process_code": LATINGO_PURCHASE_PROCESS_CODE,
					"status": "COMPLETED",
					"result": "agree",
					"apply_date": "2026-07-01",
					"currency": "RMB",
					"amount": 10,
					"detail_rows": [
						{"item_code": item_code, "item_name": item_code, "qty": 1, "uom": "个", "amount": 10}
					],
				},
				"2026-07-01",
				"2026-09-24",
			)
		)

	items = {
		"BLANK": {"custom_overseas_business_entity": ""},
		"OWNED": {"custom_overseas_business_entity": LATINGO_COMPANY},
		"OTHER": {"custom_overseas_business_entity": "其他子公司"},
	}
	state = analyze_backfill_state(
		plans,
		item_lookup=lambda code: items.get(code),
		oa_by_process=lambda _instance_id: None,
		oa_by_business=lambda _business_id: None,
	)

	assert state["item_actions"] == [
		{"item_code": "BLANK", "action": "update_ownership"},
		{"item_code": "NEW", "action": "create"},
		{"item_code": "OTHER", "action": "conflict", "existing_owner": "其他子公司"},
		{"item_code": "OWNED", "action": "reuse"},
	]
	assert state["conflicts"] == ["物料 OTHER 已属于其他子公司"]


def test_analyze_backfill_state_allows_exact_rerun_but_blocks_business_key_collision():
	plan = build_approval_plan(
		{
			"process_instance_id": "A",
			"business_id": "OA-A",
			"process_code": LATINGO_PURCHASE_PROCESS_CODE,
			"status": "COMPLETED",
			"result": "agree",
			"apply_date": "2026-07-01",
			"currency": "RMB",
			"amount": 10,
			"description": "服务",
			"detail_rows": [],
		},
		"2026-07-01",
		"2026-09-24",
	)
	plan["source_fingerprint"] = "same"

	reused = analyze_backfill_state(
		[plan],
		item_lookup=lambda _code: None,
		oa_by_process=lambda _instance_id: {
			"name": "OA-A",
			"source_fingerprint": "same",
			"purchase_order": "PO-A",
		},
		oa_by_business=lambda _business_id: None,
	)
	assert reused["existing"] == [{"process_instance_id": "A", "oa_request": "OA-A", "purchase_order": "PO-A"}]
	assert reused["conflicts"] == []

	collision = analyze_backfill_state(
		[plan],
		item_lookup=lambda _code: None,
		oa_by_process=lambda _instance_id: None,
		oa_by_business=lambda _business_id: {"name": "OLD", "process_instance_id": "OTHER"},
	)
	assert collision["conflicts"] == ["审批编号 OA-A 已被另一来源实例占用"]

	incomplete = analyze_backfill_state(
		[plan],
		item_lookup=lambda _code: None,
		oa_by_process=lambda _instance_id: {
			"name": "OA-A",
			"source_fingerprint": "same",
			"purchase_order": "",
			"purchase_order_exists": False,
		},
		oa_by_business=lambda _business_id: None,
	)
	assert incomplete["conflicts"] == ["来源实例 A 已存在但未关联有效采购订单"]


def test_assert_apply_safe_rejects_fingerprint_drift_and_preflight_conflicts():
	with pytest.raises(ValueError, match="预览指纹已变化"):
		assert_apply_safe({"fingerprint": "new", "conflicts": []}, "old")
	with pytest.raises(ValueError, match="物料 A 已属于其他子公司"):
		assert_apply_safe({"fingerprint": "same", "conflicts": ["物料 A 已属于其他子公司"]}, "same")


class FakeDB:
	def __init__(self):
		self.write_calls = []
		self.savepoints = []
		self.rollbacks = []
		self.sql_calls = []

	def get_value(self, doctype, filters, fieldname=None, as_dict=False):
		if doctype == "Item":
			return None
		if doctype == "OA Purchase Request":
			return None
		return None

	def set_value(self, *args, **kwargs):
		self.write_calls.append((args, kwargs))

	def exists(self, doctype, name):
		return doctype in {"Company", "Warehouse", "Cost Center", "Account", "Item Group", "UOM"}

	def sql(self, query, values=None):
		self.sql_calls.append((query, values))
		if "get_lock" in query.lower():
			return [(1,)]
		return []

	def savepoint(self, name):
		self.savepoints.append(name)

	def rollback(self, save_point=None):
		self.rollbacks.append(save_point)


class FakeFrappe:
	def __init__(self, roles=None):
		self.db = FakeDB()
		self.session = type("Session", (), {"user": "Administrator"})()
		self._roles = roles or ["System Manager"]

	def get_roles(self, _user):
		return self._roles

	def throw(self, message, *args, **kwargs):
		raise PermissionError(message)


def test_preview_endpoint_is_read_only_and_returns_business_counts(monkeypatch):
	completed = build_approval_plan(
		{
			"process_instance_id": "A",
			"business_id": "OA-A",
			"process_code": LATINGO_PURCHASE_PROCESS_CODE,
			"status": "COMPLETED",
			"result": "agree",
			"apply_date": "2026-07-01",
			"currency": "RMB",
			"amount": 10,
			"detail_rows": [{"item_code": "CW1", "item_name": "A", "qty": 1, "uom": "个", "amount": 10}],
		},
		"2026-07-01",
		"2026-09-24",
	)
	running = build_approval_plan(
		{
			"process_instance_id": "B",
			"business_id": "OA-B",
			"process_code": LATINGO_PURCHASE_PROCESS_CODE,
			"status": "RUNNING",
			"result": "",
			"apply_date": "2026-08-01",
			"currency": "Peso",
			"amount": 20,
			"description": "物流服务",
			"detail_rows": [],
		},
		"2026-07-01",
		"2026-09-24",
	)
	rejected = build_approval_plan(
		{
			"process_instance_id": "C",
			"business_id": "OA-C",
			"process_code": LATINGO_PURCHASE_PROCESS_CODE,
			"status": "COMPLETED",
			"result": "refuse",
			"apply_date": "2026-08-01",
			"currency": "RMB",
			"amount": 30,
			"detail_rows": [],
		},
		"2026-07-01",
		"2026-09-24",
	)
	for plan in (completed, running, rejected):
		plan["source_fingerprint"] = plan["process_instance_id"]
	fake_frappe = FakeFrappe()
	monkeypatch.setattr(service, "frappe", fake_frappe)
	monkeypatch.setattr(
		service,
		"_collect_from_archive",
		lambda *_args, **_kwargs: {
			"plans": [completed, running, rejected],
			"fingerprint": "preview-hash",
			"duplicate_source_ids": [],
			"source_updated_at": "2026-09-24T10:00:00Z",
			"source_lag_seconds": 5,
		},
	)

	preview = preview_latingo_purchase_backfill("2026-07-01", "2026-09-24")

	assert preview["dry_run"] is True
	assert preview["fingerprint"] == "preview-hash"
	assert preview["counts"] == {
		"scanned": 3,
		"eligible": 2,
		"excluded": 1,
		"completed": 1,
		"running": 1,
		"physical_orders": 1,
		"service_orders": 1,
		"CNY": 1,
		"MXN": 1,
	}
	assert preview["excluded"][0]["exclusion_reason"] == "审批已拒绝"
	assert fake_frappe.db.write_calls == []


def test_preview_endpoint_requires_system_manager(monkeypatch):
	fake_frappe = FakeFrappe(roles=["Accounts User"])
	fake_frappe.session.user = "ordinary@example.com"
	monkeypatch.setattr(service, "frappe", fake_frappe)
	with pytest.raises(PermissionError, match="System Manager"):
		preview_latingo_purchase_backfill("2026-07-01", "2026-09-24")


@pytest.mark.parametrize(
	("endpoint", "arguments"),
	[
		(preview_latingo_purchase_backfill, ("2026-06-30", "2026-09-24")),
		(apply_latingo_purchase_backfill, ("2026-07-01", "2026-09-25", "fingerprint")),
	],
)
def test_public_backfill_endpoints_enforce_the_fixed_business_range(monkeypatch, endpoint, arguments):
	fake_frappe = FakeFrappe()
	monkeypatch.setattr(service, "frappe", fake_frappe)
	monkeypatch.setattr(service, "_build_preview", lambda *_args: pytest.fail("must not read source"))
	with pytest.raises(ValueError, match="固定范围"):
		endpoint(*arguments)
	assert fake_frappe.db.sql_calls == []


def apply_preview(plans, *, existing=None, conflicts=None, fingerprint="fingerprint"):
	return {
		"ok": not conflicts,
		"dry_run": True,
		"fingerprint": fingerprint,
		"eligible": plans,
		"excluded": [],
		"item_actions": [],
		"existing": existing or [],
		"conflicts": conflicts or [],
		"warnings": [],
		"counts": {"eligible": len(plans)},
	}


def test_apply_is_idempotent_when_all_sources_already_exist(monkeypatch):
	plan = {"process_instance_id": "A", "business_id": "OA-A", "included": True}
	preview = apply_preview(
		[plan],
		existing=[{"process_instance_id": "A", "oa_request": "OA-A", "purchase_order": "PO-A"}],
	)
	fake_frappe = FakeFrappe()
	monkeypatch.setattr(service, "frappe", fake_frappe)
	monkeypatch.setattr(service, "_build_preview", lambda *_args: preview)
	monkeypatch.setattr(service, "_ensure_master_data", lambda *_args: pytest.fail("must not create master data"))
	monkeypatch.setattr(service, "_create_backfill_pair", lambda *_args: pytest.fail("must not create documents"))

	result = apply_latingo_purchase_backfill("2026-07-01", "2026-09-24", "fingerprint")

	assert result["created"] == []
	assert result["reused"] == preview["existing"]
	assert result["failed"] == []
	assert fake_frappe.db.rollbacks == []


def test_apply_rolls_back_the_whole_batch_and_returns_failure(monkeypatch):
	plans = [
		{"process_instance_id": "A", "business_id": "OA-A", "included": True},
		{"process_instance_id": "B", "business_id": "OA-B", "included": True},
	]
	preview = apply_preview(plans)
	fake_frappe = FakeFrappe()
	created_attempts = []
	monkeypatch.setattr(service, "frappe", fake_frappe)
	monkeypatch.setattr(service, "_build_preview", lambda *_args: preview)
	monkeypatch.setattr(service, "_ensure_master_data", lambda *_args: None)

	def create_pair(plan):
		created_attempts.append(plan["process_instance_id"])
		if plan["process_instance_id"] == "B":
			raise RuntimeError("second row failed")
		return {"process_instance_id": "A", "oa_request": "OA-A", "purchase_order": "PO-A"}

	monkeypatch.setattr(service, "_create_backfill_pair", create_pair)

	result = apply_latingo_purchase_backfill("2026-07-01", "2026-09-24", "fingerprint")

	assert created_attempts == ["A", "B"]
	assert result["ok"] is False
	assert result["created"] == []
	assert result["failed"] == [{"message": "second row failed"}]
	assert fake_frappe.db.savepoints == ["latingo_purchase_backfill"]
	assert fake_frappe.db.rollbacks == ["latingo_purchase_backfill"]
	assert not hasattr(fake_frappe.db, "commits")


def test_apply_creates_each_missing_source_without_explicit_commit(monkeypatch):
	plans = [
		{"process_instance_id": "A", "business_id": "OA-A", "included": True},
		{"process_instance_id": "B", "business_id": "OA-B", "included": True},
	]
	preview = apply_preview(plans)
	fake_frappe = FakeFrappe()
	monkeypatch.setattr(service, "frappe", fake_frappe)
	monkeypatch.setattr(service, "_build_preview", lambda *_args: preview)
	monkeypatch.setattr(service, "_ensure_master_data", lambda *_args: None)
	monkeypatch.setattr(
		service,
		"_create_backfill_pair",
		lambda plan: {
			"process_instance_id": plan["process_instance_id"],
			"oa_request": f"OA-{plan['process_instance_id']}",
			"purchase_order": f"PO-{plan['process_instance_id']}",
		},
	)

	result = apply_latingo_purchase_backfill("2026-07-01", "2026-09-24", "fingerprint")

	assert result["ok"] is True
	assert len(result["created"]) == 2
	assert result["reused"] == []
	assert result["failed"] == []
	assert fake_frappe.db.rollbacks == []


class FakePurchaseOrder(dict):
	def __getattr__(self, name):
		return self.get(name)

	def __setattr__(self, name, value):
		self[name] = value


@pytest.mark.parametrize(
	("calculated_total", "expected_total", "expected_discount"),
	[(1935.0, 1930.11, 4.89), (22110.0, 22119.0, -9.0)],
)
def test_purchase_order_total_adjustment_reconciles_erpnext_currency_rounding(
	calculated_total,
	expected_total,
	expected_discount,
):
	class CalculatedPurchaseOrder(FakePurchaseOrder):
		def run_method(self, method):
			assert method == "calculate_taxes_and_totals"
			self.grand_total = calculated_total

	doc = CalculatedPurchaseOrder()
	service._reconcile_purchase_order_total(doc, expected_total)

	assert doc.apply_discount_on == "Grand Total"
	assert doc.discount_amount == expected_discount


def test_submission_guard_ignores_ordinary_purchase_orders(monkeypatch):
	monkeypatch.setattr(service, "frappe", FakeFrappe())
	monkeypatch.setattr(service, "_refresh_oa_source_internal", lambda *_args: pytest.fail("must not refresh"))
	validate_latingo_purchase_order_submission(FakePurchaseOrder(custom_latingo_backfill=0))


def test_source_refresh_rejects_legacy_manual_oa_requests(monkeypatch):
	fake_frappe = FakeFrappe()
	fake_frappe.get_doc = lambda *_args: FakePurchaseOrder(
		name="OA-LEGACY",
		backfill_imported=0,
		process_instance_id="PI-LEGACY",
	)
	monkeypatch.setattr(service, "frappe", fake_frappe)
	monkeypatch.setattr(service, "_current_source_plan", lambda *_args: pytest.fail("must not read source"))
	with pytest.raises(ValueError, match="仅支持拉丁购历史回填"):
		service._refresh_oa_source_internal("OA-LEGACY")


def test_submission_guard_refreshes_source_and_blocks_every_unresolved_review(monkeypatch):
	fake_frappe = FakeFrappe()
	monkeypatch.setattr(service, "frappe", fake_frappe)
	monkeypatch.setattr(
		service,
		"_refresh_oa_source_internal",
		lambda _name: {
			"source_pending": True,
			"source_stale": True,
			"source_invalid": False,
		},
	)
	doc = FakePurchaseOrder(
		custom_latingo_backfill=1,
		custom_oa_purchase_expense="OA-A",
		supplier="拉丁购采购支出（待确认供应商）",
		currency="MXN",
		custom_latingo_exchange_rate_pending=1,
		items=[{"rate": 0}],
	)

	with pytest.raises(PermissionError) as exc:
		validate_latingo_purchase_order_submission(doc)

	message = str(exc.value)
	for expected in ("来源审批尚未完成", "来源指纹已过期", "临时供应商尚未替换", "MXN 汇率尚未确认", "存在零价格物料"):
		assert expected in message


def test_submission_guard_allows_reviewed_final_source(monkeypatch):
	monkeypatch.setattr(service, "frappe", FakeFrappe())
	monkeypatch.setattr(
		service,
		"_refresh_oa_source_internal",
		lambda _name: {"source_pending": False, "source_stale": False, "source_invalid": False},
	)
	doc = FakePurchaseOrder(
		custom_latingo_backfill=1,
		custom_oa_purchase_expense="OA-A",
		supplier="真实供应商",
		currency="MXN",
		custom_latingo_exchange_rate_pending=0,
		items=[{"rate": 12.5}],
	)
	validate_latingo_purchase_order_submission(doc)


def test_purchase_order_validate_keeps_supplier_and_price_review_flags_current():
	doc = FakePurchaseOrder(
		custom_latingo_backfill=1,
		supplier="拉丁购采购支出（待确认供应商）",
		items=[{"rate": 0}],
	)
	sync_latingo_purchase_order_review_flags(doc)
	assert doc["custom_latingo_temporary_supplier_pending"] == 1
	assert doc["custom_latingo_price_pending"] == 1

	doc["supplier"] = "真实供应商"
	doc["items"][0]["rate"] = 3
	sync_latingo_purchase_order_review_flags(doc)
	assert doc["custom_latingo_temporary_supplier_pending"] == 0
	assert doc["custom_latingo_price_pending"] == 0
