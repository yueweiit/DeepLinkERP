(function (globalThis) {
  "use strict";

  const PAGE_NAME = "inventory-location-detail";
  const DEFAULT_COMPANY = "YW Fabricación MX 核心制造";
  const COUNT_UOM_TOKENS = [
    "个", "件", "套", "卷", "包", "张", "片", "支", "条", "台",
    "pieza", "conjunto", "rollo", "paquete", "hoja", "ramo", "barra", "unidad",
  ];

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }

  function isCountUom(stockUom) {
    const normalized = String(stockUom || "").trim().toLowerCase();
    return COUNT_UOM_TOKENS.some((token) => normalized.includes(token));
  }

  function formatQuantity(value, stockUom) {
    const number = Number(value || 0);
    const integerCount = isCountUom(stockUom) && Math.abs(number - Math.round(number)) <= 1e-9;
    return number.toLocaleString("zh-CN", {
      minimumFractionDigits: integerCount ? 0 : 2,
      maximumFractionDigits: integerCount ? 0 : 2,
    });
  }

  function rowspanAttribute(size) {
    return size > 1 ? ` rowspan="${Number(size)}"` : "";
  }

  function sharedCells(group, size) {
    const rowspan = rowspanAttribute(size);
    const itemCode = escapeHtml(group.item_code);
    return {
      beforeLocations: [
        `<td class="ild-code"${rowspan}><a href="#" data-item-code="${itemCode}">${itemCode}</a></td>`,
        `<td class="ild-name"${rowspan}>${escapeHtml(group.item_name)}</td>`,
        `<td${rowspan}>${escapeHtml(group.warehouse)}</td>`,
      ].join(""),
      afterLocations: [
        `<td class="ild-quantity ild-total"${rowspan}>${formatQuantity(group.total_qty, group.stock_uom)}</td>`,
        `<td${rowspan}>${escapeHtml(group.stock_uom)}</td>`,
        `<td${rowspan}>${escapeHtml(group.item_group)}</td>`,
        `<td${rowspan}>${escapeHtml(group.dpci)}</td>`,
        `<td${rowspan}>${escapeHtml(group.external_code)}</td>`,
        `<td${rowspan}>${escapeHtml(group.original_identifier_alias)}</td>`,
      ].join(""),
    };
  }

  function renderTableRows(groups) {
    if (!Array.isArray(groups) || !groups.length) {
      return '<tr class="ild-empty"><td colspan="11">没有符合条件的库存库位记录。</td></tr>';
    }
    return groups.map((group) => {
      const locations = Array.isArray(group.locations) && group.locations.length
        ? group.locations
        : [{ original_location: "", location_qty: 0 }];
      const shared = sharedCells(group, locations.length);
      return locations.map((location, index) => {
        const before = index === 0 ? shared.beforeLocations : "";
        const after = index === 0 ? shared.afterLocations : "";
        return `<tr>${before}<td>${escapeHtml(location.original_location)}</td>`
          + `<td class="ild-quantity">${formatQuantity(location.location_qty, group.stock_uom)}</td>${after}</tr>`;
      }).join("");
    }).join("");
  }

  function downloadBase64File(result) {
    const bytes = atob(result.content_base64 || "");
    const data = new Uint8Array(bytes.length);
    for (let index = 0; index < bytes.length; index += 1) data[index] = bytes.charCodeAt(index);
    const url = URL.createObjectURL(new Blob([data], { type: result.mime_type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = result.file_name || "inventory-location-detail.xlsx";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  class InventoryLocationDetailPage {
    constructor(wrapper) {
      this.wrapper = wrapper;
      this.page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "库存库位明细",
        single_column: true,
      });
      this.requestId = 0;
      this.makeFilters();
      this.renderShell();
      this.bindEvents();
      this.refresh();
    }

    makeFilters() {
      const refresh = () => this.refresh();
      this.fields = {
        company: this.page.add_field({
          fieldname: "company",
          label: "公司",
          fieldtype: "Link",
          options: "Company",
          default: DEFAULT_COMPANY,
          change: () => {
            if (this.fields.snapshot_key) this.fields.snapshot_key.set_value("");
            refresh();
          },
        }),
        snapshot_key: this.page.add_field({
          fieldname: "snapshot_key",
          label: "盘点快照",
          fieldtype: "Select",
          options: [""],
          change: refresh,
        }),
        warehouse: this.page.add_field({
          fieldname: "warehouse",
          label: "仓库",
          fieldtype: "Link",
          options: "Warehouse",
          get_query: () => ({ filters: { company: this.fields.company.get_value() || DEFAULT_COMPANY } }),
          change: refresh,
        }),
        original_location: this.page.add_field({
          fieldname: "original_location",
          label: "原始库位",
          fieldtype: "Data",
        }),
        keyword: this.page.add_field({
          fieldname: "keyword",
          label: "物料编码/名称",
          fieldtype: "Data",
        }),
        item_group: this.page.add_field({
          fieldname: "item_group",
          label: "物料组",
          fieldtype: "Link",
          options: "Item Group",
          change: refresh,
        }),
      };
      this.page.set_primary_action("筛选", () => this.refresh(), "filter");
      this.page.add_inner_button("清除筛选", () => this.clearFilters());
      this.page.add_inner_button("导出 Excel", () => this.exportExcel());
    }

    renderShell() {
      this.$root = $(
        `<section class="inventory-location-detail" aria-label="库存库位明细">
          <div class="ild-status" role="status">正在读取库存库位快照…</div>
          <div class="ild-table-wrap">
            <table aria-label="库存库位明细表">
              <colgroup>
                <col class="ild-col-code"><col class="ild-col-name"><col class="ild-col-warehouse">
                <col class="ild-col-location"><col class="ild-col-location-qty"><col class="ild-col-total">
                <col class="ild-col-uom"><col class="ild-col-group"><col class="ild-col-dpci">
                <col class="ild-col-external"><col class="ild-col-alias">
              </colgroup>
              <thead><tr>
                <th>正式物料编码</th><th>物料名称（双语）</th><th>仓库</th><th>原始库位</th>
                <th>库位数量</th><th>总库存</th><th>库存单位</th><th>物料组</th>
                <th>DPCI</th><th>外部编码</th><th>原始标识/别名</th>
              </tr></thead>
              <tbody></tbody>
            </table>
          </div>
        </section>`
      );
      $(this.page.body).children(":not(.page-form)").remove();
      $(this.page.body).append(this.$root);
    }

    bindEvents() {
      this.$root.on("click", "[data-item-code]", (event) => {
        event.preventDefault();
        frappe.set_route("Form", "Item", $(event.currentTarget).attr("data-item-code"));
      });
      this.fields.original_location.$input.on("keydown", (event) => {
        if (event.key === "Enter") this.refresh();
      });
      this.fields.keyword.$input.on("keydown", (event) => {
        if (event.key === "Enter") this.refresh();
      });
    }

    filters() {
      return Object.fromEntries(
        Object.entries(this.fields)
          .map(([key, field]) => [key, field.get_value()])
          .filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== "")
      );
    }

    async refresh() {
      const requestId = ++this.requestId;
      this.$root.addClass("is-loading");
      this.$root.find(".ild-status").text("正在读取库存库位快照…");
      try {
        const response = await frappe.call({
          method: "overseas_costing.services.inventory_location_service.get_inventory_location_detail",
          args: { filters: this.filters() },
        });
        if (requestId !== this.requestId) return;
        const payload = response.message || {};
        this.setSnapshotOptions(payload.snapshot_options || []);
        this.$root.find("tbody").html(renderTableRows(payload.groups || []));
        const snapshot = payload.snapshot_date || payload.snapshot_key || "暂无快照";
        this.$root.find(".ild-status").text(
          `盘点快照 ${snapshot} · ${Number(payload.group_count || 0)} 个物料仓库组 · ${Number(payload.location_count || 0)} 条库位`
        );
      } catch (error) {
        if (requestId !== this.requestId) return;
        this.$root.find("tbody").html('<tr class="ild-empty"><td colspan="11">库存库位明细读取失败。</td></tr>');
        this.$root.find(".ild-status").text(error.message || "库存库位明细读取失败。");
      } finally {
        if (requestId === this.requestId) this.$root.removeClass("is-loading");
      }
    }

    clearFilters() {
      Object.entries(this.fields).forEach(([key, field]) => {
        if (key !== "company") field.set_value("");
      });
      this.refresh();
    }

    setSnapshotOptions(options) {
      const current = this.fields.snapshot_key.get_value() || "";
      const values = [
        "",
        ...options.map((option) => String(option.snapshot_key || "")).filter(Boolean),
      ];
      this.fields.snapshot_key.df.options = [...new Set(values)];
      this.fields.snapshot_key.refresh();
      if (current && !values.includes(current)) this.fields.snapshot_key.set_value("");
    }

    async exportExcel() {
      const response = await frappe.call({
        method: "overseas_costing.services.inventory_location_service.export_inventory_location_detail",
        args: { filters: this.filters() },
        freeze: true,
        freeze_message: "正在生成 Excel…",
      });
      downloadBase64File(response.message || {});
    }
  }

  const api = { escapeHtml, formatQuantity, renderTableRows, InventoryLocationDetailPage };
  globalThis.InventoryLocationDetail = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;

  if (typeof frappe !== "undefined" && frappe.pages) {
    frappe.pages[PAGE_NAME] = frappe.pages[PAGE_NAME] || {};
    frappe.pages[PAGE_NAME].on_page_load = function (wrapper) {
      frappe.pages[PAGE_NAME].controller = new InventoryLocationDetailPage(wrapper);
    };
  }
})(globalThis);
