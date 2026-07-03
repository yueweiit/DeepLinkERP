import frappe


WORKSPACE_NAME = "Manufacturing"
LINK_LABEL = "MES 系统"
LINK_TO = "mes-portal"
TOOLS_CARD_LABEL = "Tools"


def execute():
	if not frappe.db.exists("Workspace", WORKSPACE_NAME):
		return

	workspace = frappe.get_doc("Workspace", WORKSPACE_NAME)
	if has_mes_portal_link(workspace):
		return

	workspace.append(
		"links",
		{
			"type": "Link",
			"label": LINK_LABEL,
			"link_type": "Page",
			"link_to": LINK_TO,
			"hidden": 0,
			"is_query_report": 0,
			"onboard": 0,
		},
		position=get_insert_position(workspace),
	)
	workspace.save(ignore_permissions=True)
	frappe.clear_cache(doctype="Workspace")


def has_mes_portal_link(workspace):
	return any(link.type == "Link" and link.link_type == "Page" and link.link_to == LINK_TO for link in workspace.links)


def get_insert_position(workspace):
	for index, link in enumerate(workspace.links):
		if link.type == "Card Break" and link.label == TOOLS_CARD_LABEL:
			return index + 1

	return len(workspace.links)
