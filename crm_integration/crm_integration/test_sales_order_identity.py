from unittest.mock import call, patch

from frappe.tests import UnitTestCase

from crm_integration.crm_integration.sales_order_identity import (
	crm_sales_order_creation_lock,
	make_crm_order_lock_name,
)


class TestSalesOrderIdentity(UnitTestCase):
	def test_lock_name_is_stable_and_within_mariadb_limit(self):
		first = make_crm_order_lock_name("CRM-001")
		second = make_crm_order_lock_name("CRM-001")

		self.assertEqual(first, second)
		self.assertLessEqual(len(first), 64)

	def test_creation_lock_is_always_released(self):
		lock_name = make_crm_order_lock_name("CRM-001")

		with patch(
			"crm_integration.crm_integration.sales_order_identity.frappe.db.sql",
			return_value=[(1,)],
		) as sql:
			with crm_sales_order_creation_lock("CRM-001"):
				pass

		self.assertEqual(
			sql.call_args_list,
			[
				call("SELECT GET_LOCK(%s, %s)", (lock_name, 10)),
				call("SELECT RELEASE_LOCK(%s)", (lock_name,)),
			],
		)
