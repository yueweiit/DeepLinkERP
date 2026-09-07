# 多站点 ERP 路由、暂估推送与成本更新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按物料项目把整柜成本结果推送到正确子公司和 ERP 站点，支持整柜单一归属和混装、分站点部分成功、暂估转实际更新且不重复新增采购数量。

**Architecture:** 项目路由先解析为冻结的行级去向，再用已确认成本快照生成按站点/单据约束分组的同步任务。同步账本以稳定业务关联和请求幂等键分开管理首次创建与后续成本更新；ERP 适配器显式声明站点能力，不支持或未验证更新时失败关闭并保留人工待办。

**Tech Stack:** Python 3、Frappe DocType/API、ERPNext REST、pytest/fake HTTP、原生 JavaScript/CSS、现有审计及编辑版本服务。

---

## 范围、依赖与执行安全

执行本计划前完成 `2026-09-07-material-input-grid.md` 和 `2026-09-07-fee-allocation-reminders.md`。本计划消费稳定物料行、有效发货数量、不可变成本结果哈希和费用性质，不重新计算费用。

离线单元测试和本地 `development.localhost` 草稿单据可以自动执行。任何真实站点写入之前必须由用户明确指定测试站点、目标公司和脱敏/测试批次；未获得该范围时停在只读能力核验和假客户端验收。不得读取或输出 Password 字段明文，不在计划执行日志中打印 Authorization。

本期不自动撤销/提交 ERP 单据、不拦截领用、不处理领用后会计调整。已推送后变更物料集合、数量或站点属于业务变更，不走普通成本更新。

## 目标文件结构

- `overseas_costing/services/erp_routing_service.py`：项目映射、整柜快捷归属、行级去向和站点/单据分组。
- `overseas_costing/services/erp_sync_service.py`：预览、请求账本、稳定关联、分站点执行、状态和安全重试。
- `overseas_costing/services/erp_capability_service.py`：站点安全配置和只读能力核验结果。
- `overseas_costing/services/erp_client.py`：接收显式站点配置的创建、查询和成本更新适配器。
- `overseas_costing/api/erp_sync.py`：路由、预览、推送、更新和状态 API。
- `overseas_costing/doctype/overseas_cost_erp_site/*`：站点配置及能力模式，仅管理员读取凭据。
- `overseas_costing/doctype/overseas_cost_project_route/*`：项目到子公司/站点映射。
- `overseas_costing/doctype/overseas_cost_erp_document_link/*`：本地物料行到远端单据行的稳定关联。
- `overseas_costing/doctype/overseas_cost_erp_sync_request/*`：不可变请求、版本、哈希及回执。
- `overseas_costing/page/overseas_cost_workbench/parts/79-erp-sites.js`：分站点预览、差异和重试。
- `overseas_costing/page/overseas_cost_workbench/parts/51-erp-sites.css`：站点状态和差异布局。

## Task 1: 建立站点、路由、单据关联与同步账本

**Files:**

- Create: `overseas_costing/doctype/overseas_cost_erp_site/__init__.py`
- Create: `overseas_costing/doctype/overseas_cost_erp_site/overseas_cost_erp_site.py`
- Create: `overseas_costing/doctype/overseas_cost_erp_site/overseas_cost_erp_site.json`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_erp_site/__init__.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_erp_site/overseas_cost_erp_site.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_erp_site/overseas_cost_erp_site.json`
- Create: `overseas_costing/doctype/overseas_cost_project_route/__init__.py`
- Create: `overseas_costing/doctype/overseas_cost_project_route/overseas_cost_project_route.py`
- Create: `overseas_costing/doctype/overseas_cost_project_route/overseas_cost_project_route.json`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_project_route/__init__.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_project_route/overseas_cost_project_route.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_project_route/overseas_cost_project_route.json`
- Create: `overseas_costing/doctype/overseas_cost_erp_document_link/__init__.py`
- Create: `overseas_costing/doctype/overseas_cost_erp_document_link/overseas_cost_erp_document_link.py`
- Create: `overseas_costing/doctype/overseas_cost_erp_document_link/overseas_cost_erp_document_link.json`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_erp_document_link/__init__.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_erp_document_link/overseas_cost_erp_document_link.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_erp_document_link/overseas_cost_erp_document_link.json`
- Create: `overseas_costing/doctype/overseas_cost_erp_sync_request/__init__.py`
- Create: `overseas_costing/doctype/overseas_cost_erp_sync_request/overseas_cost_erp_sync_request.py`
- Create: `overseas_costing/doctype/overseas_cost_erp_sync_request/overseas_cost_erp_sync_request.json`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_erp_sync_request/__init__.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_erp_sync_request/overseas_cost_erp_sync_request.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_erp_sync_request/overseas_cost_erp_sync_request.json`
- Modify: `overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json`
- Modify: `overseas_costing/overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json`
- Create: `overseas_costing/tests/test_erp_sync_doctypes.py`

- [x] **Step 1: 写失败测试，锁定字段和权限**

```python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _doctype(name: str) -> dict:
    path = ROOT / "doctype" / name / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_erp_site_credentials_are_not_readable_by_cost_user() -> None:
    site = _doctype("overseas_cost_erp_site")
    fields = {row["fieldname"]: row for row in site["fields"]}
    permissions = {row["role"]: row for row in site["permissions"]}
    assert fields["authorization"]["fieldtype"] == "Password"
    assert not permissions.get("海外成本核算用户", {}).get("read")


def test_sync_request_has_unique_idempotency_key() -> None:
    request = _doctype("overseas_cost_erp_sync_request")
    fields = {row["fieldname"]: row for row in request["fields"]}
    assert fields["request_id"]["unique"] == 1
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_erp_sync_doctypes.py`

Expected: FAIL because the DocTypes are absent.

- [x] **Step 3: 定义站点和路由**

`Overseas Cost ERP Site` 字段：`site_code`（唯一）、`label`、`subsidiary_code`、`enabled`、`base_url`、`authorization`（Password）、`push_mode`、`company`、`default_supplier`、`cost_center`、`default_currency`、`stock_uom`、`cost_update_mode`（DISABLED/MANUAL/DRAFT_PURCHASE_ORDER）、`capability_status`（UNVERIFIED/VERIFIED/FAILED）、`capability_checked_at`、`capability_summary_json`。普通核算用户只能通过安全摘要 API 看站点代码/名称/能力状态。

`Overseas Cost Project Route` 字段：`project_collection`、`subsidiary_code`、`erp_site`、`enabled`、`valid_from/to`、`revision`、`remark`。服务必须检测同一项目同一时点的多条有效映射，不按排序取第一条。

- [x] **Step 4: 定义稳定关联和请求账本**

`ERP Document Link` 保存 `batch`、`stable_line_key`、`site_code`、`business_key`、`remote_doctype`、`remote_document`、`remote_row`、`remote_docstatus`、`status`、`last_cost_result_hash`、`last_payload_hash`、`verified_at`。

`ERP Sync Request` 保存 `request_id`、`operation`（CREATE/UPDATE_COST/VERIFY）、`batch`、`version`、`cost_result_hash`、`site_code`、`payload_hash`、`status`（PENDING/RUNNING/SUCCESS/FAILED/UNCERTAIN/MANUAL_REQUIRED/SUPERSEDED）、`attempt_count`、`safe_payload_json`、`safe_response_json`、`error_code/message`、`started_at/finished_at`。JSON 只存脱敏内容。

- [x] **Step 5: 扩展物料行路由字段**

两份 Item JSON 增加 `subsidiary_code`、`erp_site_code`、`route_status`（UNRESOLVED/RESOLVED/OVERRIDDEN/CONFLICT）、`route_revision`。项目来源事实仍使用 `project_collection`；批量归属写明确 override 和审计，不改项目原值。

- [x] **Step 6: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_erp_sync_doctypes.py`

Expected: PASS.

```bash
git add overseas_costing/doctype/overseas_cost_erp_site overseas_costing/overseas_costing/doctype/overseas_cost_erp_site overseas_costing/doctype/overseas_cost_project_route overseas_costing/overseas_costing/doctype/overseas_cost_project_route overseas_costing/doctype/overseas_cost_erp_document_link overseas_costing/overseas_costing/doctype/overseas_cost_erp_document_link overseas_costing/doctype/overseas_cost_erp_sync_request overseas_costing/overseas_costing/doctype/overseas_cost_erp_sync_request overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json overseas_costing/overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json overseas_costing/tests/test_erp_sync_doctypes.py
git commit -m 'feat: model multi-site ERP synchronization'
```

## Task 2: 实现行级路由和整柜快捷归属

**Files:**

- Create: `overseas_costing/services/erp_routing_service.py`
- Create: `overseas_costing/tests/test_erp_routing_service.py`

- [x] **Step 1: 写失败测试**

```python
def test_mixed_container_routes_distinct_materials() -> None:
    result = resolve_item_routes(
        items=[
            {"stable_line_key": "P1", "project_collection": "生产项目"},
            {"stable_line_key": "E1", "project_collection": "电商项目"},
        ],
        routes=[
            {"project_collection": "生产项目", "subsidiary_code": "PROD_CO", "site_code": "ERP_PROD", "enabled": 1},
            {"project_collection": "电商项目", "subsidiary_code": "ECOM_CO", "site_code": "ERP_ECOM", "enabled": 1},
        ],
    )
    assert result["by_item"]["P1"]["site_code"] == "ERP_PROD"
    assert result["by_item"]["E1"]["site_code"] == "ERP_ECOM"


def test_ambiguous_project_mapping_never_chooses_first_route() -> None:
    result = resolve_item_routes(
        [{"stable_line_key": "P1", "project_collection": "项目A"}],
        [
            {"project_collection": "项目A", "subsidiary_code": "CO1", "site_code": "S1", "enabled": 1},
            {"project_collection": "项目A", "subsidiary_code": "CO2", "site_code": "S2", "enabled": 1},
        ],
    )
    assert result["by_item"]["P1"]["status"] == "CONFLICT"


def test_bulk_assignment_requires_preview_when_existing_routes_differ() -> None:
    preview = preview_bulk_route(
        [
            {"stable_line_key": "P1", "erp_site_code": "S1", "route_status": "RESOLVED"},
            {"stable_line_key": "E1", "erp_site_code": "S2", "route_status": "RESOLVED"},
        ],
        target_site="S1",
    )
    assert preview["requires_confirmation"] is True
    assert preview["changed_item_keys"] == ["E1"]
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_erp_routing_service.py`

Expected: FAIL because routing service is absent.

- [x] **Step 3: 实现纯路由函数**

```python
from collections import defaultdict


def normalize_project(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def active_routes_by_project(routes: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for route in routes:
        if int(route.get("enabled", 1)):
            grouped[normalize_project(route.get("project_collection"))].append(route)
    return grouped


def _route_state(status: str, code: str = "", route: dict | None = None) -> dict:
    route = route or {}
    return {
        "status": status,
        "code": code,
        "subsidiary_code": route.get("subsidiary_code") or "",
        "site_code": route.get("site_code") or route.get("erp_site_code") or "",
    }


def resolve_item_routes(items: list[dict], routes: list[dict]) -> dict:
    by_project = active_routes_by_project(routes)
    result = {}
    for item in items:
        if item.get("route_status") == "OVERRIDDEN":
            result[item["stable_line_key"]] = _route_state("OVERRIDDEN", route=item)
            continue
        matches = by_project.get(normalize_project(item.get("project_collection")), [])
        result[item["stable_line_key"]] = (
            _route_state("UNRESOLVED", "PROJECT_REQUIRED") if not item.get("project_collection") else
            _route_state("UNRESOLVED", "ROUTE_NOT_CONFIGURED") if not matches else
            _route_state("CONFLICT", "MULTIPLE_ACTIVE_ROUTES") if len(matches) != 1 else
            _route_state("RESOLVED", route=matches[0])
        )
    return {
        "by_item": result,
        "ready": all(row["status"] in {"RESOLVED", "OVERRIDDEN"} for row in result.values()),
    }
```

整柜生产/电商快捷操作先返回差异预览，再在批次锁内写行级 override。它不得拆数量、覆盖项目名或更改费用分摊结果；若费用范围依赖子公司，路由变化使相应成本结果失效并要求重算。

费用编辑器中的“按子公司承担”是选择快捷方式：服务端按当前路由预览属于该子公司的稳定物料行，确认后仍以 `scope_type=ITEMS`、显式稳定行键和 `scope_revision=route_revision` 保存。这样后续路由变化能准确使范围失效，不会把尚未匹配的物料默认为整柜共同承担。

- [x] **Step 4: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_erp_routing_service.py`

Expected: PASS.

```bash
git add overseas_costing/services/erp_routing_service.py overseas_costing/tests/test_erp_routing_service.py
git commit -m 'feat: resolve material routes by ERP site'
```

## Task 3: 构造分站点、分单据的推送预览和门槛

**Files:**

- Modify: `overseas_costing/services/erp_routing_service.py`
- Modify: `overseas_costing/services/batch_service.py`
- Create: `overseas_costing/tests/test_erp_payload_grouping.py`
- Modify: `overseas_costing/tests/test_batch_service.py`

- [x] **Step 1: 写失败测试**

```python
def test_common_fee_is_not_duplicated_across_sites() -> None:
    preview = build_site_payload_preview(
        result={
            "status": "CONFIRMED",
            "cost_result_hash": "H1",
            "fee_total_rmb": "30",
            "items": [
                {"stable_line_key": "P1", "erp_site_code": "ERP_PROD", "total_cost_rmb": "70", "allocated_fee_rmb": "20", "supplier": "S", "purchase_currency": "CNY", "erp_stock_uom": "kg"},
                {"stable_line_key": "E1", "erp_site_code": "ERP_ECOM", "total_cost_rmb": "50", "allocated_fee_rmb": "10", "supplier": "S", "purchase_currency": "CNY", "erp_stock_uom": "件"},
            ],
        }
    )
    assert sum(Decimal(site["total_cost_rmb"]) for site in preview["sites"]) == Decimal("120")
    assert sum(Decimal(site["allocated_fee_rmb"]) for site in preview["sites"]) == Decimal("30")


def test_first_push_blocks_entire_batch_if_one_item_has_no_route() -> None:
    result = build_erp_push_state({
        "status": "CONFIRMED",
        "cost_result_hash": "H1",
        "items": [{
            "stable_line_key": "P1", "route_status": "UNRESOLVED", "erp_site_code": "",
            "total_cost_rmb": "70", "erp_stock_uom": "kg",
        }],
    })
    assert result["ready"] is False
    assert result["blocking"][0]["code"] == "ITEM_ROUTE_REQUIRED"
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_erp_payload_grouping.py overseas_costing/tests/test_batch_service.py`

Expected: FAIL because current payload copies one batch subsidiary to all items and performs one push.

- [x] **Step 3: 实现分组**

先按 `site_code`，再按目标端必要的供应商、币种及单位约束分组；分组只组织已确认的逐行金额，不重新分摊：

```python
group_key = (
    row["erp_site_code"],
    row["supplier"],
    normalize_currency(row["purchase_currency"]),
    row["erp_stock_uom"],
)
```

预览返回每站点的物料、数量、采购金额、直接/分摊费用、综合金额、暂估费用键、阻断项及分组数。站点金额之和必须与成本快照一致；整柜共同费不得复制为每站点整额。

- [x] **Step 4: 拆分门槛**

`build_erp_push_state()` 要求：本批成本结果已确认且未失效、所有待推送行路由及 ERP 单位齐、每个站点安全配置存在。费用可以仍为明确暂估；金额空白或分摊无效不能通过。被拒绝/撤销/终止审批继续阻断。

- [x] **Step 5: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_erp_payload_grouping.py overseas_costing/tests/test_batch_service.py`

Expected: PASS.

```bash
git add overseas_costing/services/erp_routing_service.py overseas_costing/services/batch_service.py overseas_costing/tests/test_erp_payload_grouping.py overseas_costing/tests/test_batch_service.py
git commit -m 'feat: preview ERP payloads by site'
```

## Task 4: 实现请求幂等和稳定远端业务关联

**Files:**

- Create: `overseas_costing/services/erp_sync_service.py`
- Create: `overseas_costing/tests/test_erp_sync_service.py`

- [x] **Step 1: 写失败测试**

覆盖相同 `request_id` 返回同一结果、相同 payload 新请求不重复创建、旧回执不覆盖新版本、超时为 UNCERTAIN 且重试前查询、历史多单据歧义为 MANUAL_REQUIRED、成本版本变化不生成新采购业务键。

```python
def test_cost_version_is_not_part_of_purchase_business_identity() -> None:
    assert purchase_business_key(batch="B1", site="S1", group="G1", version="V1") == \
           purchase_business_key(batch="B1", site="S1", group="G1", version="V2")
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_erp_sync_service.py`

Expected: FAIL because sync ledger service is absent.

- [x] **Step 3: 实现状态机和哈希**

```python
import hashlib


def purchase_business_key(*, batch: str, site: str, group: str, version: str = "") -> str:
    identity = "\x1f".join((batch.strip(), site.strip(), group.strip()))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


ALLOWED_TRANSITIONS = {
    "PENDING": {"RUNNING", "SUPERSEDED"},
    "RUNNING": {"SUCCESS", "FAILED", "UNCERTAIN", "MANUAL_REQUIRED"},
    "FAILED": {"RUNNING", "SUPERSEDED"},
    "UNCERTAIN": {"SUCCESS", "FAILED", "MANUAL_REQUIRED"},
    "SUCCESS": set(),
    "MANUAL_REQUIRED": set(),
    "SUPERSEDED": set(),
}
```

`business_key = sha256(batch + site + supplier/currency/uom group + stable line keys)`；不包含成本版本。`request_id` 包含操作、站点、业务键、成本结果哈希和随机客户端意图键。所有比较采用保存的 payload hash，不依赖 UI 当前对象。

- [x] **Step 4: 定义历史关联核验**

旧批次没有新关联时，先按批次业务标识只读查远端单据和行。唯一且物料/数量吻合才写 VERIFIED link；零条表示首次创建候选；多条、多个版本订单或行不匹配返回 `MANUAL_REQUIRED`。不得把“没有新格式 link”直接当首次推送。

- [x] **Step 5: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_erp_sync_service.py`

Expected: PASS.

```bash
git add overseas_costing/services/erp_sync_service.py overseas_costing/tests/test_erp_sync_service.py
git commit -m 'feat: track idempotent ERP sync requests'
```

## Task 5: 把 ERP 客户端改为显式站点配置并停止隐式物料主数据更新

**Files:**

- Create: `overseas_costing/services/erp_capability_service.py`
- Modify: `overseas_costing/services/erp_client.py`
- Modify: `overseas_costing/install.py`
- Modify: `overseas_costing/tests/test_erp_client.py`
- Create: `overseas_costing/tests/test_erp_capability_service.py`
- Create: `overseas_costing/tests/test_install.py`

- [x] **Step 1: 写失败测试**

```python
def test_existing_purchase_order_is_checked_before_any_item_write(monkeypatch) -> None:
    writes = []
    monkeypatch.setattr(
        erp_client,
        "lookup_purchase_by_business_key",
        lambda payload, config: {"found": True, "name": "PO-1"},
    )
    monkeypatch.setattr(
        erp_client,
        "_ensure_item",
        lambda item, payload, config: writes.append(item),
    )
    result = erp_client.create_purchase(
        {"business_key": "BK1", "items": [{"material_code": "M1"}]},
        {"base_url": "https://erp.invalid/api/resource", "authorization": "token hidden", "timeout": 1},
    )
    assert result["status"] == "EXISTS"
    assert writes == []


def test_site_config_is_explicit_and_secret_is_redacted() -> None:
    result = build_safe_site_summary({"site_code": "S1", "authorization": "token secret"})
    assert "authorization" not in result
    assert "secret" not in str(result)


def test_erpnext_custom_fields_include_stable_business_links() -> None:
    fields = build_erpnext_standard_field_spec()
    assert "custom_overseas_business_key" in {row["fieldname"] for row in fields["Purchase Order"]}
    assert "custom_overseas_stable_line_key" in {row["fieldname"] for row in fields["Purchase Order Item"]}
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_erp_client.py overseas_costing/tests/test_erp_capability_service.py overseas_costing/tests/test_install.py`

Expected: FAIL because current standard flow calls `_ensure_item` before returning a deduplicated Purchase Order and loads one global configuration.

- [x] **Step 3: 重构客户端入口**

```python
class AmbiguousRemoteBusinessKey(RuntimeError):
    """Raised when one stable business key resolves to multiple remote documents."""


def _request_json(config: dict, *, method: str, url: str, body: dict | None = None) -> dict:
    request = _build_request(config, url=url, method=method, body=body)
    with urlopen(request, timeout=config["timeout"]) as response:
        return _load_json_response(response.read().decode("utf-8", errors="ignore"))


def lookup_purchase_by_business_key(payload: dict, config: dict) -> dict:
    name = _find_existing_purchase_order_by_business_key(payload, config)
    return {"found": bool(name), "name": name}


def _find_existing_purchase_order_by_business_key(payload: dict, config: dict) -> str:
    business_key = str(payload.get("business_key") or "").strip()
    if not business_key:
        raise ValueError("business_key is required")
    filters = [["custom_overseas_business_key", "=", business_key]]
    url = (
        f"{_build_doctype_url(config, 'Purchase Order')}"
        f"?fields={quote(json.dumps(['name'], ensure_ascii=False), safe='')}"
        f"&filters={quote(json.dumps(filters, ensure_ascii=False), safe='')}"
        "&limit_page_length=2"
    )
    data = (_request_json(config, method="GET", url=url).get("data") or [])
    if len(data) > 1:
        raise AmbiguousRemoteBusinessKey(business_key)
    return str((data[0] if data else {}).get("name") or "")


def create_purchase(payload: dict, config: dict) -> dict:
    existing = lookup_purchase_by_business_key(payload, config)
    if existing["found"]:
        return {"ok": True, "status": "EXISTS", "erp_target_doc": existing["name"]}
    item_results = [_ensure_item(item, payload, config) for item in payload.get("items") or []]
    response = _request_json(
        config,
        method="POST",
        url=_build_doctype_url(config, "Purchase Order"),
        body=_build_purchase_order_body(payload, config),
    )
    return {
        "ok": True,
        "status": "CREATED",
        "erp_target_doc": _extract_target_doc(response),
        "items": item_results,
    }


def read_purchase_state(link: dict, config: dict) -> dict:
    return _request_json(
        config,
        method="GET",
        url=_build_doctype_url(config, link["remote_doctype"], link["remote_document"]),
    )


def update_purchase_cost(payload: dict, link: dict, config: dict) -> dict:
    return {"ok": False, "status": "MANUAL_REQUIRED", "code": "UPDATE_MODE_UNAVAILABLE"}
```

配置由同步服务按 `site_code` 加载并传入；客户端不得从批次自动选择全局站点。查到业务单据后先核对 payload/link，再决定 CREATE/UPDATE/NOOP。Item 主数据创建作为首次业务创建中的显式子步骤；禁止用批次成本覆盖全局 Item 成本来宣称单据已更新。

把 `ensure_erpnext_standard_fields()` 的字段字典提取成可测试的 `build_erpnext_standard_field_spec()`，为 Purchase Order 增加 `custom_overseas_business_key`、`custom_overseas_cost_result_hash`、`custom_overseas_amount_status`，为 Purchase Order Item 增加 `custom_overseas_stable_line_key`。新客户端只依赖已通过能力核验的这些字段；缺字段时不写。

这些字段不是只在综合成本应用所在站点创建：每个配置为目标的 ERP 站点都必须部署同一字段规范，或由该站点的受控适配器提供等价、可唯一查询的字段。能力核验按站点逐一确认，任何一个目标站点缺字段只阻断该站点，不把其他站点伪装成成功。

- [x] **Step 4: 实现只读能力核验**

核验只读取站点连通性、Purchase Order 元数据、所需自定义字段和目标单据状态；输出 `VERIFIED/FAILED` 及缺失能力列表，不修改远端。`cost_update_mode` 仍由管理员根据受控写验证明确启用，不能仅凭元数据自动切成可写。

- [x] **Step 5: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_erp_client.py overseas_costing/tests/test_erp_capability_service.py overseas_costing/tests/test_install.py`

Expected: PASS and no test performs network access.

```bash
git add overseas_costing/services/erp_client.py overseas_costing/services/erp_capability_service.py overseas_costing/install.py overseas_costing/tests/test_erp_client.py overseas_costing/tests/test_erp_capability_service.py overseas_costing/tests/test_install.py
git commit -m 'refactor: isolate ERP clients by site'
```

## Task 6: 实现首次分站点创建和部分成功

**Files:**

- Modify: `overseas_costing/services/erp_sync_service.py`
- Modify: `overseas_costing/services/erp_client.py`
- Modify: `overseas_costing/tests/test_erp_sync_service.py`
- Modify: `overseas_costing/tests/test_erp_client.py`

- [x] **Step 1: 写失败测试**

一个生产站点成功、电商站点失败时，断言生产 link 和 SUCCESS 请求已保存、电商为 FAILED；重试只包含电商；批次汇总为 PARTIAL；再次点击不会重复创建生产采购单；任何站点都不会收到全柜费用总额。

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_erp_sync_service.py overseas_costing/tests/test_erp_client.py`

Expected: FAIL because orchestration is not implemented.

- [x] **Step 3: 实现分站点执行**

为每个站点/单据分组先写 PENDING 请求并提交本地事务，再执行 HTTP。每个结果独立事务落账；成功后保存远端单据及行关联，并回读业务键、数量和成本字段核对。失败不回滚已成功站点，汇总从子请求计算，不把批次 `writeback_status=Success` 当真相源。

- [x] **Step 4: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_erp_sync_service.py overseas_costing/tests/test_erp_client.py`

Expected: PASS.

```bash
git add overseas_costing/services/erp_sync_service.py overseas_costing/services/erp_client.py overseas_costing/tests/test_erp_sync_service.py overseas_costing/tests/test_erp_client.py
git commit -m 'feat: push cost results to multiple ERP sites'
```

## Task 7: 实现暂估转实际的成本差异与更新适配器

**Files:**

- Modify: `overseas_costing/services/erp_sync_service.py`
- Modify: `overseas_costing/services/erp_client.py`
- Create: `overseas_costing/tests/test_erp_cost_update.py`

- [x] **Step 1: 写失败测试**

覆盖：暂估到实际金额变化；数值相同但性质从暂估转实际；只影响生产站点；更新不改变数量；DRAFT_PURCHASE_ORDER 只更新允许的成本字段及版本标记；已提交/已收货/不支持模式返回 MANUAL_REQUIRED；旧成本版本成功回执不能清新版本待办。

```python
def build_draft_purchase_cost_update(old_link: dict, new_cost: dict) -> dict:
    if str(old_link.get("quantity")) != str(new_cost.get("effective_shipped_qty")):
        raise ValueError("BUSINESS_CHANGE_REQUIRED")
    return {
        "custom_overseas_original_amount": new_cost["goods_value"],
        "custom_overseas_comprehensive_amount": new_cost["total_cost_rmb"],
        "custom_overseas_comprehensive_unit_price": new_cost["total_unit_rmb"],
        "custom_overseas_freight_alloc_amount": new_cost["freight_alloc_rmb"],
        "custom_overseas_clearance_alloc_amount": new_cost["clearance_alloc_rmb"],
        "custom_overseas_tax_alloc_amount": new_cost["tax_alloc_rmb"],
        "custom_overseas_cost_result_hash": new_cost["cost_result_hash"],
        "custom_overseas_amount_status": new_cost["amount_status"],
    }


def update_purchase_cost(payload: dict, link: dict, config: dict) -> dict:
    if config.get("cost_update_mode") != "DRAFT_PURCHASE_ORDER":
        return {"ok": False, "status": "MANUAL_REQUIRED", "code": "UPDATE_MODE_UNAVAILABLE"}
    current = read_purchase_state(link, config).get("data") or {}
    if int(current.get("docstatus") or 0) != 0:
        return {"ok": False, "status": "MANUAL_REQUIRED", "code": "DOCUMENT_NOT_DRAFT"}
    new_cost = next(
        row for row in payload.get("items") or []
        if row.get("stable_line_key") == link.get("stable_line_key")
    )
    item_response = _request_json(
        config,
        method="PUT",
        url=_build_doctype_url(config, "Purchase Order Item", link["remote_row"]),
        body=build_draft_purchase_cost_update(link, new_cost),
    )
    header_response = _request_json(
        config,
        method="PUT",
        url=_build_doctype_url(config, link["remote_doctype"], link["remote_document"]),
        body={
            "custom_overseas_cost_version": payload["version_code"],
            "custom_overseas_cost_result_hash": payload["cost_result_hash"],
            "custom_overseas_total_cost_rmb": payload["document_total_cost_rmb"],
        },
    )
    return {"ok": True, "status": "UPDATED", "item": item_response, "header": header_response}


def test_cost_update_payload_never_changes_quantity() -> None:
    body = build_draft_purchase_cost_update(
        old_link={"remote_row": "POI-1", "stable_line_key": "P1", "quantity": "34"},
        new_cost={
            "stable_line_key": "P1", "effective_shipped_qty": "34",
            "goods_value": "15300", "total_cost_rmb": "17000", "total_unit_rmb": "500",
            "freight_alloc_rmb": "900", "clearance_alloc_rmb": "500", "tax_alloc_rmb": "300",
            "cost_result_hash": "H2", "amount_status": "ACTUAL",
        },
    )
    assert "qty" not in body
    assert body["custom_overseas_comprehensive_amount"] == "17000"
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_erp_cost_update.py`

Expected: FAIL because the current code deduplicates by batch plus cost version and has no update path.

- [x] **Step 3: 构造站点差异**

`preview_cost_updates(batch, from_hash, to_hash)` 返回每站点/单据/行的旧新单价、金额、暂估性质、数量和变更字段。只有金额或报文性质变化的站点产生 UPDATE_COST；完全等价结果写 NOOP 关联。若物料集合、数量、子公司或站点变化，返回 `BUSINESS_CHANGE_REQUIRED`，不生成更新请求。

- [x] **Step 4: 实现失败关闭的更新模式**

- `DISABLED`：拒绝暂估推送功能开关并说明站点无后续更新路径。
- `MANUAL`：允许业务明确选择暂估首次推送，但后续差异导出为人工待办，系统不声称已同步。
- `DRAFT_PURCHASE_ORDER`：先回读远端父单 `docstatus=0` 和行键，再逐个 PUT `Purchase Order Item/{row_name}` 的允许成本自定义字段，最后单独更新父单成本版本/哈希/汇总；请求体不得包含数量、供应商、公司或项目。

其他单据状态全部 `MANUAL_REQUIRED`。不自动取消/复制采购订单。

- [x] **Step 5: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_erp_cost_update.py overseas_costing/tests/test_erp_sync_service.py overseas_costing/tests/test_erp_client.py`

Expected: PASS.

```bash
git add overseas_costing/services/erp_sync_service.py overseas_costing/services/erp_client.py overseas_costing/tests/test_erp_cost_update.py overseas_costing/tests/test_erp_sync_service.py overseas_costing/tests/test_erp_client.py
git commit -m 'feat: update provisional ERP costs safely'
```

## Task 8: 生成按站点关闭和重开的 ERP 待办

**Files:**

- Modify: `overseas_costing/services/fee_status_service.py`
- Modify: `overseas_costing/services/workbench_service.py`
- Modify: `overseas_costing/services/batch_service.py`
- Modify: `overseas_costing/tests/test_fee_status_service.py`
- Modify: `overseas_costing/tests/test_workbench_service.py`
- Modify: `overseas_costing/tests/test_batch_service.py`

- [ ] **Step 1: 写失败测试**

```python
def test_current_result_closes_only_successful_site_todo() -> None:
    work = build_erp_work_state(
        current_hash="H2",
        sites=[
            {"site_code": "PROD", "last_cost_result_hash": "H2", "status": "SUCCESS"},
            {"site_code": "ECOM", "last_cost_result_hash": "H1", "status": "SUCCESS"},
        ],
    )
    assert work["PROD"]["todo"] is None
    assert work["ECOM"]["todo"]["code"] == "ERP_UPDATE_REQUIRED"
```

同时断言费用待办与 ERP 回执无关；旧 H1 的迟到回执不能关闭 H2；路由/数量业务变更显示独立冲突。

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_fee_status_service.py overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_batch_service.py`

Expected: FAIL because only a batch-level writeback status exists.

- [ ] **Step 3: 实现站点状态摘要**

详情返回：

```python
"erp_work": {
  "overall": "PARTIAL",
  "sites": [
    {"site_code": "PROD", "state": "SYNCED", "cost_result_hash": "H2", "todo": None},
    {"site_code": "ECOM", "state": "UPDATE_REQUIRED", "last_hash": "H1",
     "todo": {"code": "ERP_UPDATE_REQUIRED", "action": "preview_update"}},
  ]
}
```

批次级旧字段仅作兼容投影：全部站点当前结果成功才为 Success；有成功有失败为 Pending/部分成功文案。费用最终确认和凭证状态不读取该投影。

- [ ] **Step 4: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_fee_status_service.py overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_batch_service.py`

Expected: PASS.

```bash
git add overseas_costing/services/fee_status_service.py overseas_costing/services/workbench_service.py overseas_costing/services/batch_service.py overseas_costing/tests/test_fee_status_service.py overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_batch_service.py
git commit -m 'feat: track ERP work by destination site'
```

## Task 9: 暴露安全 ERP 同步 API 和兼容入口

**Files:**

- Create: `overseas_costing/api/erp_sync.py`
- Modify: `overseas_costing/api/writeback.py`
- Create: `overseas_costing/tests/test_erp_sync_api.py`
- Modify: `overseas_costing/tests/test_access_control.py`

- [ ] **Step 1: 写失败测试**

锁定接口：

```python
get_route_preview(batch_name, version_name=None)
preview_bulk_route(batch_name, target_site_code)
apply_bulk_route(batch_name, preview_revision, edit_token, expected_modified)
preview_erp_sync(batch_name, version_name=None)
start_erp_create(batch_name, cost_result_hash, request_key)
preview_erp_updates(batch_name, from_hash, to_hash)
start_erp_updates(batch_name, to_hash, accepted_site_codes_json, request_key)
get_erp_sync_status(batch_name)
retry_erp_request(batch_name, request_id)
```

测试普通用户看不到 URL/token；发送需要写权限、已确认快照和服务器生成 payload；`accepted_site_codes` 只能来自最新预览；重试只能重试 FAILED/UNCERTAIN 经查询确认未成功的原请求。

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_erp_sync_api.py overseas_costing/tests/test_access_control.py`

Expected: FAIL because `api.erp_sync` is absent.

- [ ] **Step 3: 实现薄 API 及旧入口代理**

旧 `preview_erp_payload` 和 `writeback_to_erp` 在功能开关启用后调用新 service；若批次只能解析为一个站点，也仍写新请求和 link。禁止旧 API 继续绕过行级路由/幂等校验。

- [ ] **Step 4: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_erp_sync_api.py overseas_costing/tests/test_access_control.py overseas_costing/tests/test_batch_service.py`

Expected: PASS.

```bash
git add overseas_costing/api/erp_sync.py overseas_costing/api/writeback.py overseas_costing/tests/test_erp_sync_api.py overseas_costing/tests/test_access_control.py overseas_costing/tests/test_batch_service.py
git commit -m 'feat: expose secure multi-site ERP sync APIs'
```

## Task 10: 实现分站点预览、差异确认和重试界面

**Files:**

- Create: `overseas_costing/page/overseas_cost_workbench/parts/79-erp-sites.js`
- Create: `overseas_costing/page/overseas_cost_workbench/parts/51-erp-sites.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/05-workbench-state.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/30-calculation-erp.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js`
- Modify: `overseas_costing/tests/test_workbench_frontend_state.py`
- Modify generated files via: `overseas_costing/scripts/build_workbench_assets.py`

- [ ] **Step 1: 写前端失败测试**

验证整柜生产/电商快捷归属先显示差异；混装按行显示站点；缺路由仍可预览成本但禁用推送；推送预览按站点列数量/金额/暂估项；部分成功只重试失败站点；更新预览展示旧新金额；MANUAL_REQUIRED 不出现“更新成功”；费用待办不因站点成功消失。

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py`

Expected: FAIL because site UI state and markers are absent.

- [ ] **Step 3: 实现站点界面**

在物料表项目列旁显示子公司/站点；详情顶部 ERP 芯片显示总体状态，展开后按站点列当前结果哈希、目标单据、状态和操作。推送按钮先打开冻结预览；暂估费用逐项标注。更新按钮先显示新旧差异，用户只能选择本次预览中可更新站点。

失败或超时显示远端单据查询结果和下一步；不把重复点击变成新业务。页面只轮询当前请求的状态，有新输入版本时停止旧轮询并刷新。

- [ ] **Step 4: 生成资源并运行测试**

```bash
python overseas_costing/scripts/build_workbench_assets.py
python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py overseas_costing/tests/test_workbench_asset_builder.py
```

Expected: PASS and source/deployed assets match.

- [ ] **Step 5: 本地浏览器验收并提交**

用假 ERP 或 `development.localhost` 草稿目标验证：整柜生产、整柜电商、混装、未知项目、部分失败、迟到回执、暂估待实际、实际差异、手工处理站点。不得连接真实业务站点。

```bash
git add overseas_costing/page/overseas_cost_workbench/parts/79-erp-sites.js overseas_costing/page/overseas_cost_workbench/parts/51-erp-sites.css overseas_costing/page/overseas_cost_workbench/parts/05-workbench-state.js overseas_costing/page/overseas_cost_workbench/parts/30-calculation-erp.js overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/tests/test_workbench_frontend_state.py
git commit -m 'feat: add multi-site ERP synchronization UI'
```

## Task 11: 迁移、受控联调与阶段验收

**Files:**

- Modify: `overseas_costing/install.py`
- Modify: `overseas_costing/scripts/test_purchase_order_writeback.py`
- Create: `overseas_costing/tests/test_erp_sync_acceptance.py`
- Modify: `.github/scripts/sync_and_verify_assets.sh`

- [ ] **Step 1: 写历史迁移失败测试**

断言已推送历史批次不会自动标费用完成或当前已同步；历史相等数量不变成默认；旧单据唯一匹配才建 VERIFIED link；多版本/多单据不发送写入；迁移本身零 HTTP 写请求。

- [ ] **Step 2: 实现幂等迁移**

`after_migrate()` 只补站点/路由 DocType 元数据和本地历史候选状态，不读取 Password、不发远端请求。旧批次标 `legacy_link_status=UNVERIFIED`；真正关联在用户打开更新预览时执行只读核验。

- [ ] **Step 3: 运行离线全回归**

```bash
python -m pytest -q \
  overseas_costing/tests/test_erp_sync_doctypes.py \
  overseas_costing/tests/test_erp_routing_service.py \
  overseas_costing/tests/test_erp_payload_grouping.py \
  overseas_costing/tests/test_erp_sync_service.py \
  overseas_costing/tests/test_erp_capability_service.py \
  overseas_costing/tests/test_erp_client.py \
  overseas_costing/tests/test_erp_cost_update.py \
  overseas_costing/tests/test_erp_sync_api.py \
  overseas_costing/tests/test_erp_sync_acceptance.py \
  overseas_costing/tests/test_batch_service.py \
  overseas_costing/tests/test_workbench_service.py \
  overseas_costing/tests/test_workbench_frontend_state.py
```

Expected: PASS with fake HTTP only.

- [ ] **Step 4: 在本地 Frappe 草稿目标受控联调**

扩展 `test_purchase_order_writeback.py`，只能操作 `ERPTEST-` 前缀 Item/草稿 Purchase Order。执行前列出候选和将创建的目标；验证两个逻辑站点、稳定 link、重复请求、部分失败、暂估转实际仅更新成本字段及数量不变；清理仅删除本次测试前缀草稿。

本地通过后，输出一份逐站点部署检查：字段规范版本、业务键唯一查询能力、草稿行更新能力、凭据最小权限和回读能力。没有完成该站点检查，不得把它设为可写。

- [ ] **Step 5: 设置真实站点写入审批门槛**

如果用户尚未明确给出测试站点和测试批次，到此停止真实写联调并报告：离线及本地草稿结果、只读能力摘要、每站点 `cost_update_mode` 建议。不得自行选择生产单据。

获得明确范围后，先只读核验，再预览完整请求；用户再次确认目标后只执行一笔测试创建/更新并立即回读。不提交单据、不改变库存、不扩大凭据权限。失败保留真实状态，不用新单绕过。

- [ ] **Step 6: 验证部署检查并提交**

```bash
python overseas_costing/scripts/build_workbench_assets.py
git diff --check
python -m pytest -q overseas_costing/tests/test_erp_sync_acceptance.py overseas_costing/tests/test_workbench_frontend_state.py
git add overseas_costing/install.py overseas_costing/scripts/test_purchase_order_writeback.py overseas_costing/tests/test_erp_sync_acceptance.py .github/scripts/sync_and_verify_assets.sh
git commit -m 'test: verify multi-site ERP synchronization'
```
