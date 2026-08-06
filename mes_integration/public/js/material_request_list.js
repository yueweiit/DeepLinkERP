const native_material_request_list_settings = frappe.listview_settings["Material Request"] || {};
const native_material_request_indicator = native_material_request_list_settings.get_indicator;
const mes_issue_material_request_types = [
	"Material Issue",
	"Material Transfer for Manufacture",
	"Injection Molding Issuance",
];

frappe.listview_settings["Material Request"] = {
	...native_material_request_list_settings,
	onload: function(listview) {
		if (typeof native_material_request_list_settings.onload === "function") {
			native_material_request_list_settings.onload(listview);
		}
		listview.page.add_action_item(__("发料并推送至DLM"), function() {
			batch_issue_and_push_material_requests(listview);
		});
	},
	get_indicator: function(doc) {
		if (!mes_issue_material_request_types.includes(doc.material_request_type)) {
			return get_native_material_request_indicator(doc);
		}

		return get_mes_issue_material_request_indicator(doc);
	},
};

function batch_issue_and_push_material_requests(listview) {
	const names = listview.get_checked_items(true);
	if (!names.length) {
		frappe.msgprint(__("请先选择物料需求。"));
		return;
	}

	frappe.require("/assets/mes_integration/js/material_request.js").then(function() {
		return Promise.all(names.map((name) => frappe.xcall("frappe.client.get", {
			doctype: "Material Request",
			name: name
		})));
	})
		.then((docs) => show_batch_issue_dialog(listview, docs))
		.catch(() => frappe.msgprint({
			title: __("操作失败"),
			indicator: "red",
			message: __("无法读取选中的物料需求。")
		}));
}

function show_batch_issue_dialog(listview, docs) {
	const issueable_docs = docs.filter((doc) => can_batch_issue_material_request(doc));
	if (!issueable_docs.length) {
		frappe.msgprint({ title: __("提示"), indicator: "orange", message: __("没有可发料的物料需求。") });
		return;
	}

	const table_configs = issueable_docs.map(function(doc, index) {
		const fieldname = `items_${index}`;
		const is_transfer = doc.material_request_type === "Material Transfer for Manufacture";
		const fields = get_issue_and_push_dialog_fields({ doc }, is_transfer);
		fields.push({ fieldtype: "Check", fieldname: "is_transfer", hidden: 1, read_only: 1 });
		configure_batch_issue_dialog_fields(fields, is_transfer);
		return { doc, fieldname, is_transfer, fields, rows: get_batch_issue_rows(doc) };
	});
	const dialog_fields = [
		{ fieldtype: "HTML", fieldname: "message", options: `<p class="text-muted">${__("请确认本次发料数量和发料仓，确认后将自动创建并提交物料移动，然后推送至 DLM。")}</p>` }
	];
	table_configs.forEach(function(config) {
		dialog_fields.push({
			fieldtype: "HTML",
			fieldname: `${config.fieldname}_label`,
			options: `<h5 class="mb-2">${frappe.utils.escape_html(config.doc.name)}</h5>`
		});
		dialog_fields.push({
			fieldtype: "Table",
			fieldname: config.fieldname,
			label: __("物料"),
			cannot_add_rows: true,
			in_place_edit: true,
			data: config.rows,
			fields: config.fields
		});
	});
	const dialog = new frappe.ui.Dialog({
		title: __("发料并推送至DLM"),
		size: "extra-large",
		fields: dialog_fields,
		primary_action_label: __("确定"),
		primary_action: function(values) {
			const grouped = {};
			for (const config of table_configs) {
				for (const row of values[config.fieldname] || []) {
					const validated_rows = get_validated_issue_and_push_rows([row], config.is_transfer);
					if (!validated_rows) {
						return;
					}
					(grouped[config.doc.name] ||= []).push(validated_rows[0]);
				}
			}
			if (!Object.keys(grouped).length) {
				return;
			}
			dialog.hide();
			call_batch_issue_and_push_to_dlm(listview, Object.keys(grouped), grouped);
		}
	});
	dialog.show();
	table_configs.forEach(function(config) {
		setup_issue_and_push_dialog_warehouse_queries({ doc: config.doc }, dialog, config.fieldname);
		setup_issue_dialog_actual_qty_refresh(dialog, config.fieldname);
		refresh_issue_dialog_actual_qty(dialog, config.fieldname);
	});
	dialog.$wrapper.addClass("mes-issue-push-dialog");
	dialog.$wrapper.find(".modal-dialog").css({
		width: "min(1400px, 96vw)",
		maxWidth: "96vw"
	});
}

function configure_batch_issue_dialog_fields(fields, is_transfer) {
	fields.forEach(function(field) {
		if (field.fieldname === "material_request") {
			field.columns = 1;
		}
		if (field.fieldname === "s_warehouse") {
			field.columns = 1;
		}
		if (field.fieldname === "t_warehouse") {
			field.columns = 1;
		}
		if (field.fieldname === "t_warehouse" && !is_transfer) {
			field.in_list_view = 0;
			field.hidden = 1;
		}
	});
}

function can_batch_issue_material_request(doc) {
	return doc.docstatus === 1 && doc.status !== "Stopped" && doc.status !== "Cancelled" &&
		mes_issue_material_request_types.includes(doc.material_request_type) && flt(doc.per_ordered) < 100;
}

function get_batch_issue_rows(doc) {
	return (doc.items || []).map((row) => {
		const conversion_factor = flt(row.conversion_factor) || 1;
		const remaining_qty = Math.max(flt(row.stock_qty || row.qty) - flt(row.ordered_qty), 0) / conversion_factor;
		return {
			material_request: doc.name,
			material_request_item: row.name,
			item_code: row.item_code,
			item_name: row.item_name,
			uom: row.uom || row.stock_uom,
			request_uom: row.uom || row.stock_uom,
			stock_uom: row.stock_uom || row.uom,
			original_conversion_factor: conversion_factor,
			conversion_factor,
			remaining_stock_qty: remaining_qty * conversion_factor,
			max_issue_stock_qty: remaining_qty * conversion_factor,
			max_issue_qty: remaining_qty,
			requested_qty: flt(row.qty),
			issued_qty: flt(row.ordered_qty) / conversion_factor,
			remaining_qty,
			qty: remaining_qty,
			s_warehouse: row.from_warehouse || row.warehouse || doc.set_from_warehouse || doc.set_warehouse,
			t_warehouse: row.warehouse || doc.set_warehouse,
			is_transfer: doc.material_request_type === "Material Transfer for Manufacture"
		};
	}).filter((row) => row.item_code && row.remaining_qty > 0);
}

function call_batch_issue_and_push_to_dlm(listview, names, items) {
	frappe.call({
		method: "mes_integration.mes_integration.material_request.batch_issue_and_push_to_dlm",
		args: { material_requests: names, items },
		freeze: true,
		freeze_message: __("正在批量发料并推送至 DLM，请稍候..."),
		callback: function(r) {
			show_batch_issue_result(r.message || {});
			listview.refresh();
		}
	});
}

function show_batch_issue_result(result) {
	const rows = result.results || [];
	const failed = rows.filter((row) => row.status !== "success");
	const title = failed.length ? __("批量处理完成（部分失败）") : __("批量处理完成");
	const indicator = failed.length ? "orange" : "green";
	const message = rows
		.map((row) => `${frappe.utils.escape_html(row.material_request)}：${frappe.utils.escape_html(row.message || "")}`)
		.join("<br>");
	frappe.msgprint({ title, indicator, message });
}

function get_mes_issue_material_request_indicator(doc) {
	const precision = frappe.defaults.get_default("float_precision");
	const per_ordered = flt(doc.per_ordered, precision);

	if (doc.status === "Stopped") {
		return [__("Stopped"), "red", "status,=,Stopped"];
	}

	if (doc.docstatus !== 1) {
		return get_native_material_request_indicator(doc);
	}

	if (per_ordered === 0) {
		return [__("Pending"), "orange", "per_ordered,=,0|docstatus,=,1"];
	}

	if (per_ordered < 100) {
		return [__("Partially Ordered"), "yellow", "per_ordered,<,100"];
	}

	if (per_ordered === 100) {
		return [__("Issued"), "green", "per_ordered,=,100"];
	}

	return get_native_material_request_indicator(doc);
}

function get_native_material_request_indicator(doc) {
	return native_material_request_indicator ? native_material_request_indicator(doc) : undefined;
}
