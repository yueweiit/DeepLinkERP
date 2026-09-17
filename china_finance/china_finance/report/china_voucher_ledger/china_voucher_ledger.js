frappe.query_reports["China Voucher Ledger"] = {
	filters: [
		{
			fieldname: "company",
			label: __("公司"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
		},
		{
			fieldname: "period_preset",
			label: __("凭证日期"),
			fieldtype: "Select",
			options: ["", __("本月凭证"), __("上月凭证"), __("近三个月"), __("本年凭证")],
			default: __("本月凭证"),
			on_change: (report) => {
				const preset = report.get_filter_value("period_preset");
				if (preset) set_quick_period(report, preset);
			},
		},
		{ fieldname: "from_date", label: __("起始日期"), fieldtype: "Date", reqd: 1 },
		{ fieldname: "to_date", label: __("截止日期"), fieldtype: "Date", reqd: 1 },
		{ fieldname: "voucher_word", label: __("凭证字号"), fieldtype: "Data" },
		{
			fieldname: "voucher_status",
			label: __("状态"),
			fieldtype: "Select",
			options: ["", __("已记账"), __("已冲销")],
		},
		{ fieldname: "accounting_period", label: __("会计期间"), fieldtype: "Data" },
		{
			fieldname: "source_doctype",
			label: __("来源类型"),
			fieldtype: "Select",
			options: ["", "Journal Entry", "Payment Entry", "Period Closing Voucher"],
		},
		{ fieldname: "source_name", label: __("来源单据"), fieldtype: "Data" },
		{ fieldname: "voucher_number", label: __("凭证编号"), fieldtype: "Data" },
		{ fieldname: "account", label: __("科目"), fieldtype: "Link", options: "Account" },
		{
			fieldname: "party_type",
			label: __("往来类型"),
			fieldtype: "Select",
			options: ["", "Customer", "Supplier", "Employee", "Shareholder"],
		},
		{ fieldname: "party", label: __("往来单位"), fieldtype: "Data" },
		{ fieldname: "search_text", label: __("关键词"), fieldtype: "Data" },
	],
	tree: false,
	get_datatable_options(datatable_options) {
		// Keep one fixed width for each column so every row stays aligned.
		datatable_options.layout = "fixed";
		return datatable_options;
	},
	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (column.fieldname === "voucher_status" && data?.voucher_status !== undefined && data?.voucher_status !== null) {
			const status = {
				0: [__("草稿"), "orange"],
				1: [__("已记账"), "green"],
				2: [__("已冲销"), "red"],
			}[data.voucher_status];
			if (!status) return "";
			return `<span class="indicator-pill no-indicator-dot china-voucher-status-text ${status[1]}">${status[0]}</span>`;
		}
		if (column.fieldname === "statutory_number" && data?.source_doctype && data?.source_name) {
			const route = frappe.utils.get_form_link(data.source_doctype, data.source_name);
			return `<a href="${route}" class="china-voucher-link" data-source-doctype="${encodeURIComponent(data.source_doctype)}" data-source-name="${encodeURIComponent(data.source_name)}">${formatted}</a>`;
		}
		const editable_source_doctypes = ["Journal Entry", "Payment Entry"];
		if (
			column.fieldname === "source_action" &&
			data?.source_doctype &&
			editable_source_doctypes.includes(data.source_doctype) &&
			data?.source_name
		) {
			return `<button type="button" class="btn btn-xs btn-default china-voucher-edit-source" data-source-doctype="${encodeURIComponent(data.source_doctype)}" data-source-name="${encodeURIComponent(data.source_name)}">${__("编辑来源凭证")}</button>`;
		}
		if (!data || !["posting_date", "statutory_number", "accounting_period"].includes(column.fieldname)) {
			return formatted;
		}
		const index = Number.isInteger(row?._index) ? row._index : frappe.query_report.data?.indexOf(data);
		const previous = index > 0 ? frappe.query_report.data?.[index - 1] : null;
		if (previous && previous.voucher_snapshot === data.voucher_snapshot) return "";
		return formatted;
	},
	onload(report) {
		report.page.wrapper.addClass("china-voucher-ledger-report");
		ensure_voucher_ledger_styles();
		report.page.wrapper.on("click", ".china-voucher-link", (event) => {
			event.preventDefault();
			const source_doctype = decodeURIComponent(event.currentTarget.dataset.sourceDoctype);
			const source_name = decodeURIComponent(event.currentTarget.dataset.sourceName);
			frappe.set_route("Form", source_doctype, source_name);
		});
		bind_voucher_source_edit_click(report);
		report.page.wrapper.on("click", ".china-voucher-snapshot-link", (event) => {
			event.preventDefault();
			const snapshot_name = decodeURIComponent(event.currentTarget.dataset.snapshotName);
			frappe.set_route("Form", "China Accounting Voucher", snapshot_name);
		});
		start_voucher_ledger_floating_scroll(report);
		if (!report.get_filter_value("company")) {
			show_company_selector(report);
		}
		if (!report.get_filter_value("from_date") || !report.get_filter_value("to_date")) {
			const today = frappe.datetime.get_today();
			report.set_filter_value({
				period_preset: __("本月凭证"),
				from_date: frappe.datetime.month_start(today),
				to_date: frappe.datetime.month_end(today),
			});
		}
	},
};

function bind_voucher_source_edit_click(report) {
	const page_wrapper = report?.page?.wrapper?.[0] || report?.page?.wrapper;
	if (!page_wrapper?.addEventListener) return;

	if (report._china_voucher_source_edit_click_handler) {
		page_wrapper.removeEventListener(
			"click",
			report._china_voucher_source_edit_click_handler,
			true
		);
	}

	// Capture before DataTable handles the click. Its own cell handler can stop
	// bubbling, which prevents delegated handlers on the report wrapper from
	// seeing clicks on buttons rendered inside a cell.
	report._china_voucher_source_edit_click_handler = (event) => {
		const target = event.target instanceof Element ? event.target : event.target?.parentElement;
		const button = target?.closest?.(".china-voucher-edit-source");
		if (!button || !page_wrapper.contains(button)) return;

		event.preventDefault();
		event.stopPropagation();
		edit_source_voucher(report, button);
	};
	page_wrapper.addEventListener("click", report._china_voucher_source_edit_click_handler, true);
}

function show_company_selector(report) {
	if (report._china_voucher_company_dialog_open) return;

	// Query Report calls refresh immediately after onload. Hold that first
	// refresh until a company has been explicitly selected in the dialog.
	report._china_voucher_company_refresh_pending = true;
	if (!report._china_voucher_company_refresh_guarded) {
		const original_refresh = report.refresh;
		report._china_voucher_company_refresh_guarded = true;
		report.refresh = function (...args) {
			if (this._china_voucher_company_refresh_pending) {
				return Promise.resolve();
			}
			return original_refresh.apply(this, args);
		};
	}

	report._china_voucher_company_dialog_open = true;
	const dialog = new frappe.ui.Dialog({
		title: __("选择公司"),
		fields: [
			{
				fieldname: "company",
				label: __("公司"),
				fieldtype: "Link",
				options: "Company",
				reqd: 1,
				default: frappe.defaults.get_user_default("Company") || "",
			},
		],
		size: "small",
	});

	dialog.set_primary_action(__("查询"), () => {
		const values = dialog.get_values();
		if (!values || !values.company) return;

		// Keep the report filter as the source of truth so the existing filter,
		// URL filters, and subsequent company changes continue to work normally.
		report.set_filter_value("company", values.company);
		report._china_voucher_company_refresh_pending = false;
		dialog.hide();
		report.refresh(true);
	});

	dialog.onhide = () => {
		report._china_voucher_company_dialog_open = false;
		// Closing without a selection leaves the original mandatory filter
		// behavior available for manual selection in the report filter area.
		if (!report.get_filter_value("company")) {
			report._china_voucher_company_refresh_pending = false;
		}
	};

	dialog.show();
}

function edit_source_voucher(report, button) {
	const source_doctype = decodeURIComponent(button.dataset.sourceDoctype || "");
	const source_name = decodeURIComponent(button.dataset.sourceName || "");
	if (!source_doctype || !source_name) {
		frappe.msgprint({
			message: __("没有找到来源凭证信息，请刷新报表后重试"),
			indicator: "orange",
			title: __("无法编辑来源凭证"),
		});
		return;
	}

	const show_edit_error = (error) => {
		button.disabled = false;
		frappe.msgprint({
			message: error?.message || error?.exc || __("检查来源凭证失败，请稍后重试"),
			indicator: "red",
			title: __("编辑来源凭证失败"),
		});
	};

	button.disabled = true;
	frappe.call({
		method: "china_finance.services.source_voucher_edit.get_source_edit_status",
		args: { source_doctype, source_name },
		freeze: true,
		freeze_message: __("正在检查凭证修改条件…"),
		callback: (response) => {
			button.disabled = false;
			const status = response.message || {};
			if (!status.can_edit) {
				show_source_edit_blocker(status);
				return;
			}
			if (status.action === "open_draft") {
				frappe.set_route("Form", source_doctype, source_name);
				return;
			}

			frappe.confirm(
				__("该凭证已提交。系统会先取消原凭证，再生成修订草稿；原中国会计凭证快照会保留为历史记录。是否继续？"),
				() => {
					button.disabled = true;
					frappe.call({
						method: "china_finance.services.source_voucher_edit.prepare_source_voucher_edit",
						args: { source_doctype, source_name },
						freeze: true,
						freeze_message: __("正在取消原凭证并创建修订草稿…"),
						callback: (amend_response) => {
							const result = amend_response.message || {};
							if (result.name) {
								frappe.show_alert({
									message: result.message || __("修订草稿已生成，请修改后保存并记账"),
									indicator: "orange",
								});
								frappe.set_route("Form", source_doctype, result.name);
								return;
							}
							show_edit_error({ message: __("后台未返回修订草稿，请刷新报表后重试") });
						},
						error: show_edit_error,
						always: () => {
							button.disabled = false;
						},
					});
				},
			);
		},
		error: show_edit_error,
	});
}

function show_source_edit_blocker(status) {
	const reason = frappe.utils.escape_html(status.reason || __("当前凭证不满足修改条件"));
	const quick_unreconcile = status.quick_unreconcile;
	const bank_transactions = (status.bank_transactions || [])
		.filter(Boolean)
		.map((name) => {
			const display_name = frappe.utils.escape_html(name);
			return frappe.utils.get_form_link("Bank Transaction", name, true, display_name);
		});

	let message = `<div>${reason}</div>`;
	if (bank_transactions.length) {
		if (quick_unreconcile) {
			message += `<div class="text-muted small mt-2">${__("可使用上方按钮只撤销当前凭证对应的核销；也可以打开流水手动处理。")}</div>`;
		} else {
			message += `
				<hr>
				<div><b>${__("处理步骤")}</b></div>
				<ol class="mb-0 pl-4">
					<li>${__("打开下面的银行流水，确认当前对账分配")}</li>
					<li>${__("在银行流水中执行“撤销银行对账”或“Unreconcile Transaction”")}</li>
					<li>${__("返回查凭证后重新点击“编辑来源凭证”")}</li>
				</ol>
				<div class="text-muted small mt-2">${__("撤销操作会清除该银行流水的对账分配，请确认没有影响同一流水上的其他凭证。")}</div>
			`;
		}
		message += `<div class="mt-2"><b>${__("关联银行流水")}</b>：${bank_transactions.join("、")}</div>`;
	}

	frappe.msgprint({
		message,
		indicator: "orange",
		title: __("不能修改凭证"),
		...(quick_unreconcile
			? {
				primary_action: {
					label: __("撤销本凭证核销并继续编辑"),
					action: () => {
						frappe.hide_msgprint();
						const amount = format_currency(quick_unreconcile.amount);
						frappe.confirm(
							__(
								"将只撤销银行流水 {0} 中与当前凭证对应的 {1} 分配，其他凭证的对账分配不变。随后系统会取消原凭证并打开修订草稿。是否继续？",
								[quick_unreconcile.bank_transaction, amount]
							),
							() => {
								frappe.call({
									method: "china_finance.services.source_voucher_edit.unreconcile_and_prepare_source_voucher_edit",
									args: {
										source_doctype: status.source_doctype,
										source_name: status.source_name,
									},
									freeze: true,
									freeze_message: __("正在撤销当前凭证的银行核销并创建修订草稿…"),
								}).then((response) => {
									const result = response.message || {};
									if (!result.name) {
										frappe.msgprint({
											message: __("后台未返回修订草稿，请刷新报表后重试"),
											indicator: "red",
											title: __("编辑来源凭证失败"),
										});
										return;
									}
									frappe.show_alert({
										message: result.message || __("修订草稿已生成"),
										indicator: "green",
									});
									frappe.set_route("Form", status.source_doctype, result.name);
								}).catch((error) => {
									frappe.msgprint({
										message: error?.message || error?.exc || __("操作失败，请稍后重试"),
										indicator: "red",
										title: __("编辑来源凭证失败"),
									});
								});
							}
						);
					},
				},
			}
			: {}),
	});
}

function ensure_voucher_ledger_styles() {
	if (document.getElementById("china-voucher-ledger-inline-style")) return;
	$("<style>")
		.attr("id", "china-voucher-ledger-inline-style")
		.text(`
			.china-voucher-ledger-report .datatable,
			.china-voucher-ledger-report .dt-header,
			.china-voucher-ledger-report .dt-scrollable {
				width: 100%;
				min-width: 0;
			}
			.china-voucher-ledger-report .dt-header,
			.china-voucher-ledger-report .dt-scrollable { max-width: none; }
			.china-voucher-ledger-report .dt-row {
				min-width: 100%;
				width: max-content;
			}
			.china-voucher-ledger-report .dt-cell { flex: 0 0 auto; }
			.china-voucher-ledger-report .dt-scrollable { overflow-x: auto; }
			.china-voucher-ledger-floating-scroll {
				position: fixed;
				z-index: 1030;
				display: block;
				height: 16px;
				padding: 2px 0;
				overflow-x: auto;
				overflow-y: hidden;
				background: var(--card-bg, #fff);
				border: 1px solid var(--border-color, #d1d8dd);
				border-radius: 8px;
				box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
				scrollbar-width: thin;
			}
			.china-voucher-ledger-floating-scroll[hidden] { display: none; }
			.china-voucher-ledger-floating-scroll__content {
				height: 1px;
				min-width: 100%;
			}
			.china-voucher-ledger-report .dt-cell__content {
				line-height: 24px;
				padding-left: 6px;
				padding-right: 6px;
				white-space: nowrap;
				overflow: hidden;
				text-overflow: ellipsis;
			}
			.china-voucher-ledger-report .dt-row { min-height: 28px; }
		`)
		.appendTo(document.head);
}

function start_voucher_ledger_floating_scroll(report) {
	if (report._china_voucher_ledger_floating_scroll_watch_started) return;
	report._china_voucher_ledger_floating_scroll_watch_started = true;

	const page_wrapper = report?.page?.wrapper?.[0] || report?.page?.wrapper;
	if (!page_wrapper) return;

	let attempts = 0;
	const attach = () => {
		if (!document.body.contains(page_wrapper)) return;
		const datatable = report.datatable;
		if (datatable?.bodyScrollable) {
			setup_voucher_ledger_floating_scroll(report, datatable);
			return;
		}
		if (attempts++ < 50) window.setTimeout(attach, 100);
	};
	attach();
}

function setup_voucher_ledger_floating_scroll(report, datatable) {
	const page_wrapper = report?.page?.wrapper?.[0] || report?.page?.wrapper;
	const scrollable = datatable?.bodyScrollable;
	if (!page_wrapper || !scrollable) return;

	let state = report._china_voucher_ledger_floating_scroll;
	if (!state) {
		const bar = document.createElement("div");
		bar.className = "china-voucher-ledger-floating-scroll";
		bar.setAttribute("aria-label", __("凭证表格横向滚动条"));
		bar.hidden = true;

		const content = document.createElement("div");
		content.className = "china-voucher-ledger-floating-scroll__content";
		bar.appendChild(content);
		document.body.appendChild(bar);

		state = {
			bar,
			content,
			page_wrapper,
			scrollable: null,
			syncing: false,
			update_scheduled: false,
		};
		report._china_voucher_ledger_floating_scroll = state;

		state.update = () => {
			if (state.update_scheduled) return;
			state.update_scheduled = true;
			window.requestAnimationFrame(() => {
				state.update_scheduled = false;
				update_voucher_ledger_floating_scroll(state);
			});
		};
		state.on_table_scroll = () => {
			if (state.syncing) return;
			state.syncing = true;
			state.bar.scrollLeft = state.scrollable?.scrollLeft || 0;
			state.syncing = false;
		};
		state.on_bar_scroll = () => {
			if (state.syncing || !state.scrollable) return;
			state.syncing = true;
			state.scrollable.scrollLeft = state.bar.scrollLeft;
			state.syncing = false;
		};

		bar.addEventListener("scroll", state.on_bar_scroll, { passive: true });
		window.addEventListener("scroll", state.update, { passive: true });
		window.addEventListener("resize", state.update, { passive: true });
	}

	if (state.scrollable !== scrollable) {
		state.scrollable?.removeEventListener("scroll", state.on_table_scroll);
		state.scrollable = scrollable;
		scrollable.addEventListener("scroll", state.on_table_scroll, { passive: true });
	}

	state.page_wrapper = page_wrapper;
	state.update();
}

function update_voucher_ledger_floating_scroll(state) {
	const { bar, content, page_wrapper, scrollable } = state;
	if (!bar || !scrollable || !document.body.contains(page_wrapper)) {
		if (bar) bar.hidden = true;
		return;
	}

	const has_horizontal_overflow = scrollable.scrollWidth > scrollable.clientWidth + 2;
	const rect = scrollable.getBoundingClientRect();
	const visible_in_viewport = rect.bottom > 0 && rect.top < window.innerHeight && rect.width > 0;
	if (!has_horizontal_overflow || !visible_in_viewport) {
		bar.hidden = true;
		return;
	}

	const left = Math.max(0, rect.left);
	const width = Math.min(rect.width, window.innerWidth - left);
	if (width <= 0) {
		bar.hidden = true;
		return;
	}

	content.style.width = `${scrollable.scrollWidth}px`;
	bar.style.left = `${left}px`;
	bar.style.width = `${width}px`;
	bar.style.bottom = "10px";
	state.syncing = true;
	bar.scrollLeft = scrollable.scrollLeft;
	state.syncing = false;
	bar.hidden = false;
}

function set_quick_period(report, period) {
	const today = frappe.datetime.get_today();
	// Select values may be translated, so compare the selected option's index
	// instead of comparing translated labels directly.
	const period_control = report.get_filter("period_preset");
	const selected_index = Number(period_control.$input?.prop("selectedIndex"));
	const raw_options = period_control.df.options || [];
	const options = Array.isArray(raw_options) ? raw_options : raw_options.split("\n");
	const period_index = Number.isInteger(selected_index) && selected_index >= 0
		? selected_index
		: options.indexOf(period);
	const period_text = String(period || "");
	let from_date;
	let to_date;
	if (period_text.includes("近三") || period_index === 3) {
		from_date = moment(today).subtract(2, "months").startOf("month").format("YYYY-MM-DD");
		to_date = today;
	} else if (period_text.includes("本年") || period_index === 4) {
		from_date = `${today.slice(0, 4)}-01-01`;
		to_date = today;
	} else if (period_text.includes("本月") || period_index === 1) {
		from_date = moment(today).startOf("month").format("YYYY-MM-DD");
		to_date = moment(today).endOf("month").format("YYYY-MM-DD");
	} else if (period_text.includes("上月") || period_index === 2) {
		const previous = moment(today).subtract(1, "month");
		from_date = previous.clone().startOf("month").format("YYYY-MM-DD");
		to_date = previous.clone().endOf("month").format("YYYY-MM-DD");
	} else {
		from_date = moment(today).startOf("month").format("YYYY-MM-DD");
		to_date = moment(today).endOf("month").format("YYYY-MM-DD");
	}
	report.set_filter_value("from_date", from_date);
	report.set_filter_value("to_date", to_date);
	report.refresh();
}
