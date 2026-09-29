# DeepLinkERP 内部 Desk 链接统一路由设计

## 背景与根因

DL 导航复用 Frappe 的 `workspace_sidebar_item` 和 `make_sidebar_item()` 渲染子菜单。部分工作区把本系统地址（例如 `/desk/china-finance`）保存为 `URL` 类型。Frappe 对所有 `URL` 类型统一输出 `target="_blank"`，而其全局路由接管器会主动跳过 `_blank` 链接。因此普通点击会打开新标签页并完整加载 Desk，在加载完成前短暂显示经典 Desktop 图标和品牌启动图。

这个问题不属于中国财务工作台本身；任何被配置为 `URL`、但实际指向当前站点 `/desk` 的菜单都可能发生。

## 已确认方案

在现有 `bindRenderedSidebarLinks(container)` 统一规范化内部 Desk 链接，不创建第二套路由器：

1. 使用纯函数判断链接是否属于当前站点的 `/desk` 路由。
2. 对同源的 `/desk` 链接移除 `_blank`，保留原始 `href`。
3. 点击继续交给 Frappe 已有的 `body` 级路由接管器，由其调用 `frappe.set_route()`。
4. 外部域名、非 Desk 地址以及真正需要新标签页的外部 URL 不变。
5. 浏览器原生 Ctrl/Command 点击仍由 Frappe 放行，可按用户意图打开新标签页。

该规范化同时作用于：

- 当前模块的 Frappe 原生侧栏节点；
- DL 导航从授权快照渲染的其他模块子菜单；
- 一级、二级和三级菜单中的所有 `.item-anchor`。

## 复用与替代关系

- 复用：`bindRenderedSidebarLinks()` 作为唯一菜单链接绑定入口。
- 复用：Frappe `router.js` 已有的同源 `/desk` 点击接管、历史记录、前进后退和 modifier-key 行为。
- 新增：一个可单测的“内部 Desk 路由”判定函数；它只负责分类，不负责导航。
- 不新增：自定义 click-to-route 流程、第二个 router listener、菜单数据修复 API 或数据库迁移。
- 不删除现有 Frappe 兼容代码；现有原生链接关闭移动端侧栏和桌面展开状态保留逻辑继续使用。

## 兼容边界

- 仅当 URL 可解析为当前 origin，且规范化路径为 `/desk` 或以 `/desk/` 开头时才移除 `_blank`。
- `https://external.example/...`、`mailto:`、`tel:`、下载链接和其他非 Desk 路径保持原样。
- 经典模式不渲染 DL 导航，因此不受此次链接规范化影响。
- 直接刷新、复制链接到新标签页或 Ctrl/Command 点击仍会完整加载页面；本次修复的目标是普通左键点击不再被菜单数据中的错误 `_blank` 强制整页打开。

## 测试与验收

自动化测试新增两个独立业务场景：

1. 同源相对或绝对 `/desk` URL 被识别为内部路由，`target="_blank"` 被移除。
2. 外部 URL 和非 Desk 同源 URL 保留原 `target`，不被内部化。

现有导航测试继续验证：路由归属、三级菜单、选中高亮、移动端收起、模式隔离和无重复导航节点。

本地浏览器验收覆盖：

1. 从采购页展开中国财务并点击“中国财务工作台”，仍在当前标签页进入 `/desk/china-finance`。
2. 从至少两个其他模块点击内部 URL 类型子菜单，确认同样使用 SPA 路由。
3. 外部 URL 仍打开新标签页。
4. 前进、后退、刷新后的展开和高亮状态符合既有规则。

## 完成报告要求

实施完成后报告新增、修改、删除、测试变化和未处理技术债；同时给出代码与测试净行数、是否产生重复逻辑，以及本次保留兼容代码的实际调用方和退出条件。
