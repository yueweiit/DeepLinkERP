# DeepLinkERP 经典 / DL 模式与多分组折叠导航实施计划

> **执行要求：** 实施时必须逐任务使用 `superpowers:test-driven-development`；推荐用 `superpowers:subagent-driven-development`，也可以在当前会话用 `superpowers:executing-plans`。每个任务先写失败测试，再写最小实现，并在提交前运行该任务的聚焦测试。

**目标：** 在不复制 Frappe 菜单、权限和路由逻辑的前提下，增加“公司默认 + 用户覆盖”的经典 / DL 界面模式；同时把 DL 模式的所有带子菜单父级统一改为整行展开/收起、子菜单才导航，并让多个展开状态只在当前页面会话内保留，完整刷新后重置。

**架构：** 服务端新增一个 Single DocType 保存公司默认值，用户覆盖继续使用 Frappe `DefaultValue`。现有 `apply_boot_branding` 仍是唯一 boot 入口，向客户端下发已解析的有效模式。现有品牌生命周期仍是唯一 Desk 事件入口：品牌替换始终执行，DL 导航和紧凑首页只在 DL 模式执行，头像菜单在两种模式下执行。顶层菜单继续来自授权后的 `desktop_icons`，子菜单继续来自授权后的 `workspace_sidebar_item`，路径和 DOM 优先交给 Frappe v16 的 Sidebar item renderer；不增加第二个菜单 API、router listener 或权限判断。

**技术栈：** Frappe / ERPNext v16、Python、vanilla JavaScript、Lucide、CSS、Python `unittest`、Node.js `node:test`、Docker Compose 本地预览。

---

## 复用、替换与退出边界

- 复用 `deeplinkerp_branding.deeplinkerp_branding.branding.apply_boot_branding`，不增加第二个 `boot_session` hook。
- 复用 `frappe.defaults.get_user_default`、`set_user_default`、`clear_user_default`，不向 `User` 增加字段，也不使用浏览器存储保存模式。
- 复用 `desktop_icons`、`workspace_sidebar_item`、`.active-sidebar`、`frappe.ui.Sidebar.prototype.find_nested_items` 和 `frappe.app.sidebar.make_sidebar_item`，不复制 DocType、Report、Workspace、Page、URL 的路径生成规则。
- 复用 `deeplinkerp_branding.js` 中现有一次性路由/页面事件绑定，不创建另一套生命周期。
- 替换当前“只有当前模块可折叠”的 `data-user-collapsed` 单状态模型，改为从旧导航 DOM 提取 `expandedKeys` 与 `collapsedKeys`；旧函数和旧测试在新用例通过后删除，不保留兼容分支。
- 替换当前“带子菜单父级仍是链接”的 DOM：父级整行是 `button`，子菜单叶子才是 `a`。无子菜单的顶层项仍是正常链接。
- 经典模式通过跳过 DL 增强实现，不复制一份“经典导航”。只有以后 Frappe 提供稳定公共扩展点且浏览器验收覆盖完成，才可退出对当前 v16 Sidebar DOM 类名的兼容适配。

## 文件地图

**新增：**

- `deeplinkerp_branding/deeplinkerp_branding/interface_mode.py`：模式校验、公司默认、用户覆盖、boot payload 和保存接口。
- `deeplinkerp_branding/deeplinkerp_branding/doctype/__init__.py`
- `deeplinkerp_branding/deeplinkerp_branding/doctype/deeplinkerp_interface_settings/__init__.py`
- `deeplinkerp_branding/deeplinkerp_branding/doctype/deeplinkerp_interface_settings/deeplinkerp_interface_settings.py`
- `deeplinkerp_branding/deeplinkerp_branding/doctype/deeplinkerp_interface_settings/deeplinkerp_interface_settings.json`：Single DocType。
- `deeplinkerp_branding/translations/zh.csv`：把存储值 `classic` / `dl` 显示为“经典模式” / “DL 模式”。
- `deeplinkerp_branding/public/js/deeplinkerp_interface_mode.js`：可单测的模式读取、保存和头像菜单辅助函数；不绑定第二套生命周期。
- `tests/test_interface_mode.py`：服务端模式与权限测试。
- `tests/test_interface_mode_metadata.py`：DocType 与 Workspace 标准 JSON 合约测试。
- `tests/interface-mode.test.js`：客户端模式与保存流程测试。

**修改：**

- `deeplinkerp_branding/deeplinkerp_branding/branding.py`：把模式 payload 接入现有 boot 尾部。
- `deeplinkerp_branding/deeplinkerp_branding/workspace/deeplinkerp_settings/deeplinkerp_settings.json`：增加“界面与导航”快捷入口。
- `deeplinkerp_branding/public/js/deeplinkerp_navigation.js`：授权子菜单映射、父级整行切换、会话内展开状态。
- `deeplinkerp_branding/public/js/deeplinkerp_branding.js`：模式门控、头像菜单挂载、所有父分支渲染。
- `deeplinkerp_branding/public/css/deeplinkerp_navigation.css`：父级箭头、菜单和经典 / DL 作用域样式。
- `deeplinkerp_branding/hooks.py`：新增 helper 资源并更新 cache-busting 版本。
- `tests/test_boot_branding.py`：boot 集成与原权限结果回归。
- `tests/navigation-model.test.js`：导航模型、父级交互、展开状态和渲染复用测试。

**删除 / 替换：**

- 删除 `collectUserCollapsedKeys`、`applyUserCollapsedState` 及“inactive routed parent retains normal navigation”等旧行为测试。
- 不保留已删除的 `2026-09-29-navigation-chevron-interaction*` 文档或对应的“文字跳转、箭头单独折叠”实现。

---

### 任务 1：用测试锁定服务端模式解析与用户写入权限

**文件：**

- 新增：`tests/test_interface_mode.py`
- 新增：`deeplinkerp_branding/deeplinkerp_branding/interface_mode.py`

- [ ] **步骤 1：先写失败的纯单元测试**

在 `tests/test_interface_mode.py` 用最小 fake `frappe` 覆盖下列独立场景：

1. 公司设置不存在或值非法时回退 `dl`。
2. 公司为 `classic` 且用户无覆盖时，有效模式为 `classic`。
3. 用户 `dl` / `classic` 覆盖优先于公司默认。
4. 非法存量用户值按“无覆盖”处理。
5. `set_user_navigation_mode("follow_company")` 调用 `frappe.defaults.clear_user_default`，目标只能是 `frappe.session.user`。
6. 保存 `classic` / `dl` 调用 `frappe.defaults.set_user_default`，并返回新的完整 payload。
7. 非法参数抛出 `frappe.ValidationError`；Guest 抛出 `frappe.PermissionError`。
8. `Administrator` 和含 `System Manager` 角色的用户返回 `can_manage_company_default=true`，普通用户返回 false。

测试直接导入生产模块并断言常量：

```python
MODE_SETTING_DOCTYPE = "DeepLinkERP Interface Settings"
USER_OVERRIDE_KEY = "deeplinkerp_navigation_mode_override"
VALID_MODES = {"classic", "dl"}
```

- [ ] **步骤 2：运行测试并确认 RED**

```bash
python3 -m unittest -v tests.test_interface_mode
```

预期：因为 `interface_mode.py` 尚不存在而失败。

- [ ] **步骤 3：实现最小服务模块**

在 `interface_mode.py` 只提供以下职责：

```python
def normalize_mode(value): ...
def get_company_default_mode(): ...
def get_user_override(user=None): ...
def resolve_effective_mode(company_default, user_override): ...
def can_manage_company_default(user=None): ...
def get_interface_mode_payload(user=None): ...
def apply_interface_mode_bootinfo(bootinfo): ...

@frappe.whitelist()
def set_user_navigation_mode(mode): ...
```

规则必须是：

- 公司值从 `frappe.db.get_single_value("DeepLinkERP Interface Settings", "default_navigation_mode")` 读取。
- DocType 尚未同步、记录不存在或值非法均回退 `dl`，不能阻断 Desk boot。
- 用户值只通过 `frappe.defaults` 读取和写入；接口不接受 `user` 参数。
- `follow_company` 清除当前用户默认值；`classic` / `dl` 写入当前用户默认值。
- payload 固定为 `company_default`、`user_override`、`effective_mode`、`can_manage_company_default` 四个字段。

- [ ] **步骤 4：运行聚焦测试并确认 GREEN**

```bash
python3 -m unittest -v tests.test_interface_mode
python3 -m compileall -q deeplinkerp_branding tests
```

- [ ] **步骤 5：提交服务端领域逻辑**

```bash
git add tests/test_interface_mode.py \
  deeplinkerp_branding/deeplinkerp_branding/interface_mode.py
git commit -m "增加界面模式解析与用户覆盖服务"
```

### 任务 2：增加公司默认设置并复用现有设置工作区

**文件：**

- 新增：`tests/test_interface_mode_metadata.py`
- 新增：`deeplinkerp_branding/deeplinkerp_branding/doctype/__init__.py`
- 新增：`deeplinkerp_branding/deeplinkerp_branding/doctype/deeplinkerp_interface_settings/__init__.py`
- 新增：`deeplinkerp_branding/deeplinkerp_branding/doctype/deeplinkerp_interface_settings/deeplinkerp_interface_settings.py`
- 新增：`deeplinkerp_branding/deeplinkerp_branding/doctype/deeplinkerp_interface_settings/deeplinkerp_interface_settings.json`
- 新增：`deeplinkerp_branding/translations/zh.csv`
- 修改：`deeplinkerp_branding/deeplinkerp_branding/workspace/deeplinkerp_settings/deeplinkerp_settings.json`

- [ ] **步骤 1：写标准 JSON 合约测试**

`tests/test_interface_mode_metadata.py` 读取两个 JSON 并断言：

- DocType 名称为 `DeepLinkERP Interface Settings`、`issingle=1`、module 为 `Deeplinkerp Branding`。
- 只有一个业务字段 `default_navigation_mode`，fieldtype 为 `Select`，options 同时包含 `dl`、`classic`，default 为 `dl`，reqd 为 1。
- permissions 只有 `System Manager`，具备 read/write/create。
- 中文翻译文件包含 `classic`→“经典模式”、`dl`→“DL 模式”和设置页字段标签，存储值不因翻译改变。
- `Deeplinkerp Settings` Workspace 的 `shortcuts` 和 `content` 都只出现一次“界面与导航”，目标为该 Single DocType。
- 原有设置快捷入口仍保留，避免用整体重写丢失现有能力。

- [ ] **步骤 2：运行并确认 RED**

```bash
python3 -m unittest -v tests.test_interface_mode_metadata
```

预期：新 DocType 文件和快捷入口不存在。

- [ ] **步骤 3：创建 Single DocType 和控制器**

控制器保持最小：

```python
from frappe.model.document import Document

class DeepLinkERPInterfaceSettings(Document):
    pass
```

JSON 使用 Frappe 标准 Single DocType 结构；字段存储值严格为 `dl` / `classic`，中文显示通过 `translations/zh.csv` 提供。不要向 `System Settings`、`User` 或数据库补丁写自定义字段。

- [ ] **步骤 4：向现有 Workspace 追加一个快捷入口**

在 `shortcuts` 追加：

```json
{
  "color": "Blue",
  "doc_view": "Form",
  "label": "界面与导航",
  "link_to": "DeepLinkERP Interface Settings",
  "type": "DocType"
}
```

同步更新 `content` 中的 shortcut block；不改原快捷入口顺序和管理员角色。

- [ ] **步骤 5：运行测试并提交元数据**

```bash
python3 -m unittest -v tests.test_interface_mode_metadata
python3 -m json.tool \
  deeplinkerp_branding/deeplinkerp_branding/doctype/deeplinkerp_interface_settings/deeplinkerp_interface_settings.json \
  >/dev/null
python3 -m json.tool \
  deeplinkerp_branding/deeplinkerp_branding/workspace/deeplinkerp_settings/deeplinkerp_settings.json \
  >/dev/null
git diff --check
git add tests/test_interface_mode_metadata.py \
  deeplinkerp_branding/deeplinkerp_branding/doctype \
  deeplinkerp_branding/deeplinkerp_branding/workspace/deeplinkerp_settings/deeplinkerp_settings.json \
  deeplinkerp_branding/translations/zh.csv
git commit -m "增加公司默认界面模式设置"
```

### 任务 3：把有效模式接入现有 boot，而不改变原权限过滤结果

**文件：**

- 修改：`tests/test_boot_branding.py`
- 修改：`deeplinkerp_branding/deeplinkerp_branding/branding.py`

- [ ] **步骤 1：扩展 boot 集成测试**

给 fake `frappe` 补齐 `db.get_single_value` 与 `defaults.get_user_default`，新增断言：

- 普通用户、System Manager、Administrator 的 `bootinfo["deeplinkerp_interface_mode"]` 都存在且字段完整。
- 用户覆盖优先级正确。
- 设置 DocType 缺失时 `apply_boot_branding` 仍完成现有 desktop/sidebar 权限过滤并返回 `dl`。
- 原有 4 个权限测试的可见菜单、顺序和 blocked module 结果完全不变。

- [ ] **步骤 2：运行并确认 RED**

```bash
python3 -m unittest -v tests.test_boot_branding
```

预期：bootinfo 尚无 `deeplinkerp_interface_mode`。

- [ ] **步骤 3：在唯一 boot hook 尾部调用共享函数**

在 `apply_boot_branding(bootinfo)` 完成现有授权过滤后调用：

```python
from deeplinkerp_branding.deeplinkerp_branding.interface_mode import (
    apply_interface_mode_bootinfo,
)

apply_interface_mode_bootinfo(bootinfo)
```

不要新增 hook，不要在客户端重新计算权限或优先级。

- [ ] **步骤 4：运行全部 Python 测试并提交**

```bash
python3 -m unittest -v \
  tests.test_interface_mode \
  tests.test_interface_mode_metadata \
  tests.test_boot_branding
git add tests/test_boot_branding.py \
  deeplinkerp_branding/deeplinkerp_branding/branding.py
git commit -m "在现有启动数据中下发界面模式"
```

### 任务 4：增加可测试的客户端模式模块和头像菜单

**文件：**

- 新增：`tests/interface-mode.test.js`
- 新增：`deeplinkerp_branding/public/js/deeplinkerp_interface_mode.js`
- 修改：`deeplinkerp_branding/public/js/deeplinkerp_branding.js`
- 修改：`deeplinkerp_branding/public/css/deeplinkerp_navigation.css`

- [ ] **步骤 1：写客户端失败测试**

新测试通过 CommonJS 导入 `deeplinkerp_interface_mode.js`，覆盖：

1. 缺失 boot payload时安全回退 DL。
2. `effective_mode=classic` 与 `dl` 的判断。
3. 菜单选项固定为 `follow_company`、`classic`、`dl`，并正确标记当前个人覆盖和公司默认。
4. 保存参数只包含 `mode`，方法固定为 `deeplinkerp_branding.deeplinkerp_branding.interface_mode.set_user_navigation_mode`。
5. RPC 成功后调用一次 `location.reload()`；失败时不刷新并把错误交给调用方显示。
6. 菜单挂载幂等，重复刷新不重复创建节点或点击监听器。
7. 原头像按钮的 inline `onclick` 被移除，“个人资料”菜单项仍调用 `frappe.ui.toolbar.route_to_user()`。
8. 经典模式不调用 `renderPersistentNavigation()` / `enhanceDesktopIcons()`，不生成 DL root/body class，也不触碰 `custom_filters` 的原生栏位。

- [ ] **步骤 2：运行并确认 RED**

```bash
node --test tests/interface-mode.test.js
```

- [ ] **步骤 3：实现无生命周期的 helper 模块**

模块只导出模式规范化、菜单模型、保存动作和幂等挂载函数；不监听 router。菜单 DOM 要求：

- 使用 `role="menu"` / `role="menuitemradio"` 和 `aria-checked`。
- 支持 Enter、Space、Escape、外部点击关闭。
- 菜单展示“跟随公司默认（当前：经典模式 / DL 模式）”。
- 保存期间禁用三个选择；成功提示后刷新当前 URL，失败恢复可用状态且不修改 boot payload。
- 两种模式都能找到 `.sidebar-user-button`；移除其原 inline profile 跳转，把 profile 行放到菜单底部。

- [ ] **步骤 4：在现有品牌生命周期中调用它**

`refreshDeskEnhancements()` 顺序改为：

```javascript
patchSidebarSubtitle();
applyBranding();
DeepLinkERPInterfaceMode.ensureUserMenu(...);
if (DeepLinkERPInterfaceMode.isDLMode(frappe.boot)) {
    renderPersistentNavigation();
    enhanceDesktopIcons();
} else {
    disableDLEnhancements();
}
```

`disableDLEnhancements()` 只清理可能残留的 DL body/sidebar classes 和自建 root；不复制或重建 Frappe 原生导航。正常切换依靠整页刷新，从干净 DOM 启动。

- [ ] **步骤 5：加入两种模式都可见的头像菜单样式**

头像菜单选择器不能依赖 `body.dlp-mes-navigation-enabled`。DL 导航和首页样式仍必须全部受该 body class 限定，防止经典模式被污染。

- [ ] **步骤 6：运行聚焦测试并提交**

```bash
node --test tests/interface-mode.test.js
node --check deeplinkerp_branding/public/js/deeplinkerp_interface_mode.js
node --check deeplinkerp_branding/public/js/deeplinkerp_branding.js
git diff --check
git add tests/interface-mode.test.js \
  deeplinkerp_branding/public/js/deeplinkerp_interface_mode.js \
  deeplinkerp_branding/public/js/deeplinkerp_branding.js \
  deeplinkerp_branding/public/css/deeplinkerp_navigation.css
git commit -m "增加经典与DL模式客户端切换"
```

### 任务 5：用 DOM 会话状态替换“仅当前模块可折叠”逻辑

**文件：**

- 修改：`tests/navigation-model.test.js`
- 修改：`deeplinkerp_branding/public/js/deeplinkerp_navigation.js`

- [ ] **步骤 1：先把旧行为测试改成新规则**

删除以下旧期望：

- “inactive routed parent retains normal navigation”——它与新规则直接冲突。
- “switching modules discards collapse”——刷新前应保留多个分支。

新增失败测试：

1. 任意带子菜单父级点击整行时 `preventDefault`，只切换 `aria-expanded`、`hidden` 和 open class，绝不调用移动端 close 或导航行为。
2. 图标、文字和箭头都在同一个 button 内，因此事件统一冒泡到父 button。
3. 无子菜单父级仍绑定原路由行为，移动端点击后关闭侧栏。
4. `collectDisclosureState` 同时返回展开 key 与用户明确收起 key。
5. 重渲染时保留采购、生产两个展开 key，并自动加入刚通过子菜单进入的项目模块。
6. 用户明确收起当前模块后，同一路由上的异步重渲染不能把它重新打开。
7. 没有旧导航 DOM 时只按模型的当前模块 `item.isOpen` 初始化，模拟整页刷新重置。

- [ ] **步骤 2：运行并确认 RED**

```bash
node --test tests/navigation-model.test.js
```

- [ ] **步骤 3：实现新的 disclosure helpers**

新增并导出：

```javascript
function collectDisclosureState(navigation) {
    return { expandedKeys: new Set(), collapsedKeys: new Set() };
}

function resolveItemOpen(item, disclosureState) {
    if (disclosureState.collapsedKeys.has(item.key)) return false;
    if (disclosureState.expandedKeys.has(item.key)) return true;
    return Boolean(item.isOpen);
}
```

父级点击时同步 group DOM marker；打开删除 collapsed、写 open，收起删除 open、写 collapsed。状态只存在于当前 `.dlp-mes-navigation` DOM，禁止写 `localStorage`、cookie 或数据库。

删除 `collectUserCollapsedKeys`、`applyUserCollapsedState` 及 `route && !itemIsOpen` 旧分支。

- [ ] **步骤 4：使所有有授权子项的模块都成为可展开父级**

`buildNavigationModel()` 给每个匹配的顶层节点附加：

```javascript
node.workspaceSidebar = nativeSidebar;
node.hasNativeChildren = Boolean(nativeSidebar?.items?.length);
```

保持 `workspace_sidebar_item` 原对象不被修改。没有授权子项时 `hasNativeChildren=false`，即使有父路由也按叶子链接处理。

- [ ] **步骤 5：运行测试并提交状态模型**

```bash
node --test tests/navigation-model.test.js
node --check deeplinkerp_branding/public/js/deeplinkerp_navigation.js
git add tests/navigation-model.test.js \
  deeplinkerp_branding/public/js/deeplinkerp_navigation.js
git commit -m "统一父级展开交互与会话状态"
```

### 任务 6：让未进入的模块也能显示授权子菜单

**文件：**

- 修改：`tests/navigation-model.test.js`
- 修改：`deeplinkerp_branding/public/js/deeplinkerp_branding.js`

- [ ] **步骤 1：添加失败的渲染复用合约测试**

测试要求：

- 当前模块仍移动并复用唯一的 live `.sidebar-items` 节点，节点 identity 不变。
- 非当前模块从自己的 `item.workspaceSidebar.items` 渲染，不借用当前模块子菜单。
- 渲染前 clone item 数据，并通过 `frappe.ui.Sidebar.prototype.find_nested_items.call(tempContext)` 建立 Section Break/nested_items；boot 原数据不被写入 `parent`、`nested_items`。
- 每个 item 通过现有 `frappe.app.sidebar.make_sidebar_item({container, item})` 生成；生产代码中不得出现自写 `switch (link_type)` 或重复 `generate_route`。
- 重复 refresh 后自建导航 root 始终只有一个，任一子菜单 DOM 只出现一次。
- 不在 `desktop_icons` 或 `workspace_sidebar_item` 之外引入未知菜单。

- [ ] **步骤 2：运行并确认 RED**

```bash
node --test tests/navigation-model.test.js
```

- [ ] **步骤 3：把父级 DOM 改成整行 button**

`makeNavigationRow()` 必须遵循：

- `hasChildren=true`：创建一个 `.dlp-mes-navigation__row` button，不写 `href`，设置 `aria-expanded`；图标、文字和箭头 span 都放在 button 内。
- `hasChildren=false` 且有 route：创建 anchor，维持原移动端 close 与桌面展开保持行为。
- 箭头是视觉子元素，不再绑定独立 click handler；其尺寸仍为约 18px，尾部区域约 36px，整行最小高度 40px。

- [ ] **步骤 4：用 Frappe renderer 创建非当前模块分支**

新增局部函数：

```javascript
function cloneSidebarItems(items) { ... }
function prepareSidebarItems(items) { ... }
function renderWorkspaceSidebarBranch(item, container) { ... }
```

实现约束：

- `structuredClone` 不可用时使用 JSON-safe clone；源 boot 数据绝不变更。
- `prepareSidebarItems` 调用 Frappe 自带 `find_nested_items`，不复制其 Section Break 算法。
- `renderWorkspaceSidebarBranch` 对准备后的每个 item 调用 `frappe.app.sidebar.make_sidebar_item`。
- 当前 `nativeHostKey` 分支仍 append live `nativeItems`；其他父级使用自己的 boot items。
- 叶子点击沿用 Frappe 原生 handler；只额外补现有移动端 sidebar close 和 active accessibility，不重写路由。

- [ ] **步骤 5：重渲染时传递 disclosure state**

在替换旧 root 前读取 `{expandedKeys, collapsedKeys}`，新 root 中逐项调用 `resolveItemOpen`。旧 DOM 不存在时传空集合，因此完整刷新只打开 `buildNavigationModel()` 标记的当前模块。

- [ ] **步骤 6：运行测试并提交**

```bash
node --test tests/navigation-model.test.js
node --test tests/interface-mode.test.js
node --check deeplinkerp_branding/public/js/deeplinkerp_branding.js
git diff --check
git add tests/navigation-model.test.js \
  deeplinkerp_branding/public/js/deeplinkerp_branding.js
git commit -m "投影所有授权工作区子菜单"
```

### 任务 7：完成视觉规格、经典模式隔离和资源版本

**文件：**

- 修改：`tests/navigation-model.test.js`
- 修改：`tests/interface-mode.test.js`
- 修改：`deeplinkerp_branding/public/css/deeplinkerp_navigation.css`
- 修改：`deeplinkerp_branding/hooks.py`

- [ ] **步骤 1：添加 CSS 与资源顺序失败测试**

断言：

- DL 父级整行 40px、圆角 6–8px、hover `rgba(255,255,255,.08)`、focus-visible 描边。
- 箭头视觉区域宽高 36px，SVG 约 18px，颜色不低于 `#c7d4e3`，展开时白色。
- 选中叶子整行 `#1677ff` 且文字/图标白色。
- 除头像模式菜单外，所有 DL shell / desktop grid 规则都以 `body.dlp-mes-navigation-enabled` 开头。
- 新 helper 脚本排在 branding lifecycle 之前；最终顺序为 navigation model、interface mode helper、branding lifecycle。
- 资源 query 版本全部上调，避免旧浏览器缓存。

- [ ] **步骤 2：运行并确认 RED**

```bash
node --test tests/navigation-model.test.js tests/interface-mode.test.js
```

- [ ] **步骤 3：实现视觉和作用域**

保留现有 220px 展开宽度与移动端契约。父级 button 整行可点，箭头区域视觉上更亮、更大，但不创建嵌套 button。头像菜单使用独立 `.dlp-interface-mode-menu` 命名空间，经典模式下仍可见。

- [ ] **步骤 4：更新 hooks 资源**

目标结构：

```python
app_include_css = "/assets/deeplinkerp_branding/css/deeplinkerp_navigation.css?v=0.0.6"
app_include_js = [
    "/assets/deeplinkerp_branding/js/deeplinkerp_navigation.js?v=0.0.7",
    "/assets/deeplinkerp_branding/js/deeplinkerp_interface_mode.js?v=0.0.1",
    "/assets/deeplinkerp_branding/js/deeplinkerp_branding.js?v=0.0.13",
]
```

- [ ] **步骤 5：运行全部静态与单元测试并提交**

```bash
node --test tests/navigation-model.test.js tests/interface-mode.test.js
python3 -m unittest -v \
  tests.test_interface_mode \
  tests.test_interface_mode_metadata \
  tests.test_boot_branding
node --check deeplinkerp_branding/public/js/deeplinkerp_navigation.js
node --check deeplinkerp_branding/public/js/deeplinkerp_interface_mode.js
node --check deeplinkerp_branding/public/js/deeplinkerp_branding.js
python3 -m compileall -q deeplinkerp_branding tests
git diff --check
git add tests deeplinkerp_branding/hooks.py \
  deeplinkerp_branding/public/css/deeplinkerp_navigation.css
git commit -m "完成DL手风琴导航视觉与模式隔离"
```

### 任务 8：在全新本地镜像中迁移并验证，而不是覆盖运行容器

**文件：** 仅验证；预期不改源码。

- [ ] **步骤 1：记录测试基线与工作树状态**

```bash
git status --short --branch
node --test tests/navigation-model.test.js tests/interface-mode.test.js
python3 -m unittest -v \
  tests.test_interface_mode \
  tests.test_interface_mode_metadata \
  tests.test_boot_branding
```

预期：所有测试通过，工作树只包含已计划且未提交的变化；若有无关变化先停止并核对，不覆盖。

- [ ] **步骤 2：从独立工作树构建预览镜像**

在 `/Users/smk/.codex/worktrees/mes-navigation/DeepLinkERP` 运行：

```bash
docker build --platform linux/amd64 \
  -f /tmp/Dockerfile.deeplinkerp-mes-nav \
  -t overseas-cost-local:mes-nav-preview .
```

预期：构建成功。构建期因未连接 Redis 出现的 asset-manifest warning 可记录但不能误报为运行验证通过。

- [ ] **步骤 3：只重建预览应用服务并执行 migrate**

在 `/Users/smk/Documents/ChatGPT/综合成本计算系统-local-env/frappe_docker` 运行：

```bash
docker compose -p overseas-cost-local \
  -f pwd.yml -f compose.local.yaml -f /tmp/compose.deeplinkerp-mes-nav.yaml \
  up -d --no-deps --force-recreate \
  backend frontend websocket queue-short queue-long scheduler
docker exec overseas-cost-local-backend-1 bench --site frontend migrate
docker exec overseas-cost-local-backend-1 bench --site frontend clear-cache
```

预期：新 Single DocType 与 Workspace JSON 同步成功；数据库、Redis volume 不重建；六个应用服务均为 `Up`。

- [ ] **步骤 4：做服务端现场检查**

```bash
docker exec overseas-cost-local-backend-1 \
  bench --site frontend execute frappe.client.get \
  --kwargs "{'doctype':'DeepLinkERP Interface Settings','name':'DeepLinkERP Interface Settings'}"
docker compose -p overseas-cost-local \
  -f pwd.yml -f compose.local.yaml -f /tmp/compose.deeplinkerp-mes-nav.yaml \
  ps
curl -I http://localhost:64115/login
```

预期：Single DocType 可读取、默认值为 `dl`、站点返回正常 HTTP 响应。

### 任务 9：浏览器端到端验收

**文件：** 仅验证；发现缺陷时回到对应任务先补失败测试再修复。

- [ ] **步骤 1：管理员验证公司默认与两个模式**

在 `http://localhost:64115` 用 Administrator：

1. 从 `Deeplinkerp Settings` 打开“界面与导航”。
2. 把公司默认切为经典，保存并刷新当前 URL；确认原生 Frappe 侧栏/Desk 首页存在，没有 `.dlp-mes-navigation` 或 DL body class。
3. 左下角头像菜单选择 DL；保存成功后只刷新一次且 URL 不变；确认深蓝统一侧栏和紧凑首页恢复。
4. 选择“跟随公司默认”，确认回到经典；再把公司默认改回 DL，作为最终本地默认值。

- [ ] **步骤 2：普通用户验证覆盖与权限**

用本地普通用户验证：

- 看不到管理员设置入口，不能通过 URL 保存公司默认。
- 默认跟随公司；可选择 classic / dl；完整刷新和重新登录后个人偏好仍在。
- 用户保存接口不能指定或修改其他用户。
- 无权限模块及其子项在两种模式都不出现。

- [ ] **步骤 3：验证 DL 父级规则适用于所有模块**

在 1280×800：

1. 依次点击采购、生产、项目和至少一个其他有子菜单模块的图标、文字、箭头区域；每次只展开或收起，URL 不变。
2. 同时保持采购、生产、项目展开；确认没有重复子菜单。
3. 点击采购的一个子菜单后才导航；生产和项目继续展开。
4. 使用浏览器前进/后退与深链接，当前叶子高亮正确。
5. 完整刷新后只展开当前页面所属模块；此前其他展开模块全部重置。
6. 无子菜单顶层入口仍直接导航。
7. 箭头区域约 36×36px、图标约 18px，未展开也清晰；Tab、Enter、Space 和 focus ring 可用。

- [ ] **步骤 4：验证移动端与溢出**

在 375px 和平板宽度验证：

- 父级展开不会关闭整栏；子菜单导航后按原生契约关闭移动侧栏。
- 遮罩、汉堡按钮和桌面收栏功能不变。
- `document.documentElement.scrollWidth === document.documentElement.clientWidth`。
- 头像菜单不超出视口，Escape 和点外关闭有效。

### 任务 10：复核、清理与交付报告

**文件：** 按复核结果决定；禁止为“让测试通过”保留重复实现。

- [ ] **步骤 1：运行完整验证**

```bash
node --test tests/navigation-model.test.js tests/interface-mode.test.js
python3 -m unittest -v \
  tests.test_interface_mode \
  tests.test_interface_mode_metadata \
  tests.test_boot_branding
node --check deeplinkerp_branding/public/js/deeplinkerp_navigation.js
node --check deeplinkerp_branding/public/js/deeplinkerp_interface_mode.js
node --check deeplinkerp_branding/public/js/deeplinkerp_branding.js
python3 -m compileall -q deeplinkerp_branding tests
git diff --check
```

- [ ] **步骤 2：做 reuse-first 重复逻辑审计**

```bash
rg -n "generate_route|link_type.*switch|localStorage.*navigation|deeplinkerp_navigation_mode_override|router\.on" \
  deeplinkerp_branding tests
```

验收：

- 没有第二套菜单 API、route type switch、权限判断或 router listener。
- 用户模式 key 只在服务端共享模块和对应测试出现；菜单展开状态没有持久化。
- 旧 collapse helper、旧冲突测试与旧设计文档均不存在。

- [ ] **步骤 3：进行代码审查并修复问题**

使用 `superpowers:requesting-code-review` 检查权限绕过、Guest 行为、重复 DOM/listener、boot 容错、经典模式污染和移动端回归。任何修复都先添加能复现问题的测试。

- [ ] **步骤 4：记录最终统计**

```bash
git status --short --branch
git diff --numstat 4415dd2..HEAD
git diff --name-status 4415dd2..HEAD
git log --oneline 4415dd2..HEAD
```

最终报告必须分别列出：

- 新增、修改、删除的文件和用户行为。
- Python 业务场景数、Node 前端场景数、框架展开场景数，以及完整命令结果。
- 代码 / 测试 / 配置净行数变化。
- 复用了哪些 Frappe / DeepLinkERP 能力，是否仍存在重复菜单、路由或权限逻辑。
- 保留的兼容代码、明确删除条件。
- 未处理技术债，至少说明对 Frappe v16 Sidebar DOM 类名和非公开 renderer 的依赖。
- 本地 `http://localhost:64115` 的管理员、普通用户、桌面和平板/手机验收结果；明确说明未部署服务器。
