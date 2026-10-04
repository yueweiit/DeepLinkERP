import re
import unittest
from pathlib import Path

from deeplinkerp_branding import hooks


class PurchaseOrderAssetsTest(unittest.TestCase):
	def test_ci_runs_navigation_and_purchase_order_regressions(self):
		workflow = (
			Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
		).read_text()
		self.assertIn("node --test tests/*.test.js", workflow)
		for suite in (
			"tests.test_interface_mode",
			"tests.test_boot_branding",
			"tests.test_interface_mode_metadata",
			"tests.test_purchase_order_assets",
		):
			self.assertIn(suite, workflow)

	def test_compact_list_is_registered_only_for_supported_native_lists(self):
		self.assertEqual(
			getattr(hooks, "doctype_list_js", {}),
			{"Purchase Order": "public/js/purchase_order_list.js", "Material Request": "public/js/material_request_list.js", "Purchase Receipt": "public/js/purchase_receipt_list.js", "Sales Order": "public/js/sales_order_list.js"},
		)

	def test_unified_adapter_loads_after_cache_busted_shared_engine(self):
		scripts = hooks.app_include_js
		engine = "/assets/deeplinkerp_branding/js/compact_list.js?v=0.0.6"
		adapter = "/assets/deeplinkerp_branding/js/unified_purchase_list.js?v=0.0.1"
		self.assertIn(engine, scripts)
		self.assertLess(scripts.index(engine), scripts.index(adapter))

	def test_desk_loads_compact_styles_without_changing_website_assets(self):
		styles = hooks.app_include_css
		if isinstance(styles, str):
			styles = [styles]
		self.assertTrue(any("deeplinkerp_navigation.css" in style for style in styles))
		self.assertEqual(
			len([style for style in styles if "purchase_order_list.css" in style]), 1
		)
		self.assertNotIn("purchase_order_list", str(hooks.web_include_css))

	def test_header_and_rows_do_not_distribute_extra_width_between_columns(self):
		css = (
			Path(__file__).resolve().parents[1]
			/ "deeplinkerp_branding/public/css/purchase_order_list.css"
		).read_text()
		css = css.replace("body:is(.dlp-purchase-order-grid-active, .dlp-material-request-grid-active, .dlp-purchase-receipt-grid-active, .dlp-sales-order-grid-active)", "body.dlp-purchase-order-grid-active")
		shared_grid_rule = re.search(
			r"\.dlp-po-grid-header-columns,\s*"
			r"body\.dlp-purchase-order-grid-active \.dlp-po-grid-row\s*\{([^}]+)\}",
			css,
		)
		self.assertIsNotNone(shared_grid_rule)
		self.assertRegex(
			shared_grid_rule.group(1),
			r"justify-content:\s*start\s*;",
			"Native .level space-between must not offset data columns on wide screens",
		)
		self.assertRegex(shared_grid_rule.group(1), r"font-size:\s*inherit\s*;")
		header_rule = re.search(r"\.dlp-po-grid-header\s*\{([^}]+)\}", css)
		self.assertIsNotNone(header_rule)
		self.assertRegex(header_rule.group(1), r"font-size:\s*inherit\s*;")


if __name__ == "__main__":
	unittest.main()
