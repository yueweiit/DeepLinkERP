/* Mobile Item master list, detail and create form. */
class MobileItemsView {
	constructor(parent, app) {
		this.parent = parent;
		this.app = app;
		this.sequence = 0;
		this.reference_sequence = 0;
		this.reference_results = {};
		this.filters = { search: "", status: "enabled", stock_kind: "all", item_group: "", ...app.item_filters };
		const path = app.route.slice("/mobile/inventory/items/".length);
		this.mode = app.route === "/mobile/inventory/items/new" ? "form"
			: app.route.startsWith("/mobile/inventory/items/") ? "detail" : "list";
		this.name = this.mode === "detail" ? decodeURIComponent(path) : "";
		this.parent.addEventListener("click", (event) => this.on_click(event));
		this.parent.addEventListener("input", (event) => this.on_input(event));
		this.parent.addEventListener("change", (event) => this.on_change(event));
		this.parent.addEventListener("focusin", (event) => this.on_focus(event));
		this.refresh();
	}

	async call(method, args = {}, type) {
		return new Promise((resolve, reject) => frappe.call({
			method: `mobile_operations.items.${method}`,
			args,
			type,
			freeze: false,
			callback: (response) => response.exc ? reject(response) : resolve(response.message),
			error: reject,
		}));
	}

	async refresh() {
		if (this.busy) return;
		if (this.mode === "form" && this.form) return;
		if (this.mode === "list") {
			this.render_list_shell();
			return this.load_list();
		}
		this.parent.innerHTML = `<div class="mobile-items-page"><div class="mobile-items-empty">${__("正在加载物料...")}</div></div>`;
		try {
			if (this.mode === "detail") {
				this.detail = await this.call("get_mobile_item_detail", { name: this.name });
				if (this.parent.isConnected) this.render_detail();
				return;
			}
			this.options = await this.call("get_mobile_item_form_options");
			if (!this.parent.isConnected) return;
			const defaults = this.options.defaults || {};
			this.form = {
				item_code: "", item_name: "", item_group: "", stock_uom: "",
				is_stock_item: defaults.is_stock_item ?? 1,
				is_purchase_item: defaults.is_purchase_item ?? 1,
				is_sales_item: defaults.is_sales_item ?? 1,
				description: "",
			};
			(this.options.custom_fields || []).forEach((fieldname) => this.form[fieldname] = "");
			this.render_form();
		} catch (error) {
			if (!this.parent.isConnected) return;
			this.parent.innerHTML = `<div class="mobile-items-page">${this.back_heading(__("物料档案"))}<div class="mobile-items-empty is-error">${escape_html(mobile_item_error(error))}</div><button class="mobile-items-button" data-item-action="retry">${__("重试")}</button></div>`;
		}
	}

	back_heading(title, subtitle = __("物料档案")) {
		return `<div class="mobile-items-heading"><button class="mobile-items-back" data-item-action="back" aria-label="${__("返回")}"><i class="fa fa-arrow-left"></i></button><div><h2>${escape_html(title)}</h2><p>${escape_html(subtitle)}</p></div></div>`;
	}

	render_list_shell() {
		this.parent.innerHTML = `<div class="mobile-items-page">
			<div class="mobile-items-heading"><div><h2>${__("物料档案")}</h2><p>${__("查找、查看和新增物料")}</p></div><button class="mobile-items-button primary" data-item-action="new" hidden><i class="fa fa-plus"></i> ${__("新增物料")}</button></div>
			<section class="mobile-items-filter-panel">
				<label class="mobile-items-search"><i class="fa fa-search"></i><input type="search" data-item-filter="search" value="${escape_attribute(this.filters.search)}" placeholder="${__("搜索编码、名称、规格或助记码")}" autocomplete="off"></label>
				<div class="mobile-items-filter-columns">
					<label>${__("状态")}<select data-item-filter="status"><option value="enabled">${__("启用")}</option><option value="all">${__("全部")}</option><option value="disabled">${__("停用")}</option></select></label>
					<label>${__("物料类型")}<select data-item-filter="stock_kind"><option value="all">${__("全部")}</option><option value="stock">${__("库存物料")}</option><option value="non_stock">${__("非库存物料")}</option></select></label>
				</div>
				<label class="mobile-items-reference">${__("物料组")}<input type="search" data-item-reference="list_group" value="${escape_attribute(this.filters.item_group)}" placeholder="${__("输入物料组后选择")}" autocomplete="off"><div class="mobile-items-suggestions" data-item-suggestions="list_group"></div></label>
			</section>
			<div class="mobile-items-section"><h3>${__("查询结果")}</h3><span data-item-count></span></div>
			<div data-item-list><div class="mobile-items-empty">${__("正在加载物料...")}</div></div>
			<div class="mobile-items-message" data-item-message role="alert"></div>
		</div>`;
		this.parent.querySelector('[data-item-filter="status"]').value = this.filters.status;
		this.parent.querySelector('[data-item-filter="stock_kind"]').value = this.filters.stock_kind;
	}

	async load_list({ append = false } = {}) {
		const sequence = ++this.sequence;
		const offset = append ? (this.entries || []).length : 0;
		const list = this.parent.querySelector("[data-item-list]");
		if (!append) list.innerHTML = `<div class="mobile-items-empty">${__("正在加载物料...")}</div>`;
		this.set_message("");
		try {
			const data = await this.call("get_mobile_item_list", { ...this.filters, limit: 20, offset });
			if (!list.isConnected || sequence !== this.sequence) return;
			this.entries = append ? [...(this.entries || []), ...(data.entries || [])] : (data.entries || []);
			this.total = data.total || 0;
			this.has_more = Boolean(data.has_more);
			this.parent.querySelector('[data-item-action="new"]').hidden = !data.can_create;
			this.render_list();
		} catch (error) {
			if (list.isConnected && sequence === this.sequence) {
				if (!append) list.innerHTML = `<div class="mobile-items-empty is-error">${escape_html(mobile_item_error(error))}</div>`;
				this.set_message(mobile_item_error(error), "error");
			}
		}
	}

	render_list() {
		const count = this.parent.querySelector("[data-item-count]");
		if (count) count.textContent = __(`{0} 条`, [this.total || 0]);
		const cards = (this.entries || []).map((item) => `<button class="mobile-items-card" data-item-action="open" data-name="${escape_attribute(item.name)}">
			<div class="mobile-items-card-top"><strong>${escape_html(item.name)}</strong><span class="mobile-items-badge ${item.disabled ? "is-disabled" : "is-active"}">${item.disabled ? __("停用") : __("启用")}</span></div>
			<h3>${escape_html(item.item_name || item.name)}</h3>
			${item.custom_specifications ? `<p>${escape_html(item.custom_specifications)}</p>` : ""}
			<div class="mobile-items-card-meta"><span>${escape_html(item.item_group || "-")}</span><span>${escape_html(item.stock_uom || "-")}</span><span>${item.is_stock_item ? __("库存物料") : __("非库存物料")}</span></div>
		</button>`).join("");
		const more = this.has_more ? `<button class="mobile-items-button mobile-items-load-more" data-item-action="load-more">${__("加载更多")}</button>` : "";
		this.parent.querySelector("[data-item-list]").innerHTML = cards || `<div class="mobile-items-empty">${__("没有找到匹配物料")}</div>`;
		this.parent.querySelector("[data-item-list]").insertAdjacentHTML("beforeend", more);
	}

	render_detail() {
		const item = this.detail;
		const optional = [
			["custom_mnemonic_code", __("助记码")], ["custom_sku", "SKU"],
			["custom_external_code", __("外部编码")], ["custom_item_classification", __("物料分类")],
			["custom_short_name", __("物料简称")], ["custom_item_short_name", __("MES 物料简称")],
			["custom_mes_issue_uom", __("MES 默认发料单位")],
		].filter(([fieldname]) => item[fieldname]);
		const optional_html = optional.map(([fieldname, label]) => `<div><span>${escape_html(label)}</span><strong>${escape_html(item[fieldname])}</strong></div>`).join("");
		this.parent.innerHTML = `<div class="mobile-items-page">
			${this.back_heading(item.item_name || item.name, item.name)}
			<section class="mobile-items-panel mobile-items-detail-main">
				<div class="mobile-items-detail-top"><strong>${escape_html(item.name)}</strong><span class="mobile-items-badge ${item.disabled ? "is-disabled" : "is-active"}">${item.disabled ? __("停用") : __("启用")}</span></div>
				${item.custom_specifications ? `<p class="mobile-items-specification">${escape_html(item.custom_specifications)}</p>` : ""}
				<div class="mobile-items-facts"><div><span>${__("物料组")}</span><strong>${escape_html(item.item_group || "-")}</strong></div><div><span>${__("库存单位")}</span><strong>${escape_html(item.stock_uom || "-")}</strong></div></div>
				<div class="mobile-items-properties"><span>${item.is_stock_item ? __("库存物料") : __("非库存物料")}</span><span>${item.is_purchase_item ? __("允许采购") : __("不允许采购")}</span><span>${item.is_sales_item ? __("允许销售") : __("不允许销售")}</span></div>
			</section>
			${optional_html ? `<section class="mobile-items-panel"><h3>${__("辅助资料")}</h3><div class="mobile-items-facts">${optional_html}</div></section>` : ""}
			${item.description ? `<section class="mobile-items-panel"><h3>${__("描述")}</h3><p class="mobile-items-description">${escape_html(item.description)}</p></section>` : ""}
			<div class="mobile-items-actions">${item.can_view_inventory ? `<button class="mobile-items-button primary" data-item-action="inventory"><i class="fa fa-search"></i> ${__("查看库存")}</button>` : ""}<a class="mobile-items-button" href="/desk/Form/Item/${encodeURIComponent(item.name)}">${__("电脑端查看")}</a></div>
		</div>`;
	}

	render_form() {
		const custom = new Set(this.options.custom_fields || []);
		const custom_fields = [
			["custom_specifications", __("规格型号")], ["custom_mnemonic_code", __("助记码")],
			["custom_sku", "SKU"], ["custom_external_code", __("外部编码")],
			["custom_item_classification", __("物料分类")], ["custom_short_name", __("物料简称")],
			["custom_item_short_name", __("MES 物料简称")],
		].filter(([fieldname]) => custom.has(fieldname));
		this.parent.innerHTML = `<div class="mobile-items-page">
			${this.back_heading(__("新增物料"))}
			<section class="mobile-items-panel mobile-items-form">
				<label>${__("物料编码")} <em>*</em><input data-item-field="item_code" autocomplete="off" placeholder="${__("请输入唯一物料编码")}"></label>
				<label>${__("物料名称")}<input data-item-field="item_name" autocomplete="off" placeholder="${__("留空时使用物料编码")}"></label>
				${custom.has("custom_specifications") ? `<label>${__("规格型号")}<input data-item-field="custom_specifications" autocomplete="off"></label>` : ""}
				<div class="mobile-items-form-columns">
					<label class="mobile-items-reference">${__("物料组")} <em>*</em><input type="search" data-item-reference="item_group" placeholder="${__("输入后选择物料组")}" autocomplete="off"><div class="mobile-items-suggestions" data-item-suggestions="item_group"></div></label>
					<label class="mobile-items-reference">${__("库存单位")} <em>*</em><input type="search" data-item-reference="stock_uom" placeholder="${__("输入后选择单位")}" autocomplete="off"><div class="mobile-items-suggestions" data-item-suggestions="stock_uom"></div></label>
				</div>
				<div class="mobile-items-checks"><label><input type="checkbox" data-item-check="is_stock_item" ${this.form.is_stock_item ? "checked" : ""}>${__("库存物料")}</label><label><input type="checkbox" data-item-check="is_purchase_item" ${this.form.is_purchase_item ? "checked" : ""}>${__("允许采购")}</label><label><input type="checkbox" data-item-check="is_sales_item" ${this.form.is_sales_item ? "checked" : ""}>${__("允许销售")}</label></div>
				<details class="mobile-items-advanced"><summary>${__("更多资料")}</summary>
					${custom_fields.filter(([fieldname]) => fieldname !== "custom_specifications").map(([fieldname, label]) => `<label>${escape_html(label)}<input data-item-field="${fieldname}" autocomplete="off"></label>`).join("")}
					<label>${__("描述")}<textarea data-item-field="description" rows="4"></textarea></label>
				</details>
			</section>
			<div class="mobile-items-message" data-item-message role="alert"></div>
			<div class="mobile-items-actions"><button class="mobile-items-button" data-item-action="back">${__("取消")}</button><button class="mobile-items-button primary" data-item-action="save">${__("保存物料")}</button></div>
		</div>`;
	}

	on_click(event) {
		const suggestion = event.target.closest("[data-item-reference-option]");
		if (suggestion) return this.select_reference(suggestion);
		const action = event.target.closest("[data-item-action]")?.dataset.itemAction;
		if (!action) {
			if (!event.target.closest(".mobile-items-reference")) this.hide_suggestions();
			return;
		}
		if (action === "new") this.app.go("/mobile/inventory/items/new");
		if (action === "open") this.app.go(`/mobile/inventory/items/${encodeURIComponent(event.target.closest("[data-name]").dataset.name)}`);
		if (action === "back") this.app.go("/mobile/inventory/items");
		if (action === "retry") this.refresh();
		if (action === "load-more") this.load_list({ append: true });
		if (action === "inventory") this.app.go(`/mobile/inventory/query?item_code=${encodeURIComponent(this.name)}`);
		if (action === "save") this.save();
	}

	on_input(event) {
		const filter = event.target.dataset.itemFilter;
		if (filter === "search") {
			this.filters.search = event.target.value.trim();
			this.app.item_filters = { ...this.filters };
			clearTimeout(this.list_timer);
			this.list_timer = setTimeout(() => this.load_list(), 300);
		}
		const fieldname = event.target.dataset.itemField;
		if (fieldname && this.form) this.form[fieldname] = event.target.value;
		const reference = event.target.dataset.itemReference;
		if (reference) {
			if (reference === "list_group") {
				this.filters.item_group = "";
				this.app.item_filters = { ...this.filters };
			} else if (this.form) {
				this.form[reference] = "";
			}
			this.search_reference(reference, event.target.value.trim());
		}
	}

	on_change(event) {
		const filter = event.target.dataset.itemFilter;
		if (filter && filter !== "search") {
			this.filters[filter] = event.target.value;
			this.app.item_filters = { ...this.filters };
			this.load_list();
		}
		const check = event.target.dataset.itemCheck;
		if (check && this.form) this.form[check] = event.target.checked ? 1 : 0;
	}

	on_focus(event) {
		const reference = event.target.dataset.itemReference;
		if (reference && !event.target.value.trim()) this.search_reference(reference, "");
	}

	search_reference(reference, search) {
		clearTimeout(this.reference_timer);
		const sequence = ++this.reference_sequence;
		const kind = reference === "stock_uom" ? "uom" : "item_group";
		const container = this.parent.querySelector(`[data-item-suggestions="${reference}"]`);
		if (!container) return;
		container.textContent = __("正在搜索...");
		this.reference_timer = setTimeout(async () => {
			try {
				const rows = await this.call("search_mobile_item_references", { kind, search, limit: 20 });
				if (!container.isConnected || sequence !== this.reference_sequence) return;
				this.reference_results[reference] = rows;
				container.innerHTML = rows.length ? rows.map((row) => `<button type="button" data-item-reference-option data-reference="${reference}" data-value="${escape_attribute(row.value)}"><strong>${escape_html(row.label)}</strong>${row.description ? `<span>${escape_html(row.description)}</span>` : ""}</button>`).join("") : escape_html(__("没有匹配选项"));
			} catch (error) {
				if (container.isConnected && sequence === this.reference_sequence) container.textContent = mobile_item_error(error);
			}
		}, 220);
	}

	select_reference(option) {
		const reference = option.dataset.reference;
		const value = option.dataset.value || "";
		const input = this.parent.querySelector(`[data-item-reference="${reference}"]`);
		if (input) input.value = value;
		if (reference === "list_group") {
			this.filters.item_group = value;
			this.app.item_filters = { ...this.filters };
			this.load_list();
		} else if (this.form) {
			this.form[reference] = value;
		}
		this.hide_suggestions();
	}

	hide_suggestions() {
		this.parent.querySelectorAll(".mobile-items-suggestions").forEach((container) => container.innerHTML = "");
	}

	async save() {
		if (this.busy) return;
		this.parent.querySelectorAll("[data-item-field]").forEach((input) => this.form[input.dataset.itemField] = input.value);
		this.parent.querySelectorAll("[data-item-check]").forEach((input) => this.form[input.dataset.itemCheck] = input.checked ? 1 : 0);
		if (!this.form.item_code.trim() || !this.form.item_group || !this.form.stock_uom) {
			return this.set_message(__("请填写物料编码并从下拉列表选择物料组和库存单位"), "error");
		}
		this.busy = true;
		const button = this.parent.querySelector('[data-item-action="save"]');
		button.disabled = true;
		this.set_message(__("正在保存物料..."));
		try {
			const result = await this.call("create_mobile_item", { data: this.form }, "POST");
			if (this.parent.isConnected) this.app.go(`/mobile/inventory/items/${encodeURIComponent(result.name)}`);
		} catch (error) {
			if (this.parent.isConnected) {
				this.set_message(mobile_item_error(error), "error");
				button.disabled = false;
			}
		} finally {
			this.busy = false;
		}
	}

	set_message(message, tone = "") {
		const node = this.parent.querySelector("[data-item-message]");
		if (!node) return;
		node.textContent = message || "";
		node.className = `mobile-items-message${tone ? ` is-${tone}` : ""}`;
	}
}

function mobile_item_error(error) {
	let message = error?._server_messages || error?.responseJSON?._server_messages;
	if (message) {
		try {
			const messages = JSON.parse(message).map((entry) => {
				try { return JSON.parse(entry).message || JSON.parse(entry).title; } catch (exception) { return entry; }
			}).filter(Boolean);
			if (messages.length) return messages.join("；");
		} catch (exception) { /* fall through */ }
	}
	return error?.message || error?.responseJSON?.exception || __("操作失败，请重试");
}
