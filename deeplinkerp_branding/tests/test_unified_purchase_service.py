"""Real merge/filter behavior with only the Frappe read boundary substituted."""

from __future__ import annotations

import importlib
import json
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest


def backend():
	assert importlib.util.find_spec("deeplinkerp_branding.services.unified_purchase_service"), (
		"Unified purchase read backend is not implemented"
	)
	return importlib.import_module("deeplinkerp_branding.services.unified_purchase_service")


def po(name="PO-1", **values):
	return {
		"name": name, "transaction_date": "2026-10-01", "supplier": "SUP-1",
		"supplier_name": "供应商", "status": "Closed", "company": "Yuewei",
		"currency": "USD", "grand_total": 0, "advance_paid": 0,
		"party_account_currency": "CNY", "advance_payment_status": "Not Paid",
		"per_received": 0, "per_billed": 0, "schedule_date": None,
		"project": None, "owner": "buyer@example.test", "docstatus": 1,
		"custom_oa_purchase_expense": None, **values,
	}


def oa(name="OA-1", **values):
	return {
		"name": name, "oa_code": "审批-1", "apply_date": "2026-09-30",
		"creation": datetime(2026, 9, 29, 8), "target_company": "Yuewei",
		"currency": "人民币RMB", "detail_total_amount": 10,
		"processor_total_amount": 20, "payment_amount": 30,
		"purchase_order": None, "approval_status": "APPROVED", "sync_status": "DONE",
		"process_instance_id": "PROCESS-1", "owner": "requester@example.test",
		"order_no": "采购编号-1", **values,
	}


def test_closed_zero_orders_remain_and_explicit_links_alone_deduplicate():
	s = backend()
	result = s.build_unified_purchase_payload(
		[po(custom_oa_purchase_expense="OA-1"), po("采购编号-1")],
		[oa(), oa("OA-2", purchase_order="PO-1"), oa("OA-3")],
	)
	assert result["total_count"] == 3
	assert {row["row_key"] for row in result["rows"]} == {
		"Purchase Order::PO-1", "Purchase Order::采购编号-1", "OA Purchase Request::OA-3",
	}
	linked = next(row for row in result["rows"] if row["name"] == "PO-1")
	assert linked["grand_total"] == 0
	assert linked["source"] == "OA"
	assert linked["oa_amount"] is None
	assert "多个" in linked["oa_warning"]


def test_linked_metadata_is_merged_before_date_company_search_and_approval_filters():
	s = backend()
	result = s.build_unified_purchase_payload(
		[po(custom_oa_purchase_expense="OA-1")], [oa(target_company="Other")],
		filters={"search": "审批-1", "from_date": "2026-10-01", "to_date": "2026-10-01",
			"company": "Yuewei", "approval_status": "APPROVED", "source": "oa"},
	)
	assert result["total_count"] == 1
	row = result["rows"][0]
	assert row["oa_name"] == "OA-1"
	assert row["oa_number"] == "审批-1"
	assert row["oa_amount"] == 10
	assert row["oa_currency"] == "CNY"
	assert row["oa_amount_basis"] == "采购明细合计"
	assert row["company"] == "Yuewei"


def test_inaccessible_linked_order_keeps_oa_without_leaking_order_name():
	s = backend()
	result = s.build_unified_purchase_payload([], [oa(purchase_order="SECRET-PO")])
	row = result["rows"][0]
	assert row["name"] == "OA-1"
	assert row["status"] == "已生成订单（无权查看）"
	assert "SECRET-PO" not in str(result)
	assert row["row_type"] == "oa_request"
	assert row["grand_total"] is None
	assert row["supplier"] is None
	assert row["docstatus"] is None


def test_conflicting_order_links_do_not_assign_the_same_oa_amount_twice():
	s = backend()
	result = s.build_unified_purchase_payload(
		[po(custom_oa_purchase_expense="OA-1"), po("PO-2")],
		[oa(purchase_order="PO-2")],
	)
	assert result["total_count"] == 2
	assert all(row["oa_amount"] is None for row in result["rows"])
	assert all("冲突" in row["oa_warning"] for row in result["rows"])
	assert result["totals"]["oa"] == []


def test_conflicting_links_keep_readable_per_oa_provenance_on_both_orders():
	s = backend()
	result = s.build_unified_purchase_payload(
		[po(custom_oa_purchase_expense="OA-1"), po("PO-2")],
		[oa(purchase_order="PO-2")],
	)
	for row in result["rows"]:
		assert row["oa_amount"] is None
		assert len(row["oa_references"]) == 1
		reference = row["oa_references"][0]
		assert {key: reference[key] for key in (
			"name", "number", "approval_status", "amount", "currency", "amount_basis", "company",
		)} == {
			"name": "OA-1", "number": "审批-1", "approval_status": "APPROVED", "amount": 10,
			"currency": "CNY", "amount_basis": "采购明细合计", "company": "Yuewei",
		}
		assert "冲突" in reference["warning"]


def test_multiple_oa_references_keep_each_amount_and_approval_without_aggregate_choice():
	s = backend()
	row = s.build_unified_purchase_payload([po(custom_oa_purchase_expense="OA-1")], [
		oa(), oa("OA-2", purchase_order="PO-1", approval_status="RUNNING", currency="USD", detail_total_amount=99),
	])["rows"][0]
	assert row["oa_amount"] is None
	assert [(ref["name"], ref["amount"], ref["approval_status"]) for ref in row["oa_references"]] == [
		("OA-1", 10, "APPROVED"), ("OA-2", 99, "RUNNING"),
	]


def test_company_mismatch_keeps_both_native_companies_and_warns():
	s = backend()
	row = s.build_unified_purchase_payload([po(custom_oa_purchase_expense="OA-1")],
		[oa(target_company="Other")])["rows"][0]
	assert row["company"] == "Yuewei"
	assert row["oa_references"][0]["company"] == "Other"
	assert "公司" in row["oa_warning"]
	assert "公司" in row["oa_references"][0]["warning"]


def test_unknown_currency_in_conflicting_references_is_counted_once_per_oa():
	result = backend().build_unified_purchase_payload(
		[po(custom_oa_purchase_expense="OA-1"), po("PO-2")],
		[oa(purchase_order="PO-2", currency="神秘币")],
	)
	assert result["totals"]["oa_unknown_currency_count"] == 1
	assert result["totals"]["oa"] == []


@pytest.mark.parametrize(
	("detail", "processor", "payment", "amount", "basis", "zero_warning"),
	[(12.345678, 20, 30, 12.345678, "采购明细合计", False),
		(0, -4, 30, -4, "加工合计", False),
		(None, 0, -7, -7, "付款申请金额", False),
		(0, 0, 0, 0, "付款申请金额", True),
		(None, None, None, None, None, False)],
)
def test_oa_amount_precedence_preserves_precision_negative_zero_and_null(
	detail, processor, payment, amount, basis, zero_warning,
):
	row = backend().build_unified_purchase_payload([], [oa(
		detail_total_amount=detail, processor_total_amount=processor, payment_amount=payment,
	)])["rows"][0]
	assert row["oa_amount"] == amount
	assert row["oa_amount_basis"] == basis
	assert ("原始金额为0，待核实" in (row["oa_warning"] or "")) is zero_warning


def test_unknown_currency_is_visible_but_excluded_from_currency_totals():
	s = backend()
	result = s.build_unified_purchase_payload(
		[po(grand_total=40)],
		[oa(), oa("OA-2", currency="比索Peso", detail_total_amount=2),
			oa("OA-3", currency="神秘币", detail_total_amount=100)],
	)
	assert result["totals"] == {
		"orders": [{"currency": "USD", "amount": 40}],
		"oa": [{"currency": "CNY", "amount": 10}, {"currency": "MXN", "amount": 2}],
		"oa_unknown_currency_count": 1,
	}
	unknown = next(row for row in result["rows"] if row["name"] == "OA-3")
	assert unknown["oa_currency"] is None
	assert "币种" in unknown["oa_warning"]


def test_currency_codes_require_recognition_or_currency_master_evidence():
	s = backend()
	result = s.build_unified_purchase_payload([], [oa(currency="XYZ")])
	assert result["rows"][0]["oa_currency"] is None
	known = s.build_unified_purchase_payload([], [oa(currency="XYZ")], currency_codes={"XYZ"})
	assert known["rows"][0]["oa_currency"] == "XYZ"


def test_unconfirmed_company_and_creation_fallback_are_filterable():
	s = backend()
	result = s.build_unified_purchase_payload([], [oa(apply_date=None, target_company=None)],
		filters={"company": "__unconfirmed__", "from_date": "2026-09-29", "to_date": "2026-09-29"})
	assert result["rows"][0]["transaction_date"] == "2026-09-29"
	assert result["rows"][0]["company"] is None
	assert result["rows"][0]["status"] == "未生成订单"


@pytest.mark.parametrize(("scope", "names"), [
	("all", {"PO-1", "PO-2", "OA-2"}), ("orders", {"PO-1", "PO-2"}),
	("oa", {"PO-1", "OA-2"}),
])
def test_scope_oa_includes_linked_orders(scope, names):
	result = backend().build_unified_purchase_payload(
		[po(custom_oa_purchase_expense="OA-1"), po("PO-2")], [oa(), oa("OA-2")],
		filters={"scope": scope},
	)
	assert {row["name"] for row in result["rows"]} == names


def test_pagination_is_stable_and_totals_cover_all_filtered_rows():
	s = backend()
	orders = [po("PO-3", grand_total=3), po("PO-1", grand_total=1), po("PO-2", grand_total=2)]
	first = s.build_unified_purchase_payload(orders, [], page_length=1)
	second = s.build_unified_purchase_payload(orders, [], start=1, page_length=1)
	assert first["rows"][0]["name"] == "PO-1"
	assert second["rows"][0]["name"] == "PO-2"
	assert first["has_previous"] is False and first["has_next"] is True
	assert second["has_previous"] is True and second["has_next"] is True
	assert first["totals"] == second["totals"]
	assert first["totals"]["orders"] == [{"currency": "USD", "amount": 6}]


@pytest.mark.parametrize("kwargs", [
	{"page_length": 0}, {"page_length": 2501}, {"page_length": 1.2}, {"page_length": True},
	{"start": -1}, {"start": 1.2}, {"start": True},
	{"order_by": "transaction_date desc; DROP TABLE `tabPurchase Order`"},
	{"order_by": "unknown desc"}, {"order_by": "name sideways"},
	{"filters": {"scope": "secret"}}, {"filters": {"source": "secret"}},
])
def test_invalid_pagination_sort_and_scope_are_rejected(kwargs):
	with pytest.raises(ValueError):
		backend().build_unified_purchase_payload([], [], **kwargs)


def test_unreadable_association_and_amount_fields_are_not_inferred():
	s = backend()
	order = po()
	del order["custom_oa_purchase_expense"]
	request = oa(detail_total_amount=0, payment_amount=88)
	del request["processor_total_amount"]
	del request["currency"]
	del request["target_company"]
	result = s.build_unified_purchase_payload([order], [request])
	assert next(row for row in result["rows"] if row["name"] == "PO-1")["source"] is None
	row = next(row for row in result["rows"] if row["name"] == "OA-1")
	assert row["oa_amount"] is None
	assert row["company"] is None
	assert row["oa_currency"] is None
	assert s.build_unified_purchase_payload([order], [], filters={"source": "non_oa"})["total_count"] == 0


def test_unconfirmed_company_filter_does_not_infer_unreadable_company_is_empty():
	s = backend()
	order, request = po(), oa()
	del order["company"]
	del request["target_company"]
	result = s.build_unified_purchase_payload([order], [request], filters={"company": "__unconfirmed__"})
	assert result["total_count"] == 0


@pytest.mark.parametrize("row_type", ["purchase_order", "oa_request"])
@pytest.mark.parametrize("visibility", ["hidden", "pending", "known"])
def test_company_visibility_distinguishes_field_permissions_from_business_pending(row_type, visibility):
	s = backend()
	record = po() if row_type == "purchase_order" else oa()
	company_field = "company" if row_type == "purchase_order" else "target_company"
	if visibility == "hidden":
		del record[company_field]
	elif visibility == "pending":
		record[company_field] = None
	orders, requests = ([record], []) if row_type == "purchase_order" else ([], [record])
	result = s.build_unified_purchase_payload(orders, requests)
	row = result["rows"][0]
	assert row["company_visibility"] == visibility
	assert not any(key.startswith("_") for key in row)
	pending = s.build_unified_purchase_payload(orders, requests, filters={"company": "__unconfirmed__"})
	assert pending["total_count"] == (1 if visibility == "pending" else 0)


class ReadBoundary:
	PermissionError = PermissionError

	def __init__(self, orders=(), requests=(), *, oa_installed=True, read=None, export=None, fields=None):
		self.records = {"Purchase Order": list(orders), "OA Purchase Request": list(requests)}
		self.installed = {"Purchase Order"} | ({"OA Purchase Request"} if oa_installed else set())
		self.read = self.installed if read is None else set(read)
		self.export = self.installed if export is None else set(export)
		self.fields = fields or {key: set().union(*(row.keys() for row in value)) for key, value in self.records.items()}
		self.calls = []
		self.field_calls = []
		self.response = {}
		self.db = SimpleNamespace(exists=self.exists)

	def exists(self, doctype, name):
		if doctype == "DocType":
			return name in self.installed
		return doctype == "Currency" and name in {"CNY", "MXN", "USD", "XYZ"}

	def has_permission(self, doctype, permission_type="read"):
		return doctype in (self.read if permission_type == "read" else self.export)

	def permitted_fields(self, doctype, **kwargs):
		self.field_calls.append((doctype, kwargs))
		return self.fields.get(doctype, {"name"})

	def get_list(self, doctype, **kwargs):
		self.calls.append((doctype, kwargs))
		assert self.has_permission(doctype, "read")
		assert set(kwargs["fields"]) <= self.fields[doctype]
		return [{field: row.get(field) for field in kwargs["fields"]} for row in self.records[doctype]]

	def throw(self, message, exception):
		raise exception(message)


def connect(monkeypatch, boundary):
	s = backend()
	monkeypatch.setattr(s, "frappe", boundary)
	monkeypatch.setattr(s, "get_permitted_fields", boundary.permitted_fields)
	return s


def test_api_missing_oa_app_keeps_orders_and_reports_capability(monkeypatch):
	b = ReadBoundary([po()], oa_installed=False)
	result = connect(monkeypatch, b).get_unified_purchase_list()
	assert result["total_count"] == 1
	assert result["capabilities"] == {"purchase_order": True, "oa_request": False}
	assert result["warnings"]
	assert [call[0] for call in b.calls] == ["Purchase Order"]


def test_api_uses_permission_aware_unbounded_queries_and_sanitizes_fields(monkeypatch):
	b = ReadBoundary([po(custom_oa_purchase_expense="OA-1")], [oa()], fields={
		"Purchase Order": {"name", "transaction_date", "custom_oa_purchase_expense"},
		"OA Purchase Request": {"name", "oa_code", "purchase_order", "apply_date"},
	})
	result = connect(monkeypatch, b).get_unified_purchase_list(filters='{"search":"审批-1"}')
	assert result["total_count"] == 1
	assert result["rows"][0]["grand_total"] is None
	assert result["rows"][0]["oa_amount"] is None
	assert result["rows"][0]["company"] is None
	assert "custom_oa_purchase_expense" not in result["rows"][0]
	assert len(b.calls) == 2
	assert all(call[1]["limit_page_length"] == 0 for call in b.calls)
	assert all("filters" not in call[1] and "ignore_permissions" not in call[1] for call in b.calls)
	assert all(call[1] == {"permission_type": "read", "ignore_virtual": True} for call in b.field_calls)


def test_api_oa_read_denied_exposes_source_without_oa_links_or_metadata(monkeypatch):
	b = ReadBoundary([po(custom_oa_purchase_expense="SECRET-OA")], [oa("SECRET-OA")], read={"Purchase Order"})
	result = connect(monkeypatch, b).get_unified_purchase_list()
	assert result["rows"][0]["source"] == "OA"
	assert result["rows"][0]["oa_name"] is None
	assert "SECRET-OA" not in str(result)
	assert [call[0] for call in b.calls] == ["Purchase Order"]


@pytest.mark.parametrize("visibility", ["hidden_field", "empty_hidden_field", "no_oa_read"])
def test_api_blank_forward_link_does_not_claim_non_oa_when_reverse_link_is_unreadable(monkeypatch, visibility):
	order = po(custom_oa_purchase_expense=None)
	requests = [oa(purchase_order="PO-1")] if visibility == "hidden_field" else []
	b = ReadBoundary([order], requests, read={"Purchase Order"} if visibility == "no_oa_read" else None,
		fields={"Purchase Order": set(order), "OA Purchase Request": {"name", "oa_code"}})
	s = connect(monkeypatch, b)
	result = s.get_unified_purchase_list()
	row = next(row for row in result["rows"] if row["row_type"] == "purchase_order")
	assert row["source"] is None
	assert s.get_unified_purchase_list(filters={"source": "non_oa"})["total_count"] == 0


def test_api_empty_reverse_query_uses_permitted_field_evidence(monkeypatch):
	order = po(custom_oa_purchase_expense=None)
	b = ReadBoundary([order], [], fields={
		"Purchase Order": set(order), "OA Purchase Request": {"name", "purchase_order"},
	})
	result = connect(monkeypatch, b).get_unified_purchase_list(filters={"source": "non_oa"})
	assert result["total_count"] == 1
	assert result["rows"][0]["source"] == "未关联 OA"


def test_hidden_oa_reverse_link_does_not_infer_order_was_not_generated(monkeypatch):
	order, request = po(), oa(purchase_order="SECRET-PO")
	b = ReadBoundary([order], [request], fields={
		"Purchase Order": set(order), "OA Purchase Request": set(request) - {"purchase_order"},
	})
	result = connect(monkeypatch, b).get_unified_purchase_list()
	row = next(row for row in result["rows"] if row["row_type"] == "oa_request")
	assert row["status"] == "订单关联不可见"
	assert "订单关联不可见" in row["oa_warning"]
	assert "SECRET-PO" not in str(result)


def test_no_readable_doctype_is_explicit_permission_error(monkeypatch):
	b = ReadBoundary(read=set())
	with pytest.raises(PermissionError):
		connect(monkeypatch, b).get_unified_purchase_list()


@pytest.mark.parametrize("export_permissions", [{"Purchase Order"}, {"OA Purchase Request"}, set()])
def test_export_requires_permissions_for_both_linked_metadata_and_order(monkeypatch, export_permissions):
	b = ReadBoundary([po(custom_oa_purchase_expense="OA-1")], [oa()], export=export_permissions)
	with pytest.raises(PermissionError):
		connect(monkeypatch, b).export_unified_purchase_list()
	assert b.response == {}


def test_export_builder_uses_complete_same_filtered_result_and_selected_columns():
	s = backend()
	rows = [po("PO-2", grand_total=2), po("PO-1", grand_total=1), po("PO-3", company="Other")]
	result = s.build_unified_purchase_payload(rows, [], filters={"company": "Yuewei"}, page_length=1)
	data = s.build_unified_purchase_export(
		rows, [], filters={"company": "Yuewei"}, columns=["name", "grand_total", "party_account_currency"],
	)
	assert result["total_count"] == 2
	assert data == [["单号", "订单金额", "预付款币种"], ["PO-1", 1, "CNY"], ["PO-2", 2, "CNY"]]
	with pytest.raises(ValueError):
		s.build_unified_purchase_export(rows, [], columns=["process_instance_id"])


def test_export_builder_preserves_source_text_and_numeric_precision():
	s = backend()
	order = po(supplier_name="=1+1", project="https://example.test/source", grand_total=42.123456,
		custom_oa_purchase_expense="OA-1")
	request = oa(oa_code='=HYPERLINK("https://example.test","OA")', detail_total_amount=-7.890123)
	data = s.build_unified_purchase_export([order], [request],
		columns=["supplier_name", "oa_number", "grand_total", "oa_amount", "project"])
	assert data[1] == [order["supplier_name"], request["oa_code"], 42.123456, -7.890123, order["project"]]
	assert s.build_unified_purchase_payload([order], [request])["rows"][0]["supplier_name"] == "=1+1"


def test_export_structured_oa_references_keep_original_evidence_as_text():
	s = backend()
	order = po(custom_oa_purchase_expense="OA-1")
	request = oa(oa_code="=1+1", detail_total_amount=-7.890123)
	data = s.build_unified_purchase_export([order], [request], columns=["name", "oa_references"])
	assert data[0] == ["单号", "OA 来源明细"]
	assert isinstance(data[1][1], str)
	assert json.loads(data[1][1]) == [{
		"name": "OA-1", "number": "=1+1", "approval_status": "APPROVED", "amount": -7.890123,
		"currency": "CNY", "amount_basis": "采购明细合计", "company": "Yuewei", "warning": None,
	}]
	assert "采购明细合计" in data[1][1]


def test_export_xlsx_preserves_literal_formula_and_url_strings(monkeypatch):
	# Exercise the real installed Frappe XLSX implementation; pure environments skip only this integration.
	xlsxutils = pytest.importorskip("frappe.utils.xlsxutils")
	openpyxl = pytest.importorskip("openpyxl")
	monkeypatch.setattr(xlsxutils.XLSXStyleBuilder, "get_datetime_format", lambda: "yyyy-mm-dd hh:mm:ss")
	order = po(supplier_name='=IF(1<2,"<b>literal</b>","")', project="<b>https://example.test/source</b>", grand_total=42.123456,
		custom_oa_purchase_expense="OA-1")
	request = oa(oa_code='=HYPERLINK("https://example.test","OA")', detail_total_amount=-7.890123)
	b = ReadBoundary([order], [request])
	s = connect(monkeypatch, b)
	s.export_unified_purchase_list(columns=["supplier_name", "oa_number", "grand_total", "oa_amount", "project", "oa_references"])
	with ZipFile(BytesIO(b.response["filecontent"])) as archive:
		root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
		ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
		assert root.findall(".//x:f", ns) == []
		assert root.findall(".//x:hyperlink", ns) == []
	workbook = openpyxl.load_workbook(BytesIO(b.response["filecontent"]), data_only=False)
	sheet = workbook.active
	assert [sheet.cell(2, index).value for index in range(1, 6)] == [
		order["supplier_name"], request["oa_code"], 42.123456, -7.890123, order["project"],
	]
	assert [sheet.cell(2, index).data_type for index in range(1, 6)] == ["s", "s", "n", "n", "s"]
	assert sheet.cell(2, 6).data_type == "s"
	assert json.loads(sheet.cell(2, 6).value)[0]["amount"] == -7.890123
	assert json.loads(sheet.cell(2, 6).value)[0]["number"] == request["oa_code"]


def test_export_download_calls_frappe_xlsx_without_pagination_or_business_writes(monkeypatch):
	b = ReadBoundary([po("PO-2"), po("PO-1")], [], oa_installed=False)
	s = connect(monkeypatch, b)
	class WorkbookBoundary:
		def __init__(self, output, options):
			self.output = output
			assert options["strings_to_formulas"] is False
			assert options["strings_to_urls"] is False

		def __enter__(self):
			return self

		def __exit__(self, *_args):
			self.output.write(repr(self.data).encode())

	module = SimpleNamespace(make_xlsx=lambda data, sheet_name, wb: setattr(wb, "data", (data, sheet_name)))
	monkeypatch.setitem(__import__("sys").modules, "frappe.utils.xlsxutils", module)
	monkeypatch.setitem(__import__("sys").modules, "xlsxwriter", SimpleNamespace(Workbook=WorkbookBoundary))
	s.export_unified_purchase_list(columns='["name"]')
	assert b.response["filename"].endswith(".xlsx")
	assert b.response["type"] == "binary"
	assert b"PO-1" in b.response["filecontent"] and b"PO-2" in b.response["filecontent"]
