frappe.ready(function () {
	new MobileOperationsApp(document.getElementById("mobile-app"));
});

class MobileOperationsApp {
	constructor(root) {
		this.root = root;
		this.route = normalize_mobile_route(window.location.pathname);
		this.drawer_open = false;
		this.render();
		this.bind_events();
	}

	render() {
		this.root.innerHTML = `
			<div class="mobile-app">
				<header class="mobile-app-header">
					<button class="mobile-app-menu-button" data-action="toggle-drawer" aria-label="${__("菜单")}">
						<i class="fa fa-bars"></i>
					</button>
					<div class="mobile-app-header-title" data-region="header-title">${__("移动作业")}</div>
					<button class="mobile-app-header-action" data-action="refresh" aria-label="${__("刷新")}">
						<i class="fa fa-refresh"></i>
					</button>
				</header>
				<main class="mobile-app-main" data-region="main"></main>
				<nav class="mobile-app-bottom-nav">
					<button data-route="/mobile" data-nav="home"><i class="fa fa-home"></i>${__("首页")}</button>
					<button data-route="/mobile/inventory" data-nav="inventory"><i class="fa fa-cubes"></i>${__("库存")}</button>
					<button data-route="/mobile/production" data-nav="production"><i class="fa fa-gears"></i>${__("生产")}</button>
					<button data-route="/mobile/more" data-nav="more"><i class="fa fa-ellipsis-h"></i>${__("更多")}</button>
				</nav>
				<div data-region="drawer"></div>
			</div>
		`;
		this.render_route();
	}

	bind_events() {
		this.root.addEventListener("click", (event) => {
			const route_target = event.target.closest("[data-route]");
			if (route_target) {
				event.preventDefault();
				this.go(route_target.dataset.route);
				return;
			}

			const action = event.target.closest("[data-action]")?.dataset.action;
			if (action === "toggle-drawer") this.toggle_drawer();
			if (action === "close-drawer") this.close_drawer();
			if (action === "refresh") this.refresh();
			if (action === "desktop") window.location.href = "/desk";
		});

		window.addEventListener("popstate", () => {
			this.route = normalize_mobile_route(window.location.pathname);
			this.render_route();
		});
	}

	go(route) {
		const normalized = normalize_mobile_route(route);
		if (normalized === this.route && window.location.pathname === normalized) {
			this.close_drawer();
			return;
		}
		window.history.pushState({}, "", normalized);
		this.route = normalized;
		this.close_drawer();
		this.render_route();
	}

	render_route() {
		const main = this.root.querySelector("[data-region='main']");
		const title = this.root.querySelector("[data-region='header-title']");
		this.root.querySelectorAll("[data-nav]").forEach((button) => {
			button.classList.toggle("is-active", button.dataset.nav === route_nav_key(this.route));
		});

		if (this.route === "/mobile/material-request") {
			title.textContent = __("物料需求");
			this.material_request = new MobileMaterialRequestView(main, this);
			return;
		}

		if (this.route === "/mobile/material-request/new") {
			title.textContent = __("新建物料需求");
			this.material_request_create = new MobileMaterialRequestCreateView(main, this);
			return;
		}

		if (this.route === "/mobile/stock-entry" || this.route.startsWith("/mobile/stock-entry/")) {
			title.textContent = __("物料移动");
			this.stock_entry = new MobileStockEntryView(main, this);
			return;
		}

		if (this.route === "/mobile/inventory") {
			title.textContent = __("库存");
			this.inventory = new MobileInventoryView(main, this);
			return;
		}

		if (this.route === "/mobile/inventory/query") {
			title.textContent = __("库存查询");
			this.inventory_query = new MobileInventoryQueryView(main, this);
			return;
		}

		if (this.route === "/mobile/more") {
			title.textContent = __("更多");
			this.more = new MobileMoreView(main, this);
			return;
		}

		title.textContent = this.route === "/mobile" ? __("移动作业") : route_title(this.route);
		if (this.route === "/mobile") {
			main.innerHTML = this.home_html();
			this.refresh_home();
			return;
		}

		main.innerHTML = this.placeholder_html(this.route);
	}

	home_html() {
		return `
			<div class="mobile-home-page">
				<div class="mobile-app-page-title">${__("移动作业")}</div>
				<p class="mobile-app-page-subtitle">${__("库存与生产现场处理入口")}</p>
				<section class="mobile-home-section">
					<div class="mobile-home-section-heading"><h2>${__("工作提醒")}</h2><span>${__("需要及时处理")}</span></div>
					<div class="mobile-home-reminder-grid">
						<button class="mobile-home-reminder-card" data-route="/mobile/material-request"><strong data-region="home-in-progress">—</strong><span>${__("待处理物料需求")}</span></button>
						<button class="mobile-home-reminder-card" data-route="/mobile/stock-entry"><strong data-region="home-stock-draft">—</strong><span>${__("待提交物料移动")}</span></button>
						<button class="mobile-home-reminder-card" data-route="/mobile/stock-entry"><strong data-region="home-mes-pending">—</strong><span>${__("MES 待推送")}</span></button>
					</div>
				</section>
				<section class="mobile-home-section">
					<div class="mobile-home-section-heading"><h2>${__("库存作业")}</h2><button data-route="/mobile/inventory">${__("查看全部")}</button></div>
					<div class="mobile-home-module-grid">
						<button class="mobile-home-module-card" data-route="/mobile/material-request"><i class="fa fa-list-alt"></i><strong>${__("物料需求")}</strong><small>${__("查看和创建物料需求")}</small></button>
						<button class="mobile-home-module-card" data-route="/mobile/stock-entry"><i class="fa fa-exchange"></i><strong>${__("物料移动")}</strong><small>${__("提交和处理物料移动")}</small></button>
						<button class="mobile-home-module-card" data-route="/mobile/inventory/query"><i class="fa fa-search"></i><strong>${__("库存查询")}</strong><small>${__("按物料或仓库查询")}</small></button>
					</div>
				</section>
				<section class="mobile-home-section">
					<div class="mobile-home-section-heading"><h2>${__("生产作业")}</h2><button data-route="/mobile/production">${__("查看全部")}</button></div>
					<div class="mobile-home-module-grid mobile-home-production-grid">
						<button class="mobile-home-module-card" data-route="/mobile/production"><i class="fa fa-gears"></i><strong>${__("生产作业")}</strong><small>${__("查看生产现场任务")}</small></button>
						<button class="mobile-home-module-card" data-route="/mobile/production"><i class="fa fa-warning"></i><strong>${__("异常处理")}</strong><small>${__("查看生产异常")}</small></button>
					</div>
				</section>
			</div>
		`;
	}

	refresh_home() {
		const request_sequence = (this.home_request_sequence || 0) + 1;
		this.home_request_sequence = request_sequence;

		frappe.call({
			method: "mobile_operations.api.get_mobile_inventory_summary",
			freeze: false,
			callback: (response) => {
				if (request_sequence !== this.home_request_sequence || this.route !== "/mobile") {
					return;
				}

				const material_summary = response.message?.material_request || [];
				const stock_summary = response.message?.stock_entry || [];
				const in_progress = material_summary.find((item) => item.key === "in_progress");
				const draft = stock_summary.find((item) => item.key === "draft");
				const mes_pending = stock_summary.find((item) => item.key === "mes_pending");
				const value = this.root.querySelector('[data-region="home-in-progress"]');
				const draft_value = this.root.querySelector('[data-region="home-stock-draft"]');
				const mes_value = this.root.querySelector('[data-region="home-mes-pending"]');
				if (value) {
					value.textContent = format_integer(in_progress?.count || 0);
				}
				if (draft_value) draft_value.textContent = format_integer(draft?.count || 0);
				if (mes_value) mes_value.textContent = format_integer(mes_pending?.count || 0);
			},
		});
	}

	placeholder_html(route) {
		const content = {
			"/mobile/inventory/query": ["fa-search", __("库存查询"), __("库存查询页面将在这里接入物料、仓库和实时库存筛选。")],
			"/mobile/stock-entry": ["fa-exchange", __("物料移动"), __("物料移动页面将在这里接入扫码、数量和仓库选择。")],
			"/mobile/production": ["fa-gears", __("生产作业"), __("生产现场页面将在这里接入领料、报工和异常处理。")],
			"/mobile/material-request/new": ["fa-plus-circle", __("新建物料需求"), __("新建需求页面将在这里接入按物料、数量、仓库的快速录入。")],
		}[route] || ["fa-mobile", __("移动作业"), __("页面正在规划中。")];

		return `
			<div class="mobile-app-mobile-page">
				<div class="mobile-app-panel">
					<i class="fa ${content[0]}"></i>
					<h2>${content[1]}</h2><p>${content[2]}</p>
					<a class="mobile-app-desktop-link" href="/desk">${__("电脑端处理")}</a>
				</div>
			</div>
		`;
	}

	toggle_drawer() {
		this.drawer_open ? this.close_drawer() : this.open_drawer();
	}

	open_drawer() {
		this.drawer_open = true;
		this.root.querySelector("[data-region='drawer']").innerHTML = `
			<div class="mobile-app-drawer-backdrop" data-action="close-drawer">
				<aside class="mobile-app-drawer" onclick="event.stopPropagation()">
					<h2>${__("移动作业")}</h2><p>${escape_html(window.frappe?.boot?.user?.name || "")}</p>
					<button class="mobile-app-drawer-link" data-route="/mobile"><i class="fa fa-home"></i>${__("首页")}</button>
					<button class="mobile-app-drawer-link" data-route="/mobile/inventory"><i class="fa fa-cubes"></i>${__("库存")}</button>
					<button class="mobile-app-drawer-link mobile-app-drawer-child" data-route="/mobile/material-request"><i class="fa fa-list-alt"></i>${__("物料需求")}</button>
					<button class="mobile-app-drawer-link mobile-app-drawer-child" data-route="/mobile/stock-entry"><i class="fa fa-exchange"></i>${__("物料移动")}</button>
					<button class="mobile-app-drawer-link mobile-app-drawer-child" data-route="/mobile/inventory/query"><i class="fa fa-search"></i>${__("库存查询")}</button>
					<button class="mobile-app-drawer-link" data-route="/mobile/production"><i class="fa fa-gears"></i>${__("生产作业")}</button>
					<button class="mobile-app-drawer-link" data-route="/mobile/more"><i class="fa fa-ellipsis-h"></i>${__("更多")}</button>
					<div class="mobile-app-drawer-divider"></div>
					<button class="mobile-app-drawer-link" data-action="desktop"><i class="fa fa-desktop"></i>${__("电脑端处理")}</button>
				</aside>
			</div>
		`;
	}

	close_drawer() {
		this.drawer_open = false;
		const drawer = this.root.querySelector("[data-region='drawer']");
		if (drawer) drawer.innerHTML = "";
	}

	refresh() {
		if (this.material_request && this.route === "/mobile/material-request") {
			this.material_request.refresh();
		} else if (this.stock_entry && (this.route === "/mobile/stock-entry" || this.route.startsWith("/mobile/stock-entry/"))) {
			this.stock_entry.refresh();
		} else if (this.inventory && this.route === "/mobile/inventory") {
			this.inventory.refresh();
		} else if (this.inventory_query && this.route === "/mobile/inventory/query") {
			this.inventory_query.refresh();
		} else {
			this.render_route();
		}
	}
}

class MobileInventoryView {
	constructor(parent, app) {
		this.parent = parent;
		this.app = app;
		this.request_sequence = 0;
		this.data = { material_request: null, stock_entry: null };
		this.render_shell();
		this.refresh();
	}

	render_shell() {
		this.parent.innerHTML = `
			<div class="mobile-inventory-page">
				<div class="mobile-inventory-heading"><div><h2>${__("库存")}</h2><p>${__("库存人员常用作业入口")}</p></div><span class="mobile-inventory-heading-icon"><i class="fa fa-cubes"></i></span></div>
				<div class="mobile-inventory-summary" data-region="inventory-summary">
					<div class="mobile-inventory-summary-card"><strong data-region="inventory-mr-count">—</strong><span>${__("待处理物料需求")}</span></div>
					<div class="mobile-inventory-summary-card"><strong data-region="inventory-se-draft">—</strong><span>${__("待提交物料移动")}</span></div>
					<div class="mobile-inventory-summary-card"><strong data-region="inventory-se-pending">—</strong><span>${__("MES 待推送")}</span></div>
				</div>
				<div class="mobile-inventory-section-heading"><h3>${__("库存作业")}</h3></div>
				<div class="mobile-inventory-grid">
					<button class="mobile-inventory-card" data-route="/mobile/material-request"><i class="fa fa-list-alt"></i><strong>${__("物料需求")}</strong><small>${__("查看、创建和处理物料需求")}</small><span>${__("进入")} <i class="fa fa-angle-right"></i></span></button>
					<button class="mobile-inventory-card" data-route="/mobile/stock-entry"><i class="fa fa-exchange"></i><strong>${__("物料移动")}</strong><small>${__("提交单据和处理 MES 推送")}</small><span>${__("进入") } <i class="fa fa-angle-right"></i></span></button>
					<button class="mobile-inventory-card" data-route="/mobile/inventory/query"><i class="fa fa-search"></i><strong>${__("库存查询")}</strong><small>${__("按物料或仓库查询库存")}</small><span>${__("进入") } <i class="fa fa-angle-right"></i></span></button>
				</div>
			</div>
		`;
	}

	refresh() {
		const sequence = ++this.request_sequence;
		frappe.call({
			method: "mobile_operations.api.get_mobile_inventory_summary",
			freeze: false,
			callback: (response) => {
				if (sequence !== this.request_sequence || this.app.route !== "/mobile/inventory") return;
				const summary = response.message || {};
				this.data.material_request = { summary: summary.material_request || [] };
				this.data.stock_entry = { summary: summary.stock_entry || [] };
				this.render_summary();
			},
		});
	}

	render_summary() {
		const material_summary = this.data.material_request?.summary || [];
		const stock_summary = this.data.stock_entry?.summary || [];
		const in_progress = material_summary.find((item) => item.key === "in_progress");
		const draft = stock_summary.find((item) => item.key === "draft");
		const pending = stock_summary.find((item) => item.key === "mes_pending");
		const values = {
			"inventory-mr-count": in_progress?.count,
			"inventory-se-draft": draft?.count,
			"inventory-se-pending": pending?.count,
		};
		Object.entries(values).forEach(([region, value]) => {
			const element = this.parent.querySelector(`[data-region='${region}']`);
			if (element && value !== undefined) element.textContent = format_integer(value);
		});
	}
}

class MobileInventoryQueryView {
	constructor(parent, app) {
		this.parent = parent;
		this.app = app;
		this.request_sequence = 0;
		this.page_size = 40;
		this.offset = 0;
		this.has_searched = false;
		this.search_data = null;
		this.options = { companies: [], default_company: "" };
		this.select_options = {
			company: [{ value: "", label: __("全部公司") }],
			status: this.get_status_options(),
		};
		this.input_timer = null;
		this.suggestion_sequence = 0;
		this.render_shell();
		this.bind_events();
		this.load_options();
	}

	render_shell() {
		this.parent.innerHTML = `
			<div class="mobile-inventory-query-page">
				<div class="mobile-inventory-query-heading"><div><h2>${__("库存查询")}</h2><p>${__("按物料和库位快速查询库存")}</p></div><i class="fa fa-search"></i></div>
				<section class="mobile-inventory-query-card">
					<div class="mobile-inventory-query-field mobile-inventory-query-item"><label>${__("物料")}</label><div class="mobile-inventory-query-autocomplete"><div class="mobile-inventory-query-input"><i class="fa fa-search"></i><input type="search" data-field="inventory-item-search" placeholder="${__("请输入物料编码或名称")}" autocomplete="off"></div><div class="mobile-inventory-query-suggestions" data-region="inventory-item-suggestions" hidden></div></div></div>
					<div class="mobile-inventory-query-two-columns">
						<label class="mobile-inventory-query-field">${__("公司")}<div class="mobile-inventory-query-custom-select" data-select-field="inventory-company" data-select-value=""><button type="button" class="mobile-inventory-query-select-trigger" data-action="inventory-query-toggle-select" data-select-field="inventory-company" aria-haspopup="listbox" aria-expanded="false"><span data-region="inventory-company-label">${__("全部公司")}</span><i class="fa fa-chevron-down"></i></button><div class="mobile-inventory-query-select-options" data-region="inventory-company-options" role="listbox" hidden></div></div></label>
						<label class="mobile-inventory-query-field">${__("库存状态")}<div class="mobile-inventory-query-custom-select" data-select-field="inventory-status" data-select-value="all"><button type="button" class="mobile-inventory-query-select-trigger" data-action="inventory-query-toggle-select" data-select-field="inventory-status" aria-haspopup="listbox" aria-expanded="false"><span data-region="inventory-status-label">${__("全部库存")}</span><i class="fa fa-chevron-down"></i></button><div class="mobile-inventory-query-select-options" data-region="inventory-status-options" role="listbox" hidden></div></div></label>
					</div>
					<div class="mobile-inventory-query-two-columns">
						<label class="mobile-inventory-query-field">${__("仓库名称")}<div class="mobile-inventory-query-autocomplete"><input type="search" data-field="inventory-warehouse-name" placeholder="${__("如 INVENTARIO SEMITERMINADO")}" autocomplete="off"><div class="mobile-inventory-query-suggestions" data-region="inventory-warehouse-suggestions" hidden></div></div></label>
						<label class="mobile-inventory-query-field">${__("库位号")}<div class="mobile-inventory-query-autocomplete"><input type="search" data-field="inventory-location-code" placeholder="${__("如 A-01")}" autocomplete="off"><div class="mobile-inventory-query-suggestions" data-region="inventory-location-suggestions" hidden></div></div></label>
					</div>
					<div class="mobile-inventory-query-actions"><button class="mobile-inventory-query-clear" data-action="inventory-query-clear">${__("清空")}</button></div>
				</section>
				<div class="mobile-inventory-query-summary" data-region="inventory-query-summary"></div>
				<div class="mobile-inventory-query-result-heading"><h3>${__("查询结果")}</h3><span data-region="inventory-query-count"></span></div>
				<div class="mobile-inventory-query-results" data-region="inventory-query-results"><div class="mobile-inventory-query-empty">${__("请输入物料、仓库名称或库位号后查询")}</div></div>
				<div class="mobile-inventory-query-status" data-region="inventory-query-status" role="alert"></div>
			</div>
		`;
	}

	bind_events() {
		this.parent.addEventListener("click", (event) => {
			const suggestion = event.target.closest("[data-suggestion]");
			if (suggestion) {
				this.select_suggestion(suggestion);
				return;
			}
			const select_option = event.target.closest("[data-select-option]");
			if (select_option) {
				this.select_option(select_option);
				return;
			}
			const action = event.target.closest("[data-action]")?.dataset.action;
			if (action === "inventory-query-toggle-select") {
				this.toggle_select(event.target.closest("[data-select-field]")?.dataset.selectField);
				return;
			}
			if (action === "inventory-query-clear") this.clear();
			if (action === "inventory-query-load-more") this.query({ append: true });
		if (!event.target.closest(".mobile-inventory-query-autocomplete")) this.hide_suggestions();
			if (!event.target.closest(".mobile-inventory-query-custom-select")) this.hide_selects();
		});
		this.parent.addEventListener("input", (event) => {
			if (!event.target.matches("[data-field^='inventory-']")) return;
			this.schedule_input(event.target.dataset.field);
		});
		this.parent.addEventListener("keydown", (event) => {
			if (event.key === "Escape" && event.target.matches("[data-field^='inventory-']")) {
				this.hide_suggestions();
			}
		});
		this.parent.addEventListener("change", (event) => {
			if (event.target.matches("[data-field='inventory-status'], [data-field='inventory-company']")) this.schedule_query();
		});
		this.render_select_options("company");
		this.render_select_options("status");
	}

	load_options() {
		frappe.call({
			method: "mobile_operations.api.get_mobile_inventory_options",
			freeze: false,
			callback: (response) => {
				this.options = response.message || this.options;
				this.select_options.company = [{ value: "", label: __("全部公司") }].concat(
					(this.options.companies || []).map((item) => ({ value: item.name, label: item.name }))
				);
				this.render_select_options("company");
				this.set_select_value("inventory-company", this.options.default_company || "", false);
			},
		});
	}

	get_status_options() {
		return [
			{ value: "all", label: __("全部库存") },
			{ value: "positive", label: __("有库存") },
			{ value: "insufficient", label: __("库存不足") },
			{ value: "negative", label: __("负库存") },
			{ value: "zero", label: __("库存为零") },
		];
	}

	get_select_wrapper(field_name) {
		return this.parent.querySelector(`[data-select-field='${field_name}']`);
	}

	render_select_options(select_name) {
		const field_name = `inventory-${select_name}`;
		const region = this.parent.querySelector(`[data-region='${field_name}-options']`);
		if (!region) return;
		region.innerHTML = (this.select_options[select_name] || []).map((option) => `<button type="button" class="mobile-inventory-query-select-option" data-select-option data-select-field="${escape_attribute(field_name)}" data-value="${escape_attribute(option.value)}" role="option"><span>${escape_html(option.label)}</span></button>`).join("");
	}

	toggle_select(field_name) {
		if (!field_name) return;
		const wrapper = this.get_select_wrapper(field_name);
		const options = wrapper?.querySelector(".mobile-inventory-query-select-options");
		if (!wrapper || !options) return;
		const is_open = !options.hidden;
		this.hide_selects();
		if (!is_open) {
			options.hidden = false;
			wrapper.querySelector(".mobile-inventory-query-select-trigger")?.setAttribute("aria-expanded", "true");
		}
	}

	select_option(option) {
		this.set_select_value(option.dataset.selectField, option.dataset.value || "", true);
	}

	set_select_value(field_name, value, should_query = true) {
		const wrapper = this.get_select_wrapper(field_name);
		if (!wrapper) return;
		const select_name = field_name.replace("inventory-", "");
		const options = this.select_options[select_name] || [];
		const selected = options.find((option) => String(option.value) === String(value)) || options[0];
		if (!selected) return;
		wrapper.dataset.selectValue = selected.value;
		const label = wrapper.querySelector(`[data-region='${field_name}-label']`);
		if (label) label.textContent = selected.label;
		this.hide_selects();
		if (should_query) this.schedule_query();
	}

	hide_selects() {
		this.parent.querySelectorAll(".mobile-inventory-query-select-options").forEach((options) => {
			options.hidden = true;
			options.closest(".mobile-inventory-query-custom-select")?.querySelector(".mobile-inventory-query-select-trigger")?.setAttribute("aria-expanded", "false");
		});
	}

	get_query() {
		return {
			item_search: this.parent.querySelector("[data-field='inventory-item-search']")?.value.trim() || "",
			warehouse_name: this.parent.querySelector("[data-field='inventory-warehouse-name']")?.value.trim() || "",
			location_code: this.parent.querySelector("[data-field='inventory-location-code']")?.value.trim() || "",
			company: this.get_select_wrapper("inventory-company")?.dataset.selectValue || "",
			stock_status: this.get_select_wrapper("inventory-status")?.dataset.selectValue || "all",
		};
	}

	refresh() {
		this.load_options();
		if (this.has_searched) this.query();
	}

	schedule_input(field_name) {
		this.hide_suggestions();
		this.hide_selects();
		window.clearTimeout(this.input_timer);
		this.input_timer = window.setTimeout(() => {
			const field = this.parent.querySelector(`[data-field='${field_name}']`);
			const value = field?.value.trim() || "";
			if (value) this.load_suggestions(field_name, value);
			this.query();
		}, 300);
	}

	schedule_query() {
		window.clearTimeout(this.input_timer);
		this.hide_suggestions();
		this.hide_selects();
		this.input_timer = window.setTimeout(() => this.query(), 180);
	}

	suggestion_kind(field_name) {
		return {
			"inventory-item-search": "item",
			"inventory-warehouse-name": "warehouse",
			"inventory-location-code": "location",
		}[field_name];
	}

	load_suggestions(field_name, search_text) {
		const kind = this.suggestion_kind(field_name);
		if (!kind) return;
		const sequence = ++this.suggestion_sequence;
		frappe.call({
			method: "mobile_operations.api.get_mobile_inventory_suggestions",
			args: { kind, search_text, company: this.get_query().company, limit: 20 },
			freeze: false,
			callback: (response) => {
				if (sequence !== this.suggestion_sequence || this.app.route !== "/mobile/inventory/query") return;
				this.render_suggestions(field_name, response.message?.suggestions || []);
			},
			error: () => {
				if (sequence === this.suggestion_sequence) this.hide_suggestions();
			},
		});
	}

	render_suggestions(field_name, suggestions) {
		this.hide_suggestions();
		const region_name = {
			"inventory-item-search": "inventory-item-suggestions",
			"inventory-warehouse-name": "inventory-warehouse-suggestions",
			"inventory-location-code": "inventory-location-suggestions",
		}[field_name];
		const region = region_name && this.parent.querySelector(`[data-region='${region_name}']`);
		if (!region || !suggestions.length) return;
		region.innerHTML = suggestions.map((item) => `<button type="button" class="mobile-inventory-query-suggestion" data-suggestion data-value="${escape_attribute(item.value)}" data-field="${escape_attribute(field_name)}"><strong>${escape_html(item.label || item.value)}</strong>${item.sublabel ? `<span>${escape_html(item.sublabel)}</span>` : ""}</button>`).join("");
		region.hidden = false;
	}

	select_suggestion(suggestion) {
		const field_name = suggestion.dataset.field;
		const field = this.parent.querySelector(`[data-field='${field_name}']`);
		if (!field) return;
		field.value = suggestion.dataset.value || "";
		this.hide_suggestions();
		this.query();
	}

	hide_suggestions() {
		this.parent.querySelectorAll(".mobile-inventory-query-suggestions").forEach((region) => {
			region.hidden = true;
			region.innerHTML = "";
		});
	}

	query({ append = false } = {}) {
		const sequence = ++this.request_sequence;
		const query = this.get_query();
		if (!query.item_search && !query.warehouse_name && !query.location_code) {
			this.has_searched = false;
			this.set_status("", "");
			this.render_initial();
			return;
		}
		this.has_searched = true;
		const offset = append ? this.offset : 0;
		if (!append) this.render_loading();
		frappe.call({
			method: "mobile_operations.api.get_mobile_inventory_dashboard",
			args: { ...query, limit: this.page_size, offset },
			freeze: false,
			callback: (response) => {
				if (sequence !== this.request_sequence || this.app.route !== "/mobile/inventory/query") return;
				const next_data = response.message || { items: [], total: 0, has_more: false, summary: {} };
				if (append && this.search_data) {
					this.search_data = { ...this.search_data, ...next_data, items: [...(this.search_data.items || []), ...(next_data.items || [])] };
				} else {
					this.search_data = next_data;
				}
				this.offset = this.search_data.items?.length || 0;
				this.render_results();
				this.set_status("", "");
			},
			error: () => {
				if (sequence === this.request_sequence) {
					this.set_status(__("库存查询加载失败，请点击查询重试"), "error");
					this.render_error();
				}
			},
		});
	}

	clear() {
		window.clearTimeout(this.input_timer);
		this.request_sequence += 1;
		this.suggestion_sequence += 1;
		this.hide_suggestions();
		this.hide_selects();
		this.parent.querySelectorAll("[data-field^='inventory-']").forEach((field) => {
			field.value = "";
		});
		this.set_select_value("inventory-company", this.options.default_company || "", false);
		this.set_select_value("inventory-status", "all", false);
		this.has_searched = false;
		this.search_data = null;
		this.offset = 0;
		this.set_status("", "");
		this.render_initial();
	}

	render_initial() {
		this.parent.querySelector("[data-region='inventory-query-summary']").innerHTML = "";
		this.parent.querySelector("[data-region='inventory-query-count']").textContent = "";
		this.parent.querySelector("[data-region='inventory-query-results']").innerHTML = `<div class="mobile-inventory-query-empty">${__("请输入物料、仓库名称或库位号后查询")}</div>`;
	}

	render_loading() {
		this.parent.querySelector("[data-region='inventory-query-summary']").innerHTML = Array.from({ length: 4 }, () => "<div class='mobile-inventory-query-skeleton'></div>").join("");
		this.parent.querySelector("[data-region='inventory-query-results']").innerHTML = Array.from({ length: 3 }, () => "<div class='mobile-inventory-query-skeleton mobile-inventory-query-skeleton-card'></div>").join("");
	}

	render_error() {
		this.parent.querySelector("[data-region='inventory-query-summary']").innerHTML = "";
		this.parent.querySelector("[data-region='inventory-query-results']").innerHTML = `<div class="mobile-inventory-query-empty">${__("库存查询加载失败，请点击查询重试")}</div>`;
	}

	render_results() {
		const data = this.search_data || {};
		const summary = data.summary || {};
		const summary_items = [
			["total", __("查询结果")],
			["positive", __("有库存")],
			["insufficient", __("库存不足")],
			["negative", __("负库存")],
		];
		this.parent.querySelector("[data-region='inventory-query-summary']").innerHTML = summary_items.map(([key, label]) => `<div class="mobile-inventory-query-summary-card${key === "negative" ? " is-danger" : key === "insufficient" ? " is-warning" : ""}"><strong>${format_integer(summary[key] || 0)}</strong><span>${escape_html(label)}</span></div>`).join("");
		const count = this.parent.querySelector("[data-region='inventory-query-count']");
		if (count) count.textContent = data.total ? __(`{0} 条`, [data.total]) : __("无记录");
		const load_more = data.has_more ? `<button class="mobile-inventory-query-load-more" data-action="inventory-query-load-more">${__("加载更多")}</button>` : "";
		this.parent.querySelector("[data-region='inventory-query-results']").innerHTML = data.items?.length ? data.items.map((item) => this.inventory_card(item)).join("") + load_more : `<div class="mobile-inventory-query-empty">${__("当前筛选条件下没有库存记录")}</div>`;
	}

	inventory_card(item) {
		const warehouse_name = item.warehouse_name || item.parent_warehouse || "-";
		const warehouse_company = item.company || "";
		const status_tone = inventory_status_tone(item.status);
		return `<article class="mobile-inventory-query-result-card"><div class="mobile-inventory-query-card-top"><div><strong>${escape_html(item.item_code || "-")}</strong><span>${escape_html(item.item_name || item.description || "")}</span></div><em class="mobile-inventory-query-status ${status_tone}">${escape_html(item.status_label || "")}</em></div><div class="mobile-inventory-query-warehouse"><b>${escape_html(item.location_code || item.warehouse_display || item.warehouse || "-")}</b><span>${escape_html(warehouse_name)}${warehouse_company ? ` · ${escape_html(warehouse_company)}` : ""}</span></div><div class="mobile-inventory-query-metrics"><div><small>${__("实际库存")}</small><strong>${format_number(item.actual_qty)}</strong><span>${escape_html(item.stock_uom || "")}</span></div><div><small>${__("可用库存")}</small><strong>${format_number(item.available_qty)}</strong><span>${escape_html(item.stock_uom || "")}</span></div><div><small>${__("已预留")}</small><strong>${format_number(item.reserved_qty)}</strong><span>${escape_html(item.stock_uom || "")}</span></div></div><div class="mobile-inventory-query-projected">${__("预计库存")}: ${format_number(item.projected_qty)} ${escape_html(item.stock_uom || "")}</div></article>`;
	}

	set_status(message, tone) {
		const status = this.parent.querySelector("[data-region='inventory-query-status']");
		if (status) {
			status.textContent = message || "";
			status.className = `mobile-inventory-query-status-message${tone ? ` is-${tone}` : ""}`;
		}
	}
}

class MobileMoreView {
	constructor(parent, app) {
		this.parent = parent;
		this.app = app;
		this.parent.innerHTML = `
			<div class="mobile-more-page">
				<div class="mobile-more-heading"><div><h2>${__("更多")}</h2><p>${__("账户与系统功能")}</p></div><i class="fa fa-ellipsis-h"></i></div>
				<div class="mobile-more-panel">
					<div class="mobile-more-user"><span>${escape_html(window.frappe?.boot?.user?.name || "")}</span><small>${escape_html(window.frappe?.boot?.user?.email || "")}</small></div>
					<button class="mobile-more-link" data-action="desktop"><i class="fa fa-desktop"></i><span>${__("使用标准电脑端")}</span><i class="fa fa-angle-right"></i></button>
				</div>
				<div class="mobile-more-hint">${__("低频功能和系统设置将逐步在这里接入")}</div>
			</div>
		`;
	}
}

class MobileMaterialRequestView {
	constructor(parent, app) {
		this.parent = parent;
		this.app = app;
		this.active_bucket = "in_progress";
		this.request_sequence = 0;
		this.page_size = 40;
		this.offset = 0;
		this.search_timer = null;
		this.render_shell();
		this.bind_events();
		this.refresh();
	}

	render_shell() {
		this.parent.innerHTML = `
			<div class="mobile-material-request-page">
				<div class="mobile-mr-header"><div class="mobile-mr-heading"><h2>${__("物料需求")}</h2><p>${__("库存与生产移动作业")}</p></div><div class="mobile-mr-header-actions"><button class="mobile-mr-new" data-action="mr-new" aria-label="${__("新建物料需求")}"><i class="fa fa-plus"></i><span>${__("新建")}</span></button></div></div>
				<div class="mobile-mr-summary" data-region="summary"></div>
				<div class="mobile-mr-section-title"><h3>${__("待处理物料需求")}</h3><span data-region="list-count"></span></div>
				<div class="mobile-mr-filter">
					<div class="mobile-mr-search-box"><i class="fa fa-search"></i><input type="search" data-field="search" placeholder="${__("搜索编号、物料或需求标题")}" autocomplete="off"></div>
					<div class="mobile-mr-custom-select" data-field="status" data-select-value="in_progress">
						<button type="button" class="mobile-mr-select-trigger" data-action="mr-toggle-status" aria-haspopup="listbox" aria-expanded="false" aria-label="${__("状态筛选")}"><span data-region="mr-status-label">${__("进行中")}</span><i class="fa fa-chevron-down"></i></button>
						<div class="mobile-mr-select-options" data-region="mr-status-options" role="listbox" hidden>
							<button type="button" class="mobile-mr-select-option" data-mr-status-option data-value="all" role="option"><span>${__("全部状态")}</span></button>
							<button type="button" class="mobile-mr-select-option is-selected" data-mr-status-option data-value="in_progress" role="option"><span>${__("进行中")}</span></button>
							<button type="button" class="mobile-mr-select-option" data-mr-status-option data-value="to_issue" role="option"><span>${__("待发料")}</span></button>
							<button type="button" class="mobile-mr-select-option" data-mr-status-option data-value="partial" role="option"><span>${__("部分完成")}</span></button>
							<button type="button" class="mobile-mr-select-option" data-mr-status-option data-value="transit" role="option"><span>${__("调拨在途")}</span></button>
							<button type="button" class="mobile-mr-select-option" data-mr-status-option data-value="exception" role="option"><span>${__("异常/停止")}</span></button>
						</div>
					</div>
				</div>
				<div class="mobile-mr-request-list" data-region="requests"></div>
			</div>
		`;
	}

	bind_events() {
		this.parent.addEventListener("click", (event) => {
			const status_option = event.target.closest("[data-mr-status-option]");
			if (status_option) {
				this.set_status_filter(status_option.dataset.value || "all");
				return;
			}
			const action = event.target.closest("[data-action]")?.dataset.action;
			if (action === "mr-toggle-status") {
				this.toggle_status_filter();
				return;
			}
			if (action === "mr-refresh") this.refresh();
			if (action === "mr-new") this.app.go("/mobile/material-request/new");
			if (action === "mr-load-more") this.refresh({ append: true });
			if (action === "mr-back") this.render_dashboard();
			if (action === "mr-desktop") {
				const name = event.target.closest("[data-name]")?.dataset.name;
				if (name) window.location.href = `/desk/Form/Material Request/${encodeURIComponent(name)}`;
			}
			if (action === "mr-submit") {
				const name = event.target.closest("[data-name]")?.dataset.name;
				if (name) this.submit_detail(name);
				return;
			}
			if (action === "mr-issue-push") {
				const name = event.target.closest("[data-name]")?.dataset.name;
				if (name) this.issue_and_push_detail(name);
				return;
			}
			if (action === "mr-material-move") {
				const name = event.target.closest("[data-name]")?.dataset.name;
				if (name) this.create_material_movement_detail(name);
				return;
			}
			if (action === "mr-issue-cancel") {
				this.close_issue_dialog();
				return;
			}
			if (action === "mr-issue-confirm") {
				this.confirm_issue_detail();
				return;
			}
			if (event.target.closest("[data-bucket]")) {
				this.active_bucket = event.target.closest("[data-bucket]").dataset.bucket || "all";
				this.offset = 0;
				this.set_status_filter(this.active_bucket, false);
				this.refresh();
			}
			if (!event.target.closest(".mobile-mr-custom-select")) this.hide_status_filter();
			const open_name = event.target.closest("[data-open-request]")?.dataset.openRequest;
			if (open_name && !event.target.closest("button")) this.open_detail(open_name);
			const view_name = event.target.closest("[data-action='mr-view']")?.dataset.name;
			if (view_name) this.open_detail(view_name);
		});
		this.parent.addEventListener("input", (event) => {
			if (event.target.matches("[data-field='search']")) {
				this.offset = 0;
				window.clearTimeout(this.search_timer);
				this.search_timer = window.setTimeout(() => this.refresh(), 280);
			}
		});
		this.parent.addEventListener("change", (event) => {
			if (!event.target.matches("[data-issue-warehouse]")) return;
			const row_element = event.target.closest("[data-issue-index]");
			const item = this.current_issue_options?.items[Number(row_element?.dataset.issueIndex)];
			const actual = item ? this.get_issue_actual_qty(item, event.target.value) : 0;
			const actual_region = row_element?.querySelector("[data-issue-actual]");
			if (actual_region) actual_region.textContent = format_number(actual);
		});
		this.sync_status_filter();
	}

	get_status_label(status) {
		return {
			all: __("全部状态"),
			in_progress: __("进行中"),
			to_issue: __("待发料"),
			partial: __("部分完成"),
			transit: __("调拨在途"),
			exception: __("异常/停止"),
		}[status] || __("全部状态");
	}

	toggle_status_filter() {
		const wrapper = this.parent.querySelector("[data-field='status']");
		const options = wrapper?.querySelector(".mobile-mr-select-options");
		if (!wrapper || !options) return;
		const is_open = !options.hidden;
		this.hide_status_filter();
		if (!is_open) {
			options.hidden = false;
			wrapper.querySelector(".mobile-mr-select-trigger")?.setAttribute("aria-expanded", "true");
		}
	}

	set_status_filter(status, should_refresh = true) {
		const allowed = ["all", "in_progress", "to_issue", "partial", "transit", "exception"];
		this.active_bucket = allowed.includes(status) ? status : "all";
		this.sync_status_filter();
		this.hide_status_filter();
		if (should_refresh) {
			this.offset = 0;
			this.refresh();
		}
	}

	sync_status_filter() {
		const wrapper = this.parent.querySelector("[data-field='status']");
		if (!wrapper) return;
		wrapper.dataset.selectValue = this.active_bucket;
		const label = wrapper.querySelector("[data-region='mr-status-label']");
		if (label) label.textContent = this.get_status_label(this.active_bucket);
		wrapper.querySelectorAll("[data-mr-status-option]").forEach((option) => {
			const selected = option.dataset.value === this.active_bucket;
			option.classList.toggle("is-selected", selected);
			option.setAttribute("aria-selected", String(selected));
		});
	}

	hide_status_filter() {
		const wrapper = this.parent.querySelector("[data-field='status']");
		const options = wrapper?.querySelector(".mobile-mr-select-options");
		if (options) options.hidden = true;
		wrapper?.querySelector(".mobile-mr-select-trigger")?.setAttribute("aria-expanded", "false");
	}

	refresh({ append = false } = {}) {
		const sequence = ++this.request_sequence;
		const search = this.parent.querySelector("[data-field='search']")?.value || "";
		const offset = append ? this.offset : 0;
		if (!append) this.render_loading();
		frappe.call({
			method: "mobile_operations.api.get_mobile_material_request_dashboard",
			args: { search, bucket: this.active_bucket, limit: this.page_size, offset },
			freeze: false,
			callback: (response) => {
				if (sequence !== this.request_sequence) return;
				const next_data = response.message || { summary: [], requests: [], total: 0, has_more: false };
				if (append && this.data) {
					this.data = {
						...this.data,
						...next_data,
						requests: [...(this.data.requests || []), ...(next_data.requests || [])],
					};
				} else {
					this.data = next_data;
				}
				this.offset = this.data.requests?.length || 0;
				this.render_dashboard();
			},
			error: () => {
				if (sequence === this.request_sequence) this.render_error();
			},
		});
	}

	render_loading() {
		this.parent.querySelector("[data-region='summary']").innerHTML = Array.from({ length: 5 }, () => "<div class='mobile-mr-skeleton'></div>").join("");
		this.parent.querySelector("[data-region='requests']").innerHTML = Array.from({ length: 3 }, () => "<div class='mobile-mr-skeleton'></div>").join("");
	}

	render_error() {
		this.parent.querySelector("[data-region='summary']").innerHTML = "";
		this.parent.querySelector("[data-region='requests']").innerHTML = `<div class="mobile-mr-error">${__("加载失败，请点击右上角重试")}</div>`;
	}

	render_dashboard() {
		if (!this.parent.querySelector("[data-region='summary']")) {
			this.render_shell();
			this.sync_status_filter();
		}
		this.render_summary();
		this.render_requests();
	}

	render_summary() {
		const summary = this.data?.summary || [];
		this.parent.querySelector("[data-region='summary']").innerHTML = summary.map((card) => `<button class="mobile-mr-summary-card${this.active_bucket === card.key ? " is-active" : ""}${card.tone ? ` is-${card.tone}` : ""}" data-bucket="${escape_attribute(card.key)}"><div class="mobile-mr-summary-value">${format_integer(card.count)}</div><div class="mobile-mr-summary-label">${escape_html(card.label)}</div></button>`).join("");
	}

	render_requests() {
		const all_requests = this.data?.requests || [];
		const requests = all_requests.filter((request) => this.matches_bucket(request, this.active_bucket));
		const total = Number(this.data?.total ?? requests.length);
		const list_count = this.parent.querySelector("[data-region='list-count']");
		if (list_count) {
			list_count.textContent = total > requests.length ? __("共 {0} 条，已加载 {1} 条", [total, requests.length]) : total ? __("{0} 条", [total]) : __("无记录");
		}
		const load_more = this.data?.has_more ? `<button class="mobile-mr-load-more" data-action="mr-load-more">${__("加载更多")}</button>` : "";
		this.parent.querySelector("[data-region='requests']").innerHTML = requests.length ? requests.map((request) => this.request_card(request)).join("") + load_more : `<div class="mobile-mr-empty">${__("当前筛选条件下没有物料需求")}</div>`;
	}

	matches_bucket(request, bucket) {
		if (bucket === "all") return true;
		if (bucket === "in_progress") return request.is_active;
		return request.primary_bucket === bucket;
	}

	request_card(request) {
		const progress = Math.max(0, Math.min(100, Number(request.progress || 0)));
		return `<article class="mobile-mr-request-card" data-open-request="${escape_attribute(request.name)}"><div class="mobile-mr-card-top"><div class="mobile-mr-card-number">${escape_html(request.request_no || request.name)}</div><span class="mobile-mr-status ${status_tone(request.primary_bucket)}">${escape_html(request.status_label)}</span></div><div class="mobile-mr-card-title">${escape_html(request.item_preview || request.title || __("暂无明细"))}</div><div class="mobile-mr-card-meta"><span>${escape_html(request.type_label || request.material_request_type || "-")}</span><span>${escape_html(request.source_label || request.request_source || "-")}</span><span>${escape_html(request.schedule_date || request.modified || "-")}</span></div><div class="mobile-mr-progress-label"><span>${__("处理进度")}</span><span>${progress}%</span></div><div class="mobile-mr-progress"><div class="mobile-mr-progress-bar" style="width:${progress}%"></div></div><div class="mobile-mr-card-footer"><div class="mobile-mr-card-warehouse"><i class="fa fa-map-marker mr-1"></i>${escape_html(request.warehouse || __("未设置仓库"))}</div><button class="mobile-mr-view-button" data-action="mr-view" data-name="${escape_attribute(request.name)}">${__("查看")}</button></div></article>`;
	}

	open_detail(name) {
		this.parent.innerHTML = `<div class="mobile-mr-loading">${__("正在加载物料需求...")}</div>`;
		frappe.call({
			method: "mobile_operations.api.get_mobile_material_request_detail",
			args: { name },
			freeze: false,
			callback: (response) => this.render_detail(response.message),
			error: () => this.parent.innerHTML = `<div class="mobile-mr-error">${__("物料需求加载失败")}</div>`,
		});
	}

	render_detail(detail) {
		if (!detail) {
			this.parent.innerHTML = `<div class="mobile-mr-error">${__("未找到物料需求")}</div>`;
			return;
		}
		this.active_detail = detail;
		const item_html = (detail.items || []).map((item) => `<div class="mobile-mr-detail-item"><div class="mobile-mr-detail-item-top"><div><h4>${escape_html(item.item_code || "-")}</h4><p>${escape_html(item.item_name || item.description || "")}</p></div><div class="mobile-mr-qty"><strong>${format_number(item.remaining_qty)}</strong><span>${escape_html(item.uom || "")} ${__("剩余")}</span></div></div><div class="mobile-mr-detail-item-meta"><span>${__("需求")}: ${format_number(item.qty)} ${escape_html(item.uom || "")}</span><span>${__("已发料")}: ${format_number(item.issued_qty)}</span><span>${__("仓库")}: ${escape_html(item.warehouse || "-")}</span><span>${__("要求日期")}: ${escape_html(item.schedule_date || "-")}</span></div></div>`).join("");
		const warehouse_fields = detail.warehouse_mode === "issue"
			? detail_field(__("发料仓库"), detail.source_warehouse || "-")
			: `${detail_field(__("目标仓库"), detail.target_warehouse || "-")}${detail.warehouse_mode === "transfer" ? detail_field(__("来源仓库"), detail.source_warehouse || "-") : ""}`;
		const detail_action = Number(detail.docstatus) === 0
			? (detail.can_submit
				? `<button class="mobile-mr-detail-action primary" data-action="mr-submit" data-name="${escape_attribute(detail.name)}">${__("提交物料需求")}</button>`
				: `<div class="mobile-mr-detail-permission">${__("当前账号没有提交权限")}</div>`)
			: (detail.can_push_to_dlm
				? `<button class="mobile-mr-detail-action primary" data-action="mr-issue-push" data-name="${escape_attribute(detail.name)}">${__("发料并推送至DLM")}</button>`
				: (detail.can_create_material_movement
					? `<button class="mobile-mr-detail-action primary" data-action="mr-material-move" data-name="${escape_attribute(detail.name)}">${__("生成物料移动")}</button>`
					: `<div class="mobile-mr-detail-action-hint" role="status"><i class="fa fa-info-circle" aria-hidden="true"></i><span>${escape_html(detail.material_movement_hint || __("当前需求不能生成物料移动"))}</span></div>`));
		this.parent.innerHTML = `<div class="mobile-mr-detail"><div class="mobile-mr-detail-header"><button class="mobile-mr-back" data-action="mr-back" aria-label="${__("返回")}"><i class="fa fa-arrow-left"></i></button><div class="mobile-mr-detail-heading"><h2>${escape_html(detail.request_no || detail.name)}</h2><p>${escape_html(detail.status_label)} · ${escape_html(detail.source_label || detail.request_source || "-")} · ${escape_html(detail.material_request_type || "-")}</p></div></div><div class="mobile-mr-detail-summary"><div class="mobile-mr-detail-summary-grid">${detail_field(__("需求标题"), detail.title || "-")}${detail_field(__('要求日期'), detail.schedule_date || "-")}${warehouse_fields}${detail_field(__('处理进度'), `${format_number(detail.progress)}%`)}${detail_field(__('物料行数'), `${format_integer(detail.item_count)} ${__('行')}`)}</div></div><div class="mobile-mr-section-title"><h3>${__("物料明细")}</h3></div>${item_html || `<div class="mobile-mr-empty">${__("暂无物料明细")}</div>`}<div class="mobile-mr-detail-actions">${detail_action}<button class="mobile-mr-detail-action" data-action="mr-back">${__("返回列表")}</button></div><div class="mobile-mr-detail-status" data-region="detail-status" role="alert"></div></div>`;
	}

	submit_detail(name) {
		const button = Array.from(this.parent.querySelectorAll("[data-action='mr-submit']")).find((item) => item.dataset.name === name);
		if (button) button.disabled = true;
		this.set_detail_status(__("正在提交..."), "loading");
		frappe.call({
			method: "mobile_operations.api.submit_mobile_material_request",
			args: { name },
			freeze: false,
			callback: (response) => {
				if (response.exc) {
					if (button) button.disabled = false;
					this.set_detail_status(__("提交失败，请检查必填信息和权限"), "error");
					return;
				}
				this.open_detail(name);
			},
			error: () => {
				if (button) button.disabled = false;
				this.set_detail_status(__("提交失败，请检查必填信息和权限"), "error");
			},
		});
	}

	set_detail_status(message, tone) {
		const status = this.parent.querySelector("[data-region='detail-status']");
		if (status) {
			status.textContent = message || "";
			status.className = `mobile-mr-detail-status${tone ? ` is-${tone}` : ""}`;
		}
	}

	issue_and_push_detail(name) {
		this.open_issue_detail(name, "push");
	}

	create_material_movement_detail(name) {
		this.open_issue_detail(name, "manual");
	}

	open_issue_detail(name, mode) {
		this.set_detail_status(mode === "push" ? __("正在加载发料明细...") : __("正在加载物料移动明细..."), "loading");
		frappe.call({
			method: "mobile_operations.api.get_mobile_material_request_issue_options",
			args: { material_request_name: name },
			freeze: false,
			callback: (response) => {
				if (response.exc) {
					this.set_detail_status(__("发料明细加载失败，请检查库存权限"), "error");
					return;
				}
				const options = response.message || {};
				if (!options.items?.length) {
					this.set_detail_status(__("没有可发料的明细"), "error");
					return;
				}
				this.render_issue_dialog(name, options, mode);
			},
			error: () => this.set_detail_status(__("发料明细加载失败，请检查库存权限"), "error"),
		});
	}

	render_issue_dialog(name, options, mode) {
		this.close_issue_dialog();
		const item_html = options.items.map((item, item_index) => {
			const warehouse_options = [...(item.warehouses || [])].sort((first, second) => Number(second.actual_qty || 0) - Number(first.actual_qty || 0));
			const warehouse_html = warehouse_options.map((warehouse) => `<option value="${escape_attribute(warehouse.name)}"${warehouse.name === item.source_warehouse ? " selected" : ""}>${escape_html(warehouse_display_name(warehouse))} · ${format_number(warehouse.actual_qty)} ${escape_html(item.stock_uom || item.uom || "")}</option>`).join("");
			return `<div class="mobile-mr-issue-row" data-issue-index="${item_index}"><div class="mobile-mr-issue-item"><strong>${escape_html(item.item_code)}</strong><span>${escape_html(item.item_name || "")}</span><small>${__("剩余")}: ${format_number(item.remaining_qty)} ${escape_html(item.uom || "")}</small></div><div class="mobile-mr-issue-fields"><label>${__("本次发料数量")}<input type="number" min="0.0001" max="${escape_attribute(item.remaining_qty)}" step="any" data-issue-qty value="${escape_attribute(item.remaining_qty)}"></label><span class="mobile-mr-issue-uom">${escape_html(item.uom || "")}</span></div><label class="mobile-mr-issue-warehouse">${__("发料仓库")}<select data-issue-warehouse>${warehouse_html || `<option value="">${__("没有可选仓库")}</option>`}</select></label><div class="mobile-mr-issue-stock">${__("当前库存")}: <strong data-issue-actual>${format_number(this.get_issue_actual_qty(item, item.source_warehouse))}</strong> ${escape_html(item.stock_uom || item.uom || "")}</div></div>`;
		}).join("");
		const is_push = mode === "push";
		const title = is_push ? __("发料并推送至DLM") : __("生成物料移动");
		const subtitle = is_push ? __("请确认数量和发料仓库") : __("请确认数量和发料仓库，生成后可继续提交物料移动");
		const confirm_label = is_push ? __("确认发料并推送") : __("生成物料移动");
		this.parent.insertAdjacentHTML("beforeend", `<div class="mobile-mr-issue-overlay" data-region="issue-dialog"><div class="mobile-mr-issue-sheet"><div class="mobile-mr-issue-heading"><div><h3>${title}</h3><p>${subtitle}</p></div><button type="button" data-action="mr-issue-cancel" aria-label="${__("关闭")}"><i class="fa fa-close"></i></button></div><div class="mobile-mr-issue-items">${item_html}</div><div class="mobile-mr-issue-status" data-region="issue-status" role="alert"></div><div class="mobile-mr-issue-actions"><button type="button" data-action="mr-issue-cancel">${__("取消")}</button><button type="button" class="primary" data-action="mr-issue-confirm" data-name="${escape_attribute(name)}">${confirm_label}</button></div></div></div>`);
		this.current_issue_options = options;
		this.current_issue_mode = mode;
	}

	get_issue_actual_qty(item, warehouse_name) {
		return (item.warehouses || []).find((warehouse) => warehouse.name === warehouse_name)?.actual_qty || 0;
	}

	close_issue_dialog() {
		this.parent.querySelector("[data-region='issue-dialog']")?.remove();
		this.current_issue_options = null;
		this.current_issue_mode = null;
	}

	set_issue_dialog_status(message, tone) {
		const status = this.parent.querySelector("[data-region='issue-status']");
		if (status) {
			status.textContent = message || "";
			status.className = `mobile-mr-issue-status${tone ? ` is-${tone}` : ""}`;
		}
	}

	confirm_issue_detail() {
		const options = this.current_issue_options;
		if (!options) return;
		const rows = [];
		const errors = [];
		this.parent.querySelectorAll("[data-region='issue-dialog'] [data-issue-index]").forEach((row_element) => {
			const item = options.items[Number(row_element.dataset.issueIndex)];
			if (!item) return;
			const qty = Number(row_element.querySelector("[data-issue-qty]")?.value || 0);
			const source_warehouse = row_element.querySelector("[data-issue-warehouse]")?.value || "";
			const actual_qty = Number(this.get_issue_actual_qty(item, source_warehouse));
			if (!source_warehouse) errors.push(`${item.item_code}: ${__("请选择发料仓库")}`);
			else if (qty <= 0 || qty > Number(item.remaining_qty)) errors.push(`${item.item_code}: ${__("发料数量不能超过剩余数量")}`);
			else if (qty * Number(item.conversion_factor || 1) > actual_qty) errors.push(`${item.item_code}: ${__("库存不足，可用库存为")} ${format_number(actual_qty)} ${item.stock_uom || item.uom || ""}`);
			rows.push({ material_request_item: item.material_request_item, item_code: item.item_code, item_name: item.item_name, uom: item.uom || item.stock_uom, qty, s_warehouse: source_warehouse, t_warehouse: item.target_warehouse });
		});
		if (errors.length) {
			this.set_issue_dialog_status(errors.join("；"), "error");
			return;
		}
		const name = this.parent.querySelector("[data-action='mr-issue-confirm']")?.dataset.name;
		this.call_issue_detail(name, rows, this.current_issue_mode || "push");
	}

	call_issue_detail(name, rows, mode) {
		const button = this.parent.querySelector("[data-action='mr-issue-confirm']");
		if (button) button.disabled = true;
		const is_push = mode === "push";
		this.set_issue_dialog_status(is_push ? __("正在创建物料移动并推送至 DLM，请稍候...") : __("正在生成物料移动，请稍候..."), "loading");
		frappe.call({
			method: is_push ? "mobile_operations.api.issue_and_push_mobile_material_request" : "mobile_operations.api.create_mobile_material_request_stock_entry",
			args: { material_request_name: name, items: JSON.stringify(rows) },
			freeze: false,
			callback: (response) => {
				if (response.exc) {
					if (button) button.disabled = false;
					this.set_issue_dialog_status(is_push ? __("发料或推送失败，请检查库存、权限和 DLM 配置") : __("物料移动生成失败，请检查库存、权限和仓库设置"), "error");
					return;
				}
				const result = response.message || {};
				this.close_issue_dialog();
				this.set_detail_status(result.message || (is_push ? __("发料并推送完成") : __("物料移动草稿已生成")), result.status === "success" ? "success" : "error");
				window.setTimeout(() => {
					if (result.stock_entry) this.app.go(`/mobile/stock-entry/${encodeURIComponent(result.stock_entry)}`);
					else this.open_detail(name);
				}, 900);
			},
			error: () => {
				if (button) button.disabled = false;
				this.set_issue_dialog_status(is_push ? __("发料或推送失败，请检查库存、权限和 DLM 配置") : __("物料移动生成失败，请检查库存、权限和仓库设置"), "error");
			},
		});
	}
}

class MobileStockEntryView {
	constructor(parent, app) {
		this.parent = parent;
		this.app = app;
		this.request_sequence = 0;
		this.page_size = 40;
		this.offset = 0;
		this.status = "all";
		this.search_timer = null;
		this.selected_name = this.get_route_name();
		this.render_shell();
		this.bind_events();
		if (this.selected_name) this.open_detail(this.selected_name);
		else this.refresh();
	}

	get_route_name() {
		const prefix = "/mobile/stock-entry/";
		return this.app.route.startsWith(prefix) ? decodeURIComponent(this.app.route.slice(prefix.length)) : "";
	}

	render_shell() {
		this.parent.innerHTML = `
			<div class="mobile-se-page">
				<div class="mobile-se-heading">
					<div><h2>${__("物料移动")}</h2><p>${__("库存转移和发料单据")}</p></div>
					<button class="mobile-se-refresh" data-action="se-refresh" aria-label="${__("刷新")}"><i class="fa fa-refresh"></i></button>
				</div>
				<div class="mobile-se-summary" data-region="summary"></div>
				<div class="mobile-se-section-title"><h3>${__("物料移动单")}</h3><span data-region="list-count"></span></div>
				<div class="mobile-se-filter">
					<div class="mobile-se-search"><i class="fa fa-search"></i><input type="search" data-field="search" placeholder="${__("搜索单号、物料或仓库")}" autocomplete="off"></div>
					<div class="mobile-se-custom-select" data-field="status" data-select-value="all">
						<button type="button" class="mobile-se-select-trigger" data-action="se-toggle-status" aria-haspopup="listbox" aria-expanded="false" aria-label="${__("状态筛选")}"><span data-region="se-status-label">${__("全部状态")}</span><i class="fa fa-chevron-down"></i></button>
						<div class="mobile-se-select-options" data-region="se-status-options" role="listbox" hidden>
							<button type="button" class="mobile-se-select-option is-selected" data-se-status-option data-value="all" role="option"><span>${__("全部状态")}</span></button>
							<button type="button" class="mobile-se-select-option" data-se-status-option data-value="draft" role="option"><span>${__("草稿")}</span></button>
							<button type="button" class="mobile-se-select-option" data-se-status-option data-value="submitted" role="option"><span>${__("已提交")}</span></button>
						</div>
					</div>
				</div>
				<div class="mobile-se-list" data-region="entries"></div>
			</div>
		`;
	}

	bind_events() {
		this.parent.addEventListener("click", (event) => {
			const status_option = event.target.closest("[data-se-status-option]");
			if (status_option) {
				this.set_status_filter(status_option.dataset.value || "all");
				return;
			}
			const target = event.target.closest("[data-action]");
			const action = target?.dataset.action;
			if (action === "se-toggle-status") {
				this.toggle_status_filter();
				return;
			}
			if (action === "se-refresh") this.refresh();
			if (action === "se-back") this.go_list();
			if (action === "se-load-more") this.refresh({ append: true });
			if (action === "se-view") this.open_detail(target.dataset.name);
			if (action === "se-submit") this.submit_detail(target.dataset.name);
			if (action === "se-push") this.push_detail(target.dataset.name);
			const status_target = event.target.closest("[data-se-status]");
			if (status_target?.dataset.seStatus) {
				this.set_status_filter(status_target.dataset.seStatus, false);
				this.offset = 0;
				this.refresh();
			}
			if (!event.target.closest(".mobile-se-custom-select")) this.hide_status_filter();
			const open_name = event.target.closest("[data-open-stock-entry]")?.dataset.openStockEntry;
			if (open_name && !event.target.closest("button")) this.open_detail(open_name);
		});
		this.parent.addEventListener("input", (event) => {
			if (!event.target.matches("[data-field='search']")) return;
			this.offset = 0;
			window.clearTimeout(this.search_timer);
			this.search_timer = window.setTimeout(() => this.refresh(), 280);
		});
		this.sync_status_filter();
	}

	get_status_label(status) {
		return {
			all: __("全部状态"),
			draft: __("草稿"),
			submitted: __("已提交"),
		}[status] || __("全部状态");
	}

	toggle_status_filter() {
		const wrapper = this.parent.querySelector("[data-field='status']");
		const options = wrapper?.querySelector(".mobile-se-select-options");
		if (!wrapper || !options) return;
		const is_open = !options.hidden;
		this.hide_status_filter();
		if (!is_open) {
			options.hidden = false;
			wrapper.querySelector(".mobile-se-select-trigger")?.setAttribute("aria-expanded", "true");
		}
	}

	set_status_filter(status, should_refresh = true) {
		this.status = ["all", "draft", "submitted"].includes(status) ? status : "all";
		this.sync_status_filter();
		this.hide_status_filter();
		if (should_refresh) {
			this.offset = 0;
			this.refresh();
		}
	}

	sync_status_filter() {
		const wrapper = this.parent.querySelector("[data-field='status']");
		if (!wrapper) return;
		wrapper.dataset.selectValue = this.status;
		const label = wrapper.querySelector("[data-region='se-status-label']");
		if (label) label.textContent = this.get_status_label(this.status);
		wrapper.querySelectorAll("[data-se-status-option]").forEach((option) => {
			const selected = option.dataset.value === this.status;
			option.classList.toggle("is-selected", selected);
			option.setAttribute("aria-selected", String(selected));
		});
	}

	hide_status_filter() {
		const wrapper = this.parent.querySelector("[data-field='status']");
		const options = wrapper?.querySelector(".mobile-se-select-options");
		if (options) options.hidden = true;
		wrapper?.querySelector(".mobile-se-select-trigger")?.setAttribute("aria-expanded", "false");
	}

	refresh({ append = false } = {}) {
		if (this.selected_name && !append) {
			this.open_detail(this.selected_name);
			return;
		}
		const sequence = ++this.request_sequence;
		const search = this.parent.querySelector("[data-field='search']")?.value || "";
		const offset = append ? this.offset : 0;
		if (!append) this.render_loading();
		frappe.call({
			method: "mobile_operations.api.get_mobile_stock_entry_dashboard",
			args: { search, status: this.status, limit: this.page_size, offset },
			freeze: false,
			callback: (response) => {
				if (sequence !== this.request_sequence) return;
				const next_data = response.message || { summary: [], entries: [], total: 0, has_more: false };
				if (append && this.data) {
					this.data = { ...this.data, ...next_data, entries: [...(this.data.entries || []), ...(next_data.entries || [])] };
				} else {
					this.data = next_data;
				}
				this.offset = this.data.entries?.length || 0;
				this.selected_name = "";
				this.render_dashboard();
			},
			error: () => {
				if (sequence === this.request_sequence) this.render_error();
			},
		});
	}

	render_loading() {
		this.parent.querySelector("[data-region='summary']").innerHTML = Array.from({ length: 3 }, () => "<div class='mobile-se-skeleton'></div>").join("");
		this.parent.querySelector("[data-region='entries']").innerHTML = Array.from({ length: 3 }, () => "<div class='mobile-se-skeleton mobile-se-skeleton-card'></div>").join("");
	}

	render_error() {
		this.parent.querySelector("[data-region='summary']").innerHTML = "";
		this.parent.querySelector("[data-region='entries']").innerHTML = `<div class="mobile-se-error">${__("物料移动加载失败，请点击右上角重试")}</div>`;
	}

	render_dashboard() {
		this.render_summary();
		this.render_entries();
	}

	render_summary() {
		const summary = this.data?.summary || [];
		this.parent.querySelector("[data-region='summary']").innerHTML = summary.map((card) => {
			const is_filter = ["all", "draft", "submitted"].includes(card.key);
			const tag = is_filter ? "button" : "div";
			const attributes = is_filter ? ` data-se-status="${escape_attribute(card.key)}"` : "";
			return `<${tag} class="mobile-se-summary-card${this.status === card.key ? " is-active" : ""}${card.tone ? ` is-${card.tone}` : ""}"${attributes}><strong>${format_integer(card.count)}</strong><span>${escape_html(card.label)}</span></${tag}>`;
		}).join("");
	}

	render_entries() {
		const entries = this.data?.entries || [];
		const count = this.parent.querySelector("[data-region='list-count']");
		if (count) count.textContent = this.data?.total ? __(`{0} 条`, [this.data.total]) : __("无记录");
		const load_more = this.data?.has_more ? `<button class="mobile-se-load-more" data-action="se-load-more">${__("加载更多")}</button>` : "";
		this.parent.querySelector("[data-region='entries']").innerHTML = entries.length ? entries.map((entry) => this.entry_card(entry)).join("") + load_more : `<div class="mobile-se-empty">${__("当前筛选条件下没有物料移动")}</div>`;
	}

	entry_card(entry) {
		const warehouse = entry.to_warehouse || entry.from_warehouse || __("未设置仓库");
		return `<article class="mobile-se-card" data-open-stock-entry="${escape_attribute(entry.name)}"><div class="mobile-se-card-top"><div class="mobile-se-card-number">${escape_html(entry.entry_no || entry.name)}</div><span class="mobile-se-status ${stock_entry_status_tone(entry.status)}">${escape_html(entry.status_label)}</span></div><div class="mobile-se-card-title">${escape_html(entry.item_preview || entry.type_label || __("暂无物料明细"))}</div><div class="mobile-se-card-meta"><span>${escape_html(entry.type_label || entry.stock_entry_type || "-")}</span><span>${escape_html(entry.source_label || "-")}</span><span>${escape_html(entry.posting_date || entry.modified || "-")}</span></div><div class="mobile-se-card-warehouse"><i class="fa fa-map-marker"></i>${escape_html(warehouse)}</div><div class="mobile-se-card-footer"><span>${format_integer(entry.item_count)} ${__("行")}</span><button class="mobile-se-view" data-action="se-view" data-name="${escape_attribute(entry.name)}">${__("查看")}</button></div></article>`;
	}

	open_detail(name) {
		if (!name) return;
		this.selected_name = name;
		if (this.app.route !== `/mobile/stock-entry/${encodeURIComponent(name)}`) {
			window.history.pushState({}, "", `/mobile/stock-entry/${encodeURIComponent(name)}`);
			this.app.route = `/mobile/stock-entry/${encodeURIComponent(name)}`;
		}
		const sequence = ++this.request_sequence;
		this.parent.innerHTML = `<div class="mobile-se-loading">${__("正在加载物料移动明细...")}</div>`;
		frappe.call({
			method: "mobile_operations.api.get_mobile_stock_entry_detail",
			args: { name },
			freeze: false,
			callback: (response) => {
				if (sequence !== this.request_sequence) return;
				const detail = response.message;
				if (!detail) return this.render_detail_error();
				this.detail = detail;
				this.render_detail(detail);
			},
			error: () => {
				if (sequence === this.request_sequence) this.render_detail_error();
			},
		});
	}

	render_detail_error() {
		this.parent.innerHTML = `<div class="mobile-se-error">${__("未找到物料移动")}</div><button class="mobile-se-back-button" data-action="se-back">${__("返回列表")}</button>`;
	}

	render_detail(detail) {
		const item_html = (detail.items || []).map((item) => `<div class="mobile-se-item"><div class="mobile-se-item-top"><div><strong>${escape_html(item.item_code || "-")}</strong><span>${escape_html(item.item_name || item.description || "")}</span></div><div class="mobile-se-item-qty"><b>${format_number(item.qty)}</b><small>${escape_html(item.uom || item.stock_uom || "")}</small></div></div><div class="mobile-se-item-meta"><span>${__("发料仓库")}: ${escape_html(item.source_warehouse || "-")}</span><span>${__("目标仓库")}: ${escape_html(item.target_warehouse || "-")}</span><span>${__("需求")}: ${escape_html(item.material_request || "-")}</span></div></div>`).join("");
		let action_html = `<div class="mobile-se-hint"><i class="fa fa-info-circle"></i>${__("当前账号没有可执行的操作")}</div>`;
		if (detail.docstatus === 0) {
			action_html = detail.can_submit
				? `<button class="mobile-se-action primary" data-action="se-submit" data-name="${escape_attribute(detail.name)}">${__("提交物料移动")}</button>`
				: `<div class="mobile-se-hint">${__("当前账号没有提交物料移动的权限")}</div>`;
		} else if (detail.can_push_to_dlm) {
			action_html = `<button class="mobile-se-action primary" data-action="se-push" data-name="${escape_attribute(detail.name)}">${__("推送至DLM")}</button>`;
		} else if (detail.docstatus === 1 && detail.request_source !== "MES") {
			action_html = `<div class="mobile-se-hint is-success"><i class="fa fa-check-circle"></i>${__("手动创建的物料移动无需推送至DLM")}</div>`;
		} else if (detail.mes_status === "Pushed") {
			action_html = `<div class="mobile-se-hint is-success"><i class="fa fa-check-circle"></i>${__("该物料移动已推送至DLM")}</div>`;
		}
		this.parent.innerHTML = `<div class="mobile-se-detail"><div class="mobile-se-detail-heading"><button class="mobile-se-back" data-action="se-back" aria-label="${__("返回")}"><i class="fa fa-arrow-left"></i></button><div><h2>${escape_html(detail.entry_no || detail.name)}</h2><p>${escape_html(detail.status_label)} · ${escape_html(detail.source_label || "-")} · ${escape_html(detail.type_label || detail.stock_entry_type || "-")}</p></div></div><div class="mobile-se-detail-summary"><div class="mobile-se-detail-grid">${detail_field(__("单据编号"), detail.name)}${detail_field(__("记账日期"), detail.posting_date || "-")}${detail_field(__("公司"), detail.company || "-")}${detail_field(__("发料仓库"), detail.from_warehouse || "-")}${detail_field(__("目标仓库"), detail.to_warehouse || "-")}${detail_field(__("关联物料需求"), (detail.material_requests || []).join("、") || "-")}</div></div><div class="mobile-se-section-title"><h3>${__("物料明细")}</h3><span>${format_integer((detail.items || []).length)} ${__("行")}</span></div><div class="mobile-se-items">${item_html || `<div class="mobile-se-empty">${__("暂无物料明细")}</div>`}</div><div class="mobile-se-actions">${action_html}<button class="mobile-se-action" data-action="se-back">${__("返回列表")}</button></div><div class="mobile-se-action-status" data-region="stock-entry-status" role="alert"></div></div>`;
	}

	go_list() {
		window.history.pushState({}, "", "/mobile/stock-entry");
		this.app.route = "/mobile/stock-entry";
		this.selected_name = "";
		this.render_shell();
		this.refresh();
	}

	submit_detail(name) {
		this.call_detail_action("mobile_operations.api.submit_mobile_stock_entry", name, __("正在提交物料移动..."), __("物料移动已提交"));
	}

	push_detail(name) {
		this.call_detail_action("mobile_operations.api.push_mobile_stock_entry_to_dlm", name, __("正在推送至 DLM，请稍候..."), __("物料移动已推送至 DLM"));
	}

	call_detail_action(method, name, loading_message, success_message) {
		const status = this.parent.querySelector("[data-region='stock-entry-status']");
		if (status) {
			status.textContent = loading_message;
			status.className = "mobile-se-action-status is-loading";
		}
		this.parent.querySelectorAll("[data-action='se-submit'], [data-action='se-push']").forEach((button) => { button.disabled = true; });
		frappe.call({
			method,
			args: { name },
			freeze: false,
			callback: (response) => {
				if (response.exc) return this.set_action_status(__("操作失败，请稍后重试"), "error");
				this.set_action_status(response.message?.message || success_message, "success");
				window.setTimeout(() => this.open_detail(name), 700);
			},
			error: () => this.set_action_status(__("操作失败，请稍后重试"), "error"),
		});
	}

	set_action_status(message, tone) {
		const status = this.parent.querySelector("[data-region='stock-entry-status']");
		if (status) {
			status.textContent = message || "";
			status.className = `mobile-se-action-status${tone ? ` is-${tone}` : ""}`;
		}
		this.parent.querySelectorAll("[data-action='se-submit'], [data-action='se-push']").forEach((button) => { button.disabled = false; });
	}
}

class MobileMaterialRequestCreateView {
	constructor(parent, app) {
		this.parent = parent;
		this.app = app;
		this.options = { types: [], companies: [], warehouses: [] };
		this.item_results = {};
		this.item_search_timers = {};
		this.item_search_sequences = {};
		this.form = {
			material_request_type: "Material Issue",
			company: "",
			transaction_date: "",
			schedule_date: "",
			set_warehouse: "",
			set_from_warehouse: "",
			items: [this.empty_item()],
		};
		this.render_shell();
		this.bind_events();
		this.load_options();
	}

	empty_item() {
		return { item_code: "", item_name: "", search: "", qty: "", uom: "", stock_uom: "" };
	}

	render_shell() {
		this.parent.innerHTML = `
			<div class="mobile-mr-create-page">
				<div class="mobile-mr-create-heading">
					<button class="mobile-mr-create-back" data-action="mr-create-back" aria-label="${__("返回")}"><i class="fa fa-arrow-left"></i></button>
					<div><h2>${__("新建物料需求")}</h2><p>${__("现场快速创建物料需求")}</p></div>
				</div>
				<section class="mobile-mr-create-card">
					<div class="mobile-mr-create-card-title">${__("基本信息")}</div>
					<div class="mobile-mr-field">
						<span class="mobile-mr-field-label">${__("需求类型")}</span>
						<div class="mobile-mr-type-picker" data-region="material-request-type-picker">
							<button class="mobile-mr-select-trigger" type="button" data-action="mr-create-toggle-type" aria-haspopup="listbox" aria-expanded="false"><span data-region="material-request-type-label"></span><i class="fa fa-chevron-down" aria-hidden="true"></i></button>
							<div class="mobile-mr-select-menu" data-region="material-request-type-options" role="listbox" hidden></div>
							<select data-field="material_request_type" hidden tabindex="-1" aria-hidden="true"></select>
						</div>
					</div>
					<div class="mobile-mr-create-two-columns">
						<label class="mobile-mr-field">${__("公司")}<select data-field="company"></select></label>
						<label class="mobile-mr-field">${__("需求日期")}<input type="date" data-field="schedule_date"></label>
					</div>
					<div class="mobile-mr-field"><span data-region="set-warehouse-label">${__("目标仓库")}</span><div class="mobile-mr-warehouse-picker" data-region="warehouse-picker" data-warehouse-field="set_warehouse"><button class="mobile-mr-select-trigger" type="button" data-action="mr-create-toggle-warehouse" data-warehouse-field="set_warehouse" aria-haspopup="listbox" aria-expanded="false"><span data-region="warehouse-value"></span><i class="fa fa-chevron-down" aria-hidden="true"></i></button><div class="mobile-mr-select-menu mobile-mr-warehouse-menu" data-region="warehouse-options" role="listbox" hidden><div class="mobile-mr-warehouse-filters"><label class="mobile-mr-warehouse-filter"><span>${__("仓库名称")}</span><select data-warehouse-parent-filter aria-label="${__("仓库名称")}"></select></label><label class="mobile-mr-warehouse-filter"><span>${__("库位号")}</span><div class="mobile-mr-warehouse-location-input"><i class="fa fa-search" aria-hidden="true"></i><input type="search" data-warehouse-location-search placeholder="${__("输入库位号，如 P17R02T")}" autocomplete="off"></div></label></div><div data-region="warehouse-list"></div></div></div></div>
					<div class="mobile-mr-field" data-region="source-warehouse-field" hidden><span data-region="source-warehouse-label">${__("来源仓库")}</span><div class="mobile-mr-warehouse-picker" data-region="warehouse-picker" data-warehouse-field="set_from_warehouse"><button class="mobile-mr-select-trigger" type="button" data-action="mr-create-toggle-warehouse" data-warehouse-field="set_from_warehouse" aria-haspopup="listbox" aria-expanded="false"><span data-region="warehouse-value"></span><i class="fa fa-chevron-down" aria-hidden="true"></i></button><div class="mobile-mr-select-menu mobile-mr-warehouse-menu" data-region="warehouse-options" role="listbox" hidden><div class="mobile-mr-warehouse-filters"><label class="mobile-mr-warehouse-filter"><span>${__("仓库名称")}</span><select data-warehouse-parent-filter aria-label="${__("仓库名称")}"></select></label><label class="mobile-mr-warehouse-filter"><span>${__("库位号")}</span><div class="mobile-mr-warehouse-location-input"><i class="fa fa-search" aria-hidden="true"></i><input type="search" data-warehouse-location-search placeholder="${__("输入库位号，如 P17R02T")}" autocomplete="off"></div></label></div><div data-region="warehouse-list"></div></div></div></div>
				</section>

				<section class="mobile-mr-create-card">
					<div class="mobile-mr-create-card-heading"><div class="mobile-mr-create-card-title">${__("物料明细")}</div><span data-region="item-count"></span></div>
					<div class="mobile-mr-create-items" data-region="item-rows"></div>
					<button class="mobile-mr-add-item" data-action="mr-create-add-item"><i class="fa fa-plus"></i>${__("添加物料")}</button>
				</section>

				<div class="mobile-mr-create-status" data-region="create-status" role="alert"></div>
				<div class="mobile-mr-create-actions">
					<button class="mobile-mr-create-save" data-action="mr-create-save" data-mode="draft">${__("保存草稿")}</button>
					<button class="mobile-mr-create-submit" data-action="mr-create-save" data-mode="submit">${__("保存并提交")}</button>
				</div>
			</div>
		`;
		this.render_form_options();
		this.render_item_rows();
	}

	bind_events() {
		this.parent.addEventListener("click", (event) => {
			const event_target = event.target instanceof Element ? event.target : event.target.parentElement;
			if (!event_target) return;
			const action_target = event_target.closest("[data-action]");
			const action = action_target?.dataset.action;
			if (!action && !event_target.closest("[data-region='material-request-type-picker'], [data-region='warehouse-picker']")) {
				this.close_type_menu();
				this.close_warehouse_menus();
				return;
			}
			if (action === "mr-create-back") this.app.go("/mobile/material-request");
			if (action === "mr-create-toggle-type") {
				this.toggle_type_menu();
				return;
			}
			if (action === "mr-create-select-type") {
				this.form.material_request_type = action_target.dataset.value;
				this.close_type_menu();
				this.render_form_options();
				return;
			}
			if (action === "mr-create-toggle-warehouse") {
				event.preventDefault();
				this.toggle_warehouse_menu(action_target.closest("[data-region='warehouse-picker']"));
				return;
			}
			if (action === "mr-create-select-warehouse") {
				this.form[action_target.dataset.warehouseField] = action_target.dataset.value;
				this.close_warehouse_menus();
				this.render_form_options();
				return;
			}
			if (action === "mr-create-add-item") {
				this.form.items.push(this.empty_item());
				this.render_item_rows();
			}
			if (action === "mr-create-remove-item") {
				const index = Number(action_target.dataset.index);
				if (this.form.items.length === 1) this.form.items[0] = this.empty_item();
				else this.form.items.splice(index, 1);
				this.render_item_rows();
			}
			if (action === "mr-create-select-item") {
				this.select_item(Number(action_target.dataset.index), action_target.dataset.itemCode);
			}
			if (action === "mr-create-save") this.save(action_target.dataset.mode);
		});

		this.parent.addEventListener("input", (event) => {
			if (event.target.matches("[data-item-search]")) this.search_items(event.target);
			if (event.target.matches("[data-warehouse-location-search]")) {
				this.render_warehouse_options(event.target.closest("[data-region='warehouse-picker']"));
			}
			if (event.target.matches("[data-item-qty]")) {
				const row = this.form.items[Number(event.target.closest("[data-item-index]").dataset.itemIndex)];
				if (row) row.qty = event.target.value;
			}
			if (event.target.dataset.field && !event.target.matches("[data-item-search], [data-item-qty]")) {
				this.form[event.target.dataset.field] = event.target.value;
			}
		});

		this.parent.addEventListener("change", (event) => {
			if (event.target.matches("[data-warehouse-parent-filter]")) {
				this.render_warehouse_options(event.target.closest("[data-region='warehouse-picker']"));
				return;
			}
			const field = event.target.dataset.field;
			if (field) {
				this.form[field] = event.target.value;
				if (field === "material_request_type" || field === "company") this.render_form_options();
			}
		});
	}

	load_options() {
		frappe.call({
			method: "mobile_operations.api.get_mobile_material_request_form_options",
			freeze: false,
			callback: (response) => {
				this.options = response.message || this.options;
				this.form.company = this.form.company || this.options.default_company || "";
				this.form.schedule_date = this.form.schedule_date || this.options.today || "";
				this.render_form_options();
			},
			error: () => this.set_status(__("基础信息加载失败，请刷新后重试"), "error"),
		});
	}

	render_form_options() {
		const type_select = this.parent.querySelector("[data-field='material_request_type']");
		const type_label = this.parent.querySelector("[data-region='material-request-type-label']");
		const type_menu = this.parent.querySelector("[data-region='material-request-type-options']");
		const set_warehouse_label = this.parent.querySelector("[data-region='set-warehouse-label']");
		const source_warehouse_label = this.parent.querySelector("[data-region='source-warehouse-label']");
		const company_select = this.parent.querySelector("[data-field='company']");
		if (!type_select || !type_label || !type_menu || !set_warehouse_label || !source_warehouse_label || !company_select) return;

		const types = this.options.types?.length ? this.options.types : [
			{ value: "Material Issue", label: __("物料发料") },
			{ value: "Material Transfer", label: __("物料调拨") },
			{ value: "Purchase", label: __("采购需求") },
			{ value: "Manufacture", label: __("生产需求") },
		];
		if (!types.some((item) => item.value === this.form.material_request_type)) {
			this.form.material_request_type = types[0]?.value || "";
		}
		type_select.innerHTML = types.map((item) => `<option value="${escape_attribute(item.value)}">${escape_html(material_request_type_label(item.value) || item.label || item.value)}</option>`).join("");
		type_select.value = this.form.material_request_type;
		type_label.textContent = material_request_type_label(this.form.material_request_type) || this.form.material_request_type || __("请选择需求类型");
		type_menu.innerHTML = types.map((item) => {
			const selected = item.value === this.form.material_request_type;
			const label = material_request_type_label(item.value) || item.label || item.value;
			return `<button type="button" class="mobile-mr-select-option${selected ? " is-selected" : ""}" role="option" aria-selected="${selected}" data-action="mr-create-select-type" data-value="${escape_attribute(item.value)}">${escape_html(label)}</button>`;
		}).join("");

		company_select.innerHTML = this.select_options(this.options.companies || [], this.form.company, __("请选择公司"));
		company_select.value = this.form.company;

		const warehouses = (this.options.warehouses || []).filter((item) => !this.form.company || item.company === this.form.company);

		const date = this.parent.querySelector("[data-field='schedule_date']");
		if (date) date.value = this.form.schedule_date || "";
		const source_field = this.parent.querySelector("[data-region='source-warehouse-field']");
		const transfer_types = ["Material Transfer", "Material Transfer for Manufacture"];
		const issue_types = ["Material Issue", "Injection Molding Issuance"];
		const is_transfer = transfer_types.includes(this.form.material_request_type);
		const is_issue = issue_types.includes(this.form.material_request_type);
		set_warehouse_label.textContent = is_issue ? __("发料仓库") : __("目标仓库");
		source_warehouse_label.textContent = __("来源仓库");
		if (source_field) source_field.hidden = !is_transfer;
		if (!is_transfer) {
			this.form.set_from_warehouse = "";
		}
		this.render_warehouse_pickers(warehouses);
	}

	toggle_type_menu() {
		const picker = this.parent.querySelector("[data-region='material-request-type-picker']");
		const menu = this.parent.querySelector("[data-region='material-request-type-options']");
		const trigger = this.parent.querySelector("[data-action='mr-create-toggle-type']");
		if (!picker || !menu || !trigger) return;
		const open = menu.hidden;
		menu.hidden = !open;
		picker.classList.toggle("is-open", open);
		trigger.setAttribute("aria-expanded", String(open));
	}

	close_type_menu() {
		const picker = this.parent.querySelector("[data-region='material-request-type-picker']");
		const menu = this.parent.querySelector("[data-region='material-request-type-options']");
		const trigger = this.parent.querySelector("[data-action='mr-create-toggle-type']");
		if (menu) menu.hidden = true;
		if (picker) picker.classList.remove("is-open");
		if (trigger) trigger.setAttribute("aria-expanded", "false");
	}

	toggle_warehouse_menu(picker) {
		const menu = picker?.querySelector("[data-region='warehouse-options']");
		const trigger = picker?.querySelector("[data-action='mr-create-toggle-warehouse']");
		if (!picker || !menu || !trigger) return;
		const open = menu.hidden;
		this.close_type_menu();
		this.close_warehouse_menus();
		if (open) {
			this.render_warehouse_options(picker);
			menu.removeAttribute("hidden");
			picker.classList.add("is-open");
			picker.closest(".mobile-mr-create-card")?.classList.add("is-picker-open");
			trigger.setAttribute("aria-expanded", "true");
		}
	}

	close_warehouse_menus() {
		this.parent.querySelectorAll("[data-region='warehouse-picker']").forEach((picker) => {
			const menu = picker.querySelector("[data-region='warehouse-options']");
			const trigger = picker.querySelector("[data-action='mr-create-toggle-warehouse']");
			if (menu) menu.setAttribute("hidden", "");
			picker.classList.remove("is-open");
			picker.closest(".mobile-mr-create-card")?.classList.remove("is-picker-open");
			if (trigger) trigger.setAttribute("aria-expanded", "false");
		});
	}

	select_options(options, selected, placeholder) {
		return `<option value="">${escape_html(placeholder)}</option>` + options.map((item) => {
			const value = item.name || item.value;
			return `<option value="${escape_attribute(value)}">${escape_html(item.label || value)}</option>`;
		}).join("");
	}

	render_warehouse_pickers(warehouses) {
		this.parent.querySelectorAll("[data-region='warehouse-picker']").forEach((picker) => {
			const field = picker.dataset.warehouseField;
			const value = this.form[field] || "";
			const selected_warehouse = warehouses.find((item) => item.name === value);
			const value_region = picker.querySelector("[data-region='warehouse-value']");
			const placeholder = field === "set_from_warehouse" ? __("请选择来源仓库") : (this.form.material_request_type === "Material Issue" || this.form.material_request_type === "Injection Molding Issuance" ? __("请选择发料仓库") : __("请选择目标仓库"));
			if (value_region) value_region.textContent = selected_warehouse ? warehouse_display_name(selected_warehouse) : (value || placeholder);
			this.render_warehouse_options(picker, warehouses);
		});
	}

	render_warehouse_options(picker, warehouses = null) {
		if (!picker) return;
		const field = picker.dataset.warehouseField;
		const list = picker.querySelector("[data-region='warehouse-list']");
		const parent_filter = picker.querySelector("[data-warehouse-parent-filter]");
		const location_input = picker.querySelector("[data-warehouse-location-search]");
		if (!list) return;
		const available_warehouses = warehouses || (this.options.warehouses || []).filter((item) => !this.form.company || item.company === this.form.company);
		const parent_values = [...new Set(available_warehouses.map((item) => item.parent_warehouse).filter(Boolean))]
			.sort((first, second) => warehouse_parent_display_name({ parent_warehouse: first }).localeCompare(warehouse_parent_display_name({ parent_warehouse: second })));
		if (parent_filter) {
			const previous_parent = parent_filter.value;
			parent_filter.innerHTML = `<option value="">${escape_html(__("全部仓库名称"))}</option>` + parent_values.map((parent_name) => `<option value="${escape_attribute(parent_name)}">${escape_html(warehouse_parent_display_name({ parent_warehouse: parent_name }))}</option>`).join("");
			parent_filter.value = parent_values.includes(previous_parent) ? previous_parent : "";
		}
		const active_parent = parent_filter?.value || "";
		const location_query = (location_input?.value || "").trim().toLowerCase();
		const filtered = available_warehouses.filter((item) => {
			if (active_parent && item.parent_warehouse !== active_parent) return false;
			if (!location_query) return true;
			return [warehouse_location_code(item), warehouse_display_name(item)]
				.filter(Boolean)
				.some((value) => value.toLowerCase().includes(location_query));
		});
		const selected = this.form[field] || "";
		list.innerHTML = filtered.length ? filtered.map((item) => {
			const display_name = warehouse_display_name(item);
			const location_code = warehouse_location_code(item);
			const warehouse_label = display_name.slice(location_code.length).trim();
			const parent_name = active_parent ? "" : warehouse_parent_display_name(item);
			return `<button type="button" class="mobile-mr-warehouse-option${item.name === selected ? " is-selected" : ""}" role="option" aria-selected="${item.name === selected}" data-action="mr-create-select-warehouse" data-warehouse-field="${escape_attribute(field)}" data-value="${escape_attribute(item.name)}"><strong><b class="mobile-mr-warehouse-code">${escape_html(location_code)}</b>${warehouse_label ? ` ${escape_html(warehouse_label)}` : ""}</strong>${parent_name ? `<span>${escape_html(parent_name)}</span>` : ""}</button>`;
		}).join("") : `<div class="mobile-mr-warehouse-empty">${__("没有匹配的仓库")}</div>`;
	}

	render_item_rows() {
		const container = this.parent.querySelector("[data-region='item-rows']");
		if (!container) return;
		container.innerHTML = this.form.items.map((item, item_index) => `
			<div class="mobile-mr-create-item" data-item-index="${item_index}">
				<div class="mobile-mr-create-item-heading"><strong>${escape_html(__("物料"))} ${item_index + 1}</strong><button class="mobile-mr-remove-item" type="button" data-action="mr-create-remove-item" data-index="${item_index}" title="${escape_attribute(__("删除物料"))}"><i class="fa fa-trash-o" aria-hidden="true"></i><span class="mobile-sr-only">${escape_html(__("删除物料"))}</span></button></div>
				<div class="mobile-mr-item-search"><i class="fa fa-search"></i><input type="search" data-item-search value="${escape_attribute(item.search || item.item_code)}" placeholder="${__("搜索物料编码或名称")}" autocomplete="off"></div>
				<div class="mobile-mr-item-suggestions" data-item-suggestions="${item_index}"></div>
				<div class="mobile-mr-quantity-row"><label>${__("数量")}<input type="number" min="0.0001" step="any" data-item-qty value="${escape_attribute(item.qty)}" placeholder="0"></label><span class="mobile-mr-item-uom">${escape_html(item.uom || item.stock_uom || __("单位待自动带出"))}</span></div>
			</div>
		`).join("");
		const count = this.parent.querySelector("[data-region='item-count']");
		if (count) count.textContent = `${this.form.items.length} ${__("项")}`;
	}

	search_items(input) {
		const item_row = input.closest("[data-item-index]");
		const index = Number(item_row.dataset.itemIndex);
		const row = this.form.items[index];
		if (!row) return;
		row.search = input.value;
		row.item_code = "";
		row.item_name = "";
		row.uom = "";
		row.stock_uom = "";
		window.clearTimeout(this.item_search_timers[index]);
		this.item_results[index] = [];
		if (input.value.trim().length < 2) {
			this.render_item_suggestions(index, []);
			return;
		}
		const sequence = (this.item_search_sequences[index] || 0) + 1;
		this.item_search_sequences[index] = sequence;
		this.item_search_timers[index] = window.setTimeout(() => {
			frappe.call({
				method: "mobile_operations.api.search_mobile_material_request_items",
				args: { search: input.value.trim(), limit: 15 },
				freeze: false,
				callback: (response) => {
					if (sequence !== this.item_search_sequences[index]) return;
					this.item_results[index] = response.message || [];
					this.render_item_suggestions(index, this.item_results[index]);
				},
			});
		}, 250);
	}

	render_item_suggestions(item_index, items) {
		const container = this.parent.querySelector(`[data-item-suggestions="${item_index}"]`);
		if (!container) return;
		container.innerHTML = items.length ? items.map((item) => `<button type="button" class="mobile-mr-item-suggestion" data-action="mr-create-select-item" data-index="${item_index}" data-item-code="${escape_attribute(item.name)}"><strong>${escape_html(item.name)}</strong><span>${escape_html(item.item_name || "")} · ${escape_html(item.stock_uom || "")}</span></button>`).join("") : `<div class="mobile-mr-item-no-result">${__("没有找到匹配物料")}</div>`;
	}

	select_item(index, code) {
		const item = (this.item_results[index] || []).find((result) => result.name === code);
		if (!item || !this.form.items[index]) return;
		this.form.items[index] = {
			...this.form.items[index],
			item_code: item.name,
			item_name: item.item_name || "",
			search: item.name,
			uom: item.stock_uom || "",
			stock_uom: item.stock_uom || "",
		};
		this.render_item_rows();
	}

	save(mode) {
		const items = this.form.items.filter((item) => item.item_code);
		if (!this.form.company) return this.set_status(__("请选择公司"), "error");
		if (!this.form.material_request_type) return this.set_status(__("请选择需求类型"), "error");
		if (!this.form.schedule_date) return this.set_status(__("请选择需求日期"), "error");
		if (!items.length || items.some((item) => !item.qty || Number(item.qty) <= 0)) {
			return this.set_status(__("请为每项物料选择数量"), "error");
		}

		const payload = {
			material_request_type: this.form.material_request_type,
			company: this.form.company,
			transaction_date: this.form.transaction_date,
			schedule_date: this.form.schedule_date,
			set_warehouse: this.form.set_warehouse,
			set_from_warehouse: this.form.set_from_warehouse,
			items: items.map((item) => ({ item_code: item.item_code, qty: Number(item.qty), uom: item.uom, warehouse: this.form.set_warehouse, from_warehouse: this.form.set_from_warehouse })),
		};
		this.set_buttons_disabled(true);
		this.set_status(mode === "submit" ? __("正在提交...") : __("正在保存..."), "loading");
		frappe.call({
			method: "mobile_operations.api.create_mobile_material_request",
			args: { data: JSON.stringify(payload), submit: mode === "submit" ? 1 : 0 },
			freeze: false,
			callback: (response) => {
				if (response.exc) {
					this.set_buttons_disabled(false);
					this.set_status(__("保存失败，请检查必填信息和权限"), "error");
					return;
				}
				this.set_status(mode === "submit" ? __("物料需求已提交") : __("物料需求草稿已保存"), "success");
				this.app.go("/mobile/material-request");
			},
			error: () => {
				this.set_buttons_disabled(false);
				this.set_status(__("保存失败，请检查必填信息和权限"), "error");
			},
		});
	}

	set_buttons_disabled(disabled) {
		this.parent.querySelectorAll("[data-action='mr-create-save']").forEach((button) => {
			button.disabled = disabled;
		});
	}

	set_status(message, tone) {
		const status = this.parent.querySelector("[data-region='create-status']");
		if (status) {
			status.textContent = message || "";
			status.className = `mobile-mr-create-status${tone ? ` is-${tone}` : ""}`;
		}
	}
}

function normalize_mobile_route(path) {
	path = path.replace(/\/+$/, "") || "/mobile";
	return path === "/mobile/material-request/" ? "/mobile/material-request" : path;
}

function route_nav_key(route) {
	if (route.startsWith("/mobile/material-request")) return "inventory";
	if (route.startsWith("/mobile/inventory")) return "inventory";
	if (route.startsWith("/mobile/stock-entry")) return "inventory";
	if (route.startsWith("/mobile/production")) return "production";
	if (route.startsWith("/mobile/more")) return "more";
	return "home";
}

function route_title(route) {
	return { "/mobile/inventory": __("库存"), "/mobile/inventory/query": __("库存查询"), "/mobile/stock-entry": __("物料移动"), "/mobile/production": __("生产作业"), "/mobile/material-request/new": __("新建物料需求"), "/mobile/more": __("更多") }[route] || __("移动作业");
}

function material_request_type_label(value) {
	return {
		Purchase: __("采购需求"),
		"Material Transfer": __("物料调拨"),
		"Material Issue": __("物料发料"),
		"Material Transfer for Manufacture": __("生产领料"),
		Manufacture: __("生产需求"),
		Subcontracting: __("委外需求"),
		"Customer Provided": __("客户提供"),
		"Injection Molding Issuance": __("注塑发料"),
	}[value] || value;
}

function warehouse_display_name(warehouse) {
	const raw_name = String(warehouse?.warehouse_name || warehouse?.name || "").trim();
	const company_suffix = warehouse_company_suffix(warehouse);
	return company_suffix && raw_name.endsWith(company_suffix)
		? raw_name.slice(0, -company_suffix.length).trim()
		: raw_name;
}

function warehouse_location_code(warehouse) {
	return warehouse_display_name(warehouse).split(/\s+/)[0] || "";
}

function warehouse_company_suffix(warehouse) {
	const parent_name = String(warehouse?.parent_warehouse || "").trim();
	const separator_index = parent_name.lastIndexOf(" - ");
	return separator_index >= 0 ? parent_name.slice(separator_index) : "";
}

function warehouse_parent_display_name(warehouse) {
	const parent_name = String(warehouse?.parent_warehouse || "").trim();
	const company_suffix = warehouse_company_suffix(warehouse);
	return company_suffix && parent_name.endsWith(company_suffix)
		? parent_name.slice(0, -company_suffix.length).trim()
		: parent_name;
}

function detail_field(label, value) {
	return `<div class="mobile-mr-detail-field"><label>${escape_html(label)}</label><div>${escape_html(value)}</div></div>`;
}

function status_tone(bucket) {
	if (bucket === "completed") return "is-success";
	if (bucket === "exception") return "is-danger";
	if (bucket === "to_issue" || bucket === "transit") return "is-warning";
	return "";
}

function inventory_status_tone(status) {
	if (status === "negative") return "is-danger";
	if (status === "insufficient") return "is-warning";
	return "";
}

function escape_html(value) {
	return frappe.utils.escape_html(String(value ?? ""));
}

function escape_attribute(value) {
	return escape_html(value).replace(/`/g, "&#96;");
}

function format_integer(value) {
	return Number(value || 0).toLocaleString();
}

function format_number(value) {
	return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}
