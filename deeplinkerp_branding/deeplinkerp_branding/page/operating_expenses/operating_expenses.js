(function (root) {
	"use strict";
	root.frappe.pages["operating-expenses"].on_page_load = (wrapper) =>
		root.DeepLinkERPOperatingExpenses.onPageLoad(wrapper);
	root.frappe.pages["operating-expenses"].on_page_show = (wrapper) =>
		root.DeepLinkERPOperatingExpenses.onPageShow(wrapper);
})(globalThis);
