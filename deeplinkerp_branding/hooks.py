app_name = "deeplinkerp_branding"
app_title = "Deeplinkerp Branding"
app_publisher = "yuewei"
app_description = "Deeplinkerp brand"
app_email = "308642281@qq.com"
app_license = "mit"
app_logo_url = "/assets/deeplinkerp_branding/logo/deeplinkerp_logo_radius.png?v=0.0.6"
favicon = "/assets/deeplinkerp_branding/logo/tab_logo.svg?v=0.0.6"
splash_image = "/assets/deeplinkerp_branding/logo/deeplinkerp_logo_radius.png?v=0.0.6"

# Apps
# ------------------

add_to_apps_screen = [
	{
		"name": app_name,
		"logo": "/assets/deeplinkerp_branding/logo/deeplinkerp_logo_radius.png?v=0.0.6",
		"title": app_title,
		"route": "/app/deeplinkerp-settings",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = "/assets/deeplinkerp_branding/css/deeplinkerp_navigation.css?v=0.0.7"
app_include_js = [
	"/assets/deeplinkerp_branding/js/deeplinkerp_navigation.js?v=0.0.11",
	"/assets/deeplinkerp_branding/js/deeplinkerp_interface_mode.js?v=0.0.1",
	"/assets/deeplinkerp_branding/js/deeplinkerp_branding.js?v=0.0.19",
]

# include js, css files in header of web template
web_include_css = "/assets/deeplinkerp_branding/css/deeplinkerp_branding.css"
# web_include_js = "/assets/deeplinkerp_branding/js/deeplinkerp_branding.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "deeplinkerp_branding/public/scss/website"

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

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "deeplinkerp_branding/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

boot_session = "deeplinkerp_branding.deeplinkerp_branding.branding.apply_boot_branding"

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
# 	"methods": "deeplinkerp_branding.utils.jinja_methods",
# 	"filters": "deeplinkerp_branding.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "deeplinkerp_branding.install.before_install"
# after_install = "deeplinkerp_branding.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "deeplinkerp_branding.uninstall.before_uninstall"
# after_uninstall = "deeplinkerp_branding.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "deeplinkerp_branding.utils.before_app_install"
# after_app_install = "deeplinkerp_branding.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "deeplinkerp_branding.utils.before_app_uninstall"
# after_app_uninstall = "deeplinkerp_branding.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "deeplinkerp_branding.build.after_build"
after_migrate = ["deeplinkerp_branding.deeplinkerp_branding.branding.apply_deeplinkerp_settings_branding"]
website_context = {
	"favicon": "/assets/deeplinkerp_branding/logo/tab_logo.svg?v=0.0.6",
	"splash_image": "/assets/deeplinkerp_branding/logo/deeplinkerp_logo_radius.png?v=0.0.6",
}

website_redirects = [
	{
		"source": "/favicon.ico",
		"target": "/assets/deeplinkerp_branding/logo/tab_logo.svg?v=0.0.6",
		"redirect_http_status": 302,
	},
	{
		"source": "/apple-touch-icon.png",
		"target": "/assets/deeplinkerp_branding/logo/deeplinkerp_logo_radius.png?v=0.0.6",
		"redirect_http_status": 302,
	},
	{
		"source": "/apple-touch-icon-precomposed.png",
		"target": "/assets/deeplinkerp_branding/logo/deeplinkerp_logo_radius.png?v=0.0.6",
		"redirect_http_status": 302,
	},
	{
		"source": "/site.webmanifest",
		"target": "/assets/deeplinkerp_branding/manifest.webmanifest",
		"redirect_http_status": 302,
	},
	{
		"source": "/manifest.json",
		"target": "/assets/deeplinkerp_branding/manifest.webmanifest",
		"redirect_http_status": 302,
	},
]

update_website_context = "deeplinkerp_branding.web_context.update_context"
# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "deeplinkerp_branding.notifications.get_notification_config"

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

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"deeplinkerp_branding.tasks.all"
# 	],
# 	"daily": [
# 		"deeplinkerp_branding.tasks.daily"
# 	],
# 	"hourly": [
# 		"deeplinkerp_branding.tasks.hourly"
# 	],
# 	"weekly": [
# 		"deeplinkerp_branding.tasks.weekly"
# 	],
# 	"monthly": [
# 		"deeplinkerp_branding.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "deeplinkerp_branding.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "deeplinkerp_branding.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "deeplinkerp_branding.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "deeplinkerp_branding.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["deeplinkerp_branding.utils.before_request"]
# after_request = ["deeplinkerp_branding.utils.after_request"]

# Job Events
# ----------
# before_job = ["deeplinkerp_branding.utils.before_job"]
# after_job = ["deeplinkerp_branding.utils.after_job"]

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
# 	"deeplinkerp_branding.auth.validate"
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
