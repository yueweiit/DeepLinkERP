app_name = "china_finance"
app_title = "China Finance"
app_publisher = "yuewei"
app_description = "China Financial Compliance for ERPNext"
app_email = "china@example.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext"]

after_install = "china_finance.setup.install.after_install"
after_migrate = "china_finance.setup.install.after_migrate"

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "china_finance",
# 		"logo": "/assets/china_finance/logo.png",
# 		"title": "China Finance",
# 		"route": "/china_finance",
# 		"has_permission": "china_finance.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = "/assets/china_finance/css/china_finance.css"
# app_include_js = "/assets/china_finance/js/china_finance.js"

# include js, css files in header of web template
# web_include_css = "/assets/china_finance/css/china_finance.css"
# web_include_js = "/assets/china_finance/js/china_finance.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "china_finance/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

doctype_js = {
	"Bank Statement Import": "public/js/bank_statement_import.js",
	"Sales Invoice": ["public/js/sales_invoice_invoice_control.js", "public/js/gl_source_snapshot.js"],
	"Sales Order": "public/js/sales_order_settlement.js",
	"Delivery Note": ["public/js/delivery_note_settlement.js", "public/js/gl_source_snapshot.js"],
	"Journal Entry": "public/js/gl_source_snapshot.js",
	"Payment Entry": [
		"public/js/payment_entry_invoice_selector.js",
		"public/js/gl_source_snapshot.js",
	],
	"Purchase Invoice": "public/js/gl_source_snapshot.js",
	"Purchase Receipt": "public/js/gl_source_snapshot.js",
	"Stock Entry": "public/js/gl_source_snapshot.js",
	"Asset": "public/js/gl_source_snapshot.js",
	"Asset Capitalization": "public/js/gl_source_snapshot.js",
	"Asset Depreciation Entry": "public/js/gl_source_snapshot.js",
	"Payroll Entry": "public/js/gl_source_snapshot.js",
	"Period Closing Voucher": "public/js/gl_source_snapshot.js",
	"China Finance Settings": "public/js/china_finance_settings.js",
	"China Accounting Voucher": "public/js/china_accounting_voucher.js",
	"China Cash Flow Assignment": "public/js/china_cash_flow_assignment.js",
	"China Financial Statement Mapping": "public/js/china_financial_statement_mapping.js",
}
doctype_list_js = {
	"Journal Entry": "public/js/source_voucher_number_list.js",
	"Payment Entry": "public/js/source_voucher_number_list.js",
	"China Accounting Voucher": "public/js/china_accounting_voucher_list.js",
	"China Financial Statement Template": "public/js/china_financial_statement_template_list.js",
	"China Financial Statement Mapping": "public/js/china_financial_statement_mapping_list.js",
	"China Sales Settlement": "public/js/china_sales_settlement_list.js",
}
page_js = {
	"bank-reconciliation-tool": "public/js/bank_reconciliation_tool.js",
}

app_include_js = ["/assets/china_finance/js/bank_reconciliation_tool.js"]

override_whitelisted_methods = {
	"erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool.get_bank_transactions":
		"china_finance.services.bank_reconciliation.get_bank_transactions_with_summary",
}

# Keep ERPNext's bank statement import workflow intact while allowing the
# China Finance bank adapters to return the complete converted-file preview.
override_doctype_class = {
	"Bank Statement Import": "china_finance.overrides.bank_statement_import.ChinaFinanceBankStatementImport",
}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "china_finance/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "china_finance.utils.jinja_methods",
# 	"filters": "china_finance.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "china_finance.install.before_install"
# after_install = "china_finance.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "china_finance.uninstall.before_uninstall"
# after_uninstall = "china_finance.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "china_finance.utils.before_app_install"
# after_app_install = "china_finance.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "china_finance.utils.before_app_uninstall"
# after_app_uninstall = "china_finance.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "china_finance.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "china_finance.notifications.get_notification_config"

# These records are audit trails derived from ERPNext business documents. They
# must remain queryable after a source is cancelled or deleted, but must never
# become reverse dependencies that block the native business workflow.
ignore_links_on_delete = [
	"China Accounting Voucher",
	"China Cash Flow Assignment",
	"China Voucher Sync Issue",
	"China Electronic Document",
	"China Reconciliation Difference",
]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

_gl_source_approval_events = {
	"before_submit": "china_finance.services.voucher.validate_source_approval",
	"before_cancel": "china_finance.services.voucher.prepare_source_cancellation",
}

_journal_entry_events = {
	"before_naming": "china_finance.services.naming.sync_journal_entry_series",
	**_gl_source_approval_events,
}

doc_events = {
	doctype: _journal_entry_events if doctype == "Journal Entry" else _gl_source_approval_events
	for doctype in (
		"Journal Entry",
		"Payment Entry",
		"Sales Invoice",
		"Purchase Invoice",
		"Stock Entry",
		"Delivery Note",
		"Purchase Receipt",
		"Asset",
		"Asset Capitalization",
		"Asset Depreciation Entry",
		"Payroll Entry",
		"Period Closing Voucher",
	)
}
doc_events["Company"] = {"on_update": "china_finance.api.initialize_profile_company_on_update"}
doc_events["China Finance Settings"] = {"on_update": "china_finance.api.sync_settings_mappings_on_update"}
doc_events["Sales Order"] = {"before_insert": "china_finance.services.sales_settlement.apply_sales_order_settlement_mode"}
doc_events["Delivery Note"] = {
	"before_submit": [
		"china_finance.services.voucher.validate_source_approval",
		"china_finance.services.sales_settlement.validate_delivery_note_settlement_mode",
	],
	"before_cancel": "china_finance.services.voucher.prepare_source_cancellation",
	"on_submit": [
		"china_finance.services.voucher.on_gl_source_submit",
		"china_finance.services.auto_invoice.on_delivery_note_submit",
	],
}
doc_events["Purchase Receipt"] = {
	"before_submit": "china_finance.services.voucher.validate_source_approval",
	"before_cancel": "china_finance.services.voucher.prepare_source_cancellation",
	"on_submit": [
		"china_finance.services.voucher.on_gl_source_submit",
		"china_finance.services.auto_invoice.on_purchase_receipt_submit",
	],
}
doc_events["Sales Invoice"] = {
	"before_submit": [
		"china_finance.services.voucher.validate_source_approval",
		"china_finance.services.sales_settlement.validate_sales_invoice_settlement",
	],
	"before_cancel": "china_finance.services.voucher.prepare_source_cancellation",
	"on_cancel": "china_finance.services.sales_settlement.handle_sales_invoice_cancellation",
}
doc_events["*"] = {
	"on_submit": "china_finance.services.voucher.on_gl_source_submit",
	"on_cancel": "china_finance.services.voucher.on_gl_source_cancel",
}
doc_events["Bank Transaction"] = {
	"on_submit": "china_finance.services.bank_reconciliation.auto_create_voucher_on_submit",
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": ["china_finance.tasks.backfill_voucher_snapshots"],
}

# Testing
# -------

# before_tests = "china_finance.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "china_finance.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "china_finance.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "china_finance.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["china_finance.utils.before_request"]
# after_request = ["china_finance.utils.after_request"]

# Job Events
# ----------
# before_job = ["china_finance.utils.before_job"]
# after_job = ["china_finance.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"china_finance.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# China Finance deliberately uses standard ERPNext posting behavior. Regional
# overrides are not required because statutory vouchers are immutable snapshots
# of the resulting GL Entries.
