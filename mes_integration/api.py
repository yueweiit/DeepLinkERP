import frappe


@frappe.whitelist()
def create_stock_entry(data=None, stock_entry=None):
    """Short public alias for MES to create a draft Stock Entry."""
    from mes_integration.mes_integration.stock_entry import (
        create_draft_stock_entry_from_mes,
    )

    return create_draft_stock_entry_from_mes(data=data, stock_entry=stock_entry)


@frappe.whitelist()
def create_material_request(data=None, material_request=None):
    """Short public alias for MES to create and submit a Material Request."""
    from mes_integration.mes_integration.material_request import (
        create_and_submit_material_request_from_mes,
    )

    return create_and_submit_material_request_from_mes(
        data=data, material_request=material_request
    )
