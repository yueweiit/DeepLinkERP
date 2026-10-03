frappe.pages["purchase-payment-records"].on_page_load = wrapper => DeepLinkERPPurchasePayments.recordsPage(wrapper);
frappe.pages["purchase-payment-records"].on_page_show = wrapper => wrapper.dlpLoad?.();
