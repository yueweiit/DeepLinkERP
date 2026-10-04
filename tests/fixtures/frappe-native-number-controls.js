// Pinned read-only Frappe native control source from root QA snapshot.
// Test fixture only: exercises real parse/get_value/change formatting; never a production replacement.
// Frappe Technologies and contributors, MIT license.
// Native base_control.js
frappe.ui.form.Control = class BaseControl {
	constructor(opts) {
		$.extend(this, opts);
		this.make();
		if (this.render_input) {
			this.refresh();
		}
	}
	make() {
		this.make_wrapper();
		this.$wrapper
			.attr("data-fieldtype", this.df.fieldtype)
			.attr("data-fieldname", this.df.fieldname);
		this.wrapper = this.$wrapper.get(0);
		this.wrapper.fieldobj = this; // reference for event handlers

		this.tooltip = $(`<span class="tooltip-content">${__(this.df.fieldname)}</span>`);
		this.$wrapper.append(this.tooltip);

		this.tooltip.on("click", (e) => {
			let text = $(e.target).text();
			frappe.utils.copy_to_clipboard(text);
		});
	}

	make_wrapper() {
		this.$wrapper = $("<div class='frappe-control'></div>").appendTo(this.parent);

		// alias
		this.wrapper = this.$wrapper;
	}

	toggle(show) {
		this.df.hidden = show ? 0 : 1;
		this.refresh();
	}

	get perm() {
		return this.frm?.perm;
	}

	set perm(_perm) {
		console.error("Setting perm on controls isn't supported, update form's perm instead");
	}

	// returns "Read", "Write" or "None"
	// as strings based on permissions
	get_status(explain) {
		if (this.df.get_status) {
			return this.df.get_status(this);
		}

		if (
			(!this.doctype && !this.docname) ||
			this.df.parenttype === "Web Form" ||
			this.df.is_web_form
		) {
			let status = "Write";

			// like in case of a dialog box
			if (cint(this.df.hidden)) {
				if (explain) console.log("By Hidden: None");
				return "None";
			} else if (cint(this.df.hidden_due_to_dependency)) {
				if (explain) console.log("By Hidden Dependency: None");
				return "None";
			} else if (
				cint(this.df.read_only || this.df.is_virtual || this.df.fieldtype === "Read Only")
			) {
				if (explain) console.log("By Read Only: Read");
				status = "Read";
			} else if (
				(this.grid && this.grid.display_status == "Read") ||
				(this.layout && this.layout.grid && this.layout.grid.display_status == "Read")
			) {
				// parent grid is read
				if (explain) console.log("By Parent Grid Read-only: Read");
				status = "Read";
			}

			let value = this.value || this.get_model_value();
			value = this.get_parsed_value(value);

			if (
				status === "Read" &&
				is_null(value) &&
				!["HTML", "Image", "Button"].includes(this.df.fieldtype)
			)
				status = "Read";

			return status;
		}

		var status = frappe.perm.get_field_display_status(
			this.df,
			frappe.model.get_doc(this.doctype, this.docname),
			this.perm || (this.frm && this.frm.perm),
			explain
		);

		// Match parent grid controls read only status
		if (
			status === "Write" &&
			(this.grid || (this.layout && this.layout.grid && !cint(this.df.allow_on_submit)))
		) {
			var grid = this.grid || this.layout.grid;
			if (grid.display_status == "Read") {
				status = "Read";
				if (explain) console.log("By Parent Grid Read-only: Read");
			}
		}

		let value = frappe.model.get_value(this.doctype, this.docname, this.df.fieldname);

		if (["Date", "Datetime"].includes(this.df.fieldtype) && value) {
			value = frappe.datetime.str_to_user(value);
		}

		value = this.get_parsed_value(value);

		// hide if no value
		if (
			this.doctype &&
			status === "Read" &&
			!this.only_input &&
			is_null(value) &&
			cint(frappe.boot.sysdefaults.hide_empty_read_only_fields) &&
			!["HTML", "Image", "Button", "Geolocation"].includes(this.df.fieldtype)
		) {
			if (explain) console.log("By Hide Read-only, null fields: None");
			status = "None";
		}

		return status;
	}
	refresh() {
		this.disp_status = this.get_status();
		this.$wrapper &&
			this.$wrapper.toggleClass("hide-control", this.disp_status == "None") &&
			this.refresh_input &&
			this.refresh_input();

		var value = this.get_value();

		this.show_translatable_button(value);
	}
	show_translatable_button(value) {
		// Disable translation non-string fields or special string fields
		if (
			!frappe.model ||
			!this.frm ||
			!this.doc ||
			!this.df.translatable ||
			!frappe.model.can_write("Translation") ||
			!value
		)
			return;

		// Disable translation in website
		if (!frappe.views || !frappe.views.TranslationManager) return;

		// Already attached button
		if (this.$wrapper.find(".clearfix .btn-translation").length) return;

		const translation_btn = `<a class="btn-translation no-decoration text-muted" title="${__(
			"Open Translation"
		)}">
				<i class="fa fa-globe"></i>
			</a>`;

		$(translation_btn)
			.appendTo(this.$wrapper.find(".clearfix"))
			.on("click", () => {
				if (!this.doc.__islocal) {
					new frappe.views.TranslationManager({
						df: this.df,
						source_text: this.value,
						target_language: this.doc.language,
						doc: this.doc,
					});
				}
			});
	}
	get_doc() {
		return (
			(this.doctype &&
				this.docname &&
				locals[this.doctype] &&
				locals[this.doctype][this.docname]) ||
			{}
		);
	}
	get_model_value() {
		if (this.doc) {
			return this.doc[this.df.fieldname];
		}
	}
	get_parsed_value(value) {
		if (this.parse) {
			value = this.parse(value);
		}
		return value;
	}

	set_value(value, force_set_value = false) {
		return this.validate_and_set_in_model(value, null, force_set_value);
	}
	parse_validate_and_set_in_model(value, e) {
		value = this.get_parsed_value(value);
		return this.validate_and_set_in_model(value, e);
	}
	validate_and_set_in_model(value, e, force_set_value = false) {
		const me = this;
		const is_value_same = this.get_model_value() === value;

		if (this.inside_change_event || (is_value_same && !force_set_value)) {
			return Promise.resolve();
		}

		const old_value = this.get_model_value();
		this.frm?.undo_manager?.record_change({
			fieldname: me.df.fieldname,
			old_value,
			new_value: value,
			doctype: this.doctype,
			docname: this.docname,
			is_child: Boolean(this.doc?.parenttype),
		});
		this.inside_change_event = true;
		function set(value) {
			me.inside_change_event = false;
			return frappe.run_serially([
				() => (me._validated = true),
				() => me.set_model_value(value),
				() => delete me._validated,
				() => {
					me.set_mandatory && me.set_mandatory(value);

					if (me.df.change || me.df.onchange) {
						// onchange event specified in df
						let set = (me.df.change || me.df.onchange).apply(me, [e]);
						me.set_invalid && me.set_invalid();
						return set;
					}
					me.set_invalid && me.set_invalid();
				},
			]);
		}
		value = this.validate(value);
		if (value && value.then) {
			// got a promise
			return value.then((value) => set(value));
		} else {
			// all clear
			return set(value);
		}
	}
	get_value() {
		if (this.get_status() === "Write") {
			return this.get_input_value
				? this.parse
					? this.parse(this.get_input_value())
					: this.get_input_value()
				: undefined;
		} else {
			return this.value || undefined;
		}
	}
	set_model_value(value) {
		if (this.frm) {
			this.last_value = value;
			return frappe.model.set_value(
				this.doctype,
				this.docname,
				this.df.fieldname,
				value,
				this.df.fieldtype
			);
		} else {
			if (this.doc) {
				this.doc[this.df.fieldname] = value;
			}
			this.set_input(value);
			return Promise.resolve();
		}
	}
	set_focus() {
		if (this.$input) {
			this.$input.get(0).focus();
			return true;
		}
	}
};

frappe.ui.form.ControlInput = frappe.ui.form.Control;
// Native data.js
frappe.provide("frappe.phone_call");

frappe.ui.form.ControlData = class ControlData extends frappe.ui.form.ControlInput {
	static html_element = "input";
	static input_type = "text";
	static trigger_change_on_input_event = true;
	make_input() {
		if (this.$input) return;

		let { html_element, input_type, input_mode } = this.constructor;

		this.$input = $("<" + html_element + ">")
			.attr("type", input_type)
			.attr("inputmode", input_mode)
			.attr("autocomplete", "off")
			.addClass("input-with-feedback form-control")
			.prependTo(this.input_area);

		this.$input.on("paste", (e) => {
			let pasted_data = frappe.utils.get_clipboard_data(e);
			let maxlength = this.$input.attr("maxlength");
			if (maxlength && pasted_data.length > maxlength) {
				let warning_message = __(
					"The value you pasted was {0} characters long. Max allowed characters is {1}.",
					[cstr(pasted_data.length).bold(), cstr(maxlength).bold()]
				);

				// Only show edit link to users who can update the doctype
				if (this.frm && frappe.model.can_write(this.frm.doctype)) {
					let doctype_edit_link = null;
					if (this.frm.meta.custom) {
						doctype_edit_link = frappe.utils.get_form_link(
							"DocType",
							this.frm.doctype,
							true,
							__("this form")
						);
					} else {
						doctype_edit_link = frappe.utils.get_form_link(
							"Customize Form",
							"Customize Form",
							true,
							null,
							{
								doc_type: this.frm.doctype,
							}
						);
					}
					let edit_note = __(
						"{0}: You can increase the limit for the field if required via {1}",
						[__("Note").bold(), doctype_edit_link]
					);
					warning_message += `<br><br><span class="text-muted text-small">${edit_note}</span>`;
				}

				frappe.msgprint({
					message: warning_message,
					indicator: "orange",
					title: __("Data Clipped"),
				});
			}
		});

		this.set_input_attributes();
		this.input = this.$input.get(0);
		this.has_input = true;
		this.bind_change_event();
		this.setup_autoname_check();
		this.setup_copy_button();
		if (this.df.options == "URL") {
			this.setup_url_field();
		}
		if (this.df.options == "Barcode") {
			this.setup_barcode_field();
		}
		if (this.df.options == "IBAN") {
			this.setup_iban_field();
		}
	}

	setup_url_field() {
		this.$wrapper.find(".control-input").append(
			`<span class="link-btn">
				<a class="btn-open no-decoration" title="${__("Open Link")}" target="_blank">
					${frappe.utils.icon("link-url", "sm")}
				</a>
			</span>`
		);

		this.$link = this.$wrapper.find(".link-btn");
		this.$link_open = this.$link.find(".btn-open");

		this.$input.on("focus", () => {
			setTimeout(() => {
				let inputValue = this.get_input_value();

				if (inputValue && validate_url(inputValue)) {
					this.$link.toggle(true);
					this.$link_open.attr("href", this.get_input_value());
				}
			}, 500);
		});

		this.$input.bind("input", () => {
			let inputValue = this.get_input_value();

			if (inputValue && validate_url(inputValue)) {
				this.$link.toggle(true);
				this.$link_open.attr("href", this.get_input_value());
			} else {
				this.$link.toggle(false);
			}
		});

		this.$input.on("blur", () => {
			// if this disappears immediately, the user's click
			// does not register, hence timeout
			setTimeout(() => {
				this.$link.toggle(false);
			}, 500);
		});
	}

	setup_iban_field() {
		this.$input.on("blur", () => {
			this.set_formatted_input(this.get_input_value());
		});
	}

	setup_copy_button() {
		if (this.df.with_copy_button) {
			this.$wrapper
				.find(".control-input")
				.append(
					`<button class="btn action-btn">
					${frappe.utils.icon("clipboard", "sm")}
				</button>`
				)
				.find(".action-btn")
				.click(() => {
					frappe.utils.copy_to_clipboard(this.value);
				});
		}
	}

	setup_barcode_field() {
		this.$wrapper.find(".control-input").append(
			`<span class="link-btn">
				<a class="btn-open no-decoration" title="${__("Scan")}">
					${frappe.utils.icon("scan-barcode", "sm")}
				</a>
			</span>`
		);

		this.$scan_btn = this.$wrapper.find(".link-btn");
		this.$scan_btn.toggle(true);

		const me = this;
		$(document).on("frappe.ui.Dialog:shown", function () {
			me.$scan_btn.toggle(true);
		});
		this.$scan_btn.on("click", "a", () => {
			new frappe.ui.Scanner({
				dialog: true,
				multiple: false,
				on_scan(data) {
					if (data && data.result && data.result.text) {
						me.set_value(data.result.text);
					}
				},
			});
		});
	}

	bind_change_event() {
		const change_handler = (e) => {
			if (this.change) this.change(e);
			else {
				let value = this.get_input_value();
				this.parse_validate_and_set_in_model(value, e);
			}
		};
		this.$input.on("change", change_handler);
		if (this.constructor.trigger_change_on_input_event && !this.in_grid()) {
			// debounce to avoid repeated validations on value change
			this.$input.on("input", frappe.utils.debounce(change_handler, 500));
		}
	}
	setup_autoname_check() {
		if (!this.df.parent) return;
		this.meta = frappe.get_meta(this.df.parent);
		if (
			this.meta &&
			((this.meta.autoname &&
				this.meta.autoname.substr(0, 6) === "field:" &&
				this.meta.autoname.substr(6) === this.df.fieldname) ||
				this.df.fieldname === "__newname")
		) {
			this.$input.on("keyup", () => {
				this.set_description("");
				if (this.doc && this.doc.__islocal) {
					// check after 1 sec
					let timeout = setTimeout(() => {
						// clear any pending calls
						if (this.last_check) clearTimeout(this.last_check);

						// check if name exists
						frappe.db.get_value(
							this.doctype,
							this.$input.val(),
							"name",
							(val) => {
								if (val && val.name) {
									this.set_description(
										__("{0} already exists. Select another name", [val.name])
									);
								}
							},
							this.doc.parenttype
						);
						this.last_check = null;
					}, 1000);
					this.last_check = timeout;
				}
			});
		}
	}
	set_input_attributes() {
		if (
			["Data", "Link", "Dynamic Link", "Password", "Select", "Read Only"].includes(
				this.df.fieldtype
			)
		) {
			if (this.frm?.meta?.issingle) {
				// singles dont have any "real" length requirements
				return;
			}
			this.$input.attr("maxlength", this.df.length || 140);
		}

		this.$input
			.attr("data-fieldtype", this.df.fieldtype)
			.attr("data-fieldname", this.df.fieldname)
			.attr("placeholder", __(this.df.placeholder || ""));
		if (this.doctype) {
			this.$input.attr("data-doctype", this.doctype);
		}
		if (this.df.input_css) {
			this.$input.css(this.df.input_css);
		}
		if (this.df.input_class) {
			this.$input.addClass(this.df.input_class);
		}
		// Apply alignment for supported field types
		if (
			this.df.alignment &&
			["Data", "Int", "Float", "Currency", "Percent"].includes(this.df.fieldtype)
		) {
			this.$input.css("text-align", this.df.alignment.toLowerCase());
		}
	}
	set_input(value) {
		this.last_value = this.value;
		this.value = value;
		this.set_formatted_input(value);
		this.set_disp_area(value);
		this.set_mandatory && this.set_mandatory(value);
	}
	set_formatted_input(value) {
		this.$input && this.$input.val(this.format_for_input(value));
	}
	get_input_value() {
		return this.$input ? this.$input.val() : undefined;
	}
	format_for_input(val) {
		if (this.df.options == "IBAN" && val) {
			return frappe.utils.get_formatted_iban(val);
		}
		return val == null ? "" : val;
	}
	parse(value) {
		if (this.df.options == "IBAN" && value) {
			return value.replaceAll(" ", "");
		}
		return value;
	}
	validate(v) {
		if (!v) {
			return "";
		}
		if (this.df.is_filter) {
			return v;
		}
		if (this.df.options == "Phone") {
			this.df.invalid = !validate_phone(v);
			return v;
		} else if (this.df.options == "Name") {
			this.df.invalid = !validate_name(v);
			return v;
		} else if (this.df.options == "Email") {
			var email_list = frappe.utils.split_emails(v);
			if (!email_list) {
				return "";
			} else {
				let email_invalid = false;
				email_list.forEach(function (email) {
					if (!validate_email(email)) {
						email_invalid = true;
					}
				});
				this.df.invalid = email_invalid;
				return v;
			}
		} else if (this.df.options == "URL") {
			this.df.invalid = !validate_url(v);
			return v;
		} else {
			return v;
		}
	}
	toggle_container_scroll(el_class, scroll_class, add = false) {
		let el = this.$input.parents(el_class)[0];
		if (el) $(el).toggleClass(scroll_class, add);
	}
	in_grid() {
		return this.grid || (this.layout && this.layout.grid);
	}
};

frappe.ui.form.ControlReadOnly = frappe.ui.form.ControlData;

// Native int.js
frappe.ui.form.ControlInt = class ControlInt extends frappe.ui.form.ControlData {
	static trigger_change_on_input_event = false;
	static input_mode = "numeric";
	make() {
		super.make();
	}
	make_input() {
		super.make_input();
		this.$input.on("focus", () => {
			document.activeElement?.select?.();
			return false;
		});
	}
	validate(value) {
		return this.parse(value);
	}
	eval_expression(value) {
		if (typeof value === "string") {
			const parsed_components = value.match(/[^\d.,]+|[\d.,]+/g);
			var parsed_value = value;
			if (parsed_components !== null) {
				parsed_value = parsed_components
					.map((v) => {
						return isNaN(parseFloat(v)) ? v : flt(v);
					})
					.join("");
			}
			if (parsed_value.match(/^[0-9+\-/*.() ]+$/)) {
				// If it is a string containing operators
				try {
					return eval(parsed_value);
				} catch (e) {
					// bad expression
					return value;
				}
			}
		}
		return value;
	}
	parse(value) {
		return cint(this.eval_expression(value), null);
	}
};

frappe.ui.form.ControlLongInt = frappe.ui.form.ControlInt;

// Native float.js
frappe.ui.form.ControlFloat = class ControlFloat extends frappe.ui.form.ControlInt {
	static input_mode = "decimal";
	parse(value) {
		value = this.eval_expression(value);
		return isNaN(parseFloat(value)) ? null : flt(value, this.get_precision());
	}

	format_for_input(value) {
		if (value === null || value === undefined || isNaN(Number(value))) {
			return "";
		}

		return format_number(value, this.get_number_format(), this.get_precision());
	}

	get_number_format() {
		if (this.df.fieldtype === "Float" && !this.df.options?.trim()) return;

		const currency = frappe.meta.get_field_currency(this.df, this.get_doc());
		return get_number_format(currency);
	}

	get_precision() {
		// round based on field precision or float precision, else don't round
		return this.df.precision || cint(frappe.boot.sysdefaults.float_precision, null);
	}
};

frappe.ui.form.ControlPercent = frappe.ui.form.ControlFloat;

// Native currency.js
frappe.ui.form.ControlCurrency = class ControlCurrency extends frappe.ui.form.ControlFloat {
	get_precision() {
		// always round based on field precision or currency's precision
		// this method is also called in this.parse()
		if (typeof this.df.precision != "number" && !this.df.precision) {
			if (frappe.boot.sysdefaults.currency_precision) {
				this.df.precision = frappe.boot.sysdefaults.currency_precision;
			} else {
				this.df.precision = get_number_format_info(this.get_number_format()).precision;
			}
		}

		return this.df.precision;
	}
};
