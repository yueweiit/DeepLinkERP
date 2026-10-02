(function () {
	"use strict";
	const route = "finished-goods-inventory-detail";
	frappe.pages[route] = frappe.pages[route] || {};
	frappe.pages[route].on_page_load = function (wrapper) {
		globalThis.InventoryDetail.bootstrap(wrapper, {
			category: "finished_goods",
			title: "成品库存明细",
		});
	};
})();
