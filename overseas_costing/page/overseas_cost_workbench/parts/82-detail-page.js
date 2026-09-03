  getDetailBatch() {
    const header = this.detailState.header || {};
    return this.findBatch(this.detailState.batchName) || header;
  }

  inferDetailIssue(batch = {}) {
    if (batch.primary_issue) return batch.primary_issue;
    const writeback = String(batch.writeback_status || "").toLowerCase();
    const status = String(batch.status || "").toLowerCase();
    const sourceStatus = batch.source_status || {};
    const cost = Number(batch.actual_total_cost_rmb || batch.estimated_total_cost_rmb || 0);
    if (!batch.subsidiary_code || ["missing", "pending", "invalid"].includes(String(sourceStatus.purchase_approval_sync_state || "").toLowerCase())) {
      return "purchase";
    }
    if (["draft", "dirty", "writeback failed"].includes(status) || cost <= 0) return "calculation";
    if (writeback.includes("fail")) return "erp_failed";
    return "ready";
  }

  async openBatchDetail(batchName = "", tab = "items", options = {}) {
    const normalizedName = String(batchName || "").trim();
    if (!normalizedName) {
      this.showPendingFeature("缺少批次号，无法打开详情。");
      return;
    }
    if (this.detailState.editToken && this.detailState.batchName && this.detailState.batchName !== normalizedName) {
      await this.releaseEditSession();
    }
    const allowedTab = OverseasCostWorkbenchState.parseWorkbenchState(
      `${window.location.pathname}?screen=detail&batch=${encodeURIComponent(normalizedName)}&tab=${encodeURIComponent(tab || "items")}`
    ).tab;
    if (options.updateUrl !== false) {
      window.history.replaceState(
        { ...(window.history.state || {}), ocwScrollY: window.scrollY, overseasCostWorkbench: true },
        "",
        window.location.href
      );
      this.replaceViewState(
        { screen: "detail", batch: normalizedName, tab: allowedTab },
        { push: true }
      );
    }
    this.detailState.batchName = normalizedName;
    const requestId = ++this.detailState.requestId;
    this.detailState.refreshRequestId += 1;
    this.detailState.tab = allowedTab;
    this.activeBatchName = normalizedName;
    this.exportPinnedBatchName = normalizedName;
    this.dataCheckBatchName = normalizedName;
    this.drawerBatchName = normalizedName;
    this.$root.attr("data-screen", "detail");
    this.$root.find("[data-area='workbench-screen']").prop("hidden", true);
    this.$root.find("[data-area='detail-screen']").prop("hidden", false);
    this.renderDetailLoading();
    try {
      const result = await this.call("overseas_costing.api.batch.get_batch_detail", {
        batch_name: normalizedName,
      });
      if (requestId !== this.detailState.requestId || this.detailState.batchName !== normalizedName) return;
      if (!result || !result.ok) throw new Error((result && result.message) || "批次详情加载失败");
      const merged = {
        ...(this.findBatch(result.batch_name || normalizedName) || {}),
        ...(result.header || {}),
        name: result.batch_name || (result.header || {}).name || normalizedName,
        current_version: result.version_name || (result.header || {}).current_version || "",
        summary_snapshot: result.summary || {},
        allocation_rule_snapshot: result.allocation_rules || [],
      };
      const index = this.batches.findIndex((row) => row.name === merged.name);
      if (index >= 0) this.batches[index] = merged;
      else this.batches.push(merged);
      this.detailState.batchName = merged.name;
      this.detailState.versionName = result.version_name || merged.current_version || "";
      this.detailState.header = merged;
      this.detailState.detail = result;
      this.detailState.expectedModified = merged.modified || this.detailState.expectedModified || "";
      this.detailState.dirty = false;
      this.activeBatchName = merged.name;
      this.drawerBatchName = merged.name;
      this.renderDetailShell();
      await this.switchDetailTab(allowedTab, { updateUrl: false });
    } catch (error) {
      if (requestId !== this.detailState.requestId || this.detailState.batchName !== normalizedName) return;
      this.renderDetailError(error);
    }
  }

  async returnToWorkbench() {
    if (!(await this.confirmDiscardDetailChanges())) return;
    await this.releaseEditSession();
    this.cleanupSkuScrollControls();
    this.detailState.requestId += 1;
    this.detailState.skuRequestId += 1;
    this.detailState.refreshRequestId += 1;
    this.replaceViewState({ screen: "", batch: "", tab: "" });
    this.detailState.batchName = "";
    this.detailState.header = null;
    this.detailState.detail = null;
    this.exportPinnedBatchName = "";
    this.dataCheckBatchName = "";
    this.drawerBatchName = "";
    this.$root.attr("data-screen", "workbench");
    this.$root.find("[data-area='detail-screen']").prop("hidden", true).empty();
    this.$root.find("[data-area='workbench-screen']").prop("hidden", false);
    await this.loadBatches();
    requestAnimationFrame(() => window.scrollTo({ top: Number(window.history.state?.ocwScrollY || 0), behavior: "auto" }));
  }

  async refreshDetailSummary(options = {}) {
    const batchName = String(this.detailState.batchName || "").trim();
    if (!batchName) return;
    const activeTab = this.detailState.tab || "items";
    const requestId = ++this.detailState.refreshRequestId;
    let result;
    try {
      result = await this.call("overseas_costing.api.batch.get_batch_detail", {
        batch_name: batchName,
        version_name: this.detailState.versionName || null,
      });
    } catch (error) {
      if (requestId !== this.detailState.refreshRequestId || this.detailState.batchName !== batchName) return;
      throw error;
    }
    if (requestId !== this.detailState.refreshRequestId || this.detailState.batchName !== batchName) return;
    if (!result || !result.ok) throw new Error((result && result.message) || "批次详情刷新失败");
    const merged = {
      ...(this.findBatch(batchName) || {}),
      ...(this.detailState.header || {}),
      ...(result.header || {}),
      name: result.batch_name || batchName,
      current_version: result.version_name || (result.header || {}).current_version || this.detailState.versionName || "",
      summary_snapshot: result.summary || {},
      allocation_rule_snapshot: result.allocation_rules || [],
    };
    const index = this.batches.findIndex((row) => row.name === batchName);
    if (index >= 0) this.batches[index] = merged;
    this.detailState.header = merged;
    this.detailState.detail = result;
    this.detailState.versionName = merged.current_version;
    this.detailState.expectedModified = merged.modified || this.detailState.expectedModified || "";
    this.renderDetailShell();
    if (this.detailState.editToken) this.updateEditLeaseStatus();
    if (options.refreshCurrentTab === false) return;
    await this.switchDetailTab(activeTab, { updateUrl: false });
  }

  renderDetailLoading() {
    this.cleanupSkuScrollControls();
    this.$root.find("[data-area='detail-screen']").html(`
      <div class="ocw-detail-state"><span class="ocw-spinner"></span><strong>正在加载批次详情</strong><small>不会预加载 SKU 明细</small></div>
    `);
  }

  renderDetailError(error) {
    this.cleanupSkuScrollControls();
    this.$root.find("[data-area='detail-screen']").html(`
      <div class="ocw-detail-state is-error">
        <strong>批次详情加载失败</strong>
        <span>${this.escape(this.normalizeErrorMessage(error))}</span>
        <div><button class="ocw-outline-btn" type="button" data-action="return-workbench">返回工作台</button><button class="ocw-primary-btn" type="button" data-action="retry-detail">重试</button></div>
      </div>
    `);
  }

  detailStatusChip(label, value, tone = "neutral") {
    return `<span class="ocw-detail-status is-${tone}"><small>${this.escape(label)}</small><strong>${this.escape(this.formatValue(value || "--"))}</strong></span>`;
  }

  renderDetailShell() {
    this.cleanupSkuScrollControls();
    const batch = this.getDetailBatch();
    const issue = this.inferDetailIssue(batch);
    const action = OverseasCostWorkbenchState.primaryActionForIssue(issue);
    const reference = batch.batch_no || batch.source_approval_no || batch.customs_no || batch.name;
    const logistics = batch.waybill_no || batch.container_no || batch.sea_bill_no || "未填写物流单号";
    const sourceStatus = batch.source_status || {};
    const documentStatus = this.sourceStatusLabel(sourceStatus, batch);
    const erpInfo = this.erpWritebackStatusInfo(batch);
    const updatedAt = batch.modified || (this.detailState.detail?.version || {}).calculated_at || batch.writeback_time || "--";
    this.$root.find("[data-area='detail-screen']").html(`
      <div class="ocw-detail-page">
        <header class="ocw-detail-header">
          <div class="ocw-detail-heading">
            <button class="ocw-back-btn" type="button" data-action="return-workbench" aria-label="返回工作台">← <span>返回工作台</span></button>
            <div>
              <span class="ocw-detail-eyebrow">批次详情</span>
              <h1>${this.escape(reference)}</h1>
              <p>${this.escape(logistics)} · ${this.escape(this.businessTypeLabel(batch.business_type) || this.transportLabel(batch.transport_mode) || "未分类")}</p>
            </div>
          </div>
          <div class="ocw-detail-header-actions">
            <button class="ocw-primary-btn" type="button" data-action="detail-primary" data-primary-action="${action.action}">${action.label}</button>
            <div class="ocw-menu-wrap">
              <button class="ocw-outline-btn" type="button" data-action="toggle-detail-tools" aria-expanded="false">批次工具 ▾</button>
              <div class="ocw-detail-tools" data-area="detail-tools" hidden>
                <button type="button" data-action="detail-export">导出本批次</button>
                <button type="button" data-action="detail-voucher">凭证对比</button>
                <button type="button" data-action="detail-category">商品归类</button>
                <button type="button" data-action="detail-dingtalk">打开钉钉来源</button>
                <button type="button" data-action="detail-repull">重拉本批次</button>
                <button type="button" data-action="detail-excel">单批次 Excel 补充</button>
              </div>
            </div>
          </div>
        </header>
        <section class="ocw-detail-statusbar">
          ${this.detailStatusChip("当前问题", this.issueLabel(issue), issue === "ready" ? "ok" : "warn")}
          ${this.detailStatusChip("资料", documentStatus, documentStatus.includes("待") ? "warn" : "ok")}
          ${this.detailStatusChip("计算", this.batchStatusInfo(batch.status, batch, Number(batch.item_count || 0)).label, String(batch.status || "").toLowerCase().includes("calculated") ? "ok" : "warn")}
          ${this.detailStatusChip("ERP", erpInfo.label, erpInfo.state === "is-ok" ? "ok" : erpInfo.state === "is-warn" ? "warn" : "neutral")}
          ${this.detailStatusChip("最后更新", this.formatDateTimeMinute(updatedAt) || updatedAt, "neutral")}
          <span class="ocw-edit-lease-status" data-area="edit-lease-status">浏览模式 · 开始修改时自动申请编辑权</span>
        </section>
        <nav class="ocw-detail-tabs" aria-label="批次详情分类">
          ${[
            ["overview", "总览"],
            ["documents", "资料与费用"],
            ["items", "SKU 明细"],
            ["vouchers", "凭证核对"],
            ["audit", "操作记录"],
          ].map(([key, label]) => `<button class="${this.detailState.tab === key ? "is-active" : ""}" type="button" data-action="switch-detail-tab" data-tab="${key}">${label}</button>`).join("")}
        </nav>
        <section class="ocw-detail-content" data-area="detail-content"></section>
      </div>
    `);
  }

  async switchDetailTab(tab = "items", options = {}) {
    const allowed = OverseasCostWorkbenchState.parseWorkbenchState(
      `${window.location.pathname}?screen=detail&batch=x&tab=${encodeURIComponent(tab)}`
    ).tab;
    if (allowed !== this.detailState.tab && !(await this.confirmDiscardDetailChanges())) return;
    this.cleanupSkuScrollControls();
    this.detailState.tab = allowed;
    this.$root.find("[data-action='switch-detail-tab']").each((_, node) => {
      $(node).toggleClass("is-active", $(node).attr("data-tab") === allowed);
    });
    if (options.updateUrl !== false) {
      this.replaceViewState({ screen: "detail", batch: this.detailState.batchName, tab: allowed });
    }
    if (allowed === "items") return this.loadSkuPage();
    if (allowed === "audit") return this.renderAuditDetailTab();
    if (allowed === "vouchers") return this.renderVoucherDetailTab();
    if (allowed === "documents") return this.renderDocumentsDetailTab();
    return this.renderOverviewDetailTab();
  }

  renderDetailTabLoading(label) {
    this.cleanupSkuScrollControls();
    this.$root.find("[data-area='detail-content']").html(`
      <div class="ocw-detail-state"><span class="ocw-spinner"></span><strong>${this.escape(label)}</strong></div>
    `);
  }

  renderOverviewDetailTab() {
    const batch = this.getDetailBatch();
    this.$root.find("[data-area='detail-content']").html(`
      <div class="ocw-detail-overview">
        <div class="ocw-detail-section-head"><div><span>批次概况</span><h2>成本与 ERP 流程</h2></div><button class="ocw-outline-btn" type="button" data-action="detail-recalculate">重新计算</button></div>
        ${this.renderBatchDrawerOverview(batch, [])}
      </div>
    `);
  }

  detailDocumentAdapter() {
    return { $wrapper: this.$root.find("[data-area='detail-screen']") };
  }

  async renderDocumentsDetailTab() {
    const batch = this.getDetailBatch();
    const resolvedType = this.detectManualDocumentLogisticsType(batch);
    const $content = this.$root.find("[data-area='detail-content']");
    $content.html(`
      <div class="ocw-detail-section-head"><div><span>异常处理</span><h2>资料与费用</h2></div><button class="ocw-outline-btn" type="button" data-action="detail-repull">重拉本批次</button></div>
      <div data-area="manual-documents">${this.renderManualDocumentPanel(batch, resolvedType, [])}</div>
    `);
    try {
      await this.loadManualDocumentAttachments(batch, this.detailDocumentAdapter(), resolvedType);
    } catch (error) {
      this.showError(error);
    }
  }

  async renderVoucherDetailTab() {
    const batch = this.getDetailBatch();
    this.renderDetailTabLoading("正在读取凭证核对记录");
    try {
      const result = await this.call("overseas_costing.api.import_api.list_tax_certificate_parse_records", {
        batch_name: batch.name,
        limit: 20,
      });
      const items = (result && result.items) || [];
      this.$root.find("[data-area='detail-content']").html(`
        <div class="ocw-detail-section-head"><div><span>最终对账</span><h2>凭证核对</h2></div><button class="ocw-primary-btn" type="button" data-action="detail-voucher">+ 新增凭证对比</button></div>
        <div class="ocw-detail-voucher-list">
          ${items.length ? items.map((row) => this.renderTaxCertificateRecord(row)).join("") : `<div class="ocw-detail-empty"><strong>当前批次暂无凭证记录</strong><span>可上传完税凭证 PDF 与系统税费进行对比。</span></div>`}
        </div>
      `);
    } catch (error) {
      this.renderDetailTabError("凭证记录", error);
    }
  }

  async renderAuditDetailTab() {
    const batch = this.getDetailBatch();
    this.renderDetailTabLoading("正在读取操作记录");
    try {
      const [auditResult, usageResult] = await Promise.all([
        this.call("overseas_costing.api.batch.get_audit_logs", {
          batch_name: batch.name,
          version_name: this.detailState.versionName || batch.current_version || null,
          limit: 80,
        }),
        this.call("overseas_costing.api.usage.get_usage_logs", {
          batch_name: batch.name,
          limit: 80,
        }),
      ]);
      if (!auditResult || !auditResult.ok) throw new Error((auditResult && auditResult.message) || "修改记录加载失败");
      if (!usageResult || !usageResult.ok) throw new Error((usageResult && usageResult.message) || "使用记录加载失败");
      const auditEvents = (auditResult.items || []).map((row) => this.mapAuditRow(row, batch));
      const usageEvents = (usageResult.items || []).map((row) => this.mapUsageRow(row, batch));
      this.auditEvents = [...auditEvents, ...usageEvents].sort((left, right) => String(right.time || "").localeCompare(String(left.time || "")));
      const events = this.buildAuditSummaryEvents(this.auditEvents);
      this.$root.find("[data-area='detail-content']").html(`
        <div class="ocw-detail-section-head"><div><span>可追溯</span><h2>操作记录</h2></div><span>${events.length} 条</span></div>
        <ul class="ocw-audit-list ocw-detail-audit-list">${events.length ? events.map((event) => this.renderAuditEvent(event)).join("") : `<li class="ocw-audit-empty">当前批次暂无操作记录</li>`}</ul>
      `);
    } catch (error) {
      this.renderDetailTabError("操作记录", error);
    }
  }

  renderDetailTabError(label, error) {
    this.$root.find("[data-area='detail-content']").html(`
      <div class="ocw-detail-empty is-error"><strong>${this.escape(label)}加载失败</strong><span>${this.escape(this.normalizeErrorMessage(error))}</span><button class="ocw-outline-btn" type="button" data-action="retry-detail-tab">重试</button></div>
    `);
  }

  async loadSkuPage() {
    const batch = this.getDetailBatch();
    const sku = this.detailState.sku;
    const requestId = ++this.detailState.skuRequestId;
    this.renderDetailTabLoading("正在读取 SKU 当前页");
    try {
      const result = await this.call("overseas_costing.api.workbench.get_batch_items_page", {
        batch_name: batch.name,
        version_name: this.detailState.versionName || batch.current_version || null,
        keyword: sku.keyword || "",
        page: sku.page,
        page_length: sku.pageLength,
        field_group: sku.fieldGroup,
        sort_by: sku.sortBy,
        sort_order: sku.sortOrder,
      });
      if (requestId !== this.detailState.skuRequestId || this.detailState.batchName !== batch.name) return;
      if (!result || !result.ok) throw new Error((result && result.message) || "SKU 明细加载失败");
      if (!(result.items || []).length && sku.page > 1 && Number(result.total || 0) > 0) {
        sku.page -= 1;
        return this.loadSkuPage();
      }
      this.detailState.versionName = result.version_name || this.detailState.versionName;
      this.detailState.skuResult = result;
      this.renderSkuDetailTab(result);
    } catch (error) {
      if (requestId !== this.detailState.skuRequestId || this.detailState.batchName !== batch.name) return;
      this.renderDetailTabError("SKU 明细", error);
    }
  }

  renderSkuDetailTab(result = {}) {
    const sku = this.detailState.sku;
    const columns = result.columns || [];
    const items = result.items || [];
    const groups = [
      ["basic", "基础信息"], ["purchase", "采购数据"], ["logistics", "物流费用"],
      ["tax", "税费"], ["total", "综合成本"], ["all", "全部字段"],
    ];
    const header = columns.map((column, index) => {
      const sortable = ["material_code", "product_name", "quantity", "goods_value", "total_cost_rmb", "total_unit_rmb"].includes(column.fieldname);
      const sortMark = sku.sortBy === column.fieldname ? (sku.sortOrder === "asc" ? " ↑" : " ↓") : "";
      return `<th class="${index < 2 ? `ocw-sku-sticky ocw-sku-sticky-${index}` : ""}" title="${this.escape(`${column.excel_col} ${column.label}`)}">${sortable ? `<button type="button" data-action="sku-sort" data-sort-by="${this.escape(column.fieldname)}">` : ""}<span>${this.escape(column.excel_col)}</span>${this.escape(column.label)}${sortMark}${sortable ? "</button>" : ""}</th>`;
    }).join("");
    const body = items.map((row) => `<tr>${columns.map((column, index) => this.renderSkuPageCell(row, column, index)).join("")}</tr>`).join("");
    this.$root.find("[data-area='detail-content']").html(`
      <div class="ocw-detail-section-head"><div><span>服务端分页</span><h2>SKU 明细</h2></div><strong>共 ${Number(result.total || 0)} 行</strong></div>
      <div class="ocw-sku-toolbar">
        <label><span>搜索当前批次 SKU</span><input class="form-control" type="search" data-role="sku-keyword" value="${this.escape(sku.keyword)}" placeholder="物料编码或产品名称" /></label>
        <div class="ocw-sku-groups" role="group" aria-label="SKU 字段分组">${groups.map(([key, label]) => `<button class="${sku.fieldGroup === key ? "is-active" : ""}" type="button" data-action="sku-group" data-field-group="${key}">${label}</button>`).join("")}</div>
      </div>
      <div class="ocw-sku-table-shell">
        <div class="ocw-sku-table-wrap" data-role="sku-table-scroll">
          <table class="ocw-sku-table"><thead><tr>${header}</tr></thead><tbody>${body || `<tr><td colspan="${Math.max(columns.length, 1)}"><div class="ocw-detail-empty">当前条件下没有 SKU</div></td></tr>`}</tbody></table>
        </div>
        <div class="ocw-sku-scroll-controls">
          <button type="button" data-action="sku-scroll" data-direction="-1" aria-label="向左滚动 SKU 表">◀</button>
          <input class="ocw-sku-scrollbar" type="range" min="0" max="0" step="1" value="0" data-role="sku-scrollbar" aria-label="SKU 明细水平滚动条" disabled />
          <button type="button" data-action="sku-scroll" data-direction="1" aria-label="向右滚动 SKU 表">▶</button>
          <span>当前 ${this.escape(groups.find(([key]) => key === sku.fieldGroup)?.[1] || "基础信息")} · 全部 A–BE</span>
        </div>
      </div>
      <div class="ocw-sku-pagination">
        <span>每页 ${sku.pageLength} 行</span>
        <button class="ocw-outline-btn" type="button" data-action="sku-page" data-page="${Number(result.page || 1) - 1}" ${Number(result.page || 1) <= 1 ? "disabled" : ""}>上一页</button>
        <strong>第 ${Number(result.page || 1)} / ${Math.max(Number(result.page_count || 0), 1)} 页</strong>
        <button class="ocw-outline-btn" type="button" data-action="sku-page" data-page="${Number(result.page || 1) + 1}" ${Number(result.page || 1) >= Number(result.page_count || 0) ? "disabled" : ""}>下一页</button>
      </div>
    `);
    requestAnimationFrame(() => this.bindSkuScrollControls());
  }

  renderSkuPageCell(row, column, index) {
    const editable = this.isEditableColumn(column);
    const rawValue = this.shouldShowEmptyZeroFee(column.fieldname, row[column.fieldname]) ? "" : this.normalizeEditorValue(row[column.fieldname]);
    const displayValue = this.formatCellValue(row[column.fieldname], column);
    const content = this.renderCell(row[column.fieldname], column);
    return `
      <td class="${index < 2 ? `ocw-sku-sticky ocw-sku-sticky-${index}` : ""} ${editable ? "ocw-editable-cell" : "ocw-readonly-cell"} ${this.escape(this.columnAlignClass(column))}"
        title="${this.escape(displayValue || "")}" data-editable-cell="${editable ? "1" : "0"}"
        data-batch-name="${this.escape(this.detailState.batchName)}" data-item-name="${this.escape(row.name || "")}"
        data-version-name="${this.escape(this.detailState.versionName || "")}" data-fieldname="${this.escape(column.fieldname)}"
        data-field-label="${this.escape(column.label)}" data-raw-value="${this.escape(rawValue)}"
        data-special-override="${this.specialOverrideFields.has(column.fieldname) ? "1" : "0"}">${index < 2 ? `<span class="ocw-sku-sticky-content">${content}</span>` : content}</td>
    `;
  }

  shouldCompactSkuColumns(scrollLeft, currentlyCompact = false) {
    const position = Math.max(0, Number(scrollLeft) || 0);
    return currentlyCompact ? position > 32 : position > 148;
  }

  cleanupSkuScrollControls() {
    const cleanup = this.skuScrollCleanup;
    this.skuScrollCleanup = null;
    if (typeof cleanup === "function") cleanup();
  }

  bindSkuScrollControls() {
    this.cleanupSkuScrollControls();
    const $table = this.$root.find("[data-role='sku-table-scroll']");
    const $range = this.$root.find("[data-role='sku-scrollbar']");
    const $shell = $table.closest(".ocw-sku-table-shell");
    const table = $table.get(0);
    const range = $range.get(0);
    if (!table || !range) return;

    const skuTable = table.querySelector(".ocw-sku-table");
    let syncing = false;
    let compact = false;
    let refreshFrame = null;
    let resizeObserver = null;

    const updateCompactState = (scrollLeft) => {
      const nextCompact = this.shouldCompactSkuColumns(scrollLeft, compact);
      if (nextCompact === compact) return;
      compact = nextCompact;
      $shell.toggleClass("is-sku-compact", compact);
      scheduleMetricsRefresh();
    };

    const refreshMetrics = () => {
      const maxScrollLeft = Math.max(0, table.scrollWidth - table.clientWidth);
      const scrollLeft = Math.min(maxScrollLeft, Math.max(0, table.scrollLeft));
      if (table.scrollLeft !== scrollLeft) table.scrollLeft = scrollLeft;
      range.max = String(maxScrollLeft);
      range.value = String(scrollLeft);
      range.disabled = maxScrollLeft <= 0;
      this.updateSkuScrollButtons(table, maxScrollLeft);
      updateCompactState(scrollLeft);
    };

    const scheduleMetricsRefresh = () => {
      if (refreshFrame !== null) return;
      refreshFrame = window.requestAnimationFrame(() => {
        refreshFrame = null;
        refreshMetrics();
      });
    };

    const onTableScroll = () => {
      if (syncing) return;
      syncing = true;
      refreshMetrics();
      syncing = false;
    };

    const onRangeInput = () => {
      if (syncing) return;
      syncing = true;
      const maxScrollLeft = Math.max(0, table.scrollWidth - table.clientWidth);
      const nextScrollLeft = Math.min(maxScrollLeft, Math.max(0, Number(range.value) || 0));
      table.scrollLeft = nextScrollLeft;
      refreshMetrics();
      syncing = false;
    };

    const onColumnTransitionEnd = (event) => {
      if (!event.target.classList.contains("ocw-sku-sticky")) return;
      scheduleMetricsRefresh();
    };

    table.addEventListener("scroll", onTableScroll, { passive: true });
    range.addEventListener("input", onRangeInput);
    skuTable?.addEventListener("transitionend", onColumnTransitionEnd);
    window.addEventListener("resize", scheduleMetricsRefresh);

    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(scheduleMetricsRefresh);
      resizeObserver.observe(table);
      if (skuTable) resizeObserver.observe(skuTable);
    }

    this.skuScrollCleanup = () => {
      table.removeEventListener("scroll", onTableScroll);
      range.removeEventListener("input", onRangeInput);
      skuTable?.removeEventListener("transitionend", onColumnTransitionEnd);
      window.removeEventListener("resize", scheduleMetricsRefresh);
      resizeObserver?.disconnect();
      if (refreshFrame !== null) window.cancelAnimationFrame(refreshFrame);
      $shell.removeClass("is-sku-compact");
    };

    refreshMetrics();
  }

  updateSkuScrollButtons(table = this.$root.find("[data-role='sku-table-scroll']").get(0), maxScrollLeft = null) {
    if (!table) return;
    const max = maxScrollLeft === null ? Math.max(0, table.scrollWidth - table.clientWidth) : maxScrollLeft;
    this.$root.find("[data-action='sku-scroll'][data-direction='-1']").prop("disabled", max <= 1 || table.scrollLeft <= 1);
    this.$root.find("[data-action='sku-scroll'][data-direction='1']").prop("disabled", max <= 1 || table.scrollLeft >= max - 1);
  }

  async ensureEditSession() {
    if (this.detailState.editToken) return true;
    const batch = this.getDetailBatch();
    if (!batch || !batch.name) return false;
    const result = await this.call("overseas_costing.api.edit_session.acquire", { batch_name: batch.name }, true);
    if (!result || !result.ok) {
      this.detailState.readonly = true;
      const lockedBy = (result && result.locked_by) || "其他用户";
      const expiresAt = this.formatDateTimeMinute((result && result.expires_at) || "") || "租约过期";
      this.$root.find("[data-area='edit-lease-status']").addClass("is-locked").text(`只读 · 由 ${lockedBy} 编辑至 ${expiresAt}`);
      this.$root.find("[data-area='detail-content'] [data-editable-cell='1']").attr("data-editable-cell", "0").addClass("ocw-readonly-cell");
      frappe.show_alert({ message: (result && result.message) || `当前批次正在被 ${lockedBy} 编辑。`, indicator: "orange" });
      return false;
    }
    this.detailState.readonly = false;
    this.detailState.editToken = result.edit_token;
    this.detailState.editExpiresAt = result.expires_at;
    // 保留详情加载时的 modified，以便首次写入仍能发现“加载后、获取锁前”的并发修改。
    this.detailState.expectedModified = this.detailState.expectedModified || batch.modified || result.modified || "";
    this.updateEditLeaseStatus();
    window.clearInterval(this.detailState.renewTimer);
    this.detailState.renewTimer = window.setInterval(() => this.renewEditSession(), 120000);
    return true;
  }

  async renewEditSession() {
    if (!this.detailState.editToken || !this.detailState.batchName) return;
    try {
      const result = await this.call("overseas_costing.api.edit_session.renew", {
        batch_name: this.detailState.batchName,
        edit_token: this.detailState.editToken,
      });
      if (!result || !result.ok) throw new Error((result && result.message) || "续租失败");
      this.detailState.editExpiresAt = result.expires_at;
      this.updateEditLeaseStatus();
    } catch (error) {
      window.clearInterval(this.detailState.renewTimer);
      this.detailState.renewTimer = null;
      this.detailState.editToken = "";
      this.detailState.readonly = true;
      this.$root.find("[data-area='edit-lease-status']").addClass("is-locked").text("编辑权已失效 · 请重新点击要修改的单元格");
    }
  }

  updateEditLeaseStatus() {
    const expiresAt = this.formatDateTimeMinute(this.detailState.editExpiresAt || "") || "5 分钟后";
    this.$root.find("[data-area='edit-lease-status']").removeClass("is-locked").addClass("is-editing").text(`已获得编辑权 · 自动续租至 ${expiresAt}`);
  }

  async releaseEditSession() {
    window.clearInterval(this.detailState.renewTimer);
    this.detailState.renewTimer = null;
    const token = this.detailState.editToken;
    const batchName = this.detailState.batchName;
    this.detailState.editToken = "";
    this.detailState.editExpiresAt = "";
    this.detailState.dirty = false;
    if (!token || !batchName) return;
    try {
      await this.call("overseas_costing.api.edit_session.release", { batch_name: batchName, edit_token: token });
    } catch (error) {
      console.warn("[overseas-cost-workbench] 编辑租约释放失败，将在过期后自动释放", error);
    }
  }

  async confirmDiscardDetailChanges() {
    if (!this.detailState.dirty) return true;
    return new Promise((resolve) => {
      frappe.confirm(
        "当前单元格修改尚未保存，确认放弃并离开？",
        () => {
          this.$root.find(".ocw-cell-editor").each((_, editor) => this.cancelCellEdit($(editor).closest("td")));
          this.detailState.dirty = false;
          resolve(true);
        },
        () => resolve(false)
      );
    });
  }
