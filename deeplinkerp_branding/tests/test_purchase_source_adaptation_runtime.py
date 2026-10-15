"""Item adoption must preserve existing master data and source confirmation."""

import importlib
import json
import unittest
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch


class PurchaseSourceAdaptationRuntimeTests(unittest.TestCase):
	def setUp(self):
		try:
			self.runtime = importlib.import_module("deeplinkerp_branding.services.purchase_source_rules")
		except ModuleNotFoundError:
			self.runtime = None
		self.assertIsNotNone(self.runtime, "采购来源物料适配运行时尚未实现")
		self.spec = dict(
			item_code="DLP-SVC-PROCESSING",
			item_name="加工服务",
			is_stock_item=0,
			item_group="Services",
			uom="Nos",
			company="QA Company",
		)
		self.item = dict(
			name=self.spec["item_code"],
			disabled=0,
			is_purchase_item=1,
			is_stock_item=0,
			stock_uom="Nos",
			item_group="Services",
			uoms=[],
		)

	def test_existing_item_is_read_only_and_must_match_stock_unit_and_owner(self):
		before = deepcopy(self.item)
		self.runtime.validate_existing_item(self.spec, self.item)
		self.assertEqual(self.item, before)
		for changes in (
			{"disabled": 1},
			{"is_purchase_item": 0},
			{"is_stock_item": 1},
			{"stock_uom": "Kg"},
			{"custom_overseas_business_entity": "Other Company"},
		):
			with self.subTest(changes=changes), self.assertRaises(ValueError):
				self.runtime.validate_existing_item(self.spec, {**self.item, **changes})

	def test_alternate_purchase_unit_requires_an_explicit_positive_conversion(self):
		for factor in (None, 0, -1):
			with self.subTest(factor=factor), self.assertRaises(ValueError):
				self.runtime.validate_existing_item(
					{**self.spec, "uom": "Box"},
					{**self.item, "uoms": [dict(uom="Box", conversion_factor=factor)]},
				)
		self.runtime.validate_existing_item(
			{**self.spec, "uom": "Box"}, {**self.item, "uoms": [dict(uom="Box", conversion_factor=10)]}
		)

	def test_shared_service_item_is_created_once_for_six_rows_without_price_writes(self):
		plan = dict(company="QA Company", items=[deepcopy(self.spec) for _ in range(6)])
		created = Mock()
		created.name = self.spec["item_code"]
		created.meta.has_field.return_value = True
		with (
			patch.object(self.runtime, "read_item", return_value=None),
			patch.object(self.runtime, "check_item_creation"),
			patch.object(self.runtime, "_service", return_value=Mock()),
			patch.object(self.runtime.frappe, "new_doc", return_value=created) as new_doc,
		):
			result = self.runtime.ensure_items(plan)
		self.assertEqual(result, [self.spec["item_code"]])
		new_doc.assert_called_once_with("Item")
		created.insert.assert_called_once_with()
		self.assertEqual(created.is_stock_item, 0)
		self.assertEqual(created.stock_uom, "Nos")

	def test_existing_item_is_reused_without_insert_or_attribute_changes(self):
		plan = dict(company="QA Company", items=[deepcopy(self.spec)])
		with (
			patch.object(self.runtime, "read_item", return_value=deepcopy(self.item)),
			patch.object(self.runtime.frappe, "new_doc") as new_doc,
		):
			self.assertEqual(self.runtime.ensure_items(plan), [])
		new_doc.assert_not_called()

	def test_preview_fingerprint_serializes_real_item_dates_and_unit_children(self):
		service = self.runtime._service()
		plan = dict(
			items=[self.spec], company="QA Company", supplier="Supplier", currency="MXN", blocking_reasons=[]
		)
		item = {
			**self.item,
			"modified": datetime(2026, 10, 15),
			"uoms": [dict(uom="Nos", conversion_factor=1, modified=datetime(2026, 10, 15))],
		}
		with (
			patch.object(self.runtime, "rule_for", return_value=None),
			patch.object(self.runtime, "canonical_roles", return_value={}),
			patch.object(self.runtime, "processors", return_value=[]),
			patch(
				"deeplinkerp_branding.services.purchase_source_adaptation.build_plan",
				return_value=deepcopy(plan),
			),
			patch.object(
				service,
				"_native",
				side_effect=lambda dt, name: service.frappe._dict(name=name, modified=datetime(2026, 10, 15)),
			),
			patch.object(self.runtime, "read_item", return_value=item),
		):
			result = self.runtime.preview(dict(version="source"), dict(version="proof"))
		self.assertEqual(len(result["preview_fingerprint"]), 64)

	def test_conflicting_specs_for_one_item_never_create_anything(self):
		plan = dict(company="QA Company", items=[self.spec, {**self.spec, "is_stock_item": 1}])
		with patch.object(self.runtime.frappe, "new_doc") as new_doc, self.assertRaises(ValueError):
			self.runtime.ensure_items(plan)
		new_doc.assert_not_called()

	def test_pending_native_validation_rolls_back_new_items_before_returning_reason(self):
		service = self.runtime._service()
		self.assertTrue(
			callable(getattr(service, "_create_adapted_order", None)), "来源自动建单尚未接入统一适配"
		)
		doc = dict(name="OA", purchase_order=None)
		plan = dict(items=[self.spec], company="QA Company", blocking_reasons=[], preview_fingerprint="fp")
		with (
			patch.object(self.runtime, "preview", return_value=plan),
			patch.object(self.runtime, "ensure_items", return_value=[self.spec["item_code"]]),
			patch(
				"deeplinkerp_branding.services.purchase_repost_boundary.acquire", return_value=nullcontext()
			),
			patch.object(service, "_automatic_order", return_value=(None, "原生价格表待核对")),
			patch.object(service.frappe, "db", Mock()) as db,
			patch.object(service, "_insert_purchase_order") as insert,
		):
			result = service._create_adapted_order(doc, dict(version="original"), {}, plan)
		self.assertIsNone(result[0])
		self.assertIn("价格表", result[1])
		db.savepoint.assert_called_once()
		db.rollback.assert_called_once_with(save_point=db.savepoint.call_args.args[0])
		insert.assert_not_called()

	def test_rule_configuration_is_only_saved_after_current_preview_and_never_creates_items(self):
		source = dict(corp_id="corp", process_code="p", region="中国", department="采购组", items=[{}])
		values = dict(company="QA", supplier="SETTLEMENT", item_group="Services", purchase_uom="Nos")
		with (
			patch(
				"deeplinkerp_branding.services.purchase_repost_boundary.acquire", return_value=nullcontext()
			),
			patch.object(
				self.runtime, "preview", return_value=dict(preview_fingerprint="current", blocking_reasons=[])
			),
			patch.object(self.runtime, "ensure_items") as ensure,
			patch.object(
				self.runtime.frappe,
				"throw",
				side_effect=lambda message: (_ for _ in ()).throw(ValueError(message)),
			),
			patch.object(self.runtime.frappe, "new_doc") as new_doc,
		):
			with self.assertRaisesRegex(ValueError, "重新预览"):
				self.runtime.confirm_rule(source, {}, values, "old")
		ensure.assert_not_called()
		new_doc.assert_not_called()

	def test_temporary_settlement_supplier_cannot_submit_even_without_an_oa_link(self):
		service = self.runtime._service()
		order = service.frappe._dict(supplier="墨西哥加工费待核对")
		with patch.object(
			service.frappe, "throw", side_effect=lambda message: (_ for _ in ()).throw(ValueError(message))
		):
			with self.assertRaisesRegex(ValueError, "结算供应商"):
				service.validate_source_before_submit(order)

	def test_original_department_enrichment_does_not_rewrite_bound_source_version(self):
		service = self.runtime._service()
		raw = dict(
			corp_id="QA",
			process_instance_id="QA",
			business_id="QA",
			process_code=service.contract.PROCESS_CODES[0],
			create_time=datetime(2026, 10, 9),
			status="COMPLETED",
			result="agree",
			form_component_values=[
				{"name": "执行地区", "value": "墨西哥Mexico"},
				{"name": "币种", "value": "MXN"},
			],
		)
		old = service._normalize(raw)
		raw.update(originator_dept_id="original-dept", originator_dept_name=None)
		current = service._normalize(raw)
		self.assertEqual(old["version"], current["version"])
		self.assertEqual(current["adaptation_context"]["originator_dept_id"], "original-dept")

	def test_purchasing_user_gets_creation_token_from_full_evidence_before_redaction(self):
		service = self.runtime._service()
		source = dict(version="source", eligible=True, oa_identity=dict(process_instance_id="instance"))
		evidence = dict(version="private-proof", paid_amount="10")
		doc = service.frappe._dict(
			name="OA",
			purchase_order=None,
			custom_purchase_source_json=json.dumps(source),
			custom_cashier_payment_evidence=json.dumps(evidence),
		)
		doc.has_permission = lambda action: True
		seen = []

		def project(doc, source, proof):
			seen.append(proof)
			return dict(preview_fingerprint="fp-" + str(proof.get("version")))

		with (
			patch.object(service, "_source", return_value=doc),
			patch.object(
				service,
				"_role_projection",
				return_value=dict(purchasing_company=None, buyer_company_proposal=None),
			),
			patch.object(service, "_adaptation_preview", side_effect=project),
			patch.object(service.frappe, "session", service.frappe._dict(user="buyer")),
			patch.object(service.frappe, "get_roles", return_value=["Purchase User"]),
			patch.object(service.frappe, "has_permission", return_value=True),
			patch(
				"deeplinkerp_branding.services.unified_purchase_service.cashier_evidence_readable",
				return_value=False,
			),
		):
			result = service.get_purchase_source_detail("OA")
		self.assertEqual(seen[0]["version"], "private-proof")
		self.assertEqual(result["cashier"]["payment_evidence_status"], "hidden")
		self.assertEqual(
			result["creation_version"],
			service._version(source, evidence, dict(preview_fingerprint="fp-private-proof")),
		)

	def test_manual_item_adoption_only_includes_selected_original_items_and_company(self):
		service = self.runtime._service()
		self.assertTrue(callable(getattr(service, "_manual_adoption_plan", None)))
		plan = dict(company="QA Company", items=[self.spec, {**self.spec, "item_code": "OTHER"}])
		selected = [dict(item_code="OTHER", uom="Nos", qty="2", rate="10")]
		self.assertEqual(
			[r["item_code"] for r in service._manual_adoption_plan(plan, selected, "QA Company")["items"]],
			["OTHER"],
		)
		self.assertEqual(service._manual_adoption_plan(plan, selected, "Another Company")["items"], [])
		self.assertEqual(
			service._manual_adoption_plan(plan, [dict(item_code="REPLACEMENT", uom="Nos")], "QA Company")[
				"items"
			],
			[],
		)

	def test_batch_preview_requires_cached_source_document_and_field_access(self):
		service = self.runtime._service()
		source = dict(source_id="id", apply_date="2026-10-09", version="v")
		with (
			patch("deeplinkerp_branding.services.operating_expenses._manager"),
			patch.object(service, "_read_sync_snapshot", return_value=([(source, {}, None)], None)),
			patch.object(
				service, "_cached_doc", return_value=service.frappe._dict(name="OA", purchase_order=None)
			),
			patch.object(service, "_source", side_effect=service.frappe.PermissionError("denied")) as access,
			patch.object(self.runtime, "preview") as preview,
		):
			result = service.preview_purchase_source_adaptation(to_date="2026-10-15")
		access.assert_called_once_with("OA")
		preview.assert_not_called()
		self.assertEqual(result["rows"], [])

	def test_explicit_role_labels_reuse_permission_scoped_native_identity_matching(self):
		service = self.runtime._service()
		self.assertTrue(callable(getattr(self.runtime, "canonical_roles", None)))
		source = dict(
			purchasing_company="公司名称", supplier="供应商名称", items=[dict(supplier="供应商名称")]
		)
		with patch.object(
			service,
			"_role_candidate",
			side_effect=lambda src, key, dt: dict(
				value="COMP-ID" if dt == "Company" else "SUP-ID", status="unique"
			),
		):
			result = self.runtime.canonical_roles(source)
		self.assertEqual(result["supplier"], "SUP-ID")
		self.assertEqual(result["items"][0]["supplier"], "SUP-ID")
		self.assertEqual(result["purchasing_company"], "COMP-ID")
		self.assertEqual(source["supplier"], "供应商名称")

	def test_adopted_scope_change_requires_an_audited_explicit_human_recheck(self):
		service = self.runtime._service()
		self.assertTrue(callable(getattr(service, "_rechecked_adoption", None)))
		source = dict(
			corp_id="QA",
			process_code=service.contract.PROCESS_CODES[0],
			region="墨西哥",
			version="original",
			items=[dict(item_code="OLD")],
			processors=[],
		)
		source["department"] = "QA original organization"
		old_scope = dict(corp_id="old")
		doc = service.frappe._dict(
			{
				self.runtime.ADOPTION_FIELD: json.dumps(
					dict(plan=dict(scope=old_scope, items=[dict(item_code="OLD")]))
				)
			}
		)
		with patch.object(
			service.frappe, "throw", side_effect=lambda message: (_ for _ in ()).throw(ValueError(message))
		):
			with self.assertRaisesRegex(ValueError, "说明"):
				service._rechecked_adoption(doc, source, "")
		with (
			patch.object(service.frappe, "session", service.frappe._dict(user="buyer")),
			patch.object(service.frappe.utils, "now_datetime", return_value="2026-10-15 12:00:00"),
		):
			plan = service._rechecked_adoption(doc, source, "已核对原申请组织变化")
		self.assertEqual(plan["scope_rechecked_by"], "buyer")
		self.assertEqual(plan["previous_scope"], old_scope)
		self.assertEqual(plan["items"], [dict(item_code="OLD")])
		changed = {**source, "department": "Changed organization"}
		self.assertEqual(service._version(source, {}), service._version(changed, {}))
		self.assertNotEqual(
			service._version(source, {}, service._recheck_plan(doc, source)),
			service._version(changed, {}, service._recheck_plan(doc, changed)),
		)

	def test_ineligible_sync_outcomes_name_the_actual_approval_blocker(self):
		service = self.runtime._service()
		for source, label in (
			(dict(status="RUNNING"), "审批中"),
			(dict(status="TERMINATED"), "终止"),
			(dict(status="COMPLETED", result="refuse"), "拒绝"),
			(dict(deleted_at="2026-10-15"), "撤销"),
			(dict(status="COMPLETED", result="agree"), "来源待核对"),
		):
			with self.subTest(source=source):
				self.assertIn(label, service._approval_pending_reason(source))
				self.assertIn("不创建物料", service._approval_pending_reason(source))


if __name__ == "__main__":
	unittest.main()
