### Mes Integration

connect to mes

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app mes_integration
```

### Material Request 接口压测

压测脚本位于 `scripts/benchmark_material_request_api.py`。建议在 ERP/Frappe 主机上直接访问本机地址，并先使用单并发建立不受网络和并发影响的基线。脚本只使用标准库，不会调用 MES/DLM 外部接口，但会创建并提交真实的 Material Request，请使用专用测试公司、物料和仓库。

```bash
export MES_API_AUTHORIZATION='token <api_key>:<api_secret>'

python3 scripts/benchmark_material_request_api.py \
  --base-url http://127.0.0.1:8000 \
  --host-header dev.localhost \
  --company 'Test Company' \
  --item-code 'TEST-ITEM' \
  --warehouse 'Stores - TC' \
  --uom Nos \
  --detail-count 5000 \
  --requests 5 \
  --workers 1 \
  --warmup 1 \
  --confirm
```

输出包括成功率、吞吐量、平均耗时、P50/P95/P99 和最大耗时。`--workers 1` 用于单并发基线，确认基线后再逐步增加 `--workers` 观察并发下的变化。可先加 `--dry-run` 检查请求体大小而不调用接口；认证信息不会写入结果文件。

脚本默认只发送接口必需字段，重点观察大明细落库耗时。如果需要复现生产请求体大小，可准备一条明细 JSON 样例并传入 `--detail-template-file`；脚本会复制其中的业务字段到每条明细，并自动覆盖 `idx`、`parent` 等服务端字段。

接口内部使用不依赖 `tabSeries` 的 MES 单号。MES 请求先进入 long 队列，后台创建并提交 Material Request；`tabBin.indented_qty` 在建单事务之后由 short 队列任务重新汇总。任务按物料和仓库重新汇总所有已提交需求，因此重复执行和失败重试不会重复累加。任务执行时仍会锁定相同“物料＋仓库”的 Bin，并与标准 ERPNext 更新保持一致；队列不可用时任务会进入 Failed，MES 可使用同一个幂等号重试。任务完成前 Bin 汇总可能存在短暂延迟。

MES 重试请求时应传递稳定的 `X-Idempotency-Key`，或在请求数据中提供 `custom_material_request_no`、`request_id` 或 `idempotency_key`，接口会复用同一个异步任务，不会重复建单。

完整异步创建任务投递到 Frappe long 队列，Bin 汇总和审计日志使用 short 队列；部署时建议至少运行 2 个 long worker，并单独运行 short/default worker，避免大明细建单任务互相排队。

当前开发 bench 的进程配置为：

    bench worker --queue long
    bench worker --queue long
    bench worker --queue short,default

系统每 5 分钟会自动恢复没有实际队列任务的 Queued 任务，以及超过 30 分钟的 Processing 任务；恢复执行仍使用原任务提交用户的权限。

### MES 入库接口

MES 可调用以下接口创建入库 Stock Entry：

    POST /api/method/mes_integration.api.create_stock_entry

该接口默认创建草稿；如果 MES 需要一次完成创建和提交，可使用：

    POST /api/method/mes_integration.api.create_and_submit_stock_entry

或者在 `create_stock_entry` 请求中传递 `submit=1`。请求数据应至少包含 `company`、`stock_entry_type` 和 `items`，其中 `stock_entry_type` 支持 `Material Receipt`、`Semi Finished Goods Receipt` 和 `Finished Goods Receipt`。每行入库明细需要 `item_code`、正数 `qty` 和 `t_warehouse`；未传目标仓库时 ERP 会按物料默认仓库或配置的兜底仓库补齐。

入库接口必须传 `sales_order`。该字段优先填写 CRM 销售订单号（ERP Sales Order 的 `custom_crm_order_no`）；系统会自动解析对应的 ERP 销售订单，并写入 Stock Entry 的 `custom_sales_order` Link 字段。为兼容旧调用，也支持直接填写 ERP Sales Order 内部单号。创建并提交成功的响应会返回 ERP 销售订单号 `sales_order` 和 CRM 订单号 `sales_order_crm_order_no`，以及 `stock_entry_docstatus: 1`、`submitted: true`。

提交入库后，系统会向 `mes_status_callback_url` 回调 Stock Entry 状态；MES 接口需要返回 HTTP 2xx 的 JSON，并且 `success: true`、`data.status: "processed"`。

异步接口返回的是“已接收并返回任务号”，压测脚本统计的是 MES 到 ERP 的接收耗时，不是后台建单耗时。

MES 创建物料需求后，应保存返回的 task_id，并轮询：

    GET /api/method/mes_integration.api.get_material_request_task_status?task_id=<task_id>

状态为 queued、processing、success 或 failed。只有 success 表示 Material Request 已创建并提交；失败时可使用同一个幂等号重新调用创建接口。任务成功后会自动清空暂存的原始大 payload，只保留状态和单据号。

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/mes_integration
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
