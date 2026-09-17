app_name = "mobile_operations"
app_title = "Mobile Operations"
app_publisher = "yuewei"
app_description = "Mobile warehouse and manufacturing operations for ERPNext"
app_email = "akivision@example.com"
app_license = "mit"

required_apps = ["erpnext", "mes_integration"]

# Keep the mobile workspace outside Desk.  The catch-all rule allows the
# client-side router to keep a useful URL when a user refreshes a mobile page.
website_route_rules = [
	{"from_route": "/mobile/login", "to_route": "mobile/login"},
	{"from_route": "/mobile", "to_route": "mobile"},
	{"from_route": "/mobile/<path:subpath>", "to_route": "mobile"},
]
