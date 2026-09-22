frappe.ui.form.on("China Bank Receipt Rule", {
	setup(frm) {
		for (const field of ["account", "personal_account"]) frm.set_query(field, () => ({ filters: { company: frm.doc.company, is_group: 0, disabled: 0, account_currency: "CNY" } }));
		frm.set_query("accrual_account", () => ({ filters: { company: frm.doc.company, is_group: 0, disabled: 0, account_currency: "CNY", root_type: "Liability" } }));
	},
});
