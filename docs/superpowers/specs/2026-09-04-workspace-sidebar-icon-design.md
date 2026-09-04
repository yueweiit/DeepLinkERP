# 工作区侧栏标题图标统一设计

## 目标

让“海外成本核算”工作区侧栏标题使用 ERP 模块栏中同一份蓝色 SVG 图标，替换当前无法正确显示中文首字“海”的灰色占位图标。

## 现状与原因

- ERP 模块栏从 `frappe.boot.desktop_icons` 的 `icon_image` 渲染蓝色 SVG。
- 工作区侧栏标题由 DeepLinkERP 的公共侧栏组件渲染；`Workspace Sidebar` 顶层没有图片字段，因此回退到 `desktop-alphabet`，生成的 `<use href="#海">` 在当前图标集中不存在。
- 两处属于不同组件，现有工作区 JSON 中的 `icon: calculator` 只描述 Workspace/子链接，不能驱动侧栏标题图片。

## 设计

- 工作台显示时，从 `frappe.boot.desktop_icons` 中按“海外成本核算”找到当前用户已经获授权的桌面入口。
- 优先读取该入口的 `logo_url` 或 `icon_image`，并将同一 URL 渲染到 `.body-sidebar-container .sidebar-header > .sidebar-item-icon`。
- 不新增第二份图片资源，不硬编码未授权模块，也不修改全局侧栏组件。
- 第一次替换前保存标题图标容器原有 HTML；离开工作台时恢复，避免影响其他工作区。
- 页面首次加载和再次显示时都执行同步，以兼容 Frappe 异步重建侧栏。
- 找不到桌面入口、图片字段或标题容器时保持原样，不抛出页面错误。

## 验收

- 工作区标题与左侧 ERP 模块栏显示同一蓝色 SVG。
- ERP 模块栏、工作区折叠按钮和其他模块页面不受影响。
- 自动测试覆盖图标来源、目标选择器和离开页面恢复逻辑。
