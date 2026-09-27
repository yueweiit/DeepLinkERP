/* global china_finance */

frappe.provide("china_finance.datatable_layout");

(() => {
	function apply_full_width(datatable) {
		const scrollable = datatable?.bodyScrollable;
		if (!scrollable) return;
		scrollable.style.setProperty("width", "100%", "important");
		scrollable.style.setProperty("min-width", "0", "important");
	}

	function refresh_after_column_resize(report) {
		window.requestAnimationFrame(() => {
			const datatable = report.datatable;
			if (!datatable?.style) return;
			datatable.style.refreshColumnWidth();
			datatable.style.setBodyStyle();
			apply_full_width(datatable);
		});
	}

	china_finance.datatable_layout.bind_full_width = (report, datatable) => {
		apply_full_width(datatable);
		if (report.__china_finance_full_width_datatable_layout) return;
		report.__china_finance_full_width_datatable_layout = true;

		report.$report.on(
			"dblclick.china_finance_full_width_datatable_layout",
			".dt-cell__resize-handle",
			() => refresh_after_column_resize(report),
		);

		if (typeof ResizeObserver !== "undefined" && report.$report?.[0]) {
			const observer = new ResizeObserver(() => apply_full_width(report.datatable));
			observer.observe(report.$report[0]);
			report.__china_finance_full_width_datatable_observer = observer;
		}
	};
})();
