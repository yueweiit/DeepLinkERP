  renderShell() {
    this.$root = $(`
      <div class="ocw-page ocw-redesign" data-screen="workbench">
        <main class="ocw-workbench-screen" data-area="workbench-screen">
          <header class="ocw-redesign-header">
            <div class="ocw-redesign-title">
              <button class="ocw-icon-btn ocw-nav-toggle" type="button" data-action="toggle-module-sidebar" aria-label="展开或收起导航" title="展开或收起导航">☰</button>
              <div>
                <h1>海外成本工作台</h1>
                <p>优先处理异常批次，也可搜索已知批次核对成本。</p>
              </div>
            </div>
            <div class="ocw-header-actions">
              <div class="ocw-menu-wrap">
                <button class="ocw-outline-btn" type="button" data-action="toggle-ingest-menu" aria-expanded="false">全局工具</button>
                <div class="ocw-ingest-menu" data-area="ingest-menu" hidden>
                  <button type="button" data-action="export-current">导出当前结果</button>
                  <button type="button" data-action="file-parse">凭证对比</button>
                  <button type="button" data-action="preview-categories">商品归类</button>
                  <button type="button" data-action="pull-oa-logistics">批量钉钉拉取</button>
                  <button type="button" data-action="open-import">批量 Excel 导入</button>
                </div>
              </div>
              <button class="ocw-primary-btn" type="button" data-action="add-batch">+ 新增批次</button>
            </div>
          </header>
          <nav class="ocw-task-tabs" data-area="task-tabs" aria-label="工作任务"></nav>
          <section class="ocw-exception-summary" data-area="exception-summary" aria-label="异常摘要"></section>
          <section class="ocw-search-panel" data-area="search-panel"></section>
          <section class="ocw-batch-list-panel" data-area="batch-list"></section>
        </main>
        <main class="ocw-detail-screen" data-area="detail-screen" hidden></main>
      </div>
    `);
    $(this.page.main).empty().append(this.$root);
    this.applyDeskLayout();
    this.applyModuleSidebarPreference();
    this.renderWorkbenchLoading();
  }

  moduleSidebarStorageKey() {
    return "overseas-cost-workbench:workspace-sidebar";
  }

  moduleSidebarCollapsed() {
    try {
      const saved = window.localStorage.getItem(this.moduleSidebarStorageKey());
      return saved ? saved === "collapsed" : this.currentModuleSidebarCollapsed();
    } catch (_error) {
      return this.currentModuleSidebarCollapsed();
    }
  }

  nativeModuleSidebar() {
    return $(".body-sidebar-container").first();
  }

  setModuleSidebarCollapsed(collapsed) {
    const $workspaceSidebar = this.nativeModuleSidebar();
    $("body").toggleClass("ocw-workspace-sidebar-collapsed", collapsed);
    if ($workspaceSidebar.length) $workspaceSidebar.css("display", collapsed ? "none" : "");
  }

  currentModuleSidebarCollapsed() {
    const $workspaceSidebar = this.nativeModuleSidebar();
    return $("body").hasClass("ocw-workspace-sidebar-collapsed") || Boolean($workspaceSidebar.length && !$workspaceSidebar.is(":visible"));
  }

  persistModuleSidebarPreference(collapsed) {
    try {
      window.localStorage.setItem(this.moduleSidebarStorageKey(), collapsed ? "collapsed" : "expanded");
    } catch (_error) {
      // 无本地存储权限时仅保留当前页面状态。
    }
  }

  applyModuleSidebarPreference() {
    if (!this._moduleSidebarSnapshot) {
      const $workspaceSidebar = this.nativeModuleSidebar();
      this._moduleSidebarSnapshot = {
        bodyHadClass: $("body").hasClass("ocw-workspace-sidebar-collapsed"),
        display: $workspaceSidebar.length ? $workspaceSidebar.get(0).style.display : null,
      };
    }
    this.setModuleSidebarCollapsed(this.moduleSidebarCollapsed());
  }

  toggleModuleSidebar() {
    const collapsed = !this.currentModuleSidebarCollapsed();
    this.setModuleSidebarCollapsed(collapsed);
    this.persistModuleSidebarPreference(collapsed);
  }

  restoreModuleSidebar() {
    if (!this._moduleSidebarSnapshot) return;
    const $workspaceSidebar = this.nativeModuleSidebar();
    if ($workspaceSidebar.length && this._moduleSidebarSnapshot.display !== null) {
      $workspaceSidebar.get(0).style.display = this._moduleSidebarSnapshot.display;
    }
    $("body").toggleClass("ocw-workspace-sidebar-collapsed", this._moduleSidebarSnapshot.bodyHadClass);
    this._moduleSidebarSnapshot = null;
  }

  closeActionMenus(event) {
    if (event && $(event.target).closest(".ocw-menu-wrap").length) return;
    this.$root
      .find("[data-area='ingest-menu'], [data-area='detail-tools']")
      .prop("hidden", true);
    this.$root
      .find("[data-action='toggle-ingest-menu'], [data-action='toggle-detail-tools']")
      .attr("aria-expanded", "false");
  }

  bindRedesignEvents() {
    $(document)
      .off("click.ocwActionMenus")
      .on("click.ocwActionMenus", (event) => {
        if (!$(this.wrapper).is(":visible")) return;
        this.closeActionMenus(event);
      });
    $(window)
      .off("beforeunload.ocwDetailEdit")
      .on("beforeunload.ocwDetailEdit", (event) => {
        if (!this.detailState?.dirty) return undefined;
        event.preventDefault();
        event.returnValue = "";
        return "";
      });
    this.$root.on("click", "[data-action='toggle-module-sidebar']", () => this.toggleModuleSidebar());
    this.$root.on("click", "[data-action='toggle-ingest-menu']", (event) => {
      const $button = $(event.currentTarget);
      const $menu = this.$root.find("[data-area='ingest-menu']");
      const willOpen = $menu.prop("hidden");
      $menu.prop("hidden", !willOpen);
      $button.attr("aria-expanded", String(willOpen));
    });
    this.$root.on("click", "[data-action='set-task']", (event) => {
      this.viewState.task = $(event.currentTarget).attr("data-task") || "pending";
      this.viewState.page = 1;
      this.replaceViewState({ task: this.viewState.task, page: 1 });
      this.loadBatches();
    });
    this.$root.on("click", "[data-action='set-issue']", (event) => {
      const issue = $(event.currentTarget).attr("data-issue") || "";
      this.filters.issue = this.filters.issue === issue ? "" : issue;
      this.viewState.page = 1;
      this.replaceViewState({ issue: this.filters.issue, page: 1 });
      this.loadBatches();
    });
    this.$root.on("input", "[data-workbench-filter='q']", (event) => {
      this.viewState.q = $(event.currentTarget).val() || "";
    });
    this.$root.on("keydown", "[data-workbench-filter='q']", (event) => {
      if (event.key === "Enter") this.applyFilters();
    });
    this.$root.on("change", "[data-workbench-filter]", (event) => {
      const field = $(event.currentTarget).attr("data-workbench-filter");
      if (field === "q") return;
      this.filters[field] = $(event.currentTarget).val() || "";
    });
    this.$root.on("click", "[data-action='workbench-page']", (event) => {
      this.viewState.page = Math.max(1, Number($(event.currentTarget).attr("data-page") || 1));
      this.replaceViewState({ page: this.viewState.page });
      this.loadBatches();
    });
    this.$root.on("click", "[data-action='open-batch-detail']", (event) => {
      this.openBatchDetail($(event.currentTarget).attr("data-batch-name"));
    });
    this.$root.on("click", "[data-action='toggle-result-preview']", (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.toggleBatchResultPreview($(event.currentTarget).attr("data-batch-name"));
    });
    this.$root.on("click", "[data-action='result-preview-page']", (event) => {
      const $button = $(event.currentTarget);
      const batchName = $button.attr("data-batch-name") || this.resultPreviewState.batchName;
      const page = Math.max(1, Number($button.attr("data-page") || 1));
      this.loadBatchResultPreview(batchName, page);
    });
    this.$root.on("click", "[data-action='retry-result-preview']", () => {
      if (!this.resultPreviewState.batchName) return;
      this.loadBatchResultPreview(this.resultPreviewState.batchName, this.resultPreviewState.page, { force: true });
    });
    this.$root.on("click", "[data-action='result-preview-scroll']", (event) => {
      const direction = Number($(event.currentTarget).attr("data-direction") || 1);
      this.$root.find("[data-role='result-preview-table-scroll']").get(0)?.scrollBy({
        left: direction * 320,
        behavior: "smooth",
      });
    });
    this.$root.on("click", "[data-action='workbench-primary']", async (event) => {
      const batchName = $(event.currentTarget).attr("data-batch-name");
      const action = $(event.currentTarget).attr("data-primary-action");
      if (action === "supplement") return this.openBatchDetail(batchName, "documents");
      if (action === "recalculate") return this.recalculate(batchName);
      return this.openBatchDetail(batchName, OverseasCostWorkbenchState.detailTabForAction(action));
    });
    this.$root.on("click", "[data-action='return-workbench']", () => this.returnToWorkbench());
    this.$root.on("click", "[data-action='retry-detail']", () =>
      this.openBatchDetail(this.detailState.batchName, this.detailState.tab, { updateUrl: false })
    );
    this.$root.on("click", "[data-action='retry-detail-tab']", () => this.switchDetailTab(this.detailState.tab, { updateUrl: false }));
    this.$root.on("click", "[data-action='switch-detail-tab']", (event) =>
      this.switchDetailTab($(event.currentTarget).attr("data-tab"))
    );
    this.$root.on("click", "[data-action='view-dingtalk-approval']", () => this.switchDetailTab("dingtalk"));
    this.$root.on("click", "[data-action='open-dingtalk-packing-picker']", () =>
      this.openDingtalkPackingSourcePicker().catch((error) => this.showError(error))
    );
    this.$root.on("click", "[data-action='download-dingtalk-attachment']", (event) => {
      const $button = $(event.currentTarget);
      this.downloadDingtalkAttachmentFromDetail(
        $button.attr("data-attachment-name"), $button,
        $button.attr("data-process-instance-id"), $button.attr("data-file-id")
      ).catch((error) => this.showError(error));
    });
    this.$root.on("click", "[data-action='preview-dingtalk-attachment']", (event) => {
      const $button = $(event.currentTarget);
      this.previewDingtalkAttachmentFromDetail(
        $button.attr("data-attachment-name"),
        $button.attr("data-file-url"),
        $button.attr("data-file-name"),
        $button,
        $button.attr("data-process-instance-id"),
        $button.attr("data-file-id")
      ).catch((error) => this.showError(error));
    });
    this.$root.on("click", "[data-action='use-dingtalk-packing-source']", (event) => {
      const $button = $(event.currentTarget);
      this.openDingtalkPackingPreview(
        $button.attr("data-source-kind"),
        $button.attr("data-source-id"),
        $button.attr("data-process-instance-id"),
        $button.attr("data-file-id")
      ).catch((error) => this.showError(error));
    });
    this.$root.on("click", "[data-action='toggle-detail-tools']", (event) => {
      const $button = $(event.currentTarget);
      const $menu = this.$root.find("[data-area='detail-tools']");
      const willOpen = $menu.prop("hidden");
      $menu.prop("hidden", !willOpen);
      $button.attr("aria-expanded", String(willOpen));
    });
    this.$root.on("click", "[data-action='detail-primary']", (event) => {
      const action = $(event.currentTarget).attr("data-primary-action");
      if (action === "supplement") return this.switchDetailTab("documents");
      if (action === "recalculate") return this.recalculate(this.detailState.batchName);
      return this.switchDetailTab(OverseasCostWorkbenchState.detailTabForAction(action));
    });
    this.$root.on("click", "[data-action='detail-recalculate']", () => this.recalculate(this.detailState.batchName));
    this.$root.on("click", "[data-action='detail-export']", () => this.exportDrawerBatch().catch((error) => this.showError(error)));
    this.$root.on("click", "[data-action='detail-voucher']", () => this.openFileParseDialog(this.detailState.batchName));
    this.$root.on("click", "[data-action='detail-category']", () => this.openCategoryPreviewDialog(this.detailState.batchName));
    this.$root.on("click", "[data-action='detail-dingtalk']", () => this.openDingtalkOrder(this.detailState.batchName));
    this.$root.on("click", "[data-action='detail-repull']", () => this.repullGapDingtalk(this.detailState.batchName));
    this.$root.on("click", "[data-action='detail-excel']", () => this.openBatchExcelSupplementDialog(this.detailState.batchName));
    this.$root.on("click", "[data-action='open-voucher-record']", (event) =>
      this.openTaxCertificateRecordDialog($(event.currentTarget).attr("data-record-name"))
    );
    this.$root.on("click", "[data-action='manual-fill-gap']", (event) => {
      const $button = $(event.currentTarget);
      this.openManualGapFillDialog(this.getDetailBatch(), {
        fieldname: $button.attr("data-gap-fieldname") || "",
        label: $button.attr("data-gap-label") || $button.attr("data-slot-label") || "",
        slotCode: $button.attr("data-slot-code") || "",
        slotCodes: [$button.attr("data-slot-code") || ""].filter(Boolean),
        slotLabel: $button.attr("data-slot-label") || "",
        attachmentType: $button.attr("data-attachment-type") || "Other",
        required: $button.attr("data-required") === "1",
        logisticsType: $button.attr("data-logistics-type") || this.detectManualDocumentLogisticsType(this.getDetailBatch()),
      }, this.detailDocumentAdapter());
    });
    this.$root.on("click", "[data-action='upload-manual-document']", (event) => {
      const $button = $(event.currentTarget);
      this.openManualDocumentUploader(
        this.getDetailBatch(),
        this.detailDocumentAdapter(),
        $button.attr("data-logistics-type"),
        {
          code: $button.attr("data-slot-code"),
          label: $button.attr("data-slot-label"),
          attachmentType: $button.attr("data-attachment-type"),
          required: $button.attr("data-required") === "1",
        }
      );
    });
    this.$root.on("click", "[data-action='preview-manual-document']", (event) => {
      const $button = $(event.currentTarget);
      this.openOaAttachmentFilePreviewDialog($button.attr("data-file-url"), $button.attr("data-file-name"));
    });
    this.$root.on("click", "[data-action='download-manual-document']", (event) => {
      const $button = $(event.currentTarget);
      this.downloadFileToLocal($button.attr("data-file-url"), $button.attr("data-file-name"));
    });
    this.$root.on("click", "[data-action='delete-manual-document']", (event) => {
      const $button = $(event.currentTarget);
      this.deleteManualDocumentAttachment(
        this.getDetailBatch(),
        this.detailDocumentAdapter(),
        $button.attr("data-attachment-name"),
        $button.attr("data-logistics-type")
      ).catch((error) => this.showError(error));
    });
    this.$root.on("keydown", "[data-role='sku-keyword']", (event) => {
      if (event.key !== "Enter") return;
      this.detailState.sku.keyword = $(event.currentTarget).val() || "";
      this.detailState.sku.page = 1;
      this.loadSkuPage();
    });
    this.$root.on("click", "[data-action='sku-group']", (event) => {
      this.detailState.sku.fieldGroup = $(event.currentTarget).attr("data-field-group") || "basic";
      this.detailState.sku.page = 1;
      this.loadSkuPage();
    });
    this.$root.on("click", "[data-action='sku-page']", (event) => {
      this.detailState.sku.page = Math.max(1, Number($(event.currentTarget).attr("data-page") || 1));
      this.loadSkuPage();
    });
    this.$root.on("click", "[data-action='sku-sort']", (event) => {
      const sortBy = $(event.currentTarget).attr("data-sort-by") || "row_no";
      this.detailState.sku.sortOrder = this.detailState.sku.sortBy === sortBy && this.detailState.sku.sortOrder === "asc" ? "desc" : "asc";
      this.detailState.sku.sortBy = sortBy;
      this.detailState.sku.page = 1;
      this.loadSkuPage();
    });
    this.$root.on("click", "[data-action='sku-scroll']", (event) => {
      const direction = Number($(event.currentTarget).attr("data-direction") || 1);
      this.$root.find("[data-role='sku-table-scroll']").get(0)?.scrollBy({ left: direction * 320, behavior: "smooth" });
    });
  }

  replaceViewState(values, { push = false } = {}) {
    const nextUrl = OverseasCostWorkbenchState.buildWorkbenchUrl(window.location.href, values);
    const state = { ...(window.history.state || {}), overseasCostWorkbench: true };
    window.history[push ? "pushState" : "replaceState"](state, "", nextUrl);
    this.viewState = OverseasCostWorkbenchState.parseWorkbenchState(window.location.href);
  }

  workbenchFilters() {
    return {
      keyword: this.viewState.q || "",
      issue: this.filters.issue || "",
      business_type: this.filters.business_type || "",
      subsidiary_code: this.filters.subsidiary_code || "",
      start_date: this.filters.start_date || "",
      end_date: this.filters.end_date || "",
      erp_status: this.filters.erp_status || "",
      calculation_status: this.filters.calculation_status || "",
      include_history: 1,
    };
  }

  syncWorkbenchFiltersToUrl() {
    this.replaceViewState({
      q: this.viewState.q || "",
      issue: this.filters.issue || "",
      business_type: this.filters.business_type || "",
      subsidiary_code: this.filters.subsidiary_code || "",
      start_date: this.filters.start_date || "",
      end_date: this.filters.end_date || "",
      erp_status: this.filters.erp_status || "",
      page: this.viewState.page || 1,
    });
  }

  async applyFilters() {
    this.viewState.page = 1;
    this.syncWorkbenchFiltersToUrl();
    await this.loadBatches();
  }

  clearFilters() {
    const range = this.getDefaultPullDateRange();
    Object.assign(this.filters, {
      start_date: range.start_date,
      end_date: range.end_date,
      business_type: "",
      subsidiary_code: "",
      erp_status: "",
      calculation_status: "",
      issue: "",
    });
    this.viewState.q = "";
    this.viewState.page = 1;
    this.syncWorkbenchFiltersToUrl();
    this.loadBatches();
  }

  async loadBatches() {
    this.resetBatchResultPreview({ clearCache: true, render: false });
    this.renderWorkbenchLoading();
    try {
      const [list, summary] = await Promise.all([
        this.call("overseas_costing.api.workbench.get_batches", {
          filters_json: JSON.stringify(this.workbenchFilters()),
          task: this.viewState.task,
          page: this.viewState.page,
          page_length: 30,
        }),
        this.call("overseas_costing.api.workbench.get_summary", {
          filters_json: JSON.stringify(this.workbenchFilters()),
        }),
      ]);
      if (!list.ok) throw new Error(list.message || "工作台批次加载失败");
      this.batches = list.items || [];
      this.visibleBatches = this.batches.slice();
      this.workbenchTotal = Number(list.total || 0);
      this.exceptionCounts = (summary && summary.counts) || {};
      this.viewState.page = Number(list.page || this.viewState.page || 1);
      this.renderWorkbench();
      if (this.viewState.screen === "detail" && this.viewState.batch) {
        await this.openBatchDetail(this.viewState.batch, this.viewState.tab, { updateUrl: false });
      }
    } catch (error) {
      this.renderWorkbenchError(error);
    }
  }

  renderWorkbenchLoading() {
    if (!this.$root) return;
    this.$root.find("[data-area='batch-list']").html(`
      <div class="ocw-state-panel"><span class="ocw-spinner"></span><strong>正在加载工作台</strong></div>
    `);
  }

  renderWorkbenchError(error) {
    this.$root.find("[data-area='batch-list']").html(`
      <div class="ocw-state-panel is-error">
        <strong>工作台加载失败</strong>
        <span>${this.escape(this.normalizeErrorMessage(error))}</span>
        <button class="ocw-outline-btn" type="button" data-action="reload-batches">重新加载</button>
      </div>
    `);
  }

  renderWorkbench() {
    this.renderTaskTabs();
    this.renderExceptionSummary();
    this.renderWorkbenchSearch();
    this.renderWorkbenchBatchList();
    this.$root.attr("data-screen", "workbench");
  }

  renderTaskTabs() {
    const tasks = [
      { key: "pending", label: "待处理", hint: "优先处理资料与计算异常" },
      { key: "cost", label: "成本核对", hint: "核对已生成成本的批次" },
      { key: "erp", label: "ERP 队列", hint: "处理待推送与失败记录" },
    ];
    this.$root.find("[data-area='task-tabs']").html(
      tasks.map((task) => `
        <button class="ocw-task-tab ${this.viewState.task === task.key ? "is-active" : ""}" type="button" data-action="set-task" data-task="${task.key}">
          <strong>${task.label}</strong><span>${task.hint}</span>
        </button>
      `).join("")
    );
  }

  renderExceptionSummary() {
    const cards = [
      { key: "purchase", label: "采购资料待补", tone: "red" },
      { key: "logistics", label: "物流资料待补", tone: "orange" },
      { key: "calculation", label: "待重新计算", tone: "blue" },
      { key: "erp_failed", label: "ERP 回写异常", tone: "purple" },
    ];
    this.$root.find("[data-area='exception-summary']").html(
      cards.map((card) => `
        <button class="ocw-summary-card is-${card.tone} ${this.filters.issue === card.key ? "is-active" : ""}" type="button" data-action="set-issue" data-issue="${card.key}">
          <span>${card.label}</span><strong>${Number(this.exceptionCounts[card.key] || 0)}</strong><small>点击筛选</small>
        </button>
      `).join("")
    );
  }

  renderWorkbenchSearch() {
    const businessOptions = this.businessTypeOptions.length ? this.businessTypeOptions : this.selectOptions.business_type;
    const entityOptions = this.businessEntityOptions || [];
    this.$root.find("[data-area='search-panel']").html(`
      <div class="ocw-search-row">
        <label class="ocw-search-main"><span>查找批次或物料</span><input class="form-control" type="search" data-workbench-filter="q" value="${this.escape(this.viewState.q)}" placeholder="搜索批次号、运单号、物流单号或物料编码" /></label>
        <label><span>开始日期</span><input class="form-control" type="date" data-workbench-filter="start_date" value="${this.escape(this.filters.start_date)}" /></label>
        <label><span>结束日期</span><input class="form-control" type="date" data-workbench-filter="end_date" value="${this.escape(this.filters.end_date)}" /></label>
        <button class="ocw-primary-btn" type="button" data-action="apply-filters">查询</button>
        <button class="ocw-outline-btn" type="button" data-action="clear-filters">重置</button>
      </div>
      <div class="ocw-secondary-filter-row">
        <label><span>业务类型</span><select class="form-control" data-workbench-filter="business_type" data-filter="business_type">
          <option value="">全部业务类型</option>
          ${businessOptions.map((option) => {
            const value = typeof option === "string" ? option : option.value;
            const label = typeof option === "string" ? this.businessTypeLabel(option) : option.label;
            return `<option value="${this.escape(value)}" ${this.filters.business_type === value ? "selected" : ""}>${this.escape(label)}</option>`;
          }).join("")}
        </select></label>
        <label><span>业务主体</span><select class="form-control" data-workbench-filter="subsidiary_code" data-filter="subsidiary_code">
          <option value="">全部业务主体</option>
          ${entityOptions.map((value) => `<option value="${this.escape(value)}" ${this.filters.subsidiary_code === value ? "selected" : ""}>${this.escape(value)}</option>`).join("")}
        </select></label>
        <label><span>ERP 状态</span><select class="form-control" data-workbench-filter="erp_status">
          <option value="">全部 ERP 状态</option>
          <option value="pending" ${this.filters.erp_status === "pending" ? "selected" : ""}>待推送</option>
          <option value="failed" ${this.filters.erp_status === "failed" ? "selected" : ""}>推送失败</option>
          <option value="success" ${this.filters.erp_status === "success" ? "selected" : ""}>推送成功</option>
        </select></label>
        <span class="ocw-result-copy">共 ${this.workbenchTotal} 个批次${this.filters.issue ? " · 已按异常筛选" : ""}</span>
      </div>
    `);
  }

  issueLabel(issue) {
    return {
      purchase: "采购资料不完整",
      logistics: "物流资料不完整",
      calculation: "成本待计算",
      erp_failed: "ERP 回写失败",
      ready: "可核对",
    }[issue] || "待核对";
  }

  resultPreviewCacheKey(batchName, page) {
    const batch = (this.batches || []).find((row) => row.name === batchName);
    const currentVersion = batch?.current_version || "current";
    return `${batchName}:${currentVersion}:${Math.max(1, Number(page || 1))}`;
  }

  cleanupResultPreviewScrollControls() {
    if (this._resultPreviewScrollCleanup) this._resultPreviewScrollCleanup();
    this._resultPreviewScrollCleanup = null;
  }

  resetBatchResultPreview({ clearCache = false, render = true } = {}) {
    const requestId = Number(this.resultPreviewState?.requestId || 0) + 1;
    this.cleanupResultPreviewScrollControls();
    this.resultPreviewState = {
      batchName: "",
      page: 1,
      loading: false,
      error: "",
      data: null,
      requestId,
    };
    if (clearCache) this.resultPreviewCache.clear();
    if (render) this.renderWorkbenchBatchList();
  }

  async toggleBatchResultPreview(batchName) {
    if (!batchName) return;
    if (this.resultPreviewState.batchName === batchName) {
      this.resetBatchResultPreview();
      return;
    }
    this.cleanupResultPreviewScrollControls();
    this.resultPreviewState = {
      ...this.resultPreviewState,
      batchName,
      page: 1,
      loading: false,
      error: "",
      data: null,
    };
    await this.loadBatchResultPreview(batchName, 1);
  }

  async loadBatchResultPreview(batchName, page = 1, { force = false } = {}) {
    if (!batchName) return;
    page = Math.max(1, Number(page || 1));
    const cacheKey = this.resultPreviewCacheKey(batchName, page);
    const cached = force ? null : this.resultPreviewCache.get(cacheKey);
    const requestId = Number(this.resultPreviewState?.requestId || 0) + 1;
    this.resultPreviewState = {
      ...this.resultPreviewState,
      batchName,
      page,
      loading: !cached,
      error: "",
      data: cached || null,
      requestId,
    };
    this.renderWorkbenchBatchList();
    if (cached) return;

    try {
      const result = await this.call("overseas_costing.api.workbench.get_batch_result_preview", {
        batch_name: batchName,
        page,
        page_length: 20,
      });
      if (this.resultPreviewState.requestId !== requestId || this.resultPreviewState.batchName !== batchName) return;
      if (!result?.ok) throw new Error(result?.message || "SKU 核算结果加载失败");
      this.resultPreviewCache.set(cacheKey, result);
      this.resultPreviewState = {
        ...this.resultPreviewState,
        page: Number(result.page || page),
        loading: false,
        error: "",
        data: result,
      };
      this.renderWorkbenchBatchList();
    } catch (error) {
      if (this.resultPreviewState.requestId !== requestId || this.resultPreviewState.batchName !== batchName) return;
      this.resultPreviewState = {
        ...this.resultPreviewState,
        loading: false,
        error: this.normalizeErrorMessage(error),
        data: null,
      };
      this.renderWorkbenchBatchList();
    }
  }

  formatResultPreviewMoney(value, currency = "RMB") {
    if (value === null || value === undefined || value === "") return "未计算";
    const amount = this.formatMoney(value);
    return `${amount}${currency ? ` ${currency}` : ""}`;
  }

  renderBatchResultPreviewState() {
    const state = this.resultPreviewState;
    if (state.loading) {
      return `
        <section class="ocw-result-preview ocw-result-preview-state" aria-live="polite">
          <span class="ocw-spinner"></span><strong>正在加载 SKU 核算结果</strong>
        </section>
      `;
    }
    if (state.error) {
      return `
        <section class="ocw-result-preview ocw-result-preview-state is-error" aria-live="polite">
          <strong>SKU 核算结果加载失败</strong>
          <span>${this.escape(state.error)}</span>
          <button class="ocw-outline-btn" type="button" data-action="retry-result-preview">重试</button>
        </section>
      `;
    }
    return this.renderBatchResultPreview(state.data || {});
  }

  renderBatchResultPreview(data) {
    const summary = data.summary || {};
    const purchaseTotals = Array.isArray(summary.purchase_totals) ? summary.purchase_totals : [];
    const purchaseTotalHtml = purchaseTotals.length
      ? purchaseTotals.map((row) => `<span>${this.escape(this.formatResultPreviewMoney(row.amount, row.currency || ""))}</span>`).join("")
      : "<span>未计算</span>";
    const calculationPending = summary.calculation_status === "pending";
    const otherCost = Number(summary.unlisted_other_cost_rmb || 0);
    const items = Array.isArray(data.items) ? data.items : [];
    const page = Math.max(1, Number(data.page || 1));
    const pageCount = Math.max(1, Number(data.page_count || 1));
    const total = Math.max(0, Number(data.total || 0));
    const moneyCell = (value, currency = "RMB") => this.escape(this.formatResultPreviewMoney(value, currency));
    const sourceMoneyCell = (value, currency = "") => {
      return this.escape(this.formatResultPreviewMoney(value, currency));
    };
    const columns = [
      "物料编码",
      "产品名称",
      "规格型号",
      "原始采购单价",
      "采购数量",
      "分摊运费",
      "分摊关税/税费",
      "分摊清关",
      "单品综合单价",
    ];
    const headerClass = (index) => index === 0 ? " is-sticky-code" : index === 1 ? " is-sticky-name" : "";
    const visualHeaders = columns.map((label, index) =>
      `<th class="ocw-result-cell${headerClass(index)}">${this.escape(label)}</th>`
    ).join("");
    const semanticHeaders = columns.map((label, index) =>
      `<th id="ocw-result-preview-column-${index + 1}" scope="col">${this.escape(label)}</th>`
    ).join("");
    const columnClasses = [
      "is-code",
      "is-name",
      "is-spec",
      "is-unit-price",
      "is-quantity",
      "is-freight",
      "is-tax",
      "is-clearance",
      "is-total-unit",
    ];
    const columnGroup = `<colgroup>${columnClasses.map((className) => `<col class="ocw-result-col ${className}" />`).join("")}</colgroup>`;
    const cellHeaders = (index) => ` headers="ocw-result-preview-column-${index + 1}"`;
    const rows = items.map((item) => `
      <tr>
        <td class="ocw-result-cell is-sticky-code"${cellHeaders(0)} title="${this.escape(item.material_code || "")}"><span>${this.escape(item.material_code || "—")}</span></td>
        <td class="ocw-result-cell is-sticky-name"${cellHeaders(1)} title="${this.escape(item.product_name || "")}"><span>${this.escape(item.product_name || "—")}</span></td>
        <td class="ocw-result-cell"${cellHeaders(2)} title="${this.escape(item.spec_model || "")}">${this.escape(item.spec_model || "—")}</td>
        <td class="ocw-result-cell is-number"${cellHeaders(3)}>${sourceMoneyCell(item.unit_price, item.purchase_currency || "")}</td>
        <td class="ocw-result-cell is-number"${cellHeaders(4)}>${this.escape(this.formatNumber(item.quantity) || "—")}</td>
        <td class="ocw-result-cell is-number"${cellHeaders(5)}>${moneyCell(item.freight_alloc_rmb)}</td>
        <td class="ocw-result-cell is-number"${cellHeaders(6)}>${moneyCell(item.tax_alloc_rmb)}</td>
        <td class="ocw-result-cell is-number"${cellHeaders(7)}>${moneyCell(item.clearance_alloc_rmb)}</td>
        <td class="ocw-result-cell is-number"${cellHeaders(8)}>${moneyCell(item.total_unit_rmb)}</td>
      </tr>
    `).join("");

    return `
      <section class="ocw-result-preview" aria-label="当前批次 SKU 核算结果">
        <div class="ocw-result-table-shell">
          <div class="ocw-result-sticky-dock" data-role="result-preview-sticky-dock">
            <div class="ocw-result-summary">
              <div><span>批次号</span><strong>${this.escape(summary.batch_no || "—")}</strong></div>
              <div><span>物流单号</span><strong>${this.escape(summary.logistics_no || "未填写")}</strong></div>
              <div><span>批次总货值</span><strong class="ocw-result-summary-stack">${purchaseTotalHtml}</strong></div>
              <div><span>总运费</span><strong>${moneyCell(summary.total_freight_rmb)}</strong></div>
              <div><span>总关税/税费</span><strong>${moneyCell(summary.total_tax_rmb)}</strong></div>
              <div><span>总清关费</span><strong>${moneyCell(summary.total_clearance_rmb)}</strong></div>
              <div><span>总数量</span><strong>${this.escape(this.formatNumber(summary.total_quantity) || "0")}</strong></div>
              <div><span>批次加权综合单价</span><strong>${moneyCell(summary.weighted_total_unit_rmb)}</strong></div>
            </div>
            ${otherCost > 0 ? `<p class="ocw-result-other-cost">另有 ${moneyCell(otherCost)} 其他费用已计入综合单价</p>` : ""}
            ${calculationPending ? `<p class="ocw-result-pending-note">当前版本尚未完成计算，核算结果显示为“未计算”。</p>` : ""}
            <div class="ocw-result-scroll-controls">
              <button class="ocw-scroll-arrow" type="button" data-action="result-preview-scroll" data-direction="-1" aria-label="向左滚动 SKU 结果">‹</button>
              <input class="ocw-result-scrollbar" type="range" min="0" max="0" step="1" value="0" data-role="result-preview-scrollbar" aria-label="横向滚动 SKU 结果" disabled />
              <button class="ocw-scroll-arrow" type="button" data-action="result-preview-scroll" data-direction="1" aria-label="向右滚动 SKU 结果">›</button>
            </div>
            <div class="ocw-result-header-scroll" data-role="result-preview-header-scroll" aria-hidden="true">
              <table class="ocw-result-table ocw-result-header-table" role="presentation">
                ${columnGroup}
                <thead><tr>${visualHeaders}</tr></thead>
              </table>
            </div>
          </div>
          <div class="ocw-result-table-scroll" data-role="result-preview-table-scroll">
            <table class="ocw-result-table ocw-result-data-table" aria-label="当前批次 SKU 核算明细" aria-colcount="9">
              ${columnGroup}
              <thead class="ocw-result-semantic-head"><tr>${semanticHeaders}</tr></thead>
              <tbody>${rows || `<tr><td class="ocw-result-empty" colspan="9">当前批次没有 SKU 明细</td></tr>`}</tbody>
            </table>
          </div>
        </div>
        <div class="ocw-result-pagination">
          <span>共 ${total} 个 SKU</span>
          <div>
            <button class="ocw-outline-btn" type="button" data-action="result-preview-page" data-batch-name="${this.escape(data.batch_name || this.resultPreviewState?.batchName || "")}" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>上一页</button>
            <span>第 ${page} / ${pageCount} 页</span>
            <button class="ocw-outline-btn" type="button" data-action="result-preview-page" data-batch-name="${this.escape(data.batch_name || this.resultPreviewState?.batchName || "")}" data-page="${page + 1}" ${page >= pageCount ? "disabled" : ""}>下一页</button>
          </div>
        </div>
      </section>
    `;
  }

  shouldCompactResultPreviewColumns(scrollLeft, currentlyCompact = false) {
    const position = Math.max(0, Number(scrollLeft) || 0);
    return currentlyCompact ? position > 32 : position > 148;
  }

  bindResultPreviewScrollControls() {
    this.cleanupResultPreviewScrollControls();
    const tableScroll = this.$root.find("[data-role='result-preview-table-scroll']").get(0);
    const headerScroll = this.$root.find("[data-role='result-preview-header-scroll']").get(0);
    const range = this.$root.find("[data-role='result-preview-scrollbar']").get(0);
    const $preview = this.$root.find(".ocw-result-preview");
    if (!tableScroll || !headerScroll || !range) return;
    const table = tableScroll.querySelector(".ocw-result-data-table");
    const headerTable = headerScroll.querySelector(".ocw-result-header-table");
    let syncing = false;
    let compact = false;
    let refreshFrame = null;
    let resizeObserver = null;

    const updateCompactState = (scrollLeft) => {
      const nextCompact = this.shouldCompactResultPreviewColumns(scrollLeft, compact);
      if (nextCompact === compact) return;
      compact = nextCompact;
      $preview.toggleClass("is-result-compact", compact);
      scheduleUpdate();
    };
    const update = () => {
      const max = Math.max(0, tableScroll.scrollWidth - tableScroll.clientWidth);
      const left = Math.min(max, Math.max(0, tableScroll.scrollLeft));
      if (tableScroll.scrollLeft !== left) tableScroll.scrollLeft = left;
      headerScroll.scrollLeft = left;
      range.max = String(max);
      range.value = String(left);
      range.disabled = max <= 1;
      this.$root.find("[data-action='result-preview-scroll'][data-direction='-1']").prop("disabled", max <= 1 || left <= 1);
      this.$root.find("[data-action='result-preview-scroll'][data-direction='1']").prop("disabled", max <= 1 || left >= max - 1);
      updateCompactState(left);
    };
    const scheduleUpdate = () => {
      if (refreshFrame !== null) return;
      refreshFrame = window.requestAnimationFrame(() => {
        refreshFrame = null;
        update();
      });
    };
    const onScroll = () => {
      if (syncing) return;
      syncing = true;
      update();
      syncing = false;
    };
    const onInput = () => {
      if (syncing) return;
      syncing = true;
      const max = Math.max(0, tableScroll.scrollWidth - tableScroll.clientWidth);
      tableScroll.scrollLeft = Math.min(max, Math.max(0, Number(range.value || 0)));
      update();
      syncing = false;
    };
    const onColumnTransitionEnd = (event) => {
      if (!event.target.classList?.contains("ocw-result-cell")) return;
      scheduleUpdate();
    };
    tableScroll.addEventListener("scroll", onScroll, { passive: true });
    range.addEventListener("input", onInput);
    table?.addEventListener("transitionend", onColumnTransitionEnd);
    headerTable?.addEventListener("transitionend", onColumnTransitionEnd);
    window.addEventListener("resize", scheduleUpdate);
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(scheduleUpdate);
      resizeObserver.observe(tableScroll);
      if (table) resizeObserver.observe(table);
      if (headerTable) resizeObserver.observe(headerTable);
    }
    update();
    this._resultPreviewScrollCleanup = () => {
      tableScroll.removeEventListener("scroll", onScroll);
      range.removeEventListener("input", onInput);
      table?.removeEventListener("transitionend", onColumnTransitionEnd);
      headerTable?.removeEventListener("transitionend", onColumnTransitionEnd);
      window.removeEventListener("resize", scheduleUpdate);
      resizeObserver?.disconnect();
      if (refreshFrame !== null) window.cancelAnimationFrame(refreshFrame);
      $preview.removeClass("is-result-compact");
    };
  }

  renderWorkbenchBatchList() {
    const pageCount = Math.ceil(this.workbenchTotal / 30);
    const rows = this.batches.map((batch) => this.renderWorkbenchBatchRow(batch)).join("");
    const $batchList = this.$root.find("[data-area='batch-list']");
    $batchList.toggleClass("has-expanded-preview", Boolean(this.resultPreviewState?.batchName));
    $batchList.html(`
      <div class="ocw-list-head">
        <div><h2>${this.viewState.task === "pending" ? "异常批次" : this.viewState.task === "erp" ? "ERP 处理队列" : "成本核对批次"}</h2><span>${this.workbenchTotal} 个结果</span></div>
        <span>点击批次号或“查看详情”进入全宽详情</span>
      </div>
      <div class="ocw-batch-grid ocw-batch-grid-head" aria-hidden="true">
        <span></span><span>批次 / 物流单号</span><span>业务类型 / SKU</span><span>当前问题</span><span>采购货值</span><span>综合成本</span><span>更新时间</span><span>下一步</span>
      </div>
      <div class="ocw-batch-grid-body">
        ${rows || `<div class="ocw-state-panel"><strong>当前条件下没有批次</strong><span>可清空筛选或切换任务视图。</span></div>`}
      </div>
      <div class="ocw-pagination">
        <button class="ocw-outline-btn" type="button" data-action="workbench-page" data-page="${this.viewState.page - 1}" ${this.viewState.page <= 1 ? "disabled" : ""}>上一页</button>
        <span>第 ${this.viewState.page} / ${Math.max(pageCount, 1)} 页</span>
        <button class="ocw-outline-btn" type="button" data-action="workbench-page" data-page="${this.viewState.page + 1}" ${this.viewState.page >= pageCount ? "disabled" : ""}>下一页</button>
      </div>
    `);
    window.requestAnimationFrame(() => this.bindResultPreviewScrollControls());
  }

  renderWorkbenchBatchRow(batch) {
    const reference = batch.batch_no || batch.source_approval_no || batch.name;
    const logisticsNo = batch.waybill_no || batch.customs_no || "未填写物流单号";
    const action = OverseasCostWorkbenchState.primaryActionForIssue(batch.primary_issue);
    const totalCost = batch.actual_total_cost_rmb || batch.estimated_total_cost_rmb;
    const expanded = this.resultPreviewState?.batchName === batch.name;
    return `
      <div class="ocw-workbench-record ${expanded ? "is-expanded" : ""}" data-batch-name="${this.escape(batch.name)}">
        <article class="ocw-batch-grid ocw-workbench-row">
          <button class="ocw-result-preview-toggle" type="button" data-action="toggle-result-preview" data-batch-name="${this.escape(batch.name)}" aria-expanded="${expanded}" aria-label="${expanded ? "收起" : "展开"} ${this.escape(reference)} 的 SKU 核算结果">
            <span aria-hidden="true">›</span>
          </button>
          <div class="ocw-batch-identity">
            <button type="button" class="ocw-batch-link" data-action="open-batch-detail" data-batch-name="${this.escape(batch.name)}">${this.escape(reference)}</button>
            <span>${this.escape(logisticsNo)}</span>
          </div>
          <div><strong>${this.escape(this.businessTypeLabel(batch.business_type) || batch.transport_mode || "-")}</strong><span>${Number(batch.item_count || 0)} 个 SKU</span></div>
          <div><strong class="ocw-issue is-${this.escape(batch.primary_issue)}">${this.escape(this.issueLabel(batch.primary_issue))}</strong><span>${this.escape((batch.issue_codes || []).map((code) => this.issueLabel(code)).join("、") || "资料可用")}</span></div>
          <div><strong>${this.escape(this.formatMoney(batch.total_goods_value || 0))}</strong><span>RMB</span></div>
          <div><strong>${this.escape(this.formatMoney(totalCost || 0))}</strong><span>RMB</span></div>
          <div><strong>${this.escape(this.formatDateTimeMinute(batch.modified) || "-")}</strong><span>${this.escape(batch.status || "")}</span></div>
          <div class="ocw-row-actions">
            <button class="ocw-primary-btn" type="button" data-action="workbench-primary" data-primary-action="${action.action}" data-batch-name="${this.escape(batch.name)}">${action.label}</button>
            <button class="ocw-outline-btn" type="button" data-action="row-more" data-batch-name="${this.escape(batch.name)}">更多</button>
          </div>
        </article>
        ${expanded ? this.renderBatchResultPreviewState() : ""}
      </div>
    `;
  }

  async handleWorkbenchPopState() {
    const previousDetailBatch = this.detailState.batchName;
    this.viewState = OverseasCostWorkbenchState.parseWorkbenchState(window.location.href);
    if (this.viewState.screen === "detail" && this.viewState.batch) {
      await this.openBatchDetail(this.viewState.batch, this.viewState.tab, { updateUrl: false });
      return;
    }
    if (previousDetailBatch && this.detailState.editToken) {
      await this.releaseEditSession();
    }
    this.detailState.requestId += 1;
    this.detailState.skuRequestId += 1;
    this.detailState.refreshRequestId += 1;
    this.detailState.batchName = "";
    this.detailState.header = null;
    this.detailState.detail = null;
    this.exportPinnedBatchName = "";
    this.dataCheckBatchName = "";
    this.drawerBatchName = "";
    this.$root.find("[data-area='detail-screen']").prop("hidden", true);
    this.$root.find("[data-area='workbench-screen']").prop("hidden", false);
    await this.loadBatches();
    requestAnimationFrame(() => window.scrollTo({ top: Number(window.history.state?.ocwScrollY || 0), behavior: "auto" }));
  }
