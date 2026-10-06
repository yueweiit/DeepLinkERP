frappe.ui.form.on("OA Purchase Request", {
	refresh(frm) {
		for (const label of new Set(["生成采购订单", "Generate Purchase Order", __("生成采购订单"), __("Generate Purchase Order")])) frm.remove_custom_button(label);
		if (frm.is_new()) return;
		frm.add_custom_button(__("完善/关联采购订单"), () => deeplinkerp.purchaseSource.open(frm.doc.name));
	},
});
