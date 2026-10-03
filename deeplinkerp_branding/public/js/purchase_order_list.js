(function (root, factory) {
	const grid = factory();
	if (typeof module === "object" && module.exports) module.exports = grid;
	root.DeepLinkERPPurchaseOrderGrid = grid;
	grid.install(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
	"use strict";

	const DOCTYPE = "Purchase Order";
	const COLUMNS = [
		["transaction_date", "订单日期", 96], ["name", "采购订单号", 166],
		["supplier_name", "供应商名称", 205], ["status", "订单状态", 120],
		["schedule_date", "需求日期", 96], ["company", "公司", 100],
		["currency", "币种", 56], ["grand_total", "订单金额", 176],
		["advance_paid", "已预付", 176], ["advance_payment_status", "预付款状态", 94],
		["per_received", "已收货%", 70], ["per_billed", "已开票%", 70],
		["project", "项目", 96], ["owner", "创建人", 96],
	].map(([fieldname, label, width]) => ({ fieldname, label, width }));
	const NUMBERS = new Set(["grand_total", "advance_paid", "per_received", "per_billed"]);
	const DATES = new Set(["transaction_date", "schedule_date"]);
	const callRequests = new WeakMap();
	const responseRequests = new WeakMap();
	const installed = new WeakSet();

	function escapeHTML(value) {
		return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
	}

	function allowedFields(meta, canRead, standardFields = []) {
		const allowed = new Set(canRead(0) ? standardFields : []);
		for (const df of meta?.fields || []) {
			if (!df.is_virtual && canRead(df.permlevel || 0)) allowed.add(df.fieldname);
		}
		return allowed;
	}

	function preferenceKey(site, user) {
		return ["dlp-list", site, user, DOCTYPE].map((part) => encodeURIComponent(String(part || ""))).join(":");
	}

	function normalizePreferences(value, allowed) {
		const candidates = COLUMNS.filter((col) => allowed.has(col.fieldname)).map((col) => col.fieldname);
		const selected = Array.isArray(value?.columns) ? value.columns : candidates;
		const columns = [...new Set(selected.filter((field) => candidates.includes(field)))];
		if (!columns.includes("name") && allowed.has("name")) columns.unshift("name");
		return { density: value?.density === "standard" ? "standard" : "tight", columns };
	}

	function fieldName(field) {
		if (Array.isArray(field)) return field[0];
		if (typeof field !== "string") return null;
		// Native ListView emits qualified columns. Linked aliases need their own metadata/permission scope.
		const qualified = field.match(/^`?(?:tab)?Purchase Order`?\.`?([\w]+)`?$/);
		return qualified ? qualified[1] : /^[\w]+$/.test(field) ? field : null;
	}

	function buildQuery(nativeArgs, quick, allowed) {
		const filters = (nativeArgs.filters || []).map((filter) => Array.isArray(filter) ? filter.slice(0, 4) : filter);
		const or_filters = (nativeArgs.or_filters || []).map((filter) => Array.isArray(filter) ? filter.slice(0, 4) : filter);
		const add = (field, operator, value) => {
			if (allowed.has(field) && value !== undefined && value !== null && value !== "") filters.push([DOCTYPE, field, operator, value]);
		};
		add("transaction_date", ">=", quick.from_date);
		add("transaction_date", "<=", quick.to_date);
		for (const field of ["company", "status", "advance_payment_status"]) add(field, "=", quick[field]);
		const search = String(quick.search || "").trim();
		if (search && or_filters.length) throw new Error("Quick search cannot be combined with existing OR filters.");
		if (search) {
			for (const field of ["name", "supplier_name"]) {
				if (allowed.has(field)) or_filters.push([DOCTYPE, field, "like", `%${search}%`]);
			}
		}
		return { ...nativeArgs, fields: (nativeArgs.fields || []).filter((field) => allowed.has(fieldName(field))), filters, or_filters };
	}

	function buildRequests(args, columns, allowed) {
		const common = { doctype: DOCTYPE, filters: args.filters, or_filters: args.or_filters };
		const orderGrouping = fieldName(args.group_by) === "name";
		const exportFields = [];
		for (const field of columns) {
			if (!allowed.has(field)) continue;
			if (field === "advance_paid" && !allowed.has("party_account_currency")) continue;
			exportFields.push(field);
			if (field === "advance_paid") exportFields.push("party_account_currency");
		}
		const summary = allowed.has("currency") && allowed.has("grand_total") ? (orderGrouping ? {
			...common, fields: ["name", "currency", "grand_total", "party_account_currency", "advance_paid"].filter((field) => allowed.has(field)),
			group_by: args.group_by, order_by: args.order_by, start: 0, limit_page_length: 0,
		} : {
			...common, fields: ["currency"], group_by: "currency", aggregate_function: "sum",
			aggregate_on_doctype: DOCTYPE, aggregate_on_field: "grand_total", order_by: "currency asc", start: 0, limit_page_length: 0,
		}) : null;
		return {
			count: { ...common, distinct: true, limit: 0 },
			summary,
			export: { ...common, fields: exportFields, ...(args.group_by ? { group_by: args.group_by } : {}), order_by: args.order_by, start: 0, file_format_type: "Excel", title: DOCTYPE },
		};
	}

	function currencyTotals(rows) {
		const seen = new Set();
		const totals = new Map();
		for (const row of rows) {
			if (!row.name || seen.has(row.name)) continue;
			seen.add(row.name);
			const amount = Number(row.grand_total);
			if (!Number.isFinite(amount)) continue;
			const currency = row.currency || "";
			totals.set(currency, (totals.get(currency) || 0) + amount);
		}
		return [...totals].map(([currency, amount]) => ({ currency, _aggregate_column: amount }));
	}

	function renderValue(field, doc, formatters = {}) {
		const value = doc[field];
		if (value === undefined || value === null || value === "") return "—";
		if (NUMBERS.has(field)) {
			const number = Number(value);
			if (!Number.isFinite(number)) return "—";
			const formatted = number === 0 ? "0" : escapeHTML(formatters.number ? formatters.number(number, field, doc) : number.toLocaleString(undefined, { maximumFractionDigits: 6 }));
			if (field.startsWith("per_")) return `${formatted}%`;
			const currency = doc[field === "advance_paid" ? "party_account_currency" : "currency"];
			return formatted + (currency ? ` ${escapeHTML(currency)}` : "");
		}
		if (DATES.has(field) && formatters.date) return escapeHTML(formatters.date(value));
		if (field === "advance_payment_status" && formatters.translate) return escapeHTML(formatters.translate(value));
		return escapeHTML(value);
	}

	function isNativeList(list) {
		return list?.doctype === DOCTYPE && list.view_name === "List" && (!list.view || list.view === "List");
	}

	function isListRoute(frappe) {
		const route = frappe.get_route?.() || [];
		return String(route[0]).toLowerCase() === "list" && route[1] === DOCTYPE && (!route[2] || String(route[2]).toLowerCase() === "list");
	}

	function requestKey(args) {
		return JSON.stringify([args.filters, args.or_filters, args.order_by, args.group_by, args.start, args.page_length, args.fields]);
	}

	function mount(list, root) {
		if (!isNativeList(list)) return null;
		if (list.dlpPurchaseOrderGrid) {
			list.dlpPurchaseOrderGrid.activate();
			return list.dlpPurchaseOrderGrid;
		}
		const frappe = root.frappe;
		const allowed = allowedFields(list.meta, (level) => frappe.perm.has_perm(DOCTYPE, level, "read"), frappe.model.std_fields_list);
		const key = preferenceKey(frappe.boot?.sitename || root.location?.host, frappe.session?.user);
		let saved;
		try { saved = JSON.parse(root.localStorage?.getItem(key) || "null"); } catch (_) { /* Browsers may disable storage. */ }
		const originals = {};
		for (const name of ["get_args", "get_call_args", "no_change", "prepare_data", "reset_defaults", "get_header_html", "get_list_row_html", "render_list", "render_count", "toggle_result_area", "on_filter_change", "process_document_refreshes", "debounced_refresh"]) originals[name] = list[name];
		const controller = {
			list, root, allowed, originals, quick: {}, controls: {}, resetting: false, preferences: normalizePreferences(saved, allowed),
			page: 0, pageSize: 100, requestId: 0, querySignature: null, total: null, summary: [],
			translate: root.__ || ((label) => label),
			setPage(page) {
				this.page = Math.max(0, Number(page) || 0);
				list.start = this.page * this.pageSize;
				list.page_length = this.pageSize;
				list.last_args = null;
			},
			activate() {
				root.document?.body?.classList.toggle("dlp-purchase-order-grid-active", isListRoute(frappe));
			},
			savePreferences() {
				this.preferences = normalizePreferences(this.preferences, allowed);
				try { root.localStorage?.setItem(key, JSON.stringify(this.preferences)); } catch (_) { /* Rendering must work without storage. */ }
				list.$frappe_list?.toggleClass("dlp-po-standard", this.preferences.density === "standard");
			},
			setColumns(columns) {
				this.preferences.columns = columns;
				this.savePreferences();
				const hadSelection = Boolean(list.$checks?.length);
				list.render_list();
				list.set_rows_as_checked?.();
				// Native restoration calls on_row_checked itself only when there were checked elements.
				if (!hadSelection) list.on_row_checked?.();
			},
			async clearQuickFilters() {
				if (this.resetting) return;
				this.resetting = true;
				this.quick = {};
				this.setPage(0);
				try { await Promise.all(Object.values(this.controls).map((control) => control.set_value(""))); }
				finally { this.resetting = false; this.restoreSavedFilterLabel?.(); await this.refresh(); }
			},
			async exportCurrent() {
				if (!frappe.model.can_export?.(DOCTYPE)) throw new Error("当前用户没有采购订单导出权限。");
				const args = buildRequests(list.get_args(), this.preferences.columns, allowed).export;
				if (!root.DeepLinkERPPurchaseOrderExport?.exportExcel) await frappe.require("/assets/deeplinkerp_branding/js/purchase_order_export.js");
				if (!root.DeepLinkERPPurchaseOrderExport?.exportExcel) throw new Error("Excel 导出组件加载失败，请刷新页面后重试。");
				await root.DeepLinkERPPurchaseOrderExport.exportExcel(root, args);
			},
			refresh() {
				this.activate();
				list.last_args = null;
				return list.refresh();
			},
		};
		list.dlpPurchaseOrderGrid = controller;
		controller.setPage(0);
		list.selected_page_count = 100;
		for (const field of new Set([...COLUMNS.map((col) => col.fieldname), "supplier", "party_account_currency", list.workflow_state_fieldname])) {
			if (allowed.has(field) && !list.fields.some((entry) => fieldName(entry) === field)) list.fields.push([field, DOCTYPE]);
		}

		list.get_args = function () {
			const nativeArgs = originals.get_args.call(this);
			if (controller.quick.search && nativeArgs.or_filters?.length) {
				controller.quick.search = "";
				controller.searchControl?.$input?.val("");
				frappe.show_alert?.({ message: controller.translate("现有 OR 筛选已保留；请清除这些条件后使用订单/供应商搜索。"), indicator: "orange" });
			}
			const args = buildQuery(nativeArgs, controller.quick, allowed);
			const signature = JSON.stringify([args.filters, args.or_filters, args.order_by]);
			if (controller.querySignature !== null && controller.querySignature !== signature) {
				controller.setPage(0);
				controller.total = null;
				controller.summary = [];
			}
			controller.querySignature = signature;
			args.start = controller.page * controller.pageSize;
			args.page_length = controller.pageSize;
			this.start = args.start;
			this.page_length = args.page_length;
			return args;
		};
		list.get_call_args = function () {
			const call = originals.get_call_args.call(this);
			const request = { id: null, key: requestKey(call.args) };
			callRequests.set(call, request);
			const callback = call.callback;
			call.callback = (response) => {
				responseRequests.set(response, request);
				callback?.(response);
			};
			return call;
		};
		list.no_change = function (call) {
			const unchanged = originals.no_change.call(this, call);
			// Only the native dispatch gate can distinguish duplicate checks from forced refreshes.
			if (!unchanged && callRequests.has(call)) callRequests.get(call).id = ++controller.requestId;
			return unchanged;
		};
		list.prepare_data = function (response) {
			const request = responseRequests.get(response);
			// Compare the current filters too: a pending throttled refresh may not have issued its new request yet.
			const current = this.get_args();
			if (request && (request.id !== controller.requestId || request.key !== requestKey(current))) return;
			const start = this.start;
			this.start = 0;
			originals.prepare_data.call(this, response);
			this.start = start;
		};
		list.reset_defaults = function () {
			originals.reset_defaults.call(this);
			this.start = controller.page * controller.pageSize;
			this.page_length = controller.pageSize;
			this.selected_page_count = controller.pageSize;
		};
		list.on_filter_change = function (...args) {
			controller.setPage(0);
			return originals.on_filter_change?.apply(this, args);
		};
		list.get_header_html = () => headerHTML(controller);
		list.get_list_row_html = (doc) => rowHTML(controller, doc);
		list.render_list = function () {
			this.$result?.find(".list-row-container").remove();
			this.$list_head_subject = null;
			this.$checkbox_actions = null;
			this.render_header();
			this.data.forEach((doc, index) => {
				doc._idx = index;
				this.$result?.append(this.get_list_row_html(doc));
			});
		};
		list.toggle_result_area = function () {
			originals.toggle_result_area.call(this);
			this.$result?.parent(".result-container").show();
			this.$result?.show();
			this.$paging_area?.hide();
			controller.$paging?.show();
		};
		list.render_count = () => updateSummary(controller);
		preserveRealtimePaging(controller);
		preserveSavedFilterGroup(controller);
		mountControls(controller);
		controller.activate();
		list.render_header(true);
		return controller;
	}

	function preserveRealtimePaging(controller) {
		const { list, root, originals } = controller;
		if (!originals.process_document_refreshes || !root.frappe.utils?.debounce) return;
		// Native incremental refresh appends matching documents and bypasses fixed-page preparation.
		list.process_document_refreshes = function () {
			if (!this.pending_document_refreshes?.length) return;
			if (!isListRoute(root.frappe) || root.cur_list !== this) {
				this.pending_document_refreshes = [];
				this.disable_realtime_updates?.();
				return;
			}
			if (this.$checks?.length || this.avoid_realtime_update?.() || this.disable_list_update || this.filter_area?.is_being_edited?.()) return;
			this.pending_document_refreshes = [];
			return controller.refresh();
		};
		// The constructor already bound the old method; cancel it before replacing that binding.
		originals.debounced_refresh?.cancel?.();
		list.debounced_refresh = root.frappe.utils.debounce(list.process_document_refreshes.bind(list), list.is_large_table ? 15000 : 2000);
	}

	function preserveSavedFilterGroup(controller) {
		const page = controller.list.page;
		const canonical = "Saved Filters";
		const translated = controller.translate(canonical);
		if (translated === canonical || !page?.inner_toolbar?.find || !page.get_inner_group_button || !page.get_or_add_inner_group_button) return;
		// Native ListFilter creates a translated identity but its label updater looks up English.
		// Keep the same button/menu, and alias only this page's group lookup/creation methods.
		const normalize = () => page.inner_toolbar.find(`.inner-group-button[data-label="${encodeURIComponent(translated)}"]`).attr("data-label", encodeURIComponent(canonical));
		normalize();
		for (const name of ["get_inner_group_button", "get_or_add_inner_group_button"]) {
			const original = page[name];
			controller.originals[`page_${name}`] = original;
			page[name] = function (label, ...args) {
				if (label !== canonical && label !== translated) return original.call(this, label, ...args);
				normalize();
				const group = original.call(this, canonical, ...args);
				const text = group.find("button").contents().first()[0];
				if (text?.textContent.trim() === canonical) text.textContent = translated;
				return group;
			};
		}
		controller.restoreSavedFilterLabel = () => page.get_inner_group_button(canonical);
	}

	function layout(controller) {
		const cols = controller.preferences.columns.map((field) => COLUMNS.find((col) => col.fieldname === field));
		const lastFrozen = cols.findIndex((col) => col.fieldname === "supplier_name");
		let left = 76;
		return cols.map((col, index) => {
			const frozen = lastFrozen >= 0 && index <= lastFrozen;
			const result = { ...col, frozen, left };
			left += col.width;
			return result;
		});
	}

	function cellHTML(col, value, title = "", header = false) {
		const classes = ["dlp-po-grid-cell", "ellipsis", col.frozen ? "dlp-po-frozen" : "", NUMBERS.has(col.fieldname) ? "dlp-po-number" : "", DATES.has(col.fieldname) ? "dlp-po-date" : "", col.fieldname === "status" ? "dlp-po-status" : "", col.fieldname === "name" ? "list-subject" : ""].filter(Boolean).join(" ");
		return `<div class="${classes}" data-fieldname="${col.fieldname}" style="--dlp-po-left:${col.left}px;width:${col.width}px" title="${escapeHTML(title)}"${header ? ` data-sort-by="${col.fieldname}"` : ""}>${value}</div>`;
	}

	function template(controller) {
		return `36px 40px ${layout(controller).map((col) => `${col.width}px`).join(" ")}`;
	}

	function selectionCell(html, sequence) {
		return `<div class="dlp-po-grid-cell dlp-po-frozen select-like" data-fieldname="_select" style="--dlp-po-left:0px;width:36px">${html}</div><div class="dlp-po-grid-cell dlp-po-frozen dlp-po-number" data-fieldname="_sequence" style="--dlp-po-left:36px;width:40px">${sequence}</div>`;
	}

	function headerHTML(controller) {
		const { translate: t, list } = controller;
		const checkbox = `<input class="list-header-checkbox list-check-all" type="checkbox" title="${escapeHTML(t("Select All"))}">`;
		const columns = layout(controller).map((col) => {
			const label = t(col.label);
			return cellHTML(col, escapeHTML(label), label, true);
		}).join("");
		return `<div class="list-row-container"><header class="list-row-head dlp-po-grid-header" style="--dlp-po-columns:${template(controller)}"><div class="list-header-subject dlp-po-grid-header-columns">${selectionCell(checkbox, "#")}${columns}</div><div class="checkbox-actions" style="display:none"><span class="select-like">${checkbox}</span><span class="list-header-meta"></span></div></header></div>`;
	}

	function rowHTML(controller, doc) {
		const { list, root } = controller;
		const formatters = {
			translate: controller.translate,
			number: (value, field) => root.format_number ? root.format_number(value, null, field.startsWith("per_") ? 2 : undefined) : value.toLocaleString(undefined, { maximumFractionDigits: 6 }),
			date: (value) => root.frappe.datetime?.str_to_user ? root.frappe.datetime.str_to_user(value) : value,
		};
		const checkbox = `<input type="checkbox" class="list-row-checkbox" data-doctype="${DOCTYPE}" data-name="${escapeHTML(doc.name)}">`;
		const cells = layout(controller).map((col) => {
			let value = renderValue(col.fieldname, doc, formatters);
			if (col.fieldname === "name") value = `<a href="${escapeHTML(list.get_form_link(doc))}" data-name="${escapeHTML(doc.name)}">${value}</a>`;
			if (col.fieldname === "supplier_name" && doc.supplier) value = `<a href="/desk/supplier/${encodeURIComponent(doc.supplier)}">${value}</a>`;
			if (col.fieldname === "status") value = list.get_indicator_html(doc, Boolean(list.workflow_state_fieldname)) || value;
			return cellHTML(col, value, doc[col.fieldname] ?? "—");
		}).join("");
		return `<div class="list-row-container" tabindex="0"><div class="level list-row dlp-po-grid-row" style="--dlp-po-columns:${template(controller)}">${selectionCell(checkbox, controller.page * controller.pageSize + (doc._idx || 0) + 1)}${cells}</div></div>`;
	}

	function mountControls(controller) {
		const { list, root, translate: t } = controller;
		if (!root.$ || !list.$frappe_list || !root.document) return;
		const $ = root.$;
		list.$frappe_list.addClass("dlp-po-grid");
		list.$paging_area.addClass("dlp-po-native-paging").hide();
		controller.$toolbar = $(`<div class="dlp-po-toolbar"><label>${escapeHTML(t("密度"))} <select class="form-control input-xs dlp-po-density"><option value="tight">${escapeHTML(t("紧凑"))}</option><option value="standard">${escapeHTML(t("标准"))}</option></select></label><button class="btn btn-default btn-sm dlp-po-columns" type="button">${escapeHTML(t("列设置"))}</button></div>`).prependTo(list.$frappe_list);
		controller.$toolbar.find(".dlp-po-density").val(controller.preferences.density).on("change.dlpPO", (event) => {
			controller.preferences.density = event.target.value;
			controller.savePreferences();
		});
		controller.$toolbar.find(".dlp-po-columns").on("click.dlpPO", () => columnDialog(controller));
		if (root.frappe.model.can_export?.(DOCTYPE)) {
			$(`<button class="btn btn-default btn-sm dlp-po-export" type="button">${escapeHTML(t("导出 Excel"))}</button>`).appendTo(controller.$toolbar).on("click.dlpPO", async (event) => {
				const button = $(event.currentTarget).prop("disabled", true);
				try { await controller.exportCurrent(); }
				catch (error) { root.frappe.msgprint({ title: t("导出失败"), message: escapeHTML(error.message || t("导出失败，请重试。")), indicator: "red" }); }
				finally { button.prop("disabled", false); }
			});
		}
		controller.$filters = $('<div class="dlp-po-filters"></div>').prependTo(list.page.wrapper.find(".page-form").first());
		const controls = [
			{ fieldname: "search", fieldtype: "Data", label: "采购订单号 / 供应商名称" },
			{ fieldname: "from_date", fieldtype: "Date", label: "订单开始日期", permission_field: "transaction_date" },
			{ fieldname: "to_date", fieldtype: "Date", label: "订单结束日期", permission_field: "transaction_date" },
			{ fieldname: "company", fieldtype: "Link", options: "Company", label: "公司" },
			{ fieldname: "status", fieldtype: "Select", label: "订单状态" },
			{ fieldname: "advance_payment_status", fieldtype: "Select", label: "预付款状态" },
		];
		for (const control of controls) {
			if (control.fieldname !== "search" && !controller.allowed.has(control.permission_field || control.fieldname)) continue;
			const field = list.meta.fields.find((df) => df.fieldname === control.fieldname);
			if (control.fieldtype === "Select") control.options = `\n${field?.options || ""}`;
			const holder = $(`<div class="dlp-po-filter" data-fieldname="${control.fieldname}"></div>`).appendTo(controller.$filters);
			const input = root.frappe.ui.form.make_control({ parent: holder, df: { ...control, label: t(control.label), placeholder: t(control.label), change: () => {
				if (controller.resetting) return;
				controller.quick[control.fieldname] = input.get_value();
				controller.setPage(0);
				controller.refresh();
			} }, render_input: true });
			input.$input?.attr("aria-label", t(control.label));
			controller.controls[control.fieldname] = input;
			if (control.fieldname === "search") controller.searchControl = input;
		}
		list.page.wrapper.find(".page-form .filter-x-button").off("click.dlpPOFilters").on("click.dlpPOFilters", () => controller.clearQuickFilters()).attr("title", t("清空筛选"));
		controller.$summary = $('<div class="dlp-po-summary" aria-live="polite"></div>').insertBefore(list.$paging_area);
		controller.$paging = $(`<div class="dlp-po-paging"><label>${escapeHTML(t("每页"))} <select class="form-control input-xs dlp-po-page-size">${[20, 100, 500, 2500].map((size) => `<option value="${size}">${size}</option>`).join("")}</select></label><span class="dlp-po-page-info"></span><button class="btn btn-default btn-sm dlp-po-previous" type="button">${escapeHTML(t("上一页"))}</button><button class="btn btn-default btn-sm dlp-po-next" type="button">${escapeHTML(t("下一页"))}</button></div>`).appendTo(list.$frappe_list);
		controller.$paging.find(".dlp-po-page-size").val(100).on("change.dlpPO", (event) => {
			controller.pageSize = Number(event.target.value);
			controller.setPage(0);
			controller.refresh();
		});
		for (const [selector, delta] of [[".dlp-po-previous", -1], [".dlp-po-next", 1]]) {
			controller.$paging.find(selector).on("click.dlpPO", () => {
				controller.setPage(controller.page + delta);
				controller.refresh();
			});
		}
		controller.savePreferences();
		paintSummary(controller);
	}

	function paintSummary(controller) {
		const { translate: t, list } = controller;
		const count = controller.total === null ? "…" : controller.total.toLocaleString();
		const amounts = controller.summary.map((row) => renderValue("grand_total", { grand_total: row._aggregate_column, currency: row.currency })).join(" · ");
		controller.$summary?.html(`${escapeHTML(t("Total"))}: ${escapeHTML(count)}${amounts ? ` · ${amounts}` : ""}`);
		const from = list.data.length ? controller.page * controller.pageSize + 1 : 0;
		const to = list.data.length ? controller.page * controller.pageSize + list.data.length : 0;
		controller.$paging?.find(".dlp-po-page-info").text(`${from}–${to} / ${count}`);
		controller.$paging?.find(".dlp-po-previous").prop("disabled", controller.page === 0);
		controller.$paging?.find(".dlp-po-next").prop("disabled", controller.total === null || to >= controller.total || list.data.length === 0);
	}

	function updateSummary(controller) {
		const { list, root } = controller;
		if (!root.frappe.call) return Promise.resolve();
		const args = list.get_args();
		const signature = controller.querySignature;
		const requests = buildRequests(args, controller.preferences.columns, controller.allowed);
		const version = (controller.summaryVersion || 0) + 1;
		controller.summaryVersion = version;
		const current = () => version === controller.summaryVersion && signature === controller.querySignature;
		const count = root.frappe.call({ method: "frappe.desk.reportview.get_count", args: requests.count }).then((response) => {
			if (!current()) return;
			controller.total = Number(response.message || 0);
			list.total_count = controller.total;
			paintSummary(controller);
		});
		const summary = requests.summary ? root.frappe.call({ method: "frappe.desk.reportview.get_list", args: requests.summary }).then((response) => {
			if (!current()) return;
			controller.summary = requests.summary.aggregate_function ? response.message || [] : currencyTotals(response.message || []);
			paintSummary(controller);
		}) : Promise.resolve();
		return Promise.all([count, summary]).catch(() => {
			if (current()) controller.$summary?.text(controller.translate("Unable to load totals"));
		});
	}

	function columnDialog(controller) {
		const { root, list, translate: t } = controller;
		const visible = new Set(controller.preferences.columns);
		const order = [...controller.preferences.columns, ...COLUMNS.map((col) => col.fieldname).filter((field) => controller.allowed.has(field) && !visible.has(field))];
		const dialog = new root.frappe.ui.Dialog({ title: t("列设置"), fields: [{ fieldtype: "HTML", fieldname: "columns" }], primary_action_label: t("保存"), primary_action: () => {
			controller.setColumns(order.filter((field) => visible.has(field)));
			dialog.hide();
		} });
		const wrapper = dialog.fields_dict.columns.$wrapper;
		const draw = () => wrapper.html(`<div class="dlp-po-column-options">${order.map((field) => {
			const col = COLUMNS.find((col) => col.fieldname === field);
			return `<div class="dlp-po-column-option" data-field="${field}"><label><input type="checkbox"${visible.has(field) ? " checked" : ""}${field === "name" ? " disabled" : ""}> ${escapeHTML(t(col.label))}</label><button type="button" class="btn btn-xs btn-default" data-move="-1" aria-label="${escapeHTML(t("Move Up"))}">↑</button><button type="button" class="btn btn-xs btn-default" data-move="1" aria-label="${escapeHTML(t("Move Down"))}">↓</button></div>`;
		}).join("")}</div>`);
		wrapper.off(".dlpPO").on("change.dlpPO", "input", (event) => {
			const field = root.$(event.target).closest("[data-field]").attr("data-field");
			if (event.target.checked) visible.add(field); else visible.delete(field);
		}).on("click.dlpPO", "[data-move]", (event) => {
			const field = root.$(event.target).closest("[data-field]").attr("data-field");
			const index = order.indexOf(field);
			const target = index + Number(event.target.dataset.move);
			if (target >= 0 && target < order.length) {
				[order[index], order[target]] = [order[target], order[index]];
				draw();
			}
		});
		draw();
		dialog.show();
	}

	function install(root) {
		const frappe = root.frappe;
		if (!frappe?.listview_settings || installed.has(frappe)) return;
		installed.add(frappe);
		const settings = frappe.listview_settings[DOCTYPE] || (frappe.listview_settings[DOCTYPE] = {});
		const onload = settings.onload;
		const refresh = settings.refresh;
		settings.onload = function (list) {
			const result = onload?.apply(this, arguments);
			mount(list, root);
			return result;
		};
		settings.refresh = function (list) {
			const result = refresh?.apply(this, arguments);
			if (isNativeList(list)) mount(list, root)?.activate();
			return result;
		};
		frappe.router?.on("change", () => {
			root.document?.body?.classList.toggle("dlp-purchase-order-grid-active", isListRoute(frappe));
			const list = frappe.views?.list_view?.[DOCTYPE] || root.cur_list;
			if (isListRoute(frappe) && isNativeList(list)) mount(list, root);
		});
	}

	return { COLUMNS, allowedFields, preferenceKey, normalizePreferences, buildQuery, buildRequests, currencyTotals, renderValue, mount, install };
});
