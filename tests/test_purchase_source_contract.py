import copy
import importlib
import unittest
from datetime import datetime, timezone


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

    def test_scope_requires_purchase_template_china_and_china_year(self):
        self.assertTrue(self.module.in_scope(source()))
        for patch in ({"process_code": "operation"}, {"create_time": datetime(2025, 12, 31, 15, 59, tzinfo=timezone.utc)},
                      {"create_time": datetime(2026, 12, 31, 16, tzinfo=timezone.utc)}):
            self.assertFalse(self.module.in_scope(source(**patch)))
        for region in ("墨西哥Mexico", "", "China待确认"):
            row = source(); row["form_component_values"][0]["value"] = region
            self.assertFalse(self.module.in_scope(row))

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

    def test_duplicate_field_is_ambiguous_and_no_qty_one_fallback(self):
        row = source(); row["form_component_values"].append(copy.deepcopy(row["form_component_values"][0]))
        self.assertFalse(self.module.in_scope(row))
        row = source(); del row["form_component_values"][4]["value"][0]["数量"]
        item = self.module.normalize(row)
        self.assertIsNone(item["items"][0]["qty"])

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

    def test_existing_detail_parser_can_supply_flattened_real_dingtalk_tables(self):
        row = source(); row["form_component_values"][4]["value"] = [[{"label":"数量Cantidad", "value":"2"}]]
        item = self.module.normalize(row, detail_rows=[{"material_code":"ITEM", "product_name":"A", "quantity":"2", "unit":"个", "goods_value":"100"}])
        self.assertEqual(item["items"][0]["qty"], "2")
        self.assertEqual(item["items"][0]["item_code"], "ITEM")

    def test_normalized_unit_is_not_confused_with_unit_price(self):
        item=self.module.normalize(source(),detail_rows=[{"material_code":"ITEM","product_name":"A","quantity":"2","unit":"Nos","unit_price":"50","goods_value":"100"}])
        self.assertEqual(item["items"][0]["uom"],"Nos")

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
