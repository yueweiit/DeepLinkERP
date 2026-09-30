(function () {
  "use strict";
  const route = "semi-finished-inventory-detail";
  frappe.pages[route] = frappe.pages[route] || {};
  frappe.pages[route].on_page_load = function (wrapper) {
    frappe.require([
      "/assets/overseas_costing/js/categorized_inventory_detail.js",
      "/assets/overseas_costing/css/categorized_inventory_detail.css",
    ], () => globalThis.CategorizedInventoryDetail.bootstrap(wrapper, {
      category: "semi_finished",
      title: "半成品库存明细",
    }));
  };
})();
