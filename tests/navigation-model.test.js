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

test("keeps the Desk assets separate from website CSS and loads the model before the lifecycle", () => {
	const hooks = fs.readFileSync(
		path.join(__dirname, "..", "deeplinkerp_branding", "hooks.py"),
		"utf8"
	);
	const modelAsset = "/assets/deeplinkerp_branding/js/deeplinkerp_navigation.js";
	const lifecycleAsset = "/assets/deeplinkerp_branding/js/deeplinkerp_branding.js";

	assert.match(hooks, /app_include_css\s*=\s*"\/assets\/deeplinkerp_branding\/css\/deeplinkerp_navigation\.css/);
	assert.ok(hooks.indexOf(modelAsset) < hooks.indexOf(lifecycleAsset));
	assert.match(hooks, /web_include_css\s*=\s*"\/assets\/deeplinkerp_branding\/css\/deeplinkerp_branding\.css"/);
});

test("renders through the existing lifecycle and moves rather than clones the native sidebar", () => {
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
	assert.match(lifecycle, /appendChild\(nativeItems\)/);
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
});
