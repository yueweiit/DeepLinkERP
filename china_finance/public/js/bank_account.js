frappe.ui.form.on("Bank Account", {
	refresh(frm) {
		china_finance_prepare_bank_account_link(frm);
	},
	company(frm) {
		const control = china_finance_prepare_bank_account_link(frm);
		if (!control?.$input) return frm.set_value("account", "");

		// Link search caches use the search text, not the company filter.
		control.$input.cache = {};
		control.title_value_map = {};
		return control.set_value("");
	},
	async before_save(frm) {
		const control = frm.fields_dict.account;
		// A blur event can enqueue another validation while Save is waiting.
		while (control?.china_finance_pending_value) {
			await control.china_finance_pending_value;
		}
	},
});

function china_finance_prepare_bank_account_link(frm) {
	const control = frm.fields_dict.account;
	if (!control?.$input || control.china_finance_bank_link_ready) return control;
	control.china_finance_bank_link_ready = true;

	const native_parse = control.parse_validate_and_set_in_model;
	control.parse_validate_and_set_in_model = function (value, event, label) {
		if (label && value) {
			// Preserve the selected name immediately: different companies can have
			// identical account titles, including while validation is in flight.
			this.title_value_map ||= {};
			this.title_value_map[this.get_translated(label)] = value;
		}
		return native_parse.call(this, value, event, label);
	};

	const native_validate = control.validate_and_set_in_model;
	control.validate_and_set_in_model = function (value, event, force_set_value = false) {
		// Frappe drops a new selection when inside_change_event is still true.
		// Serialize changes on this field, retaining the native link validation.
		const validate = async () => {
			try {
				return await native_validate.call(this, value, event, force_set_value);
			} catch (error) {
				// A failed request must not leave subsequent selections locked out.
				this.inside_change_event = false;
				throw error;
			}
		};
		const previous = this.china_finance_pending_value;
		const result = previous ? previous.then(validate, validate) : validate();
		const pending = Promise.resolve(result).finally(() => {
			if (this.china_finance_pending_value === pending) {
				delete this.china_finance_pending_value;
			}
		});
		this.china_finance_pending_value = pending;
		return pending;
	};
	return control;
}
