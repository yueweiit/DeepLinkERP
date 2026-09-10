"""Exact structured category contract shared with the upstream SQL fixture."""
import json
from pathlib import Path
import pytest
from overseas_costing.services.logistics_settlement.model import is_logistics_expense

CASES = json.loads((Path(__file__).parent / 'fixtures/purchase-category-cases.json').read_text())

@pytest.mark.parametrize('case', CASES, ids=lambda case: case['description'])
def test_purchase_category_contract(case):
    fields = {item['name']: item['value'] for item in case['components']}
    assert is_logistics_expense(fields) is case['expected']
