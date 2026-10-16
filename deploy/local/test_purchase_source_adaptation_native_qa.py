"""Real ERPNext integration checks on one isolated synthetic database only.

Load after frappe.init/connect/set_user; only upstream snapshot reads are stubbed.
The master-data seed may commit. Every test rolls back its own business writes.
"""

import json
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import frappe

from deeplinkerp_branding.services import purchase_source_adaptation as adaptation
from deeplinkerp_branding.services import purchase_source_contract as contract
from deeplinkerp_branding.services import purchase_source_rules as rules
from deeplinkerp_branding.services import purchase_source_service as service

SITE = "purchase-source-adaptation-qa.localhost"
COMPANY = "QA Source MX"
GROUP = "QA Source Services"
PRICE_LIST = "QA Source Buying MXN"
PROTECTED = (
	"Purchase Receipt",
	"Purchase Invoice",
	"Payment Entry",
	"Journal Entry",
	"GL Entry",
	"Stock Entry",
	"Stock Ledger Entry",
	"Item Price",
)


def guard_site():
	if frappe.local.site != SITE or frappe.conf.db_host != "db":
		raise RuntimeError("Dedicated purchase-source-adaptation synthetic QA site only")


def seed():
	"""Bootstrap a minimal native ERP, without copying another site's business data."""
	guard_site()
	frappe.set_user("Administrator")
	if any(frappe.db.count(dt) for dt in PROTECTED[:-1]):
		raise RuntimeError("Synthetic QA site must remain unposted")
	if not frappe.db.exists("DocType", service.DOCTYPE):
		from oa_purchase_request.install import create_or_update_oa_purchase_request

		create_or_update_oa_purchase_request()
	from deeplinkerp_branding.purchase_source_install import after_migrate

	after_migrate()
	frappe.db.commit()  # Metadata-only installation precedes native business leases.
	from deeplinkerp_branding.purchase_reversal_install import after_migrate as reversal_metadata

	reversal_metadata()
	if not frappe.db.exists("Warehouse Type", "Transit"):
		frappe.get_doc({"doctype": "Warehouse Type", "warehouse_type": "Transit"}).insert()
	if not frappe.db.exists("Company", COMPANY):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": COMPANY,
				"abbr": "QASMX",
				"default_currency": "MXN",
				"country": "Mexico",
				"chart_of_accounts": "Standard",
				"create_chart_of_accounts_based_on": "Standard Template",
			}
		).insert()
	company = frappe.get_doc("Company", COMPANY)
	if company.default_currency != "MXN" or company.abbr != "QASMX":
		raise RuntimeError("Unexpected synthetic company configuration")
	if not frappe.db.exists("Item Group", GROUP):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": GROUP,
				"parent_item_group": "All Item Groups",
				"is_group": 0,
			}
		).insert()
	if not frappe.db.exists("Supplier Group", "QA Source Suppliers"):
		frappe.get_doc(
			{
				"doctype": "Supplier Group",
				"supplier_group_name": "QA Source Suppliers",
				"parent_supplier_group": "All Supplier Groups",
				"is_group": 0,
			}
		).insert()
	if not frappe.db.exists("Price List", PRICE_LIST):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": PRICE_LIST,
				"currency": "MXN",
				"buying": 1,
				"selling": 0,
				"enabled": 1,
			}
		).insert()
	if not frappe.db.exists("Supplier", rules.TEMP_SETTLEMENT_SUPPLIER):
		frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": rules.TEMP_SETTLEMENT_SUPPLIER,
				"supplier_group": "QA Source Suppliers",
				"supplier_type": "Company",
				"country": "Mexico",
				"default_currency": "MXN",
				"default_price_list": PRICE_LIST,
			}
		).insert()
	if not frappe.db.exists("Fiscal Year", "2026"):
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": "2026",
				"year_start_date": "2026-01-01",
				"year_end_date": "2026-12-31",
			}
		).insert()
	for doctype, values in (
		(
			"Global Defaults",
			{"default_company": COMPANY, "default_currency": "MXN", "current_fiscal_year": "2026"},
		),
		(
			"Buying Settings",
			{
				"supplier_group": "QA Source Suppliers",
				"buying_price_list": PRICE_LIST,
				"allow_multiple_items": 1,
				"bill_for_rejected_quantity_in_purchase_invoice": 0,
			},
		),
		(
			"Stock Settings",
			{
				"item_group": GROUP,
				"stock_uom": "Nos",
				"item_naming_by": "Item Code",
				"default_warehouse": "Stores - QASMX",
				"auto_insert_price_list_rate_if_missing": 0,
				"update_existing_price_list_rate": 0,
			},
		),
	):
		meta = frappe.get_meta(doctype)
		frappe.db.set_single_value(
			doctype, {key: value for key, value in values.items() if meta.has_field(key)}
		)
		frappe.clear_document_cache(doctype)
	frappe.defaults.set_global_default("company", COMPANY)
	frappe.db.commit()  # Synthetic masters only; never source/Item/PO test artifacts.
	frappe.clear_cache()


def fixture(suffix="SIX", *, department="QA-MX-ORIGINAL-DEPT"):
	quantities = (4630, 1050, 600, 3520, 100, 250)
	rates = tuple(Decimal(value) for value in ("0.64", "0.64", "0.64", "0.64", "0.70", "0.70"))
	processors = (
		"QA Processor A",
		"QA Processor A",
		"QA Processor B",
		"QA Processor C",
		"QA Processor C",
		"QA Processor D",
	)
	table = []
	for index, (qty, rate, processor) in enumerate(zip(quantities, rates, processors, strict=True), 1):
		table.append(
			{
				"rowValue": [
					{"label": "加工商名称", "value": processor},
					{"label": "加工材料", "value": "SUPER CAPITAN" if index <= 4 else "TITANIO"},
					{"label": "ODT工单", "value": "QA-ODT-" + str(index)},
					{"label": "销售单号", "value": "QA-SO-" + str(index)},
					{"label": "加工数量", "value": str(qty)},
					{"label": "加工单价", "value": str(rate)},
					{"label": "加工金额", "value": str(qty * rate)},
				]
			}
		)
	raw = {
		"corp_id": "QA-SOURCE-ADAPTATION",
		"process_instance_id": "QA-ADAPT-" + suffix,
		"business_id": "QA-SOURCE-" + suffix,
		"process_code": contract.PROCESS_CODES[0],
		"status": "COMPLETED",
		"result": "agree",
		"originator_user_name": "QA Source Applicant",
		"originator_dept_id": department,
		"create_time": datetime(2026, 10, 8, tzinfo=UTC),
		"updated_at": datetime(2026, 10, 8, tzinfo=UTC),
		"form_component_values": [
			{"name": "执行地区", "value": "墨西哥Mexico"},
			{"name": "币种", "value": "MXN"},
			{"name": "金额importe", "value": "6517"},
			{"name": "交付日期", "value": "2026-10-05"},
			{"name": "其他采购说明", "value": "QA synthetic processing draft only"},
			{"name": "加工商明细", "componentType": "TableField", "value": json.dumps(table)},
		],
	}
	source = service._normalize(raw)
	evidence = contract.payment_evidence(
		source,
		[
			{
				"source_id": "QA-PROOF-" + suffix,
				"source_type": "purchase",
				"corp_id": source["corp_id"],
				"process_instance_id": source["process_instance_id"],
				"currency": "MXN",
				"paid_amount": "0",
				"payment_evidence_status": "recorded",
				"payments": [],
				"attachments": [],
			}
		],
	)
	return source, evidence, raw


def mapping(**changes):
	return {
		"company": COMPANY,
		"supplier": rules.TEMP_SETTLEMENT_SUPPLIER,
		"item_group": GROUP,
		"purchase_uom": "Nos",
		**changes,
	}


def confirm(source, evidence, **changes):
	name = service._cache_source(source, evidence, COMPANY)
	doc = frappe.get_doc(service.DOCTYPE, name)
	values = mapping(**changes)
	plan = rules.preview(source, evidence, doc=doc, candidate=values)
	if plan["blocking_reasons"]:
		raise AssertionError(plan["blocking_reasons"])
	with patch.object(service, "_fresh_source", return_value=(source, evidence)):
		result = service.confirm_purchase_source_rule(name, values, plan["preview_fingerprint"])
	return name, result


def sync(*snapshots):
	with patch.object(service, "_read_sync_snapshot", return_value=(list(snapshots), len(snapshots))):
		return service.sync_purchase_sources()


def seed_browser_fixture():
	"""Explicit opt-in: retain exactly one QA source/draft for local browser acceptance."""
	guard_site()
	seed()
	from deeplinkerp_branding.services.purchase_repost_boundary import initialize

	initialize()
	source, evidence, _ = fixture("BROWSER", department="QA-BROWSER-ORIGINAL-DEPT")
	cached = service._cached_doc(source)
	if not cached or not cached.purchase_order:
		name, _ = confirm(
			source,
			evidence,
			service_item_code="QA-ADAPT-BROWSER-SERVICE",
			service_item_name="QA 浏览器加工服务",
		)
		result = sync((source, evidence, COMPANY))
		if result.get("created") != 1 or result.get("new_items") != 1:
			raise AssertionError(result)
		cached = frappe.get_doc(service.DOCTYPE, name)
		frappe.db.commit()
	order = frappe.get_doc("Purchase Order", cached.purchase_order)
	assert order.docstatus == 0 and order.supplier == rules.TEMP_SETTLEMENT_SUPPLIER
	return {
		"site": SITE,
		"source": cached.name,
		"purchase_order": order.name,
		"business_id": source["business_id"],
		"item": order.items[0].item_code,
		"rows": len(order.items),
		"amount": str(order.grand_total),
		"currency": order.currency,
	}


class NativePurchaseSourceAdaptationQA(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		seed()

	def setUp(self):
		guard_site()
		frappe.set_user("Administrator")
		from deeplinkerp_branding.services.purchase_repost_boundary import initialize

		initialize()
		self.source, self.evidence, self.raw = fixture(self._testMethodName)
		self.before = {
			dt: frappe.db.count(dt)
			for dt in (*PROTECTED, "Item", "Purchase Order", service.DOCTYPE, "Integration Request")
		}

	def test_manual_adopted_draft_uses_original_application_date_and_retains_date_explanation(self):
		name, _ = confirm(self.source, self.evidence)
		with patch.object(service, "_fresh_source", return_value=(self.source, self.evidence)):
			detail = service.get_purchase_source_detail(name, fresh=1)
			plan = detail["adaptation"]
			result = service.create_purchase_order_from_source(
				name,
				detail["creation_version"],
				COMPANY,
				rules.TEMP_SETTLEMENT_SUPPLIER,
				"MXN",
				plan["schedule_date"],
				plan["items"],
			)
		order = frappe.get_doc("Purchase Order", result["name"])
		self.assertEqual(str(order.transaction_date), self.source["apply_date"])
		self.assertEqual(str(order.schedule_date), self.source["apply_date"])
		self.assertEqual(Decimal(str(order.grand_total)), Decimal("6517"))
		self.assertIn("2026-10-05", order.items[0].description)
		self.assertEqual(order.docstatus, 0)
		self.assert_no_postings_or_prices()

	def tearDown(self):
		frappe.db.rollback()
		frappe.set_user("Administrator")
		frappe.clear_cache()

	def assert_no_postings_or_prices(self):
		for dt in PROTECTED:
			self.assertEqual(frappe.db.count(dt), self.before[dt], dt)

	def test_preview_and_confirm_only_save_rule_preserving_original_bound_version(self):
		original = deepcopy(self.source)
		old_raw = {key: value for key, value in self.raw.items() if key != "originator_dept_id"}
		self.assertEqual(service._normalize(old_raw)["version"], self.source["version"])
		name = service._cache_source(self.source, self.evidence, COMPANY)
		preview = rules.preview(self.source, self.evidence, candidate=mapping())
		self.assertFalse(preview["blocking_reasons"])
		self.assertEqual(len(preview["new_items"]), 1)
		self.assertEqual(preview["new_items"][0]["is_stock_item"], 0)
		self.assertEqual(preview["schedule_date"], "2026-10-08")
		self.assertEqual(self.source, original)
		confirm(self.source, self.evidence)
		cached = frappe.get_doc(service.DOCTYPE, name)
		self.assertFalse(cached.purchase_order)
		self.assertFalse(cached.get(service.BOUND_FIELD))
		self.assertEqual(json.loads(cached.get(service.SOURCE_FIELD)), original)
		self.assertEqual(frappe.db.count("Item"), self.before["Item"])
		self.assertEqual(frappe.db.count("Purchase Order"), self.before["Purchase Order"])
		self.assert_no_postings_or_prices()

	def test_six_native_rows_four_processors_6517_mxn_and_repeat_sync_reuses(self):
		name, _ = confirm(self.source, self.evidence)
		result = sync((self.source, self.evidence, COMPANY))
		self.assertEqual((result["created"], result["new_items"], result["pending"]), (1, 1, 0), result)
		cached = frappe.get_doc(service.DOCTYPE, name)
		order = frappe.get_doc("Purchase Order", cached.purchase_order)
		self.assertEqual(order.docstatus, 0)
		self.assertEqual(
			(order.company, order.supplier, order.currency), (COMPANY, rules.TEMP_SETTLEMENT_SUPPLIER, "MXN")
		)
		self.assertEqual(order.custom_oa_purchase_expense, name)
		self.assertEqual(len(order.items), 6)
		self.assertEqual(Decimal(str(order.grand_total)), Decimal("6517"))
		self.assertEqual(str(order.transaction_date), "2026-10-08")
		self.assertEqual(str(order.schedule_date), "2026-10-08")
		adopted = json.loads(cached.get(rules.ADOPTION_FIELD))
		self.assertEqual(len({row["processor_name"] for row in adopted["plan"]["items"]}), 4)
		for native, source_row in zip(order.items, adopted["plan"]["items"], strict=True):
			for key in ("qty", "rate", "amount"):
				self.assertEqual(Decimal(str(native.get(key))), Decimal(source_row[key]))
			for key in ("processor_name", "processing_materials", "odt", "sales_order_no"):
				self.assertIn(source_row[key], native.description)
			self.assertEqual(native.item_code, adaptation.SERVICE_ITEM_CODE)
			self.assertEqual(native.uom, "Nos")
			self.assertEqual(str(native.schedule_date), "2026-10-08")
		item = frappe.get_doc("Item", adaptation.SERVICE_ITEM_CODE)
		self.assertEqual(item.is_stock_item, 0)
		self.assertEqual(item.is_purchase_item, 1)
		self.assertEqual(item.stock_uom, "Nos")
		self.assertEqual(cached.get(service.BOUND_FIELD), self.source["version"])
		self.assertEqual(adopted["source_version"], self.source["version"])
		self.assertEqual(json.loads(cached.get(service.SOURCE_FIELD)), self.source)
		before_item, before_order = item.as_dict(), order.as_dict()
		repeated = sync((self.source, self.evidence, COMPANY))
		self.assertEqual((repeated["created"], repeated["new_items"], repeated["already_linked"]), (0, 0, 1))
		self.assertEqual(frappe.get_doc("Item", item.name).as_dict(), before_item)
		self.assertEqual(frappe.get_doc("Purchase Order", order.name).as_dict(), before_order)
		self.assertEqual(frappe.db.count("Item"), self.before["Item"] + 1)
		self.assertEqual(frappe.db.count("Purchase Order"), self.before["Purchase Order"] + 1)
		self.assert_no_postings_or_prices()

	def test_existing_service_item_is_reused_without_master_mutation(self):
		name, _ = confirm(self.source, self.evidence)
		rules.ensure_items(rules.preview(self.source, self.evidence))
		item_before = frappe.get_doc("Item", adaptation.SERVICE_ITEM_CODE).as_dict()
		result = sync((self.source, self.evidence, COMPANY))
		self.assertEqual((result["created"], result["new_items"]), (1, 0), result)
		self.assertTrue(frappe.db.get_value(service.DOCTYPE, name, "purchase_order"))
		self.assertEqual(frappe.get_doc("Item", adaptation.SERVICE_ITEM_CODE).as_dict(), item_before)
		self.assert_no_postings_or_prices()

	def test_explicit_goods_code_creates_one_native_stock_item_and_draft(self):
		raw = deepcopy(self.raw)
		raw["form_component_values"] = [
			row for row in raw["form_component_values"] if row["name"] != "加工商明细"
		]
		raw["form_component_values"].append(
			{
				"name": "需求明细",
				"componentType": "TableField",
				"value": json.dumps(
					[
						[
							{"name": "物品编码Código", "value": "QA-ADAPT-GOODS"},
							{
								"name": "物品名称Nombre del artículo",
								"value": "QA explicit synthetic material",
							},
							{"name": "数量Cantidad", "value": "1"},
							{"name": "单位Unidad", "value": "Nos"},
							{"name": "总金额Monto Total", "value": "6517"},
						]
					]
				),
			}
		)
		source = service._normalize(raw)
		evidence = contract.payment_evidence(source, [])
		name, _ = confirm(source, evidence)
		result = sync((source, evidence, COMPANY))
		self.assertEqual((result["created"], result["new_items"]), (1, 1), result)
		item = frappe.get_doc("Item", "QA-ADAPT-GOODS")
		self.assertEqual(item.is_stock_item, 1)
		self.assertEqual(item.stock_uom, "Nos")
		order = frappe.get_doc("Purchase Order", frappe.db.get_value(service.DOCTYPE, name, "purchase_order"))
		self.assertEqual(order.items[0].item_code, item.name)
		self.assertEqual(order.docstatus, 0)
		self.assertEqual(Decimal(str(order.grand_total)), Decimal("6517"))
		self.assert_no_postings_or_prices()

	def test_existing_conflicting_item_and_unconfirmed_other_department_stay_pending(self):
		name, _ = confirm(self.source, self.evidence)
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": adaptation.SERVICE_ITEM_CODE,
				"item_name": "QA existing stock material",
				"item_group": GROUP,
				"stock_uom": "Nos",
				"is_stock_item": 1,
			}
		).insert()
		original = frappe.get_doc("Item", item.name).as_dict()
		result = sync((self.source, self.evidence, COMPANY))
		self.assertEqual((result["created"], result["new_items"], result["pending"]), (0, 0, 1), result)
		self.assertIn("库存属性", result["outcomes"][0]["reason"])
		self.assertEqual(frappe.get_doc("Item", item.name).as_dict(), original)
		self.assertFalse(frappe.db.get_value(service.DOCTYPE, name, "purchase_order"))
		other, evidence, _ = fixture("OTHER-DEPARTMENT", department="QA-OTHER-DEPARTMENT")
		pending = sync((other, evidence, COMPANY))
		self.assertEqual(pending["created"], 0, pending)
		self.assertEqual(pending["pending"], 1)
		self.assertIn("采购公司", pending["outcomes"][0]["reason"])
		self.assertEqual(frappe.db.count("Purchase Order"), self.before["Purchase Order"])
		self.assert_no_postings_or_prices()

	def test_existing_item_price_cannot_be_overwritten_by_native_defaults(self):
		confirm(self.source, self.evidence)
		rules.ensure_items(rules.preview(self.source, self.evidence))
		price = frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": adaptation.SERVICE_ITEM_CODE,
				"price_list": PRICE_LIST,
				"buying": 1,
				"currency": "MXN",
				"uom": "Nos",
				"price_list_rate": 999,
				"valid_from": "2026-01-01",
			}
		).insert()
		before = frappe.get_doc("Item Price", price.name).as_dict()
		frappe.db.set_single_value(
			"Stock Settings",
			{"auto_insert_price_list_rate_if_missing": 1, "update_existing_price_list_rate": 1},
		)
		frappe.clear_document_cache("Stock Settings")
		result = sync((self.source, self.evidence, COMPANY))
		self.assertEqual((result["created"], result["new_items"], result["pending"]), (0, 0, 1), result)
		self.assertIn("自动更新", result["outcomes"][0]["reason"])
		self.assertEqual(frappe.get_doc("Item Price", price.name).as_dict(), before)
		self.assertEqual(frappe.db.count("Item Price"), self.before["Item Price"] + 1)
		self.assertEqual(frappe.db.count("Purchase Order"), self.before["Purchase Order"])
		for dt in PROTECTED[:-1]:
			self.assertEqual(frappe.db.count(dt), self.before[dt], dt)

	def test_temporary_supplier_is_blocked_by_real_native_submit(self):
		name, _ = confirm(self.source, self.evidence)
		result = sync((self.source, self.evidence, COMPANY))
		self.assertEqual(result["created"], 1, result)
		order = frappe.get_doc("Purchase Order", frappe.db.get_value(service.DOCTYPE, name, "purchase_order"))
		self.assertEqual(frappe.db.get_value("Purchase Order", order.name, "docstatus"), 0)
		with self.assertRaisesRegex(frappe.ValidationError, "临时结算供应商"):
			order.submit()
		# The native protected submit rolls back this entire uncommitted test transaction.
		self.assertFalse(frappe.db.exists("Purchase Order", {"name": order.name, "docstatus": 1}))
		self.assertEqual(frappe.db.count("Purchase Order"), self.before["Purchase Order"])
		self.assert_no_postings_or_prices()

	def test_native_price_defaults_leave_item_order_and_price_unchanged(self):
		name, _ = confirm(self.source, self.evidence)
		frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 1)
		frappe.clear_document_cache("Stock Settings")
		result = sync((self.source, self.evidence, COMPANY))
		self.assertEqual((result["created"], result["new_items"], result["pending"]), (0, 0, 1), result)
		self.assertIn("价格表", result["outcomes"][0]["reason"])
		self.assertFalse(frappe.db.exists("Item", adaptation.SERVICE_ITEM_CODE))
		self.assertFalse(frappe.db.get_value(service.DOCTYPE, name, "purchase_order"))
		self.assertEqual(frappe.db.count("Purchase Order"), self.before["Purchase Order"])
		self.assert_no_postings_or_prices()

	def test_second_source_identity_failure_rolls_back_first_real_item_po_and_links(self):
		confirm(self.source, self.evidence)
		other = deepcopy(self.source)
		other["corp_id"] = "QA-OTHER-CORP"
		other["oa_identity"]["corp_id"] = other["corp_id"]
		other["source_id"] = "QA-CONFLICTING-IDENTITY"
		other["version"] = contract.digest(other)
		observed = []

		def snapshots():
			yield self.source, self.evidence, COMPANY
			# Observe persisted native effects before the next upstream identity fails.
			observed.append(frappe.db.count("Purchase Order"))
			self.assertEqual(observed[-1], self.before["Purchase Order"] + 1)
			self.assertTrue(frappe.db.exists("Item", adaptation.SERVICE_ITEM_CODE))
			first = service._cached_doc(self.source)
			self.assertTrue(first.purchase_order)
			self.assertEqual(
				frappe.db.get_value("Purchase Order", first.purchase_order, "custom_oa_purchase_expense"),
				first.name,
			)
			yield other, self.evidence, COMPANY

		with patch.object(service, "_read_sync_snapshot", return_value=(snapshots(), 2)):
			result = service.sync_purchase_sources()
		self.assertTrue(observed)
		self.assertTrue(result["failed"], result)
		self.assertIn("身份冲突", result["error"])
		for dt, count in self.before.items():
			self.assertEqual(frappe.db.count(dt), count, dt)
		cached = service._cached_doc(self.source)
		self.assertIsNone(cached)
		self.assertFalse(frappe.db.exists("Item", adaptation.SERVICE_ITEM_CODE))

	def test_stale_preview_and_unprivileged_confirmation_never_create_rule_or_item(self):
		name = service._cache_source(self.source, self.evidence, COMPANY)
		values = mapping()
		preview = rules.preview(self.source, self.evidence, candidate=values)
		group = frappe.get_doc("Item Group", GROUP)
		group.item_group_name = GROUP
		group.save()
		with patch.object(service, "_fresh_source", return_value=(self.source, self.evidence)):
			with self.assertRaisesRegex(frappe.ValidationError, "重新预览"):
				service.confirm_purchase_source_rule(name, values, preview["preview_fingerprint"])
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			service.confirm_purchase_source_rule(name, values, preview["preview_fingerprint"])
		frappe.set_user("Administrator")
		self.assertFalse(rules.rule_for(self.source))
		self.assertEqual(frappe.db.count("Item"), self.before["Item"])
		self.assertEqual(frappe.db.count("Purchase Order"), self.before["Purchase Order"])
		self.assert_no_postings_or_prices()


if __name__ == "__main__":
	unittest.main()
