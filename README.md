# Custom Filters

`custom_filters` 是面向 Frappe / ERPNext 的综合定制扩展，集中提供列表筛选、桌面交互、订单收发货查询、供应商报价同步、生产计划增强、业务翻译和单点登录等功能。

功能主要嵌入 ERPNext 现有的列表、表单和登录页，通过 [hooks.py](custom_filters/hooks.py) 接入。部分功能会更新采购价格、创建业务单据或在迁移时修复历史数据。

## 功能与使用入口

| 功能 | 使用入口 | 作用 |
| --- | --- | --- |
| 物料组筛选 | 物料（Item）列表 | 选择上级物料组时，查询其下属叶子组的物料；选择叶子组时查询该组物料。 |
| 仓库筛选 | 库存数量（Bin）列表 | 选择上级仓库时，查询其下属叶子仓库的库存。 |
| 销售流程筛选 | 销售订单列表 | 增加“流程状态”筛选，使用站点已有的 `custom_process_status` 字段及其选项。 |
| 仓库库存提示 | 物料需求、库存移动、生产计划 | 仓库下拉选项按公司及非分组仓库过滤，选定物料后显示实际库存数量。 |
| 多标签页 | Desk 顶部 | 支持页面切换、固定标签、关闭其他标签和恢复标签；按站点和用户保存到浏览器。 |
| 快捷导航 | Desk 右侧 | 根据桌面图标生成应用入口，支持文件夹展开和当前页面高亮。 |
| 表格操作 | 表单子表和列表页 | 子表支持拖动列宽、保存用户列宽设置及顶部横向滚动条；列表提供随页面位置调整的横向滚动条。 |
| 销售出货明细 | 销售订单的“出货明细”页签 | 按订单物料展开每次出货，显示订购、已出货、待出货数量和关联交货单。 |
| 采购交货详情 | 采购订单的“交货详情”页签 | 按订单物料展开每次收货，显示订购、已收货、待收货数量和关联采购收货单。 |
| BOM 反查 | 物料的生产页签 → 关联成品 | 查看当前物料被哪些已提交 BOM 使用，以及成品、用量、默认和启用状态。 |
| 阶梯价格查询 | 物料的价格页签 → 阶梯价格表 | 查看物料对应定价规则的数量区间、价格或折扣、适用对象和有效期。 |
| 供应商报价管理 | 供应商报价表单及列表 | 默认仓库回填、提交前价格提示、报价同步及同步状态展示。 |
| 生产计划增强 | 生产计划表单 | 调整物料需求仓库、显示调拨数量、查询实时缺口、创建采购需求和按库存创建工单。 |
| 翻译与菜单调整 | 中文界面、字段说明和桌面头像菜单 | 调整业务术语及说明翻译，隐藏桌面头像菜单中的 About 和 Frappe Support；另包含部分西班牙语翻译。 |
| 单点登录 | 登录页、EIMS 入口 | 将 EIMS 或钉钉身份绑定到已有 ERP 用户并登录。 |

订单明细也提供独立的树形脚本报表，可按名称搜索后选择一张订单查看：

- `Sales Order Shipment Details`（销售订单出货明细）。
- `Purchase Order Delivery Details`（采购订单交货详情）。

当前订单收发货统计使用已提交、数量为正的交货单或采购收货单明细，退货不会作为负数冲减该视图中的累计数量。

## 供应商报价与价格同步

在采购设置（Buying Settings）中配置“供应商报价默认仓库”后，报价明细的空仓库会自动补齐，已有仓库值会保留。

报价提交前，页面会检查与历史报价相比是否涨价、数量档位是否减少，并让用户确认是否继续。检查属于提示功能，检查失败时会提示跳过并继续提交。

报价提交后按物料同步采购价格：

- 同一物料有两个及以上有效数量档位时，生成或更新供应商专属采购定价规则（Pricing Rule）。
- 同一物料只有一个数量档位时，生成或更新供应商物料价格（Item Price），使用报价单或采购设置中的采购价格表，缺省时查找启用的采购价格表。
- 在阶梯价与单档价格之间切换时，会清理或停用本应用自动生成的对应旧价格。
- 同步失败不阻止报价单提交，列表显示“同步失败”；已提交报价单可通过“操作 → 同步阶梯价”重试，该按钮同时处理单档价格。
- 取消报价单时，停用或删除仍归属于该报价单的自动价格，并尝试从同一供应商、匹配公司/币种/采购价格表的上一份已提交报价恢复价格。

这些价格记录会参与 ERPNext 后续采购取价。实现见 [quote_pricing.py](custom_filters/quote_pricing.py) 和 [supplier_quotation_price_check.py](custom_filters/supplier_quotation_price_check.py)。

## 生产计划增强

获取需求物料时，在 ERPNext 原有计算基础上调整目标仓库，优先采用物料在当前公司的默认仓库。采购与调拨同时生成时，同一物料使用统一的接收仓库，保留调拨来源仓库，并显示 `custom_transfer_qty`（调拨数量）。

生产计划提供两个主要操作：

- **查看本计划实时物料缺口**：按物料和仓库汇总 BOM 需求、当前库存、本计划关联的申请余额及采购未入库量；已提交计划可从缺口创建采购需求。
- **按库存创建可生产工单**：选择生产物料、优先级和生产数量，按原材料库存计算可生产数量，扣除已创建工单对应的计划数量，并为工单原材料设置发料仓库。

实时缺口的计算方式为：

```text
计划缺口 = max(BOM 需求数量 − 当前仓库实际库存 − 已申请未下单数量 − 采购未入库数量, 0)
```

当前实现将本计划关联的草稿和已提交物料申请余额都计入“已申请未下单数量”；采购未入库量取自关联的已提交采购订单。创建采购需求后，是否自动提交由生产计划的 `submit_material_request` 设置决定。

## 安装与更新

运行环境需要已安装 ERPNext 的 Frappe Bench。当前代码包含 Frappe v16 桌面适配，[pyproject.toml](pyproject.toml) 声明 Python `>=3.14`。

在 Bench 根目录执行，将占位符替换为实际路径、仓库地址和站点名：

```bash
cd /path/to/frappe-bench
bench get-app <repository-url> --branch main
bench --site <site-name> install-app custom_filters
bench --site <site-name> migrate
bench build --app custom_filters
bench --site <site-name> clear-cache
```

如果应用代码已在 `apps/custom_filters` 中，跳过 `get-app`。更新应用代码后执行：

```bash
bench --site <site-name> migrate
bench build --app custom_filters
bench --site <site-name> clear-cache
```

生产部署按其进程管理方式重启应用服务，浏览器刷新后加载新的前端资源。

### 迁移时的处理

[patches.txt](custom_filters/patches.txt) 登记一次性补丁，[setup.py](custom_filters/custom_filters/setup.py) 的 `after_migrate` 负责重复执行时的字段和状态维护，内容包括：

- 创建用户的 EIMS / 钉钉身份字段、供应商报价默认仓库和价格同步状态字段。
- 增加订单收发货页签、物料 BOM/价格展示字段和生产计划调拨数量字段。
- 调整字段位置及已有用户的生产计划子表列配置。
- 对缺少同步状态的已提交供应商报价补做价格同步。
- 修正部分会计术语翻译，并将匹配历史名称的资产、负债根科目重命名为“资产”“负债”。

翻译包含 `Sales Invoice → 销售应收单`、`Purchase Invoice → 采购应付单`、`Payment Entry → 收付款凭证`、`Journal Entry → 记账凭证` 等。迁移既有界面配置变更，也可能写入价格和科目数据。

## 单点登录配置

安装或更新后先执行 `migrate`，确保 User 上的身份绑定字段已创建。两种登录流程都只登录已启用的现有 ERP 用户，不自动创建 ERP 用户。

### EIMS SSO

在 Desk 创建并启用自定义 `Social Login Key`，填写 EIMS 提供的 Client ID、Client Secret、授权地址、Access Token 地址和 UserInfo 地址（API Endpoint）。回调路径设置为：

```text
/api/method/custom_filters.overrides.oauth.login_via_eims
```

在 EIMS 中登记对应 ERP 域名下的完整回调 URL。EIMS 需支持授权码流程、PKCE S256 和服务端 `client_secret_post` 换取令牌；UserInfo 需返回 `app_user_id`。

应用默认读取名称为 `eims` 的 Social Login Key。使用其他记录名称时配置：

```bash
bench --site <site-name> set-config eims_social_login_key <social-login-key-name>
```

在 ERP 用户的 `custom_eims_app_user_id`（EIMS App User ID）中填写对应的 `app_user_id`。绑定按 ID 匹配，不使用邮箱或手机号替代。

可从登录页进入，也可使用 `/api/method/custom_filters.overrides.oauth.start_eims_login` 发起登录。EIMS 链接可指向 ERP 的 `/?from_eims=1`，未登录用户会进入 EIMS 授权流程。授权状态保存在服务端，使用一次性 state、浏览器 nonce 和 PKCE 校验。

### DingTalk SSO

钉钉使用统一的第三方网站登录流程：Client Secret 保存在服务端，验证一次性 state 和浏览器 nonce 后，通过钉钉 JSON API 交换 `authCode`，再根据 Union ID 或 Open ID 匹配已有 ERP 用户。

在 Desk 创建 `Social Login Key`：

| 字段 | 值 |
| --- | --- |
| Enable Social Login | 启用 |
| Social Login Provider | Custom |
| Provider Name | DingTalk |
| Base URL | `https://login.dingtalk.com` |
| Authorize URL | `https://login.dingtalk.com/oauth2/auth` |
| Access Token URL | `https://api.dingtalk.com/v1.0/oauth2/userAccessToken` |
| Redirect URL | `/api/method/custom_filters.overrides.oauth.login_via_dingtalk` |
| Auth URL Data | `{"scope":"openid","prompt":"consent"}` |

使用钉钉应用的 Client ID/AppKey 和 Client Secret/AppSecret。在钉钉“钉钉登录与分享”设置中登记 ERP 站点的回调域名，并授予读取授权用户个人信息的权限。

应用默认读取名称为 `dingtalk` 的 Social Login Key。使用其他记录名称时配置：

```bash
bench --site <site-name> set-config dingtalk_social_login_key <social-login-key-name>
```

生产使用时，在现有 ERP 用户的 `custom_dingtalk_union_id` 中填写钉钉 Union ID；`custom_dingtalk_open_id` 可用于 Open ID 绑定。登录入口为登录页钉钉按钮或 `/api/method/custom_filters.overrides.oauth.start_dingtalk_login`。

需要首次登录时通过唯一匹配的钉钉邮箱或手机号绑定已有 ERP 用户，可启用以下可选配置；默认不启用，不会创建新用户：

```bash
bench --site <site-name> set-config dingtalk_auto_bind_by_email_or_mobile 1
```

## 代码导航

| 路径 | 内容 |
| --- | --- |
| [custom_filters/hooks.py](custom_filters/hooks.py) | 静态资源、表单/列表脚本、单据事件、接口覆盖和迁移入口。 |
| [custom_filters/public](custom_filters/public) | 桌面交互、业务表单、列表增强的 JS/CSS。 |
| [custom_filters/custom_filters](custom_filters/custom_filters) | 筛选接口、物料与订单查询、脚本报表、迁移后设置。 |
| [custom_filters/quote_pricing.py](custom_filters/quote_pricing.py) | 报价到定价规则及物料价格的同步、取消和回退。 |
| [custom_filters/production_plan.py](custom_filters/production_plan.py) | 生产计划需求物料的仓库选择和库存值刷新。 |
| [custom_filters/production_plan_shortage.py](custom_filters/production_plan_shortage.py) | 实时物料缺口和采购需求创建。 |
| [custom_filters/production_plan_work_order.py](custom_filters/production_plan_work_order.py) | 按库存与生产优先级创建工单。 |
| [custom_filters/overrides/oauth.py](custom_filters/overrides/oauth.py) | EIMS / 钉钉登录、用户绑定和 OAuth 请求日志脱敏。 |
| [custom_filters/patches](custom_filters/patches) | 字段、布局、翻译及历史数据迁移补丁。 |
| [custom_filters/translations](custom_filters/translations) | 中文及部分西班牙语翻译。 |
| [custom_filters/tests](custom_filters/tests) | 登录流程和生产计划相关测试。 |

## 开发与检查

安装 [pre-commit](https://pre-commit.com/#installation) 后，在应用目录启用检查：

```bash
cd apps/custom_filters
pre-commit install
```

[.pre-commit-config.yaml](.pre-commit-config.yaml) 配置了 Ruff、ESLint、Prettier 及基础文件检查。

GitHub Actions 配置见 [.github/workflows](.github/workflows)：`CI` 在推送到 `main` 和创建 Pull Request 时安装应用并运行测试；`Linters` 在 Pull Request 时执行 pre-commit、Frappe Semgrep 规则和 pip-audit。实际检查范围以工作流配置为准。

## 许可证

[MIT](license.txt)
