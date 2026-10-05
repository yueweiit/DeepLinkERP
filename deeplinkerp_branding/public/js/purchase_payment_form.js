if (!window.dlpPurchasePaymentFormInstalled) {
 window.dlpPurchasePaymentFormInstalled = true;
 for (const doctype of ["Purchase Receipt", "Purchase Order", "Purchase Invoice", "Payment Entry"]) {
  frappe.ui.form.on(doctype, {refresh: frm => DeepLinkERPPurchasePayments.formRefresh(frm)});
 }
}
