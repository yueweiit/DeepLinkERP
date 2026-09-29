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
	"deeplinkerp_interface_mode.js"
);
const interfaceMode = fs.existsSync(modulePath) ? require(modulePath) : {};

function productionFunction(name) {
	assert.equal(typeof interfaceMode[name], "function", `${name} must be exported`);
	return interfaceMode[name];
}

class FakeElement {
	constructor(tagName = "div") {
		this.tagName = tagName.toUpperCase();
		this.children = [];
		this.parentElement = null;
		this.className = "";
		this.dataset = {};
		this.attributes = new Map();
		this.listeners = {};
		this.hidden = false;
		this.disabled = false;
		this.textContent = "";
		this.type = "";
	}

	appendChild(child) {
		child.parentElement = this;
		this.children.push(child);
		return child;
	}

	setAttribute(name, value) {
		this.attributes.set(name, String(value));
	}

	getAttribute(name) {
		return this.attributes.get(name) ?? null;
	}

	removeAttribute(name) {
		this.attributes.delete(name);
	}

	addEventListener(type, listener) {
		this.listeners[type] = this.listeners[type] || [];
		this.listeners[type].push(listener);
	}

	dispatch(type, overrides = {}) {
		const event = {
			target: this,
			defaultPrevented: false,
			preventDefault() {
				this.defaultPrevented = true;
			},
			stopPropagation() {},
			...overrides,
		};
		for (const listener of this.listeners[type] || []) listener(event);
		return event;
	}

	contains(target) {
		return target === this || this.children.some((child) => child.contains(target));
	}
}

class FakeDocument {
	constructor(root) {
		this.root = root;
		this.listeners = {};
	}

	createElement(tagName) {
		return new FakeElement(tagName);
	}

	querySelector(selector) {
		const className = selector.startsWith(".") ? selector.slice(1) : "";
		const visit = (element) => {
			if (className && element.className.split(/\s+/).includes(className)) return element;
			for (const child of element.children) {
				const match = visit(child);
				if (match) return match;
			}
			return null;
		};
		return visit(this.root);
	}

	addEventListener(type, listener) {
		this.listeners[type] = this.listeners[type] || [];
		this.listeners[type].push(listener);
	}

	dispatch(type, overrides = {}) {
		const event = { target: this.root, ...overrides };
		for (const listener of this.listeners[type] || []) listener(event);
	}
}

test("normalizes missing or invalid boot state to DL mode", () => {
	const getModeState = productionFunction("getModeState");

	assert.deepEqual(getModeState({}), {
		companyDefault: "dl",
		userOverride: null,
		effectiveMode: "dl",
		canManageCompanyDefault: false,
	});
	assert.equal(getModeState({ deeplinkerp_interface_mode: { effective_mode: "legacy" } }).effectiveMode, "dl");
});

test("uses the server resolved effective mode without recalculating precedence", () => {
	const isDLMode = productionFunction("isDLMode");

	assert.equal(isDLMode({ deeplinkerp_interface_mode: { effective_mode: "classic" } }), false);
	assert.equal(isDLMode({ deeplinkerp_interface_mode: { effective_mode: "dl" } }), true);
});

test("builds follow-company, classic, and DL choices from the boot payload", () => {
	const buildModeOptions = productionFunction("buildModeOptions");
	const options = buildModeOptions(
		{
			deeplinkerp_interface_mode: {
				company_default: "classic",
				user_override: "dl",
				effective_mode: "dl",
			},
		},
		(value) => value
	);

	assert.deepEqual(options.map((option) => option.value), ["follow_company", "classic", "dl"]);
	assert.match(options[0].label, /Classic Mode/);
	assert.equal(options[0].checked, false);
	assert.equal(options[1].checked, false);
	assert.equal(options[2].checked, true);
});

test("saves only the requested mode and reloads once after success", async () => {
	const saveNavigationMode = productionFunction("saveNavigationMode");
	const calls = [];
	let reloads = 0;
	const frappe = {
		xcall(method, args) {
			calls.push({ method, args });
			return Promise.resolve({ effective_mode: "classic" });
		},
	};

	const result = await saveNavigationMode({
		frappe,
		mode: "classic",
		reload: () => {
			reloads += 1;
		},
	});

	assert.deepEqual(calls, [
		{
			method: "deeplinkerp_branding.deeplinkerp_branding.interface_mode.set_user_navigation_mode",
			args: { mode: "classic" },
		},
	]);
	assert.equal(result.effective_mode, "classic");
	assert.equal(reloads, 1);
});

test("does not reload when saving the preference fails", async () => {
	const saveNavigationMode = productionFunction("saveNavigationMode");
	let reloads = 0;
	const failure = new Error("save failed");

	await assert.rejects(
		saveNavigationMode({
			frappe: { xcall: () => Promise.reject(failure) },
			mode: "dl",
			reload: () => {
				reloads += 1;
			},
		}),
		failure
	);
	assert.equal(reloads, 0);
});

test("mounts one accessible avatar menu and retains the profile action", () => {
	const ensureUserMenu = productionFunction("ensureUserMenu");
	const root = new FakeElement();
	const container = root.appendChild(new FakeElement());
	const userButton = container.appendChild(new FakeElement("a"));
	userButton.className = "sidebar-user-button";
	userButton.setAttribute("onclick", "return frappe.ui.toolbar.route_to_user()" );
	const document = new FakeDocument(root);
	let profileCalls = 0;
	const frappe = {
		boot: { deeplinkerp_interface_mode: { company_default: "dl", effective_mode: "dl" } },
		ui: { toolbar: { route_to_user: () => { profileCalls += 1; } } },
	};

	const first = ensureUserMenu({ document, frappe, translate: (value) => value });
	const second = ensureUserMenu({ document, frappe, translate: (value) => value });

	assert.equal(first, second);
	assert.equal(userButton.getAttribute("onclick"), null);
	assert.equal((userButton.listeners.click || []).length, 1);
	assert.equal(container.children.filter((child) => child.className === "dlp-interface-mode-menu").length, 1);
	assert.equal(first.menu.getAttribute("role"), "menu");
	const radioItems = first.menu.children.filter((child) => child.getAttribute("role") === "menuitemradio");
	assert.equal(radioItems.length, 3);
	assert.equal(radioItems.filter((item) => item.getAttribute("aria-checked") === "true").length, 1);
	const profile = first.menu.children.find((child) => child.dataset.action === "profile");
	profile.dispatch("click");
	assert.equal(profileCalls, 1);
});

test("Escape and outside click close the avatar menu and synchronize aria-expanded", () => {
	const ensureUserMenu = productionFunction("ensureUserMenu");
	const root = new FakeElement();
	const container = root.appendChild(new FakeElement());
	const userButton = container.appendChild(new FakeElement("a"));
	userButton.className = "sidebar-user-button";
	const document = new FakeDocument(root);
	const controller = ensureUserMenu({
		document,
		frappe: {
			boot: { deeplinkerp_interface_mode: { effective_mode: "dl" } },
			ui: { toolbar: { route_to_user() {} } },
		},
		translate: (value) => value,
	});

	userButton.dispatch("click");
	assert.equal(controller.menu.hidden, false);
	assert.equal(userButton.getAttribute("aria-expanded"), "true");
	document.dispatch("keydown", { key: "Escape" });
	assert.equal(controller.menu.hidden, true);
	assert.equal(userButton.getAttribute("aria-expanded"), "false");

	userButton.dispatch("click");
	document.dispatch("click", { target: root });
	assert.equal(controller.menu.hidden, true);
	assert.equal(userButton.getAttribute("aria-expanded"), "false");
});

test("gates DL navigation and desktop enhancement behind the effective mode", () => {
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

	assert.match(lifecycle, /DeepLinkERPInterfaceMode\.ensureUserMenu/);
	assert.match(lifecycle, /DeepLinkERPInterfaceMode\.isDLMode\(frappe\.boot\)/);
	assert.match(lifecycle, /disableDLEnhancements\(\)/);
	assert.doesNotMatch(lifecycle, /disableDLEnhancements[\s\S]*custom-filters-right-sidebar/);
});
