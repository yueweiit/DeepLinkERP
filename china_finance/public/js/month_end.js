frappe.provide("china_finance.month_end");

(() => {
	const call = async (method, name) => (await frappe.call({method: `china_finance.services.month_end.${method}`, args: {name}, type: "POST"})).message;
	const esc = value => frappe.utils.escape_html(String(value ?? ""));
	const labels = {Posting: "统一记账", Checking: "核销与现金流检查", Closing: "损益结转", Ready: "待确认结账", Paused: "已暂停", Failed: "待处理错误"};
	const show = (frm, result) => {
		frm.set_intro(`${esc(labels[result.state] || result.state)} · ${result.completed || 0}/${result.total || 0} 张<br>${esc(result.message)}`, ["Failed", "Paused"].includes(result.state) ? "orange" : "blue");
	};
	const run = async frm => {
		if (frm.__month_running) return;
		frm.__month_running = true;
		frm.__month_stop = false;
		try {
			if (frm.is_new() || frm.is_dirty()) await frm.save();
			let result = await call("start", frm.doc.name);
			show(frm, result);
			frm.add_custom_button(__("暂停处理"), async () => {
				frm.__month_stop = true;
				await call("pause", frm.doc.name);
				await frm.reload_doc();
			});
			while (!frm.__month_stop && ["Posting", "Checking", "Closing"].includes(result.state)) {
				result = await call("advance", frm.doc.name);
				show(frm, result);
				if (result.state === "Closing") await new Promise(resolve => setTimeout(resolve, 2000));
			}
		} finally {
			frm.__month_running = false;
			await frm.reload_doc();
		}
	};
	china_finance.month_end.render = frm => {
		for (const field of ["naming_series", "status", "previous_frozen_date", "closed_by", "closed_on", "reopened_by", "reopened_on", "reopen_reason", "checks_section", "checks", "notes", "preparation_state", "preparation_message"]) {
			frm.toggle_display(field, false);
		}
		frm.toggle_display("archive_package", !!frm.doc.archive_package);
		frm.toggle_display("period_closing_voucher", !!frm.doc.period_closing_voucher);
		frm.set_df_property("period_closing_voucher", "read_only", 1);
		const data = JSON.parse(frm.doc.preparation_data || "{}");
		if (frm.doc.preparation_state) show(frm, {state: frm.doc.preparation_state, message: frm.doc.preparation_message, completed: data.done?.length, total: data.items?.length});
		frm.fields_dict.preparation_preview.$wrapper.html(`<p>先核对草稿与试算，再统一记账和结转；核对正式报表后确认结账。关闭页面会保留进度，可重新打开继续或暂停。</p>${(data.checks || []).length ? `<table class="table table-bordered"><thead><tr><th>结账检查</th><th>结果</th><th>说明</th></tr></thead><tbody>${data.checks.map(r => `<tr><td>${esc(r.description)}</td><td>${r.passed ? "通过" : esc(r.severity === "Blocking" ? "待处理" : "提示")}</td><td>${esc(r.details)}</td></tr>`).join("")}</tbody></table>` : ""}`);
		frm.add_custom_button(__("查凭证"), () => {
			frappe.route_options = {company: frm.doc.company, from_date: frm.doc.from_date, to_date: frm.doc.to_date, period_preset: "", voucher_status: "全部有效凭证"};
			frappe.set_route("query-report", "China Voucher Ledger");
		});
		frm.add_custom_button(__("未记账试算"), () => frappe.require("/assets/china_finance/js/voucher_preparation.js", () => china_finance.preparation.trial(frm.doc.company, frm.doc.from_date, frm.doc.to_date)));
		frm.add_custom_button(__("核对正式报表"), () => {
			frappe.route_options = {company: frm.doc.company, from_date: frm.doc.from_date, to_date: frm.doc.to_date};
			frappe.set_route("query-report", "China Financial Statements");
		});
		frm.add_custom_button(__("现金流项目"), () => frappe.set_route("List", "China Cash Flow Assignment", {company: frm.doc.company}));
		if (frm.doc.docstatus === 1) {
			frm.set_intro(frm.doc.archive_package ? __("已结账，归档包已生成") : __("已结账；归档包尚未就绪，可刷新状态或重试归档"), "green");
			return;
		}
		if (frm.doc.preparation_state === "Ready") {
			frm.page.set_primary_action(__("确认结账"), () => frappe.confirm(__("已核对正式报表，确认冻结本期并生成归档？"), async () => {
				await call("finish", frm.doc.name); await frm.reload_doc();
			}));
		} else {
			frm.page.set_primary_action(__(frm.doc.preparation_state ? "检查并继续处理" : "检查并统一记账"), () => frappe.confirm(__("将按日期正式记账本期已核对的草稿，并继续损益结转。确认开始？"), () => run(frm)));
		}
		if (["Posting", "Checking", "Closing"].includes(frm.doc.preparation_state) || frm.__month_running) {
			frm.add_custom_button(__("暂停处理"), async () => {
				frm.__month_stop = true;
				await call("pause", frm.doc.name);
				await frm.reload_doc();
			});
		}
	};
})();
