"""供应商 / 项目归属：已确认批次仍可维护，且不会把批次钉在「待重新计算」上。

这两项是采购在成本确认**之后**才补的 ERP 基础资料（站点默认供应商、ERP 项目路由），
分摊计算从不读它们，所以 ``REFERENCE_ITEM_FIELDS`` 单开一档写入门槛：已确认 / 已锁定 /
已回写的**当前版本**放行，历史与归档版本照旧只读；数量金额与装箱组结构一字没放开。
"""

from types import SimpleNamespace

import pytest

from overseas_costing.services import calculate_service, effective_source_values


def _version_row(*, current_version="V-1", version_status="Confirmed",
                 confirm_status="Confirmed", writeback_status="Failed"):
    return {"current_version": current_version, "version_status": version_status,
            "confirm_status": confirm_status, "writeback_status": writeback_status}


class _ItemDouble:
    """只替换持久化：保住 item 文档的读写表面，让写路径本身的逻辑可测。"""

    def __init__(self, payload):
        self.__dict__.update(payload)
        self.saved = False

    def save(self, ignore_permissions=False):
        self.saved = True
        return self

    def as_dict(self):
        return {key: value for key, value in vars(self).items() if key != "saved"}


def _item_payload():
    return {"name": "I-1", "batch": "B-1", "version": "V-1", "row_no": 1,
            "material_code": "SKU-1", "product_name": "Product", "transport_mode": "SEA",
            "extra_json": "{}", "project_collection": "", "supplier": "", "quantity": 10.0}


def _install_gate(monkeypatch, **version_overrides):
    """只装门槛需要的那一层：``db.sql`` 返回一行「批次 + 版本」写入上下文。"""

    monkeypatch.setattr(calculate_service, "_frappe", SimpleNamespace(
        db=SimpleNamespace(sql=lambda *args, **kwargs: [_version_row(**version_overrides)])))


def _install_write(monkeypatch, **version_overrides):
    """装一条可写的 item 记录，并记录 batch 写入与指纹刷新调用。"""

    item = _ItemDouble(_item_payload())
    writes = []
    refreshed = []

    def get_value(doctype, name, fields=None, **kwargs):
        return "2026-09-30 10:00:00" if fields == "modified" else "B-1"

    monkeypatch.setattr(calculate_service, "_frappe", SimpleNamespace(
        get_doc=lambda *_args: item,
        session=SimpleNamespace(user="tester@example.com"),
        db=SimpleNamespace(
            sql=lambda *args, **kwargs: [_version_row(**version_overrides)],
            set_value=lambda *args, **kwargs: writes.append((args, kwargs)),
            get_value=get_value,
            commit=lambda *args, **kwargs: None,
        )))
    monkeypatch.setattr(calculate_service, "_insert_audit_log", lambda **_kwargs: None)
    monkeypatch.setattr(calculate_service, "_refresh_saved_input_hash_for_reference_change",
                        lambda batch, version: refreshed.append((batch, version)))
    monkeypatch.setattr(effective_source_values, "batch_source_context", lambda *args, **kwargs: {})
    return item, writes, refreshed


def _written_fields(writes):
    """把 set_value 调用折成 {字段名: 值}，方便断言「写了什么、没写什么」。"""

    return {args[2]: args[3] for args, _kwargs in writes if len(args) > 3}


def test_reference_fields_are_writable_on_a_confirmed_current_version(monkeypatch):
    """已确认 / 已锁定的当前版本：这两项放行，其余字段的门槛一字未变。"""

    _install_gate(monkeypatch)
    with pytest.raises(ValueError, match="只能编辑当前未确认的活动版本"):
        calculate_service._assert_current_item_version("B-1", "V-1")
    context = calculate_service._assert_current_item_version("B-1", "V-1", reference_fields=True)
    assert context["confirm_status"] == "Confirmed"
    assert context["current_version"] == "V-1"


@pytest.mark.parametrize("version_status", ["", "Archived"])
def test_reference_fields_stay_locked_on_archived_or_unknown_versions(monkeypatch, version_status):
    """归档（以及读不到状态）的版本不给开：这一档只放宽「当前版本」。"""

    _install_gate(monkeypatch, version_status=version_status)
    with pytest.raises(ValueError, match="历史或归档版本"):
        calculate_service._assert_current_item_version("B-1", "V-1", reference_fields=True)


def test_reference_gate_requires_the_current_version(monkeypatch):
    """看的不是当前版本（历史版本）就不许改，即使版本状态还挂着 Confirmed。"""

    _install_gate(monkeypatch, current_version="V-2")
    with pytest.raises(ValueError, match="历史或归档版本"):
        calculate_service._assert_current_item_version("B-1", "V-1", reference_fields=True)


def test_reference_gate_still_rejects_a_foreign_version_request(monkeypatch):
    _install_gate(monkeypatch)
    with pytest.raises(ValueError, match="物料不属于所选版本"):
        calculate_service._assert_current_item_version("B-1", "V-1", "V-9", reference_fields=True)


def test_reference_write_on_a_confirmed_batch_keeps_the_status_and_realigns_the_hash(monkeypatch):
    """写入落库、批次不被标成 Dirty、指纹刷新一次 —— 三件事一次说清。"""

    item, writes, refreshed = _install_write(monkeypatch)
    result = calculate_service.update_item_field(
        "I-1", "project_collection", "项目一", "V-1", remark="补项目归属",
        _skip_edit_check=True, _skip_commit=True)

    assert result["ok"] is True and result["changed"] is True
    assert result["reference_relaxed"] is True
    assert item.saved is True and item.project_collection == "项目一"
    fields = _written_fields(writes)
    # 已确认批次绝不能被写成 Dirty：那会让 cost_review_service 判 RESULT_STALE、
    # 也会让批次列表把这个批次显示成未确认。
    assert "status" not in fields and "Dirty" not in fields.values()
    assert "modified" in fields
    assert refreshed == [("B-1", "V-1")]
    assert "成本结果保持不变" in result["message"]


def test_reference_write_defers_the_realign_when_the_batch_entry_owns_it(monkeypatch):
    """批量入口逐行写时不逐行重算全批哈希：整批写完由调用方刷新一次。"""

    _item, _writes, refreshed = _install_write(monkeypatch)
    result = calculate_service.update_item_field(
        "I-1", "supplier", "/", "V-1", remark="标记为无供应商",
        _skip_edit_check=True, _skip_commit=True, _defer_reference_rebaseline=True)

    assert result["ok"] is True and result["reference_relaxed"] is True
    assert refreshed == []


def test_confirmed_batch_still_rejects_cost_fields(monkeypatch):
    """放开只限那两项：数量金额在已确认版本上照旧被拒。"""

    item, writes, refreshed = _install_write(monkeypatch)
    result = calculate_service.update_item_field(
        "I-1", "quantity", "12", "V-1", _skip_edit_check=True, _skip_commit=True)

    assert result["ok"] is False
    assert "只能编辑当前未确认的活动版本" in result["message"]
    assert item.saved is False
    assert _written_fields(writes) == {}
    assert refreshed == []
