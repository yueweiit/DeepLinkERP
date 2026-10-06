"""Original OA applications stay authoritative; cashier evidence is supplemental."""
import copy
import importlib
import unittest
from datetime import datetime, timezone


def approval(**values):
    return dict(corp_id="corp", process_instance_id="instance-1", business_id="20260101001",
        process_code="PROC-0DC5DE17-A29A-497C-8A1F-1324298A04AA", status="COMPLETED", result="agree",
        create_time=datetime(2026, 1, 1, tzinfo=timezone.utc), originator_user_id="u1", originator_user_name="Alice",
        form_component_values=[{"name": n, "value": v} for n, v in (
            ("申请类型Tipo de trámite", "付款申请Solicitud de pago"), ("执行地区Región de ejecución", "中国"),
            ("金额importe", "100.00"), ("币种Moneda", "人民币"), ("事项说明Explicación de asuntos", "Office"),
            ("收款人beneficiario", "Vendor"), ("付款日期Fecha de pago", "2026-01-09"))], **values)


class RecordingConnection:
    """Capture the actual adapter query at the external database boundary."""
    def __init__(self, rows): self.rows = rows
    def __call__(self): return self
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self): return self
    def execute(self, sql, params): self.sql, self.params = sql, params
    def fetchall(self): return self.rows


class OriginalOperatingSourceTest(unittest.TestCase):
    def setUp(self):
        try:
            self.source = importlib.import_module("deeplinkerp_branding.services.operating_oa_source")
        except ImportError:
            self.source = None
        self.assertIsNotNone(self.source, "Original operating OA adapter is missing")

    def test_scope_requires_verified_template_region_year_and_request_type(self):
        self.assertTrue(self.source.in_scope(approval()))
        variants = [dict(process_code="procurement"), dict(create_time=datetime(2025, 12, 31, 15, 59, tzinfo=timezone.utc)),
                    dict(create_time=datetime(2026, 12, 31, 16, tzinfo=timezone.utc))]
        for values in variants:
            row = approval(); row.update(values)
            self.assertFalse(self.source.in_scope(row))
        for index, value in ((0, "备用金借款"), (1, "墨西哥"), (1, "")):
            row = approval(); row["form_component_values"][index]["value"] = value
            self.assertFalse(self.source.in_scope(row))
        row = approval(); row["form_component_values"][0]["value"] = "费用报销Reembolso de gastos"
        self.assertTrue(self.source.in_scope(row))

    def test_requested_payment_date_never_means_paid(self):
        item = self.source.merge_application(approval(), [], {})
        self.assertEqual(item["source_system"], "dingtalk-oa")
        self.assertEqual(item["amount"], "100.00")
        self.assertEqual(item["source_status"], "付款待核对")
        self.assertIsNone(item["paid_amount"])
        self.assertIsNone(item["pending_amount"])
        self.assertEqual(item["payments"], [])

    def test_observed_bilingual_oa_currency_values_are_normalized_exactly(self):
        for value, currency in (("人民币RMB", "CNY"), ("美元Dólar", "USD")):
            with self.subTest(value=value):
                row = approval(); row["form_component_values"][3]["value"] = value
                item = self.source.merge_application(row, [], {})
                self.assertEqual(item["currency"], currency)
                self.assertEqual(item["original_source_currency"], currency)

    def test_unknown_oa_currency_never_borrows_cashier_currency(self):
        row = approval(); row["form_component_values"][3]["value"] = "人民币RMB待核对"
        cashier = {"source_id": "r1", "process_instance_id": "instance-1", "amount": "100", "currency": "CNY",
                   "paid_amount": "100", "pending_amount": "0", "payments": [], "attachments": [],
                   "payment_evidence_status": "recorded"}
        item = self.source.merge_application(row, [cashier], {})
        self.assertIsNone(item["currency"])
        self.assertIsNone(item["original_source_currency"])
        self.assertTrue(item["source_conflict"])
        self.assertIsNone(item["paid_amount"])
        self.assertIsNone(item["pending_amount"])

    def test_verified_unique_approval_joins_actual_payments_and_keeps_original_identity(self):
        raw = approval()
        cashier = {"source_id": "legacy-root", "approval_no": raw["business_id"], "approval_identity_status": "explicit",
                   "amount": "100", "currency": "CNY", "paid_amount": "20", "pending_amount": "80",
                   "source_status": "部分付款", "payments": [{"source_id": "p1", "amount": "20", "currency": "CNY", "evidence_status": "recorded"}],
                   "attachments": [], "payment_evidence_status": "recorded"}
        company = {"status": "matched", "assigned_department": "拉丁购", "match_source": "user_id"}
        item = self.source.merge_application(raw, [cashier], company)
        self.assertEqual(item["payments"], cashier["payments"])
        self.assertEqual(item["source_company"], "拉丁购")
        self.assertEqual(item["paid_amount"], "20")
        self.assertEqual(item["cashier_source_id"], "legacy-root")
        self.assertEqual(item["source_id"], self.source.application_id(raw))

    def test_ambiguous_identity_and_amount_conflict_never_become_unpaid(self):
        matching = {"source_id": "root", "process_instance_id": "instance-1", "amount": "999", "currency": "CNY",
                    "paid_amount": "0", "pending_amount": "999", "payments": [], "attachments": []}
        item = self.source.merge_application(approval(), [matching], {})
        self.assertTrue(item["source_conflict"])
        self.assertEqual(item["amount"], "100.00")
        self.assertIsNone(item["pending_amount"])
        item = self.source.merge_application(approval(), [matching, {**matching, "source_id": "root2"}], {})
        self.assertTrue(item["source_conflict"])
        self.assertEqual(item["payments"], [])

    def test_mutable_number_or_name_amount_never_authorizes_join(self):
        for extra in ({"dingding_id": "20260101001"}, {"approval_no": "20260101001", "approval_identity_status": "unverified"},
                      {"amount": "100", "applicant": "Alice"}):
            self.assertIsNone(self.source.merge_application(approval(), [extra], {})["cashier_source_id"])

    def test_rejected_running_cancelled_and_deleted_stay_blocked(self):
        for status, result, deleted in (("COMPLETED", "refuse", None), ("RUNNING", "agree", None),
                                       ("TERMINATED", "agree", None), ("COMPLETED", "agree", "2026-01-10")):
            row = approval(); row.update(status=status, result=result, deleted_at=deleted)
            item = self.source.merge_application(row, [], {})
            self.assertEqual(item["approvals"]["eligibility"], "blocked")
            self.assertIsNone(item["pending_amount"])

    def test_missing_or_float_money_not_fabricated_as_zero(self):
        for value in ("", None, 0.1, "NaN"):
            row = approval(); row["form_component_values"][2]["value"] = value
            self.assertIsNone(self.source.merge_application(row, [], {})["amount"])
        row = approval(); row["form_component_values"][2]["value"] = "0"
        self.assertEqual(self.source.merge_application(row, [], {})["amount"], "0")

    def test_paid_supplement_changes_version_without_overwriting_source_or_inputs(self):
        raw = approval(); previous = copy.deepcopy(raw)
        item = self.source.merge_application(raw, [], {})
        paid = self.source.merge_application(raw, [{"source_id": "r1", "process_instance_id": "instance-1",
           "amount": "100", "currency": "CNY", "paid_amount": "100", "pending_amount": "0", "source_status": "已付款",
           "payments": [], "attachments": [], "payment_evidence_status": "recorded"}], {})
        self.assertNotEqual(item["version"], paid["version"])
        self.assertEqual(item["source_id"], paid["source_id"])
        self.assertEqual(raw, previous)

    def test_cursor_is_bounded_and_binds_source_snapshot(self):
        value = self.source.encode_cursor("2026-10-06T00:00:00Z", "corp", "i")
        self.assertEqual(self.source.decode_cursor(value), ("2026-10-06T00:00:00Z", "corp", "i"))
        for invalid in ("garbage", "A" * 3000):
            with self.assertRaises(ValueError):
                self.source.decode_cursor(invalid)

    def test_explicit_identity_conflict_and_duplicate_business_ids_block_join(self):
        row = approval(); row["business_count"] = 2
        self.assertIsNone(self.source.merge_application(row, [{"source_id": "r1", "approval_no": row["business_id"], "approval_identity_status": "explicit"}], {})["cashier_source_id"])
        self.assertIsNone(self.source.merge_application(approval(), [{"source_id": "r1", "process_instance_id": "instance-1", "identity_conflict": True}], {})["cashier_source_id"])

    def test_blank_business_numbers_never_authorize_cashier_fallback(self):
        for business_id in (None, ""):
            with self.subTest(business_id=business_id):
                row = approval(); row.update(business_id=business_id, business_count=0)
                cashier = {"source_id": "r1", "approval_no": business_id, "approval_identity_status": "explicit"}
                self.assertIsNone(self.source.merge_application(row, [cashier], {})["cashier_source_id"])

    def test_read_page_projects_bounded_sql_in_existing_read_only_connection(self):
        query = RecordingConnection([approval(), {**approval(), "process_instance_id": "instance-2"}])
        rows, cursor = self.source.read_page(query, 1, "2026-10-06T00:00:00Z")
        self.assertEqual(len(rows), 1)
        self.assertTrue(cursor)
        self.assertEqual(self.source.decode_cursor(cursor), ("2026-10-06T00:00:00Z", "corp", "instance-1"))
        self.assertIn("form_component_values::text", query.sql)
        self.assertNotIn("SELECT *", query.sql)
        self.assertEqual(query.params[-1], 2)
        with self.assertRaises(ValueError):
            self.source.read_page(query, 1, "2026-10-07T00:00:00Z", cursor=cursor)

    def test_read_page_limits_materialized_page_before_global_business_count(self):
        query = RecordingConnection([])
        self.source.read_page(query, 500, "2026-10-06T00:00:00Z")
        sql = " ".join(query.sql.split())
        self.assertTrue(sql.startswith("WITH page AS MATERIALIZED (SELECT "), sql)
        self.assertNotIn(" OVER ", sql.upper())
        page, counts = sql.split("), counts AS (", 1)
        self.assertIn("FROM costing_read.approval_instances_v2 WHERE process_code = ANY(%s)", page)
        self.assertIn("create_time >= %s AND create_time < %s AND updated_at <= %s", page)
        self.assertTrue(page.endswith("ORDER BY corp_id,process_instance_id LIMIT %s"), page)
        self.assertTrue(counts.startswith("SELECT business_id,count(*) AS business_count FROM costing_read.approval_instances_v2 WHERE business_id IN (SELECT business_id FROM page WHERE NULLIF(business_id,'') IS NOT NULL) GROUP BY business_id) "), counts)
        self.assertTrue(counts.endswith("SELECT page.*,COALESCE(counts.business_count,0) AS business_count FROM page LEFT JOIN counts USING(business_id) ORDER BY page.corp_id,page.process_instance_id"), counts)
        self.assertEqual(query.params, (list(self.source.PROCESS_CODES), self.source.START, self.source.END,
                                       datetime(2026, 10, 6, tzinfo=timezone.utc), 501))

    def test_read_page_cursor_and_identity_are_parameterized_in_bounded_page(self):
        until = "2026-10-06T00:00:00Z"
        after_corp, after_instance = "corp-after", "instance-after"
        identity = {"corp_id": "corp'identity", "process_instance_id": "instance'identity"}
        query = RecordingConnection([])
        cursor = self.source.encode_cursor(until, after_corp, after_instance)
        rows, next_cursor = self.source.read_page(query, 7, until, cursor=cursor, identity=identity)
        self.assertEqual((rows, next_cursor), ([], None))
        self.assertTrue(query.sql.startswith("WITH page AS MATERIALIZED ("), query.sql)
        page = query.sql.split("), counts AS (", 1)[0]
        self.assertIn("(corp_id, process_instance_id) > (%s, %s)", page)
        self.assertIn("corp_id=%s AND process_instance_id=%s", page)
        for value in (after_corp, after_instance, *identity.values()):
            self.assertNotIn(value, query.sql)
        self.assertEqual(query.params, (list(self.source.PROCESS_CODES), self.source.START, self.source.END,
            datetime(2026, 10, 6, tzinfo=timezone.utc), after_corp, after_instance,
            identity["corp_id"], identity["process_instance_id"], 8))

    def test_attachment_manifest_is_scoped_and_proves_file_version(self):
        row = approval()
        archived = {"corp_id": "corp", "process_instance_id": "instance-1", "file_id": "f1", "file_name": "invoice.pdf",
                    "archive_status": "archived", "sha256": "a" * 64, "actual_size": 100}
        items = self.source.archive_attachments(row, [archived, {**archived, "corp_id": "other"}])
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["url"].startswith("/oa-archive/"))
        self.assertEqual(items[0]["archive_identity"]["file_id"], "f1")

    def test_archive_integrity_requires_complete_exact_evidence(self):
        manifest = {"archive_status": "archived", "sha256": "a" * 64, "actual_size": 100}
        self.assertTrue(hasattr(self.source, "archive_integrity"), "Archive integrity guard missing")
        self.assertEqual(self.source.archive_integrity(manifest), ("a" * 64, 100))
        for mutation in ({"sha256": None}, {"sha256": "a"}, {"actual_size": None}, {"actual_size": -1}, {"actual_size": True}, {"actual_size": 1.5}, {"archive_status": "pending"}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.source.archive_integrity({**manifest, **mutation})

    def test_ambiguous_manual_applicant_never_falls_back_to_old_user_company(self):
        cashier = {"source_id": "r", "process_instance_id": "instance-1", "amount": "100", "currency": "CNY",
                   "applicant_identity": {"status": "ambiguous", "manual_applicant_override": None}}
        item = self.source.merge_application(approval(), [cashier], {"status": "matched", "assigned_department": "拉丁购"})
        self.assertIsNone(item["source_company"])
        self.assertEqual(item["company_resolution"]["status"], "ambiguous")

    def test_manual_applicant_identity_uses_current_resolver_not_old_oa_userid(self):
        cashier = {"source_id": "r", "process_instance_id": "instance-1", "applicant_identity": {
            "user_id": "", "employee_name": "Manual Alice", "status": "identified", "manual_applicant_override": True}}
        self.assertEqual(self.source.resolution_applicant(approval(), [cashier]), {"user_id": "", "employee_name": "Manual Alice"})
        cashier["applicant_identity"]["status"] = "ambiguous"
        self.assertEqual(self.source.resolution_applicant(approval(), [cashier]), {"user_id": "", "employee_name": ""})

    def test_withdrawn_cache_clears_payable_and_has_stable_fingerprint(self):
        item = self.source.merge_application(approval(), [], {})
        removed = self.source.withdrawn_source(item)
        self.assertEqual(removed, self.source.withdrawn_source(removed))
        self.assertEqual(removed["approvals"]["eligibility"], "blocked")
        self.assertIsNone(removed["pending_amount"])

    def test_cashier_approval_and_reported_payment_fields_are_preserved_as_evidence(self):
        cashier = {"source_id": "r", "process_instance_id": "instance-1", "amount": "100", "currency": "CNY",
                   "source_status": "已付款", "approvals": {"raw": {"general_manager_approval": "同意付款", "finance_review": "已付款"}}}
        item = self.source.merge_application(approval(), [cashier], {})
        self.assertEqual(item["approvals"]["raw"]["cashier_general_manager_approval"], "同意付款")
        self.assertEqual(item["cashier_reported_payment_status"], "已付款")
        self.assertEqual(item["source_status"], "付款待核对")
        self.assertIsNone(item["paid_amount"])
