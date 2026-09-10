"""Server-owned eligibility for AI fee suggestions, independent of packing source."""
from copy import deepcopy

from .logistics_settlement.fee_policy import is_final, row_scopes
from .transport_fee_service import fee_is_active


def blocked_reason(payload, fees, context):
    scopes = row_scopes(payload)
    freight = (context or {}).get('freight') or {}
    if 'freight' in scopes and freight.get('selected'):
        return '已有实际运费，本报价不参与填充；金额调整请使用费用更正。' if freight.get('available') else '实际运费待核对，本报价不参与填充，不能恢复旧暂估。'
    key = str(payload.get('logical_fee_key') or '')
    for fee in fees or []:
        if is_final(fee) and (scopes & row_scopes(fee) or key == fee.get('logical_fee_key')):
            return '已有实际运费或最终费用，本报价不参与填充；请通过费用更正调整。'
        if key and key == fee.get('logical_fee_key') and not fee_is_active(fee):
            return '该费用已停用，仅供参考，不能通过 AI 填充恢复启用。'
    return ''


def decorate(proposals, fees, context):
    output = deepcopy(proposals)
    for proposal in output:
        if proposal.get('proposal_type') != 'fee_update':
            continue
        reason = blocked_reason(proposal.get('payload') or {}, fees, context)
        proposal.update(can_apply=not bool(reason), blocked_reason=reason)
        if reason:
            proposal['default_selected'] = False
    return output


def assert_allowed(proposals, fees, context):
    for proposal in proposals:
        if proposal.get('proposal_type') == 'fee_update':
            reason = blocked_reason(proposal.get('payload') or {}, fees, context)
            if reason:
                raise ValueError(reason)


def prompt_policy(fees, context, keys):
    return {key: {'can_apply': not bool(reason), 'reason': reason}
            for key in sorted(keys)
            for reason in [blocked_reason({'logical_fee_key': key}, fees, context)]}
