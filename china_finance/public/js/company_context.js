frappe.provide("china_finance.company_context");

// A company choice belongs to this user's current tab, not to the site defaults.
(() => {
	const context = china_finance.company_context;
	const workspace_path = "/desk/china-finance";
	let selected_company;
	let selection;
	let selected_before_navigation = false;
	let last_route;
	const storage_key = () => `china_finance:company:${frappe.session.user}`;

	context.get_company = () => {
		if (selected_company === undefined) {
			try {
				selected_company = sessionStorage.getItem(storage_key()) || "";
			} catch {
				selected_company = "";
			}
		}
		return selected_company;
	};

	context.default_company = () => context.get_company() || frappe.defaults.get_user_default("Company");

	function is_workspace() {
		const route = frappe.get_route() || [];
		return route[0] === "Workspaces" && route[1] === "China Finance";
	}

	function update_workspace_action() {
		if (!is_workspace() || !frappe.workspace?.is_read_only) return;
		const company = context.get_company();
		frappe.workspace.page.set_secondary_action(
			company ? __("当前公司：{0}", [company]) : __("选择公司"),
			() => context.select_company(),
			"building-2"
		);
	}

	context.select_company = () => {
		if (selection) return selection;
		selection = new Promise((resolve) => {
			let chosen = null;
			let saving = false;
			const dialog = new frappe.ui.Dialog({
				title: __("选择公司"),
				size: "small",
				fields: [{
					fieldname: "company", label: __("公司"), fieldtype: "Link", options: "Company",
					reqd: 1, default: context.default_company() || "",
					get_query: () => ({ filters: { is_group: 0 } }),
				}],
			});
			dialog.set_primary_action(__("确定"), async () => {
				const values = dialog.get_values();
				if (!values?.company || saving) return;
				saving = true;
				dialog.get_primary_btn().prop("disabled", true);
				try {
					// Use the permission-aware client API before remembering a Link value.
					const response = await frappe.db.get_value("Company", values.company, ["name", "is_group"]);
					if (!response.message?.name || response.message.is_group) {
						frappe.msgprint(__("请选择有权访问的非集团公司"));
						return;
					}
					if (!dialog.display) return;
					chosen = selected_company = response.message.name;
					try { sessionStorage.setItem(storage_key(), chosen); } catch { /* Keep the in-memory choice. */ }
					update_workspace_action();
					dialog.hide();
				} catch {
					if (dialog.display) frappe.msgprint(__("无法确认公司，请检查权限或网络后重试"));
				} finally {
					saving = false;
					dialog.get_primary_btn().prop("disabled", false);
				}
			});
			dialog.onhide = () => { selection = null; resolve(chosen); };
			dialog.show();
		});
		return selection;
	};

	function navigation_target(url) {
		const path = decodeURIComponent(url.pathname).replace(/\/$/, "");
		const items = frappe.boot.workspace_sidebar_item?.["china finance"]?.items || [];
		return items.find((item) => {
			if (item.type !== "Link") return false;
			if (item.link_type === "Report") return path === `/desk/query-report/${item.link_to}`;
			if (item.link_type === "Page") return path === `/desk/${item.link_to}`;
			if (item.link_type === "DocType") {
				const base = `/desk/${frappe.router.slug(item.link_to)}`;
				return path === base || path === `${base}/view/list`;
			}
			return false;
		});
	}

	// Pass filters before Frappe loads a page, including already-cached lists/reports.
	// Existing document URLs are deliberately not navigation targets.
	context.route_for_company = async (href) => {
		const url = new URL(href, window.location.origin);
		const company = context.get_company();
		if (!company || url.origin !== window.location.origin) return null;
		const target = navigation_target(url);
		if (!target) return null;
		if (target.link_type === "DocType") {
			await frappe.model.with_doctype(target.link_to);
			if (!frappe.meta.get_docfield(target.link_to, "company")) return null;
		}
		// ListView parses array filters from the URL; an explicit equality also
		// keeps a company name from being interpreted as serialized JSON.
		url.searchParams.set("company", target.link_type === "DocType" ? JSON.stringify(["=", company]) : company);
		// Already in the China Finance sidebar. Its v16 route listener clears
		// all route_options when a sidebar parameter is supplied, losing filters.
		url.searchParams.delete("sidebar");
		return url.pathname + url.search + url.hash;
	};

	function navigate(href) {
		const url = new URL(href, window.location.origin);
		frappe.route_options = Object.fromEntries([...url.searchParams].map(([key, value]) => {
			try { return [key, JSON.parse(value)]; } catch { return [key, value]; }
		}));
		frappe.route_hash = url.hash;
		return frappe.set_route(url.pathname);
	}

	document.addEventListener("click", async (event) => {
		if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
		const link = event.target.closest?.("a[href]");
		if (!link || link.hasAttribute("download")) return;
		const url = new URL(link.href, window.location.origin);
		if (url.origin !== window.location.origin) return;
		// Frappe gives URL sidebar items target="_blank"; this workspace entry
		// is an internal company switch and must stay in the current tab.
		if (url.pathname.replace(/\/$/, "") === workspace_path) {
			event.preventDefault();
			event.stopImmediatePropagation();
			if (await context.select_company()) {
				selected_before_navigation = !is_workspace();
				await navigate(workspace_path);
				frappe.after_ajax(update_workspace_action);
			}
			return;
		}
		if (link.target === "_blank") return;
		if (!context.get_company() || !navigation_target(url)) return;
		if (!is_workspace() && !link.closest('.body-sidebar[data-title="China Finance"]')) return;
		event.preventDefault();
		event.stopImmediatePropagation();
		const route = await context.route_for_company(link.href);
		await navigate(route || url.pathname + url.search + url.hash);
	}, true);

	function on_route() {
		const route = (frappe.get_route() || []).join("/");
		if (route === last_route) return;
		last_route = route;
		if (!is_workspace()) return;
		const already_selected = selected_before_navigation;
		selected_before_navigation = false;
		setTimeout(() => frappe.after_ajax(() => {
			if (!is_workspace()) return;
			update_workspace_action();
			if (!already_selected) context.select_company();
		}), 0);
	}

	$(document).on("app_ready", () => {
		frappe.router.on("change", on_route);
		on_route();
	});
})();
