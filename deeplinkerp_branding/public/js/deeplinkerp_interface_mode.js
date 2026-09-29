(function (root, factory) {
	const interfaceMode = factory();
	if (typeof module === "object" && module.exports) {
		module.exports = interfaceMode;
	}
	root.DeepLinkERPInterfaceMode = interfaceMode;
	interfaceMode.startDLPreparation({
		document: root.document,
		boot: root.frappe?.boot,
		schedule: root.setTimeout?.bind(root),
		cancel: root.clearTimeout?.bind(root),
		warn: root.console?.warn?.bind(root.console),
	});
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
	"use strict";

	const SAVE_METHOD =
		"deeplinkerp_branding.deeplinkerp_branding.interface_mode.set_user_navigation_mode";
	const VALID_MODES = new Set(["classic", "dl"]);
	const DL_PREPARING_CLASS = "dlp-interface-mode-dl-pending";
	const DL_PREPARATION_TIMEOUT_MS = 2000;
	const activeMenus = new WeakMap();
	const activePreparations = new WeakMap();
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

	function explicitEffectiveMode(boot = {}) {
		return normalizeMode(boot?.deeplinkerp_interface_mode?.effective_mode);
	}

	function startDLPreparation({
		document,
		boot,
		schedule = globalThis.setTimeout?.bind(globalThis),
		cancel = globalThis.clearTimeout?.bind(globalThis),
		warn = globalThis.console?.warn?.bind(globalThis.console),
		timeoutMs = DL_PREPARATION_TIMEOUT_MS,
	} = {}) {
		const rootElement = document?.documentElement;
		if (!rootElement || explicitEffectiveMode(boot) !== "dl") return null;
		const existing = activePreparations.get(document);
		if (existing) return existing;

		rootElement.classList.add(DL_PREPARING_CLASS);
		rootElement.setAttribute("aria-busy", "true");
		let finished = false;
		let timerId;
		const controller = {
			finish({ timedOut = false } = {}) {
				if (finished) return false;
				finished = true;
				if (!timedOut && timerId !== undefined && cancel) cancel(timerId);
				rootElement.classList.remove(DL_PREPARING_CLASS);
				rootElement.removeAttribute("aria-busy");
				activePreparations.delete(document);
				if (timedOut && warn) {
					warn("DL navigation preparation timed out; showing the native Desk UI.");
				}
				return true;
			},
		};
		activePreparations.set(document, controller);
		if (schedule) timerId = schedule(() => controller.finish({ timedOut: true }), timeoutMs);
		return controller;
	}

	function finishDLPreparation(document) {
		const controller = document ? activePreparations.get(document) : null;
		if (controller) return controller.finish();
		document?.documentElement?.classList.remove(DL_PREPARING_CLASS);
		document?.documentElement?.removeAttribute("aria-busy");
		return false;
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

	function bindUserButton(controller, userButton, document) {
		userButton.removeAttribute("onclick");
		userButton.dataset.dlpModeMenuBound = "true";
		userButton.setAttribute("aria-haspopup", "menu");
		userButton.setAttribute("aria-expanded", "false");
		controller.userButton = userButton;
		userButton.addEventListener("click", (event) => {
			event.preventDefault();
			event.stopPropagation();
			controller.menu.hidden = !controller.menu.hidden;
			userButton.setAttribute("aria-expanded", String(!controller.menu.hidden));
			if (!controller.menu.hidden) activeMenus.set(document, controller);
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
		if (existing?.__dlpController) {
			const controller = existing.__dlpController;
			if (controller.userButton !== userButton) {
				closeMenu(controller);
				bindUserButton(controller, userButton, document);
			}
			return controller;
		}

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

		const controller = { menu, userButton: null };
		menu.__dlpController = controller;
		bindUserButton(controller, userButton, document);
		bindDocumentDismissal(document);
		return controller;
	}

	return Object.freeze({
		SAVE_METHOD,
		buildModeOptions,
		ensureUserMenu,
		finishDLPreparation,
		getModeState,
		isDLMode,
		normalizeMode,
		saveNavigationMode,
		startDLPreparation,
	});
});
