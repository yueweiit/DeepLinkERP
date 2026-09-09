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

frappe.ui.form.on("China Closing Run", {
	refresh(frm) {
		lock_check_grid(frm);
		if (frm.doc.company && frm.doc.from_date && frm.doc.to_date && frm.doc.docstatus === 0) {
			frm.add_custom_button(__(frm.doc.closing_type === "Monthly"
				? "生成本月损益结转草稿"
				: "生成年度损益结转草稿"), () => frappe.call({
				method: "china_finance.services.closing.create_period_closing_voucher",
				args: {
					company: frm.doc.company,
					from_date: frm.doc.from_date,
					to_date: frm.doc.to_date,
					closing_type: frm.doc.closing_type,
				},
				freeze: true,
				callback: (response) => {
					const result = response.message || {};
					if (!result.name) return;
					frm.set_value("period_closing_voucher", result.name);
					const show_result = () => frappe.msgprint({
						message: result.message + (frm.is_new()
							? __("；当前结账运行单尚未保存，请保存后再提交结账")
							: ""),
						primary_action: {
							label: __("打开损益结转凭证"),
							action: () => frappe.set_route("Form", "Period Closing Voucher", result.name),
						},
					});
					if (frm.is_new()) {
						show_result();
					} else {
						frm.save().then(show_result);
					}
				},
			}), __("结账"));
			frm.add_custom_button(__("生成必需对账单"), () => frappe.call({
				method: "china_finance.services.reconciliation_control.generate_required_statements",
				args: { company: frm.doc.company, from_date: frm.doc.from_date, to_date: frm.doc.to_date },
				freeze: true,
				callback: (response) => {
					const result = response.message || {};
					frappe.msgprint(__("处理 {0} 项，创建 {1} 张，已存在 {2} 张，失败 {3} 项", [result.processed || 0, result.created || 0, result.existing || 0, result.failed || 0]));
				},
			}), __("对账"));
			frm.add_custom_button(__("运行结账检查"), () => {
				if (!frm.doc.period_closing_voucher) {
					frappe.msgprint({
						message: __("请先填写并选择 ERPNext 损益结转凭证"),
						indicator: "orange",
					});
					return;
				}
				frappe.call({
					method: "china_finance.services.closing.preview_closing_checks",
					args: {
						company: frm.doc.company,
						from_date: frm.doc.from_date,
						to_date: frm.doc.to_date,
						period_closing_voucher: frm.doc.period_closing_voucher,
					},
					freeze: true,
					callback: (response) => {
						frm.clear_table("checks");
						(response.message || []).forEach((row) => frm.add_child("checks", row));
						frm.refresh_field("checks");
						lock_check_grid(frm);
						frm.save().then(() => frappe.show_alert({
							message: __("结账检查已生成并保存为草稿"),
							indicator: "green",
						}));
					},
				});
			}, __("对账"));
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
