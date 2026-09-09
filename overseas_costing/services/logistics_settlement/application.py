"""把已确认的结算来源转换成可审阅、可原子提交的成本变更。"""
from decimal import Decimal, ROUND_HALF_UP
import json
from .model import digest, identity

SCOPES = {'freight', 'customs', 'tax', 'mexico_inland'}


def row_scope(rule):
    if rule.get('covered_scopes'):
        return set(str(rule['covered_scopes']).split(','))
    code = str(rule.get('rule_code') or '').lower()
    if 'mexico_inland' in code:
        return {'mexico_inland'}
    if 'freight' in code or 'ocean' in code:
        return {'freight'}
    if 'customs' in code or 'clearance' in code:
        return {'customs'}
    if 'tax' in code:
        return {'tax'}
    return set()


def row_meta(item):
    try:
        return json.loads(item.get('extra_json') or '{}')
    except (ValueError, TypeError):
        return {}


def plan_application(expense, items, rules, *, binding_id, coverage=None, negative_confirmed=False):
    scopes = list(coverage or ([] if expense['coverage'] == 'unknown' else ['freight']))
    blocking = list(expense.get('fee_issues') or [])
    if not expense['approved'] or expense['invalid']:
        blocking.append('采购支出未通过或来源已失效')
    if not scopes or set(scopes) - SCOPES:
        blocking.append('需确认最终费用包含的运费、清关和税费范围')
    if expense['amount'] is None and not expense['fees']:
        blocking.append('缺少明确的最终金额')
    if expense['currency'] not in {'RMB', 'USD', 'MXN'}:
        blocking.append('缺少或不支持的费用币种')
    blocking.extend(issue for issue in expense['issues'] if ('费用' in issue or '冲抵' in issue) and not (negative_confirmed and '负数或冲抵' in issue))
    for rule in rules:
        if rule.get('is_enabled', 1) and rule.get('is_active', 1) and row_scope(rule) & set(scopes) and row_scope(rule) - set(scopes):
            blocking.append('已有费用覆盖范围交叉，不能部分停用整笔费用')
    fees = expense['fees'] or [{'line_key': 'total', 'label': '国际物流费用', 'amount': expense['amount'], 'currency': expense['currency']}]
    result_rules = []
    for fee in fees:
        if fee.get('currency') not in {'RMB', 'USD', 'MXN'} or fee.get('amount') is None:
            blocking.append('费用明细缺少金额或币种')
        if fee.get('currency') != expense['currency']:
            blocking.append('整单与明细币种不一致，需核对原币合计')
        result_rules.append({'rule_code': 'settlement_freight_' + digest(binding_id, fee['line_key'])[:20], 'expense_category': fee.get('label') or '国际物流费用', 'amount': fee.get('amount'), 'currency': fee.get('currency'), 'source_binding_id': binding_id, 'source_snapshot': expense.get('snapshot', expense['fingerprint']), 'covered_scopes': ','.join(scopes), 'is_final': 1, 'is_enabled': 1, 'is_active': 1})
    if result_rules and all(r['amount'] is not None for r in result_rules):
        round_fee_rules(result_rules)
    updates, additions, used, packing_review, goods_pending = [], [], set(), [], []
    if not expense['goods_complete']:
        goods_pending.append('采购货物清单不完整，保留原物料待核对')
    if expense['goods_complete']:
        for row in expense['goods']:
            matches = [item for item in items if row_meta(item).get('settlement_line_key') == row['line_key']]
            if not matches:
                matches = [item for item in items if (identity(item.get('material_code')) == identity(row.get('material_code')) if row.get('material_code') else identity(item.get('product_name')) == identity(row.get('product_name'))) and identity(item.get('spec_model')) == identity(row.get('spec_model')) and identity(item.get('unit')) == identity(row.get('unit'))]
            if len(matches) > 1 or (matches and matches[0]['name'] in used):
                goods_pending.append('物料行归属不唯一：' + str(row.get('material_code') or row.get('product_name')))
                continue
            values = {k: row.get(k) for k in ('material_code', 'product_name', 'spec_model', 'quantity', 'unit')}
            if matches:
                item = matches[0]; used.add(item['name'])
                if Decimal(str(item.get('quantity') or '0')) != Decimal(str(row['quantity'])):
                    packing_review.append(item['name'])
                updates.append({'name': item['name'], 'values': values, 'line_key': row['line_key']})
            else:
                additions.append({'values': values, 'line_key': row['line_key']})
        if goods_pending:
            updates, additions, used = [], [], {i['name'] for i in items}
    remove = [i['name'] for i in items if i['name'] not in used] if expense['goods_complete'] and not goods_pending else []
    if any(i.get('manual_override_flag') and i['name'] in remove for i in items):
        goods_pending.append('完整清单与人工补充物料不一致，需核对')
        updates, additions, remove = [], [], []
    return {'ready': not blocking, 'blocking': sorted(set(blocking)), 'rules': result_rules, 'disable_rules': [r['name'] for r in rules if row_scope(r) & set(scopes)], 'goods_updates': updates, 'goods_additions': additions, 'remove_items': remove, 'goods_pending': goods_pending, 'packing_review': packing_review, 'coverage': scopes}


def round_fee_rules(rules):
    quantum = Decimal('0.000001')
    for cur in sorted({r['currency'] for r in rules}):
        group = sorted((r for r in rules if r['currency'] == cur), key=lambda r:r['rule_code'])
        exact = [Decimal(r['amount']) for r in group]
        rounded = [value.quantize(quantum, rounding=ROUND_HALF_UP) for value in exact]
        target = sum(exact, Decimal(0)).quantize(quantum, rounding=ROUND_HALF_UP)
        # Adjust the most over/under-rounded rows; source identity breaks ties.
        # This avoids inventing a negative fee when a tiny positive row rounded to zero.
        units = int((target - sum(rounded, Decimal(0))) / quantum)
        sign = 1 if units >= 0 else -1
        order = sorted(range(len(group)), key=lambda i: (-sign * (exact[i]-rounded[i]), group[i]['rule_code']))
        for index in range(abs(units)):
            rounded[order[index % len(order)]] += sign * quantum
        for rule, original, value in zip(group, exact, rounded):
            rule.update(original_amount=str(original), amount=format(value.normalize(), 'f'), rounding_adjustment=str(value-original))
