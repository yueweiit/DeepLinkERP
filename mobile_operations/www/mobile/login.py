from urllib.parse import urlencode

import frappe
from frappe.www.login import get_context as get_standard_login_context


no_cache = 1


def get_context(context):
	redirect_to = frappe.local.request.args.get("redirect-to") or "/mobile"
	if not redirect_to.startswith("/mobile"):
		redirect_to = "/mobile"

	if frappe.session.user != "Guest":
		frappe.local.flags.redirect_location = redirect_to
		raise frappe.Redirect

	# Reuse the standard login context so the mobile page follows the same
	# account rules, app logo, DingTalk/OAuth providers, and email-link setting
	# as the PC login page.
	context = get_standard_login_context(context)
	context.redirect_to = redirect_to
	context.mobile_login_redirect_query = urlencode({"redirect-to": redirect_to})
	context.title = frappe._("Login")
	return context
