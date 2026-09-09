from openpyxl import Workbook
import pytest
from overseas_costing.services import packing_attachment_service as service


def test_sheet_names_are_read_on_demand_and_fenced(monkeypatch, tmp_path):
    path = tmp_path / 'packing.xlsx'
    book = Workbook(); book.active.title = '货物明细'; book.create_sheet('费用'); book.save(path); book.close()
    context = {'root_kind': 'expense', 'available': True, 'fingerprint': 'current'}
    bundle = {'context': context}
    calls = []
    monkeypatch.setattr(service.effective_source, 'current_source_bundle', lambda *a: bundle)
    monkeypatch.setattr(service.packing_source_service, '_attachment_source_v2', lambda *a: {'file_url': str(path)})
    monkeypatch.setattr(service.effective_source, 'validate_packing_source', lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(service.effective_source, 'attachment_allowed', lambda *a, **kw: True)
    result = service.list_attachment_sheets('B', 'approval_attachment', 'ATT')
    assert result['sheets'] == ['货物明细', '费用'] and result['source_context'] == context
    assert calls == [('B', 'approval_attachment', 'ATT')]
    reads = iter([bundle, {'context': {**context, 'fingerprint': 'changed'}}])
    monkeypatch.setattr(service.effective_source, 'current_source_bundle', lambda *a: next(reads))
    with pytest.raises(ValueError, match='来源已变化'):
        service.list_attachment_sheets('B', 'approval_attachment', 'ATT')


def test_foreign_source_rejected_before_file_read(monkeypatch):
    monkeypatch.setattr(service.effective_source, 'current_source_bundle', lambda *a: None)
    monkeypatch.setattr(service.packing_source_service, '_attachment_source_v2', lambda *a: {'file_url': '/secret'})
    monkeypatch.setattr(service.effective_source, 'validate_packing_source', lambda *a, **kw: (_ for _ in ()).throw(ValueError('foreign')))
    monkeypatch.setattr(service.packing_source_service, 'resolve_packing_attachment_path', lambda *a: pytest.fail('foreign file read'))
    with pytest.raises(ValueError, match='foreign'):
        service.list_attachment_sheets('B', 'approval_attachment', 'FOREIGN')


def test_real_archived_xls_sheet_catalogue_and_cargo_parser(monkeypatch):
    from pathlib import Path
    from overseas_costing.services.packing_parse_service import parse_packing_grid
    path = Path(__file__).parent / 'fixtures' / 'current_expense_packing.xls'
    bundle = {'context': {'root_kind': 'expense', 'available': True, 'fingerprint': 'xls'}}
    source = {'file_url': str(path), 'file_name': path.name}
    monkeypatch.setattr(service.effective_source, 'current_source_bundle', lambda *a: bundle)
    monkeypatch.setattr(service.effective_source, 'validate_packing_source', lambda *a, **kw: None)
    monkeypatch.setattr(service.effective_source, 'attachment_allowed', lambda *a, **kw: True)
    monkeypatch.setattr(service.packing_source_service, '_attachment_source_v2', lambda *a: source)
    assert service.list_attachment_sheets('B', 'approval_attachment', 'XLS')['sheets'] == ['Expense packing']
    grid = service.packing_source_service._read_archived_xls_grid(path, 'Expense packing')
    rows = parse_packing_grid(grid)['material_rows']
    assert len(rows) == 1 and rows[0]['material_code'] == 'SKU-A'
    assert float(rows[0]['quantity']) == 6 and float(rows[0]['gross_weight_kg']) == 12
