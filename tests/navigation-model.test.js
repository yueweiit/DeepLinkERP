const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const modulePath = path.join(
	__dirname,
	"..",
	"deeplinkerp_branding",
	"public",
	"js",
	"deeplinkerp_navigation.js"
);
const navigation = fs.existsSync(modulePath) ? require(modulePath) : {};

function productionFunction(name) {
	assert.equal(typeof navigation[name], "function", `${name} must be exported by the navigation model`);
	return navigation[name];
}

class FakeClassList {
	constructor(names = []) {
		this.names = new Set(names);
	}

	contains(name) {
		return this.names.has(name);
	}
}

class FakeElement {
	constructor(classes = []) {
		this.children = [];
		this.classList = new FakeClassList(classes);
		this.parentElement = null;
		this.listeners = {};
	}

	appendChild(child) {
		child.remove();
		this.children.push(child);
		child.parentElement = this;
		return child;
	}

	prepend(child) {
		child.remove();
		this.children.unshift(child);
		child.parentElement = this;
		return child;
	}

	remove() {
		if (!this.parentElement) return;
		this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
		this.parentElement = null;
	}

	addEventListener(type, listener) {
		this.listeners[type] = listener;
	}

	dispatch(type) {
		this.listeners[type]?.({ currentTarget: this });
	}
}

test("maps the approved MES line icons and keeps a deterministic fallback", () => {
	const getNavigationIcon = productionFunction("getNavigationIcon");
	const labels = [
		"DLP Framework",
		"AI Assistant",
		"China Finance",
		"Organization",
		"Accounting",
		"Assets",
		"Buying",
		"Manufacturing",
		"Projects",
		"Quality",
		"Selling",
		"Stock",
		"Subcontracting",
		"Deeplinkerp Settings",
		"Overseas Cost",
		"Unknown Module",
	];

	assert.deepEqual(
		labels.map((label) => getNavigationIcon(label)),
		[
			"blocks",
			"bot",
			"file-text",
			"network",
			"landmark",
			"warehouse",
			"tag",
			"factory",
			"presentation",
			"shield-check",
			"briefcase",
			"boxes",
			"repeat-2",
			"settings",
			"calculator",
			"layout-grid",
		]
	);
});

test("builds the visible desktop tree in source order without mutating boot data", () => {
	const buildNavigationTree = productionFunction("buildNavigationTree");
	const icons = [
		{ name: "Operations", label: "Operations", icon_type: "Folder" },
		{ name: "Stock", label: "Stock", parent_icon: "Operations" },
		{ name: "Hidden", label: "Hidden", hidden: 1 },
		{ name: "Selling", label: "Selling" },
		{ name: "Orphan", label: "Orphan", parent_icon: "Hidden" },
	];
	const snapshot = structuredClone(icons);

	const first = buildNavigationTree(icons);
	const second = buildNavigationTree(icons);

	assert.deepEqual(
		first.map((item) => [item.label, item.children.map((child) => child.label)]),
		[
			["Operations", ["Stock"]],
			["Selling", []],
			["Orphan", []],
		]
	);
	assert.deepEqual(second, first, "the model must be idempotent");
	assert.deepEqual(icons, snapshot, "boot data must remain authoritative and unmodified");
});

test("projects stale runtime layout onto the boot authorization whitelist", () => {
	const projectAuthorizedDesktopIcons = productionFunction("projectAuthorizedDesktopIcons");
	const authorized = [
		{ name: "Stock", label: "Stock", link: "/desk/stock", idx: 1, hidden: 0 },
		{ name: "Operations", label: "Operations", icon_type: "Folder", idx: 2, hidden: 0 },
		{ name: "Selling", label: "Selling", link: "/desk/selling", idx: 3, hidden: 0 },
	];
	const runtimeLayout = [
		{ name: "Unauthorized", label: "Unauthorized", link: "/desk/secret", idx: 0 },
		{
			name: "Stock",
			label: "Tampered Stock",
			link: "https://invalid.example",
			idx: 9,
			hidden: 1,
			parent_icon: "Operations",
		},
		{ name: "Operations", label: "Old Operations", idx: 1, hidden: 0 },
		{ name: "Stock", label: "Duplicate Stock", idx: 10 },
	];
	const authorizedSnapshot = structuredClone(authorized);

	const projected = projectAuthorizedDesktopIcons(authorized, runtimeLayout);

	assert.deepEqual(projected.map((icon) => icon.name), ["Stock", "Operations", "Selling"]);
	assert.equal(projected.some((icon) => icon.name === "Unauthorized"), false);
	assert.deepEqual(
		projected[0],
		{
			name: "Stock",
			label: "Stock",
			link: "/desk/stock",
			idx: 9,
			hidden: 1,
			parent_icon: "Operations",
		},
		"only layout fields may override trusted boot metadata"
	);
	assert.deepEqual(authorized, authorizedSnapshot, "the authorization whitelist must not be mutated");
});

test("projects unsaved edit-state order, visibility, and folder placement without admitting new icons", () => {
	const projectAuthorizedDesktopIcons = productionFunction("projectAuthorizedDesktopIcons");
	const authorized = [
		{ name: "Stock", label: "Stock", idx: 1, hidden: 0 },
		{ name: "Operations", label: "Operations", icon_type: "Folder", idx: 2, hidden: 0 },
		{ name: "Selling", label: "Selling", idx: 3, hidden: 0 },
	];
	const editState = [
		{ name: "Selling", label: "Selling", idx: 0, hidden: 1, parent_icon: "Operations" },
		{ name: "Draft Only", label: "Draft Only", idx: 1, hidden: 0 },
		{ name: "Operations", label: "Operations", idx: 2, hidden: 0 },
	];

	const projected = projectAuthorizedDesktopIcons(authorized, editState);

	assert.deepEqual(projected.map((icon) => icon.name), ["Selling", "Operations", "Stock"]);
	assert.deepEqual(
		projected.map(({ name, idx, hidden, parent_icon = "" }) => [name, idx, hidden, parent_icon]),
		[
			["Selling", 0, 1, "Operations"],
			["Operations", 2, 0, ""],
			["Stock", 1, 0, ""],
		]
	);
});

test("normalizes direct, refreshed, and sidebar-qualified Desk routes", () => {
	const normalizeRoute = productionFunction("normalizeRoute");

	assert.deepEqual(normalizeRoute("https://erp.test/desk/stock/?sidebar=Stock#view"), {
		path: "/desk/stock",
		sidebar: "Stock",
	});
	assert.deepEqual(normalizeRoute("/desk"), { path: "/desk", sidebar: "" });
	assert.deepEqual(normalizeRoute("/desk/item?sidebar=China%20Finance"), {
		path: "/desk/item",
		sidebar: "China Finance",
	});
});

test("resolves query, exact route, and native sidebar active states in authority order", () => {
	const buildNavigationModel = productionFunction("buildNavigationModel");
	const desktopIcons = [
		{ label: "Operations", icon_type: "Folder" },
		{ label: "Stock", parent_icon: "Operations", navigation_route: "/desk/stock" },
		{ label: "Accounting", navigation_route: "/desk/accounting" },
		{ label: "Website", navigation_route: "/desk/website" },
	];
	const workspaceSidebars = {
		stock: { label: "Stock", items: [{ type: "Link", link_to: "Item" }] },
		accounting: { label: "Accounting", items: [{ type: "Link", link_to: "Account" }] },
	};

	const selectedLeaf = buildNavigationModel({
		desktopIcons,
		workspaceSidebars,
		route: "/desk/item?sidebar=Stock",
		currentSidebar: "Accounting",
	});
	assert.deepEqual(selectedLeaf.activePathLabels, ["Operations", "Stock"]);
	assert.equal(selectedLeaf.activeItem.label, "Stock");
	assert.equal(selectedLeaf.activeItem.isOpen, true);
	assert.equal(selectedLeaf.activeItem.isSelfActive, false);
	assert.equal(selectedLeaf.nativeHostKey, selectedLeaf.activeItem.key);

	const exactModule = buildNavigationModel({
		desktopIcons,
		workspaceSidebars,
		route: "/desk/accounting/",
		currentSidebar: "Accounting",
		nativeLeafSelected: false,
	});
	assert.deepEqual(exactModule.activePathLabels, ["Accounting"]);
	assert.equal(exactModule.activeItem.isOpen, true);
	assert.equal(exactModule.activeItem.isSelfActive, true);

	const routeOnly = buildNavigationModel({
		desktopIcons,
		workspaceSidebars,
		route: "/desk/website",
		currentSidebar: "Stock",
	});
	assert.equal(routeOnly.activeItem.label, "Website");
	assert.equal(
		routeOnly.activeItem.isSelfActive,
		true,
		"an exact module route overrides stale native sidebar state and is blue"
	);
});

test("keeps an exact workspace parent open without blue when the native leaf is selected", () => {
	const buildNavigationModel = productionFunction("buildNavigationModel");
	const desktopIcons = [
		{
			label: "Organization",
			navigation_route: "/desk/company",
		},
	];
	const workspaceSidebars = {
		organization: {
			label: "Organization",
			items: [{ type: "Link", link_to: "Company" }],
		},
	};

	const model = buildNavigationModel({
		desktopIcons,
		workspaceSidebars,
		route: "/desk/company",
		currentSidebar: "Organization",
		nativeLeafSelected: true,
	});

	assert.equal(model.activeItem.label, "Organization");
	assert.equal(model.activeItem.isOpen, true);
	assert.equal(model.activeItem.isSelfActive, false);
	assert.equal(model.nativeHostKey, model.activeItem.key);
});

test("keeps a sidebar-qualified exact module route open without making its parent blue", () => {
	const buildNavigationModel = productionFunction("buildNavigationModel");
	const desktopIcons = [
		{
			label: "Stock",
			navigation_route: "/desk/item?sidebar=Stock",
		},
	];
	const workspaceSidebars = {
		stock: { label: "Stock", items: [{ type: "Link", link_to: "Item" }] },
	};

	const model = buildNavigationModel({
		desktopIcons,
		workspaceSidebars,
		route: "/desk/item?sidebar=Stock",
	});

	assert.equal(model.activeItem.label, "Stock");
	assert.equal(model.activeItem.isOpen, true);
	assert.equal(model.activeItem.isSelfActive, false);
	assert.equal(model.nativeHostKey, model.activeItem.key);
});

test("keeps the Desk assets separate from website CSS and loads the model before the lifecycle", () => {
	const hooks = fs.readFileSync(
		path.join(__dirname, "..", "deeplinkerp_branding", "hooks.py"),
		"utf8"
	);
	const modelAsset = "/assets/deeplinkerp_branding/js/deeplinkerp_navigation.js";
	const lifecycleAsset = "/assets/deeplinkerp_branding/js/deeplinkerp_branding.js";

	assert.match(
		hooks,
		/app_include_css\s*=\s*"\/assets\/deeplinkerp_branding\/css\/deeplinkerp_navigation\.css\?v=0\.0\.4"/
	);
	assert.ok(hooks.indexOf(modelAsset) < hooks.indexOf(lifecycleAsset));
	assert.match(hooks, /deeplinkerp_navigation\.js\?v=0\.0\.4/);
	assert.match(hooks, /deeplinkerp_branding\.js\?v=0\.0\.10/);
	assert.match(hooks, /web_include_css\s*=\s*"\/assets\/deeplinkerp_branding\/css\/deeplinkerp_branding\.css"/);
});

test("mounts repeated route renders with one root and the same native sidebar node", () => {
	const replaceNavigationRoot = productionFunction("replaceNavigationRoot");
	const top = new FakeElement();
	const nativeItems = new FakeElement(["sidebar-items"]);
	top.appendChild(nativeItems);

	const firstRoot = replaceNavigationRoot(top, nativeItems, () => {
		const root = new FakeElement(["dlp-mes-navigation"]);
		root.appendChild(nativeItems);
		return root;
	});
	const secondRoot = replaceNavigationRoot(top, nativeItems, () => {
		const root = new FakeElement(["dlp-mes-navigation"]);
		root.appendChild(nativeItems);
		return root;
	});

	assert.notEqual(secondRoot, firstRoot);
	assert.equal(
		top.children.filter((child) => child.classList.contains("dlp-mes-navigation")).length,
		1
	);
	assert.equal(nativeItems.parentElement, secondRoot);
	assert.equal(secondRoot.children[0], nativeItems, "the live native node identity must be preserved");
});

test("custom mobile navigation links close through the native sidebar contract", () => {
	const bindNativeSidebarClose = productionFunction("bindNativeSidebarClose");
	const link = new FakeElement();
	let closeCalls = 0;
	bindNativeSidebarClose(link, {
		isMobile: () => true,
		closeSidebar: () => {
			closeCalls += 1;
		},
	});

	link.dispatch("click");
	assert.equal(closeCalls, 1);

	const desktopLink = new FakeElement();
	bindNativeSidebarClose(desktopLink, {
		isMobile: () => false,
		closeSidebar: () => {
			closeCalls += 1;
		},
	});
	desktopLink.dispatch("click");
	assert.equal(closeCalls, 1, "desktop navigation must not collapse the sidebar");
});

test("integrates the executable lifecycle helpers through the existing single router binding", () => {
	const lifecycle = fs.readFileSync(
		path.join(
			__dirname,
			"..",
			"deeplinkerp_branding",
			"public",
			"js",
			"deeplinkerp_branding.js"
		),
		"utf8"
	);

	assert.equal((lifecycle.match(/frappe\.router\.on\("change"/g) || []).length, 1);
	assert.match(lifecycle, /function renderPersistentNavigation\(/);
	assert.match(lifecycle, /refreshDeskEnhancements[\s\S]*renderPersistentNavigation\(\)/);
	assert.match(lifecycle, /projectAuthorizedDesktopIcons\(/);
	assert.match(lifecycle, /replaceNavigationRoot\(/);
	assert.match(lifecycle, /bindNativeSidebarClose\(/);
	assert.match(
		lifecycle,
		/nativeLeafSelected:\s*Boolean\(nativeItems\.querySelector\("\.active-sidebar"\)\)/
	);
	assert.doesNotMatch(lifecycle, /cloneNode\(/);
});

test("scopes the dark shell, full-row active state, focus ring, and mobile overflow protection", () => {
	const stylesheetPath = path.join(
		__dirname,
		"..",
		"deeplinkerp_branding",
		"public",
		"css",
		"deeplinkerp_navigation.css"
	);
	assert.equal(fs.existsSync(stylesheetPath), true, "the Desk-only navigation stylesheet must exist");
	const stylesheet = fs.readFileSync(stylesheetPath, "utf8");

	assert.match(stylesheet, /body\.dlp-mes-navigation-enabled/);
	assert.match(stylesheet, /#001529/i);
	assert.match(stylesheet, /#1677ff/i);
	assert.match(stylesheet, /:focus-visible/);
	assert.match(stylesheet, /@media\s*\(max-width:/);
	assert.match(stylesheet, /overflow-x:\s*hidden/);
	const openParent = stylesheet.match(
		/\.dlp-mes-navigation__group--open\s*>\s*\.dlp-mes-navigation__row\s*\{([^}]*)\}/
	)?.[1];
	const activeItem = stylesheet.match(
		/\.dlp-mes-navigation__group--self-active\s*>\s*\.dlp-mes-navigation__row\s*\{([^}]*)\}/
	)?.[1];
	assert.match(openParent || "", /background:\s*transparent/);
	assert.match(openParent || "", /color:\s*#fff/i);
	assert.match(activeItem || "", /background:\s*#1677ff/i);
	assert.match(activeItem || "", /color:\s*#fff/i);
	const supersededCustomFiltersSidebar = stylesheet.match(
		/body\.dlp-mes-navigation-enabled\s+\.custom-filters-right-sidebar-container\s*,\s*body\.dlp-mes-navigation-enabled\s+\.custom-filters-right-sidebar-flyout\s*\{([^}]*)\}/
	)?.[1];
	assert.match(supersededCustomFiltersSidebar || "", /display:\s*none\s*!important/);
});

test("expands the root Desktop grid and keeps enhanced entries compact and horizontal", () => {
	const stylesheet = fs.readFileSync(
		path.join(
			__dirname,
			"..",
			"deeplinkerp_branding",
			"public",
			"css",
			"deeplinkerp_navigation.css"
		),
		"utf8"
	);
	const rootContainer = stylesheet.match(
		/body\.dlp-mes-navigation-enabled\s+\.desktop-container\s*>\s*\.icons-container\s*\{([^}]*)\}/
	)?.[1];
	const rootGrid = stylesheet.match(
		/body\.dlp-mes-navigation-enabled\s+\.desktop-container\s*>\s*\.icons-container\s*>\s*\.icons\s*\{([^}]*)\}/
	)?.[1];
	const enhancedEntry = stylesheet.match(
		/body\.dlp-mes-navigation-enabled\s+\.desktop-container\s*>\s*\.icons-container\s*>\s*\.icons\s*>\s*\.desktop-icon\.dlp-desktop-icon-enhanced\s*\{([^}]*)\}/
	)?.[1];
	const enhancedIcon = stylesheet.match(
		/body\.dlp-mes-navigation-enabled\s+\.desktop-icon\.dlp-desktop-icon-enhanced\s+\.dlp-desktop-line-icon\s*\{([^}]*)\}/
	)?.[1];

	assert.match(rootContainer || "", /width:\s*100%\s*!important/);
	assert.match(rootContainer || "", /flex:\s*1\s+1\s+auto/);
	assert.match(rootGrid || "", /display:\s*grid\s*!important/);
	assert.match(rootGrid || "", /grid-template-columns:\s*repeat\(auto-fill,\s*minmax\(180px,\s*1fr\)\)/);
	assert.match(rootGrid || "", /width:\s*100%\s*!important/);
	assert.match(enhancedEntry || "", /display:\s*flex\s*!important/);
	assert.match(enhancedEntry || "", /flex-direction:\s*row\s*!important/);
	assert.match(enhancedEntry || "", /width:\s*100%\s*!important/);
	assert.match(enhancedEntry || "", /height:\s*44px\s*!important/);
	assert.match(enhancedEntry || "", /min-height:\s*44px\s*!important/);
	assert.match(enhancedIcon || "", /width:\s*32px\s*!important/);
	assert.match(enhancedIcon || "", /height:\s*32px\s*!important/);
	assert.doesNotMatch(
		stylesheet,
		/body\.dlp-mes-navigation-enabled\s+\.desktop-container\s+\.desktop-icon\s*\{/
	);
});
