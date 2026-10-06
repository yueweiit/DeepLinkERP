"""Narrow Page/assets contracts: no parallel business ListView override."""

import json
import unittest
from pathlib import Path

from deeplinkerp_branding import hooks

ROOT = Path(__file__).parents[1]


class OperatingExpenseAssetsTest(unittest.TestCase):
	def test_business_title_is_operating_expenses_without_route_rename(self):
		values = json.loads((ROOT / "deeplinkerp_branding/deeplinkerp_branding/page/operating_expenses/operating_expenses.json").read_text())
		self.assertEqual(values["title"], "运营支出")
		self.assertEqual(values["name"], "operating-expenses")
	def test_page_metadata_uses_only_existing_finance_roles(self):
		page = (
			ROOT / "deeplinkerp_branding/deeplinkerp_branding/page/operating_expenses/operating_expenses.json"
		)
		self.assertTrue(page.exists(), "Native operating-expenses Page missing")
		values = json.loads(page.read_text())
		self.assertEqual(values["name"], "operating-expenses")
		self.assertEqual(
			{r["role"] for r in values["roles"]}, {"Accounts User", "Accounts Manager", "System Manager"}
		)

	def test_shared_shell_assets_load_before_operating_drawer_and_provider(self):
		files = [path.split("?")[0] for path in hooks.app_include_js]
		shell = "/assets/deeplinkerp_branding/js/purchase_payments.js"
		drawer = "/assets/deeplinkerp_branding/js/operating_expense_drawer.js"
		provider = "/assets/deeplinkerp_branding/js/operating_expenses.js"
		self.assertIn(drawer, files)
		self.assertIn(provider, files)
		self.assertLess(files.index(shell), files.index(drawer))
		self.assertLess(files.index(drawer), files.index(provider))
		self.assertIn(drawer + "?v=0.0.11", hooks.app_include_js)
		self.assertNotIn("Operating Expense Source", hooks.doctype_list_js)
		self.assertEqual(len([p for p in hooks.app_include_css if "operating_expenses.css" in p]), 1)

	def test_shared_compact_styles_and_scoped_viewport_are_registered(self):
		shared = (ROOT / "deeplinkerp_branding/public/css/purchase_order_list.css").read_text()
		self.assertIn(", .dlp-operating-expense-grid-active)", shared)
		specific = ROOT / "deeplinkerp_branding/public/css/operating_expenses.css"
		self.assertTrue(specific.exists(), "Scoped operating-expenses styles missing")
		self.assertIn("--dlp-operating-result-max-height", specific.read_text())
		self.assertIn(
			"tests.test_operating_expense_contract", (ROOT / ".github/workflows/ci.yml").read_text()
		)
		self.assertIn(
			"tests.test_operating_expense_navigation", (ROOT / ".github/workflows/ci.yml").read_text()
		)

	def test_new_business_labels_have_spanish_translations(self):
		translations = (ROOT / "deeplinkerp_branding/translations/es.csv").read_text()
		for label in (
			"运营费用",
			"法律公司",
			"来源审批通过",
			"出纳已付",
			"出纳待付",
			"新确认费用",
			"生成费用凭证草稿",
			"生成结算凭证草稿",
			"尚未核销",
			"原始审批编号",
			"原始钉钉实例编号",
			"原始来源请求编号",
			"请先保存费用映射并生成或关联费用确认凭证，再维护本笔结算。",
			"费用确认凭证已记账，只能查看；后续实际付款仍可办理结算。",
			"来源版本已变化，请刷新抽屉后重新预览。",
			"本笔结算已记账、已取消或存在问题，只能查看。",
		):
			self.assertIn(label + ",", translations)
