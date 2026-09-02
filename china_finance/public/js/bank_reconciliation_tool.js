/* Small compatibility layer for the native ERPNext reconciliation dialog. */
frappe.ui.form.on("Bank Reconciliation Tool", {
	refresh(frm) {
		// Keep old bookmarks working while making the React Banking module the
		// single entry point for import, matching, reconciliation and summaries.
		window.location.replace("/banking");
	},
});

(function patch_bank_reconciliation_dialog() {
	const try_patch = () => {
		const DialogManager = window.erpnext?.accounts?.bank_reconciliation?.DialogManager;
		if (!DialogManager || DialogManager.prototype.__china_finance_patched) return !!DialogManager;

		const prototype = DialogManager.prototype;
		const native_edit_in_full_page = prototype.edit_in_full_page;
		const DataTableManager = window.erpnext.accounts.bank_reconciliation.DataTableManager;
		const native_make_dt = DataTableManager?.prototype.make_dt;
		const native_get_dt_columns = DataTableManager?.prototype.get_dt_columns;
		const native_format_row = DataTableManager?.prototype.format_row;

		if (DataTableManager && !DataTableManager.prototype.__china_finance_patched) {
			DataTableManager.prototype.make_dt = function () {
				const me = this;
				frappe.call({
					method: "china_finance.services.bank_reconciliation.get_bank_transactions_with_summary",
					args: {
						bank_account: this.bank_account,
						from_date: this.bank_statement_from_date,
						to_date: this.bank_statement_to_date,
					},
					callback: function (response) {
						me.format_data(response.message || []);
						me.get_dt_columns();
						me.get_datatable();
						me.set_listeners();
					},
				});
			};

			DataTableManager.prototype.get_dt_columns = function () {
				native_get_dt_columns.call(this);
				this.columns.splice(3, 0, {
					name: __("摘要"),
					editable: false,
					width: 180,
				});
			};

			DataTableManager.prototype.format_row = function (row) {
				const formatted = native_format_row.call(this, row);
				formatted.splice(3, 0, row.custom_summary || "");
				return formatted;
			};
			DataTableManager.prototype.__china_finance_patched = true;
		}

		prototype.show_dialog = function (bank_transaction_name, update_dt_cards) {
			this.bank_transaction_name = bank_transaction_name;
			this.update_dt_cards = update_dt_cards;
			frappe.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "Bank Transaction",
					filters: { name: bank_transaction_name },
					fieldname: [
						"date", "deposit", "withdrawal", "currency", "description", "custom_summary",
						"name", "bank_account", "company", "reference_number", "party_type", "party",
						"unallocated_amount", "allocated_amount", "transaction_type",
					],
				},
				callback: (response) => {
					if (!response.message) return;
					this.bank_transaction = response.message;
					this.bank_transaction.custom_summary = clean_bank_summary(
						this.bank_transaction.custom_summary || this.bank_transaction.description
					);
					this.bank_transaction.payment_entry = 1;
					this.bank_transaction.journal_entry = 1;
					this.dialog.set_values(this.bank_transaction);
					const summary = this.bank_transaction.custom_summary || "";
					if (this.dialog.fields_dict.description) {
						const description_wrapper = this.dialog.fields_dict.description.$wrapper;
						let summary_wrapper = this.dialog.$wrapper.find(
							"[data-fieldname='china_finance_summary']"
						);
						if (!summary_wrapper.length) {
							summary_wrapper = $(
								`<div class="form-group" data-fieldname="china_finance_summary">
									<div class="clearfix"><label class="control-label">${__("摘要")}</label></div>
									<textarea class="form-control" readonly rows="3"></textarea>
								</div>`
							);
							description_wrapper.before(summary_wrapper);
						}
						summary_wrapper.find("textarea").val(summary).prop("readonly", true);
					}
					this.copy_data_to_voucher();
					this.dialog.show();
				},
			});
		};

		prototype.add_journal_entry = function (values) {
			frappe.call({
				method: "china_finance.services.bank_reconciliation.create_journal_entry_with_summary",
				args: {
					bank_transaction_name: this.bank_transaction.name,
					reference_number: values.reference_number,
					reference_date: values.reference_date,
					party_type: values.party_type,
					party: values.party,
					posting_date: values.posting_date,
					mode_of_payment: values.mode_of_payment,
					entry_type: values.journal_entry_type,
					second_account: values.second_account,
					remarks: this.bank_transaction.custom_summary || this.bank_transaction.description || "",
					allow_edit: true,
				},
				callback: (response) => {
					const docs = frappe.model.sync(response.message);
					const alert_string = __("Bank Transaction {0} added as a draft Journal Entry", [
						this.bank_transaction.name,
					]);
					frappe.show_alert(alert_string);
					this.dialog.hide();
					if (docs?.[0]) frappe.set_route("Form", docs[0].doctype, docs[0].name);
				},
			});
	};

	function clean_bank_summary(value) {
		return String(value || "")
			.split("｜", 1)[0]
			.replace(/\s*参考\s*#?.*$/i, "")
			.trim();
	}

	prototype.edit_in_full_page = function () {
			if (this.dialog.get_value("document_type") !== "Journal Entry") {
				return native_edit_in_full_page.call(this);
			}

			const summary = this.bank_transaction?.custom_summary || this.bank_transaction?.description || "";
			const values = this.dialog.get_values(true);
			frappe.call({
				method: "china_finance.services.bank_reconciliation.create_journal_entry_with_summary",
				args: {
					bank_transaction_name: this.bank_transaction.name,
					reference_number: values.reference_number,
					reference_date: values.reference_date,
					party_type: values.party_type,
					party: values.party,
					posting_date: values.posting_date,
					mode_of_payment: values.mode_of_payment,
					entry_type: values.journal_entry_type,
					second_account: values.second_account,
					allow_edit: true,
					remarks: summary,
				},
				callback: (response) => {
					const doc = frappe.model.sync(response.message);
					frappe.set_route("Form", doc[0].doctype, doc[0].name);
				},
			});
		};

		prototype.__china_finance_patched = true;
		return true;
	};

	// The page controller loads the reconciliation bundle asynchronously. Load it
	// first so the first table is created with the patched data source and columns.
	frappe.require("bank-reconciliation-tool.bundle.js", () => {
		if (try_patch()) return;
		const timer = setInterval(() => {
			if (try_patch()) clearInterval(timer);
		}, 100);
		setTimeout(() => clearInterval(timer), 10000);
	});
})();
