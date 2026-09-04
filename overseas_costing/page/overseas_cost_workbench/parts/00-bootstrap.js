frappe.pages["overseas-cost-workbench"] = frappe.pages["overseas-cost-workbench"] || {};

function hideDeskChromeWhenReady(workbench) {
  workbench.hideDeskChrome();
  requestAnimationFrame(() => workbench.hideDeskChrome());
  window.setTimeout(() => {
    if (!$(workbench.wrapper).is(":visible")) return;
    workbench.hideDeskChrome();
    ensureDeskModuleSidebar(workbench);
  }, 300);
}

function ensureDeskModuleSidebar(workbench) {
  // DeeplinkERP 将授权后的模块图标放在这个独立容器。
  // .body-sidebar-container 是工作区内部侧栏，不是 ERP 模块栏。
  const $nativeSidebar = $(".custom-filters-right-sidebar-container").first();
  if ($nativeSidebar.length) {
    if (!workbench._erpModuleSidebarSnapshot) {
      workbench._erpModuleSidebarSnapshot = {
        element: $nativeSidebar.get(0),
        display: $nativeSidebar.get(0).style.display,
        visibility: $nativeSidebar.get(0).style.visibility,
        opacity: $nativeSidebar.get(0).style.opacity,
      };
    }
    $nativeSidebar.css({ display: "", visibility: "visible", opacity: "1" });
    $("#ocw-erp-module-sidebar-fallback").remove();
    $("body").removeClass("ocw-has-erp-module-sidebar-fallback");
    return;
  }
}

frappe.pages["overseas-cost-workbench"].on_page_load = function (wrapper) {
  const workbench = new OverseasCostWorkbench(wrapper);
  frappe.pages["overseas-cost-workbench"].workbench = workbench;
  workbench.init();
  ensureDeskModuleSidebar(workbench);
  hideDeskChromeWhenReady(workbench);
  // 离开工作台时恢复桌面外壳（侧栏 / 顶部标签栏 / 右侧栏），避免影响其它页面。
  $(wrapper).on("hide", function () {
    workbench.restoreDeskChrome();
  });
};

frappe.pages["overseas-cost-workbench"].on_page_show = function () {
  const workbench = frappe.pages["overseas-cost-workbench"].workbench;
  if (!workbench) return;
  ensureDeskModuleSidebar(workbench);
  hideDeskChromeWhenReady(workbench);
  workbench.applyDeskLayout();
  workbench.applyModuleSidebarPreference();
  requestAnimationFrame(() => workbench.applyDeskLayout());
};
