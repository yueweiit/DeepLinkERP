from urllib.parse import urlencode

import frappe


no_cache = 1


def get_context(context):
	"""Render the mobile shell for logged-in system users only."""
	if frappe.session.user == "Guest":
		redirect_to = frappe.local.request.path or "/mobile"
		if not redirect_to.startswith("/mobile"):
			redirect_to = "/mobile"
		frappe.redirect(f"/mobile/login?{urlencode({'redirect-to': redirect_to})}")

	return context
