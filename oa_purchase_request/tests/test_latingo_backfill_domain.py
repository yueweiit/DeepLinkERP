from datetime import date

import pytest

from oa_purchase_request.latingo_backfill_domain import (
	GENERIC_PURCHASE_PROCESS_CODE,
	LATINGO_PURCHASE_PROCESS_CODE,
	build_approval_plan,
	build_preview_fingerprint,
	iter_month_windows,
	source_from_instance,
	submission_blockers,
)


def source(**overrides):
	values = {
		"process_instance_id": "instance-1",
		"business_id": "202607010001",
		"process_code": LATINGO_PURCHASE_PROCESS_CODE,
		"status": "COMPLETED",
		"result": "agree",
		"is_deleted": False,
		"apply_date": "2026-07-01",
		"organization": "拉丁购",
		"currency": "RMB",
		"amount": 100,
		"payee": "原始收款人",
		"description": "普通采购",
		"delivery_date": "2026-06-30",
		"service_purchase_type": "",
		"pds_category": "",
		"detail_rows": [],
	}
	values.update(overrides)
	return values


def test_month_windows_are_inclusive_and_bounded():
	assert iter_month_windows("2026-07-01", "2026-09-24") == [
		(date(2026, 7, 1), date(2026, 7, 31)),
		(date(2026, 8, 1), date(2026, 8, 31)),
		(date(2026, 9, 1), date(2026, 9, 24)),
	]


@pytest.mark.parametrize(
	("candidate", "included", "reason"),
	[
		(source(organization="任意组织"), True, ""),
		(
			source(
				process_code=GENERIC_PURCHASE_PROCESS_CODE,
				organization="OBG 线上业务组Grupo de negocios en línea",
			),
			True,
			"",
		),
		(
			source(
				process_code=GENERIC_PURCHASE_PROCESS_CODE,
				organization="OBG1线上业务部Grupo de negocios en línea",
			),
			True,
			"",
		),
		(
			source(process_code=GENERIC_PURCHASE_PROCESS_CODE, organization="非电商组织"),
			False,
			"组织不属于 OBG/OBG1 电商",
		),
		(source(status="COMPLETED", result="refuse"), False, "审批已拒绝"),
		(source(status="TERMINATED", result="agree"), False, "审批已终止或撤销"),
		(source(is_deleted=True), False, "来源已删除"),
		(source(apply_date="2026-06-30"), False, "申请日期超出范围"),
	],
)
def test_scope_and_status_filtering(candidate, included, reason):
	plan = build_approval_plan(candidate, "2026-07-01", "2026-09-24")
	assert plan["included"] is included
	assert plan["exclusion_reason"] == reason


def test_running_approval_is_included_but_cannot_submit():
	plan = build_approval_plan(source(status="RUNNING", result=""), "2026-07-01", "2026-09-24")
	assert plan["included"] is True
	assert plan["review_flags"]["source_pending"] is True
	assert "来源审批尚未完成" in submission_blockers(plan)


@pytest.mark.parametrize(
	("candidate", "item_code"),
	[
		(source(pds_category="PDS拍摄", description="主播拍摄"), "LGO-SVC-PDS"),
		(source(service_purchase_type="物流及运输服务"), "LGO-SVC-LOGISTICS"),
		(source(description="其他无明细支出"), "LGO-SVC-OTHER"),
	],
)
def test_no_detail_expense_becomes_one_service_line(candidate, item_code):
	plan = build_approval_plan(candidate, "2026-07-01", "2026-09-24")
	assert plan["included"] is True
	assert plan["source_kind"] == "service"
	assert plan["items"] == [
		{
			"item_code": item_code,
			"item_group": "LGO 服务采购",
			"stock_uom": "项：servicio",
			"is_stock_item": 0,
			"qty": 1.0,
			"rate": 100.0,
			"amount": 100.0,
			"warehouse": "",
			"description": candidate["description"],
		}
	]


def test_physical_item_mapping_groups_uoms_and_zero_price_flag():
	candidate = source(
		currency="Peso",
		amount=0,
		detail_rows=[
			{"item_code": " PLAYO ", "item_name": "Playo", "qty": 32, "uom": "个", "amount": 0},
			{"item_code": "CW-001", "item_name": "宠物用品", "qty": 2, "uom": "只", "amount": 20},
			{"item_code": "0", "item_name": "透明安全眼镜", "qty": 1, "uom": "套", "amount": 10},
		],
	)
	plan = build_approval_plan(candidate, "2026-07-01", "2026-09-24")
	assert [row["item_code"] for row in plan["items"]] == [
		"PLAYO",
		"CW-001",
		"LGO-PPE-GLASSES-CLEAR",
	]
	assert [row["item_group"] for row in plan["items"]] == [
		"FL Suministros Auxiliares辅料",
		"CW 宠物用品",
		"GJ Herramienta工具",
	]
	assert [row["stock_uom"] for row in plan["items"]] == ["个：pieza", "个：pieza", "套：conjunto"]
	assert plan["currency"] == "MXN"
	assert plan["conversion_rate"] == 0.39
	assert plan["review_flags"]["exchange_rate_pending"] is True
	assert plan["review_flags"]["price_pending"] is True
	assert "存在零价格物料" in submission_blockers(plan)


def test_physical_item_rate_keeps_source_precision_needed_to_reconcile_amount():
	plan = build_approval_plan(
		source(
			amount=22119,
			detail_rows=[
				{"item_code": "CW000218", "item_name": "宠物六件套", "qty": 3000, "uom": "套", "amount": 22119}
			],
		),
		"2026-07-01",
		"2026-09-24",
	)
	assert plan["items"][0]["rate"] == 7.373
	assert plan["items"][0]["amount"] == 22119.0


def test_delivery_date_falls_back_to_order_date_and_mxn_requires_review():
	plan = build_approval_plan(source(currency="Peso"), "2026-07-01", "2026-09-24")
	assert plan["transaction_date"] == "2026-07-01"
	assert plan["schedule_date"] == "2026-07-01"
	assert "MXN 汇率尚未确认" in submission_blockers(plan)


def test_known_august_tax_difference_becomes_actual_tax_row():
	plan = build_approval_plan(
		source(
			business_id="202608241502000513674",
			apply_date="2026-08-24",
			amount=13332,
			detail_rows=[
				{"item_code": "A", "item_name": "A", "qty": 1, "uom": "个", "amount": 12000},
				{"item_code": "B", "item_name": "B", "qty": 1, "uom": "个", "amount": 1200},
			],
		),
		"2026-07-01",
		"2026-09-24",
	)
	assert plan["net_total"] == 13200.0
	assert plan["taxes"] == [
		{
			"charge_type": "Actual",
			"account_head": "22210101 - 应交税费－应交增值税－进项税额 - 拉丁购",
			"tax_amount": 132.0,
			"description": "来源审批明确的 1% 进项税",
		}
	]
	assert plan["grand_total"] == 13332.0


def test_unexplained_amount_difference_is_visible_warning():
	plan = build_approval_plan(
		source(
			amount=120,
			detail_rows=[{"item_code": "A", "item_name": "A", "qty": 1, "uom": "个", "amount": 100}],
		),
		"2026-07-01",
		"2026-09-24",
	)
	assert plan["amount_difference"] == 20.0
	assert plan["warnings"] == ["审批金额与明细/税费合计相差 20.00 CNY"]


def test_fingerprint_is_order_independent_and_detects_source_change():
	left = build_approval_plan(source(process_instance_id="A"), "2026-07-01", "2026-09-24")
	right = build_approval_plan(source(process_instance_id="B", business_id="2"), "2026-07-01", "2026-09-24")
	assert build_preview_fingerprint([left, right]) == build_preview_fingerprint([right, left])

	changed = dict(right)
	changed["header_amount"] = 101.0
	assert build_preview_fingerprint([left, right]) != build_preview_fingerprint([left, changed])


def test_stale_source_temp_supplier_and_invalid_later_status_block_submit():
	plan = build_approval_plan(source(), "2026-07-01", "2026-09-24")
	plan["review_flags"].update(
		{
			"source_stale": True,
			"temporary_supplier": True,
			"source_invalid": True,
		}
	)
	assert submission_blockers(plan) == [
		"来源审批后来已拒绝、撤销或删除",
		"来源指纹已过期",
		"临时供应商尚未替换",
	]


def test_source_instance_uses_existing_parser_outputs_and_bilingual_fields():
	instance = {
		"processInstanceId": "PI-1",
		"businessId": "OA-1",
		"processCode": GENERIC_PURCHASE_PROCESS_CODE,
		"status": "RUNNING",
		"result": "",
		"isDeleted": False,
	}
	fields = {
		"申请日期Fecha de solicitud": "2026-09-24",
		"申请部门/组织 Departamento Solicitante": "OBG1线上业务部Grupo de negocios en línea",
		"币种Moneda": "Peso",
		"金额importe": "39.00",
		"收款人beneficiario": "Proveedor Uno",
		"规格明细需求说明Descripcion de las necesidades de detalles": "购买宠物用品",
		"交付日期Fecha de entrega": "2026-09-30",
		"服务类采购 Adquisiciones de servicios": "",
		"PDS分类Clasificacion PDS": "",
	}
	rows = [{"物品编码": "CW01", "物品名称": "玩具", "数量": 2, "单位": "只", "金额": 39}]

	parsed = source_from_instance(instance, fields=fields, detail_rows=rows)

	assert parsed == {
		"process_instance_id": "PI-1",
		"business_id": "OA-1",
		"process_code": GENERIC_PURCHASE_PROCESS_CODE,
		"status": "RUNNING",
		"result": "",
		"is_deleted": False,
		"apply_date": "2026-09-24",
		"organization": "OBG1线上业务部Grupo de negocios en línea",
		"currency": "Peso",
		"amount": "39.00",
		"payee": "Proveedor Uno",
		"description": "购买宠物用品",
		"delivery_date": "2026-09-30",
		"service_purchase_type": "",
		"pds_category": "",
		"expense_category": "",
		"detail_rows": rows,
	}


def test_source_instance_honors_archived_delete_markers():
	parsed = source_from_instance(
		{"process_instance_id": "PI-2", "deleted_at": "2026-09-24T10:00:00Z"},
		fields={},
		detail_rows=[],
	)
	assert parsed["is_deleted"] is True


def test_source_instance_matches_accented_spanish_labels_from_archive():
	parsed = source_from_instance(
		{"processInstanceId": "PI-3"},
		fields={
			"Especificación": "规格 A",
			"PDS分类Clasificación PDS": "计时外包",
			"规格明细需求说明Descripción de las necesidades de detalles": "CREACION DE CONTENIDO",
		},
		detail_rows=[],
	)
	assert parsed["pds_category"] == "计时外包"
	assert parsed["description"] == "CREACION DE CONTENIDO"
