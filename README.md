# 中国财务本土化

`china_finance` 是面向 ERPNext v16 的中国财务合规应用。应用保留 ERPNext 原有总账过账机制，在其基础上提供法定会计凭证快照、对账单、税务发票、版本化财务报表、期间结账控制和电子档案。

## 已实现模块

- 按公司配置企业会计准则或小企业会计准则；
- 独立的收、付、转、记凭证编号，不修改来源单据名称；
- 自动捕获所有已提交且产生总账分录的来源单据，生成不可变凭证快照；
- 客户、供应商和银行对账快照；
- 进项、销项数电票，支持蓝票、红票、作废票及多对多业务单据分摊；
- 电子原始凭证 SHA-256 校验和私有结账档案包；
- 版本化财务报表模板、科目映射、比较期间和结账报表快照；
- 中国凭证账簿、凭证完整性检查、增值税台账、增值税申报底稿和业务单据链报表；
- 提供独立的中国财务工作区、桌面入口和侧边栏，集中展示当前可用的中国财务功能；
- 基于 ERPNext `Period Closing Voucher` 和公司会计冻结日期的结账检查。

应用不使用 Server Script，不执行生产环境手工 SQL，不修改 ERPNext 核心代码，也不覆盖地区总账逻辑。

## 兼容环境

- Frappe / ERPNext `v16.23.0`
- Python `3.14`
- MariaDB `11.8`
- Node.js `24`

## 公司启用

应用随自定义镜像发布后，按公司执行初始化。启用日期是法定凭证切换日；切换日前的总账分录仍可在 ERPNext 报表中查询，但不会倒排法定凭证号。

```bash
bench --site SITE execute china_finance.api.initialize_company --kwargs \
  '{"company":"公司全称","accounting_standard":"企业会计准则","taxpayer_type":"一般纳税人","activation_date":"2026-01-01","enforce_role_separation":1}'
```

初始化会为资产负债表和利润表生成建议科目映射，所有建议映射默认处于“未复核”状态，必须由财务人员确认。现金流量表和所有者权益变动表取决于企业会计政策及现金流分类，需手工配置。

## 公共接口

- `china_finance.api.initialize_company`：初始化公司设置和建议科目映射；
- `china_finance.api.deployment_health`：检查部署结构和标准数据；
- `china_finance.services.voucher.rebuild_missing_vouchers`：幂等补建切换日后的缺失凭证；
- `china_finance.services.reconciliation.generate_statement`：生成客户、供应商或银行对账快照；
- `china_finance.services.tax_invoice.import_invoices`：幂等导入税务发票；
- `china_finance.services.closing.preview_closing_checks`：预览结账检查；
- `china_finance.services.closing.reopen_closing`：按审计要求重新开账；
- `china_finance.services.archive.verify_archive`：复核档案文件 SHA-256；
- `china_finance.services.archive.export_archive_package`：导出私有电子档案包。

所有批量接口均返回处理数、成功数、跳过数、失败数和逐条错误，不会静默跳过失败记录。

## 旧财务数据核查

管理员可通过 `bench execute china_finance.services.finance_cleanup.preview_finance_cleanup`，按公司及日期只读预览旧凭证、关联记录和清理阻塞项。该命令不提供删除功能。参数、结果说明和后续处理边界见 [旧财务凭证清理预览](docs/旧财务凭证清理.md)。

## 发布约束

应用必须能够进入现有自定义镜像，并兼容服务器既有的 `deploy_akivision_apps.sh` 更新流程。应用代码不得要求在服务器上执行额外手工 SQL、临时补丁或应用外数据修复。

## 许可证

MIT
