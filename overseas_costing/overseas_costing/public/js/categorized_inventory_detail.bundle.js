(function (globalThis) {
  "use strict";

  const PAGE_LENGTHS = [100, 500, 2500];
  const COUNT_UOM_TOKENS = [
    "个", "件", "套", "卷", "包", "张", "片", "支", "条", "台",
    "pieza", "conjunto", "rollo", "paquete", "hoja", "ramo", "barra", "unidad",
  ];

  function resolveDefaultCompany(framework) {
    const getter = framework?.defaults?.get_default;
    return typeof getter === "function"
      ? String(getter.call(framework.defaults, "company") || "").trim()
      : "";
  }

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
    if (value === null || value === undefined || value === "") return "—";
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
    const status = escapeHtml(group.inventory_status || "库位待维护");
    const quantityClass = Number(group.actual_qty || 0) < 0 ? " cid-negative" : "";
    const statusClass = group.inventory_status === "库存差异"
      ? " is-difference"
      : group.inventory_status === "库存一致" ? " is-balanced" : " is-pending";
    return {
      beforeLocations: [
        `<td class="cid-code"${rowspan}><a href="#" data-item-code="${itemCode}">${itemCode}</a></td>`,
        `<td class="cid-name"${rowspan}>${escapeHtml(group.item_name)}</td>`,
        `<td${rowspan}>${escapeHtml(group.warehouse || "—")}</td>`,
      ].join(""),
      afterQuantities: [
        `<td class="cid-quantity${quantityClass}"${rowspan}>${formatQuantity(group.actual_qty, group.stock_uom)}</td>`,
        `<td class="cid-quantity"${rowspan}>${formatQuantity(group.difference_qty, group.stock_uom)}</td>`,
        `<td${rowspan}><span class="cid-status${statusClass}">${status}</span></td>`,
      ].join(""),
      afterDate: [
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
      return '<tr class="cid-empty"><td colspan="14">没有符合条件的库存记录。</td></tr>';
    }
    return groups.map((group) => {
      const locations = Array.isArray(group.locations) && group.locations.length
        ? group.locations
        : [{ reference_location: "库位待维护", snapshot_location_qty: null, snapshot_date: "" }];
      const shared = sharedCells(group, locations.length);
      return locations.map((location, index) => {
        const before = index === 0 ? shared.beforeLocations : "";
        const afterQuantities = index === 0 ? shared.afterQuantities : "";
        const afterDate = index === 0 ? shared.afterDate : "";
        return `<tr>${before}<td>${escapeHtml(location.reference_location || "库位待维护")}</td>`
          + `<td class="cid-quantity">${formatQuantity(location.snapshot_location_qty, group.stock_uom)}</td>`
          + `${afterQuantities}<td>${escapeHtml(location.snapshot_date || "—")}</td>${afterDate}</tr>`;
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
    anchor.download = result.file_name || "categorized-inventory-detail.xlsx";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  class CategorizedInventoryDetailPage {
    constructor(wrapper, config) {
      this.wrapper = wrapper;
      this.config = config;
      this.start = 0;
      this.pageLength = PAGE_LENGTHS[0];
      this.requestId = 0;
      this.page = frappe.ui.make_app_page({
        parent: wrapper,
        title: config.title,
        single_column: true,
      });
      this.makeFilters();
      this.renderShell();
      this.bindEvents();
      this.refresh();
    }

    makeFilters() {
      const resetAndRefresh = () => this.refresh(true);
      const defaultCompany = resolveDefaultCompany(frappe);
      this.fields = {
        company: this.page.add_field({
          fieldname: "company",
          label: "公司",
          fieldtype: "Link",
          options: "Company",
          default: defaultCompany,
          change: () => {
            if (this.fields.warehouse) this.fields.warehouse.set_value("");
            if (this.fields.item_group) this.fields.item_group.set_value("");
            resetAndRefresh();
          },
        }),
        warehouse: this.page.add_field({
          fieldname: "warehouse",
          label: "仓库",
          fieldtype: "Link",
          options: "Warehouse",
          get_query: () => {
            const company = this.fields.company.get_value() || defaultCompany;
            const filters = { is_group: 0 };
            if (company) filters.company = company;
            return { filters };
          },
          change: resetAndRefresh,
        }),
        item_group: this.page.add_field({
          fieldname: "item_group",
          label: "下级物料组",
          fieldtype: "Select",
          options: [""],
          change: resetAndRefresh,
        }),
        keyword: this.page.add_field({
          fieldname: "keyword",
          label: "物料编码/名称",
          fieldtype: "Data",
        }),
        reference_location: this.page.add_field({
          fieldname: "reference_location",
          label: "参考库位",
          fieldtype: "Data",
        }),
        only_with_stock: this.page.add_field({
          fieldname: "only_with_stock",
          label: "只看有库存",
          fieldtype: "Check",
          default: 0,
          change: resetAndRefresh,
        }),
        page_length: this.page.add_field({
          fieldname: "page_length",
          label: "每页",
          fieldtype: "Select",
          options: PAGE_LENGTHS.map(String),
          default: String(PAGE_LENGTHS[0]),
          change: () => {
            this.pageLength = Number(this.fields.page_length.get_value()) || PAGE_LENGTHS[0];
            resetAndRefresh();
          },
        }),
      };
      this.page.set_primary_action("筛选", () => this.refresh(true), "filter");
      this.page.add_inner_button("清除筛选", () => this.clearFilters());
      this.page.add_inner_button("导出 Excel", () => this.exportExcel());
    }

    renderShell() {
      this.$root = $(
        `<section class="categorized-inventory-detail" aria-label="${escapeHtml(this.config.title)}">
          <div class="cid-summary" role="status">正在读取 ERP 实时库存…</div>
          <div class="cid-table-wrap">
            <table aria-label="${escapeHtml(this.config.title)}表">
              <colgroup>
                <col class="cid-col-code"><col class="cid-col-name"><col class="cid-col-warehouse">
                <col class="cid-col-location"><col class="cid-col-snapshot"><col class="cid-col-actual">
                <col class="cid-col-difference"><col class="cid-col-status"><col class="cid-col-date">
                <col class="cid-col-uom"><col class="cid-col-group"><col class="cid-col-dpci">
                <col class="cid-col-external"><col class="cid-col-alias">
              </colgroup>
              <thead><tr>
                <th>正式物料编码</th><th>物料名称（双语）</th><th>仓库</th><th>参考库位</th>
                <th>快照库位数量</th><th>实时库存</th><th>库存差异</th><th>库存状态</th>
                <th>快照日期</th><th>库存单位</th><th>物料组</th><th>DPCI</th>
                <th>外部编码</th><th>原始标识/别名</th>
              </tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <div class="cid-pager">
            <button type="button" class="btn btn-default btn-sm" data-page-action="previous">上一页</button>
            <span class="cid-page-label">第 1 页</span>
            <button type="button" class="btn btn-default btn-sm" data-page-action="next">下一页</button>
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
      this.$root.on("click", "[data-page-action]", (event) => {
        const action = $(event.currentTarget).attr("data-page-action");
        if (action === "previous" && this.start > 0) {
          this.start = Math.max(0, this.start - this.pageLength);
          this.refresh();
        }
        if (action === "next" && this.lastPayload?.has_next) {
          this.start += this.pageLength;
          this.refresh();
        }
      });
      for (const fieldname of ["keyword", "reference_location"]) {
        this.fields[fieldname].$input.on("keydown", (event) => {
          if (event.key === "Enter") this.refresh(true);
        });
      }
    }

    filters() {
      return Object.fromEntries(
        Object.entries(this.fields)
          .filter(([key]) => key !== "page_length")
          .map(([key, field]) => [key, field.get_value()])
          .filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== "")
      );
    }

    async refresh(resetStart = false) {
      if (resetStart) this.start = 0;
      const requestId = ++this.requestId;
      this.$root.addClass("is-loading");
      this.$root.find(".cid-summary").text("正在读取 ERP 实时库存…");
      try {
        const response = await frappe.call({
          method: "overseas_costing.services.inventory_location_service.get_categorized_inventory_detail",
          args: {
            category: this.config.category,
            filters: this.filters(),
            start: this.start,
            page_length: this.pageLength,
          },
        });
        if (requestId !== this.requestId) return;
        const payload = response.message || {};
        this.lastPayload = payload;
        this.setItemGroupOptions(payload.item_group_options || []);
        this.$root.find("tbody").html(renderTableRows(payload.groups || []));
        const snapshot = payload.snapshot_date || "暂无库位快照";
        const summary = payload.warning
          || `ERP 实时库存 · ${Number(payload.total_count || 0)} 个物料仓库组 · 当前 ${Number(payload.page_count || 0)} 条 · 参考快照 ${snapshot}`;
        this.$root.find(".cid-summary").text(summary);
        this.renderPager(payload);
      } catch (error) {
        if (requestId !== this.requestId) return;
        this.$root.find("tbody").html('<tr class="cid-empty"><td colspan="14">库存明细读取失败。</td></tr>');
        this.$root.find(".cid-summary").text(error.message || "库存明细读取失败。");
      } finally {
        if (requestId === this.requestId) this.$root.removeClass("is-loading");
      }
    }

    setItemGroupOptions(options) {
      const current = this.fields.item_group.get_value() || "";
      const values = ["", ...options.map(String).filter(Boolean)];
      this.fields.item_group.df.options = [...new Set(values)];
      this.fields.item_group.refresh();
      if (current && !values.includes(current)) this.fields.item_group.set_value("");
    }

    renderPager(payload) {
      const page = Math.floor(Number(payload.start || 0) / this.pageLength) + 1;
      const pages = Math.max(1, Math.ceil(Number(payload.total_count || 0) / this.pageLength));
      this.$root.find(".cid-page-label").text(`第 ${page} / ${pages} 页`);
      this.$root.find('[data-page-action="previous"]').prop("disabled", !payload.has_previous);
      this.$root.find('[data-page-action="next"]').prop("disabled", !payload.has_next);
    }

    clearFilters() {
      Object.entries(this.fields).forEach(([key, field]) => {
        if (key === "company") return;
        if (key === "page_length") field.set_value(String(PAGE_LENGTHS[0]));
        else field.set_value(key === "only_with_stock" ? 0 : "");
      });
      this.pageLength = PAGE_LENGTHS[0];
      this.refresh(true);
    }

    async exportExcel() {
      const response = await frappe.call({
        method: "overseas_costing.services.inventory_location_service.export_categorized_inventory_detail",
        args: { category: this.config.category, filters: this.filters() },
        freeze: true,
        freeze_message: "正在生成 Excel…",
      });
      downloadBase64File(response.message || {});
    }
  }

  function bootstrap(wrapper, config) {
    return new CategorizedInventoryDetailPage(wrapper, config);
  }

  const api = {
    escapeHtml,
    formatQuantity,
    renderTableRows,
    resolveDefaultCompany,
    CategorizedInventoryDetailPage,
    bootstrap,
  };
  globalThis.CategorizedInventoryDetail = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
