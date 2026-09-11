// Copyright (c) 2026, Yuewei and contributors
// License: MIT

frappe.listview_settings["Bank Transaction"] = {
	add_fields: ["unallocated_amount", "docstatus"],

	get_indicator: function (doc) {
		if (doc.docstatus == 2) {
			return [__("Cancelled"), "red", "docstatus,=,2"];
		} else if (flt(doc.unallocated_amount) <= 0) {
			return [__("Reconciled"), "green", "unallocated_amount,=,0"];
		} else if (flt(doc.unallocated_amount) > 0) {
			return [__("Unreconciled"), "orange", "unallocated_amount,>,0"];
		}
	},

	onload: function (listview) {
		// Bulk deletion of more than ten documents is queued in the background by
		// Frappe. Submitted Bank Transactions then fail asynchronously, which used
		// to leave the user without a useful explanation. Stop that action in the
		// browser and explain the required Cancel -> Delete sequence first.
		const delete_link = listview.page.actions
			.find("a.dropdown-item")
			.filter(function () {
				const label = $(this).find(".menu-item-label").text().trim();
				return label === __("Delete") || label === "Delete" || label === "删除";
			})
			.first();

		if (!delete_link.length || delete_link[0].dataset.chinaFinanceDeleteGuard) return;

		delete_link[0].addEventListener(
			"click",
			function (event) {
				const selected = listview.get_checked_items();
				const submitted = selected.filter((row) => Number(row.docstatus) === 1);

				if (!submitted.length) return;

				event.preventDefault();
				event.stopImmediatePropagation();

				const names = submitted
					.slice(0, 10)
					.map((row) => frappe.utils.escape_html(row.name))
					.join(", ");
				const suffix = submitted.length > 10 ? __("等") : "";

				frappe.msgprint({
					title: __("银行流水不能直接删除"),
					indicator: "orange",
					message: [
						__("已选择 {0} 条已提交的银行流水，不能直接删除。", [submitted.length]),
						__("请先执行“取消”，取消成功后再执行“删除”。"),
						names ? `${__("涉及记录")}：${names}${suffix}` : "",
					]
					.filter(Boolean)
					.join("<br>"),
				});
			},
			true
		);

		delete_link[0].dataset.chinaFinanceDeleteGuard = "1";
	},
};
