import copy
import importlib
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


def source(**values):
    return dict({"corp_id":"corp", "process_instance_id":"i1", "business_id":"DT-1",
        "process_code":"PROC-BFDF6F09-4551-43B3-8C55-537AA74A241B", "status":"COMPLETED", "result":"agree",
        "create_time":datetime(2026, 1, 1, tzinfo=timezone.utc),
        "form_component_values":[{"name": n, "value": v} for n, v in [
            ("执行地区Región de ejecución", "中国China"), ("币种Moneda", "人民币RMB"),
            ("收款人beneficiario", "Vendor"), ("金额importe", "100"),
            ("需求明细Desglose de los gastos", [{"物品编码": "ITEM", "数量": "2", "单位": "个", "金额": "100"}])]]}, **values)


class PurchaseSourceContractTest(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module("deeplinkerp_branding.services.purchase_source_contract")
        except ModuleNotFoundError:
            self.module = None
        self.assertIsNotNone(self.module, "采购来源契约尚未实现")

    def test_scope_requires_purchase_template_recognized_region_and_china_year(self):
        self.assertTrue(self.module.in_scope(source()))
        # Confirmed original purchase-expense template, not an operating template.
        newer = source(process_code="PROC-E69FCD3E-E374-4C54-9D8F-6E1F55AD741F", status="RUNNING")
        self.assertTrue(self.module.in_scope(newer))
        self.assertFalse(self.module.normalize(newer)["eligible"])
        for patch in ({"process_code": "operation"}, {"create_time": datetime(2025, 12, 31, 15, 59, tzinfo=timezone.utc)},
                      {"create_time": datetime(2026, 12, 31, 16, tzinfo=timezone.utc)}):
            self.assertFalse(self.module.in_scope(source(**patch)))
        for region in ("美国USA", "", "China待确认", "Mexico待确认"):
            row = source(); row["form_component_values"][0]["value"] = region
            self.assertFalse(self.module.in_scope(row))

    def test_mexico_internal_molds_use_only_fixed_purchase_templates_and_known_regions(self):
        for region in ("墨西哥", "墨西哥Mexico", "墨西哥México", "墨西哥 México", "Mexico", "México"):
            for code in self.module.PROCESS_CODES:
                with self.subTest(region=region, code=code):
                    row = source(process_code=code)
                    row["form_component_values"][0]["value"] = region
                    self.assertTrue(self.module.in_scope(row))
                    self.assertTrue(self.module.normalize(row)["eligible"])
                    row["process_code"] = "PROC-OPERATING-EXPENSE"
                    self.assertFalse(self.module.in_scope(row))

    def test_explicit_beneficiary_aliases_are_separate_from_applicant_and_payee(self):
        for alias in ("归属子公司Subsidiaria", "所属子公司Empresa filial", "子公司Subsidiaria", "受益公司Empresa beneficiaria", "Empresa beneficiaria"):
            with self.subTest(alias=alias):
                row = source()
                row["form_component_values"].extend([
                    {"name": alias, "value": "Mexico Factory"},
                    {"name": "申请部门/组织", "value": "Domestic Buyer"},
                ])
                before = copy.deepcopy(row)
                item = self.module.normalize(row)
                self.assertEqual(item.get("beneficiary_company"), "Mexico Factory")
                self.assertEqual(item.get("beneficiary_company_status"), "unique")
                self.assertEqual(item["department"], "Domestic Buyer")
                self.assertEqual(item["payee"], "Vendor")
                self.assertEqual(item["original_fields"].get("beneficiary_company"), "Mexico Factory")
                self.assertEqual(row, before)

    def test_beneficiary_and_project_ambiguity_preserves_every_raw_occurrence(self):
        row = source()
        row["form_component_values"].extend([
            {"name": "归属子公司", "value": "Mexico Factory"},
            {"name": "归属子公司Subsidiaria", "value": "Mexico Seller"},
            {"name": "项目归属", "value": "Factory molds"},
            {"name": "Proyecto", "value": "Store launch"},
        ])
        item = self.module.normalize(row)
        self.assertIsNone(item.get("beneficiary_company"))
        self.assertIsNone(item.get("project"))
        self.assertEqual(item.get("beneficiary_company_status"), "ambiguous")
        self.assertEqual(item.get("project_status"), "ambiguous")
        self.assertEqual(item["original_fields"].get("beneficiary_company"), ["Mexico Factory", "Mexico Seller"])
        self.assertEqual(item["original_fields"].get("project"), ["Factory molds", "Store launch"])

    def test_role_controls_ignore_empty_branches_but_never_guess_structured_selections(self):
        for key, alias in (("beneficiary_company", "归属子公司"), ("project", "项目Proyecto")):
            for value in (["A", "B"], {"name": "A"}):
                row = source()
                row["form_component_values"].append({"name": alias, "value": value})
                item = self.module.normalize(row)
                self.assertIsNone(item.get(key))
                self.assertEqual(item.get(key + "_status"), "ambiguous")
                self.assertEqual(item["original_fields"][key], value)
            row = source()
            row["form_component_values"].extend([
                {"name": alias, "value": None}, {"name": alias, "value": "A"},
            ])
            item = self.module.normalize(row)
            self.assertEqual(item.get(key), "A")
            self.assertEqual(item.get(key + "_status"), "unique")
        self.assertEqual(self.module.normalize(source()).get("beneficiary_company_status"), "missing")

    def test_normalization_reads_field_occurrences_only_once(self):
        row = source()
        row["form_component_values"] = self.module.json.dumps(row["form_component_values"])
        with patch.object(self.module, "_field_occurrences", wraps=self.module._field_occurrences) as occurrences:
            item = self.module.normalize(row)
        self.assertTrue(item["eligible"])
        self.assertEqual(item["currency"], "CNY")
        self.assertEqual(occurrences.call_count, 1)

    def test_only_completed_agree_without_deletion_can_convert(self):
        for status, result, expected in [("COMPLETED", "agree", True), ("COMPLETED", "refuse", False),
                                         ("RUNNING", "agree", False), ("REJECTED", None, False)]:
            self.assertEqual(self.module.normalize(source(status=status, result=result))["eligible"], expected)
        self.assertFalse(self.module.normalize(source(deleted_at="2026-10-01"))["eligible"])

    def test_original_items_and_amount_are_authoritative_not_planned_payment(self):
        row = source(); row["form_component_values"][3]["value"] = "999"
        item = self.module.normalize(row)
        self.assertEqual(item["items"][0]["qty"], "2")
        self.assertEqual(item["detail_total_amount"], "100")
        self.assertEqual(item["requested_amount"], "999")
        self.assertIn("金额不一致", "；".join(item["issues"]))
        self.assertIsNone(self.module.payment_evidence(item, [])["paid_amount"])

    def test_zero_detail_amount_is_not_replaced_by_payment_amount(self):
        row = source(); row["form_component_values"][4]["value"][0]["金额"] = "0"
        self.assertEqual(self.module.normalize(row)["detail_total_amount"], "0")

    def test_mapper_price_currency_supplier_and_explicit_buyer_survive_without_zero_fallback(self):
        row = source()
        row["form_component_values"].extend([
            {"name": "采购公司", "value": "Buyer"}, {"name": "供应商", "value": "Supplier"}])
        for rate in (None, "0", "50", "待确认"):
            with self.subTest(rate=rate):
                item = self.module.normalize(row, detail_rows=[{"material_code": "ITEM", "quantity": "2",
                    "unit": "Nos", "unit_price": rate, "goods_value": "100", "purchase_currency": "CNY", "supplier": "Supplier"}])
                self.assertEqual(item["items"][0].get("rate"), None if rate == "待确认" else rate)
                self.assertEqual(bool(item["items"][0].get("rate_invalid")),rate == "待确认")
                self.assertEqual(item["items"][0].get("currency"), "CNY")
                self.assertEqual(item["items"][0].get("supplier"), "Supplier")
                self.assertEqual(item.get("purchasing_company"), "Buyer")
                self.assertEqual(item.get("purchasing_company_status"), "unique")
                self.assertEqual(item.get("supplier"), "Supplier")

    def test_duplicate_field_is_ambiguous_and_no_qty_one_fallback(self):
        row = source(); row["form_component_values"].append(copy.deepcopy(row["form_component_values"][0]))
        self.assertFalse(self.module.in_scope(row))
        row = source(); del row["form_component_values"][4]["value"][0]["数量"]
        item = self.module.normalize(row)
        self.assertIsNone(item["items"][0]["qty"])

    def test_inactive_duplicate_controls_keep_the_single_populated_value_and_raw_evidence(self):
        for empty in (None, "", "  "):
            for empty_first in (False, True):
                with self.subTest(empty=empty, empty_first=empty_first):
                    row = source()
                    original = copy.deepcopy(row["form_component_values"][1:4])
                    inactive = [{**component, "value": empty} for component in original]
                    row["form_component_values"] = (inactive + row["form_component_values"] if empty_first
                                                   else row["form_component_values"] + inactive)
                    before = copy.deepcopy(row)
                    item = self.module.normalize(row)
                    self.assertEqual(item["currency"], "CNY")
                    self.assertEqual(item["payee"], "Vendor")
                    self.assertEqual(item["requested_amount"], "100")
                    self.assertEqual(item["detail_total_amount"], "100")
                    for key, component in zip(("currency", "payee", "requested_amount"), original):
                        values = [empty, component["value"]] if empty_first else [component["value"], empty]
                        self.assertEqual(item["original_fields"][key], values)
                    self.assertEqual(row, before)

    def test_multiple_equivalent_currency_values_can_verify_matching_payment_evidence(self):
        row = source()
        row["form_component_values"].extend([
            {"name": "币种Moneda", "value": "CNY"}, {"name": "币种Moneda", "value": None}])
        item = self.module.normalize(row)
        self.assertEqual(item["currency"], "CNY")
        self.assertEqual(item["original_fields"]["currency"], ["人民币RMB", "CNY", None])
        proof = dict(source_id="c1", process_instance_id="i1", source_type="purchase", currency="CNY",
                     payment_evidence_status="recorded", paid_amount="20", amount="100", payments=[])
        self.assertEqual(self.module.payment_evidence(item, [proof])["paid_amount"], "20")

    def test_conflicting_or_unknown_populated_currency_keeps_payments_hidden(self):
        for value in ("USD", "待确认", [], {}, 0):
            with self.subTest(value=value):
                row = source()
                row["form_component_values"].append({"name": "币种Moneda", "value": value})
                item = self.module.normalize(row)
                self.assertIsNone(item["currency"])
                self.assertEqual(item["original_fields"]["currency"], ["人民币RMB", value])
                proof = dict(source_id="c1", process_instance_id="i1", source_type="purchase", currency="CNY",
                             payment_evidence_status="recorded", paid_amount="20", attachments=[{"source_id":"private"}])
                evidence = self.module.payment_evidence(item, [proof])
                self.assertIsNone(evidence["paid_amount"])
                self.assertEqual(evidence["attachments"], [])

    def test_multiple_populated_amounts_are_never_summed_or_coalesced(self):
        for value in ("100", "200"):
            with self.subTest(value=value):
                row = source()
                row["form_component_values"].append({"name": "金额importe", "value": value})
                item = self.module.normalize(row)
                self.assertIsNone(item["requested_amount"])
                self.assertEqual(item["detail_total_amount"], "100")
                self.assertEqual(item["original_fields"]["requested_amount"], ["100", value])

    def test_single_currency_control_with_a_structured_value_is_not_guessed(self):
        for value in (["CNY"], ["CNY", "CNY"], {"value": "CNY"}):
            with self.subTest(value=value):
                row = source()
                row["form_component_values"][1]["value"] = value
                item = self.module.normalize(row)
                self.assertIsNone(item["currency"])
                self.assertEqual(item["original_fields"]["currency"], value)

    def test_inactive_control_does_not_erase_zero_or_relax_execution_region_scope(self):
        row = source()
        row["form_component_values"][3]["value"] = "0"
        row["form_component_values"].append({"name": "金额importe", "value": None})
        self.assertEqual(self.module.normalize(row)["requested_amount"], "0")
        row["form_component_values"].append({"name": "执行地区Región de ejecución", "value": None})
        self.assertFalse(self.module.in_scope(row))

    def test_payment_requires_exact_identity_scope_and_recorded_currency_proof(self):
        item = self.module.normalize(source())
        proof = dict(source_id="c1", process_instance_id="i1", source_type="purchase", currency="CNY",
                     payment_evidence_status="recorded", paid_amount="20", amount="100", payments=[])
        evidence = self.module.payment_evidence(item, [proof])
        self.assertEqual(evidence["paid_amount"], "20")
        for patch in ({"source_type": "operation"}, {"process_instance_id": "other"},
                      {"currency": "USD"}, {"payment_evidence_status": "unknown"}, {"corp_id": "other"}):
            self.assertIsNone(self.module.payment_evidence(item, [{**proof, **patch}])["paid_amount"])
        self.assertIsNone(self.module.payment_evidence(item, [proof, {**proof, "source_id": "c2"}])["paid_amount"])

    def test_approval_number_fallback_requires_explicit_unique_source(self):
        item = self.module.normalize(source(business_count=2))
        proof = dict(source_id="c1", approval_no="DT-1", approval_identity_status="explicit", source_type="purchase",
                     currency="CNY", payment_evidence_status="recorded", paid_amount="20", amount="100")
        self.assertIsNone(self.module.payment_evidence(item, [proof])["paid_amount"])

    def test_read_adapter_uses_fixed_purchase_templates_not_operating_templates(self):
        from tests.test_operating_oa_source import RecordingConnection
        from deeplinkerp_branding.services import operating_oa_source
        connection = RecordingConnection([])
        operating_oa_source.read_page(connection, 100, "2026-10-06T00:00:00Z", process_codes=self.module.PROCESS_CODES)
        self.assertEqual(connection.params[0], list(self.module.PROCESS_CODES))

    def test_purchase_identity_count_is_batched_globally_after_bounded_page(self):
        from tests.test_operating_oa_source import RecordingConnection
        from deeplinkerp_branding.services import operating_oa_source
        connection = RecordingConnection([])
        operating_oa_source.read_page(connection, 500, "2026-10-06T00:00:00Z", process_codes=self.module.PROCESS_CODES)
        sql = " ".join(connection.sql.split())
        self.assertIn("instance_counts AS MATERIALIZED (", sql)
        counts = sql.split("instance_counts AS MATERIALIZED (", 1)[1].split(") SELECT page.*", 1)[0]
        self.assertEqual(counts, "SELECT process_instance_id,count(*) AS instance_count FROM costing_read.approval_instances_v2 "
                         "WHERE process_instance_id IN (SELECT process_instance_id FROM page) GROUP BY process_instance_id")
        self.assertNotIn("duplicate.process_instance_id=page.process_instance_id", sql)
        self.assertIn("COALESCE(instance_counts.instance_count,0) AS instance_count", sql)
        self.assertIn("LEFT JOIN instance_counts USING(process_instance_id)", sql)
        self.assertEqual(connection.params[-1], 501)

    def test_existing_detail_parser_can_supply_flattened_real_dingtalk_tables(self):
        row = source(); row["form_component_values"][4]["value"] = [[{"label":"数量Cantidad", "value":"2"}]]
        item = self.module.normalize(row, detail_rows=[{"material_code":"ITEM", "product_name":"A", "quantity":"2", "unit":"个", "goods_value":"100"}])
        self.assertEqual(item["items"][0]["qty"], "2")
        self.assertEqual(item["items"][0]["item_code"], "ITEM")

    def test_normalized_unit_is_not_confused_with_unit_price(self):
        item=self.module.normalize(source(),detail_rows=[{"material_code":"ITEM","product_name":"A","quantity":"2","unit":"Nos","unit_price":"50","goods_value":"100"}])
        self.assertEqual(item["items"][0]["uom"],"Nos")

    def test_new_blank_buyer_supplier_facts_do_not_change_bound_fingerprint(self):
        row=source(); original=self.module.normalize(row)
        row["form_component_values"].extend([{"name":"采购公司","value":None},{"name":"供应商","value":" "}])
        self.assertEqual(self.module.normalize(row),original)

    def test_selection_requires_explicit_values_and_reason_for_corrections(self):
        original = self.module.normalize(source())
        chosen = [{"item_code":"ITEM", "qty":"2", "uom":"个", "rate":"50"}]
        self.assertEqual(self.module.validate_selection(original, "CNY", chosen)[0]["qty"], "2")
        for key in ("item_code", "qty", "uom", "rate"):
            bad = copy.deepcopy(chosen); bad[0].pop(key)
            with self.assertRaises(ValueError): self.module.validate_selection(original, "CNY", bad)
        bad = [{**chosen[0], "qty":"0"}]
        with self.assertRaises(ValueError): self.module.validate_selection(original, "CNY", bad)
        changed = [{**chosen[0], "rate":"60"}]
        with self.assertRaises(ValueError): self.module.validate_selection(original, "CNY", changed)
        self.assertEqual(self.module.validate_selection(original, "CNY", changed, "核对原单并更正价格")[0]["rate"], "60")
        with self.assertRaises(ValueError): self.module.validate_selection(original, "USD", chosen)
        with self.assertRaises(ValueError): self.module.validate_selection(original,"CNY",[{**chosen[0],"uom":"箱"}])

    def test_conflicting_payment_proof_does_not_expose_attachments(self):
        item = self.module.normalize(source())
        proof = dict(source_id="c1", process_instance_id="i1", source_type="purchase", currency="CNY",
                     source_conflict=True, payment_evidence_status="recorded", paid_amount="20", attachments=[{"source_id":"secret"}])
        self.assertEqual(self.module.payment_evidence(item, [proof])["attachments"], [])


if __name__ == "__main__":
    unittest.main()
