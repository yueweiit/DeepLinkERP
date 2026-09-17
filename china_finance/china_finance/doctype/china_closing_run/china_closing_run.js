function remove_empty_check_rows(frm) {
	const rows = frm.doc.checks || [];
	const populated_rows = rows.filter((row) =>
		["check_code", "description", "severity", "details"].some((fieldname) => row[fieldname])
	);

	if (populated_rows.length === rows.length) return;

	frm.clear_table("checks");
	populated_rows.forEach((row) => {
		const child = frm.add_child("checks");
		["check_code", "description", "severity", "passed", "details"].forEach((fieldname) => {
			child[fieldname] = row[fieldname];
		});
	});
	frm.refresh_field("checks");
}

function lock_check_grid(frm) {
	const checks_field = frm.get_field("checks");
	if (!checks_field) return;

	// 检查结果只能由“运行结账检查”生成，用户不能手工添加、删除或编辑。
	frm.set_df_property("checks", "cannot_add_rows", true);
	frm.set_df_property("checks", "cannot_delete_rows", true);
	remove_empty_check_rows(frm);
}

function initialize_amended_closing_run(frm) {
	if (!frm.is_new() || !frm.doc.amended_from || frm.__china_closing_amendment_initialized) return;

	frm.__china_closing_amendment_initialized = true;
	Object.assign(frm.doc, {
		status: "Draft",
		archive_package: null,
		previous_frozen_date: null,
		closed_by: null,
		closed_on: null,
		reopened_by: null,
		reopened_on: null,
		reopen_reason: null,
	});
	frm.clear_table("checks");
	frm.refresh_fields();
}

async function save_latest_closing_run(frm) {
	if (!frm.is_dirty()) return;

	await frm.save();
	if (frm.is_dirty()) {
		throw new Error(__("期末智能结转保存失败，请刷新页面后重试"));
	}
}

function get_closing_action_error(error) {
	const response = error?.responseJSON || frappe.last_response || error || {};
	if (response._server_messages) {
		try {
			const messages = JSON.parse(response._server_messages)
				.map((item) => {
					if (typeof item !== "string") return item.message || item.title || "";
					try {
						const parsed = JSON.parse(item);
						return parsed.message || parsed.title || item;
					} catch (_parse_error) {
						return item;
					}
				})
				.filter(Boolean);
			if (messages.length) return messages.join("<br>");
		} catch (_parse_error) {
			return response._server_messages;
		}
	}
	return response._error_message
		|| response.message
		|| error?.message
		|| response.exc_type
		|| error?.statusText
		|| __("操作失败，请刷新页面后重试");
}

function show_closing_action_error(title, error) {
	console.error(error);
	frappe.msgprint({
		title: __(title),
		message: get_closing_action_error(error),
		indicator: "red",
	});
}

async function generate_period_closing_voucher(frm) {
	if (frm.__china_closing_action_running) return;

	frm.__china_closing_action_running = true;
	frappe.dom.freeze(__("正在生成并保存损益结转凭证..."));
	try {
		const response = await frappe.call({
			method: "china_finance.services.closing.create_period_closing_voucher",
			args: {
				company: frm.doc.company,
				from_date: frm.doc.from_date,
				to_date: frm.doc.to_date,
				closing_type: frm.doc.closing_type,
			},
		});
		const result = response.message || {};
		if (!result.name) return;

		await frm.set_value("period_closing_voucher", result.name);
		if (!frm.is_new()) {
			await save_latest_closing_run(frm);
			await frm.reload_doc();
		}
		frappe.msgprint({
			message: result.message + (frm.is_new()
				? __("；当前期末智能结转尚未保存，请保存后再提交结转")
				: ""),
			primary_action: {
				label: __("打开损益结转凭证"),
				action: () => frappe.set_route("Form", "Period Closing Voucher", result.name),
			},
		});
	} catch (error) {
		show_closing_action_error("损益结转凭证生成失败", error);
	} finally {
		frappe.dom.unfreeze();
		frm.__china_closing_action_running = false;
	}
}

async function run_closing_checks(frm) {
	if (frm.__china_closing_action_running) return;
	if (!frm.doc.period_closing_voucher) {
		frappe.msgprint({
			message: __("请先填写并选择 ERPNext 损益结转凭证"),
			indicator: "orange",
		});
		return;
	}

	frm.__china_closing_action_running = true;
	frappe.dom.freeze(__("正在运行并保存结账检查..."));
	try {
		const response = await frappe.call({
			method: "china_finance.services.closing.preview_closing_checks",
			args: {
				company: frm.doc.company,
				from_date: frm.doc.from_date,
				to_date: frm.doc.to_date,
				period_closing_voucher: frm.doc.period_closing_voucher,
				closing_type: frm.doc.closing_type,
			},
		});
		frm.clear_table("checks");
		(response.message || []).forEach((row) => frm.add_child("checks", row));
		frm.refresh_field("checks");
		lock_check_grid(frm);
		await save_latest_closing_run(frm);
		await frm.reload_doc();
		frappe.show_alert({
			message: __("结账检查已生成并保存为草稿"),
			indicator: "green",
		});
	} catch (error) {
		show_closing_action_error("结账检查保存失败", error);
	} finally {
		frappe.dom.unfreeze();
		frm.__china_closing_action_running = false;
	}
}

async function submit_and_complete_closing(frm) {
	if (frm.__china_closing_action_running || frm.is_new() || frm.doc.docstatus !== 0) return;

	frm.__china_closing_action_running = true;
	frappe.dom.freeze(__("正在提交并完成期末结账..."));
	try {
		await save_latest_closing_run(frm);
		const response = await frappe.call({
			method: "china_finance.services.closing.submit_closing_run",
			args: { name: frm.doc.name },
			type: "POST",
		});
		await frm.reload_doc();
		frappe.show_alert({
			message: response.message?.already_submitted
				? __("期末结账已经提交")
				: __("期末结账已提交并完成"),
			indicator: "green",
		}, 7);
	} catch (error) {
		show_closing_action_error("期末结账提交失败", error);
	} finally {
		frappe.dom.unfreeze();
		frm.__china_closing_action_running = false;
	}
}

frappe.ui.form.on("China Closing Run", {
	refresh(frm) {
		initialize_amended_closing_run(frm);
		lock_check_grid(frm);
		if (frm.doc.company && frm.doc.from_date && frm.doc.to_date && frm.doc.docstatus === 0) {
			if (!frm.is_new()) {
				frm.page.set_primary_action(__("提交并完成结账"), () => {
					frappe.confirm(
						__("确认提交并完成期末结账 {0}？", [frm.doc.name]),
						() => submit_and_complete_closing(frm)
					);
				}, "check");
			}
			frm.add_custom_button(__(frm.doc.closing_type === "Monthly"
				? "生成本月损益结转草稿"
				: "生成年度损益结转草稿"), () => generate_period_closing_voucher(frm), __("结账"));
			frm.add_custom_button(__("生成必需对账单"), () => frappe.call({
				method: "china_finance.services.reconciliation_control.generate_required_statements",
				args: { company: frm.doc.company, from_date: frm.doc.from_date, to_date: frm.doc.to_date },
				freeze: true,
				callback: (response) => {
					const result = response.message || {};
					frappe.msgprint(__("处理 {0} 项，创建 {1} 张，已存在 {2} 张，失败 {3} 项", [result.processed || 0, result.created || 0, result.existing || 0, result.failed || 0]));
				},
			}), __("对账"));
			frm.add_custom_button(__("运行结账检查"), () => run_closing_checks(frm), __("对账"));
		}
		if (frm.doc.docstatus === 1 && frm.doc.status === "Closed") {
			frm.add_custom_button(__("重新开账（含后续期间）"), () => {
				frappe.prompt(
					[{ fieldname: "reason", fieldtype: "Small Text", label: __("重新开账原因"), reqd: 1 }],
					(values) => frappe.call({
						method: "china_finance.services.closing.reopen_closing",
						args: { name: frm.doc.name, reason: values.reason },
						freeze: true,
						callback: (response) => {
							const result = response.message || {};
							const runs = (result.reopened_runs || []).map((run) => run.name).join(", ");
							const vouchers = (result.period_closing_vouchers || []).join(", ");
							frappe.msgprint({
								message: [
									__("已按倒序重新开账：{0}", [runs]),
									__("当前账务冻结日期已恢复至：{0}", [result.previous_frozen_date || __("无")]),
									__("请按倒序取消以下损益结转凭证：{0}", [vouchers || __("无")]),
									__("修改完成后，请按期间正序重新结转并提交结账。"),
								].join("<br>"),
								indicator: "green",
							});
							frm.reload_doc();
						},
					}),
					__("重新开账（含后续期间）")
				);
			});
		}
	},
});
