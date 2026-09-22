/* Mobile BOM list, composition and draft editor. */
class MobileBOMView {
	constructor(parent, app) {
		this.parent = parent;
		this.app = app;
		this.sequence = 0;
		this.search_sequences = {};
		this.search_timers = {};
		this.item_results = {};
		this.row_counter = 0;
		this.filters = { search: "", status: "active", company: "", ...app.bom_filters };
		const path = app.route.slice("/mobile/production/bom/".length);
		this.mode = app.route === "/mobile/production/bom/new" ? "form"
			: app.route.endsWith("/edit") ? "form"
				: app.route.startsWith("/mobile/production/bom/") ? "detail" : "list";
		this.name = this.mode === "list" || path === "new" ? "" : decodeURIComponent(path.replace(/\/edit$/, ""));
		this.parent.addEventListener("click", (event) => this.on_click(event));
		this.parent.addEventListener("input", (event) => this.on_input(event));
		this.parent.addEventListener("change", (event) => this.on_change(event));
		this.refresh();
	}

	async call(method, args = {}) {
		return new Promise((resolve, reject) => frappe.call({
			method: `mobile_operations.bom.${method}`, args, freeze: false,
			callback: (response) => response.exc ? reject(response) : resolve(response.message),
			error: reject,
		}));
	}

	async refresh() {
		if (this.busy) return;
		if (this.mode === "form" && this.form) return; // Preserve unsaved input on header refresh.
		if (this.mode === "list") {
			this.render_list_shell();
			return this.load_list();
		}
		this.parent.innerHTML = `<div class="mobile-bom-page"><div class="mobile-bom-empty">${__("正在加载 BOM...")}</div></div>`;
		try {
			if (this.mode === "form") {
				this.options = await this.call("get_mobile_bom_form_options", { name: this.name });
				if (!this.parent.isConnected) return;
				const detail = this.options.detail;
				this.form = {
					name: detail?.name, modified: detail?.modified,
					company: detail?.company || this.options.default_company,
					item: detail?.item || "", item_name: detail?.item_name || "",
					search: detail?.item || "", uom: detail?.uom || "", quantity: detail?.quantity || 1,
					specification: detail?.specification || "",
					items: detail ? detail.items.map((row) => this.new_row(row)) : [this.new_row()],
				};
				this.render_form();
			} else {
				this.detail = await this.call("get_mobile_bom_detail", { name: this.name });
				if (!this.parent.isConnected) return;
				this.output_qty = this.detail.quantity;
				this.component_mode = "items";
				this.render_detail();
			}
		} catch (error) {
			if (!this.parent.isConnected) return;
			this.parent.innerHTML = `<div class="mobile-bom-page">${this.back_heading(__("BOM 物料清单"))}<div class="mobile-bom-empty is-error">${escape_html(mobile_bom_error(error))}</div><button class="mobile-bom-button" data-bom-action="retry">${__("重试")}</button></div>`;
		}
	}

	back_heading(title) {
		return `<div class="mobile-bom-heading"><button class="mobile-bom-back" data-bom-action="back" aria-label="${__("返回")}"><i class="fa fa-arrow-left"></i></button><div><h2>${escape_html(title)}</h2><p>${__("BOM 物料清单")}</p></div></div>`;
	}

	render_list_shell() {
		this.parent.innerHTML = `<div class="mobile-bom-page">
			<div class="mobile-bom-heading"><div><h2>${__("BOM 物料清单")}</h2><p>${__("查看成品配方与组件用量")}</p></div><button class="mobile-bom-button primary" data-bom-action="new" hidden><i class="fa fa-plus"></i> ${__("新建")}</button></div>
			<div class="mobile-bom-panel mobile-bom-filters">
				<label class="mobile-bom-search"><i class="fa fa-search"></i><input type="search" data-bom-filter="search" value="${escape_attribute(this.filters.search)}" placeholder="${__("搜索 BOM、成品编码、名称或规格")}" aria-label="${__("搜索 BOM、成品编码、名称或规格")}" autocomplete="off"></label>
				<div class="mobile-bom-columns"><label>${__("状态")}<select data-bom-filter="status">${["active", "all", "default", "draft", "inactive", "cancelled"].map((key) => `<option value="${key}"${key === this.filters.status ? " selected" : ""}>${mobile_bom_status(key)}</option>`).join("")}</select></label><label>${__("公司")}<select data-bom-filter="company"><option value="">${__("全部公司")}</option></select></label></div>
			</div><div class="mobile-bom-section"><h3>${__("BOM 列表")}</h3><span data-bom-region="count"></span></div>
			<div data-bom-region="list"></div><div data-bom-region="message" class="mobile-bom-message" role="status"></div>
			<button class="mobile-bom-button mobile-bom-load-more" data-bom-action="more" hidden>${__("加载更多")}</button>
		</div>`;
	}

	async load_list(append = false) {
		if (append && this.loading) return;
		this.loading = true;
		const sequence = ++this.sequence;
		const more = this.parent.querySelector('[data-bom-action="more"]');
		more.disabled = true;
		if (!append) {
			this.entries = [];
			more.hidden = true;
			this.parent.querySelector('[data-bom-region="list"]').innerHTML = `<div class="mobile-bom-empty">${__("正在加载 BOM...")}</div>`;
		}
		this.app.bom_filters = { ...this.filters };
		this.message("");
		try {
			const result = await this.call("get_mobile_bom_list", { ...this.filters, offset: this.entries.length, limit: 20 });
			if (sequence !== this.sequence || !this.parent.isConnected) return;
			this.entries = append ? [...this.entries, ...result.entries] : result.entries;
			this.parent.querySelector('[data-bom-action="new"]').hidden = !result.can_create;
			const company = this.parent.querySelector('[data-bom-filter="company"]');
			company.innerHTML = `<option value="">${__("全部公司")}</option>` + result.companies.map((name) => `<option value="${escape_attribute(name)}">${escape_html(name)}</option>`).join("");
			company.value = this.filters.company;
			this.parent.querySelector('[data-bom-region="count"]').textContent = __("共 {0} 条，已加载 {1} 条", [result.total, this.entries.length]);
			this.parent.querySelector('[data-bom-region="list"]').innerHTML = this.entries.length ? this.entries.map((bom) => `<button class="mobile-bom-card" data-bom-action="open" data-name="${escape_attribute(bom.name)}">
				<div class="mobile-bom-card-top"><strong>${escape_html(bom.item)}</strong>${this.badges(bom)}</div><h3>${escape_html(bom.item_name || bom.item)}</h3>
				${bom.specification ? `<p class="mobile-bom-specification">${escape_html(bom.specification)}</p>` : ""}<p class="mobile-bom-id">${escape_html(bom.name)}</p>
				<div class="mobile-bom-card-meta"><span>${__("基准数量")}: ${mobile_bom_number(bom.quantity)} ${escape_html(bom.uom || "")}</span><span>${__("组件")}: ${bom.item_count} ${__("项")}</span></div>
				<div class="mobile-bom-card-footer"><span>${escape_html(bom.company)}</span><i class="fa fa-angle-right"></i></div></button>`).join("") : `<div class="mobile-bom-empty">${__("没有符合条件的 BOM")}</div>`;
			more.hidden = !result.has_more;
		} catch (error) {
			if (sequence !== this.sequence || !this.parent.isConnected) return;
			if (!append) this.parent.querySelector('[data-bom-region="list"]').replaceChildren();
			this.message(mobile_bom_error(error), true);
		} finally {
			if (sequence === this.sequence) { this.loading = false; more.disabled = false; }
		}
	}

	badges(bom) {
		return `<span class="mobile-bom-badges"><span class="mobile-bom-badge is-${bom.status}">${mobile_bom_status(bom.status)}</span>${bom.is_default ? `<span class="mobile-bom-badge is-default">${__("默认")}</span>` : ""}</span>`;
	}

	render_detail() {
		const bom = this.detail;
		this.parent.innerHTML = `<div class="mobile-bom-page">${this.back_heading(bom.item)}
			<section class="mobile-bom-panel"><div class="mobile-bom-card-top"><h3>${escape_html(bom.item_name || bom.item)}</h3>${this.badges(bom)}</div>
				${bom.specification ? `<p class="mobile-bom-specification">${escape_html(bom.specification)}</p>` : ""}<p class="mobile-bom-id">${escape_html(bom.name)}</p>
				<div class="mobile-bom-facts">${this.fact(__("公司"), bom.company)}${this.fact(__("基准数量"), `${mobile_bom_number(bom.quantity)} ${bom.uom || ""}`)}</div>
			</section>
			<section class="mobile-bom-panel"><label class="mobile-bom-output">${__("生产数量")}<div><input type="number" data-bom-output min="0" step="any" inputmode="decimal" value="${escape_attribute(this.output_qty)}"><span>${escape_html(bom.uom || "")}</span></div></label><p class="mobile-bom-help">${__("按 BOM 基准数量等比例换算，仅用于查看用量。")}</p></section>
			<div class="mobile-bom-tabs"><button data-bom-action="components" data-mode="items" class="is-active">${__("直接组件")}</button><button data-bom-action="components" data-mode="exploded_items">${__("展开物料")}</button></div>
			<div data-bom-region="components"></div>
			${bom.operations.length ? `<section class="mobile-bom-panel"><h3>${__("工序")}</h3>${bom.operations.map((row) => `<div class="mobile-bom-operation"><strong>${escape_html(row.operation)}</strong><span>${mobile_bom_number(row.time_in_mins)} ${__("分钟")}</span><p>${escape_html(row.workstation || row.description || "")}</p></div>`).join("")}</section>` : ""}
			${bom.secondary_items.length ? `<section class="mobile-bom-panel"><h3>${__("副产品")}</h3>${bom.secondary_items.map((row) => `<div class="mobile-bom-operation"><strong>${escape_html(row.item_code)}</strong><span>${mobile_bom_number(row.qty)} ${escape_html(row.uom || "")}</span><p>${escape_html(row.item_name || "")}</p></div>`).join("")}</section>` : ""}
			<div class="mobile-bom-actions">${bom.can_edit ? `<button class="mobile-bom-button" data-bom-action="edit">${__("编辑草稿")}</button>` : ""}${bom.can_submit ? `<button class="mobile-bom-button primary" data-bom-action="submit">${__("提交 BOM")}</button>` : ""}</div>
			<div data-bom-region="message" class="mobile-bom-message" role="status"></div>
			<a class="mobile-bom-desktop" href="/desk/bom/${encodeURIComponent(bom.name)}">${__("电脑端处理")} <i class="fa fa-external-link"></i></a>
		</div>`;
		this.render_components();
	}

	fact(label, value) {
		return `<div><span>${escape_html(label)}</span><strong>${escape_html(value || "—")}</strong></div>`;
	}

	render_components() {
		const container = this.parent.querySelector('[data-bom-region="components"]');
		const quantity = Number(this.output_qty);
		if (!Number.isFinite(quantity) || quantity <= 0 || this.detail.quantity <= 0) {
			container.innerHTML = `<div class="mobile-bom-empty">${__("请输入大于零的生产数量")}</div>`;
			return;
		}
		const items = this.detail[this.component_mode];
		const factor = quantity / this.detail.quantity;
		container.innerHTML = items.length ? items.map((row) => `<article class="mobile-bom-component"><div class="mobile-bom-card-top"><strong>${escape_html(row.item_code)}</strong><div class="mobile-bom-quantity"><b>${mobile_bom_number(row.qty * factor)}</b><span>${escape_html(row.uom || "")}</span></div></div><p>${escape_html(row.item_name || row.description || "")}</p>
			<div class="mobile-bom-component-meta"><span>${__("基准用量")}: ${mobile_bom_number(row.qty)} ${escape_html(row.uom || "")}</span>${Number(row.scrap_rate) ? `<span>${__("损耗率")}: ${mobile_bom_number(row.scrap_rate)}%</span>` : ""}${row.operation ? `<span>${escape_html(row.operation)}</span>` : ""}${row.source_warehouse ? `<span>${escape_html(row.source_warehouse)}</span>` : ""}</div>
			${row.bom_no ? `<button class="mobile-bom-sub" data-bom-action="open" data-name="${escape_attribute(row.bom_no)}">${__("子 BOM")}: ${escape_html(row.bom_no)} <i class="fa fa-angle-right"></i></button>` : ""}</article>`).join("") : `<div class="mobile-bom-empty">${__("暂无物料明细")}</div>`;
	}

	new_row(data = {}) {
		return { key: String(++this.row_counter), item_code: "", item_name: "", qty: "", uom: "", scrap_rate: 0, ...data, search: data.item_code || "", original: { ...data } };
	}

	render_form() {
		const form = this.form;
		this.parent.innerHTML = `<div class="mobile-bom-page">${this.back_heading(this.name ? __("编辑 BOM") : __("新建 BOM"))}
			<section class="mobile-bom-panel"><h3>${__("基本信息")}</h3>
				<label class="mobile-bom-field">${__("公司")}<select data-bom-field="company">${this.options.companies.map((row) => `<option value="${escape_attribute(row.name)}"${row.name === form.company ? " selected" : ""}>${escape_html(row.name)}</option>`).join("")}</select></label>
				<label class="mobile-bom-field">${__("成品物料")}<input type="search" data-bom-search="product" value="${escape_attribute(form.search)}" placeholder="${__("搜索物料编码或名称")}" autocomplete="off"></label>
				<div class="mobile-bom-suggestions" data-bom-suggestions="product"></div><p class="mobile-bom-selected" data-bom-product-name>${escape_html(form.item_name)}</p>
				<div class="mobile-bom-columns"><label class="mobile-bom-field">${__("基准数量")}<input type="number" min="0" step="any" inputmode="decimal" data-bom-field="quantity" value="${escape_attribute(form.quantity)}"></label><div class="mobile-bom-field"><span>${__("单位")}</span><div class="mobile-bom-unit" data-bom-product-uom>${escape_html(form.uom || __("单位待自动带出"))}</div></div></div>
				${this.options.has_specification ? `<label class="mobile-bom-field">${__("规格")}<input data-bom-field="specification" value="${escape_attribute(form.specification)}"${this.options.specification_read_only ? " readonly" : ""}></label>` : ""}
			</section><section class="mobile-bom-panel"><div class="mobile-bom-section"><h3>${__("组件明细")}</h3><span data-bom-region="item-count"></span></div><div data-bom-region="form-items"></div><button class="mobile-bom-add" data-bom-action="add"><i class="fa fa-plus"></i> ${__("添加组件")}</button></section>
			<div data-bom-region="message" class="mobile-bom-message" role="status"></div><div class="mobile-bom-actions"><button class="mobile-bom-button" data-bom-action="save">${__("保存草稿")}</button>${this.options.can_submit ? `<button class="mobile-bom-button primary" data-bom-action="save-submit">${__("保存并提交")}</button>` : ""}</div>
		</div>`;
		this.render_form_items();
	}

	render_form_items() {
		this.parent.querySelector('[data-bom-region="item-count"]').textContent = `${this.form.items.length} ${__("项")}`;
		this.parent.querySelector('[data-bom-region="form-items"]').innerHTML = this.form.items.map((row, position) => `<div class="mobile-bom-form-item" data-bom-row="${row.key}"><div class="mobile-bom-section"><strong>${__("组件")} ${position + 1}</strong><button class="mobile-bom-remove" data-bom-action="remove" data-key="${row.key}" aria-label="${__("删除组件")}"><i class="fa fa-trash-o"></i></button></div>
			<input type="search" data-bom-search="${row.key}" value="${escape_attribute(row.search)}" placeholder="${__("搜索物料编码或名称")}" aria-label="${__("组件物料")}" autocomplete="off"><div class="mobile-bom-suggestions" data-bom-suggestions="${row.key}"></div><p class="mobile-bom-selected">${escape_html(row.item_name)}</p>
			<div class="mobile-bom-columns"><label class="mobile-bom-field">${__("组件用量")}<input type="number" data-bom-row-field="qty" value="${escape_attribute(row.qty)}" min="0" step="any" inputmode="decimal"></label><div class="mobile-bom-field"><span>${__("单位")}</span><div class="mobile-bom-unit">${escape_html(row.uom || __("单位待自动带出"))}</div></div></div>
			${this.options.has_scrap_rate ? `<label class="mobile-bom-field">${__("损耗率")} (%)<input type="number" data-bom-row-field="scrap_rate" value="${escape_attribute(row.scrap_rate || 0)}" min="0" max="100" step="any" inputmode="decimal"></label>` : ""}
			${row.bom_no ? `<small class="mobile-bom-help">${__("子 BOM")}: ${escape_html(row.bom_no)}</small>` : ""}</div>`).join("");
	}

	on_input(event) {
		const input = event.target;
		if (input.dataset.bomFilter === "search") {
			this.filters.search = input.value;
			// Invalidate any response for the previous text immediately.
			this.sequence += 1;
			clearTimeout(this.list_timer);
			this.list_timer = setTimeout(() => this.parent.isConnected && this.load_list(), 250);
		}
		if (input.hasAttribute("data-bom-output")) { this.output_qty = input.value; this.render_components(); }
		if (!this.form) return;
		if (input.dataset.bomField) this.form[input.dataset.bomField] = input.value;
		if (input.dataset.bomRowField) {
			const row = this.form.items.find((item) => item.key === input.closest('[data-bom-row]').dataset.bomRow);
			if (row) row[input.dataset.bomRowField] = input.value;
		}
		if (input.hasAttribute("data-bom-search")) this.search_items(input);
	}

	on_change(event) {
		const input = event.target;
		if (input.dataset.bomFilter && input.dataset.bomFilter !== "search") {
			this.filters[input.dataset.bomFilter] = input.value;
			clearTimeout(this.list_timer);
			this.load_list();
		}
		if (this.form && input.dataset.bomField) this.form[input.dataset.bomField] = input.value;
	}

	search_items(input) {
		const key = input.dataset.bomSearch;
		const row = key === "product" ? this.form : this.form.items.find((item) => item.key === key);
		if (!row) return;
		const query = input.value.trim();
		row.search = input.value;
		if (key === "product") row.item = "";
		else row.item_code = "";
		row.item_name = "";
		row.uom = "";
		const sequence = this.search_sequences[key] = (this.search_sequences[key] || 0) + 1;
		clearTimeout(this.search_timers[key]);
		this.item_results[key] = [];
		const container = this.parent.querySelector(`[data-bom-suggestions="${key}"]`);
		container.textContent = query.length < 2 ? "" : __("正在搜索物料...");
		if (key === "product") {
			this.parent.querySelector('[data-bom-product-name]').textContent = "";
			this.parent.querySelector('[data-bom-product-uom]').textContent = __("单位待自动带出");
			if (this.options.specification_read_only) {
				this.form.specification = "";
				this.parent.querySelector('[data-bom-field="specification"]').value = "";
			}
		} else {
			input.closest('[data-bom-row]').querySelector('.mobile-bom-selected').textContent = "";
			input.closest('[data-bom-row]').querySelector('.mobile-bom-unit').textContent = __("单位待自动带出");
		}
		if (query.length < 2) return;
		this.search_timers[key] = setTimeout(async () => {
			if (!this.parent.isConnected) return;
			try {
				const items = await this.call("search_mobile_bom_items", { search: query, name: this.name, limit: 15 });
				if (!container.isConnected || sequence !== this.search_sequences[key]) return;
				this.item_results[key] = items;
				container.innerHTML = items.length ? items.map((item) => `<button data-bom-action="select-item" data-key="${key}" data-code="${escape_attribute(item.name)}"><strong>${escape_html(item.name)}</strong><span>${escape_html(item.item_name || item.description || "")} · ${escape_html(item.stock_uom || "")}</span></button>`).join("") : escape_html(__("没有找到匹配物料"));
			} catch (error) {
				if (container.isConnected && sequence === this.search_sequences[key]) container.textContent = mobile_bom_error(error);
			}
		}, 250);
	}

	select_item(key, code) {
		const item = this.item_results[key]?.find((row) => row.name === code);
		if (!item) return;
		this.search_sequences[key] += 1;
		if (key === "product") {
			Object.assign(this.form, { item: item.name, search: item.name, item_name: item.item_name, uom: item.stock_uom });
			this.parent.querySelector('[data-bom-search="product"]').value = item.name;
			this.parent.querySelector('[data-bom-product-name]').textContent = item.item_name || "";
			this.parent.querySelector('[data-bom-product-uom]').textContent = item.stock_uom || "";
			if (this.options.specification_read_only) {
				this.form.specification = item.specification || "";
				this.parent.querySelector('[data-bom-field="specification"]').value = this.form.specification;
			}
			this.parent.querySelector('[data-bom-suggestions="product"]').replaceChildren();
		} else {
			const position = this.form.items.findIndex((row) => row.key === key);
			if (position < 0) return;
			const old = this.form.items[position];
			const same_item = old.original.item_code === item.name;
			this.form.items[position] = this.new_row(same_item
				? { ...old.original, qty: old.qty, scrap_rate: old.scrap_rate }
				: { item_code: item.name, item_name: item.item_name, qty: old.qty, uom: item.stock_uom });
			this.render_form_items();
		}
	}

	on_click(event) {
		const button = event.target.closest('[data-bom-action]');
		if (!button || this.busy) return;
		const action = button.dataset.bomAction;
		if (action === "back") this.app.go("/mobile/production");
		if (action === "new") this.app.go("/mobile/production/bom/new");
		if (action === "open") this.app.go(`/mobile/production/bom/${encodeURIComponent(button.dataset.name)}`);
		if (action === "edit") this.app.go(`/mobile/production/bom/${encodeURIComponent(this.name)}/edit`);
		if (action === "retry") this.refresh();
		if (action === "more") this.load_list(true);
		if (action === "components") {
			this.component_mode = button.dataset.mode;
			this.parent.querySelectorAll('[data-bom-action="components"]').forEach((tab) => tab.classList.toggle("is-active", tab === button));
			this.render_components();
		}
		if (action === "add") { this.form.items.push(this.new_row()); this.render_form_items(); }
		if (action === "remove") {
			this.form.items = this.form.items.filter((row) => row.key !== button.dataset.key);
			if (!this.form.items.length) this.form.items.push(this.new_row());
			this.render_form_items();
		}
		if (action === "select-item") this.select_item(button.dataset.key, button.dataset.code);
		if (action === "save" || action === "save-submit") this.save(action === "save-submit");
		if (action === "submit") this.submit();
	}

	set_busy(value) {
		this.busy = value;
		this.parent.querySelectorAll('button, input, select').forEach((input) => { input.disabled = value; });
	}

	async save(submit) {
		const form = this.form;
		if (!form.company || !form.item) return this.message(__("请选择公司和成品物料"), true);
		if (!Number.isFinite(Number(form.quantity)) || Number(form.quantity) <= 0) return this.message(__("成品数量和组件用量必须大于零"), true);
		if (form.items.some((row) => !row.item_code || !Number.isFinite(Number(row.qty)) || Number(row.qty) <= 0)) return this.message(__("请为每项组件选择物料并填写有效用量"), true);
		if (form.items.some((row) => row.item_code === form.item)) return this.message(__("成品不能作为自身组件"), true);
		if (form.items.some((row) => !Number.isFinite(Number(row.scrap_rate || 0)) || Number(row.scrap_rate) < 0 || Number(row.scrap_rate) > 100)) return this.message(__("损耗率必须在 0 到 100 之间"), true);
		this.set_busy(true);
		this.message(submit ? __("正在提交...") : __("正在保存..."));
		try {
			const data = { ...form, items: form.items.map(({ name, item_code, qty, scrap_rate }) => ({ name, item_code, qty, scrap_rate })) };
			const result = await this.call("save_mobile_bom", { data: JSON.stringify(data), submit: submit ? 1 : 0 });
			if (this.parent.isConnected) this.app.go(`/mobile/production/bom/${encodeURIComponent(result.name)}`);
		} catch (error) { this.message(mobile_bom_error(error), true); }
		finally { this.set_busy(false); }
	}

	async submit() {
		this.set_busy(true);
		this.message(__("正在提交..."));
		try {
			await this.call("submit_mobile_bom", { name: this.name, modified: this.detail.modified });
			this.busy = false;
			if (this.parent.isConnected) await this.refresh();
		} catch (error) { this.message(mobile_bom_error(error), true); }
		finally { this.set_busy(false); }
	}

	message(text, error = false) {
		const element = this.parent.querySelector('[data-bom-region="message"]');
		if (element) { element.textContent = text; element.classList.toggle("is-error", error); }
	}
}

function mobile_bom_status(status) {
	return { all: __("全部状态"), active: __("已启用"), default: __("默认 BOM"), draft: __("草稿"), inactive: __("已停用"), cancelled: __("已取消") }[status] || status;
}

function mobile_bom_number(value) {
	return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 9 });
}

function mobile_bom_error(error) {
	try {
		const response = error.responseJSON || error;
		const messages = JSON.parse(response._server_messages || "[]");
		if (messages.length) {
			const text = messages.map((message) => JSON.parse(message).message).join("；");
			const element = document.createElement("div");
			element.innerHTML = text;
			return element.textContent;
		}
	} catch { /* Use a concise fallback when the response is not structured. */ }
	return __("操作失败，请检查权限或稍后重试");
}
