import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
	from deploy.production import backfill_historical_oa_company as backfill
except ImportError:
	backfill = None


def row(name="OA-1", **overrides):
	return {"name": name, "apply_date": "2026-06-30", "creation": "2026-04-18 10:00:00",
		"target_company": None, "docstatus": 0, "purchase_order": None, "modified": "2026-10-03",
		"modified_by": "source@example.com", "payment_amount": 15, **overrides}


class HistoricalCompanyTests(unittest.TestCase):
	def setUp(self):
		self.assertIsNotNone(backfill, "The one-time audited backfill implementation must exist")

	def test_dates_use_apply_date_then_creation_and_exclude_cutoff(self):
		rows = [row("earlier"), row("fallback", apply_date=None), row("cutoff", apply_date="2026-07-01"),
			row("later", apply_date="2026-07-02"), row("known", target_company="Other Company")]
		before = copy.deepcopy(rows)
		self.assertEqual([r["name"] for r in backfill.select_candidates(rows)], ["earlier", "fallback"])
		self.assertEqual(rows, before)

	def test_blank_company_does_not_allow_ambiguous_source_rows(self):
		for overrides in [{"apply_date": "bad"}, {"apply_date": None, "creation": None},
			{"docstatus": 1}, {"purchase_order": "PO-1"}]:
			with self.subTest(overrides=overrides), self.assertRaises(ValueError):
				backfill.select_candidates([row(**overrides)])
		with self.assertRaises(ValueError):
			backfill.select_candidates([row(), row()])
		for reverse_link in ["OA-1", " OA-1 "]:
			with self.subTest(reverse_link=reverse_link), self.assertRaises(ValueError):
				backfill.select_candidates([row()], {reverse_link})

	def test_manifest_is_order_independent_and_detects_any_source_change(self):
		rows = [row("B"), row("A")]
		digest = backfill.manifest_digest(rows)
		self.assertEqual(digest, backfill.manifest_digest(list(reversed(rows))))
		backfill.verify_manifest(rows, 2, digest)
		for changed in [[row("B", payment_amount=16), row("A")], [row("A")]]:
			with self.subTest(changed=changed), self.assertRaises(ValueError):
				backfill.verify_manifest(changed, 2, digest)
		with self.assertRaises(ValueError):
			backfill.verify_manifest(rows, 2, "0" * 64)

	def test_readback_allows_only_selected_company_and_standard_modified_fields(self):
		before = [row(), row("known", target_company="Other Company")]
		after = copy.deepcopy(before)
		after[0].update(target_company="YUEWEI MX", modified="2026-10-04", modified_by="actor@example.com")
		backfill.verify_rows(before, after, {"OA-1"}, "actor@example.com")
		for index, field, value in [(0, "payment_amount", 16), (1, "modified", "2026-10-04"),
			(0, "target_company", "Other Company"), (0, "modified_by", "Other User")]:
			changed = copy.deepcopy(after)
			changed[index][field] = value
			with self.subTest(field=field), self.assertRaises(ValueError):
				backfill.verify_rows(before, changed, {"OA-1"}, "actor@example.com")

	def test_version_is_exactly_one_company_change_and_no_child_changes(self):
		valid = {"changed": [["target_company", "", "YUEWEI MX"]], "added": [], "removed": [], "row_changed": []}
		backfill.verify_version(valid)
		for invalid in [{**valid, "added": [["items", {}]]}, {**valid, "changed": valid["changed"] + [["currency", "", "MXN"]]},
			{**valid, "changed": [["target_company", "Other Company", "YUEWEI MX"]]}]:
			with self.subTest(invalid=invalid), self.assertRaises(ValueError):
				backfill.verify_version(invalid)

	def test_production_writes_require_exact_count_and_maintenance(self):
		backfill.verify_execution("deeplinkerp.com", "apply", 148, True)
		for arguments in [("other.site", "apply", 148, True), ("po-grid-qa.localhost", "apply", 2, True),
			("deeplinkerp.com", "apply", 147, True), ("deeplinkerp.com", "dry-run", 148, False)]:
			with self.subTest(arguments=arguments), self.assertRaises(ValueError):
				backfill.verify_execution(*arguments)

	def test_post_commit_report_failure_is_explicitly_committed_not_retryable_failure(self):
		commits = []
		frappe = SimpleNamespace(db=SimpleNamespace(commit=lambda: commits.append(True)))
		self.assertTrue(hasattr(backfill, "commit_and_record"), "Commit reporting must distinguish post-commit IO errors")
		with patch.object(backfill, "write_private_report", side_effect=OSError("disk full")):
			result = backfill.commit_and_record(frappe, "/private/report", "deeplinkerp.com", {"count": 148}, lambda: None)
		self.assertEqual(commits, [True])
		self.assertEqual(result["status"], "committed")
		self.assertIn("disk full", result["report_marker_warning"])

	def test_commit_callback_failure_requires_durable_readback_before_success(self):
		frappe = SimpleNamespace(db=SimpleNamespace(commit=lambda: (_ for _ in ()).throw(RuntimeError("after commit"))))
		verified = []
		with patch.object(backfill, "write_private_report"):
			result = backfill.commit_and_record(frappe, "/private/report", "deeplinkerp.com", {}, lambda: verified.append(True))
		self.assertEqual(verified, [True])
		self.assertEqual(result["status"], "committed")
		self.assertIn("after commit", result["commit_warning"])
		with patch.object(backfill, "write_private_report") as write_report:
			with self.assertRaisesRegex(RuntimeError, "not confirmed.*Do not retry"):
				backfill.commit_and_record(frappe, "/private/report", "deeplinkerp.com", {},
					lambda: (_ for _ in ()).throw(ValueError("not persisted")))
			write_report.assert_not_called()


if __name__ == "__main__":
	unittest.main()
