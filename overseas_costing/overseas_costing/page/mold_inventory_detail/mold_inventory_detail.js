(function () {
  "use strict";
  const route = "mold-inventory-detail";
  frappe.pages[route] = frappe.pages[route] || {};
  frappe.pages[route].on_page_load = function (wrapper) {
    globalThis.CategorizedInventoryDetail.bootstrap(wrapper, {
      category: "mold",
      title: "模具库存明细",
    });
  };
})();
