import frappe


SIDEBAR_NAME = "Manufacturing"
LINK_LABEL = "MES 系统"
LINK_TO = "mes-portal"
TOOLS_SECTION_LABEL = "Tools"


def execute():
	if not frappe.db.exists("Workspace Sidebar", SIDEBAR_NAME):
		return

	sidebar = frappe.get_doc("Workspace Sidebar", SIDEBAR_NAME)
	if has_mes_portal_item(sidebar):
		return

	sidebar.append(
		"items",
		{
			"type": "Link",
			"label": LINK_LABEL,
			"link_type": "Page",
			"link_to": LINK_TO,
			"child": 1,
		},
		position=get_insert_position(sidebar),
	)
	sidebar.save(ignore_permissions=True)
	frappe.clear_cache(doctype="Workspace Sidebar")


def has_mes_portal_item(sidebar):
	return any(item.type == "Link" and item.link_type == "Page" and item.link_to == LINK_TO for item in sidebar.items)


def get_insert_position(sidebar):
	for index, item in enumerate(sidebar.items):
		if item.type == "Section Break" and item.label == TOOLS_SECTION_LABEL:
			return index + 1

	return len(sidebar.items)
