from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from crm_integration.crm_integration.auth import validate_crm_api_user


class TestCRMAuth(UnitTestCase):
	def test_validate_crm_api_user_rejects_non_crm_user(self):
		with (
			patch("crm_integration.crm_integration.auth.is_crm_api_user", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			validate_crm_api_user()

	def test_validate_crm_api_user_accepts_crm_user(self):
		with patch("crm_integration.crm_integration.auth.is_crm_api_user", return_value=True):
			validate_crm_api_user()
