(function (root, factory) {
 const engine = { create: factory, fitViewport };
 // Opt-in sizing shared by Sales and inventory; other list heights stay native.
 function fitViewport(owner, options) {
  if (!owner) return;
  if (!options.active) return owner.stopTableViewport?.();
  if (owner.updateTableViewport) return owner.updateTableViewport();
  const {root:host,scrollElement:result,layoutTailElement:list,property,headerSelector,rowSelector,observeTargets=[]}=options;
  if (!result?.getBoundingClientRect || !list?.getBoundingClientRect || !host.requestAnimationFrame || !host.getComputedStyle) return;
  let frame, stopped=false, observedHeader, observedRow;
  const schedule=()=>{if(!stopped && frame===undefined)frame=host.requestAnimationFrame(measure);};
  const observer=host.ResizeObserver ? new host.ResizeObserver(schedule) : null;
  const number=value=>parseFloat(value)||0;
  function measure() {
   frame=undefined;
   if(stopped)return;
   const ancestors=[];
   for(let node=result.parentElement;node;node=node.parentElement)ancestors.push(node);
   // Normalize geometry to the unscrolled layout so an outer scroll cannot grow the table.
   const top=result.getBoundingClientRect().top+ancestors.reduce((sum,node)=>sum+(node.scrollTop||0),0);
   let bottom=host.innerHeight,spacing=number(host.getComputedStyle(list).marginBottom),reachedScroller=false;
   ancestors.forEach((node,index)=>{
    const style=host.getComputedStyle(node),scrollable=/^(auto|scroll|overlay)$/.test(style.overflowY);
    if(scrollable){
     const above=ancestors.slice(index+1).reduce((sum,parent)=>sum+(parent.scrollTop||0),0);
     bottom=Math.min(bottom,node.getBoundingClientRect().top+(node.clientTop||0)+node.clientHeight+above);
    }
    if(node!==list && !reachedScroller)spacing+=number(style.paddingBottom)+(scrollable?0:number(style.marginBottom));
    reachedScroller ||= scrollable;
   });
   const header=result.querySelector(headerSelector),row=result.querySelector(rowSelector);
   for(const [previous,current] of [[observedHeader,header],[observedRow,row]]){
    if(previous!==current){if(previous)observer?.unobserve?.(previous);if(current)observer?.observe(current);}
   }
   observedHeader=header;observedRow=row;
   const rowHeight=row ? number(host.getComputedStyle(row).minHeight)||row.getBoundingClientRect?.().height||0 : 0;
   const minimum=(header?.getBoundingClientRect().height||0)+rowHeight+Math.max(0,result.offsetHeight-result.clientHeight);
   const tail=Math.max(0,list.getBoundingClientRect().bottom-result.getBoundingClientRect().bottom);
   const height=`${Math.floor(Math.max(minimum,bottom-top-tail-spacing))}px`;
   if(result.style.getPropertyValue(property)!==height)result.style.setProperty(property,height);
  }
  owner.updateTableViewport=schedule;
  owner.stopTableViewport=()=>{
   stopped=true;observer?.disconnect();
   if(frame!==undefined)host.cancelAnimationFrame(frame);
   host.removeEventListener('resize',schedule);result.style.removeProperty(property);
   owner.updateTableViewport=null;owner.stopTableViewport=null;
  };
  for(const node of new Set([list,result,...observeTargets]))if(node)observer?.observe(node);
  host.addEventListener('resize',schedule);
  schedule();
 }
 if (typeof module === "object" && module.exports) module.exports = engine;
 root.DeepLinkERPCompactList = engine;
})(typeof globalThis !== "undefined" ? globalThis : this, function (config) {
 "use strict";
 const DOCTYPE = config.doctype;
	const COLUMNS = config.columns;
	const NUMBERS = new Set(config.numbers || []);
	const DATES = new Set(config.dates || []);
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

	function normalizePreferences(value, allowed, definitions = COLUMNS) {
		if (definitions === COLUMNS && config.migratePreferences) value = config.migratePreferences(value, allowed);
		const candidates = definitions.filter((col) => allowed.has(col.fieldname)).map((col) => col.fieldname);
		const defaults = definitions === COLUMNS ? config.defaultColumns : config.provider?.defaultColumns;
		const selected = Array.isArray(value?.columns) ? value.columns : (defaults || candidates);
		const columns = [...new Set(selected.filter((field) => candidates.includes(field)))];
		if (!columns.includes("name") && allowed.has("name")) columns.unshift("name");
		return { density: value?.density === "standard" ? "standard" : "tight", columns, ...(config.preferenceVersion ? { version: config.preferenceVersion } : {}) };
	}

	function selectOptions(control, field, translate) {
		const options = control.options || `\n${field?.options || ""}`;
		const labels = config.optionLabels?.[control.fieldname];
		if (!labels && !control.emptyLabel) return options;
		const values = typeof options === "string" ? options.split("\n") : options;
		return [...new Set(values)].map(value => typeof value === "object" ? value : ({ value, label: translate(value ? labels?.[value] || value : control.emptyLabel || "") }));
	}

	function fieldName(field) {
		if (Array.isArray(field)) return field[0];
		if (typeof field !== "string") return null;
		// Native ListView emits qualified columns. Linked aliases need their own metadata/permission scope.
		const clean = field.replace(/`/g, "");
		const prefix = clean.startsWith("tab") ? `tab${DOCTYPE}.` : `${DOCTYPE}.`;
		const name = clean.startsWith(prefix) ? clean.slice(prefix.length) : clean;
		return /^[\w]+$/.test(name) ? name : null;
	}

	function buildQuery(nativeArgs, quick, allowed) {
		const filters = (nativeArgs.filters || []).map((filter) => Array.isArray(filter) ? filter.slice(0, 4) : filter);
		const or_filters = (nativeArgs.or_filters || []).map((filter) => Array.isArray(filter) ? filter.slice(0, 4) : filter);
		const add = (field, operator, value) => {
			if (allowed.has(field) && value !== undefined && value !== null && value !== "") filters.push([DOCTYPE, field, operator, value]);
		};
		add(config.dateField || "transaction_date", ">=", quick.from_date);
		add(config.dateField || "transaction_date", "<=", quick.to_date);
		for (const field of config.quickFields || []) add(field, "=", quick[field]);
		const search = String(quick.search || "").trim();
		if (search && or_filters.length) throw new Error("Quick search cannot be combined with existing OR filters.");
		if (search) {
			for (const field of config.searchFields || ["name"]) {
				if (allowed.has(field)) or_filters.push([DOCTYPE, field, "like", `%${search}%`]);
			}
		}
		let order_by = nativeArgs.order_by;
		if (typeof order_by === "string") {
			const unavailable = new Set((config.legacyDisplayFields || []).filter((field) => !allowed.has(field)));
			const parts = order_by.split(",").map((part) => part.trim());
			const retained = parts.filter((part) => !unavailable.has(fieldName(part.replace(/\s+(?:asc|desc)\s*$/i, ""))));
			if (retained.length !== parts.length) order_by = retained.join(", ") || (allowed.has("name") ? "name desc" : undefined);
		}
		return { ...nativeArgs, order_by, fields: (nativeArgs.fields || []).filter((field) => allowed.has(fieldName(field))), filters, or_filters };
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
		const summary = config.moneySummary && allowed.has("currency") && allowed.has("grand_total") ? (orderGrouping ? {
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

	function formatNumber(root, value, field) {
		const configured = config.moneyPrecision ?? root.frappe?.boot?.sysdefaults?.currency_precision;
		const currencyPrecision = configured !== undefined && configured !== null && configured !== "" ? Number(configured) : 2;
		const precision = field.startsWith("per_") ? 2 : (Number.isInteger(currencyPrecision) && currencyPrecision >= 0 && currencyPrecision <= 9 ? currencyPrecision : 2);
		return root.format_number ? root.format_number(value, null, precision) : value.toLocaleString(undefined, { minimumFractionDigits: field.startsWith("per_") ? 0 : precision, maximumFractionDigits: precision });
	}

	function renderValue(field, doc, formatters = {}) {
		const custom = config.renderValue?.(field, doc, formatters, escapeHTML);
		if (custom !== undefined) return custom;
		const value = doc[field];
		if (value === undefined || value === null || value === "") return "—";
		if (NUMBERS.has(field)) {
			const number = Number(value);
			if (!Number.isFinite(number)) return "—";
			const percentage = field.startsWith("per_");
			const formatted = percentage && number === 0 ? "0" : escapeHTML(formatters.number ? formatters.number(number, field, doc) : number.toLocaleString(undefined, { minimumFractionDigits: percentage ? 0 : 2, maximumFractionDigits: 2 }));
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
		return JSON.stringify(args);
	}

	function providerActive(controller) { return Boolean(config.provider && (controller.pageSurface || controller.providerScope !== "orders")); }
	function displayColumns(controller) { return providerActive(controller) ? config.provider.columns : COLUMNS; }
	function displayPermissions(controller) { return providerActive(controller) ? controller.providerAllowed : controller.displayAllowed; }
	function currentRows(controller) { return providerActive(controller) ? controller.providerRows : controller.list.data; }

	function mount(list, root) {
		if (!isNativeList(list)) return null;
		if (list[config.controllerKey]) {
			list[config.controllerKey].activate();
			return list[config.controllerKey];
		}
		const frappe = root.frappe;
		const allowed = allowedFields(list.meta, (level) => frappe.perm.has_perm(DOCTYPE, level, "read"), frappe.model.std_fields_list);
		const missing = (config.optionalFields || []).filter((field) => !(list.meta?.fields || []).some((df) => df.fieldname === field));
		const displayAllowed = new Set(allowed);
		if (frappe.perm.has_perm(DOCTYPE, 0, "read")) for (const field of config.computedFields || []) displayAllowed.add(field);
		if (frappe.perm.has_perm(DOCTYPE, 0, "read")) {
			for (const field of config.legacyDisplayFields || []) if (missing.includes(field)) displayAllowed.add(field);
		}
		if (missing.length) frappe.show_alert?.({ message: (root.__ || ((x) => x))("申请来源字段尚未安装；当前显示可用的原生申请信息。"), indicator: "orange" });
		const key = preferenceKey(frappe.boot?.sitename || root.location?.host, frappe.session?.user);
		let saved;
		try { saved = JSON.parse(root.localStorage?.getItem(key) || "null"); } catch (_) { /* Browsers may disable storage. */ }
		const originals = {};
		for (const name of ["get_args", "get_call_args", "no_change", "prepare_data", "reset_defaults", "get_header_html", "get_list_row_html", "render_list", "render_count", "toggle_result_area", "on_filter_change", "process_document_refreshes", "debounced_refresh", "get_checked_items", "set_rows_as_checked", "on_row_checked", "before_render", "after_render"]) originals[name] = list[name];
		const providerAllowed = new Set(displayAllowed);
		for (const field of config.provider?.virtualFields || []) providerAllowed.add(field);
		let providerSaved;
		try { providerSaved = JSON.parse(root.localStorage?.getItem(`${key}:unified`) || "null"); } catch (_) { /* Local preferences are optional. */ }
		if (!providerSaved && saved && config.provider) providerSaved = { ...saved, columns: [...(saved.columns || []), ...(config.provider.newColumns || [])] };
		const controller = {
			list, root, allowed, displayAllowed, originals, quick: {}, controls: {}, resetting: false, preferences: normalizePreferences(saved, displayAllowed),
			providerAllowed, providerScope: "orders", providerRows: [], providerPayload: null, providerOrderBy: "transaction_date desc",
			nativePreferences: normalizePreferences(saved, displayAllowed), providerPreferences: config.provider ? normalizePreferences(providerSaved, providerAllowed, config.provider.columns) : null,
			page: 0, pageSize: 100, requestId: 0, querySignature: null, total: null, summary: [],
			translate: root.__ || ((label) => label),
			setPage(page) {
				this.page = Math.max(0, Number(page) || 0);
				list.start = this.page * this.pageSize;
				list.page_length = this.pageSize;
				list.last_args = null;
			},
			activate() {
				root.document?.body?.classList.toggle(config.routeClass, isListRoute(frappe));
				root.document?.body?.classList.toggle(`${config.routeClass}-readonly`, isListRoute(frappe) && providerActive(this));
				if (isListRoute(frappe) && providerActive(this)) config.provider.onActivate?.(this);
			},
			setProviderScope(scope, refresh = true) {
				if (!config.provider || !["all", "orders", "oa"].includes(scope)) return;
				if (providerActive(this)) this.providerPreferences = this.preferences; else this.nativePreferences = this.preferences;
				list.clear_checked_items?.();
				this.providerScope = scope;
				this.preferences = providerActive(this) ? this.providerPreferences : this.nativePreferences;
				this.providerRows = []; this.providerPayload = null; list.data = [];
				this.total = null; this.summary = []; this.querySignature = null; this.requestId++;
				this.setPage(0); this.savePreferences(); this.activate();
				this.$providerScope?.val(scope);
				this.$providerControls?.toggle(providerActive(this));
				for (const field of config.quickFields || []) if (field !== "company") this.controls[field]?.$wrapper?.toggle(!providerActive(this));
				list.page?.hide_actions_menu?.();
				if (providerActive(this)) list.page?.clear_primary_action?.();
				// Do not leave readonly OA rows onscreen after native actions become available.
				list.render_list();
				if (refresh) return this.refresh();
			},
			savePreferences() {
				this.preferences = normalizePreferences(this.preferences, displayPermissions(this), displayColumns(this));
				try { root.localStorage?.setItem(providerActive(this) ? `${key}:unified` : key, JSON.stringify(this.preferences)); } catch (_) { /* Rendering must work without storage. */ }
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
				return config.onColumnsChange?.(this);
			},
			async clearQuickFilters() {
				if (this.resetting) return;
				this.resetting = true;
				this.quick = {};
				this.setPage(0);
				try { await Promise.all(Object.values(this.controls).map((control) => control.set_value(""))); }
				finally { this.resetting = false; this.$providerControls?.find("input, select").val("").prop("checked", false); this.restoreSavedFilterLabel?.(); await this.refresh(); }
			},
			async exportCurrent() {
				if (providerActive(this)) return config.provider.exportCurrent(this);
				if (!frappe.model.can_export?.(DOCTYPE)) throw new Error("当前用户没有导出权限。");
				const args = buildRequests(list.get_args(), this.preferences.columns, allowed).export;
				if (!root.DeepLinkERPPurchaseOrderExport?.exportExcel) await frappe.require("/assets/deeplinkerp_branding/js/purchase_order_export.js");
				if (!root.DeepLinkERPPurchaseOrderExport?.exportExcel) throw new Error("Excel 导出组件加载失败，请刷新页面后重试。");
				await root.DeepLinkERPPurchaseOrderExport.exportExcel(root, args, config.exportOptions?.(args, this));
			},
			refresh() {
				this.activate();
				list.last_args = null;
				return list.refresh();
			},
		};
		list[config.controllerKey] = controller;
		controller.setPage(0);
		list.selected_page_count = 100;
		for (const field of new Set([...COLUMNS.map((col) => col.fieldname), ...(config.extraFields || []), list.workflow_state_fieldname])) {
			if (allowed.has(field) && !list.fields.some((entry) => fieldName(entry) === field)) list.fields.push([field, DOCTYPE]);
		}

		list.get_args = function () {
			if (providerActive(controller)) {
				let args;
				try { args = config.provider.request(controller).args; }
				catch (error) { if (config.provider.onQueryError?.(controller, error)) return this.get_args(); throw error; }
				const { start, page_length, ...scope } = args;
				const signature = JSON.stringify(scope);
				if (controller.querySignature !== null && signature !== controller.querySignature) {
					controller.setPage(0); controller.total = null; controller.providerPayload = null;
					args.start = 0;
				}
				controller.querySignature = signature;
				args.start = controller.page * controller.pageSize;
				args.page_length = controller.pageSize;
				return args;
			}
			const nativeArgs = originals.get_args.call(this);
			if (controller.quick.search && nativeArgs.or_filters?.length) {
				controller.quick.search = "";
				controller.searchControl?.$input?.val("");
				frappe.show_alert?.({ message: controller.translate(config.searchConflictMessage || "现有 OR 筛选已保留；请清除这些条件后使用订单/供应商搜索。"), indicator: "orange" });
			}
			const baseArgs = buildQuery(nativeArgs, controller.quick, allowed);
			const args = config.transformQuery?.(baseArgs, controller) || baseArgs;
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
			if (providerActive(controller)) { call.method = config.provider.request(controller).method; call.args = this.get_args(); }
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
			if (!unchanged && callRequests.has(call)) {
				callRequests.get(call).id = ++controller.requestId;
				config.onRequestStart?.(controller);
			}
			return unchanged;
		};
		list.prepare_data = function (response) {
			const request = responseRequests.get(response);
			// Compare the current filters too: a pending throttled refresh may not have issued its new request yet.
			const current = this.get_args();
			if (request && (request.id !== controller.requestId || request.key !== requestKey(current))) return;
			if (providerActive(controller)) {
				controller.providerPayload = response.message || {};
				controller.providerRows = controller.providerPayload.rows || [];
				controller.total = Number(controller.providerPayload.total_count || 0);
				this.total_count = controller.total;
				// Read-only union records never enter native PO selection or document actions.
				this.data = [];
				config.provider.onPayload?.(controller);
				return;
			}
			const start = this.start;
			this.start = 0;
			originals.prepare_data.call(this, response);
			this.start = start;
			config.onRows?.(controller);
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
		list.get_checked_items = function (...args) { return providerActive(controller) ? [] : originals.get_checked_items?.apply(this, args) || []; };
		list.set_rows_as_checked = function (...args) { if (!providerActive(controller)) return originals.set_rows_as_checked?.apply(this, args); };
		if (config.keepColumnHeader) list.on_row_checked = function (...args) {
			const result = originals.on_row_checked?.apply(this, args);
			// Keep native checks, bulk permissions and actions; only replace its header presentation.
			this.$list_head_subject?.show();
			this.$checkbox_actions?.hide();
			const checked = this.$checks?.length || 0;
			this.$list_head_subject?.find(".list-check-all").prop("checked", checked > 0 && checked === this.data.length).prop("indeterminate", checked > 0 && checked < this.data.length);
			config.onSelectionChange?.(controller);
			return result;
		};
		for (const name of ["before_render", "after_render"]) list[name] = function (...args) { if (!providerActive(controller)) return originals[name]?.apply(this, args); };
		if (config.provider && list.setup_realtime_updates) {
			const nativeSetupRealtime = list.setup_realtime_updates;
			list.setup_realtime_updates = function (...args) {
				const result = nativeSetupRealtime.apply(this, args);
				if (providerActive(controller)) config.provider.onActivate?.(controller);
				return result;
			};
		}
		list.get_header_html = () => headerHTML(controller);
		list.get_list_row_html = (doc) => rowHTML(controller, doc);
		list.render_list = function () {
			this.$result?.find(".list-row-container").remove();
			this.$list_head_subject = null;
			this.$checkbox_actions = null;
			this.render_header();
			currentRows(controller).forEach((doc, index) => {
				doc._idx = index;
				this.$result?.append(this.get_list_row_html(doc));
			});
			config.afterRender?.(controller);
			if (providerActive(controller) && !currentRows(controller).length) this.$result?.append('<div class="list-row-container dlp-provider-empty text-muted text-center" role="status">没有符合条件的采购记录</div>');
		};
		list.toggle_result_area = function () {
			if (!providerActive(controller)) originals.toggle_result_area.call(this);
			else { this.$no_result?.hide(); this.page?.hide_actions_menu?.(); this.page?.clear_primary_action?.(); }
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
		const cols = controller.preferences.columns.map((field) => displayColumns(controller).find((col) => col.fieldname === field)).filter(Boolean);
		const lastFrozen = cols.findIndex((col) => col.fieldname === (providerActive(controller) ? config.provider.freezeUntil : config.freezeUntil));
		let left = 76;
		return cols.map((col, index) => {
			const frozen = lastFrozen >= 0 && index <= lastFrozen;
			const result = { ...col, frozen, left };
			left += col.width;
			return result;
		});
	}

	function cellHTML(col, value, title = "", header = false, readonly = false) {
		const classes = ["dlp-po-grid-cell", "ellipsis", col.frozen ? "dlp-po-frozen" : "", NUMBERS.has(col.fieldname) ? "dlp-po-number" : "", DATES.has(col.fieldname) ? "dlp-po-date" : "", col.fieldname === "status" ? "dlp-po-status" : "", col.fieldname === "name" ? "list-subject" : ""].filter(Boolean).join(" ");
		return `<div class="${classes}" data-fieldname="${col.fieldname}" style="--dlp-po-left:${col.left}px;width:${col.width}px" title="${escapeHTML(title)}"${header ? ` data-${readonly ? "provider-sort" : "sort-by"}="${col.fieldname}"` : ""}>${value}</div>`;
	}

	function template(controller) {
		return `36px 40px ${layout(controller).map((col) => `${col.width}px`).join(" ")}`;
	}

	function selectionCell(html, sequence) {
		return `<div class="dlp-po-grid-cell dlp-po-frozen select-like" data-fieldname="_select" style="--dlp-po-left:0px;width:36px">${html}</div><div class="dlp-po-grid-cell dlp-po-frozen dlp-po-number" data-fieldname="_sequence" style="--dlp-po-left:36px;width:40px">${sequence}</div>`;
	}

	function headerHTML(controller) {
		const { translate: t, list } = controller;
		const readonly = providerActive(controller);
		const checkbox = readonly ? "" : `<input class="list-header-checkbox list-check-all" type="checkbox" title="${escapeHTML(t("Select All"))}">`;
		const columns = layout(controller).map((col) => {
			const label = t(col.label);
			return cellHTML(col, escapeHTML(label), label, readonly ? (config.provider.sortFields || []).includes(col.fieldname) : controller.allowed.has(col.fieldname), readonly);
		}).join("");
		return `<div class="list-row-container"><header class="list-row-head dlp-po-grid-header" style="--dlp-po-columns:${template(controller)}"><div class="list-header-subject dlp-po-grid-header-columns">${selectionCell(checkbox, "#")}${columns}</div><div class="checkbox-actions" style="display:none"><span class="select-like">${checkbox}</span><span class="list-header-meta"></span></div></header></div>`;
	}

	function rowHTML(controller, doc) {
		const { list, root } = controller;
		const readonly = providerActive(controller);
		const formatters = {
			allowed: controller.allowed,
			translate: controller.translate,
			number: (value, field) => formatNumber(root, value, field),
			date: (value) => root.frappe.datetime?.str_to_user ? root.frappe.datetime.str_to_user(value) : value,
		};
		const checkbox = readonly ? "" : `<input type="checkbox" class="list-row-checkbox" data-doctype="${DOCTYPE}" data-name="${escapeHTML(doc.name)}">`;
		const cells = layout(controller).map((col) => {
			let value = (readonly ? config.provider.renderValue?.(col.fieldname, doc, formatters, escapeHTML) : undefined) ?? renderValue(col.fieldname, doc, formatters);
			if (col.fieldname === "name") value = config.renderLink?.(controller, doc, value) ?? `<a href="${escapeHTML(readonly ? config.provider.formLink(doc) : list.get_form_link(doc))}" data-name="${escapeHTML(doc.name)}">${value}</a>`;
			if (col.fieldname === "supplier_name" && doc.supplier) value = `<a href="/desk/supplier/${encodeURIComponent(doc.supplier)}">${value}</a>`;
			if (col.fieldname === "status" && (!readonly || config.provider.useNativeIndicator?.(doc))) value = list.get_indicator_html?.(doc, Boolean(list.workflow_state_fieldname)) || value;
			const raw = doc[col.fieldname];
			return cellHTML(col, value, controller.allowed.has(col.fieldname) && (raw === null || typeof raw !== 'object') ? raw ?? "—" : "");
		}).join("");
		const sequence = controller.page * controller.pageSize + (doc._idx || 0) + 1;
		return `<div class="list-row-container" tabindex="0"><div class="level ${readonly ? "dlp-po-readonly-row" : "list-row"} dlp-po-grid-row" style="--dlp-po-columns:${template(controller)}">${selectionCell(checkbox, config.renderSequence?.(controller, doc, sequence) ?? sequence)}${cells}</div>${config.rowExtra?.(controller, doc) || ""}</div>`;
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
		let filterHost = list.page.wrapper.find(".page-form").first();
		if (controller.pageSurface) {
			list.page.show_form?.();
			filterHost = list.page.page_form || filterHost;
			if (!filterHost.length) filterHost = $('<div class="page-form row"></div>').prependTo(list.page.main);
			filterHost.removeClass('hide').show();
		}
		controller.$filters = $('<div class="dlp-po-filters"></div>').prependTo(filterHost);
		const controls = (config.controls || []).map((control) => ({ ...control }));
		for (const control of controls) {
			if (control.fieldname !== "search" && !controller.allowed.has(control.permission_field || control.fieldname)) continue;
			const field = list.meta.fields.find((df) => df.fieldname === control.fieldname);
			if (control.fieldtype === "Select") control.options = selectOptions(control, field, t);
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
		// Move the native button itself so its advanced/saved-filter handlers survive.
		list.page.wrapper.find(".page-form .filter-x-button").off("click.dlpPOFilters").on("click.dlpPOFilters", () => controller.clearQuickFilters())
			.text(t("清空筛选")).attr("title", t("清空筛选")).attr("aria-label", t("清空筛选")).addClass("dlp-po-clear-filters").appendTo(controller.$filters);
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
		config.provider?.mountControls?.(controller);
		config.mountControls?.(controller);
		if (config.dismissInitialOnboarding) dismissAutomaticOnboarding(controller, root);
		paintSummary(controller);
	}

	function dismissAutomaticOnboarding(controller, root) {
		if (controller.initialOnboardingDismissed || controller.stopInitialOnboarding || !root.document || !root.MutationObserver) return;
		let observer, timer, stopped = false;
		const cleanup = () => {
			if (stopped) return;
			stopped = true; observer?.disconnect();
			if (timer !== undefined) (root.clearTimeout || clearTimeout)(timer);
			root.document.removeEventListener?.('click', manualStart, true);
			controller.stopInitialOnboarding = null;
		};
		controller.stopInitialOnboarding = cleanup;
		const manualStart = event => {
			if (event.target.closest?.('.onboarding-sidebar')) { controller.initialOnboardingDismissed = true; cleanup(); }
		};
		const closeInitial = () => {
			if (stopped) return;
			const active = config.pageRoute ? (root.frappe.get_route?.() || [])[0] === config.pageRoute : isListRoute(root.frappe);
			if (!active) return cleanup();
			const close = root.document.querySelector('.user-onboarding')?.querySelector('.onb-header-actions button:has(use[href="#icon-x"])');
			if (close) { controller.initialOnboardingDismissed = true; close.click(); cleanup(); }
		};
		// Observe only a bounded initial load, including delayed native mount.
		// Capture the real Getting Started entry before native code opens it.
		observer = new root.MutationObserver(closeInitial);
		observer.observe(root.document.querySelector('.user-onboarding') || root.document.body, { childList: true, subtree: true });
		root.document.addEventListener?.('click', manualStart, true);
		timer = (root.setTimeout || setTimeout)(() => { controller.initialOnboardingDismissed = true; cleanup(); }, 5000);
		closeInitial();
	}

	function paintSummary(controller) {
		const { translate: t, list } = controller;
		const count = controller.total === null ? "…" : controller.total.toLocaleString();
		const amounts = providerActive(controller) ? config.provider.summary(controller, escapeHTML) : controller.summary.map((row) => renderValue("grand_total", { grand_total: row._aggregate_column, currency: row.currency }, { number: (value, field) => formatNumber(controller.root, value, field) })).join(" · ");
		controller.$summary?.html(`${escapeHTML(t("Total"))}: ${escapeHTML(count)}${amounts ? ` · ${amounts}` : ""}`);
		const rows = currentRows(controller);
		const from = rows.length ? controller.page * controller.pageSize + 1 : 0;
		const to = rows.length ? controller.page * controller.pageSize + rows.length : 0;
		controller.$paging?.find(".dlp-po-page-info").text(`${from}–${to} / ${count}`);
		controller.$paging?.find(".dlp-po-previous").prop("disabled", controller.page === 0);
		controller.$paging?.find(".dlp-po-next").prop("disabled", controller.total === null || to >= controller.total || rows.length === 0);
	}

	function updateSummary(controller) {
		const { list, root } = controller;
		if (providerActive(controller)) { paintSummary(controller); return Promise.resolve(); }
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
		const columns = displayColumns(controller);
		const order = [...controller.preferences.columns, ...columns.map((col) => col.fieldname).filter((field) => displayPermissions(controller).has(field) && !visible.has(field))];
		const dialog = new root.frappe.ui.Dialog({ title: t("列设置"), fields: [{ fieldtype: "HTML", fieldname: "columns" }], primary_action_label: t("保存"), primary_action: () => {
			controller.setColumns(order.filter((field) => visible.has(field)));
			dialog.hide();
		} });
		const wrapper = dialog.fields_dict.columns.$wrapper;
		const draw = () => wrapper.html(`<div class="dlp-po-column-options">${order.map((field) => {
				const col = columns.find((col) => col.fieldname === field);
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
			root.document?.body?.classList.toggle(config.routeClass, isListRoute(frappe));
			const current = frappe.views?.list_view?.[DOCTYPE] || root.cur_list;
			root.document?.body?.classList.toggle(`${config.routeClass}-readonly`, isListRoute(frappe) && Boolean(current?.[config.controllerKey] && providerActive(current[config.controllerKey])));
			const list = frappe.views?.list_view?.[DOCTYPE] || root.cur_list;
			config.onRouteChange?.(list?.[config.controllerKey], isListRoute(frappe));
			if (!isListRoute(frappe)) list?.[config.controllerKey]?.stopInitialOnboarding?.();
			if (isListRoute(frappe) && isNativeList(list)) mount(list, root);
		});
	}

	// Standalone Page surface uses the same renderer, preferences and controls. It
	// is not a native ListView and never participates in native business selection.
	function mountPage(page, root) {
		const $ = root.$, frappe = root.frappe;
		const meta = frappe.get_meta?.(DOCTYPE) || { fields: config.controls || [] };
		const surface = { page, meta, data: [],
			$frappe_list: $('<div class="frappe-list dlp-page-grid"></div>').appendTo(page.main) };
		surface.$result = $('<div class="result"></div>').appendTo($('<div class="result-container"></div>').appendTo(surface.$frappe_list));
		surface.$paging_area = $('<div></div>').appendTo(surface.$frappe_list);
		const nativeAllowed = allowedFields(meta, level => frappe.perm?.has_perm ? frappe.perm.has_perm(DOCTYPE, level, 'read') : true, frappe.model.std_fields_list || ['name','owner','docstatus','creation','modified','modified_by','idx']);
		const permitted = new Set(nativeAllowed);
		for (const col of COLUMNS) {
			const source = config.pageFieldMap?.[col.fieldname];
			if (!source || nativeAllowed.has(source)) permitted.add(col.fieldname);
		}
		const key = preferenceKey(frappe.boot?.sitename || root.location?.host, frappe.session?.user);
		let saved; try { saved = JSON.parse(root.localStorage?.getItem(key) || 'null'); } catch (_) { /* Optional preferences. */ }
		const c = { pageSurface: true, root, list: surface, nativeAllowed, allowed: permitted, displayAllowed: permitted, providerAllowed: permitted,
			preferences: normalizePreferences(saved, permitted, config.provider.columns), controls: {}, quick: {}, resetting: false,
			providerRows: [], providerPayload: null, providerOrderBy: config.defaultSort || 'posting_date desc', page: 0, pageSize: 100, total: null, requestId: 0, querySignature: null,
			translate: root.__ || (x => x),
			setPage(value) { this.page = Math.max(0, Number(value) || 0); },
			activate() { root.document.body.classList.toggle(config.routeClass, active()); },
			savePreferences() { this.preferences = normalizePreferences(this.preferences, permitted, config.provider.columns); try { root.localStorage?.setItem(key, JSON.stringify(this.preferences)); } catch (_) { /* Rendering must work without storage. */ } surface.$frappe_list.toggleClass('dlp-po-standard', this.preferences.density === 'standard'); },
			setColumns(columns) { this.preferences.columns = columns; this.savePreferences(); render(); },
			async clearQuickFilters() { this.resetting = true; this.quick = {}; this.setPage(0); try { this.resetAdvancedFilters?.(); await Promise.all(Object.values(this.controls).map(control => control.set_value(''))); } finally { this.resetting = false; } return this.refresh(); },
			exportCurrent() { return config.provider.exportCurrent(this); },
			async refresh() {
				this.activate(); if (!active()) return;
				const request = config.provider.request(this), { start, page_length, ...scope } = request.args;
				const signature = JSON.stringify(scope);
				if (this.querySignature !== null && signature !== this.querySignature) this.setPage(0);
				this.querySignature = signature; request.args.start = this.page * this.pageSize; request.args.page_length = this.pageSize;
				const generation = ++this.requestId;
				try {
					const response = await frappe.call(request);
					if (generation !== this.requestId || !active() || requestKey(config.provider.request(this).args) !== requestKey(request.args)) return;
					this.providerPayload = response.message || {}; this.providerRows = this.providerPayload.rows || []; this.total = Number(this.providerPayload.total_count || 0);
					render(); config.provider.onPayload?.(this); paintSummary(this);
				} catch (error) { if (generation === this.requestId && active()) this.$summary.text('无权读取或加载失败，请核对系统提示。'); }
			},
		};
		function active() { return (frappe.get_route?.() || [])[0] === config.pageRoute; }
		function render() { surface.$result.html(headerHTML(c) + c.providerRows.map((row, index) => { row._idx = index; return rowHTML(c, row); }).join('')); if (!c.providerRows.length) surface.$result.append('<div class="dlp-provider-empty text-muted" role="status">没有符合条件的采购付款记录</div>'); config.afterRender?.(c); paintSummary(c); }
		surface.render_list = render; surface.refresh = () => c.refresh();
		mountControls(c); render(); c.activate();
		frappe.router?.on('change', () => { c.activate(); if (!active()) { c.requestId++; c.stopInitialOnboarding?.(); } });
		return c;
	}
	return { COLUMNS, escapeHTML, allowedFields, preferenceKey, normalizePreferences, selectOptions, buildQuery, buildRequests, currencyTotals, formatNumber, renderValue, mount, mountPage, install, dismissAutomaticOnboarding };
});
