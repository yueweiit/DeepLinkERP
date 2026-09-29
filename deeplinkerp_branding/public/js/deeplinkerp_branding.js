(function () {
	const ERPNextBrandName = "ERPNext";
	const DeeplinkERPBrandName = "Deeplinkerp";
	const ERPNextSettingsName = "ERPNext Settings";
	const DeeplinkERPSettingsName = "Deeplinkerp Settings";
	const ProductAppNames = new Set(["ai_assistant", "mes_integration"]);
	const ProductSidebarTitles = new Set(["AI Assistant", "Mes Integration", "MES Integration", "MES Integration Log"]);
	const ProductSidebarSubtitles = new Set(["AI Assistant", "Mes Integration", "MES Integration", "MES Integration Log"]);
	const FrappeFrameworkName = "Frappe Framework";
	const DLPFrameworkName = "DLP Framework";
	const translate = (text) => (typeof window.__ === "function" ? window.__(text) : text);
	const getBrandName = () => translate(DeeplinkERPBrandName);
	const getSettingsName = () => translate(DeeplinkERPSettingsName);
	const getFrameworkName = () => translate(DLPFrameworkName);
	const FaviconURL = "/assets/deeplinkerp_branding/logo/tab_logo.svg?v=0.0.6";
	const BrandLogoURL = "/assets/deeplinkerp_branding/logo/deeplinkerp_logo_radius.png?v=0.0.6";
	const isNarrowNavigationViewport = () =>
		typeof window.matchMedia === "function"
			? window.matchMedia("(max-width: 767.98px)").matches
			: window.innerWidth < 768;
	let eventsBound = false;

	function setFavicon() {
		document
			.querySelectorAll("link[rel~='icon'], link[rel='shortcut icon'], link[rel='apple-touch-icon']")
			.forEach((link) => link.remove());

		const favicon = document.createElement("link");
		favicon.rel = "icon";
		favicon.type = "image/svg+xml";
		favicon.href = FaviconURL;
		document.head.appendChild(favicon);

		const shortcut = document.createElement("link");
		shortcut.rel = "shortcut icon";
		shortcut.type = "image/svg+xml";
		shortcut.href = FaviconURL;
		document.head.appendChild(shortcut);
	}

	function replaceERPNextAppTitle() {
		if (!window.frappe?.boot) return;

		(frappe.boot.app_data || []).forEach((app) => {
			const brandName = getBrandName();
			const frameworkName = getFrameworkName();
			if (app.app_name === "erpnext" || app.app_title === ERPNextBrandName || app.app_title === DeeplinkERPBrandName) {
				if (app.app_title !== brandName) app.app_title = brandName;
			}
			if (app.app_name === "frappe" || app.app_title === FrappeFrameworkName || app.app_title === DLPFrameworkName) {
				if (app.app_title !== frameworkName) app.app_title = frameworkName;
			}
			if (ProductAppNames.has(app.app_name)) {
				if (app.app_title !== brandName) app.app_title = brandName;
			}
		});

		const brandName = getBrandName();
		const frameworkName = getFrameworkName();
		if (frappe.current_app?.app_name === "erpnext") {
			if (frappe.current_app.app_title !== brandName) frappe.current_app.app_title = brandName;
		}
		if (frappe.current_app?.app_name === "frappe") {
			if (frappe.current_app.app_title !== frameworkName) frappe.current_app.app_title = frameworkName;
		}
		if (ProductAppNames.has(frappe.current_app?.app_name)) {
			if (frappe.current_app.app_title !== brandName) frappe.current_app.app_title = brandName;
		}
	}

	function replaceBootLabels() {
		if (!window.frappe?.boot) return;

		const settingsSidebar = frappe.boot.workspace_sidebar_item?.["erpnext settings"];
		const settingsName = getSettingsName();
		if (settingsSidebar) {
			if (settingsSidebar.label !== settingsName) settingsSidebar.label = settingsName;
			if (settingsSidebar.title !== settingsName) settingsSidebar.title = settingsName;
		}

		Object.entries(frappe.boot.workspace_sidebar_item || {}).forEach(([key, sidebar]) => {
			if (ProductSidebarTitles.has(sidebar.label) || ProductSidebarTitles.has(sidebar.module) || ProductSidebarTitles.has(key)) {
				sidebar.app = sidebar.app || (sidebar.label === "AI Assistant" ? "ai_assistant" : "mes_integration");
			}
		});

		frappe.boot.module_app = frappe.boot.module_app || {};
		Object.assign(frappe.boot.module_app, {
			"ai assistant": "ai_assistant",
			ai_assistant: "ai_assistant",
			"mes integration": "mes_integration",
			mes_integration: "mes_integration",
			"mes integration log": "mes_integration",
			mes_integration_log: "mes_integration",
		});

		(frappe.boot.workspaces?.pages || []).forEach((workspace) => {
			if (
				workspace.name === ERPNextSettingsName ||
				workspace.label === ERPNextSettingsName ||
				workspace.title === ERPNextSettingsName
			) {
				if (workspace.label !== settingsName) workspace.label = settingsName;
				if (workspace.title !== settingsName) workspace.title = settingsName;
			}
		});
	}

	function addReplacement(replacements, source, target) {
		if (source && target && source !== target) {
			replacements[source] = target;
		}
	}

	function replaceTextContent(selector, replacements) {
		document.querySelectorAll(selector).forEach((element) => {
			const text = element.textContent.trim();
			if (replacements[text] && replacements[text] !== text) {
				element.textContent = replacements[text];
			}
		});
	}

	function replaceDisplayAttributes(replacements) {
		const attributes = ["title", "data-original-title", "aria-label", "alt"];
		document.querySelectorAll("[title], [data-original-title], [aria-label], [alt]").forEach((element) => {
			attributes.forEach((attribute) => {
				const value = element.getAttribute(attribute);
				if (replacements[value] && replacements[value] !== value) {
					element.setAttribute(attribute, replacements[value]);
				}
			});
		});
	}

	function replaceVisibleBranding() {
		const replacements = {};
		const brandName = getBrandName();
		const settingsName = getSettingsName();
		const frameworkName = getFrameworkName();
		addReplacement(replacements, ERPNextBrandName, brandName);
		addReplacement(replacements, DeeplinkERPBrandName, brandName);
		addReplacement(replacements, ERPNextSettingsName, settingsName);
		addReplacement(replacements, DeeplinkERPSettingsName, settingsName);
		addReplacement(replacements, FrappeFrameworkName, frameworkName);
		addReplacement(replacements, DLPFrameworkName, frameworkName);

		if (window.frappe?.app?.sidebar?.header_subtitle === FrappeFrameworkName || window.frappe?.app?.sidebar?.header_subtitle === DLPFrameworkName) {
			if (frappe.app.sidebar.header_subtitle !== frameworkName) frappe.app.sidebar.header_subtitle = frameworkName;
		}
		if (ProductSidebarSubtitles.has(window.frappe?.app?.sidebar?.header_subtitle)) {
			if (frappe.app.sidebar.header_subtitle !== brandName) frappe.app.sidebar.header_subtitle = brandName;
		}

		document.querySelectorAll(".title-container").forEach((container) => {
			const title = container.querySelector(".header-title")?.textContent.trim();
			const subtitle = container.querySelector(".header-subtitle");
			if (subtitle && ProductSidebarTitles.has(title) && subtitle.textContent.trim() !== brandName) {
				subtitle.textContent = brandName;
			}
		});

		document.querySelectorAll(".header-subtitle").forEach((subtitle) => {
			const text = subtitle.textContent.trim();
			if ((text === ERPNextBrandName || ProductSidebarSubtitles.has(text)) && text !== brandName) {
				subtitle.textContent = brandName;
			}
			if ((text === FrappeFrameworkName || text === DLPFrameworkName) && text !== frameworkName) {
				subtitle.textContent = frameworkName;
			}
		});

		replaceTextContent(
			[
				".sidebar-item-label",
				".sidebar-item-title",
				".icon-title",
				".menu-item-title",
				".workspace-title",
				".title-text",
				".ellipsis",
				".awesomplete [role='option']",
			].join(", "),
			replacements
		);

		replaceDisplayAttributes(replacements);
	}

	function applyBranding() {
		try {
			setFavicon();
			replaceERPNextAppTitle();
			replaceBootLabels();
			replaceVisibleBranding();
		} catch (error) {
			console.warn("Deeplinkerp branding failed to apply", error);
		}
	}

	function patchSidebarSubtitle() {
		if (
			!window.frappe?.ui?.Sidebar ||
			frappe.ui.Sidebar.prototype.__deeplinkerpPatched ||
			typeof frappe.ui.Sidebar.prototype.choose_app_name !== "function"
		) {
			return;
		}

		const originalChooseAppName = frappe.ui.Sidebar.prototype.choose_app_name;
		frappe.ui.Sidebar.prototype.choose_app_name = function (...args) {
			const result = originalChooseAppName.apply(this, args);
			if (this.header_subtitle === FrappeFrameworkName || this.header_subtitle === DLPFrameworkName) {
				this.header_subtitle = getFrameworkName();
			}
			if (
				ProductSidebarTitles.has(this.sidebar_title) ||
				ProductSidebarTitles.has(this.workspace_title) ||
				ProductSidebarSubtitles.has(this.header_subtitle) ||
				ProductAppNames.has(frappe.current_app?.app_name)
			) {
				this.header_subtitle = getBrandName();
			}
			return result;
		};
		frappe.ui.Sidebar.prototype.__deeplinkerpPatched = true;
	}

	function getDesktopIcons() {
		const authorizedIcons = frappe.boot.desktop_icons || [];
		let runtimeLayout = frappe.desktop_icons || authorizedIcons;
		if (frappe.pages?.desktop?.desktop_page?.edit_mode && Array.isArray(frappe.new_desktop_icons)) {
			runtimeLayout = frappe.new_desktop_icons;
		}
		return DeepLinkERPNavigation.projectAuthorizedDesktopIcons(authorizedIcons, runtimeLayout);
	}

	function getIconsWithRoutes() {
		return getDesktopIcons().map((icon) => ({
			...icon,
			navigation_route:
				typeof frappe.utils?.get_route_for_icon === "function"
					? frappe.utils.get_route_for_icon(icon)
					: icon.link || icon.url || "",
		}));
	}

	function makeLineIcon(name, size = "sm") {
		if (typeof frappe.utils?.icon !== "function") return "";
		return frappe.utils.icon(name, size, "", "", "dlp-mes-navigation__line-icon", true);
	}

	function ensureBrandHeader(sidebar) {
		const nativeHeader = sidebar.querySelector(".sidebar-header");
		const fallbackHeader = sidebar.querySelector(".dlp-mes-navigation__brand-fallback");
		if (!nativeHeader) {
			if (fallbackHeader) return;
			const fallback = document.createElement("a");
			fallback.className = "dlp-mes-navigation__brand-fallback";
			fallback.href = "/desk";
			fallback.setAttribute("aria-label", "DeepLinkERP Desktop");
			DeepLinkERPNavigation.bindNativeSidebarClose(fallback, {
				isNarrowViewport: isNarrowNavigationViewport,
				closeSidebar: () => frappe.app.sidebar.close(),
				preserveDesktopExpansion: () =>
					DeepLinkERPNavigation.rememberDesktopSidebarExpansion(
						sidebar.querySelector(".dlp-mes-navigation"),
						sidebar.closest(".body-sidebar-container")
					),
			});

			const image = document.createElement("img");
			image.src = BrandLogoURL;
			image.alt = "";
			fallback.appendChild(image);

			const label = document.createElement("span");
			label.textContent = "DeepLinkERP";
			fallback.appendChild(label);
			sidebar.prepend(fallback);
			return;
		}

		fallbackHeader?.remove();
		nativeHeader.classList.add("dlp-mes-navigation__brand");
		nativeHeader.setAttribute("aria-label", "DeepLinkERP menu");
		const title = nativeHeader.querySelector(".header-title");
		if (title) title.textContent = "DeepLinkERP";
		const subtitle = nativeHeader.querySelector(".header-subtitle");
		if (subtitle) subtitle.textContent = "";
		const logo = nativeHeader.querySelector(".header-logo");
		if (logo && logo.dataset.dlpBrandLogo !== BrandLogoURL) {
			logo.replaceChildren();
			const image = document.createElement("img");
			image.src = BrandLogoURL;
			image.alt = "";
			logo.appendChild(image);
			logo.dataset.dlpBrandLogo = BrandLogoURL;
		}
	}

	function makeNavigationRow(item, isOpen = item.isOpen) {
		const hasChildren = item.children.length > 0 || item.hasNativeChildren;
		const route = item.navigation_route || item.route || item.link || item.url;
		const row = document.createElement(route ? "a" : "button");
		row.className = "dlp-mes-navigation__row";
		if (route) {
			row.href = route;
		} else {
			row.type = "button";
		}
		if (hasChildren) row.setAttribute("aria-expanded", String(isOpen));
		if (item.isSelfActive) row.setAttribute("aria-current", "page");

		const icon = document.createElement("span");
		icon.className = "dlp-mes-navigation__icon";
		icon.innerHTML = makeLineIcon(DeepLinkERPNavigation.getNavigationIcon(item.label));
		row.appendChild(icon);

		const label = document.createElement("span");
		label.className = "dlp-mes-navigation__label";
		label.textContent = translate(item.label);
		row.appendChild(label);

		if (hasChildren) {
			const chevron = document.createElement("span");
			chevron.className = "dlp-mes-navigation__chevron";
			chevron.innerHTML = makeLineIcon(isOpen ? "chevron-down" : "chevron-right");
			row.appendChild(chevron);
		}
		return row;
	}

	function renderNavigationItem(item, nativeItems, nativeHostKey, userCollapsedKeys, depth = 0) {
		const group = document.createElement("div");
		group.className = "dlp-mes-navigation__group";
		group.dataset.navigationKey = item.key;
		group.style.setProperty("--dlp-navigation-depth", depth);
		const isOpen = DeepLinkERPNavigation.applyUserCollapsedState(
			group,
			item,
			userCollapsedKeys
		);
		if (isOpen) group.classList.add("dlp-mes-navigation__group--open");
		if (item.isSelfActive) group.classList.add("dlp-mes-navigation__group--self-active");

		const row = makeNavigationRow(item, isOpen);
		group.appendChild(row);
		const needsBranch = item.children.length > 0 || item.key === nativeHostKey;
		const route = item.navigation_route || item.route || item.link || item.url || "";
		const interactionOptions = {
			route,
			isNarrowViewport: isNarrowNavigationViewport,
			closeSidebar: () => frappe.app.sidebar.close(),
			preserveDesktopExpansion: () =>
				DeepLinkERPNavigation.rememberDesktopSidebarExpansion(
					row.closest(".dlp-mes-navigation"),
					row.closest(".body-sidebar-container")
				),
		};
		if (!needsBranch) {
			DeepLinkERPNavigation.bindNavigationRowInteractions(row, interactionOptions);
			return group;
		}

		const branch = document.createElement("div");
		branch.className = "dlp-mes-navigation__children";
		branch.hidden = !isOpen;
		item.children.forEach((child) => {
			branch.appendChild(
				renderNavigationItem(
					child,
					nativeItems,
					nativeHostKey,
					userCollapsedKeys,
					depth + 1
				)
			);
		});
		if (item.key === nativeHostKey) {
			branch.appendChild(nativeItems);
		}
		group.appendChild(branch);

		DeepLinkERPNavigation.bindNavigationRowInteractions(row, {
			...interactionOptions,
			group,
			branch,
			itemIsOpen: item.isOpen,
			updateChevron: (open) => {
				const chevron = row.querySelector(".dlp-mes-navigation__chevron");
				if (chevron) chevron.innerHTML = makeLineIcon(open ? "chevron-down" : "chevron-right");
			},
		});
		return group;
	}

	function updateNativeLeafAccessibility(nativeItems) {
		nativeItems.querySelectorAll(".item-anchor").forEach((anchor) => {
			anchor.removeAttribute("aria-current");
			if (anchor.closest(".standard-sidebar-item")?.classList.contains("active-sidebar")) {
				anchor.setAttribute("aria-current", "page");
			}
		});
	}

	function renderPersistentNavigation() {
		if (!window.frappe?.boot || !window.DeepLinkERPNavigation || !frappe.app?.sidebar) return;
		const sidebarContainer = frappe.app.sidebar.wrapper?.[0] || document.querySelector(".body-sidebar-container");
		const sidebar = sidebarContainer?.querySelector(".body-sidebar");
		const top = sidebar?.querySelector(".body-sidebar-top");
		const nativeItems = sidebar?.querySelector(".sidebar-items");
		if (!sidebarContainer || !sidebar || !top || !nativeItems) return;

		document.body.classList.add("dlp-mes-navigation-enabled");
		sidebar.classList.add("dlp-mes-navigation-sidebar");
		sidebarContainer.style.removeProperty("display");
		ensureBrandHeader(sidebar);
		const previousNavigation = top.querySelector(":scope > .dlp-mes-navigation");
		DeepLinkERPNavigation.restoreDesktopSidebarExpansion(
			previousNavigation,
			sidebarContainer,
			isNarrowNavigationViewport()
		);
		const userCollapsedKeys = DeepLinkERPNavigation.collectUserCollapsedKeys(
			previousNavigation
		);

		const model = DeepLinkERPNavigation.buildNavigationModel({
			desktopIcons: getIconsWithRoutes(),
			workspaceSidebars: frappe.boot.workspace_sidebar_item || {},
			route: window.location.href,
			currentSidebar: frappe.app.sidebar.sidebar_title || "",
			nativeLeafSelected: Boolean(nativeItems.querySelector(".active-sidebar")),
		});

		// Keep Frappe's live node and its handlers while replacing only our shell.
		DeepLinkERPNavigation.replaceNavigationRoot(top, nativeItems, () => {
			const navigation = document.createElement("nav");
			navigation.className = "dlp-mes-navigation";
			navigation.setAttribute("aria-label", translate("Modules"));
			model.items.forEach((item) => {
				navigation.appendChild(
					renderNavigationItem(
						item,
						nativeItems,
						model.nativeHostKey,
						userCollapsedKeys
					)
				);
			});
			if (!model.nativeHostKey) {
				const nativeParking = document.createElement("div");
				nativeParking.className = "dlp-mes-navigation__native-parking";
				nativeParking.hidden = true;
				nativeParking.appendChild(nativeItems);
				navigation.appendChild(nativeParking);
			}
			return navigation;
		});
		updateNativeLeafAccessibility(nativeItems);
	}

	function enhanceDesktopIcons() {
		if (!window.DeepLinkERPNavigation || !window.frappe?.utils?.icon) return;
		document.querySelectorAll(".desktop-container .desktop-icon:not(.add-new-icon)").forEach((entry) => {
			const label = entry.dataset.id || entry.querySelector(".icon-title")?.textContent.trim();
			if (!label) return;
			const iconName = DeepLinkERPNavigation.getNavigationIcon(label);
			entry.classList.add("dlp-desktop-icon-enhanced");
			let visual = entry.querySelector(":scope > .dlp-desktop-line-icon");
			if (!visual) {
				visual = document.createElement("div");
				visual.className = "icon-container dlp-desktop-line-icon";
				entry.prepend(visual);
			}
			if (visual.dataset.dlpIcon !== iconName) {
				visual.innerHTML = makeLineIcon(iconName, "md");
				visual.dataset.dlpIcon = iconName;
			}
		});
	}

	function disableDLEnhancements() {
		const navigation = document.querySelector(".dlp-mes-navigation");
		const top = navigation?.closest(".body-sidebar-top");
		const nativeItems = navigation?.querySelector(".sidebar-items");
		if (top && nativeItems) top.prepend(nativeItems);
		navigation?.remove();
		document.body.classList.remove("dlp-mes-navigation-enabled");
		document
			.querySelector(".body-sidebar.dlp-mes-navigation-sidebar")
			?.classList.remove("dlp-mes-navigation-sidebar");
		document.querySelectorAll(".dlp-desktop-line-icon").forEach((icon) => icon.remove());
		document
			.querySelectorAll(".desktop-icon.dlp-desktop-icon-enhanced")
			.forEach((entry) => entry.classList.remove("dlp-desktop-icon-enhanced"));
	}

	function refreshDeskEnhancements() {
		patchSidebarSubtitle();
		applyBranding();
		if (window.DeepLinkERPInterfaceMode) {
			DeepLinkERPInterfaceMode.ensureUserMenu({ document, frappe, translate });
		}
		const dlModeEnabled =
			!window.DeepLinkERPInterfaceMode || DeepLinkERPInterfaceMode.isDLMode(frappe.boot);
		if (dlModeEnabled) {
			renderPersistentNavigation();
			enhanceDesktopIcons();
		} else {
			disableDLEnhancements();
		}
	}

	function bindDeskEvents() {
		if (eventsBound) return;
		eventsBound = true;

		if (window.frappe?.router?.on) {
			frappe.router.on("change", refreshDeskEnhancements);
		}

		if (window.frappe?.after_ajax) {
			frappe.after_ajax(refreshDeskEnhancements);
		}

		if (window.jQuery) {
			jQuery(document).on("page-change form-refresh desktop_screen", refreshDeskEnhancements);
		}
	}

	function initialize() {
		refreshDeskEnhancements();
		bindDeskEvents();
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", initialize);
	} else {
		initialize();
	}

	[100, 500, 1000, 2000].forEach((delay) => setTimeout(refreshDeskEnhancements, delay));
})();
