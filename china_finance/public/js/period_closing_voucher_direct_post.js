function china_finance_can_complete_period_closing(frm) {
	const workflow_state = frm.doc.workflow_state || (frm.is_new() ? "Draft" : "");
	return Boolean(
		frm.doc.docstatus === 0
		&& ["Draft", "Pending Review", "Approved"].includes(workflow_state)
		&& frm.perm?.[0]?.write
	);
}

function china_finance_set_period_closing_action(frm) {
	if (!china_finance_can_complete_period_closing(frm)) return;

	frm.page.set_primary_action(
		__("保存并完成结账"),
		() => china_finance_save_and_complete_period_closing(frm),
		null,
		__("正在保存并完成结账...")
	);

	if (!frm.__china_finance_period_closing_save_button_added) {
		frm.add_custom_button(__("仅保存草稿"), () => frm.save("Save"), __("更多"));
		frm.__china_finance_period_closing_save_button_added = true;
	}
}

function china_finance_save_period_closing(frm) {
	if (!frm.is_dirty()) return Promise.resolve();

	return frm.save("Save").then(() => {
		if (frm.is_dirty()) {
			throw new Error(__("凭证保存尚未完成，请检查必填项和校验提示"));
		}
	});
}

function china_finance_get_period_closing_status(name) {
	return frappe.call({
		method: "frappe.client.get_value",
		args: {
			doctype: "Period Closing Voucher",
			filters: { name },
			fieldname: JSON.stringify(["docstatus", "workflow_state", "gle_processing_status"]),
		},
	});
}

function china_finance_wait_for_period_closing_processing(frm, name) {
	const timeout_at = Date.now() + 120000;

	return new Promise((resolve, reject) => {
		const poll = () => {
			china_finance_get_period_closing_status(name)
				.then((response) => {
					const status = response.message || {};
					if (Number(status.docstatus) === 1 && status.gle_processing_status === "Completed") {
						resolve(status);
						return;
					}
					if (status.gle_processing_status === "Failed") {
						reject(new Error(__("总账处理失败，请打开凭证查看错误信息")));
						return;
					}
					if (Date.now() >= timeout_at) {
						reject(new Error(__("凭证已记账，但总账仍在后台处理中，请稍后刷新查看")));
						return;
					}
					setTimeout(poll, 1500);
				})
				.catch(reject);
		};

		poll();
	});
}

function china_finance_render_period_closing_entries(frm) {
	const field = frm.fields_dict.custom_china_period_entries;
	if (!field?.$wrapper) return;

	const wrapper = field.$wrapper;
	const request_id = (frm.__china_finance_period_entries_request_id || 0) + 1;
	frm.__china_finance_period_entries_request_id = request_id;

	if (frm.is_new()) {
		wrapper.html(`<div class="china-period-closing-entries__empty text-muted">${__("保存后，提交结账凭证将生成会计分录")}</div>`);
		return;
	}

	wrapper.html(`<div class="china-period-closing-entries__loading text-muted">${__("正在加载会计分录...")}</div>`);
	frappe.call({
		method: "china_finance.services.closing.get_period_closing_entries",
		args: { name: frm.doc.name },
	}).then((response) => {
		if (request_id !== frm.__china_finance_period_entries_request_id) return;

		const result = response.message || {};
		const rows = result.rows || [];
		const currency = result.currency || "CNY";
		const total_debit = Number(result.total_debit || 0);
		const total_credit = Number(result.total_credit || 0);
		const balanced = Math.abs(total_debit - total_credit) <= 0.005;
		const escape = frappe.utils.escape_html;
		const format_amount = (value) => format_currency(Number(value || 0), currency);

		if (!rows.length) {
			let message = __("提交后将显示实际生成的会计分录");
			if (result.processing_status === "In Progress") message = __("总账正在后台处理中，请稍后刷新");
			if (Number(result.docstatus) === 2) message = __("该结账凭证已取消，没有有效会计分录");
			wrapper.html(`<div class="china-period-closing-entries__empty text-muted">${escape(message)}</div>`);
			return;
		}

		const body = rows.map((row) => `
			<tr>
				<td class="china-period-closing-entries__index">${escape(String(row.idx || ""))}</td>
				<td>${escape(row.summary || "")}</td>
				<td class="china-period-closing-entries__account">${escape(row.account || "")}</td>
				<td class="text-right">${format_amount(row.debit)}</td>
				<td class="text-right">${format_amount(row.credit)}</td>
			</tr>`).join("");

		wrapper.html(`
			<div class="china-period-closing-entries">
				<div class="china-period-closing-entries__meta">
					<span>${__("共 {0} 条分录", [rows.length])}</span>
					<span class="${balanced ? "text-success" : "text-danger"}">${balanced ? __("借贷平衡") : __("借贷不平")}</span>
				</div>
				<div class="table-responsive">
					<table class="table table-bordered china-period-closing-entries__table">
						<thead>
							<tr>
								<th>${__("编号")}</th>
								<th>${__("摘要")}</th>
								<th>${__("科目")}</th>
								<th class="text-right">${__("借方")}</th>
								<th class="text-right">${__("贷方")}</th>
							</tr>
						</thead>
						<tbody>${body}</tbody>
						<tfoot>
							<tr>
								<th colspan="3" class="text-right">${__("合计")}</th>
								<th class="text-right">${format_amount(total_debit)}</th>
								<th class="text-right">${format_amount(total_credit)}</th>
							</tr>
						</tfoot>
					</table>
				</div>
			</div>`);
	}).catch((error) => {
		if (request_id !== frm.__china_finance_period_entries_request_id) return;
		const message = error?.message || __("会计分录加载失败，请刷新页面重试");
		wrapper.html(`<div class="china-period-closing-entries__empty text-danger">${frappe.utils.escape_html(message)}</div>`);
	});
}

function china_finance_save_and_complete_period_closing(frm) {
	if (!china_finance_can_complete_period_closing(frm) || frm.__china_finance_period_closing_processing) {
		return;
	}

	frm.__china_finance_period_closing_processing = true;
	frm.page.btn_primary.prop("disabled", true);

	china_finance_save_period_closing(frm)
		.then(() => frappe.call({
			method: "china_finance.services.closing.save_and_complete_period_closing_voucher",
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message: __("正在提交审核、审核通过并记账，请稍候..."),
		}))
		.then(() => china_finance_wait_for_period_closing_processing(frm, frm.doc.name))
		.then(() => {
			frappe.show_alert({ message: __("期末结账已保存并记账"), indicator: "green" });
			return frm.reload_doc();
		})
		.catch((error) => {
			frappe.msgprint({
				title: __("期末结账失败"),
				message: error?.message || error?.exc || __("请检查凭证和工作流权限后重试"),
				indicator: "red",
			});
			return frm.reload_doc();
		})
		.finally(() => {
			frm.__china_finance_period_closing_processing = false;
			frm.page.btn_primary.prop("disabled", false);
			china_finance_set_period_closing_action(frm);
		});
}

frappe.ui.form.on("Period Closing Voucher", {
	refresh(frm) {
		china_finance_render_period_closing_entries(frm);
		if (!china_finance_can_complete_period_closing(frm)) return;
		frm.__china_finance_period_closing_save_button_added = false;

		$(frm.wrapper)
			.off("dirty.china_finance_period_closing")
			.on("dirty.china_finance_period_closing", () => {
				setTimeout(() => china_finance_set_period_closing_action(frm), 0);
			});
		china_finance_set_period_closing_action(frm);
	},
});
