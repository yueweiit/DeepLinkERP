(() => {
	const system_log_doctypes = new Set([
		"MES Material Request Task",
		"MES Integration Log",
	]);
	const target_sidebar = "System";
	const patch_flag = Symbol.for("mes_integration.system_log_sidebar_patched");
	let attempts = 0;

	function clear_stale_sidebar_preferences() {
		try {
			const preferences = JSON.parse(localStorage.getItem("sidebar_item_map") || "{}");
			let changed = false;

			for (const doctype of system_log_doctypes) {
				if (preferences[doctype]) {
					delete preferences[doctype];
					changed = true;
				}
			}

			if (changed) {
				localStorage.setItem("sidebar_item_map", JSON.stringify(preferences));
			}
		} catch (error) {
			console.warn("Unable to clear MES sidebar preferences", error);
		}
	}

	function install_sidebar_override() {
		const Sidebar = window.frappe?.ui?.Sidebar;
		if (!Sidebar?.prototype?.resolve_sidebar) {
			attempts += 1;
			if (attempts < 100) {
				window.setTimeout(install_sidebar_override, 50);
			}
			return;
		}

		const prototype = Sidebar.prototype;
		if (!prototype[patch_flag]) {
			const resolve_sidebar = prototype.resolve_sidebar;
			prototype.resolve_sidebar = function (entity, module) {
				if (
					system_log_doctypes.has(entity) &&
					frappe.boot.workspace_sidebar_item?.[target_sidebar.toLowerCase()]
				) {
					this.preferred_sidebars = this.get_workspace_sidebars(entity);
					return target_sidebar;
				}

				return resolve_sidebar.call(this, entity, module);
			};
			prototype[patch_flag] = true;
		}

		clear_stale_sidebar_preferences();

		// The first route can be resolved before app_include_js finishes loading.
		// Resolve it once more so a direct URL or hard refresh is corrected too.
		window.setTimeout(() => {
			frappe.app?.sidebar?.set_workspace_sidebar(frappe.router);
		}, 0);
	}

	install_sidebar_override();
})();
