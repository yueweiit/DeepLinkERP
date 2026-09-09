from frappe.tests import UnitTestCase

from china_finance.services.account_display import get_account_display_name, get_account_display_title


class TestAccountDisplay(UnitTestCase):
	def test_display_title_keeps_number_and_omits_company_suffix(self):
		self.assertEqual(
			get_account_display_title("1001", "库存现金"),
			"1001 - 库存现金",
		)

	def test_display_title_falls_back_to_number_when_name_is_empty(self):
		self.assertEqual(get_account_display_title("1001", None), "1001")

	def test_six_digit_child_keeps_category_name_under_four_digit_group(self):
		self.assertEqual(
			get_account_display_name("销售费用－职工薪酬", "销售费用", "660101", "6601"),
			"销售费用－职工薪酬",
		)
		self.assertEqual(
			get_account_display_title("660101", "销售费用－职工薪酬", "销售费用", "6601"),
			"660101 - 销售费用－职工薪酬",
		)

	def test_six_digit_child_without_repeated_group_name_is_unchanged(self):
		self.assertEqual(
			get_account_display_name("城市维护建设税", "税金及附加", "640301", "6403"),
			"城市维护建设税",
		)
