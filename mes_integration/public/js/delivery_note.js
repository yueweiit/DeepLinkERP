function load_mes_integration_enabled(frm) {
	if (!frm || !frm.doc || !frm.doc.company) {
		return Promise.resolve(false);
	}
	return frappe.db.get_value("Company", frm.doc.company, "custom_enable_mes_integration").then(function(r) {
		return cint(r && r.message ? r.message.custom_enable_mes_integration : 0) === 1;
	});
}

frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		load_mes_integration_enabled(frm).then(function(enabled) {
		if (enabled) {
			schedule_delivery_readiness_badge(frm);
		} else {
			remove_delivery_readiness_badge(frm);
		}
	});
	},
	custom_delivery_readiness_status(frm) {
		schedule_delivery_readiness_badge(frm);
	},
});

function schedule_delivery_readiness_badge(frm) {
	setTimeout(() => display_delivery_readiness_badge(frm), 100);
}

function display_delivery_readiness_badge(frm) {
	remove_delivery_readiness_badge(frm);

	if (!frm || !frm.doc || !frm.doc.custom_delivery_readiness_status) {
		return;
	}

	const status = frm.doc.custom_delivery_readiness_status;
	const color = get_delivery_readiness_color(status);
	const statusHtml = `<span class="delivery-readiness-badge indicator-pill no-indicator-dot whitespace-nowrap ${color}"><span>${__(status)}</span></span>`;
	const $titleArea = frm.page && frm.page.wrapper ? frm.page.wrapper.find(".title-area") : $(".title-area");
	const $statusIndicator = frm.page && frm.page.indicator && frm.page.indicator.length
		? frm.page.indicator
		: $titleArea.find(".indicator-pill").not(".delivery-readiness-badge").last();

	if ($statusIndicator.length) {
		$statusIndicator.after(statusHtml);
	} else if ($titleArea.length) {
		$titleArea.append(statusHtml);
	}
}

function remove_delivery_readiness_badge(frm) {
	if (frm && frm.page && frm.page.wrapper) {
		frm.page.wrapper.find(".delivery-readiness-badge").remove();
	}
	$(".delivery-readiness-badge").remove();
}

function get_delivery_readiness_color(status) {
	return {
		"Pending Release": "yellow",
		"Ready to Deliver": "blue",
		"Delivered": "green",
	}[status] || "gray";
}
