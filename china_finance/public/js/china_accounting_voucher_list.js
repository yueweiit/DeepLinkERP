function print_china_accounting_vouchers_a5_landscape(listview) {
	const docs = listview.get_checked_items();
	if (!docs.length) {
		frappe.msgprint(__("请先勾选需要打印的凭证"));
		return;
	}

	const invalid_docs = docs.filter((doc) => doc.docstatus !== 1 && !frappe.user.has_role("Administrator"));
	if (invalid_docs.length) {
		frappe.msgprint(__("只能打印已提交的凭证，请取消勾选草稿或已取消的凭证"));
		return;
	}

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Letter Head",
			fields: ["name", "is_default"],
			filters: { disabled: 0 },
			order_by: "is_default desc, name asc",
			limit_page_length: 1,
		},
		callback: (response) => {
			const letterhead = response.message?.[0]?.name || "No Letterhead";
			const names = JSON.stringify(docs.map((doc) => doc.name));
			const options = JSON.stringify({
				"page-size": "A5",
				orientation: "Landscape",
			});
			const args = {
				doctype: "China Accounting Voucher",
				name: names,
				format: "China Accounting Voucher A5 Landscape",
				no_letterhead: letterhead === "No Letterhead" ? "1" : "0",
				letterhead,
				options,
			};

			if (docs.length > 25) {
				frappe.call({
					method: "frappe.utils.print_format.download_multi_pdf_async",
					args,
				}).then((result) => {
					const task_id = result.message.task_id;
					frappe.realtime.task_subscribe(task_id);
					frappe.realtime.on(`task_complete:${task_id}`, (data) => {
						frappe.msgprint({
							title: __("批量打印完成"),
							message: __("A5 横向凭证 PDF 已生成"),
							primary_action: {
								label: __("下载 PDF"),
								client_action: "window.open",
								args: data.file_url,
							},
						});
						frappe.realtime.task_unsubscribe(task_id);
						frappe.realtime.off(`task_complete:${task_id}`);
					});
				});
				return;
			}

			const query = new URLSearchParams(args).toString();
			const print_window = window.open(`/api/method/frappe.utils.print_format.download_multi_pdf?${query}`);
			if (!print_window) frappe.msgprint(__("请允许浏览器打开弹出窗口"));
		},
	});
}

frappe.listview_settings["China Accounting Voucher"] = {
	onload(listview) {
		listview.page.add_action_item(__("打印 A5 横向"), () => {
			print_china_accounting_vouchers_a5_landscape(listview);
		});
	},
};
