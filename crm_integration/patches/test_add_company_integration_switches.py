from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from crm_integration.patches.add_company_integration_switches import execute


class TestAddCompanyIntegrationSwitches(UnitTestCase):
	def test_new_company_switch_defaults_to_disabled_without_data_update(self):
		with (
			patch(
				"crm_integration.patches.add_company_integration_switches.create_custom_fields"
			) as create_custom_fields,
			patch.object(frappe, "clear_cache"),
			patch.object(frappe.db, "sql") as sql,
		):
			execute()

		field = create_custom_fields.call_args.args[0]["Company"][0]
		self.assertEqual(field["fieldname"], "custom_enable_crm_integration")
		self.assertEqual(field["default"], "0")
		sql.assert_not_called()
