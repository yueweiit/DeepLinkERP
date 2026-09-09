"""Minimal, non-identifying workbook regression from the verified 6262 shipment."""
from copy import deepcopy
from decimal import Decimal

import pytest
from openpyxl import Workbook

from overseas_costing.services import material_ai_fill_service as service, packing_source_service, attachment_parse_service
from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
from overseas_costing.services.packing_parse_service import parse_packing_grid
from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
from overseas_costing.tests.test_logistics_autofill import approval, existing_items, GOODS
from overseas_costing.tests.test_material_ai_fill_service import _LifecycleRepository
from overseas_costing.utils.excel_workbook import read_packing_grid


@pytest.mark.parametrize('already_eight', [False, True])
def test_real_minimal_workbook_worker_previews_values_projects_without_writes(tmp_path, monkeypatch, already_eight):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '装箱'
    sheet.append(['物料编码','数量','单位','单价 unit price','总价（RMB)','项目归属','总毛重','总体积'])
    for index, (code, qty) in enumerate(GOODS):
        sheet.append([code, qty, '个', .604 if index == 0 else .13 if index == 6 else 4.4 if index == 7 else None,
            60400 if index == 0 else 2860 if index == 6 else 10560 if index == 7 else None,
            '超队1.0项目' if index < 6 else '亮甲2.0项目' if index == 6 else 'TK宠物用品项目',
            [388,9.7,0,32,150,89,77,130][index], [.4002,.00864,0,.032016,.0828,.04071,.16687,.507375][index]])
    path = tmp_path / 'packing.xlsx'
    workbook.save(path)
    items = existing_items()
    for row in items:
        row.update(unit_price=.13 if row['material_code'] == 'FL003377' else .151, unit='个', purchase_currency='RMB')
    if already_eight:
        items = build_logistics_reconciliation(items, approval())['payload']['rows']
        for row in items[1:3]:
            row.update(gross_weight_kg=4.85, volume_m3=.00432, manual_override_flag=1)
    before = deepcopy(items)
    repo = _LifecycleRepository(status='QUEUED')
    repo.sources = [approval(), {'source_kind':'manual_attachment','source_id':'X','source_hash':'h1',
        'file_name':'packing.xlsx','source_label':'packing.xlsx','sheet_name':'装箱','dedicated_packing':True}]
    context = {'batch':'B1','version':'V1','transport_mode':'SEA','fx_rates':{'RMB':'1'}}
    repo.get_context = lambda *args: deepcopy(context)
    repo.get_items = lambda *args: deepcopy(items)
    repo.get_fees = lambda *args: [{'name':'F','logical_fee_key':'international_sea_freight','amount':2004,
        'currency':'RMB','amount_status':'ACTUAL','scope_type':'ALL_ITEMS','allocation_basis':'volume'}]
    manifest = prepare_source_manifest(repo.sources)
    repo.run.update(proposal_version=1, source_manifest_json=manifest,
        input_fingerprint=service._source_review_fingerprint('B1','V1',items,manifest,'',context=context))
    monkeypatch.setattr(service,'frappe',None)
    monkeypatch.setattr(service,'_ensure_local_attachment',lambda source: {**source,'file_url':'private.xlsx'})
    monkeypatch.setattr(attachment_parse_service,'_resolve_source_file_path',lambda **kw: path)
    monkeypatch.setattr(packing_source_service,'resolve_trusted_packing_source',lambda **kw: {
        'preview':parse_packing_grid(read_packing_grid(path,sheet_name=kw['sheet_name'],require_exact_sheet=True))})
    monkeypatch.setattr(service,'_call_source_review_ai',lambda *a,**kw: {'ok':False,'proposals':[],'warning':'AI unavailable'})
    result = service.execute_material_ai_fill('RUN-1',repository=repo)
    assert result['status'] == 'READY', repo.run.get('error_message')
    preview = repo.run['draft_json']['autofill_preview']
    assert [Decimal(row['shipment_value_rmb']) for row in preview['items']] == list(map(Decimal,
        ['14496','604','604','14496','15100','15100','2860','10560']))
    assert preview['cost_summary']['total_cost_rmb'] == '81576.20'
    assert [row['allocated_fees_rmb'] for row in preview['project_summary']] == ['5922.77','682.00','1151.43']
    assert len(preview['fees']) == 1
    assert items == before and repo.applied == []
    if already_eight:
        assert [row['stable_line_key'] for row in preview['items']] == [row['stable_line_key'] for row in items]
        assert [(row['gross_weight_kg'],row['volume_m3']) for row in preview['items'][1:3]] == [(4.85,.00432)] * 2
