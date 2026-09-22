import frappe
from frappe.tests import IntegrationTestCase, set_user

from mobile_operations.api import (
	_search_mobile_items,
	get_mobile_inventory_suggestions,
	search_mobile_material_request_items,
	search_mobile_stock_entry_items,
)


class TestMobileItemSearch(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.token = frappe.generate_hash(length=10).upper()
		self.query = f"ZZMOBILE{self.token}"
		self.addCleanup(frappe.db.rollback)

	def make_item(self, code, item_name="Test material", description=None, disabled=0):
		# Search fixtures only; avoid invoking stock and integration document hooks.
		frappe.get_doc({
			"doctype": "Item",
			"name": code,
			"item_code": code,
			"item_name": item_name,
			"description": description,
			"stock_uom": "Nos",
			"disabled": disabled,
		}).db_insert()
		return code

	def test_code_matches_are_ranked_before_applying_limit_in_all_selectors(self):
		expected = [self.make_item(self.query)]
		expected += [self.make_item(f"{self.query}{number:04d}") for number in (1, 2)]
		self.make_item(f"{self.query}0000", disabled=1)
		self.make_item(f"AA-{self.query}")
		# These sort before the requested codes and used to consume the entire result limit.
		for number in range(20):
			self.make_item(f"AA-{self.token}-{number:02d}", item_name=f"ny{self.query}on")

		for query in (self.query, self.query.lower(), f" {self.query} "):
			with self.subTest(query=query):
				for search in (search_mobile_stock_entry_items, search_mobile_material_request_items):
					self.assertEqual([row.name for row in search(query, limit=3)], expected)
				inventory = get_mobile_inventory_suggestions(kind="item", search_text=query, limit=3)
				self.assertEqual([row["value"] for row in inventory["suggestions"]], expected)

	def test_partial_code_precedes_name_and_description_matches(self):
		code = self.make_item(f"ZZ-{self.query}")
		name = self.make_item(f"AA-{self.token}-NAME", item_name=f"物料 {self.query}")
		description = self.make_item(f"AA-{self.token}-DESC", description=f"规格 {self.query}")
		rows = search_mobile_stock_entry_items(self.query)
		self.assertEqual([row.name for row in rows], [code, name, description])
		self.assertEqual(rows[0].stock_uom, "Nos")

	def test_name_and_description_searches_work_without_code_matches(self):
		name = self.make_item(f"AA-{self.token}-NAME", item_name=f"原料 {self.query}")
		description = self.make_item(f"AA-{self.token}-DESC", description=f"规格 {self.query}")
		self.assertEqual(
			[row.name for row in search_mobile_material_request_items(self.query)],
			[name, description],
		)

	def test_typed_wildcards_do_not_match_unrelated_codes(self):
		self.make_item(f"{self.query}XPART")
		self.make_item(f"{self.query}PART")
		for character in ("%", "_", "\\"):
			with self.subTest(character=character):
				query = f"{self.query}{character}PART"
				code = self.make_item(query)
				self.assertEqual([row.name for row in search_mobile_stock_entry_items(query)], [code])

	def test_permissions_are_preserved(self):
		with set_user("Guest"):
			for search in (_search_mobile_items, search_mobile_stock_entry_items, search_mobile_material_request_items):
				with self.subTest(search=search.__name__), self.assertRaises(frappe.PermissionError):
					search(self.query)
			with self.assertRaises(frappe.PermissionError):
				get_mobile_inventory_suggestions(kind="item", search_text=self.query)
