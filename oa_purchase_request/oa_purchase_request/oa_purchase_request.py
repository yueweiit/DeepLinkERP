import json
import mimetypes
import os
import re
import subprocess
from base64 import b64decode
from urllib.parse import quote, unquote, urlparse

import requests
import frappe
from frappe.utils.data import cint
from frappe.utils.file_manager import save_file
from frappe.utils import flt, getdate, nowdate


DEFAULT_PURCHASE_WAREHOUSE = "采购 - YC"
OA_PURCHASE_REQUEST_PROCESS_CODE = "PROC-BFDF6F09-4551-43B3-8C55-537AA74A241B"
OA_LATINGO_PURCHASE_REQUEST_PROCESS_CODE = "PROC-6E11B527-2F82-439C-817D-C868DE086C97"
OA_LOGISTICS_PROCESS_CODE = "PROC-RIYJTXWV-CN52YRK70C5499JG0TJ03-3GSSHZQJ-5"

ITEM_ALIASES = {
	"item_name": ["item_name", "物品名称", "物料名称", "名称", "name"],
	"item_code": ["item_code", "物品编码", "物料编码", "编码", "code"],
	"specification": ["specification", "规格", "规格型号", "description", "说明"],
	"qty": ["qty", "quantity", "数量", "cantidad"],
	"uom": ["uom", "unit", "单位", "unidad"],
	"amount": ["amount", "金额", "总金额", "importe", "monto"],
}

PROCESSOR_ALIASES = {
	"processor_name": ["processor_name", "加工商名字", "加工商", "Nombre del proveedor de servicios de procesam"],
	"processor_phone": ["processor_phone", "加工商电话", "电话", "Telefono del proveedor de servicios de proces"],
	"odt": ["odt", "ODT"],
	"sales_order_no": ["sales_order_no", "销售订单号码", "销售订单", "El numero de la orden de venta"],
	"processing_materials": ["processing_materials", "加工物料", "Materiales de Procesamiento"],
	"qty": ["processor_qty", "qty", "quantity", "数量", "Cantidad"],
	"unit_price": ["processor_unit_price", "unit_price", "单价", "Precio Unitario"],
	"amount": ["processor_total_amount", "amount", "总金额", "Monto Total"],
}

PAYMENT_ALIASES = {
	"payee": ["payee", "收款人", "beneficiario"],
	"amount": ["payment_amount", "amount", "金额", "importe"],
	"payment_terms": ["payment_terms", "付款条件", "Terminos de pago"],
	"currency": ["currency", "币种", "Moneda"],
	"payment_date": ["payment_date", "付款日期", "Fecha de pago"],
}

URL_KEYS = {
	"downloadUrl",
	"download_url",
	"fileUrl",
	"file_url",
	"imageUrl",
	"image_url",
	"mediaUrl",
	"media_url",
	"previewUrl",
	"preview_url",
	"url",
	"value",
}

FILE_ID_KEYS = {
	"fileId",
	"fileID",
	"file_id",
	"file_id_list",
	"fileIds",
	"file_ids",
}

FILENAME_KEYS = {
	"fileName",
	"file_name",
	"filename",
	"name",
	"title",
}

MEDIA_ID_KEYS = {
	"authMediaId",
	"auth_media_id",
	"mediaId",
	"mediaID",
	"media_id",
	"mediaIds",
	"media_ids",
}

ATTACHMENT_HINTS = (
	"attach",
	"file",
	"image",
	"media",
	"photo",
	"picture",
	"url",
	"附件",
	"图片",
	"凭证",
)


def normalize_child_tables(doc, method=None):
	fill_table_from_json(doc, "items", "items_json", ITEM_ALIASES)
	fill_table_from_json(doc, "processors", "processors_json", PROCESSOR_ALIASES)
	fill_table_from_json(doc, "payments", "payments_json", PAYMENT_ALIASES)

	if not doc.get("processors"):
		append_processor_from_flat_fields(doc)

	if not doc.get("payments"):
		append_payment_from_flat_fields(doc)

	remove_empty_child_rows(doc)


def sync_attachments(doc, method=None):
	if doc.get("backfill_imported"):
		return
	for attachment in extract_attachment_candidates(doc):
		try:
			attach_candidate(doc, attachment)
		except Exception:
			frappe.log_error(
				title=f"OA Purchase Request attachment sync failed: {doc.name}",
				message=frappe.get_traceback(),
			)


def sync_existing_attachments():
	for row in frappe.get_all("OA Purchase Request", fields=["name"]):
		doc = frappe.get_doc("OA Purchase Request", row.name)
		sync_attachments(doc)
	frappe.db.commit()


def get_attachment_sync_status(docname):
	doc = frappe.get_doc("OA Purchase Request", docname)
	return {
		"files": frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": doc.doctype,
				"attached_to_name": doc.name,
			},
			fields=["name", "file_name", "file_url", "is_private"],
		),
		"candidates": extract_attachment_candidates(doc),
		"has_attachments_json": bool(doc.get("attachments_json")),
		"has_raw_payload": bool(doc.get("raw_payload")),
	}


def inspect_attachment_payload(docname):
	doc = frappe.get_doc("OA Purchase Request", docname)
	rows = []
	for fieldname in ("attachments_json", "raw_payload"):
		collect_attachment_debug_rows(parse_json_value(doc.get(fieldname)), rows, fieldname)
	return rows[:200]


@frappe.whitelist()
def get_oa_purchase_request_dingtalk_url(docname):
	doc = frappe.get_doc("OA Purchase Request", docname)
	doc.check_permission("read")

	process_instance_id = (doc.get("process_instance_id") or "").strip()
	if not process_instance_id:
		frappe.throw("缺少 OA Purchase Request 的 process_instance_id")

	process_code = (doc.get("process_code") or "").strip()
	if process_code and process_code not in {
		OA_PURCHASE_REQUEST_PROCESS_CODE,
		OA_LATINGO_PURCHASE_REQUEST_PROCESS_CODE,
	}:
		frappe.throw(f"OA Purchase Request 模板码不匹配：{process_code}")

	return {"dingtalk_url": get_dingtalk_approval_url(process_instance_id)}


@frappe.whitelist()
def get_oa_logistics_dingtalk_url(oa_logistics_code):
	oa_logistics_code = (oa_logistics_code or "").strip()
	if not oa_logistics_code:
		frappe.throw("缺少 OA Logistics Code")

	rows = find_oa_logistics_approval_rows(oa_logistics_code)
	if not rows:
		frappe.throw(f"未找到 OA Logistics Code 对应的国际物流审批：{oa_logistics_code}")

	process_instance_id = rows[0].process_instance_id
	if not process_instance_id:
		frappe.throw(f"国际物流审批缺少 process_instance_id：{oa_logistics_code}")

	return {"dingtalk_url": get_dingtalk_approval_url(process_instance_id)}


def find_oa_logistics_approval_rows(oa_logistics_code):
	return find_oa_logistics_approval_rows_from_postgres(oa_logistics_code)


def find_oa_logistics_approval_rows_from_postgres(oa_logistics_code):
	host = frappe.conf.get("oa_mapping_pg_host")
	user = frappe.conf.get("oa_mapping_pg_user")
	if not host or not user:
		return []

	database = frappe.conf.get("oa_mapping_pg_database") or "Depart_Employ"
	port = str(frappe.conf.get("oa_mapping_pg_port") or 5432)
	schema = frappe.conf.get("oa_mapping_pg_schema") or "public"
	table = frappe.conf.get("oa_mapping_pg_table") or "oa_mapping"
	password = frappe.conf.get("oa_mapping_pg_password")
	query = f"""
		select oa_code, instance_id
		from {quote_pg_identifier(schema)}.{quote_pg_identifier(table)}
		where process_code = '{escape_pg_literal(OA_LOGISTICS_PROCESS_CODE)}'
			and oa_code = '{escape_pg_literal(oa_logistics_code)}'
		order by update_time desc
		limit 1
	"""
	env = os.environ.copy()
	if password:
		env["PGPASSWORD"] = password

	try:
		result = subprocess.run(
			[
				"psql",
				"--tuples-only",
				"--no-align",
				"--field-separator",
				"\t",
				"--host",
				host,
				"--port",
				port,
				"--username",
				user,
				"--dbname",
				database,
				"--command",
				query,
			],
			env=env,
			check=False,
			capture_output=True,
			text=True,
			timeout=10,
		)
	except Exception:
		return []

	if result.returncode != 0:
		frappe.log_error(
			title="OA logistics PostgreSQL lookup failed",
			message=result.stderr or result.stdout,
		)
		return []

	line = (result.stdout or "").strip().splitlines()
	if not line:
		return []

	oa_code, instance_id = (line[0].split("\t", 1) + [""])[:2]
	if not instance_id:
		return []
	return [frappe._dict({"name": oa_code, "process_instance_id": instance_id})]


def quote_pg_identifier(value):
	return '"' + str(value).replace('"', '""') + '"'


def escape_pg_literal(value):
	return str(value).replace("'", "''")


def get_dingtalk_approval_url(process_instance_id):
	safe_mobile_url = (
		"https://aflow.dingtalk.com/dingtalk/mobile/homepage.htm"
		f"?showmenu=false&dd_progress=false#/approval?procInstId={process_instance_id}"
	)
	return (
		"dingtalk://dingtalkclient/page/link?"
		f"url={quote(safe_mobile_url, safe='')}&pc_slide=true"
	)


@frappe.whitelist()
def create_purchase_order(docname, supplier_name, oa_logistics_item_code=None, oa_logistics_amount=None):
	doc = frappe.get_doc("OA Purchase Request", docname)
	doc.check_permission("read")

	supplier_name = (supplier_name or "").strip()
	oa_logistics_item_code = (oa_logistics_item_code or "").strip()
	oa_logistics_amount = "" if oa_logistics_amount in (None, "") else oa_logistics_amount
	if not supplier_name:
		frappe.throw("请填写供应商")

	if doc.get("sync_status") == "Closed":
		frappe.throw("已关闭的 OA Purchase Request 不能生成采购订单")

	if doc.get("purchase_order") and frappe.db.exists("Purchase Order", doc.purchase_order):
		frappe.throw(f"已生成采购订单：{doc.purchase_order}")

	if not frappe.db.exists("Warehouse", DEFAULT_PURCHASE_WAREHOUSE):
		frappe.throw(f"默认仓库不存在：{DEFAULT_PURCHASE_WAREHOUSE}")

	if not doc.get("items"):
		normalize_child_tables(doc)

	if not doc.get("items"):
		frappe.throw("没有可生成采购订单的需求明细")

	supplier = get_or_create_supplier(supplier_name)
	company = frappe.defaults.get_user_default("Company") or frappe.db.get_default("company")
	if not company:
		frappe.throw("未找到默认公司，无法生成采购订单")

	schedule_date = get_purchase_order_schedule_date(doc)
	purchase_order = frappe.new_doc("Purchase Order")
	purchase_order.supplier = supplier
	purchase_order.company = company
	purchase_order.transaction_date = nowdate()
	purchase_order.schedule_date = schedule_date
	purchase_order.set_warehouse = DEFAULT_PURCHASE_WAREHOUSE
	purchase_order.custom_oa_purchase_expense = doc.name
	purchase_order.custom_oa_logistics_code = oa_logistics_item_code
	purchase_order.custom_logistics_cost = oa_logistics_amount

	for row in doc.get("items"):
		if not has_meaningful_item_row(row):
			continue

		item_code = get_existing_item(row)
		qty = flt(row.get("qty")) or 1
		amount = flt(row.get("amount"))
		rate = amount / qty if amount else 0
		description = row.get("specification") or row.get("item_name") or item_code
		uom = get_item_uom(item_code, row.get("uom"))

		purchase_order.append(
			"items",
			{
				"item_code": item_code,
				"item_name": row.get("item_name") or item_code,
				"description": description,
				"qty": qty,
				"uom": uom,
				"schedule_date": schedule_date,
				"warehouse": DEFAULT_PURCHASE_WAREHOUSE,
				"rate": rate,
			},
		)

	if not purchase_order.get("items"):
		frappe.throw("没有可生成采购订单的有效需求明细")

	purchase_order.insert(ignore_permissions=True)

	frappe.db.set_value(
		"OA Purchase Request",
		doc.name,
		{
			"purchase_order": purchase_order.name,
			"oa_logistics_code": oa_logistics_item_code,
			"sync_status": "Purchase Order Created",
		},
	)
	frappe.db.commit()

	return {"purchase_order": purchase_order.name}


@frappe.whitelist()
def close_oa_purchase_requests(names):
	if isinstance(names, str):
		names = json.loads(names)

	if not names:
		return {"closed_count": 0, "names": []}

	closed_names = []
	for name in names:
		doc = frappe.get_doc("OA Purchase Request", name)
		doc.check_permission("write")
		frappe.db.set_value("OA Purchase Request", doc.name, "sync_status", "Closed", update_modified=False)
		closed_names.append(doc.name)

	frappe.db.commit()
	return {"closed_count": len(closed_names), "names": closed_names}


def get_or_create_supplier(supplier_name):
	existing_supplier = frappe.db.exists("Supplier", supplier_name) or frappe.db.get_value(
		"Supplier",
		{"supplier_name": supplier_name},
		"name",
	)
	if existing_supplier:
		return existing_supplier

	supplier = frappe.new_doc("Supplier")
	supplier.supplier_name = supplier_name
	supplier.supplier_type = "Company"
	supplier_group = get_default_supplier_group()
	if supplier_group:
		supplier.supplier_group = supplier_group
	supplier.insert(ignore_permissions=True)
	return supplier.name


def get_default_supplier_group():
	return frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")


def get_purchase_order_schedule_date(doc):
	date_value = doc.get("delivery_date") or doc.get("apply_date") or nowdate()
	if getdate(date_value) < getdate(nowdate()):
		return nowdate()
	return date_value


def has_meaningful_item_row(row):
	return row.get("item_code") or row.get("item_name")


def auto_create_purchase_receipt(doc, method=None):
	if doc.docstatus != 1 or doc.get("status") in ("Closed", "On Hold"):
		return

	if has_purchase_receipt(doc.name) or not has_receivable_items(doc):
		return

	try:
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		purchase_receipt = make_purchase_receipt(doc.name)
		if not purchase_receipt.get("items"):
			return

		purchase_receipt.insert(ignore_permissions=True)
		frappe.msgprint(f"已自动生成采购入库单 {purchase_receipt.name}")
	except Exception:
		frappe.log_error(
			title=f"Auto create Purchase Receipt failed: {doc.name}",
			message=frappe.get_traceback(),
		)
		frappe.throw("自动生成采购入库单失败，请检查采购订单明细后手动创建采购入库单")


def has_purchase_receipt(purchase_order):
	return bool(
		frappe.db.sql(
			"""
			select pri.parent
			from `tabPurchase Receipt Item` pri
			inner join `tabPurchase Receipt` pr on pr.name = pri.parent
			where pri.purchase_order = %s
				and pr.docstatus < 2
			limit 1
			""",
			(purchase_order,),
		)
	)


def has_receivable_items(doc):
	has_unit_price_items = cint(doc.get("has_unit_price_items"))
	for row in doc.get("items"):
		if row.get("delivered_by_supplier"):
			continue
		if has_unit_price_items and flt(row.get("qty")) == 0:
			return True
		if abs(flt(row.get("received_qty"))) < abs(flt(row.get("qty"))):
			return True
	return False


def get_existing_item(row):
	item_code = (row.get("item_code") or "").strip()
	if not item_code:
		frappe.throw(f"第 {row.idx} 行缺少物料编码，不能创建采购订单")

	if frappe.db.exists("Item", item_code):
		return item_code

	frappe.throw(f"第 {row.idx} 行物料编码不存在：{item_code}，不能创建采购订单")


def get_item_uom(item_code, requested_uom=None):
	return frappe.db.get_value("Item", item_code, "stock_uom") or get_or_create_uom(requested_uom)


def get_or_create_uom(uom):
	uom = (uom or "").strip() or "Nos"
	if frappe.db.exists("UOM", uom):
		return uom

	doc = frappe.new_doc("UOM")
	doc.uom_name = uom
	doc.enabled = 1
	doc.insert(ignore_permissions=True)
	return doc.name


def get_default_item_group():
	item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	if not item_group:
		frappe.throw("未找到可用的物料组，无法自动创建物料")
	return item_group


def fill_table_from_json(doc, table_field, json_field, aliases):
	if doc.get(table_field) or not doc.get(json_field):
		return

	for row in parse_rows(doc.get(json_field)):
		mapped = map_row(row, aliases)
		if has_value(mapped):
			doc.append(table_field, mapped)


def parse_rows(value):
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except Exception:
			return []

	if isinstance(value, dict):
		for key in ("data", "items", "rows", "list", "value"):
			if isinstance(value.get(key), list):
				return value.get(key)
		return [value]

	if isinstance(value, list):
		return value

	return []


def parse_json_value(value):
	if not value:
		return None

	if isinstance(value, str):
		try:
			return json.loads(value)
		except Exception:
			return None

	return value


def extract_attachment_candidates(doc):
	candidates = []
	for source in (doc.get("attachments_json"), doc.get("raw_payload")):
		collect_attachment_candidates(parse_json_value(source), candidates)
		collect_attachment_candidates_from_text(source, candidates)
	return candidates


def collect_attachment_candidates_from_text(value, candidates):
	if not value:
		return

	text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
	for url in re.findall(r"https?://[^\s\"'<>\\]+", text):
		if looks_like_attachment_url(url):
			candidates.append({"url": url, "filename": filename_from_url(url)})

	for file_id in re.findall(r'"fileId"\s*:\s*"([^"]+)"', text):
		candidates.append({"file_id": file_id, "filename": None})

	for auth_media_id in re.findall(r'"authMediaId"\s*:\s*"([^"]+)"', text):
		candidates.append({"media_id": auth_media_id, "filename": None})


def looks_like_attachment_url(url):
	path = urlparse(url).path.lower()
	return path.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf")) or "static.dingtalk.com/media" in url


def collect_attachment_candidates(value, candidates):
	if isinstance(value, str):
		parsed = parse_json_value(value)
		if parsed is not None:
			collect_attachment_candidates(parsed, candidates)
		elif value.startswith(("http://", "https://", "data:")):
			candidates.append({"url": value, "filename": None})
		return

	if isinstance(value, list):
		for item in value:
			collect_attachment_candidates(item, candidates)
		return

	if not isinstance(value, dict):
		return

	url = first_value(value, URL_KEYS)
	data = value.get("content") or value.get("data") or value.get("base64")
	file_id = first_value(value, FILE_ID_KEYS)
	filename = first_value(value, FILENAME_KEYS)
	media_id = first_value(value, MEDIA_ID_KEYS)

	if isinstance(url, str) and url.startswith(("http://", "https://", "data:")):
		candidates.append({"url": url, "filename": filename})
	elif isinstance(data, str) and looks_like_base64(data):
		candidates.append({"data": data, "filename": filename})
	elif file_id:
		for item in ensure_list(file_id):
			candidates.append({"file_id": item, "filename": filename})
	elif media_id:
		for item in ensure_list(media_id):
			candidates.append({"media_id": item, "filename": filename})

	for item in value.values():
		if isinstance(item, (dict, list)):
			collect_attachment_candidates(item, candidates)


def collect_attachment_debug_rows(value, rows, path):
	if isinstance(value, str):
		parsed = parse_json_value(value)
		if parsed is not None:
			collect_attachment_debug_rows(parsed, rows, path)
		elif looks_like_attachment_value(path, value):
			rows.append({"path": path, "value": preview_value(value)})
		return

	if isinstance(value, list):
		for index, item in enumerate(value):
			collect_attachment_debug_rows(item, rows, f"{path}[{index}]")
		return

	if isinstance(value, dict):
		for key, item in value.items():
			child_path = f"{path}.{key}"
			if looks_like_attachment_value(key, item):
				rows.append({"path": child_path, "value": preview_value(item)})
			collect_attachment_debug_rows(item, rows, child_path)


def looks_like_attachment_value(key, value):
	key = str(key).lower()
	if any(hint in key for hint in ATTACHMENT_HINTS):
		return True

	return isinstance(value, str) and value.startswith(("http://", "https://", "data:"))


def preview_value(value):
	if isinstance(value, (dict, list)):
		value = json.dumps(value, ensure_ascii=False)
	else:
		value = str(value)

	return value[:500]


def ensure_list(value):
	if isinstance(value, list):
		return value

	if isinstance(value, str):
		parsed = parse_json_value(value)
		if isinstance(parsed, list):
			return parsed

	return [value]


def attach_candidate(doc, attachment):
	source_url = attachment.get("url") or attachment.get("file_id") or attachment.get("media_id")
	if source_url and file_exists_by_source_url(doc, source_url):
		return

	if attachment.get("url", "").startswith("data:"):
		content, filename = content_from_data_uri(attachment["url"], attachment.get("filename"))
	elif attachment.get("url"):
		content, filename = content_from_url(attachment["url"], attachment.get("filename"))
	elif attachment.get("data"):
		content = b64decode(strip_base64_header(attachment["data"]))
		filename = attachment.get("filename") or "dingtalk_attachment"
	elif attachment.get("file_id"):
		content, filename = content_from_dingtalk_file_id(
			doc,
			attachment["file_id"],
			attachment.get("filename"),
		)
	elif attachment.get("media_id"):
		content, filename = content_from_dingtalk_media_id(attachment["media_id"], attachment.get("filename"))
	else:
		return

	filename = normalize_filename(filename, content)
	if file_exists(doc, filename):
		return

	file_doc = save_file(filename, content, doc.doctype, doc.name, is_private=0)
	if source_url and has_file_source_url_field():
		file_doc.source_url = source_url
		file_doc.save(ignore_permissions=True)


def content_from_url(url, filename=None):
	response = requests.get(url, timeout=20)
	response.raise_for_status()

	return response.content, filename or filename_from_url(url) or filename_from_content_type(response.headers.get("content-type"))


def content_from_dingtalk_file_id(doc, file_id, filename=None):
	access_token = get_dingtalk_access_token()
	process_instance_id = doc.get("process_instance_id")
	if not process_instance_id:
		frappe.throw("Missing process_instance_id for DingTalk approval attachment download")

	response = requests.post(
		"https://oapi.dingtalk.com/topapi/processinstance/file/url/get",
		params={"access_token": access_token},
		json={
			"process_instance_id": process_instance_id,
			"file_id": file_id,
		},
		timeout=20,
	)
	response.raise_for_status()
	payload = response.json()
	assert_dingtalk_success(payload)

	result = payload.get("result") or {}
	download_url = (
		result.get("download_uri")
		or result.get("downloadUrl")
		or result.get("download_url")
		or result.get("url")
	)
	if not download_url:
		frappe.throw(f"DingTalk did not return a download URL for file_id {file_id}")

	return content_from_url(download_url, filename or result.get("file_name") or result.get("fileName"))


def content_from_dingtalk_media_id(media_id, filename=None):
	access_token = get_dingtalk_access_token()

	for method, url, kwargs in (
		(
			"get",
			"https://oapi.dingtalk.com/media/get",
			{"params": {"access_token": access_token, "media_id": media_id}},
		),
		(
			"post",
			"https://oapi.dingtalk.com/media/downloadFile",
			{"params": {"access_token": access_token}, "json": {"media_id": media_id}},
		),
	):
		response = getattr(requests, method)(url, timeout=20, **kwargs)
		if response.headers.get("content-type", "").startswith("application/json"):
			payload = response.json()
			if payload.get("errcode"):
				continue

		response.raise_for_status()
		return (
			response.content,
			filename or filename_from_content_type(response.headers.get("content-type")),
		)

	frappe.throw(f"Unable to download DingTalk media_id {media_id}")


def get_dingtalk_access_token():
	cached_token = frappe.cache().get_value("oa_purchase_request_dingtalk_access_token")
	if cached_token:
		return cached_token

	app_key = frappe.conf.get("dingtalk_app_key")
	app_secret = frappe.conf.get("dingtalk_app_secret")
	if not app_key or not app_secret:
		frappe.throw("Missing dingtalk_app_key or dingtalk_app_secret in site_config")

	response = requests.get(
		"https://oapi.dingtalk.com/gettoken",
		params={"appkey": app_key, "appsecret": app_secret},
		timeout=20,
	)
	response.raise_for_status()
	payload = response.json()
	assert_dingtalk_success(payload)

	access_token = payload.get("access_token")
	if not access_token:
		frappe.throw("DingTalk did not return access_token")

	frappe.cache().set_value("oa_purchase_request_dingtalk_access_token", access_token, expires_in_sec=7000)
	return access_token


def assert_dingtalk_success(payload):
	if payload.get("errcode") not in (None, 0):
		frappe.throw(f"DingTalk API error {payload.get('errcode')}: {payload.get('errmsg')}")


def content_from_data_uri(value, filename=None):
	header, data = value.split(",", 1)
	extension = "bin"
	if ";" in header:
		content_type = header.split(":", 1)[-1].split(";", 1)[0]
		extension = mimetypes.guess_extension(content_type).lstrip(".") or extension

	return b64decode(data), filename or f"dingtalk_attachment.{extension}"


def strip_base64_header(value):
	if value.startswith("data:") and "," in value:
		return value.split(",", 1)[1]
	return value


def looks_like_base64(value):
	return value.startswith("data:") or len(value) > 80


def filename_from_url(url):
	path = unquote(urlparse(url).path or "")
	filename = path.rsplit("/", 1)[-1]
	return filename or None


def filename_from_content_type(content_type):
	if not content_type:
		return "dingtalk_attachment"

	extension = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
	return f"dingtalk_attachment{extension or ''}"


def normalize_filename(filename, content):
	filename = (filename or "dingtalk_attachment").strip()
	if "." not in filename:
		kind = mimetypes.guess_extension("image/png") if content.startswith(b"\x89PNG") else None
		filename = f"{filename}{kind or ''}"
	return filename


def file_exists(doc, filename):
	return cint(
		frappe.db.count(
			"File",
			{
				"attached_to_doctype": doc.doctype,
				"attached_to_name": doc.name,
				"file_name": filename,
			},
		)
	)


def file_exists_by_source_url(doc, source_url):
	if not has_file_source_url_field():
		return False

	return cint(
		frappe.db.count(
			"File",
			{
				"attached_to_doctype": doc.doctype,
				"attached_to_name": doc.name,
				"source_url": source_url,
			},
		)
	)


def has_file_source_url_field():
	return frappe.db.has_column("File", "source_url")


def make_existing_attachments_public():
	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "OA Purchase Request",
			"is_private": 1,
		},
		fields=["name"],
	)

	for row in files:
		file_doc = frappe.get_doc("File", row.name)
		file_doc.is_private = 0
		file_doc.save(ignore_permissions=True)

	frappe.db.commit()


def deduplicate_existing_attachments():
	for row in frappe.get_all("OA Purchase Request", fields=["name"]):
		files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "OA Purchase Request",
				"attached_to_name": row.name,
			},
			fields=["name", "file_name", "file_url"],
			order_by="creation asc",
		)
		seen = set()
		for file_row in files:
			key = (file_row.file_name, file_row.file_url)
			if key in seen:
				frappe.delete_doc("File", file_row.name, ignore_permissions=True)
			else:
				seen.add(key)

	frappe.db.commit()


def map_row(row, aliases):
	if not isinstance(row, dict):
		return {}

	mapped = {}
	for target_field, source_keys in aliases.items():
		value = first_value(row, source_keys)
		if value in (None, ""):
			continue

		if target_field in {"amount", "qty", "unit_price"}:
			value = flt(value)

		mapped[target_field] = value

	return mapped


def first_value(row, keys):
	for key in keys:
		if key in row and row.get(key) not in (None, ""):
			return row.get(key)
	return None


def has_value(row):
	return any(value not in (None, "") for value in row.values())


def append_processor_from_flat_fields(doc):
	row = {
		"processor_name": doc.get("processor_name"),
		"processor_phone": doc.get("processor_phone"),
		"odt": doc.get("odt"),
		"sales_order_no": doc.get("sales_order_no"),
		"processing_materials": doc.get("processing_materials"),
	}
	add_number_if_present(row, "qty", doc.get("processor_qty"))
	add_number_if_present(row, "unit_price", doc.get("processor_unit_price"))
	add_number_if_present(row, "amount", doc.get("processor_total_amount"))

	if has_meaningful_row_value(row):
		doc.append("processors", row)


def append_payment_from_flat_fields(doc):
	row = {
		"payee": doc.get("payee"),
		"payment_terms": doc.get("payment_terms"),
		"currency": doc.get("currency"),
		"payment_date": doc.get("payment_date"),
	}
	add_number_if_present(row, "amount", doc.get("payment_amount"))

	if has_meaningful_row_value(row):
		doc.append("payments", row)


def add_number_if_present(row, fieldname, value):
	if value not in (None, ""):
		row[fieldname] = flt(value)


def has_meaningful_row_value(row):
	for value in row.values():
		if value in (None, ""):
			continue
		if isinstance(value, int | float) and flt(value) == 0:
			continue
		return True

	return False


def remove_empty_child_rows(doc):
	for table_field in ("items", "processors", "payments"):
		doc.set(table_field, [row for row in doc.get(table_field) if child_row_has_value(row)])


def child_row_has_value(row):
	ignored_fields = {
		"creation",
		"docstatus",
		"doctype",
		"idx",
		"modified",
		"modified_by",
		"name",
		"owner",
		"parent",
		"parentfield",
		"parenttype",
	}

	for fieldname, value in row.as_dict().items():
		if fieldname in ignored_fields or value in (None, ""):
			continue
		if isinstance(value, int | float) and flt(value) == 0:
			continue
		return True

	return False


def cleanup_existing_child_tables():
	for row in frappe.get_all("OA Purchase Request", fields=["name"]):
		doc = frappe.get_doc("OA Purchase Request", row.name)
		before_counts = (len(doc.get("items") or []), len(doc.get("processors") or []), len(doc.get("payments") or []))
		remove_empty_child_rows(doc)
		after_counts = (len(doc.get("items") or []), len(doc.get("processors") or []), len(doc.get("payments") or []))

		if after_counts != before_counts:
			doc.save(ignore_permissions=True)

	frappe.db.commit()
