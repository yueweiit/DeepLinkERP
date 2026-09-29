(function (root, factory) {
	const interfaceMode = factory();
	if (typeof module === "object" && module.exports) {
		module.exports = interfaceMode;
	}
	root.DeepLinkERPInterfaceMode = interfaceMode;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
	"use strict";

	const SAVE_METHOD =
		"deeplinkerp_branding.deeplinkerp_branding.interface_mode.set_user_navigation_mode";
	const VALID_MODES = new Set(["classic", "dl"]);
	const activeMenus = new WeakMap();
	const boundDocuments = new WeakSet();

	function normalizeMode(value) {
		const mode = String(value || "").trim().toLowerCase();
		return VALID_MODES.has(mode) ? mode : null;
	}

	function getModeState(boot = {}) {
		const payload = boot.deeplinkerp_interface_mode || {};
		return {
			companyDefault: normalizeMode(payload.company_default) || "dl",
			userOverride: normalizeMode(payload.user_override),
			effectiveMode: normalizeMode(payload.effective_mode) || "dl",
			canManageCompanyDefault: Boolean(payload.can_manage_company_default),
		};
	}

	function isDLMode(boot = {}) {
		return getModeState(boot).effectiveMode === "dl";
	}

	function buildModeOptions(boot = {}, translate = (value) => value) {
		const state = getModeState(boot);
		const companyLabel =
			state.companyDefault === "classic" ? translate("Classic Mode") : translate("DL Mode");
		return [
			{
				value: "follow_company",
				label: `${translate("Follow Company Default")} (${translate("Current")}: ${companyLabel})`,
				checked: state.userOverride === null,
			},
			{
				value: "classic",
				label: translate("Classic Mode"),
				checked: state.userOverride === "classic",
			},
			{
				value: "dl",
				label: translate("DL Mode"),
				checked: state.userOverride === "dl",
			},
		];
	}

	async function saveNavigationMode({ frappe, mode, reload }) {
		const result = await frappe.xcall(SAVE_METHOD, { mode });
		const reloadPage =
			reload || (() => globalThis.location && globalThis.location.reload());
		reloadPage();
		return result;
	}

	function classNames(element) {
		return String(element.className || "").split(/\s+/).filter(Boolean);
	}

	function addClass(element, name) {
		const names = new Set(classNames(element));
		names.add(name);
		element.className = Array.from(names).join(" ");
	}

	function findDirectChild(container, className) {
		return Array.from(container.children || []).find((child) =>
			classNames(child).includes(className)
		);
	}

	function setModeButtonsDisabled(menu, disabled) {
		Array.from(menu.children || []).forEach((item) => {
			if (item.getAttribute("role") === "menuitemradio") item.disabled = disabled;
		});
	}

	function showSaveError(frappe, error, translate) {
		if (typeof frappe.msgprint === "function") {
			frappe.msgprint({
				title: translate("Unable to Save"),
				message: error?.message || translate("Unable to save interface mode."),
				indicator: "red",
			});
		}
	}

	function closeMenu(controller) {
		controller.menu.hidden = true;
		controller.userButton.setAttribute("aria-expanded", "false");
	}

	function bindDocumentDismissal(document) {
		if (boundDocuments.has(document)) return;
		boundDocuments.add(document);
		document.addEventListener("click", (event) => {
			const active = activeMenus.get(document);
			if (!active) return;
			if (!active.menu.contains(event.target) && !active.userButton.contains(event.target)) {
				closeMenu(active);
			}
		});
		document.addEventListener("keydown", (event) => {
			if (event.key !== "Escape") return;
			const active = activeMenus.get(document);
			if (!active) return;
			closeMenu(active);
		});
	}

	function ensureUserMenu({
		document,
		frappe,
		translate = (value) => value,
		reload,
	} = {}) {
		const userButton = document?.querySelector?.(".sidebar-user-button");
		const container = userButton?.parentElement;
		if (!userButton || !container) return null;

		const existing = findDirectChild(container, "dlp-interface-mode-menu");
		if (existing?.__dlpController) return existing.__dlpController;

		userButton.removeAttribute("onclick");
		addClass(container, "dlp-interface-mode-menu-host");

		const menu = document.createElement("div");
		menu.className = "dlp-interface-mode-menu";
		menu.setAttribute("role", "menu");
		menu.setAttribute("aria-label", translate("Interface Mode"));
		menu.hidden = true;

		buildModeOptions(frappe.boot, translate).forEach((option) => {
			const item = document.createElement("button");
			item.type = "button";
			item.className = "dlp-interface-mode-menu__item";
			item.dataset.mode = option.value;
			item.setAttribute("role", "menuitemradio");
			item.setAttribute("aria-checked", String(option.checked));
			item.textContent = option.label;
			item.addEventListener("click", async (event) => {
				event.preventDefault();
				event.stopPropagation();
				setModeButtonsDisabled(menu, true);
				try {
					await saveNavigationMode({ frappe, mode: option.value, reload });
				} catch (error) {
					setModeButtonsDisabled(menu, false);
					showSaveError(frappe, error, translate);
				}
			});
			menu.appendChild(item);
		});

		const profile = document.createElement("button");
		profile.type = "button";
		profile.className = "dlp-interface-mode-menu__item dlp-interface-mode-menu__profile";
		profile.dataset.action = "profile";
		profile.setAttribute("role", "menuitem");
		profile.textContent = translate("Profile");
		profile.addEventListener("click", (event) => {
			event.preventDefault();
			closeMenu({ menu, userButton });
			frappe.ui.toolbar.route_to_user();
		});
		menu.appendChild(profile);
		container.appendChild(menu);

		const controller = { menu, userButton };
		menu.__dlpController = controller;
		userButton.dataset.dlpModeMenuBound = "true";
		userButton.setAttribute("aria-haspopup", "menu");
		userButton.setAttribute("aria-expanded", "false");
		userButton.addEventListener("click", (event) => {
			event.preventDefault();
			event.stopPropagation();
			menu.hidden = !menu.hidden;
			userButton.setAttribute("aria-expanded", String(!menu.hidden));
			if (!menu.hidden) activeMenus.set(document, controller);
		});
		bindDocumentDismissal(document);
		return controller;
	}

	return Object.freeze({
		SAVE_METHOD,
		buildModeOptions,
		ensureUserMenu,
		getModeState,
		isDLMode,
		normalizeMode,
		saveNavigationMode,
	});
});
