app_name = "custom_filters"
app_title = "Custom Filters"
app_publisher = "yuewei"
app_description = "custom filters"
app_email = "308642281@qq.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "custom_filters",
# 		"logo": "/assets/custom_filters/logo.png",
# 		"title": "Custom Filters",
# 		"route": "/custom_filters",
# 		"has_permission": "custom_filters.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = [
	"/assets/custom_filters/css/desk_tabs.css",
	"/assets/custom_filters/css/right_sidebar.css",
	"/assets/custom_filters/css/grid_column_resize.css?v=2026.08.31.2",
]
app_include_js = [
	"/assets/custom_filters/js/naming_series_i18n.js",
	"/assets/custom_filters/js/desk_tabs.js",
	"/assets/custom_filters/js/desktop_user_menu.js",
	"/assets/custom_filters/js/right_sidebar.js?v=2026.08.31.1",
	"/assets/custom_filters/js/grid_column_resize.js?v=2026.08.31.2",
	"/assets/custom_filters/js/info_card_i18n.js",
	"/assets/custom_filters/js/warehouse_query.js",
]

# include js, css files in header of web template
# web_include_css = "/assets/custom_filters/css/custom_filters.css"
# web_include_js = "/assets/custom_filters/js/custom_filters.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "custom_filters/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views

doctype_js = {
	"Material Request": "public/js/material_request.js",
	"Stock Entry": "public/js/stock_entry.js",
	"Sales Order": "public/js/sales_order.js",
	"Purchase Order": "public/js/purchase_order.js",
	"Item": "public/js/item.js",
	"Production Plan": "public/js/production_plan.js",
	"Supplier Quotation": "public/js/supplier_quotation.js",
}

doctype_list_js = {
	"Item": "public/js/item_list.js",
	"Bin": "public/js/bin_list.js",
	"Sales Order": "public/js/sales_order_list.js",
	"Supplier Quotation": "public/js/supplier_quotation_list.js",
}

override_whitelisted_methods = {
	"erpnext.manufacturing.doctype.production_plan.production_plan.get_items_for_material_requests":
		"custom_filters.production_plan.get_items_for_material_requests",
}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "custom_filters/public/icons.svg"

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
# 	"methods": "custom_filters.utils.jinja_methods",
# 	"filters": "custom_filters.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "custom_filters.install.before_install"
# after_install = "custom_filters.install.after_install"

# Migration
# ------------

after_migrate = "custom_filters.custom_filters.setup.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "custom_filters.uninstall.before_uninstall"
# after_uninstall = "custom_filters.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "custom_filters.utils.before_app_install"
# after_app_install = "custom_filters.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "custom_filters.utils.before_app_uninstall"
# after_app_uninstall = "custom_filters.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "custom_filters.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "custom_filters.notifications.get_notification_config"

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

doc_events = {
	"Supplier Quotation": {
		"validate": "custom_filters.custom_filters.supplier_quotation.set_default_warehouse",
		"on_submit": "custom_filters.quote_pricing.sync_quotation_tiers_on_submit",
		"on_cancel": "custom_filters.quote_pricing.disable_quotation_tiers_on_cancel",
	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"custom_filters.tasks.all"
# 	],
# 	"daily": [
# 		"custom_filters.tasks.daily"
# 	],
# 	"hourly": [
# 		"custom_filters.tasks.hourly"
# 	],
# 	"weekly": [
# 		"custom_filters.tasks.weekly"
# 	],
# 	"monthly": [
# 		"custom_filters.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "custom_filters.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "custom_filters.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "custom_filters.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "custom_filters.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["custom_filters.utils.before_request"]
# after_request = ["custom_filters.utils.after_request"]

# Job Events
# ----------
# before_job = ["custom_filters.utils.before_job"]
# after_job = ["custom_filters.utils.after_job"]

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
# 	"custom_filters.auth.validate"
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
