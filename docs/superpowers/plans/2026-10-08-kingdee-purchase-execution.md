# 金蝶式采购实施检查表

批准范围：钉钉可靠来源生成原生订单草稿、人工审核、逐单/合并入库、单独确认应付与部分/合并付款。采购主表仅真实订单，缺项来源在同页待完善标签。内部 WMS 复用原生库存。生产测试不提交业务单据。

基线：`336c7054fbf7f4bfdfe459020ea5e677d556db60`；分支 `codex/kingdee-purchase-flow`。复用本对话已有干净工作树，不复制旧采购实现。

## 实施顺序

- [x] 核对 Branding 远端与 Vultr 当前 image，协调唯一发布负责人。
- [x] 采购 JS 基线：128 个测试通过；不将旧 QA 报告算作当前验证。
- [ ] 替换 Redis 唯一结果缓存为共用、持久化 Integration Request 操作边界；原生入口/同步冲销/日志和提交前校验。
- [ ] 扩展既有原生转换和付款服务支持同主体合并；整批事务/来源行/当前余量与权限。
- [ ] 可靠钉钉来源自动草稿；不足字段保持待完善，人工值与历史付款保护不变。
- [ ] 复用紧凑列表与付款抽屉：真实 rowspan 明细、整单选择、订单/待完善标签、统一偏好迁移、集中动作。
- [ ] 分别进行规格审查、质量审查，修复后复审。
- [ ] 新的独立本地 Compose 数据库运行真实控制器故障注入、回滚/幂等及浏览器流程；不改变其他 QA 环境。
- [ ] 专项、全量、语法、资源/CI 检查；独立交付联动清单、校验点、测试结果与代码统计。
- [ ] 交给已协调的唯一发布负责人串行 Vultr 发布；核验 SHA、缓存、健康及线上只读操作。

## 复用与兼容

复用 purchase_document_actions、purchase_payment_service、purchase_source_service、compact_list、purchase_payments 与 ERPNext/中国财务原生服务。移除被替换的采购 Redis-only 事务实现和旧采购组合单元格默认值，不保留第二条采购联动逻辑。其他模块仍调用共用表格/抽屉，配置隔离保留其真实功能；保留标准表单及已保存草稿办理入口。所有动态钩子和外部调用须重新核对后才可删除。运营对话的共享文件改动按实际候选 SHA 串行合并，不覆盖。

严格边界：无关联模块记录不适用；不生成虚构销售/运营分摊，不新增库存流水，不修改盘点快照/公司自动应付配置，不写钉钉/WMS/银行外部系统。成功日志随事务，失败结构化运行日志独立留存。所有正式金额/数量使用原生精度。

## 已执行基线（不是最终验收）

- `node --test tests/*.test.js`：475 通过，零失败/跳过。采购专项子集 128 通过。
- 初始化 Frappe 后，actions/payment links/source service 的原有单元测试：126 通过。
- `python3 -m unittest -q tests.test_purchase_source_contract tests.test_unified_purchase_release tests.test_purchase_order_assets`：69 通过。
- `test_procurement_integration_qa.execute()`：7 个原生场景通过；最终 PO139、PR114、PI5、PE6、GL16、Payment Ledger8、User6、User Permission3 未变化。对齐当前财务服务后再次通过。
- 测试库只从本地合成库复制，不复制线上业务数据。独立 Compose 项目 `dlp-kingdee-purchase-qa`，`127.0.0.1:64248`，站点 `po-grid-qa.localhost`，数据库 `qa_procurement_5`，独立持久卷。
- 初始本地中国财务 voucher.py 与线上版本不一致，已只读复制线上 `4f019f91f36aa549df1854d2df0b60e20c01751c` 包到独立 QA。voucher.py SHA256 `bf91a573a920cabb810161cd893d78fdc4044d760611b6fc43522986ef43038e`，auto_invoice.py SHA256 `14fb90b7a55ed385bd4147e3879b0ce0e540d71e682091206fca12fcc0db5a6d`。生产未改动。
- 全应用 migrate 在原有 Overseas workspace 的 `Overseas Cost ERP Settings` 链接处失败；未修改该无关模块。Branding/Finance 相关 schema 与三个安装钩子单独完成。发布必须沿用现有窄范围元数据工具，不能把这个 migrate 记为通过。
- 全 Python 基线最初缺 pytest；补齐后曾因 QA 服务工作目录调整而被中断，尚未计入通过。最终需完整重跑。
- `bench build --app deeplinkerp_branding` 完成，带既有 Browserslist 数据过期提示；后续前端变更仍需重新构建与真实页面验收。
