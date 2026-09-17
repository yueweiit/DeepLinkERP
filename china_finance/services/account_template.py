"""Bundled Yuewei chart-of-accounts template integration."""

import json
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import frappe


SOURCE_COMPANY = "悦为智能技术(东莞)有限公司"
COMPANY_TEMPLATE = f"{SOURCE_COMPANY}（公司科目模板）"
TEMPLATE_COUNTRY = "China"
TEMPLATE_DATA_PATH = Path(__file__).resolve().parent.parent / "setup" / "data" / "yuewei_company_chart.json"

CHART_METADATA_FIELDS = {
	"account_name",
	"account_number",
	"account_type",
	"account_category",
	"root_type",
	"is_group",
	"tax_rate",
	"account_currency",
}


def source_company_available():
	"""Return whether the source company is available for refreshing the snapshot."""
	return bool(
		frappe.db.exists("Company", SOURCE_COMPANY)
		and frappe.db.exists("Account", {"company": SOURCE_COMPANY})
	)


def count_chart_accounts(children):
	"""Count account nodes in a chart tree."""
	count = 0
	for account_name, child in children.items():
		if account_name in CHART_METADATA_FIELDS or not isinstance(child, dict):
			continue
		count += 1 + count_chart_accounts(child)
	return count


@lru_cache(maxsize=1)
def get_company_template_data():
	"""Load the deployable chart snapshot bundled with China Finance."""
	with TEMPLATE_DATA_PATH.open(encoding="utf-8") as template_file:
		data = json.load(template_file)

	if data.get("name") != COMPANY_TEMPLATE or not isinstance(data.get("tree"), dict):
		raise ValueError(f"Invalid company chart template: {TEMPLATE_DATA_PATH}")
	return data


def get_company_template_chart():
	"""Return the bundled chart tree used to create accounts for a new company."""
	return get_company_template_data()["tree"]


def company_template_available():
	"""Return whether a valid bundled chart snapshot is installed."""
	try:
		return bool(get_company_template_chart())
	except (OSError, ValueError, json.JSONDecodeError):
		return False


def build_company_template_chart(company):
	"""Build a lossless chart tree, including same-name sibling accounts."""
	accounts = frappe.get_all(
		"Account",
		filters={"company": company, "disabled": 0},
		fields=[
			"name",
			"account_name",
			"parent_account",
			"account_type",
			"account_category",
			"is_group",
			"root_type",
			"tax_rate",
			"account_number",
			"account_currency",
		],
		order_by="lft, rgt",
	)
	children_by_parent = defaultdict(list)
	for account in accounts:
		children_by_parent[account.parent_account or ""].append(account)

	def build_children(parent_name=""):
		tree = {}
		siblings = children_by_parent[parent_name]
		name_counts = Counter(account.account_name for account in siblings)
		for index, account in enumerate(siblings, start=1):
			key = account.account_name
			if name_counts[account.account_name] > 1:
				key = f"{account.account_number or index} - {account.account_name}"
			while key in tree:
				key = f"{key} ({index})"

			child = {"account_name": account.account_name}
			for fieldname in (
				"account_number",
				"account_type",
				"account_category",
				"tax_rate",
				"account_currency",
			):
				if account.get(fieldname):
					child[fieldname] = account.get(fieldname)
			if account.is_group:
				child["is_group"] = 1
			if not parent_name:
				child["root_type"] = account.root_type
			child.update(build_children(account.name))
			tree[key] = child
		return tree

	tree = build_children()
	if count_chart_accounts(tree) != len(accounts):
		raise ValueError(f"Not all accounts for {company} are connected to the account tree")
	return tree


def export_company_template():
	"""Refresh the bundled snapshot from the current source-company account tree."""
	if not source_company_available():
		frappe.throw(f"Source company is unavailable: {SOURCE_COMPANY}")

	tree = build_company_template_chart(SOURCE_COMPANY)
	payload = {
		"name": COMPANY_TEMPLATE,
		"country": TEMPLATE_COUNTRY,
		"source_company": SOURCE_COMPANY,
		"account_count": count_chart_accounts(tree),
		"tree": tree,
	}
	TEMPLATE_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
	TEMPLATE_DATA_PATH.write_text(
		json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8",
	)
	get_company_template_data.cache_clear()
	return {
		"path": str(TEMPLATE_DATA_PATH),
		"account_count": payload["account_count"],
	}


@frappe.whitelist()
def get_charts_for_country(country, with_standard=False):
	"""Add the bundled Yuewei chart to ERPNext's China template options."""
	from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import (
		get_charts_for_country as get_native_charts_for_country,
	)

	charts = get_native_charts_for_country(country, with_standard=with_standard) or []
	if country == TEMPLATE_COUNTRY and company_template_available():
		charts = [*charts, COMPANY_TEMPLATE]

	return list(dict.fromkeys(charts))
