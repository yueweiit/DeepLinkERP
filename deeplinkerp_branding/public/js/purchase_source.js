(function (root, factory) {
	if (typeof module === "object" && module.exports) module.exports = factory;
	else {
		root.deeplinkerp ||= {};
		root.deeplinkerp.purchaseSource ||= factory(root);
	}
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
	"use strict";
	const SERVICE = "deeplinkerp_branding.services.purchase_source_service.";
	const t = value => (root.__ || (text => text))(value);
	const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
	const labels = { region: "执行地区", currency: "币种", payee: "收款人", requested_amount: "申请金额", items: "需求明细", processors: "加工商明细", detail_total: "明细汇总金额", description: "采购说明", schedule_date: "交付日期", department: "申请部门", project: "项目", order_no: "来源订单编号", payments: "原单付款信息", payment_date: "原单付款日期", payment_terms: "付款条件", attachments: "关键凭证" };
	const text = value => value === undefined || value === null || value === "" ? "—" : esc(value);
	const exactDisplay = (value, format) => value == null || value === "" ? "—" : `<span title="${esc(t("原值"))} · ${esc(value)}">${format(value)}</span>`;
	const money = (value, currency) => exactDisplay(value, amount => root.DeepLinkERPPurchasePayments.formatMoney(amount, currency || "币种待确认"));
	const quantity = value => exactDisplay(value, amount => root.DeepLinkERPPurchasePayments.formatQuantity(amount));
	const poLink = name => `<a href="/desk/purchase-order/${encodeURIComponent(name)}">${esc(name)}</a>`;
	const call = async (method, args, options = {}) => (await root.frappe.call({ method: SERVICE + method, args, silent: true, ...options })).message;
	async function sync() {
		if (root.frappe.session?.user !== "Administrator" && !root.frappe.user_roles?.includes("System Manager")) throw new Error(t("采购来源同步需要管理员权限。"));
		const result = await call("sync_purchase_sources", {}, { type: "POST" });
		root.frappe.show_alert({ message: `${t("采购来源已同步")}${result?.count !== undefined ? ` · ${result.count} ${t("条")}` : ""}`, indicator: "green" });
		return result;
	}
	function readable(value) {
		if (typeof value === "string" && /^[\[{]/.test(value.trim())) { try { return readable(JSON.parse(value)); } catch (_) { /* Original text remains evidence. */ } }
		if (Array.isArray(value)) return `<ol>${value.map(item => `<li>${readable(item)}</li>`).join("")}</ol>`;
		if (value && typeof value === "object") return `<dl>${Object.entries(value).map(([key, item]) => `<dt>${esc(labels[key] || key)}</dt><dd>${readable(item)}</dd>`).join("")}</dl>`;
		return `<span class="dlp-source-text">${text(value)}</span>`;
	}
	function originalLink(source) {
		try {
			const url = new URL(source.source_url);
			if (url.protocol === "https:" && url.hostname === "aflow.dingtalk.com") return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(t("钉钉原单"))}</a>`;
		} catch (_) { /* Unavailable source URLs are not guessed. */ }
		return esc(t("钉钉原单链接暂不可用"));
	}
	function evidenceHTML(detail) {
		const source = detail.source, proof = detail.cashier || {};
		const cashier = proof.payment_evidence_status === "hidden" ? { payment_evidence_status: "hidden", issues: proof.issues } : proof;
		const facts = [["来源申请金额", money(source.requested_amount, source.currency)], ["来源明细金额", money(source.detail_total_amount, source.currency)], ["出纳实付（证据）", money(cashier.paid_amount, cashier.currency)], ["付款证据状态", text(cashier.payment_evidence_status === "hidden" ? "付款证据不可见" : cashier.payment_evidence_status === "recorded" ? "已记录" : "待核对")], ["申请日期", text(source.apply_date)], ["原交付日期", text(source.schedule_date)], ["原收款人", text(source.payee)]];
		const columns = [["item_code", "原物料编码"], ["item_name", "原物料名称"], ["qty", "原数量"], ["uom", "原单位"], ["amount", "原明细金额"]];
		const table = root.DeepLinkERPCompactList.detailTable({ columns, items: source.items || [], escape: esc, translate: t, format: (field, item) => field === "qty" ? quantity(item.qty) : field === "amount" ? money(item.amount, source.currency) : undefined, wrapperClass: "dlp-document-items", tableClass: "table-bordered" });
		const files = [...(source.attachment_manifest || []), ...(cashier.attachments || [])];
		const attachments = files.map(file => {
			const id = file.attachment_id, available = file.downloadable === true && id && file.version;
			const url = `/api/method/${SERVICE}download_source_attachment?name=${encodeURIComponent(detail.name)}&attachment_id=${encodeURIComponent(id)}&version=${encodeURIComponent(file.version)}`;
			return `<p>${available ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${text(file.filename || id)}</a>` : text(file.filename || id)} · ${esc(t(available ? "可下载证据" : "附件暂不可下载，请在原单核对"))}</p>`;
		}).join("") || `<p>${esc(t("暂无已归档附件，请在原单核对。"))}</p>`;
		const payments = (cashier.payments || []).map(payment => `<p>${text(payment.source_id)} · ${text(payment.payment_date)} · ${money(payment.amount, payment.currency)} · ${text(payment.payer)} · ${text(payment.evidence_status)}<br>${text(payment.remark)} · ${text(payment.bank_reference)}</p>`).join("") || `<p>${esc(t("尚无可核实的实际付款证据。"))}</p>`;
		return `<section class="dlp-source-evidence"><h4>${esc(t("采购来源"))} · ${text(source.business_id || detail.name)}</h4><p>${originalLink(source)} · <a href="/desk/oa-purchase-request/${encodeURIComponent(detail.name)}">${esc(t("OA 来源记录"))}</a></p><div class="dlp-source-facts">${facts.map(([label, value]) => `<div><strong>${esc(t(label))}</strong><span>${value}</span></div>`).join("")}</div><p class="text-muted">${esc(t("出纳实付是原付款证据；ERP 登记付款和核销在订单中另列。"))}</p>${[...(source.issues || []), ...(cashier.issues || [])].map(issue => `<p class="text-warning">${esc(issue)}</p>`).join("")}<h5>${esc(t("原始采购明细（只读）"))}</h5>${table}<details><summary>${esc(t("原始申请内容"))}</summary>${readable(source.original_fields || {})}</details><details><summary>${esc(t("出纳付款证据"))}</summary>${payments}${attachments}</details></section>`;
	}
	function value(control) {
		const raw = control?.$input?.val?.();
		if (!control?.dlpNumeric) return control?.get_value?.() ?? "";
		if (raw === "") return "";
		if (control.dlpManualValue !== undefined) return control.dlpManualValue;
		if (raw === control.dlpInitialDisplay) return control.dlpOriginalValue;
		return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(String(raw).trim()) ? String(raw).trim() : String(control.get_value());
	}
	async function open(name) {
		if (!name) return;
		const frappe = root.frappe, $ = root.$;
		const shellReady = () => ["createDrawer", "formatMoney", "formatQuantity", "formatNumericInput"].every(key => typeof root.DeepLinkERPPurchasePayments?.[key] === "function");
		if (!shellReady()) await frappe.require("/assets/deeplinkerp_branding/js/purchase_payments.js");
		const shell = root.DeepLinkERPPurchasePayments;
		if (!shellReady()) { frappe.msgprint(t("采购抽屉组件版本不完整，请整页刷新后重试。")); return; }
		const drawer = shell.createDrawer("完善/关联采购订单", true); if (!drawer) return;
		drawer.panel.find(".dlp-payment-body").html(`<p class="dlp-source-loading" role="status">${esc(t("正在读取采购来源…"))}</p><div class="dlp-error text-danger" role="alert"></div>`);
		let detail, rows = [], paymentRows = [], controls = new Map(), saved = null, confirming = false, uncertain = false, freshRead = false;
		const eligible = () => Boolean(detail?.source?.eligible && detail.can_write && !detail.purchase_order);
		const reviewable = () => Boolean(detail?.source?.eligible && detail.can_write && detail.purchase_order);
		const canReview = () => reviewable() && freshRead;
		const canReconcile = () => Boolean(detail?.source?.eligible && detail.can_reconcile && detail.purchase_order && detail.cashier?.payment_evidence_status === "recorded" && detail.cashier.paid_amount != null && Number(detail.cashier.paid_amount) > 0);
		const capture = () => ({ header: Object.fromEntries([...controls].filter(([field]) => !/_\d+$/.test(field)).map(([field, control]) => [field, value(control)])), items: rows.map((_, index) => Object.fromEntries(["item_code", "qty", "uom", "rate"].map(field => [field, value(controls.get(`${field}_${index}`))]))), paymentEntries: paymentRows.map((_, index) => value(controls.get(`payment_entry_${index}`))) });
		async function input(holder, fieldname, nativeType, nativeField, options, initial) {
			if (!drawer.alive()) return;
			// Dialog-only explanation is not a Purchase Order field or form write.
			const native = nativeType ? frappe.meta.get_docfield(nativeType, nativeField) : { fieldtype: options.fieldtype };
			if (!native) throw new Error(t("采购订单字段元数据不完整，请核对安装状态后刷新。"));
			const { label, fieldtype, ...presentation } = options;
			const overrides = Object.fromEntries(Object.entries(presentation).filter(([, option]) => option !== undefined));
			const numeric = ["Float", "Currency"].includes(native.fieldtype);
			const control = frappe.ui.form.make_control({ parent: holder, df: { ...native, ...overrides, fieldname, label: t(label), fieldtype: numeric ? native.fieldtype : fieldtype, only_select: 1, hidden: 0, read_only: 0, ignore_user_permissions: 0, depends_on: null, read_only_depends_on: null, mandatory_depends_on: null, fetch_from: null, default: null }, render_input: true });
			drawer.controls.push(control); controls.set(fieldname, control);
			control.$input?.attr("aria-label", t(label));
			control.get_doc = () => ({ currency: controls.get("currency")?.get_value() || "" });
			if (numeric) shell.formatNumericInput(control);
			await control.set_value(initial ?? "");
			if (!drawer.alive()) { shell.disposeControls(drawer.controls); return; }
			if (initial === undefined || initial === null || initial === "") control.$input?.val("");
			control.dlpNumeric = numeric; control.dlpOriginalValue = initial ?? ""; control.dlpInitialDisplay = control.$input?.val?.();
			if (numeric) {
				const node = control.$input?.get?.(0);
				const touched = () => { if (drawer.alive()) { const raw = control.$input.val(); control.dlpManualValue = raw === "" ? "" : /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(String(raw).trim()) ? String(raw).trim() : String(control.get_value()); } };
				if (node?.addEventListener) {
					for (const event of ["input", "change"]) node.addEventListener(event, touched, true);
					control.dlpDisposeInput = () => { for (const event of ["input", "change"]) node.removeEventListener(event, touched, true); };
				}
			}
			return control;
		}
		async function render() {
			if (!drawer.alive()) return;
			shell.disposeControls(drawer.controls); controls = new Map();
			drawer.panel.find("footer .dlp-source-create,footer .dlp-source-associate,footer .dlp-source-reload,footer .dlp-source-reconcile,footer .dlp-source-review").remove();
			const notice = detail.purchase_order ? `${esc(t("已关联采购订单"))} ${poLink(detail.purchase_order)}` : !detail.source.eligible ? esc(t("来源未满足当前审批条件，只可查看证据。")) : !detail.can_write ? esc(t("当前没有办理权限，或公司归属待核对，请核对系统提示。")) : !detail.can_create ? esc(t("当前没有新建采购订单权限，可以核对并关联已有订单。")) : esc(t("请确认已有公司、供应商和物料，再创建采购订单草稿。"));
			const review = canReview() ? `<section class="dlp-source-review-fields"><h4>${esc(t("复核现有关联"))}</h4><p>${esc(t("当前采购订单"))}：${poLink(detail.purchase_order)} · ${esc(t("仅复核，不替换关联或创建订单。"))}</p></section>` : detail.purchase_order ? `<p class="text-muted">${esc(t(!detail.source.eligible ? "来源审批未满足办理条件，只可查看证据。" : !detail.can_write ? "当前没有办理权限，只可查看证据。" : "请先刷新来源，核对当前证据后再复核现有关联。"))}</p>` : "";
			drawer.panel.find(".dlp-payment-body").html(`${evidenceHTML(detail)}<p class="text-warning">${notice}</p>${detail.reconciliation_notice ? `<p class="text-muted">${esc(detail.reconciliation_notice)}</p>` : ""}${review}${canReconcile() ? '<section class="dlp-source-reconciliation"><h4>核对历史付款</h4><p>选择已提交、已分配到本订单的原生付款单。核对仅保存对应关系。</p><div class="dlp-source-payment-entries"></div></section>' : ""}${eligible() ? '<section class="dlp-source-mapping"><h4>手工完善</h4><div class="dlp-document-fields"></div><div class="dlp-source-items"></div></section>' : ""}<div class="dlp-error text-danger" role="alert"></div>`);
			$("<button type='button' class='btn btn-default dlp-source-reload'>刷新来源</button>").appendTo(drawer.panel.find("footer")).on("click.dlpSource", () => load(true));
			if (canReview()) {
				await input($("<div></div>").appendTo(drawer.panel.find(".dlp-source-review-fields")), "correction_reason", null, null, { fieldtype: "Small Text", label: "完善/差异说明", reqd: 0 }, saved?.header?.correction_reason);
				if (!drawer.alive()) return;
				$("<button type='button' class='btn btn-primary dlp-source-review'>复核现有关联</button>").appendTo(drawer.panel.find("footer")).on("click.dlpSource", () => confirm("review"));
			}
			if (canReconcile()) await renderReconciliation();
			if (!eligible()) return;
			try { await frappe.model.with_doctype("Purchase Order"); if (!drawer.alive()) return; await frappe.model.with_doctype("Purchase Order Item"); }
			catch (_) { throw new Error(t("采购订单字段元数据读取失败，请核对安装状态和权限后刷新。")); }
			if (!drawer.alive()) return;
			const initial = saved?.header || { company: detail.target_company || "", currency: detail.source.currency || "", schedule_date: /^\d{4}-\d{2}-\d{2}$/.test(detail.source.schedule_date || "") ? detail.source.schedule_date : "" };
			for (const [field, fieldtype, options, label] of [["company", "Link", "Company", "公司"], ["supplier", "Link", "Supplier", "已有供应商"], ["currency", "Link", "Currency", "币种"], ["schedule_date", "Date", null, "需求日期"], ["correction_reason", "Small Text", null, "完善/差异说明"], ["purchase_order", "Link", "Purchase Order", "关联已有采购订单"]]) {
				if (!drawer.alive()) return;
				await input($("<div></div>").appendTo(drawer.panel.find(".dlp-document-fields")), field, field === "correction_reason" ? null : "Purchase Order", field === "purchase_order" ? "amended_from" : field, { fieldtype, options, label, reqd: ["company", "supplier", "currency", "schedule_date"].includes(field) ? 1 : 0 }, initial[field]);
			}
			if (!drawer.alive()) return;
			rows = saved?.items || (detail.source.items?.length ? detail.source.items.map(item => ({ item_code: item.item_code, qty: item.qty, uom: item.uom, rate: null })) : [{}]);
			await renderItems(); if (!drawer.alive()) return;
			if (detail.can_create) $("<button type='button' class='btn btn-primary dlp-source-create'>创建采购订单草稿</button>").appendTo(drawer.panel.find("footer")).on("click.dlpSource", () => confirm("create"));
			$("<button type='button' class='btn btn-default dlp-source-associate'>确认关联已有订单</button>").appendTo(drawer.panel.find("footer")).on("click.dlpSource", () => confirm("associate"));
		}
		async function renderReconciliation() {
			try { await frappe.model.with_doctype("Payment Entry"); } catch (_) { throw new Error(t("付款单字段元数据读取失败，请核对安装状态和权限。")); }
			if (!drawer.alive()) return;
			paymentRows = saved?.paymentEntries?.length ? saved.paymentEntries : [""];
			const holder = drawer.panel.find(".dlp-source-payment-entries");
			for (const [index, name] of paymentRows.entries()) {
				if (!drawer.alive()) return;
				const control = await input($("<div></div>").appendTo(holder), `payment_entry_${index}`, "Payment Entry", "amended_from", { fieldtype: "Link", options: "Payment Entry", label: "原生付款单" }, name);
				if (control) control.get_query = () => ({ filters: { docstatus: 1, payment_type: "Pay", ...(detail.target_company ? { company: detail.target_company } : {}) } });
			}
			$("<button type='button' class='btn btn-default dlp-source-add-payment'>添加付款单</button>").appendTo(holder).on("click.dlpSource", async () => {
				if (drawer.busy || confirming || !drawer.alive()) return;
				saved = capture(); saved.paymentEntries.push(""); drawer.setBusy(true);
				try { await render(); } catch (error) { if (drawer.alive()) drawer.error(error); } finally { if (drawer.alive()) drawer.setBusy(false); }
			});
			$("<button type='button' class='btn btn-primary dlp-source-reconcile'>确认历史付款核对</button>").appendTo(drawer.panel.find("footer")).on("click.dlpSource", () => confirm("reconcile"));
		}
		async function renderItems() {
			const columns = [["item_code", "已有物料", "Link", "Item"], ["qty", "数量", "Float"], ["uom", "单位", "Link", "UOM"], ["rate", "单价", "Currency"]];
			drawer.panel.find(".dlp-source-items").html(`<div class="dlp-document-items"><table class="table table-bordered"><thead><tr>${columns.map(([, label]) => `<th>${esc(t(label))}</th>`).join("")}<th></th></tr></thead><tbody>${rows.map((_, index) => `<tr>${columns.map(([field]) => `<td data-source-field="${field}_${index}"></td>`).join("")}<td><button type="button" class="btn btn-link dlp-source-remove-item" data-index="${index}">${esc(t("移除"))}</button></td></tr>`).join("")}</tbody></table></div><button type="button" class="btn btn-default dlp-source-add-item">${esc(t("添加物料"))}</button><p class="text-muted">${esc(t("数量和单价须明确填写；缺失值保持空白。"))}</p>`);
			for (const [index, row] of rows.entries()) for (const [field, label, fieldtype, options] of columns) {
				if (!drawer.alive()) return;
				await input(drawer.panel.find(`[data-source-field="${field}_${index}"]`), `${field}_${index}`, "Purchase Order Item", field, { fieldtype, options, label, reqd: 1 }, row[field]);
			}
			const redraw = async change => {
				if (drawer.busy || confirming || !drawer.alive()) return;
				saved = capture(); change(saved.items); drawer.setBusy(true);
				try { await render(); } catch (error) { if (drawer.alive()) drawer.error(error); } finally { if (drawer.alive()) drawer.setBusy(false); }
			};
			drawer.panel.find(".dlp-source-add-item").on("click.dlpSource", () => redraw(items => items.push({})));
			drawer.panel.find(".dlp-source-remove-item").on("click.dlpSource", event => redraw(items => items.splice(Number(event.currentTarget.dataset.index), 1)));
		}
		function confirm(action) {
			const permitted = () => action === "reconcile" ? canReconcile() : action === "review" ? canReview() : eligible();
			if (!drawer.alive() || drawer.busy || confirming || uncertain || !permitted()) return;
			const data = capture(), header = data.header, items = data.items;
			if (action === "create" && (!detail.can_create || !["company", "supplier", "currency", "schedule_date"].every(field => header[field]) || !items.length || items.some(item => !item.item_code || !item.uom || item.qty === "" || item.rate === "" || !Number.isFinite(Number(item.qty)) || Number(item.qty) <= 0 || !Number.isFinite(Number(item.rate)) || Number(item.rate) < 0))) { drawer.error(new Error(t("请填写公司、已有供应商、币种、需求日期，以及每行物料、正数数量、单位和明确单价。"))); return; }
			if (action === "associate" && !header.purchase_order) { drawer.error(new Error(t("请选择要关联的已有采购订单。"))); return; }
			const paymentEntries = data.paymentEntries.filter(Boolean);
			if (action === "reconcile" && !paymentEntries.length) { drawer.error(new Error(t("请明确选择历史原生付款单。"))); return; }
			const args = { name: detail.name, expected_version: detail.version, ...(action === "reconcile" ? { payment_entries: JSON.stringify(paymentEntries) } : { correction_reason: header.correction_reason || "", ...(action === "create" ? { company: header.company, supplier: header.supplier, currency: header.currency, schedule_date: header.schedule_date, items: JSON.stringify(items) } : { purchase_order: action === "review" ? detail.purchase_order : header.purchase_order }) }) };
			const summary = action === "create" ? `<p>${esc(header.company)} · ${esc(header.supplier)} · ${esc(header.currency)} · ${esc(header.schedule_date)}</p>${items.map(item => `<p>${esc(item.item_code)} · ${quantity(item.qty)} ${esc(item.uom)} × ${money(item.rate, header.currency)}</p>`).join("")}` : ["associate", "review"].includes(action) ? `<p>${esc(args.purchase_order)}</p><p>${esc(header.correction_reason || "")}</p>` : `<p>${paymentEntries.map(esc).join(" · ")}</p>`;
			confirming = true;
			frappe.confirm(`${esc(t(action === "create" ? "确认创建采购订单草稿？创建后请在订单核对。" : action === "associate" ? "确认将此来源关联到所选采购订单？" : action === "review" ? "确认复核现有关联？不创建或替换采购订单。" : "确认核对历史付款并保存对应关系？"))}${summary}`, async () => {
				confirming = false;
				if (!drawer.alive() || drawer.busy || uncertain || !permitted()) return;
				drawer.setBusy(true);
				try {
					const result = await call({ create: "create_purchase_order_from_source", associate: "associate_purchase_order", review: "associate_purchase_order", reconcile: "confirm_historical_payments" }[action], args);
					if (!drawer.alive()) return;
					if (action === "reconcile") { frappe.show_alert({ message: t("历史付款已核对"), indicator: "green" }); drawer.setBusy(false); await load(); return; }
					if (!result?.name || result.doctype !== "Purchase Order") throw new Error(t("操作结果未确认，请刷新来源核对。"));
					frappe.show_alert({ message: t(action === "create" ? "采购订单草稿已创建" : action === "review" ? "现有关联已复核" : "采购来源已关联"), indicator: "green" });
					drawer.close(true); shell.openNative("Purchase Order", result.name);
				} catch (error) { if (drawer.alive()) { uncertain = true; drawer.error(new Error(`${error.message || t("操作未确认")}；${t("请先刷新来源或核对采购订单，再继续办理。")}`)); } }
				finally { if (drawer.alive()) drawer.setBusy(false); }
			}, () => { confirming = false; });
		}
		async function load(fresh = false) {
			if (!drawer.alive() || drawer.busy || confirming) return;
			if (controls.size) saved = capture();
			const generation = ++drawer.loadId; uncertain = true; freshRead = false; drawer.setBusy(true);
			try {
				const result = await call("get_purchase_source_detail", { name, ...(fresh ? { fresh: 1 } : {}) });
				if (!drawer.alive() || generation !== drawer.loadId) return;
				if (!result?.source || !result.name || !result.version) throw new Error(t("采购来源详情不完整，请核对同步和权限后刷新。"));
				detail = result; freshRead = fresh; uncertain = false; await render();
			} catch (error) { if (drawer.alive()) { uncertain = true; drawer.panel.find(".dlp-source-loading").text(t("采购来源读取未完成，请核对同步状态或权限。")); drawer.error(new Error(error.message || t("采购来源不可用或无权查看，请核对系统提示。"))); } }
			finally { if (drawer.alive() && generation === drawer.loadId) drawer.setBusy(false); }
		}
		await load(); return drawer;
	}
	if (root.document) root.document.addEventListener("click", event => {
		const button = event.target.closest?.("[data-purchase-source]"); if (!button) return;
		event.preventDefault(); event.stopPropagation();
		open(button.dataset.purchaseSource).catch(error => root.frappe.msgprint({ message: esc(error.message || t("采购来源读取失败，请刷新重试。")), indicator: "red" }));
	}, true);
	return { open, sync };
});
