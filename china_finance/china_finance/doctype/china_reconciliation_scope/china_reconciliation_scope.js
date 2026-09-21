frappe.ui.form.on("China Reconciliation Scope", {
	onload: sync_scope_currency,
	company: sync_scope_currency,
	scope_type: sync_scope_currency,
	reference_name: sync_scope_currency,
});

async function sync_scope_currency(frm) {
	const { company, scope_type, reference_name } = frm.doc;
	if (!company) return;
	const base = await frappe.db.get_value("Company", company, "default_currency");
	let currency = base.message.default_currency;
	if (scope_type === "Bank" && reference_name) {
		const bank = await frappe.db.get_value("Bank Account", reference_name, "account");
		if (bank.message.account) {
			const account = await frappe.db.get_value("Account", bank.message.account, "account_currency");
			currency = account.message.account_currency || currency;
		}
	}
	if (frm.doc.company !== company || frm.doc.scope_type !== scope_type || frm.doc.reference_name !== reference_name) return;
	await frm.set_value("currency", currency);
}
