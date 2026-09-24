import frappe
from frappe import scrub

DOCTYPE = "OA Purchase Request"
MODULE = "Buying"
CLIENT_SCRIPT_NAME = "OA Purchase Request Hide Empty Fields"
LIST_CLIENT_SCRIPT_NAME = "OA Purchase Request Time Filters"

CHILD_DOCTYPES = {
	"OA Purchase Request Item": [
		("物品名称", "item_name", "Data", None),
		("编码", "item_code", "Data", None),
		("规格", "specification", "Small Text", None),
		("数量", "qty", "Float", None),
		("单位", "uom", "Data", None),
		("金额", "amount", "Currency", None),
	],
	"OA Purchase Request Processor": [
		("加工商名字", "processor_name", "Data", None),
		("电话", "processor_phone", "Data", None),
		("ODT", "odt", "Data", None),
		("销售订单", "sales_order_no", "Data", None),
		("加工物料", "processing_materials", "Data", None),
		("数量", "qty", "Float", None),
		("单价", "unit_price", "Currency", None),
		("金额", "amount", "Currency", None),
	],
	"OA Purchase Request Payment": [
		("收款人", "payee", "Data", None),
		("金额", "amount", "Currency", None),
		("付款条件", "payment_terms", "Data", None),
		("币种", "currency", "Data", None),
		("付款日期", "payment_date", "Date", None),
	],
}

FIELDS = [
	("申请日期Fecha de solicitud", "apply_date", "Date", None),
	("申请部门/组织 Departamento Solicitante", "department", "Data", None),
	("生产/非生产Produccion / No produccion", "production_type", "Data", None),
	("本月预算金额Importe presupuestado del mes", "monthly_budget_amount", "Currency", None),
	("本月预算已用金额Importe utilizado del presupuesto mensual", "monthly_budget_used", "Currency", None),
	("采购支出Gastos de Compra", "purchase_type", "Data", None),
	("订单Pedido", "order_no", "Data", None),
	("项目Proyecto", "project", "Data", None),
	("产品Producto", "product", "Data", None),
	("YW OEM IML Phone Case OEM IML手机保护套类", "yw_oem_iml_phone_case", "Data", None),
	("YW OEM Phone Case OEM手机保护套类", "yw_oem_phone_case", "Data", None),
	("YW OEM Tablet Case YW OEM 平板保护套类", "yw_oem_tablet_case", "Data", None),
	("YW OEM Soporte 支架类", "yw_oem_soporte", "Data", None),
	("YW MOLDES ODM YW模具 ODM类", "yw_moldes_odm", "Data", None),
	("咨询服务类 Servicios De Consultoria", "consulting_services", "Data", None),
	("Tiktok线上店铺", "tiktok_store", "Data", None),
	("执行地区Region de ejecucion", "execution_region", "Data", None),
	("订单采购Compras por pedido", "order_purchase_type", "Data", None),
	("费用分类 Clasificacion de gastos", "expense_category", "Data", None),
	("投资采购Compra de inversion", "investment_purchase_type", "Data", None),
	("服务类采购 Adquisiciones de servicios", "service_purchase_type", "Data", None),
	("MRO分类Clasificacion MRO", "mro_category", "Data", None),
	("生产性 Productivo MRO", "productive_mro", "Data", None),
	("非生产性 No productivo MRO", "non_productive_mro", "Data", None),
	("PDS分类Clasificacion PDS", "pds_category", "Data", None),
	("计件外包 Outsourcing por pieza", "piecework_outsourcing", "Data", None),
	("物流及运输服务Servicios de logistica y transporte", "logistics_transport_service", "Data", None),
	("清关服务Servicios de despacho aduanero", "customs_clearance_service", "Data", None),
	("需求明细", "items", "Table", "OA Purchase Request Item"),
	("需求明细Desglose de los gastos", "items_json", "Code", None),
	("明细汇总金额Monto total detallado", "detail_total_amount", "Currency", None),
	("加工商明细", "processors", "Table", "OA Purchase Request Processor"),
	("加工商明细detalles de los procesadores", "processors_json", "Code", None),
	("加工商名字Nombre del proveedor de servicios de procesam", "processor_name", "Data", None),
	("加工商电话Telefono del proveedor de servicios de proces", "processor_phone", "Data", None),
	("ODT", "odt", "Data", None),
	("销售订单号码El numero de la orden de venta", "sales_order_no", "Data", None),
	("加工物料Materiales de Procesamiento", "processing_materials", "Data", None),
	("数量Cantidad", "processor_qty", "Float", None),
	("单价Precio Unitario", "processor_unit_price", "Currency", None),
	("总金额Monto Total", "processor_total_amount", "Currency", None),
	("规格明细需求说明Descripcion de las necesidades de detalles", "description", "Small Text", None),
	("交付日期Fecha de entrega", "delivery_date", "Date", None),
	("付款信息", "payments", "Table", "OA Purchase Request Payment"),
	("付款信息", "payments_json", "Code", None),
	("收款人beneficiario", "payee", "Data", None),
	("金额importe", "payment_amount", "Currency", None),
	("付款条件Terminos de pago", "payment_terms", "Data", None),
	("币种Moneda", "currency", "Data", None),
	("付款日期Fecha de pago", "payment_date", "Date", None),
	("关键凭证Comprobante clave", "attachments_json", "Code", None),
	("审批完成时间", "approval_completed_at", "Data", None),
	("钉钉审批状态", "approval_status", "Data", None),
	("当前节点", "current_node", "Data", None),
	("当前负责人", "current_approver", "Data", None),
	("历史审批人", "approval_history", "Small Text", None),
	("审批编号", "oa_code", "Data", None),
	("创建人", "creator", "Data", None),
	("创建时间", "created_time", "Data", None),
	("更新时间", "updated_time", "Data", None),
	("创建人部门", "creator_department", "Data", None),
	("Process Instance ID", "process_instance_id", "Data", None),
	("Process Code", "process_code", "Data", None),
	("Form Name", "form_name", "Data", None),
	("Raw Payload", "raw_payload", "Code", None),
	(
		"Sync Status",
		"sync_status",
		"Select",
		"Pending Purchase Order\nPurchase Order Created\nFailed\nClosed\n来源失效\n来源已变化\n待复核\n已建草稿",
	),
	("Purchase Order", "purchase_order", "Link", "Purchase Order"),
	("OA Logistics Code", "oa_logistics_code", "Data", None),
	("Error Message", "error_message", "Small Text", None),
	("来源指纹", "source_fingerprint", "Data", None),
	("最新来源指纹", "latest_source_fingerprint", "Data", None),
	("目标公司", "target_company", "Link", "Company"),
	("目标仓库", "target_warehouse", "Link", "Warehouse"),
	("临时供应商", "temporary_supplier", "Link", "Supplier"),
	("原始收款方", "original_payee", "Small Text", None),
	("来源币种", "source_currency", "Link", "Currency"),
	("来源汇率", "source_exchange_rate", "Float", None),
	("来源状态", "source_state", "Select", "待复核\n已建草稿\n来源失效\n来源已变化"),
	("来源审批中", "source_pending", "Check", None),
	("来源已变化", "source_stale", "Check", None),
	("来源失效", "source_invalid", "Check", None),
	("汇率待复核", "exchange_rate_pending", "Check", None),
	("价格待补", "price_pending", "Check", None),
	("临时供应商待替换", "temporary_supplier_pending", "Check", None),
	("拉丁购历史回填", "backfill_imported", "Check", None),
]

FIELDNAMES_TO_UPDATE = {
	"approval_completed_at",
	"approval_status",
	"backfill_imported",
	"created_time",
	"exchange_rate_pending",
	"items",
	"latest_source_fingerprint",
	"payments",
	"oa_logistics_code",
	"original_payee",
	"price_pending",
	"process_instance_id",
	"purchase_order",
	"processors",
	"source_currency",
	"source_exchange_rate",
	"source_fingerprint",
	"source_invalid",
	"source_pending",
	"source_stale",
	"source_state",
	"sync_status",
	"target_company",
	"target_warehouse",
	"temporary_supplier",
	"temporary_supplier_pending",
	"updated_time",
}

FIELD_PROPERTIES = {
	"process_instance_id": {"unique": 1},
	"source_fingerprint": {"read_only": 1},
	"latest_source_fingerprint": {"read_only": 1},
	"backfill_imported": {"read_only": 1},
}

STANDARD_CUSTOM_FIELDS = {
	"Purchase Order": [
		{"fieldname": "custom_latingo_backfill", "label": "拉丁购历史回填", "fieldtype": "Check", "read_only": 1},
		{
			"fieldname": "custom_latingo_source_instance_id",
			"label": "拉丁购来源实例 ID",
			"fieldtype": "Data",
			"unique": 1,
			"read_only": 1,
		},
		{
			"fieldname": "custom_latingo_source_fingerprint",
			"label": "拉丁购来源指纹",
			"fieldtype": "Data",
			"read_only": 1,
		},
		{"fieldname": "custom_latingo_source_status", "label": "来源审批状态", "fieldtype": "Data", "read_only": 1},
		{"fieldname": "custom_latingo_source_result", "label": "来源审批结果", "fieldtype": "Data", "read_only": 1},
		{"fieldname": "custom_latingo_source_pending", "label": "来源审批中", "fieldtype": "Check", "read_only": 1},
		{"fieldname": "custom_latingo_source_stale", "label": "来源已变化", "fieldtype": "Check", "read_only": 1},
		{"fieldname": "custom_latingo_source_invalid", "label": "来源失效", "fieldtype": "Check", "read_only": 1},
		{
			"fieldname": "custom_latingo_exchange_rate_pending",
			"label": "MXN 汇率待复核",
			"fieldtype": "Check",
		},
		{"fieldname": "custom_latingo_price_pending", "label": "价格待补", "fieldtype": "Check", "read_only": 1},
		{
			"fieldname": "custom_latingo_temporary_supplier_pending",
			"label": "临时供应商待替换",
			"fieldtype": "Check",
			"read_only": 1,
		},
		{"fieldname": "custom_latingo_original_payee", "label": "原始收款方", "fieldtype": "Small Text", "read_only": 1},
	],
}

LIST_VIEW_FIELDS = {
	"approval_status",
	"purchase_order",
	"oa_logistics_code",
}

HIDDEN_LEGACY_FIELDS = {
	"attachments_json",
	"approval_history",
	"currency",
	"created_time",
	"creator",
	"creator_department",
	"form_name",
	"items_json",
	"odt",
	"oa_code",
	"payee",
	"payment_amount",
	"payment_date",
	"payment_terms",
	"payments_json",
	"processing_materials",
	"process_code",
	"process_instance_id",
	"processor_name",
	"processor_phone",
	"processor_qty",
	"processor_total_amount",
	"processor_unit_price",
	"processors_json",
	"raw_payload",
	"sales_order_no",
}


def after_install():
	create_or_update_oa_purchase_request()


def create_or_update_oa_purchase_request():
	for doctype, fields in CHILD_DOCTYPES.items():
		create_or_update_child_doctype(doctype, fields)

	if frappe.db.exists("DocType", DOCTYPE):
		doc = frappe.get_doc("DocType", DOCTYPE)
		existing = {field.fieldname for field in doc.fields}
		fields_by_name = {field.fieldname: field for field in doc.fields}
	else:
		doc = frappe.new_doc("DocType")
		doc.name = DOCTYPE
		doc.module = MODULE
		doc.custom = 1
		doc.istable = 0
		doc.issingle = 0
		doc.is_submittable = 0
		doc.track_changes = 1
		doc.permissions = []
		doc.append(
			"permissions",
			{
				"role": "System Manager",
				"read": 1,
				"write": 1,
				"create": 1,
				"delete": 1,
				"export": 1,
				"print": 1,
				"email": 1,
				"share": 1,
			},
		)
		existing = set()
		fields_by_name = {}

	doc.autoname = "field:oa_code"

	for label, fieldname, fieldtype, options in FIELDS:
		if fieldname in existing:
			if fieldname in FIELDNAMES_TO_UPDATE:
				field = fields_by_name[fieldname]
				field.label = label
				field.fieldtype = fieldtype
				field.options = options
			if fieldname in HIDDEN_LEGACY_FIELDS:
				fields_by_name[fieldname].hidden = 1
			if fieldname in LIST_VIEW_FIELDS:
				fields_by_name[fieldname].hidden = 0
				fields_by_name[fieldname].in_list_view = 1
			for property_name, value in FIELD_PROPERTIES.get(fieldname, {}).items():
				setattr(fields_by_name[fieldname], property_name, value)
			continue

		field = {
			"label": label,
			"fieldname": fieldname,
			"fieldtype": fieldtype,
		}
		if options:
			field["options"] = options
		if fieldname in HIDDEN_LEGACY_FIELDS:
			field["hidden"] = 1
		if fieldname in LIST_VIEW_FIELDS:
			field["in_list_view"] = 1
		field.update(FIELD_PROPERTIES.get(fieldname, {}))

		doc.append("fields", field)

	doc.save(ignore_permissions=True)
	create_or_update_standard_custom_fields()
	backfill_existing_child_tables()
	create_or_update_client_script()
	create_or_update_list_client_script()
	frappe.db.commit()
	frappe.clear_cache(doctype=DOCTYPE)

	return f"{DOCTYPE} created/updated successfully"


def create_or_update_standard_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(STANDARD_CUSTOM_FIELDS, update=True)


def create_or_update_child_doctype(doctype, fields):
	if frappe.db.exists("DocType", doctype):
		doc = frappe.get_doc("DocType", doctype)
		existing = {field.fieldname for field in doc.fields}
		fields_by_name = {field.fieldname: field for field in doc.fields}
	else:
		doc = frappe.new_doc("DocType")
		doc.name = doctype
		doc.module = MODULE
		doc.custom = 1
		doc.istable = 1
		doc.issingle = 0
		doc.permissions = []
		existing = set()
		fields_by_name = {}

	for label, fieldname, fieldtype, options in fields:
		if fieldname in existing:
			field = fields_by_name[fieldname]
			field.label = label
			field.fieldtype = fieldtype
			field.options = options
			continue

		field = {
			"label": label,
			"fieldname": fieldname,
			"fieldtype": fieldtype,
			"in_list_view": 1,
		}
		if options:
			field["options"] = options

		doc.append("fields", field)

	doc.save(ignore_permissions=True)


def backfill_existing_child_tables():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	from oa_purchase_request.oa_purchase_request.oa_purchase_request import normalize_child_tables

	for row in frappe.get_all(DOCTYPE, fields=["name"]):
		doc = frappe.get_doc(DOCTYPE, row.name)
		before_counts = (len(doc.get("items") or []), len(doc.get("processors") or []), len(doc.get("payments") or []))
		normalize_child_tables(doc)
		after_counts = (len(doc.get("items") or []), len(doc.get("processors") or []), len(doc.get("payments") or []))

		if after_counts != before_counts:
			doc.save(ignore_permissions=True)


def create_or_update_client_script():
	script = get_form_script()
	if not script:
		return

	if frappe.db.exists("Client Script", CLIENT_SCRIPT_NAME):
		doc = frappe.get_doc("Client Script", CLIENT_SCRIPT_NAME)
	else:
		doc = frappe.new_doc("Client Script")
		doc.name = CLIENT_SCRIPT_NAME

	doc.dt = DOCTYPE
	doc.enabled = 1
	doc.view = "Form"
	doc.script = script
	doc.save(ignore_permissions=True)


def create_or_update_list_client_script():
	script = get_list_script()
	if not script:
		return

	if frappe.db.exists("Client Script", LIST_CLIENT_SCRIPT_NAME):
		doc = frappe.get_doc("Client Script", LIST_CLIENT_SCRIPT_NAME)
	else:
		doc = frappe.new_doc("Client Script")
		doc.name = LIST_CLIENT_SCRIPT_NAME

	doc.dt = DOCTYPE
	doc.enabled = 1
	doc.view = "List"
	doc.script = script
	doc.save(ignore_permissions=True)


def get_form_script():
	app_path = frappe.get_app_path("oa_purchase_request")
	script_path = f"{app_path}/public/js/{scrub(DOCTYPE)}.js"

	try:
		with open(script_path) as file:
			return file.read()
	except OSError:
		return None


def get_list_script():
	app_path = frappe.get_app_path("oa_purchase_request")
	script_path = f"{app_path}/public/js/{scrub(DOCTYPE)}_list.js"

	try:
		with open(script_path) as file:
			return file.read()
	except OSError:
		return None
