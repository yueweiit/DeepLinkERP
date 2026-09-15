from overseas_costing.services import material_ai_fee_policy as policy


def proposal(key='international_express_fee'):
    return {'proposal_id':key,'proposal_type':'fee_update','default_selected':True,
            'payload':{'logical_fee_key':key,'amount':'100','currency':'RMB'}}


def test_adopted_freight_blocks_quotes_even_when_packing_still_uses_logistics():
    context={'root_kind':'logistics','freight':{'selected':True,'available':True,'claims':[{'amount':'0'}]}}
    result=policy.decorate([proposal()],[],context)[0]
    assert not result['can_apply'] and not result['default_selected']
    assert '实际运费' in result['blocked_reason']


def test_disabled_fee_stays_reference_and_other_fee_remains_selectable():
    old={'logical_fee_key':'international_express_fee','is_enabled':0,'is_active':0}
    result=policy.decorate([proposal(),proposal('customs_clearance_fee')],[old],{})
    assert result[0]['can_apply'] is False
    assert result[1]['can_apply'] is True


def test_revoked_last_claim_never_allows_ai_to_restore_estimate():
    result=policy.decorate([proposal()],[],{'freight':{'selected':True,'available':False,'claims':[]}})[0]
    assert result['can_apply'] is False


def test_selected_disabled_fee_is_rejected_at_application_boundary():
    import pytest
    with pytest.raises(ValueError,match='停用'):
        policy.assert_allowed([proposal()],[{'logical_fee_key':'international_express_fee','is_active':0}],{})


def test_total_components_and_other_alternatives_are_read_only_in_catalog():
    total = {**proposal('international_air_freight'), 'proposal_id': 'TOTAL',
             'selection_role': 'primary_total'}
    component = {**proposal('port_and_forwarder_charges'), 'proposal_id': 'COMPONENT',
                 'selection_role': 'component', 'parent_proposal_id': 'TOTAL'}
    alternative = {**proposal('express_surcharge'), 'proposal_id': 'ALTERNATIVE',
                   'selection_role': 'alternative'}

    result = {row['proposal_id']: row for row in policy.decorate(
        [total, component, alternative], [], {}
    )}

    assert result['TOTAL']['can_apply'] is True
    for proposal_id in ('COMPONENT', 'ALTERNATIVE'):
        assert result[proposal_id]['can_apply'] is False
        assert result[proposal_id]['default_selected'] is False
        assert '只读' in result[proposal_id]['blocked_reason']


def test_read_only_fee_roles_are_rejected_at_application_boundary():
    import pytest

    for role in ('component', 'alternative'):
        with pytest.raises(ValueError, match='只读'):
            policy.assert_allowed([{**proposal(), 'selection_role': role}], [], {})
