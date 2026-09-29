(function (root, factory) {
	const navigation = factory();
	if (typeof module === "object" && module.exports) {
		module.exports = navigation;
	}
	root.DeepLinkERPNavigation = navigation;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
	"use strict";

	const ICONS = Object.freeze({
		"dlp framework": "blocks",
		framework: "blocks",
		"ai assistant": "bot",
		"china finance": "file-text",
		organization: "network",
		accounting: "landmark",
		assets: "warehouse",
		buying: "tag",
		manufacturing: "factory",
		projects: "presentation",
		quality: "shield-check",
		selling: "briefcase",
		stock: "boxes",
		subcontracting: "repeat-2",
	});

	function normalizeIdentity(value) {
		return String(value || "")
			.trim()
			.toLowerCase()
			.replace(/[_-]+/g, " ")
			.replace(/\s+/g, " ");
	}

	function getNavigationIcon(label) {
		const normalized = normalizeIdentity(label);
		if (normalized.includes("setting")) return "settings";
		if (
			normalized.includes("overseas cost") ||
			normalized.includes("overseas costing") ||
			normalized.includes("海外成本") ||
			normalized.includes("综合成本")
		) {
			return "calculator";
		}
		return ICONS[normalized] || "layout-grid";
	}

	function desktopIconKey(icon) {
		return normalizeIdentity(icon && (icon.name || icon.label));
	}

	function projectAuthorizedDesktopIcons(authorizedIcons, runtimeLayout) {
		const authorized = new Map();
		(authorizedIcons || []).forEach((icon) => {
			const key = desktopIconKey(icon);
			if (key && !authorized.has(key)) authorized.set(key, icon);
		});

		const projected = [];
		const included = new Set();
		(runtimeLayout || []).forEach((layoutIcon) => {
			const key = desktopIconKey(layoutIcon);
			const trustedIcon = authorized.get(key);
			if (!trustedIcon || included.has(key)) return;

			const icon = { ...trustedIcon };
			["idx", "hidden", "parent_icon"].forEach((field) => {
				if (Object.prototype.hasOwnProperty.call(layoutIcon, field)) {
					icon[field] = layoutIcon[field];
				}
			});
			projected.push(icon);
			included.add(key);
		});

		for (const [key, icon] of authorized) {
			if (!included.has(key)) projected.push({ ...icon });
		}
		return projected;
	}

	function replaceNavigationRoot(top, nativeItems, buildNavigation) {
		top.appendChild(nativeItems);
		Array.from(top.children)
			.filter((element) => element.classList.contains("dlp-mes-navigation"))
			.forEach((element) => element.remove());
		const navigation = buildNavigation(nativeItems);
		top.prepend(navigation);
		return navigation;
	}

	function bindNativeSidebarClose(
		link,
		{ isNarrowViewport, closeSidebar, preserveDesktopExpansion = () => {} }
	) {
		link.addEventListener("click", (event) => {
			if (event.defaultPrevented) return;
			if (isNarrowViewport()) closeSidebar();
			else preserveDesktopExpansion();
		});
	}

	function bindNavigationRowInteractions(
		row,
		{
			group,
			branch,
			route = "",
			updateChevron,
			isNarrowViewport,
			closeSidebar,
			preserveDesktopExpansion,
		}
	) {
		if (branch) {
			bindNavigationBranchToggle(row, {
				group,
				branch,
				updateChevron,
			});
			return;
		}
		if (route) {
			bindNativeSidebarClose(row, {
				isNarrowViewport,
				closeSidebar,
				preserveDesktopExpansion,
			});
		}
	}

	function rememberDesktopSidebarExpansion(navigation, sidebarContainer) {
		if (!navigation || !sidebarContainer?.classList.contains("expanded")) return false;
		navigation.dataset.restoreSidebarExpanded = "true";
		return true;
	}

	function restoreDesktopSidebarExpansion(
		navigation,
		sidebarContainer,
		isNarrowViewport
	) {
		const shouldRestore = Boolean(
			navigation?.dataset.restoreSidebarExpanded === "true" &&
				sidebarContainer &&
				!isNarrowViewport
		);
		if (shouldRestore) sidebarContainer.classList.add("expanded");
		return shouldRestore;
	}

	function collectDisclosureKeys(navigation, attribute) {
		if (!navigation) return new Set();
		return new Set(
			Array.from(
				navigation.querySelectorAll(
					`.dlp-mes-navigation__group[data-${attribute}="true"]`
				)
			)
				.map((group) => group.dataset.navigationKey)
				.filter(Boolean)
		);
	}

	function collectDisclosureState(navigation) {
		return {
			expandedKeys: collectDisclosureKeys(navigation, "user-expanded"),
			collapsedKeys: collectDisclosureKeys(navigation, "user-collapsed"),
		};
	}

	function resolveItemOpen(item, disclosureState = {}) {
		if (disclosureState.collapsedKeys?.has(item.key)) return false;
		if (disclosureState.expandedKeys?.has(item.key)) return true;
		return Boolean(item.isOpen);
	}

	function bindNavigationBranchToggle(row, { group, branch, updateChevron }) {
		row.addEventListener("click", (event) => {
			event.preventDefault();
			const open = row.getAttribute("aria-expanded") !== "true";
			row.setAttribute("aria-expanded", String(open));
			branch.hidden = !open;
			group.classList.toggle("dlp-mes-navigation__group--open", open);
			if (open) {
				delete group.dataset.userCollapsed;
				group.dataset.userExpanded = "true";
			} else {
				delete group.dataset.userExpanded;
				group.dataset.userCollapsed = "true";
			}
			updateChevron(open);
		});
	}

	function normalizePath(pathname) {
		let path = pathname || "/desk";
		try {
			path = decodeURIComponent(path);
		} catch (error) {
			// Keep malformed paths usable for matching instead of breaking navigation.
		}
		path = `/${String(path).replace(/^\/+/, "")}`.replace(/\/{2,}/g, "/");
		return path.length > 1 ? path.replace(/\/+$/, "") : path;
	}

	function normalizeRoute(route) {
		if (Array.isArray(route)) {
			return {
				path: normalizePath(`/desk/${route.filter(Boolean).join("/")}`),
				sidebar: "",
			};
		}

		let parsed;
		try {
			parsed = new URL(String(route || "/desk"), "https://deeplinkerp.invalid");
		} catch (error) {
			parsed = new URL("/desk", "https://deeplinkerp.invalid");
		}
		return {
			path: normalizePath(parsed.pathname),
			sidebar: parsed.searchParams.get("sidebar") || "",
		};
	}

	function nodeAliases(node) {
		return [node.label, node.name, node.link_to]
			.map(normalizeIdentity)
			.filter(Boolean);
	}

	function buildNavigationTree(desktopIcons) {
		const visibleIcons = (desktopIcons || []).filter(
			(icon) => icon && icon.hidden !== 1 && icon.hidden !== "1"
		);
		const nodes = visibleIcons.map((icon, index) => ({
			...icon,
			key: `${normalizeIdentity(icon.name || icon.label) || "desktop-icon"}:${index}`,
			children: [],
		}));
		const parents = new Map();
		nodes.forEach((node) => {
			nodeAliases(node).forEach((alias) => {
				if (!parents.has(alias)) parents.set(alias, node);
			});
		});

		const roots = [];
		nodes.forEach((node) => {
			const parent = parents.get(normalizeIdentity(node.parent_icon));
			if (parent && parent !== node) {
				parent.children.push(node);
			} else {
				roots.push(node);
			}
		});
		return roots;
	}

	function findPath(items, predicate, ancestors) {
		for (const item of items) {
			const path = [...ancestors, item];
			if (predicate(item)) return path;
			const nested = findPath(item.children, predicate, path);
			if (nested.length) return nested;
		}
		return [];
	}

	function findBySidebar(items, sidebar) {
		const wanted = normalizeIdentity(sidebar);
		if (!wanted) return [];
		return findPath(items, (item) => nodeAliases(item).includes(wanted), []);
	}

	function nodeRoute(node) {
		return node.navigation_route || node.route || node.link || node.url || "";
	}

	function findByExactRoute(items, route) {
		return findPath(items, (item) => {
			const candidate = nodeRoute(item);
			return candidate && normalizeRoute(candidate).path === route.path;
		}, []);
	}

	function getWorkspaceSidebar(node, workspaceSidebars) {
		const entries = Object.entries(workspaceSidebars || {});
		const aliases = nodeAliases(node);
		for (const [key, sidebar] of entries) {
			if (
				aliases.includes(normalizeIdentity(key)) ||
				aliases.includes(normalizeIdentity(sidebar && (sidebar.label || sidebar.title)))
			) {
				return sidebar;
			}
		}
		return null;
	}

	function buildNavigationModel({
		desktopIcons = [],
		workspaceSidebars = {},
		route = "/desk",
		currentSidebar = "",
		nativeLeafSelected = false,
	} = {}) {
		const items = buildNavigationTree(desktopIcons);
		const normalizedRoute = normalizeRoute(route);
		let activePath = findBySidebar(items, normalizedRoute.sidebar);
		if (!activePath.length) activePath = findByExactRoute(items, normalizedRoute);
		if (!activePath.length) activePath = findBySidebar(items, currentSidebar);

		const activeKeys = new Set(activePath.map((item) => item.key));
		const activeLeaf = activePath.at(-1) || null;
		const exactRoute = Boolean(
			activeLeaf &&
			nodeRoute(activeLeaf) &&
			normalizeRoute(nodeRoute(activeLeaf)).path === normalizedRoute.path
		);
		let activeItem = null;
		let nativeHostKey = "";

		function decorate(nodes) {
			nodes.forEach((node) => {
				decorate(node.children);
				const nativeSidebar = getWorkspaceSidebar(node, workspaceSidebars);
				const hasNativeChildren = Boolean(nativeSidebar && nativeSidebar.items?.length);
				node.workspaceSidebar = nativeSidebar;
				const isActive = Boolean(activeLeaf && node.key === activeLeaf.key);
				node.hasNativeChildren = hasNativeChildren;
				node.isOpen = activeKeys.has(node.key) && (node.children.length > 0 || hasNativeChildren);
				const hasSelectedNativeLeaf = Boolean(
					hasNativeChildren && (normalizedRoute.sidebar || nativeLeafSelected)
				);
				node.isSelfActive =
					isActive &&
					!hasSelectedNativeLeaf &&
					(exactRoute || (!node.children.length && !hasNativeChildren));
				if (isActive) {
					activeItem = node;
					if (hasNativeChildren) nativeHostKey = node.key;
				}
			});
		}
		decorate(items);

		return {
			items,
			normalizedRoute,
			activePathLabels: activePath.map((item) => item.label),
			activeItem,
			nativeHostKey,
			exactRoute,
		};
	}

	return Object.freeze({
		bindNavigationBranchToggle,
		bindNavigationRowInteractions,
		bindNativeSidebarClose,
		buildNavigationModel,
		buildNavigationTree,
		collectDisclosureState,
		getNavigationIcon,
		normalizeRoute,
		projectAuthorizedDesktopIcons,
		rememberDesktopSidebarExpansion,
		replaceNavigationRoot,
		resolveItemOpen,
		restoreDesktopSidebarExpansion,
	});
});
