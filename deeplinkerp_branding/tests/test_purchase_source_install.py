"""Installation adds absent metadata only; existing OA/PO definitions win."""
import unittest
from unittest.mock import Mock, patch

import frappe
from deeplinkerp_branding import purchase_source_install as install


class PurchaseSourceInstallTests(unittest.TestCase):
    def test_existing_purchase_order_field_is_never_redefined(self):
        native = Mock()
        native.has_field.side_effect=lambda field:field=="custom_oa_purchase_expense"
        oa = Mock(); oa.has_field.return_value=True
        with patch.object(frappe,"db",Mock()),patch.object(frappe,"get_meta",side_effect=lambda dt:native if dt=="Purchase Order" else oa),patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields") as create:
            install.after_migrate()
        for call in create.call_args_list:
            self.assertNotIn("Purchase Order",call.args[0])

    def test_second_install_has_no_field_writes(self):
        meta=Mock(); meta.has_field.return_value=True
        with patch.object(frappe,"db",Mock()),patch.object(frappe,"get_meta",return_value=meta),patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields") as create:
            install.after_migrate()
        create.assert_not_called()


if __name__=="__main__": unittest.main()
