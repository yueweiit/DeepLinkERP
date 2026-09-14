import pytest

from overseas_costing.services.material_bulk_edit_service import bulk_exclude_materials


class Repo:
    def __init__(self):
        self.state = {
            'batch': 'B1',
            'batch_modified': 'BM1',
            'version': 'V1',
            'editable': True,
            'items': [
                {'name': 'I1', 'stable_line_key': 'L1', 'row_no': 1, 'is_excluded': 0},
                {'name': 'I2', 'stable_line_key': 'L2', 'row_no': 2, 'is_excluded': 0},
                {'name': 'I3', 'stable_line_key': 'L3', 'row_no': 3, 'is_excluded': 0},
            ],
            'groups': [{'group_id': 'G1', 'member_keys': ['L1', 'L2'], 'status': 'confirmed'}],
        }
        self.saved = []

    def load(self, batch, version, *, lock=False):
        return {
            **self.state,
            'items': [dict(item) for item in self.state['items']],
            'groups': [dict(group) for group in self.state['groups']],
        }

    def assert_write(self, batch, edit_token, expected_modified):
        if expected_modified != self.state['batch_modified']:
            raise ValueError('批次已变化')

    def save_exclusions(self, state, items, stable_line_keys, reason, actor):
        self.saved.append(list(stable_line_keys))
        for item in self.state['items']:
            if item['stable_line_key'] in stable_line_keys:
                item['is_excluded'] = 1
        self.state['batch_modified'] = 'BM2'
        return {'batch_modified': 'BM2', 'affected_group_ids': ['G1']}


def test_bulk_exclude_validates_all_rows_before_one_atomic_save():
    repo = Repo()

    result = bulk_exclude_materials(
        'B1', 'V1', ['L1', 'L2', 'L3'], 'TOKEN', 'BM1',
        reason='用户批量删除', repository=repo, actor='user@example.com',
    )

    assert result['excluded_count'] == 3
    assert result['stable_line_keys'] == ['L1', 'L2', 'L3']
    assert result['affected_group_ids'] == ['G1']
    assert result['batch_modified'] == 'BM2'
    assert repo.saved == [['L1', 'L2', 'L3']]


def test_bulk_exclude_rejects_missing_duplicate_or_already_excluded_without_writes():
    repo = Repo()
    with pytest.raises(ValueError, match='已变化'):
        bulk_exclude_materials(
            'B1', 'V1', ['L1', 'MISSING'], 'TOKEN', 'BM1', repository=repo,
        )
    with pytest.raises(ValueError, match='重复'):
        bulk_exclude_materials(
            'B1', 'V1', ['L1', 'L1'], 'TOKEN', 'BM1', repository=repo,
        )
    repo.state['items'][0]['is_excluded'] = 1
    with pytest.raises(ValueError, match='已变化'):
        bulk_exclude_materials(
            'B1', 'V1', ['L1'], 'TOKEN', 'BM1', repository=repo,
        )

    assert repo.saved == []


def test_bulk_exclude_rejects_a_single_group_member_until_group_is_removed():
    repo = Repo()

    with pytest.raises(ValueError, match='完整装箱组'):
        bulk_exclude_materials(
            'B1', 'V1', ['L1'], 'TOKEN', 'BM1', repository=repo,
        )

    assert repo.saved == []


def test_bulk_exclude_rejects_read_only_version_before_writing():
    repo = Repo()
    repo.state['editable'] = False

    with pytest.raises(ValueError, match='不能删除'):
        bulk_exclude_materials(
            'B1', 'V1', ['L1'], 'TOKEN', 'BM1', repository=repo,
        )
    assert repo.saved == []
