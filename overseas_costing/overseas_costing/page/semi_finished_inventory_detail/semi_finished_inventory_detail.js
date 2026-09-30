(function () {
  "use strict";
  const route = "semi-finished-inventory-detail";
  frappe.pages[route] = frappe.pages[route] || {};
  frappe.pages[route].on_page_load = function (wrapper) {
    globalThis.CategorizedInventoryDetail.bootstrap(wrapper, {
      category: "semi_finished",
      title: "半成品库存明细",
    });
  };
})();
