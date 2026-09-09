"""
中文用途：海外成本分摊规则控制器。

分摊规则用于描述：
1. 某个费用池是什么
2. 该费用按什么维度分摊
3. 该规则当前是否启用
"""

from __future__ import annotations

from frappe.model.document import Document

from overseas_costing.constants import ALLOCATION_BASES
from overseas_costing.utils.validators import require_in, require_value


class OverseasCostAllocationRule(Document):
    """海外成本分摊规则。"""

    def validate(self) -> None:
        from overseas_costing.services.calculate_service import (
            _server_metadata_fields,
            assert_server_metadata_unchanged,
        )

        scope = getattr(self, "scope_value_json", None)
        if not self.flags.get("ignore_permissions"):
            previous = self.get_doc_before_save()
            assert_server_metadata_unchanged(
                getattr(previous, "scope_value_json", None), scope,
                fields=("project_allocation",),
            )
            if _server_metadata_fields(getattr(previous, "scope_value_json", None), ("project_allocation",)) and any(
                getattr(previous, field, None) != getattr(self, field, None) for field in ("batch", "version")
            ):
                raise ValueError("服务器项目规则不能通过普通保存迁移到其他批次或版本。")
        if _server_metadata_fields(scope, ("project_allocation",)) and (
            getattr(self, "scope_type", None) != "ALL_ITEMS" or self.allocation_basis != "gross_weight"
            or getattr(self, "basis_field", None) not in (None, "", "gross_weight")
        ):
            raise ValueError("已确认的项目毛重规则不能变更为其他范围或依据。")
        require_value(self.batch, "所属批次")
        require_value(self.version, "所属版本")
        require_value(self.rule_code, "规则编码")
        if self.allocation_basis:
            require_in(self.allocation_basis, ALLOCATION_BASES, "分摊依据")
