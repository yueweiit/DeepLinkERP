(function () {
	const indicators = {
		Queued: [__("Queued"), "orange"],
		Processing: [__("Processing"), "blue"],
		Success: [__("Success"), "green"],
		Failed: [__("Failed"), "red"],
	};

	frappe.listview_settings["MES Material Request Task"] = {
		add_fields: ["status"],
		get_indicator(doc) {
			const indicator = indicators[doc.status] || [__(doc.status || "Unknown"), "gray"];
			return [indicator[0], indicator[1], `status,=,${doc.status}`];
		},
	};
})();
