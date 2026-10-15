import copy
import importlib
import unittest
from datetime import UTC
from decimal import Decimal

from deeplinkerp_branding.services import purchase_source_contract


def source(**values):
	return dict(
		{
			"corp_id": "corp-mx",
			"process_code": purchase_source_contract.PROCESS_CODES[0],
			"process_instance_id": "instance-1",
			"eligible": True,
			"status": "COMPLETED",
			"result": "agree",
			"apply_date": "2026-09-25",
			"region": "墨西哥Mexico",
			"department": "墨西哥模具BU",
			"currency": "MXN",
			"purchasing_company": "Mexico Buyer",
			"supplier": "Settlement Supplier",
			"schedule_date": "2026-10-31",
			"requested_amount": "100",
			"detail_total_amount": "100",
			"items": [{"item_code": "STEEL", "item_name": "钢料", "qty": "2", "uom": "Kg", "amount": "100"}],
			"processors": [],
			"issues": [],
			"version": "immutable-source-version",
		},
		**values,
	)


def processing_rows():
	values = (
		("A", "4630", "0.64"),
		("B", "1050", "0.64"),
		("C", "600", "0.64"),
		("A", "3520", "0.64"),
		("D", "100", "0.70"),
		("B", "250", "0.70"),
	)
	return [
		{
			"processor_name": name,
			"processing_materials": f"模具-{index}",
			"odt": f"ODT-{index}",
			"sales_order_no": f"SO-{index}",
			"qty": qty,
			"rate": rate,
			"amount": str(Decimal(qty) * Decimal(rate)),
			"source_row_key": f"row-{index}",
		}
		for index, (name, qty, rate) in enumerate(values, 1)
	]


class PurchaseSourceAdaptationTest(unittest.TestCase):
	def setUp(self):
		try:
			self.module = importlib.import_module("deeplinkerp_branding.services.purchase_source_adaptation")
		except ModuleNotFoundError:
			self.module = None
		self.assertIsNotNone(self.module, "采购来源适配计划尚未实现")

	def rule(self, value, **changes):
		return dict(
			{
				"scope_key": self.module.scope_key(self.module.scope(value)),
				"enabled": 1,
				"company": "Mexico Buyer",
				"supplier": "Settlement Supplier",
				"item_group": "加工服务",
				"purchase_uom": "Nos",
			},
			**changes,
		)

	def assert_blocked(self, plan, text):
		self.assertIn(text, "；".join(plan["blocking_reasons"]))

	def test_six_processing_lines_keep_four_processors_under_one_supplier_and_6517_mxn(self):
		value = source(
			items=[],
			processors=processing_rows(),
			requested_amount="6517",
			detail_total_amount="6517",
			issues=["采购明细待完善"],
		)
		before = copy.deepcopy(value)
		plan = self.module.build_plan(value, self.rule(value))
		self.assertEqual(plan["blocking_reasons"], [])
		self.assertEqual(
			(plan["company"], plan["supplier"], plan["currency"], plan["total_amount"]),
			("Mexico Buyer", "Settlement Supplier", "MXN", "6517.00"),
		)
		self.assertEqual(len(plan["items"]), 6)
		self.assertEqual({row["processor_name"] for row in plan["items"]}, {"A", "B", "C", "D"})
		for original, item in zip(value["processors"], plan["items"], strict=True):
			for key in (
				"processor_name",
				"processing_materials",
				"odt",
				"sales_order_no",
				"qty",
				"rate",
				"amount",
				"source_row_key",
			):
				self.assertEqual(item[key], original[key])
			self.assertEqual(
				(
					item["item_code"],
					item["item_name"],
					item["is_stock_item"],
					item["uom"],
					item["item_group"],
				),
				("DLP-SVC-PROCESSING", "加工服务", 0, "Nos", "加工服务"),
			)
			for detail in (
				original["processor_name"],
				original["processing_materials"],
				original["odt"],
				original["sales_order_no"],
			):
				self.assertIn(detail, item["description"])
		self.assertEqual(value, before)
		self.assertEqual(value["version"], "immutable-source-version")
		self.assertNotEqual(plan["version"], value["version"])
		self.assertEqual(plan["version"], self.module.build_plan(value, self.rule(value))["version"])

	def test_scope_is_canonical_exact_and_includes_purchase_type_and_explicit_organization(self):
		value = source()
		expected = {
			"corp_id": "corp-mx",
			"process_code": value["process_code"],
			"execution_region": "墨西哥",
			"source_organization": "墨西哥模具BU",
			"purchase_type": "goods",
		}
		self.assertEqual(self.module.scope(value), expected)
		key = self.module.scope_key(expected)
		self.assertEqual(len(key), 64)
		self.assertEqual(key, self.module.scope_key(dict(reversed(list(expected.items())))))
		for field in expected:
			with self.subTest(field=field):
				with self.assertRaises(ValueError):
					self.module.scope_key({**expected, field: ""})
				self.assertNotEqual(key, self.module.scope_key({**expected, field: expected[field] + "2"}))
		for region in ("中国China", "China", "中国"):
			self.assertEqual(self.module.scope(source(region=region))["execution_region"], "中国")
		self.assertEqual(
			self.module.scope(source(items=[], processors=processing_rows()))["purchase_type"], "processing"
		)
		self.assertEqual(self.module.scope(source(processors=processing_rows()))["purchase_type"], "mixed")
		self.assertEqual(self.module.scope(source(items=[]))["purchase_type"], "unknown")
		self.assertEqual(self.module.scope(source(department={"name": "BU"}))["source_organization"], "")

	def test_rules_fill_only_missing_roles_for_the_exact_enabled_scope(self):
		value = source(
			items=[],
			processors=processing_rows(),
			requested_amount="6517",
			purchasing_company=None,
			supplier=None,
		)
		rule = self.rule(value)
		self.assertEqual(self.module.build_plan(value, rule)["blocking_reasons"], [])
		for patch in ({"enabled": 0}, {"scope_key": "other"}):
			with self.subTest(patch=patch):
				self.assert_blocked(self.module.build_plan(value, {**rule, **patch}), "规则")
		self.assert_blocked(self.module.build_plan({**value, "department": "Other"}, rule), "规则")
		self.assert_blocked(self.module.build_plan({**value, "department": None}, rule), "组织")
		for field, role in (("purchasing_company", "采购公司"), ("supplier", "供应商")):
			with self.subTest(field=field):
				self.assert_blocked(self.module.build_plan({**value, field: "Conflicting"}, rule), role)
				self.assert_blocked(
					self.module.build_plan({**value, field + "_status": "ambiguous"}, rule), role
				)

	def test_processors_cannot_supply_settlement_supplier_or_unconfirmed_service_master_data(self):
		value = source(items=[], processors=processing_rows(), requested_amount="6517", supplier=None)
		self.assertIsNone(self.module.build_plan(value)["supplier"])
		self.assert_blocked(self.module.build_plan(value), "供应商")
		for field in ("item_group", "purchase_uom"):
			with self.subTest(field=field):
				self.assert_blocked(self.module.build_plan(value, self.rule(value, **{field: ""})), "加工")
		plan = self.module.build_plan(
			value, self.rule(value, service_item_code="PROCESS", service_item_name="外协加工")
		)
		self.assertEqual(plan["blocking_reasons"], [])
		self.assertEqual(
			(plan["items"][0]["item_code"], plan["items"][0]["item_name"]), ("PROCESS", "外协加工")
		)

	def test_processor_rows_accept_flat_aliases_and_delegate_only_envelope_rows(self):
		flat = {
			"加工商名称Nombre": "A",
			"加工材料Material": "钢料",
			"ODT": "ODT-1",
			"销售订单": "SO-1",
			"数量Cantidad": "2",
			"单价Precio": "50",
			"金额Importe": "100",
			"单位Unidad": "Nos",
			"source_row_key": "rk",
		}
		before = copy.deepcopy(flat)
		normalized = self.module.processor_rows([flat])[0]
		self.assertEqual(
			normalized,
			{
				"processor_name": "A",
				"processing_materials": "钢料",
				"odt": "ODT-1",
				"sales_order_no": "SO-1",
				"qty": "2",
				"rate": "50",
				"amount": "100",
				"uom": "Nos",
				"source_row_key": "rk",
			},
		)
		self.assertEqual(flat, before)
		calls = []
		envelopes = [{"rowValue": [{"label": "加工商", "value": "A"}]}, [{"label": "加工商", "value": "B"}]]

		def flatten(raw):
			calls.append(raw)
			return flat

		rows = self.module.processor_rows(envelopes, flatten_row=flatten)
		self.assertEqual(calls, [envelopes[0], {"rowValue": envelopes[1]}])
		self.assertEqual(len(rows), 2)
		for value in (
			envelopes,
			"not json",
			{"rows": [flat]},
			[{"processor_name": "A", "qty": "2", "数量": "2"}],
		):
			with self.subTest(value=value):
				with self.assertRaises(ValueError):
					self.module.processor_rows(value)

	def test_processor_phone_is_not_a_second_name_and_envelope_row_identity_survives_flattening(self):
		row = {
			"加工商名称Nombre": "A",
			"加工商电话Teléfono": "555-0000",
			"加工材料": "钢料",
			"数量": "2",
			"单价": "50",
			"金额": "100",
		}
		self.assertEqual(self.module.processor_rows([row])[0]["processor_name"], "A")
		envelope = {"rowId": "original-row-id", "rowValue": [{"label": "加工商", "value": "A"}]}
		before = copy.deepcopy(envelope)

		def flatten(value):
			value["rowValue"].clear()
			return row

		result = self.module.processor_rows([envelope], flatten_row=flatten)
		self.assertEqual(result[0]["source_row_key"], "original-row-id")
		self.assertEqual(envelope, before)

	def test_arithmetic_preserves_source_decimal_precision_without_accepting_rounded_mismatches(self):
		rate = "1." + "0" * 210 + "1"
		amount = "2." + "0" * 210 + "2"
		row = {**source()["items"][0], "rate": rate, "amount": None}
		plan = self.module.build_plan(source(items=[row], requested_amount=amount))
		self.assertEqual(plan["blocking_reasons"], [])
		self.assertEqual(plan["items"][0]["amount"], amount)
		self.assertEqual(plan["total_amount"], amount)
		rounded = self.module.build_plan(source(items=[{**row, "amount": "2"}], requested_amount="2"))
		self.assert_blocked(rounded, "金额不一致")

	def test_approved_bilingual_dingtalk_row_uses_shared_flattened_values_and_original_row_number(self):
		flat = {
			"加工商名字Nombre del proveedor de servicios de procesam": "Procesador A",
			"加工商电话Teléfono del proveedor de servicios de proces": "555-0000",
			"ODT": "ODT-MX-1",
			"销售订单号码El número de la orden de venta": "SO-MX-1",
			"加工物料Materiales de Procesamiento": "Molde A",
			"数量Cantidad": "2",
			"单价Precio Unitario": "50",
			"总金额Monto Total": "100",
			"_dingtalk_row_number": 7,
		}
		envelope = {"rowNumber": 7, "rowValue": [{"label": "数量Cantidad", "value": "2"}]}
		calls = []

		def shared_flattened_values(value):
			calls.append(value)
			return flat

		rows = self.module.processor_rows([envelope], flatten_row=shared_flattened_values)
		self.assertEqual(calls, [envelope])
		self.assertEqual(rows[0]["processor_name"], "Procesador A")
		self.assertEqual(rows[0]["sales_order_no"], "SO-MX-1")
		self.assertEqual(rows[0]["_dingtalk_row_number"], 7)
		self.assertEqual(rows[0]["source_row_key"], "processors:7")
		value = source(items=[], processors=[envelope])
		plan = self.module.build_plan(value, self.rule(value), processors=rows)
		self.assertEqual(plan["blocking_reasons"], [])
		self.assertEqual(plan["items"][0]["_dingtalk_row_number"], 7)
		self.assertEqual(plan["items"][0]["processing_materials"], "Molde A")

	def test_unapproved_and_outside_cutoff_sources_are_blocked_despite_eligible_hint(self):
		for patch in (
			{"status": "RUNNING"},
			{"result": "refuse"},
			{"eligible": False},
			{"deleted_at": "2026-10-01"},
			{"apply_date": "2026-09-24"},
			{"apply_date": "2027-01-01"},
			{"apply_date": "invalid"},
			{"process_code": "other"},
			{"region": "USA"},
			{"instance_count": 2},
			{"business_count": 2},
		):
			with self.subTest(patch=patch):
				self.assertTrue(self.module.build_plan(source(**patch))["blocking_reasons"])
		self.assertEqual(self.module.build_plan(source())["blocking_reasons"], [])

	def test_goods_preserve_source_values_and_derive_only_exact_missing_prices_or_amounts(self):
		for raw, amount, rate in (
			({"qty": "2.5", "amount": "100.00"}, "100.00", "40"),
			({"qty": "2.5", "rate": "40"}, "100.0", "40"),
			({"qty": "2.5", "rate": "0", "amount": "0"}, "0", "0"),
		):
			with self.subTest(raw=raw):
				item = {
					"item_code": "STEEL",
					"item_name": "钢料",
					"uom": "Kg",
					"source_row_key": "goods-row",
					**raw,
				}
				value = source(items=[item], requested_amount=amount)
				before = copy.deepcopy(value)
				plan = self.module.build_plan(value)
				self.assertEqual(plan["blocking_reasons"], [])
				result = plan["items"][0]
				self.assertEqual((result["qty"], result["amount"], result["rate"]), ("2.5", amount, rate))
				self.assertEqual(
					(
						result["item_code"],
						result["item_name"],
						result["uom"],
						result["source_row_key"],
						result["is_stock_item"],
					),
					("STEEL", "钢料", "Kg", "goods-row", 1),
				)
				self.assertEqual(value, before)

	def test_missing_invalid_zero_quantity_or_inconsistent_numbers_are_never_guessed(self):
		invalids = (
			{"qty": None},
			{"qty": "0"},
			{"qty": "-1"},
			{"qty": "invalid"},
			{"amount": None},
			{"amount": "invalid"},
			{"amount": "-1"},
			{"rate": "invalid"},
			{"rate": "-1"},
			{"rate_invalid": True},
			{"rate": "49"},
			{"qty": "3", "amount": "100"},
		)
		for processing in (False, True):
			for patch in invalids:
				with self.subTest(processing=processing, patch=patch):
					if processing:
						row = {**processing_rows()[0], **patch}
						if patch.get("amount", "present") is None:
							row.pop("rate")
						value = source(items=[], processors=[row], requested_amount="1000")
						plan = self.module.build_plan(value, self.rule(value))
					else:
						row = {**source()["items"][0], **patch}
						plan = self.module.build_plan(source(items=[row]))
					self.assertTrue(plan["blocking_reasons"])

	def test_mixed_rows_keep_independent_lines_and_recompute_old_goods_only_issue(self):
		processor = {**processing_rows()[0], "qty": "2", "rate": "25", "amount": "50"}
		value = source(
			processors=[processor], requested_amount="150", issues=["采购明细与申请金额不一致，请核对原单"]
		)
		plan = self.module.build_plan(value, self.rule(value))
		self.assertEqual(plan["blocking_reasons"], [])
		self.assertEqual((len(plan["items"]), plan["total_amount"]), (2, "150"))
		self.assertEqual([row["is_stock_item"] for row in plan["items"]], [1, 0])
		self.assert_blocked(
			self.module.build_plan({**value, "requested_amount": "151"}, self.rule(value)), "金额不一致"
		)
		self.assert_blocked(
			self.module.build_plan({**value, "issues": ["来源存在冲突"]}, self.rule(value)), "来源存在冲突"
		)

	def test_duplicate_or_overlapping_goods_and_processing_billing_is_blocked_without_merging(self):
		processor = {
			**processing_rows()[0],
			"processing_materials": "钢料",
			"qty": "2",
			"rate": "50",
			"amount": "100",
		}
		value = source(processors=[processor], requested_amount="200")
		plan = self.module.build_plan(value, self.rule(value))
		self.assertEqual(len(plan["items"]), 2)
		self.assert_blocked(plan, "重复计费")
		duplicate = source(items=[], processors=[processor, copy.deepcopy(processor)], requested_amount="200")
		self.assert_blocked(self.module.build_plan(duplicate, self.rule(duplicate)), "重复")

	def test_unsupported_tables_and_missing_purchasable_rows_report_specific_reasons(self):
		self.assert_blocked(self.module.build_plan(source(items=[], processors=[])), "可采购明细")
		self.assert_blocked(
			self.module.build_plan(source(items=[], processors="legacy free text")), "加工商明细格式"
		)
		value = source(
			items=[], processors=None, original_fields={"processors": [processing_rows(), processing_rows()]}
		)
		self.assert_blocked(self.module.build_plan(value), "加工商明细存在多个")

	def test_processing_duplicates_compare_numeric_values_independent_of_decimal_formatting(self):
		first = {**processing_rows()[0], "qty": "2", "rate": "50", "amount": "100"}
		second = {**first, "qty": "2.0", "amount": "100.00", "source_row_key": "different-row"}
		value = source(items=[], processors=[first, second], requested_amount="200")
		plan = self.module.build_plan(value, self.rule(value))
		self.assertEqual(len(plan["items"]), 2)
		self.assert_blocked(plan, "重复计费")

	def test_multiple_requirement_controls_cannot_be_ignored_when_processing_matches_total(self):
		from datetime import datetime, timezone

		from tests.test_purchase_source_contract import source as raw_source

		row = raw_source(create_time=datetime(2026, 9, 25, tzinfo=UTC))
		row["form_component_values"].extend(
			[
				{"name": "采购公司", "value": "Mexico Buyer"},
				{"name": "供应商", "value": "Settlement Supplier"},
				{"name": "申请部门/组织", "value": "Original BU"},
				{"name": "交付日期", "value": "2026-10-31"},
				{
					"name": "加工商明细",
					"value": [{**processing_rows()[0], "qty": "2", "rate": "50", "amount": "100"}],
				},
			]
		)
		row["form_component_values"].append(copy.deepcopy(row["form_component_values"][4]))
		value = purchase_source_contract.normalize(row)
		self.assertEqual(value["items"], [])
		self.assertEqual(value["issues"], ["采购明细待完善"])
		before = copy.deepcopy(value)
		plan = self.module.build_plan(value, self.rule(value))
		self.assert_blocked(plan, "需求明细存在多个")
		self.assertEqual(value, before)

	def test_original_department_snapshot_fills_missing_organization_without_changing_source_version(self):
		value = source(
			department=None,
			adaptation_context={"originator_dept_id": "12345", "originator_dept_name": " 原申请部门 "},
		)
		before = copy.deepcopy(value)
		current = self.module.scope(value)
		self.assertEqual(current["source_organization"], "dept:12345")
		key = self.module.scope_key(current)
		renamed = {
			**value,
			"adaptation_context": {**value["adaptation_context"], "originator_dept_name": "Renamed"},
		}
		self.assertEqual(self.module.scope_key(self.module.scope(renamed)), key)
		changed_id = {
			**value,
			"adaptation_context": {**value["adaptation_context"], "originator_dept_id": "54321"},
		}
		self.assertNotEqual(self.module.scope_key(self.module.scope(changed_id)), key)
		self.assertEqual(
			self.module.scope({**value, "department": "Explicit organization"})["source_organization"],
			"Explicit organization",
		)
		name_only = {**value, "adaptation_context": {"originator_dept_name": " 原申请部门 "}}
		self.assertEqual(self.module.scope(name_only)["source_organization"], "dept-name: 原申请部门 ")
		missing = {**value, "adaptation_context": {}}
		with self.assertRaises(ValueError):
			self.module.scope_key(self.module.scope(missing))
		self.assert_blocked(self.module.build_plan(missing, self.rule(value)), "组织")
		self.assertEqual(value, before)

	def test_old_schedule_date_uses_application_date_and_audit_note_on_every_line(self):
		processor = {**processing_rows()[0], "qty": "2", "rate": "25", "amount": "50"}
		value = source(schedule_date="2026-09-20", processors=[processor], requested_amount="150")
		before = copy.deepcopy(value)
		plan = self.module.build_plan(value, self.rule(value))
		self.assertEqual(plan["blocking_reasons"], [])
		self.assertEqual(plan["schedule_date"], "2026-09-25")
		note = "原需求日期 2026-09-20 早于申请日期 2026-09-25，草稿需求日期按申请日期 2026-09-25"
		self.assertEqual(plan["date_adjustment"], note)
		for item in plan["items"]:
			self.assertIn(note, item["description"])
		self.assertEqual(value, before)
		for schedule in ("2026-09-25", "2026-10-31"):
			kept = self.module.build_plan(source(schedule_date=schedule))
			self.assertEqual(kept["schedule_date"], schedule)
			self.assertFalse(kept.get("date_adjustment"))


if __name__ == "__main__":
	unittest.main()
