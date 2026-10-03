(function () {
	"use strict";
	const route = "inventory-location-detail";
	frappe.pages[route] = frappe.pages[route] || {};
	frappe.pages[route].on_page_load = function (wrapper) {
		globalThis.InventoryDetail.bootstrap(wrapper, {
			category: "material",
			title: "物料库存明细",
		});
	};
})();
