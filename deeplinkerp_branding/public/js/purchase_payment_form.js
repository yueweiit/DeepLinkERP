if (!window.dlpPurchasePaymentFormInstalled) {
 window.dlpPurchasePaymentFormInstalled = true;
 frappe.ui.form.on("Purchase Receipt", {refresh: frm => DeepLinkERPPurchasePayments.formRefresh(frm)});
 frappe.ui.form.on("Purchase Order", {refresh: frm => DeepLinkERPPurchasePayments.formRefresh(frm)});
}
