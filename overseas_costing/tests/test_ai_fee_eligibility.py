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
