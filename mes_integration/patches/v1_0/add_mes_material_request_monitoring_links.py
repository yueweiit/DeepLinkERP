import frappe


SOURCE_WORKSPACE = "Manufacturing"
TARGET_WORKSPACE = "System"
SECTION_LABEL = "Logs"
MONITORING_LINKS = (
	("MES 物料需求任务", "MES Material Request Task"),
	("MES 集成日志", "MES Integration Log"),
)
MONITORING_DOCTYPES = {link_to for _label, link_to in MONITORING_LINKS}


def execute():
	move_workspace_links()
	move_sidebar_links()
	frappe.clear_cache(doctype="Workspace")
	frappe.clear_cache(doctype="Workspace Sidebar")


def move_workspace_links():
	remove_links_from_workspace(SOURCE_WORKSPACE)
	if not frappe.db.exists("Workspace", TARGET_WORKSPACE):
		return

	workspace = frappe.get_doc("Workspace", TARGET_WORKSPACE)
	links = [link for link in workspace.links if not is_monitoring_link(link)]
	position = get_section_position(links, "Card Break")
	if position is None:
		links.append({"type": "Card Break", "label": SECTION_LABEL})
		position = len(links)

	links[position:position] = [get_workspace_link(label, link_to) for label, link_to in MONITORING_LINKS]
	set_row_indexes(links)
	workspace.set("links", links)
	workspace.save(ignore_permissions=True)


def remove_links_from_workspace(workspace_name):
	if not frappe.db.exists("Workspace", workspace_name):
		return

	workspace = frappe.get_doc("Workspace", workspace_name)
	links = [link for link in workspace.links if not is_monitoring_link(link)]
	if len(links) == len(workspace.links):
		return

	set_row_indexes(links)
	workspace.set("links", links)
	workspace.save(ignore_permissions=True)


def move_sidebar_links():
	remove_links_from_sidebar(SOURCE_WORKSPACE)
	if not frappe.db.exists("Workspace Sidebar", TARGET_WORKSPACE):
		return

	sidebar = frappe.get_doc("Workspace Sidebar", TARGET_WORKSPACE)
	items = [item for item in sidebar.items if not is_monitoring_link(item)]
	position = get_section_position(items, "Section Break")
	if position is None:
		items.append({"type": "Section Break", "label": SECTION_LABEL})
		position = len(items)

	items[position:position] = [get_sidebar_link(label, link_to) for label, link_to in MONITORING_LINKS]
	set_row_indexes(items)
	sidebar.set("items", items)
	sidebar.save(ignore_permissions=True)


def remove_links_from_sidebar(sidebar_name):
	if not frappe.db.exists("Workspace Sidebar", sidebar_name):
		return

	sidebar = frappe.get_doc("Workspace Sidebar", sidebar_name)
	items = [item for item in sidebar.items if not is_monitoring_link(item)]
	if len(items) == len(sidebar.items):
		return

	set_row_indexes(items)
	sidebar.set("items", items)
	sidebar.save(ignore_permissions=True)


def is_monitoring_link(row):
	return row.type == "Link" and row.link_type == "DocType" and row.link_to in MONITORING_DOCTYPES


def get_section_position(rows, break_type):
	for index, row in enumerate(rows):
		if row.type == break_type and row.label == SECTION_LABEL:
			return index + 1

	return None


def get_workspace_link(label, link_to):
	return {
		"type": "Link",
		"label": label,
		"link_type": "DocType",
		"link_to": link_to,
		"hidden": 0,
		"is_query_report": 0,
		"onboard": 0,
	}


def get_sidebar_link(label, link_to):
	return {
		"type": "Link",
		"label": label,
		"link_type": "DocType",
		"link_to": link_to,
		"child": 1,
		"indent": 0,
		"collapsible": 1,
		"keep_closed": 0,
		"show_arrow": 0,
	}


def set_row_indexes(rows):
	for index, row in enumerate(rows, start=1):
		if isinstance(row, dict):
			row["idx"] = index
		else:
			row.idx = index
