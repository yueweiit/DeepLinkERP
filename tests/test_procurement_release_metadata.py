"""Only approved metadata deltas pass; business and existing permissions remain frozen."""

import copy
import runpy
import unittest
from pathlib import Path

module = runpy.run_path(str(Path(__file__).parents[1] / "deploy/production/procurement_release_metadata.py"))


class ProcurementReleaseMetadataTests(unittest.TestCase):
	def test_only_the_two_payment_models_expand_the_reviewed_release_scope(self):
		self.assertEqual(set(module["JOINT_MODELS"]), {"Operating Expense Company Map","Operating Expense Source","Operating Expense Mapping","Operating Expense Event","Operating Expense Sync Settings","Purchase Fulfilment Link","Operating Expense Takeover","Operating Expense Payment"})
	def fixture(self):
		old = {
			"scope": {"Page": [], "Has Role": []},
			"outside": {"Has Role": {"count": 20, "sha256": "existing"}},
		}
		new = copy.deepcopy(old)
		new["scope"]["Page"] = [{"name": "purchase-payables"}]
		new["scope"]["Has Role"] = [
			{"role": role, "name": f"new-{index}"}
			for index, role in enumerate(("System Manager", "Accounts User", "Accounts Manager"))
		]
		receipt = {
			"before": old,
			"after": new,
			"new_page": True,
			"semantic_validated": True,
			"second_reconcile_unchanged": True,
		}
		before = {
			"procurement_metadata": copy.deepcopy(old),
			"tables": {
				"Has Role": {"count": 20, "sha256": "old"},
				"Payment Entry": {"count": 8, "sha256": "unchanged"},
			},
		}
		after = {
			"procurement_metadata": copy.deepcopy(new),
			"tables": {
				"Has Role": {"count": 23, "sha256": "new"},
				"Payment Entry": {"count": 8, "sha256": "unchanged"},
			},
		}
		return before, after, receipt

	def test_only_validated_receipt_removes_expected_three_new_page_roles(self):
		before, after, receipt = self.fixture()
		module["verify_audit_delta"](before, after, receipt)
		self.assertEqual(before, after)

	def test_receipt_rejects_outside_permission_drift_count_role_or_idempotence_failure(self):
		for scenario in ("outside", "count", "role", "receipt", "second-run", "unvalidated"):
			with self.subTest(scenario=scenario):
				before, after, receipt = self.fixture()
				if scenario == "outside":
					receipt["after"]["outside"]["Has Role"]["sha256"] = "changed-existing-ids"
					after["procurement_metadata"] = copy.deepcopy(receipt["after"])
				elif scenario == "count":
					after["tables"]["Has Role"]["count"] += 1
				elif scenario == "role":
					receipt["after"]["scope"]["Has Role"][0]["role"] = "Purchase User"
					after["procurement_metadata"] = copy.deepcopy(receipt["after"])
				elif scenario == "receipt":
					after["procurement_metadata"]["scope"]["Page"][0]["name"] = "other-page"
				elif scenario == "second-run":
					receipt["second_reconcile_unchanged"] = False
				else:
					receipt["semantic_validated"] = False
				with self.assertRaises(AssertionError):
					module["verify_audit_delta"](before, after, receipt)

	def test_business_drift_remains_in_strict_equality_after_metadata_validation(self):
		before, after, receipt = self.fixture()
		after["tables"]["Payment Entry"]["sha256"] = "unexpected-payment"
		module["verify_audit_delta"](before, after, receipt)
		self.assertNotEqual(before, after)

	def test_existing_child_id_creation_and_custom_values_cannot_be_normalized_away(self):
		normalize = module["normalize_document"]
		row = {
			"name": "existing",
			"parenttype": "Workspace",
			"creation": "original",
			"modified": "now",
			"modified_by": "Administrator",
			"filters": "custom",
			"label": "My filter",
		}
		original = normalize(row, {"existing"})
		for field in ("name", "creation", "filters", "label"):
			with self.subTest(field=field):
				changed = dict(row, **{field: "other"})
				self.assertNotEqual(original, normalize(changed, {"existing"}))

	def test_existing_page_roles_must_keep_their_ids(self):
		before, after, receipt = self.fixture()
		receipt["new_page"] = False
		receipt["before"]["scope"] = copy.deepcopy(receipt["after"]["scope"])
		before["procurement_metadata"] = copy.deepcopy(receipt["before"])
		before["tables"]["Has Role"]["count"] = 23
		before["tables"]["Has Role"]["sha256"] = after["tables"]["Has Role"]["sha256"]
		module["verify_audit_delta"](before, after, receipt)
		self.assertEqual(before, after)
		before, after, receipt = self.fixture()
		receipt["new_page"] = False
		receipt["before"]["scope"] = copy.deepcopy(receipt["after"]["scope"])
		receipt["before"]["scope"]["Has Role"][0]["name"] = "original-id"
		before["procurement_metadata"] = copy.deepcopy(receipt["before"])
		with self.assertRaises(AssertionError):
			module["verify_audit_delta"](before, after, receipt)
