frappe.ui.form.on("Overseas Cost ERP Settings", {
    refresh(frm) {
        frm.add_custom_button("测试连接", () => {
            frm.save().then(() => {
                frappe.call({
                    method: "overseas_costing.services.erp_client.check_erp_connection",
                    freeze: true,
                    freeze_message: "正在检查 ERP 连接...",
                    callback(r) {
                        const result = r.message || {};
                        const indicator = result.ok ? "green" : "red";
                        frappe.msgprint({
                            title: "ERP 连接检查",
                            indicator,
                            message: result.message || "没有返回检查结果。",
                        });
                    },
                });
            });
        });
    },
});
