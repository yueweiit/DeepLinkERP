  ensureMaterialFeeState() {
    const batchName = String(this.detailState.batchName || "");
    if (!this.materialFeeState || this.materialFeeState.batchName !== batchName) {
      this.materialFeeState = {
        batchName,
        page: 1,
        pageLength: 200,
        onlyMissing: false,
        showAuxiliary: false,
        loading: false,
        requestId: 0,
        materials: null,
        fees: null,
        preview: null,
      };
    }
    return this.materialFeeState;
  }

  bindMaterialFeeWorkspaceEvents() {
    this.$root.on("click", "[data-action='mf-reload']", () => this.loadMaterialFeeWorkspace());
    this.$root.on("click", "[data-action='mf-toggle-missing']", () => {
      const state = this.ensureMaterialFeeState();
      state.onlyMissing = !state.onlyMissing;
      this.renderMaterialFeeWorkspace();
    });
    this.$root.on("click", "[data-action='mf-toggle-aux']", () => {
      const state = this.ensureMaterialFeeState();
      state.showAuxiliary = !state.showAuxiliary;
      this.renderMaterialFeeWorkspace();
    });
    this.$root.on("click", "[data-action='mf-material-page']", (event) => {
      const state = this.ensureMaterialFeeState();
      state.page = Math.max(1, Number($(event.currentTarget).attr("data-page") || 1));
      this.loadMaterialFeeWorkspace();
    });
    this.$root.on("click", "[data-action='mf-edit-fee']", (event) => {
      this.openMaterialFeeDialog($(event.currentTarget).attr("data-fee-key"));
    });
    this.$root.on("click", "[data-action='mf-link-evidence']", (event) => {
      this.openMaterialFeeEvidenceDialog($(event.currentTarget).attr("data-fee-key"));
    });
    this.$root.on("click", "[data-action='mf-evidence-status']", (event) => {
      const $button = $(event.currentTarget);
      this.setMaterialFeeEvidenceStatus(
        $button.attr("data-evidence-name"),
        $button.attr("data-status")
      ).catch((error) => this.showError(error));
    });
    this.$root.on("click", "[data-action='mf-preview-cost']", () => {
      this.refreshMaterialFeeCostPreview(true).catch((error) => this.showError(error));
    });
    this.$root.on("click", "[data-action='mf-show-sources']", () => this.openMaterialFeeSourcesDialog());
    this.$root.on("click", "[data-action='mf-import-xlsx']", () => this.openMaterialXlsxUploader());
    this.$root.on("click", "[data-action='mf-import-wiki']", () => {
      this.openWikiMaterialImportDialog().catch((error) => this.showError(error));
    });
    this.$root.on("focus", "[data-mf-fee-input]", (event) => {
      $(event.currentTarget).closest(".ocw-mf-fee-amount-cell").removeClass("is-save-error").attr("title", "");
    });
    this.$root.on("keydown", "[data-mf-fee-input]", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      event.currentTarget.blur();
    });
    this.$root.on("blur", "[data-mf-fee-input]", (event) => {
      this.saveMaterialFeeInlineAmount($(event.currentTarget)).catch((error) => this.showError(error));
    });
    this.$root.on("focus", "[data-mf-cell-input]", (event) => {
      $(event.currentTarget).closest(".ocw-mf-cell").removeClass("is-save-error").attr("title", "");
    });
    this.$root.on("keydown", "[data-mf-cell-input]", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      event.currentTarget.blur();
    });
    this.$root.on("blur", "[data-mf-cell-input]", (event) => {
      this.saveMaterialFeeCell($(event.currentTarget)).catch((error) => this.showError(error));
    });
    this.$root.on("paste", "[data-mf-cell-input]", (event) => {
      const clipboard = event.originalEvent?.clipboardData?.getData("text/plain") || "";
      if (!clipboard.includes("\t") && !clipboard.includes("\n") && !clipboard.includes("\r")) return;
      event.preventDefault();
      this.previewMaterialPaste($(event.currentTarget), clipboard);
    });
  }

  async loadMaterialFeeWorkspace(options = {}) {
    const state = this.ensureMaterialFeeState();
    const batch = this.getDetailBatch();
    const requestId = ++state.requestId;
    state.loading = true;
    if (!options.quiet) this.renderDetailTabLoading("正在读取费用、凭证和物料表");
    try {
      const [materials, fees, preview] = await Promise.all([
        this.call("overseas_costing.api.materials.get_material_grid", {
          batch_name: batch.name,
          version_name: this.detailState.versionName || batch.current_version || null,
          page: state.page,
          page_length: state.pageLength,
        }),
        this.call("overseas_costing.api.fees.get_fee_worklist", {
          batch_name: batch.name,
          version_name: this.detailState.versionName || batch.current_version || null,
        }),
        this.call("overseas_costing.api.calculate.preview_comprehensive_cost", {
          batch_name: batch.name,
          version_name: this.detailState.versionName || batch.current_version || null,
        }),
      ]);
      if (requestId !== state.requestId || this.detailState.tab !== "documents") return;
      state.materials = materials;
      state.fees = fees;
      state.preview = preview;
      state.loading = false;
      this.renderMaterialFeeWorkspace();
    } catch (error) {
      if (requestId !== state.requestId || this.detailState.tab !== "documents") return;
      state.loading = false;
      this.renderDetailTabError("资料与费用", error);
    }
  }

  materialFeeBasisLabel(value) {
    return {
      goods_value: "采购货值",
      gross_weight: "毛重",
      volume: "体积",
      chargeable_weight: "计费重",
    }[String(value || "")] || String(value || "--");
  }

  materialFeeAmountStatus(value) {
    return {
      MISSING: { label: "待补", tone: "danger" },
      ESTIMATED: { label: "暂估", tone: "warn" },
      ACTUAL: { label: "实际", tone: "ok" },
      NOT_INCURRED: { label: "未发生", tone: "neutral" },
      INCLUDED: { label: "已包含", tone: "neutral" },
    }[String(value || "MISSING").toUpperCase()] || { label: String(value || "待补"), tone: "danger" };
  }

  materialFeeEvidenceLabel(value) {
    return {
      VALID: { label: "已核对", tone: "ok" },
      PENDING: { label: "已关联", tone: "info" },
      INVALID: { label: "需重补", tone: "danger" },
      MISSING: { label: "待补", tone: "danger" },
      NOT_REQUIRED: { label: "无需凭证", tone: "neutral" },
    }[String(value || "MISSING").toUpperCase()] || { label: String(value || "待补"), tone: "danger" };
  }

  materialFeeEvidenceFinalLabel(value) {
    return {
      VALID: "已确认有效",
      PENDING: "待核对",
      INVALID: "已标记无效",
    }[String(value || "PENDING").toUpperCase()] || String(value || "待核对");
  }

  renderMaterialFeeWorkspace() {
    const state = this.ensureMaterialFeeState();
    if (!state.materials || !state.fees || !state.preview) return;
    const materialSummary = state.materials || {};
    const feeSummary = state.fees.summary || {};
    const evidencePending = Number(feeSummary.missing_evidence_fee_count || 0);
    const previewSummary = state.preview.summary || {};
    const $content = this.$root.find("[data-area='detail-content']");
    $content.html(`
      <div class="ocw-mf-workspace">
        <div class="ocw-detail-section-head ocw-mf-page-head">
          <div><span>资料与费用</span><h2>综合成本资料工作区</h2><p>没有装箱计划也可以先用 OA 资料预览；正式推送前再补齐红色缺项和未定费用。</p></div>
          <div class="ocw-detail-section-actions">
            <button class="ocw-outline-btn" type="button" data-action="mf-show-sources">查看资料来源</button>
            <button class="ocw-outline-btn" type="button" data-action="mf-reload">刷新</button>
          </div>
        </div>
        <div class="ocw-mf-alert-strip" aria-label="当前待办摘要">
          ${this.renderMaterialFeeMetric("计算红格", materialSummary.missing_cell_count || 0, "danger")}
          ${this.renderMaterialFeeMetric("费用未定", feeSummary.missing_amount_fee_count || 0, "danger")}
          ${this.renderMaterialFeeMetric("凭证待补", evidencePending, evidencePending ? "warn" : "ok")}
          ${this.renderMaterialFeeMetric("暂估待核", feeSummary.estimated_fee_count || 0, Number(feeSummary.estimated_fee_count || 0) ? "warn" : "ok")}
        </div>
        <section class="ocw-mf-section ocw-mf-fee-section">
          <div class="ocw-mf-section-title"><div><span>01</span><h3>费用与凭证</h3><p>五类费用会按运输方式显示；只有修改并保存后才会入库。</p></div></div>
          <div class="ocw-mf-fee-layout">
            <div class="ocw-mf-fee-table-wrap">${this.renderMaterialFeeTable(state.fees.fees || state.fees.items || [])}</div>
            <aside class="ocw-mf-preview-card">
              <span>当前试算</span>
              <strong>RMB ${this.escape(previewSummary.total_cost_rmb || "0.00")}</strong>
              <small>${previewSummary.is_complete ? "已纳入的资料可完整试算" : `非完整成本 · ${Number(previewSummary.excluded_fee_count || 0)} 笔未计入`}</small>
              <dl>
                <div><dt>采购金额</dt><dd>${this.escape(previewSummary.purchase_goods_value_rmb || "0.00")}</dd></div>
                <div><dt>直接费用</dt><dd>${this.escape(previewSummary.direct_fees_rmb || "0.00")}</dd></div>
                <div><dt>分摊费用</dt><dd>${this.escape(previewSummary.allocated_fees_rmb || "0.00")}</dd></div>
              </dl>
              <button class="ocw-primary-btn" type="button" data-action="mf-preview-cost">预览综合单价</button>
              <em>只读试算，不创建成本版本，不改变 ERP 状态。</em>
            </aside>
          </div>
        </section>
        <section class="ocw-mf-section ocw-mf-material-section">
          <div class="ocw-mf-section-title ocw-mf-material-title">
            <div><span>02</span><h3>物料与装箱数据</h3><p>采购事实保持只读；蓝色发货数量表示默认等于采购数量，红格可直接补录。</p></div>
            <div class="ocw-mf-material-actions">
              <button class="ocw-outline-btn ${state.onlyMissing ? "is-active" : ""}" type="button" data-action="mf-toggle-missing">只看缺项</button>
              <button class="ocw-outline-btn ${state.showAuxiliary ? "is-active" : ""}" type="button" data-action="mf-toggle-aux">展开辅助列</button>
              <button class="ocw-primary-btn" type="button" data-action="mf-import-wiki">从装箱计划表获取</button>
              <button class="ocw-primary-btn" type="button" data-action="mf-import-xlsx">导入 Excel 补资料</button>
            </div>
          </div>
          ${this.renderMaterialFeeGrid()}
        </section>
        ${this.renderMaterialFeeTodos()}
        ${this.renderMaterialFeeCostTable()}
      </div>
    `);
  }

  renderMaterialFeeMetric(label, value, tone) {
    const number = Number(value || 0);
    return `<div class="ocw-mf-metric is-${this.escape(tone)}"><span>${this.escape(label)}</span><strong>${this.escape(String(number))}</strong><em>${number ? "待处理" : "已清零"}</em></div>`;
  }

  renderMaterialFeeTable(fees) {
    if (!fees.length) return `<div class="ocw-detail-empty"><strong>暂无费用清单</strong></div>`;
    return `
      <table class="ocw-mf-fee-table">
        <thead><tr><th>费用项目</th><th>状态</th><th>原币金额</th><th>分摊依据</th><th>凭证</th><th>操作</th></tr></thead>
        <tbody>${fees.map((fee) => this.renderMaterialFeeRow(fee)).join("")}</tbody>
      </table>
    `;
  }

  renderMaterialFeeRow(fee) {
    const amountInfo = this.materialFeeAmountStatus(fee.amount_state || fee.amount_status);
    const evidenceInfo = this.materialFeeEvidenceLabel(fee.evidence_state);
    const allocation = fee.allocation || {};
    const allocationBlocked = ["ESTIMATED", "ACTUAL"].includes(String(fee.amount_state || fee.amount_status || "")) && allocation.status !== "ALLOCATED";
    const scopeLabel = String(fee.scope_type || "ALL_ITEMS") === "ALL_ITEMS" ? "全批物料" : String(fee.scope_type) === "DIRECT_ITEM" ? "指定单行" : "指定物料";
    const amountStatus = String(fee.amount_state || fee.amount_status || "MISSING").toUpperCase();
    const amount = fee.amount ?? "";
    const currency = String(fee.currency || "RMB");
    const missingSavedAmount = amountStatus === "MISSING" && amount !== "";
    const evidence = fee.evidence || [];
    return `
      <tr class="${fee.legacy_unmapped || fee.requires_review ? "is-review" : ""}">
        <td><strong>${this.escape(fee.expense_category || fee.logical_fee_key || "--")}</strong><small>${fee.virtual ? "默认项 · 未入库" : fee.legacy_unmapped ? "历史费用 · 请核对" : "已保存"}</small></td>
        <td><span class="ocw-mf-badge is-${amountInfo.tone}">${this.escape(amountInfo.label)}</span></td>
        <td class="ocw-mf-fee-amount-cell">
          <div class="ocw-mf-fee-inline-fields">
            <input data-mf-fee-input="currency" data-mf-fee-currency="1" data-fee-key="${this.escape(fee.logical_fee_key || fee.fee_key || "")}" data-original-value="${this.escape(currency)}" value="${this.escape(currency)}" maxlength="3" pattern="[A-Za-z]{3}" autocomplete="off" spellcheck="false" aria-label="币种" />
            <input data-mf-fee-input="amount" data-mf-fee-amount="1" data-fee-key="${this.escape(fee.logical_fee_key || fee.fee_key || "")}" data-original-value="${this.escape(amount)}" value="${this.escape(amount)}" ${missingSavedAmount ? 'data-mf-force-actual="1"' : ""} inputmode="decimal" aria-label="原币金额" />
          </div>
          <small data-mf-fee-amount-hint="1">${missingSavedAmount ? "尚未计入 · 按 Enter 或离开后确认为实际" : "Enter 或失焦自动保存为实际"}</small>
        </td>
        <td><span class="${allocationBlocked ? "ocw-mf-inline-error" : ""}">${this.escape(this.materialFeeBasisLabel(fee.allocation_basis || fee.basis_field))}</span><small>${allocationBlocked ? "暂未计入试算 · 当前依据缺失，未自动改规则" : scopeLabel}</small></td>
        <td><span class="ocw-mf-badge is-${evidenceInfo.tone}">${this.escape(evidenceInfo.label)}</span><small>${evidence.length ? `${evidence.length} 份已关联` : "可上传或关联已有资料"}</small></td>
        <td><div class="ocw-mf-row-actions"><button type="button" data-action="mf-edit-fee" data-fee-key="${this.escape(fee.logical_fee_key || "")}">更多设置</button><button type="button" data-action="mf-link-evidence" data-fee-key="${this.escape(fee.logical_fee_key || "")}">关联凭证</button></div>
          <details class="ocw-mf-row-details"><summary>范围与凭证详情</summary><div><span>适用：${this.escape(scopeLabel)}</span>${evidence.length ? evidence.map((row) => `<span>${this.escape(row.evidence_role || "凭证")} · 终核状态：${this.escape(this.materialFeeEvidenceFinalLabel(row.validation_status))} <button type="button" data-action="mf-evidence-status" data-evidence-name="${this.escape(row.name || "")}" data-status="VALID">确认有效</button><button type="button" data-action="mf-evidence-status" data-evidence-name="${this.escape(row.name || "")}" data-status="INVALID">标记无效</button></span>`).join("") : "<span>暂无关联凭证</span>"}</div></details>
        </td>
      </tr>
    `;
  }

  materialFeeGridColumns() {
    const state = this.ensureMaterialFeeState();
    const columns = [
      { field: "row_no", label: "行", readonly: true },
      { field: "source_doc_no", label: "采购审批号", readonly: true },
      { field: "material_code", label: "物料编码", readonly: true },
      { field: "product_name", label: "物料名称", readonly: true },
      { field: "quantity", label: "采购数量", readonly: true, numeric: true },
      { field: "actual_shipped_qty", label: "发货数量", numeric: true },
      { field: "shipped_uom", label: "发货单位" },
      { field: "goods_value", label: "采购货值", readonly: true, numeric: true },
      { field: "gross_weight_kg", label: "毛重 kg", numeric: true },
      { field: "volume_m3", label: "体积 m³", numeric: true },
      { field: "chargeable_weight_kg", label: "计费重 kg", numeric: true },
      { field: "project_collection", label: "项目归属" },
    ];
    if (state.showAuxiliary) {
      columns.push(
        { field: "net_weight_kg", label: "净重 kg", numeric: true },
        { field: "unit_price", label: "采购单价", readonly: true, numeric: true },
        { field: "unit_price_uom", label: "计价单位", readonly: true },
        { field: "purchase_currency", label: "采购币种", readonly: true },
        { field: "supplier", label: "供应商", readonly: true },
        { field: "source_file_name", label: "来源文件", readonly: true }
      );
    }
    return columns;
  }

  renderMaterialFeeGrid() {
    const state = this.ensureMaterialFeeState();
    const materialData = state.materials || {};
    const columns = this.materialFeeGridColumns();
    let items = materialData.items || [];
    if (state.onlyMissing) items = items.filter((row) => (row.requirements?.missing_fields || []).length);
    const page = Number(materialData.page || state.page || 1);
    const pageCount = Math.max(1, Number(materialData.page_count || 1));
    return `
      <div class="ocw-mf-grid-shell">
        <div class="ocw-mf-grid-note"><span>单格离开或按 Enter 自动保存</span><span>Tab 可连续操作</span><span>多格粘贴会先预览再整体确认</span><span>项目归属缺失不阻断试算</span></div>
        <div class="ocw-mf-grid-scroll">
          <table class="ocw-mf-grid-table">
            <thead><tr>${columns.map((column) => `<th>${this.escape(column.label)}</th>`).join("")}</tr></thead>
            <tbody>${items.length ? items.map((item, index) => this.renderMaterialFeeGridRow(item, columns, index)).join("") : `<tr><td class="ocw-mf-grid-empty" colspan="${columns.length}">${state.onlyMissing ? "当前页没有缺项" : "当前批次暂无物料行"}</td></tr>`}</tbody>
          </table>
        </div>
        <div class="ocw-mf-grid-footer"><span>共 ${Number(materialData.total || 0)} 行 · 当前第 ${page}/${pageCount} 页</span><div><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="mf-material-page" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>上一页</button><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="mf-material-page" data-page="${page + 1}" ${page >= pageCount ? "disabled" : ""}>下一页</button></div></div>
      </div>
    `;
  }

  renderMaterialFeeGridRow(item, columns, rowIndex) {
    const missingFields = new Set(item.requirements?.missing_fields || []);
    return `<tr data-mf-row-index="${rowIndex}" data-item-name="${this.escape(item.name || "")}">${columns.map((column, columnIndex) => this.renderMaterialFeeGridCell(item, column, missingFields, columnIndex)).join("")}</tr>`;
  }

  renderMaterialFeeGridCell(item, column, missingFields, columnIndex) {
    let value = item[column.field];
    const shippingField = ["actual_shipped_qty", "shipped_uom"].includes(column.field);
    if (column.field === "actual_shipped_qty") value = item.effective_shipping_quantity;
    if (column.field === "shipped_uom") value = item.effective_shipping_uom;
    const isMissing = missingFields.has(column.field);
    const isDefault = shippingField && item.effective_shipping?.is_default;
    const classes = ["ocw-mf-cell", isMissing ? "is-missing" : "", isDefault ? "is-default" : "", column.readonly ? "is-readonly" : ""].filter(Boolean).join(" ");
    const reason = (item.requirements?.field_reasons?.[column.field] || []).map((row) => row.message || row.code).join("；");
    if (column.readonly) {
      return `<td class="${classes}" data-mf-column-index="${columnIndex}" title="${this.escape(reason)}"><span>${this.escape(this.formatValue(value || "--"))}</span></td>`;
    }
    return `<td class="${classes}" data-mf-column-index="${columnIndex}" title="${this.escape(reason)}"><input data-mf-cell-input="1" data-item-name="${this.escape(item.name || "")}" data-fieldname="${this.escape(column.field)}" data-original-value="${this.escape(value ?? "")}" value="${this.escape(value ?? "")}" ${column.numeric ? 'inputmode="decimal"' : ""} aria-label="${this.escape(column.label)}" />${isDefault && column.field === "actual_shipped_qty" ? `<small>默认=采购数</small>` : ""}</td>`;
  }

  findMaterialFeeItem(itemName) {
    return (this.ensureMaterialFeeState().materials?.items || []).find((row) => String(row.name) === String(itemName));
  }

  updateMaterialFeeExpectedModified(result) {
    const modified = result?.batch_modified;
    if (!modified) return;
    this.detailState.expectedModified = modified;
    if (this.detailState.header) this.detailState.header.modified = modified;
  }

  async saveMaterialFeeCell($input) {
    if (!$input.length || $input.data("saving")) return;
    const original = String($input.attr("data-original-value") ?? "");
    const value = String($input.val() ?? "").trim();
    if (value === original) return;
    const itemName = $input.attr("data-item-name");
    const fieldname = $input.attr("data-fieldname");
    const item = this.findMaterialFeeItem(itemName);
    if (!item || !(await this.ensureEditSession())) return;
    const $cell = $input.closest(".ocw-mf-cell");
    $input.data("saving", true).prop("disabled", true);
    $cell.addClass("is-saving").removeClass("is-save-error");
    try {
      let result;
      if (["actual_shipped_qty", "shipped_uom"].includes(fieldname)) {
        const editingQuantity = fieldname === "actual_shipped_qty";
        const currentMode = String(item.effective_shipping?.mode || "DEFAULT_PURCHASE");
        const mode = editingQuantity || currentMode !== "DEFAULT_PURCHASE" ? "MANUAL_CONFIRMED" : "DEFAULT_PURCHASE";
        const quantity = editingQuantity ? value : item.effective_shipping_quantity;
        const uom = fieldname === "shipped_uom" ? value : item.effective_shipping_uom;
        result = await this.call("overseas_costing.api.materials.set_shipping_quantity", {
          batch_name: this.detailState.batchName,
          item_name: itemName,
          mode,
          value: quantity,
          uom,
          edit_token: this.detailState.editToken,
          expected_modified: this.detailState.expectedModified,
        });
      } else {
        result = await this.call("overseas_costing.api.calculate.update_item_field", {
          item_name: itemName,
          fieldname,
          value,
          version_name: this.detailState.versionName || null,
          remark: "资料与费用页单格自动保存",
          edit_token: this.detailState.editToken,
          expected_modified: this.detailState.expectedModified,
        });
      }
      if (!result || !result.ok) throw new Error(result?.message || "保存失败");
      this.updateMaterialFeeExpectedModified(result);
      this.detailState.dirty = false;
      frappe.show_alert({ message: "已保存", indicator: "green" });
      await this.loadMaterialFeeWorkspace({ quiet: true });
    } catch (error) {
      $input.data("saving", false).prop("disabled", false);
      $cell.removeClass("is-saving").addClass("is-save-error").attr("title", `${this.normalizeErrorMessage(error)}；当前输入已保留，请重试。`);
      frappe.show_alert({ message: "保存失败，当前值已保留", indicator: "red" });
    }
  }

  previewMaterialPaste($startInput, text) {
    const rows = String(text || "").replace(/\r/g, "").split("\n").filter((row, index, list) => row || index < list.length - 1).map((row) => row.split("\t"));
    const $table = $startInput.closest("table");
    const $startRow = $startInput.closest("tr");
    const visibleRows = $table.find("tbody tr[data-item-name]").toArray();
    const startRowIndex = visibleRows.indexOf($startRow.get(0));
    const editableColumns = this.materialFeeGridColumns().filter((column) => !column.readonly);
    const startField = $startInput.attr("data-fieldname");
    const startColumnIndex = editableColumns.findIndex((column) => column.field === startField);
    const updates = [];
    rows.forEach((values, rowOffset) => {
      const targetRow = visibleRows[startRowIndex + rowOffset];
      if (!targetRow) return;
      const itemName = $(targetRow).attr("data-item-name");
      values.forEach((value, columnOffset) => {
        const column = editableColumns[startColumnIndex + columnOffset];
        if (!column) return;
        const current = this.findMaterialFeeItem(itemName)?.[column.field];
        const effectiveCurrent = column.field === "actual_shipped_qty" ? this.findMaterialFeeItem(itemName)?.effective_shipping_quantity : column.field === "shipped_uom" ? this.findMaterialFeeItem(itemName)?.effective_shipping_uom : current;
        if (String(value).trim() === String(effectiveCurrent ?? "").trim()) return;
        updates.push({ item_name: itemName, fieldname: column.field, value: String(value).trim(), old_value: effectiveCurrent, label: column.label });
      });
    });
    if (!updates.length) {
      frappe.show_alert({ message: "粘贴内容没有可更新的单元格", indicator: "blue" });
      return;
    }
    const dialog = new frappe.ui.Dialog({
      title: "预览多格粘贴",
      fields: [{ fieldtype: "HTML", fieldname: "preview", options: `<div class="ocw-mf-paste-preview"><div class="ocw-mf-dialog-note">即将更新 ${updates.length} 个单元格；确认后整批提交，任一行失败都会整体回滚。</div><table><thead><tr><th>物料</th><th>字段</th><th>当前值</th><th>新值</th></tr></thead><tbody>${updates.slice(0, 500).map((row) => `<tr><td>${this.escape(this.findMaterialFeeItem(row.item_name)?.material_code || row.item_name)}</td><td>${this.escape(row.label)}</td><td>${this.escape(this.formatValue(row.old_value ?? "--"))}</td><td>${this.escape(row.value || "--")}</td></tr>`).join("")}</tbody></table></div>` }],
      primary_action_label: "确认整批保存",
      primary_action: () => this.applyMaterialPaste(dialog, updates),
    });
    dialog._ocwMaterialPreview = preview;
    dialog._ocwMaterialImportBaseChoices = null;
    dialog.show();
    dialog.$wrapper.addClass("ocw-mf-dialog");
  }

  async applyMaterialPaste(dialog, updates) {
    if (!(await this.ensureEditSession())) return;
    const result = await this.call("overseas_costing.api.calculate.batch_update_items", {
      batch_name: this.detailState.batchName,
      version_name: this.detailState.versionName || null,
      updates: JSON.stringify(updates.map(({ item_name, fieldname, value }) => ({ item_name, fieldname, value, remark: "资料与费用页多格粘贴" }))),
      remark: "资料与费用页多格粘贴",
      edit_token: this.detailState.editToken,
      expected_modified: this.detailState.expectedModified,
    }, true);
    if (!result || !result.ok) throw new Error(result?.message || "多格粘贴保存失败");
    this.updateMaterialFeeExpectedModified(result);
    dialog.hide();
    frappe.show_alert({ message: `已更新 ${result.changed_count || 0} 个单元格`, indicator: "green" });
    await this.loadMaterialFeeWorkspace({ quiet: true });
  }

  findMaterialFee(feeKey) {
    const fees = this.ensureMaterialFeeState().fees?.fees || this.ensureMaterialFeeState().fees?.items || [];
    return fees.find((row) => String(row.logical_fee_key || row.fee_key) === String(feeKey));
  }

  materialFeeSavePayload(fee, overrides = {}) {
    const feeKey = fee.logical_fee_key || fee.fee_key || "";
    return {
      logical_fee_key: feeKey,
      rule_code: fee.rule_code || feeKey,
      expense_category: fee.expense_category,
      amount_status: overrides.amount_status || fee.amount_state || fee.amount_status || "MISSING",
      amount: overrides.amount !== undefined ? overrides.amount : fee.amount,
      currency: overrides.currency || fee.currency || "RMB",
      allocation_basis: fee.allocation_basis || fee.basis_field || "goods_value",
      scope_type: fee.scope_type || "ALL_ITEMS",
      scope_value_json: fee.scope_value_json || "[]",
      required_evidence_role: fee.required_evidence_role || "",
      included_in_fee_key: fee.included_in_fee_key || "",
      priority_no: fee.priority_no ?? 0,
      remark: fee.remark || "",
      is_active: fee.is_active === undefined ? 1 : fee.is_active,
      is_enabled: fee.is_enabled === undefined ? 1 : fee.is_enabled,
    };
  }

  async saveMaterialFeeInlineAmount($input) {
    if (!$input.length) return;
    const $cell = $input.closest(".ocw-mf-fee-amount-cell");
    if ($cell.data("saving")) return;
    const $amount = $cell.find("[data-mf-fee-amount]");
    const $currency = $cell.find("[data-mf-fee-currency]");
    const amount = String($amount.val() ?? "").trim();
    const currency = String($currency.val() || "RMB").trim().toUpperCase();
    const originalAmount = String($amount.attr("data-original-value") ?? "").trim();
    const originalCurrency = String($currency.attr("data-original-value") || "RMB").trim().toUpperCase();
    const forceActual = $input.attr("data-mf-fee-input") === "amount" && $amount.attr("data-mf-force-actual") === "1";
    if (!amount || (!forceActual && amount === originalAmount && currency === originalCurrency)) return;
    const fee = this.findMaterialFee($input.attr("data-fee-key"));
    if (!fee) return;

    const $inputs = $cell.find("[data-mf-fee-input]");
    $cell.data("saving", true).addClass("is-saving").removeClass("is-save-error").attr("title", "");
    $inputs.prop("disabled", true);
    try {
      if (!(await this.ensureEditSession())) {
        $cell.data("saving", false).removeClass("is-saving");
        $inputs.prop("disabled", false);
        return;
      }
      const payload = this.materialFeeSavePayload(fee, {
        amount_status: "ACTUAL",
        amount,
        currency,
      });
      const result = await this.call("overseas_costing.api.fees.save_fee", {
        batch_name: this.detailState.batchName,
        version_name: this.detailState.versionName,
        fee_payload: JSON.stringify(payload),
        edit_token: this.detailState.editToken,
        expected_modified: this.detailState.expectedModified,
      });
      if (!result || !result.ok) throw new Error(result?.message || "费用保存失败");
      this.updateMaterialFeeExpectedModified(result);
      this.detailState.dirty = false;
      await this.refreshMaterialFeeData();
      $amount.attr("data-original-value", amount).attr("data-mf-force-actual", "0");
      $currency.val(currency).attr("data-original-value", currency);
      $cell.data("saving", false).removeClass("is-saving");
      $inputs.prop("disabled", false);
      frappe.show_alert({ message: result.message || "费用已保存", indicator: "green" });
    } catch (error) {
      $cell.data("saving", false).removeClass("is-saving").addClass("is-save-error").attr(
        "title",
        `${this.normalizeErrorMessage(error)}；当前输入已保留，请刷新后重试。`
      );
      $inputs.prop("disabled", false);
      frappe.show_alert({ message: "保存失败，当前输入已保留；请刷新后重试", indicator: "red" });
    }
  }

  async refreshMaterialFeeData() {
    const state = this.ensureMaterialFeeState();
    const [fees, preview] = await Promise.all([
      this.call("overseas_costing.api.fees.get_fee_worklist", {
        batch_name: this.detailState.batchName,
        version_name: this.detailState.versionName || null,
      }),
      this.call("overseas_costing.api.calculate.preview_comprehensive_cost", {
        batch_name: this.detailState.batchName,
        version_name: this.detailState.versionName || null,
      }),
    ]);
    state.fees = fees;
    state.preview = preview;
    this.renderMaterialFeeWorkspace();
  }

  openMaterialFeeDialog(feeKey, candidate = null) {
    const fee = this.findMaterialFee(feeKey);
    if (!fee) return;
    let selectedKeys = [];
    try { selectedKeys = JSON.parse(fee.scope_value_json || "[]"); } catch (_error) { selectedKeys = []; }
    const materials = this.ensureMaterialFeeState().materials?.items || [];
    const otherFees = (this.ensureMaterialFeeState().fees?.fees || []).filter((row) => row.logical_fee_key !== fee.logical_fee_key);
    const dialog = new frappe.ui.Dialog({
      title: `编辑费用：${fee.expense_category || fee.logical_fee_key}`,
      fields: [
        ...(candidate ? [{ fieldtype: "HTML", fieldname: "candidate_note", options: `<div class="ocw-mf-dialog-note">已带入凭证识别候选 ${this.escape(candidate.currency || "")} ${this.escape(candidate.amount || "")}。请仍由你确认金额状态；系统不会自动认定为实际费用。</div>` }] : []),
        { fieldtype: "Select", fieldname: "amount_status", label: "金额状态", reqd: 1, options: "MISSING\nESTIMATED\nACTUAL\nNOT_INCURRED\nINCLUDED", default: fee.amount_state || fee.amount_status || "MISSING" },
        { fieldtype: "Data", fieldname: "amount", label: "原币金额", default: candidate?.amount || fee.amount || "" },
        { fieldtype: "Data", fieldname: "currency", label: "币种", reqd: 1, default: candidate?.currency || fee.currency || "RMB" },
        { fieldtype: "Select", fieldname: "allocation_basis", label: "分摊依据", reqd: 1, options: "goods_value\ngross_weight\nvolume\nchargeable_weight", default: fee.allocation_basis || fee.basis_field || "goods_value" },
        { fieldtype: "Select", fieldname: "scope_type", label: "适用范围", reqd: 1, options: "ALL_ITEMS\nITEMS\nDIRECT_ITEM", default: fee.scope_type || "ALL_ITEMS" },
        { fieldtype: "HTML", fieldname: "scope_items", options: `<div class="ocw-mf-scope-picker"><strong>限定到指定物料时勾选</strong>${materials.map((item) => `<label><input type="checkbox" data-mf-scope-key="${this.escape(item.stable_line_key || "")}" ${selectedKeys.includes(item.stable_line_key) ? "checked" : ""}/><span>${this.escape(item.material_code || "--")} · ${this.escape(item.product_name || "--")} · 行 ${this.escape(item.row_no || "--")}</span></label>`).join("")}</div>` },
        { fieldtype: "Select", fieldname: "included_in_fee_key", label: "已包含于", options: ["", "purchase_goods_value", ...otherFees.map((row) => row.logical_fee_key)].join("\n"), default: fee.included_in_fee_key || "" },
        { fieldtype: "Small Text", fieldname: "remark", label: "备注 / 未发生或已包含原因", default: fee.remark || "" },
      ],
      primary_action_label: "保存费用",
      primary_action: () => this.saveMaterialFeeDialog(dialog, fee),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-mf-dialog");
  }

  async saveMaterialFeeDialog(dialog, fee) {
    const values = dialog.get_values();
    if (!values || !(await this.ensureEditSession())) return;
    const scopeKeys = dialog.$wrapper.find("[data-mf-scope-key]:checked").toArray().map((node) => $(node).attr("data-mf-scope-key"));
    const payload = {
      logical_fee_key: fee.logical_fee_key,
      rule_code: fee.rule_code || fee.logical_fee_key,
      expense_category: fee.expense_category,
      amount_status: values.amount_status,
      amount: values.amount,
      currency: values.currency,
      allocation_basis: values.allocation_basis,
      scope_type: values.scope_type,
      scope_value_json: values.scope_type === "ALL_ITEMS" ? [] : scopeKeys,
      required_evidence_role: fee.required_evidence_role || "",
      included_in_fee_key: values.included_in_fee_key,
      priority_no: fee.priority_no || 0,
      remark: values.remark,
      is_active: 1,
      is_enabled: 1,
    };
    const result = await this.call("overseas_costing.api.fees.save_fee", {
      batch_name: this.detailState.batchName,
      version_name: this.detailState.versionName,
      fee_payload: JSON.stringify(payload),
      edit_token: this.detailState.editToken,
      expected_modified: this.detailState.expectedModified,
    }, true);
    if (!result || !result.ok) throw new Error(result?.message || "费用保存失败");
    this.updateMaterialFeeExpectedModified(result);
    dialog.hide();
    frappe.show_alert({ message: result.message || "费用已保存", indicator: "green" });
    await this.loadMaterialFeeWorkspace({ quiet: true });
  }

  openMaterialFeeEvidenceDialog(feeKey) {
    const fee = this.findMaterialFee(feeKey);
    if (!fee) return;
    if (!fee.name) {
      frappe.show_alert({ message: "请先编辑并保存这笔费用，再关联凭证。", indicator: "orange" });
      return;
    }
    const candidates = this.ensureMaterialFeeState().fees?.evidence_candidates || [];
    const linked = new Set((fee.evidence || []).map((row) => row.attachment));
    const dialog = new frappe.ui.Dialog({
      title: `关联凭证：${fee.expense_category || fee.logical_fee_key}`,
      fields: [{ fieldtype: "HTML", fieldname: "evidence", options: `<div class="ocw-mf-evidence-picker"><div class="ocw-mf-dialog-note">一个凭证可关联多笔费用，一笔费用也可关联多个凭证。附件识别金额只是候选，不会自动修改费用。</div>${candidates.length ? candidates.map((candidate) => `<label class="ocw-mf-evidence-option"><input type="checkbox" data-mf-evidence-attachment="${this.escape(candidate.attachment || "")}" ${linked.has(candidate.attachment) ? "checked disabled" : ""}/><span><strong>${this.escape(candidate.file_name || candidate.attachment || "--")}</strong><small>${this.escape(candidate.source_type || "附件")} · ${this.escape(candidate.parse_status || "Draft")}</small>${candidate.amount_candidates?.length ? `<em>识别候选：${candidate.amount_candidates.map((row) => `${this.escape(row.currency || "")} ${this.escape(row.amount)} <button type="button" data-mf-use-candidate="1" data-candidate-amount="${this.escape(row.amount || "")}" data-candidate-currency="${this.escape(row.currency || fee.currency || "RMB")}">带入费用表</button>`).join("、")}</em>` : ""}</span></label>`).join("") : `<div class="ocw-detail-empty"><strong>暂无可关联资料</strong><span>可先上传新凭证。</span></div>`}<button class="ocw-outline-btn" type="button" data-action="mf-upload-evidence">上传新凭证并关联</button></div>` }],
      primary_action_label: "关联所选凭证",
      primary_action: () => this.linkSelectedMaterialFeeEvidence(dialog, fee),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-mf-dialog");
    dialog.$wrapper.on("click", "[data-action='mf-upload-evidence']", () => {
      this.uploadMaterialFeeEvidence(dialog, fee);
    });
    dialog.$wrapper.on("click", "[data-mf-use-candidate]", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const $button = $(event.currentTarget);
      dialog.hide();
      this.openMaterialFeeDialog(fee.logical_fee_key, {
        amount: $button.attr("data-candidate-amount"),
        currency: $button.attr("data-candidate-currency"),
      });
    });
  }

  async linkSelectedMaterialFeeEvidence(dialog, fee) {
    if (!(await this.ensureEditSession())) return;
    const attachments = dialog.$wrapper.find("[data-mf-evidence-attachment]:checked:not(:disabled)").toArray().map((node) => $(node).attr("data-mf-evidence-attachment"));
    if (!attachments.length) {
      frappe.show_alert({ message: "请选择至少一份未关联凭证", indicator: "orange" });
      return;
    }
    for (const attachment of attachments) {
      const result = await this.call("overseas_costing.api.fees.link_fee_evidence", {
        batch_name: this.detailState.batchName,
        fee_rule: fee.name,
        attachment,
        evidence_role: fee.required_evidence_role || "expense_invoice",
        edit_token: this.detailState.editToken,
        expected_modified: this.detailState.expectedModified,
      });
      if (!result || !result.ok) throw new Error(result?.message || "凭证关联失败");
      this.updateMaterialFeeExpectedModified(result);
    }
    dialog.hide();
    frappe.show_alert({ message: `已关联 ${attachments.length} 份凭证`, indicator: "green" });
    await this.loadMaterialFeeWorkspace({ quiet: true });
  }

  uploadMaterialFeeEvidence(dialog, fee) {
    const batch = this.getDetailBatch();
    this.openManualDocumentUploader(batch, this.detailDocumentAdapter(), this.detectManualDocumentLogisticsType(batch), {
      code: `fee_evidence_${fee.logical_fee_key}`,
      label: `${fee.expense_category || fee.logical_fee_key}凭证`,
      attachmentType: "Other",
      required: false,
    }, async (registered) => {
      const attachment = registered?.attachment?.name;
      if (!attachment || !(await this.ensureEditSession())) return;
      let recognitionOk = false;
      try {
        const recognition = await this.call(
          "overseas_costing.api.import_api.preview_oa_source_attachment",
          { attachment_name: attachment },
          true
        );
        recognitionOk = Boolean(recognition?.ok);
      } catch (_error) {
        // 识别失败不影响凭证关联，用户仍可以手填费用。
      }
      const result = await this.call("overseas_costing.api.fees.link_fee_evidence", {
        batch_name: this.detailState.batchName,
        fee_rule: fee.name,
        attachment,
        evidence_role: fee.required_evidence_role || "expense_invoice",
        edit_token: this.detailState.editToken,
        expected_modified: this.detailState.expectedModified,
      });
      if (!result || !result.ok) throw new Error(result?.message || "凭证关联失败");
      this.updateMaterialFeeExpectedModified(result);
      dialog.hide();
      await this.loadMaterialFeeWorkspace({ quiet: true });
      frappe.show_alert({
        message: recognitionOk
          ? "凭证已关联，识别金额已作为候选，等待人工确认"
          : "凭证已关联；本次未识别出金额，可手工补录",
        indicator: recognitionOk ? "green" : "orange",
      });
    });
  }

  async setMaterialFeeEvidenceStatus(evidenceName, status) {
    if (!evidenceName || !(await this.ensureEditSession())) return;
    const result = await this.call("overseas_costing.api.fees.set_fee_evidence_status", {
      batch_name: this.detailState.batchName,
      evidence_name: evidenceName,
      status,
      remark: status === "VALID" ? "费用页人工确认凭证有效" : "费用页人工标记凭证无效",
      edit_token: this.detailState.editToken,
      expected_modified: this.detailState.expectedModified,
    });
    if (!result || !result.ok) throw new Error(result?.message || "凭证状态更新失败");
    this.updateMaterialFeeExpectedModified(result);
    await this.loadMaterialFeeWorkspace({ quiet: true });
  }

  async refreshMaterialFeeCostPreview(scrollToResult = false) {
    const state = this.ensureMaterialFeeState();
    state.preview = await this.call("overseas_costing.api.calculate.preview_comprehensive_cost", {
      batch_name: this.detailState.batchName,
      version_name: this.detailState.versionName || null,
    });
    this.renderMaterialFeeWorkspace();
    if (scrollToResult) this.$root.find(".ocw-mf-cost-section").get(0)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  renderMaterialFeeTodos() {
    const state = this.ensureMaterialFeeState();
    const todos = [];
    (state.fees?.fees || state.fees?.items || []).forEach((fee) => (fee.todos || []).forEach((todo) => todos.push(`${fee.expense_category || fee.logical_fee_key}：${todo.label}`)));
    (state.materials?.items || []).forEach((item) => (item.requirements?.missing_fields || []).forEach((field) => todos.push(`${item.material_code || item.name}：缺少 ${this.materialFeeGridColumns().find((column) => column.field === field)?.label || field}`)));
    (state.preview?.incomplete_reasons || []).forEach((row) => {
      const text = row.message || row.reason_code;
      if (text && !todos.includes(text)) todos.push(text);
    });
    return `<details class="ocw-mf-section ocw-mf-todos"><summary><span><strong>详细待办</strong><em>${todos.length} 项</em></span><small>默认收起，需要时展开查看</small></summary><div>${todos.length ? `<ul>${todos.slice(0, 100).map((todo) => `<li>${this.escape(todo)}</li>`).join("")}</ul>` : `<div class="ocw-detail-empty"><strong>当前没有待办</strong></div>`}</div></details>`;
  }

  renderMaterialFeeCostTable() {
    const preview = this.ensureMaterialFeeState().preview || {};
    const items = preview.items || [];
    return `<section class="ocw-mf-section ocw-mf-cost-section"><div class="ocw-mf-section-title"><div><span>03</span><h3>SKU 综合单价试算</h3><p>只读预览；未计入费用会单独列出，不会把未知金额当作 0。</p></div><span class="ocw-mf-completeness ${preview.summary?.is_complete ? "is-complete" : "is-partial"}">${preview.summary?.is_complete ? "完整成本" : "非完整成本"}</span></div><div class="ocw-mf-cost-scroll"><table><thead><tr><th>物料编码</th><th>物料名称</th><th>采购货值</th><th>直接费用</th><th>分摊费用</th><th>综合成本</th><th>每发货单位</th><th>每采购计价单位</th></tr></thead><tbody>${items.length ? items.map((item) => `<tr><td>${this.escape(item.material_code || "--")}</td><td>${this.escape(item.product_name || "--")}</td><td>${this.escape(item.goods_value_rmb || "0.00")}</td><td>${this.escape(item.direct_fees_rmb || "0.00")}</td><td>${this.escape(item.allocated_fees_rmb || "0.00")}</td><td><strong>${this.escape(item.total_cost_rmb || "0.00")}</strong></td><td>${item.shipping_unit_cost ? `${this.escape(item.shipping_unit_cost.amount_rmb)} / ${this.escape(item.shipping_unit_cost.uom)}` : "--"}</td><td>${item.purchase_pricing_unit_cost ? `${this.escape(item.purchase_pricing_unit_cost.amount_rmb)} / ${this.escape(item.purchase_pricing_unit_cost.uom)}` : `<span class="ocw-mf-muted">单位换算未明确</span>`}</td></tr>`).join("") : `<tr><td colspan="8">暂无可试算物料</td></tr>`}</tbody></table></div>${preview.excluded_fees?.length ? `<div class="ocw-mf-excluded"><strong>未计入费用</strong>${preview.excluded_fees.map((fee) => `<span>${this.escape(fee.expense_category || fee.fee_key || "--")} · ${this.escape(fee.reason_code || "--")}</span>`).join("")}</div>` : ""}</section>`;
  }

  openMaterialFeeSourcesDialog() {
    const state = this.ensureMaterialFeeState();
    const candidates = state.fees?.evidence_candidates || [];
    const dialog = new frappe.ui.Dialog({
      title: "查看资料来源",
      fields: [{ fieldtype: "HTML", fieldname: "sources", options: `<div class="ocw-mf-sources"><div class="ocw-mf-dialog-note">OA 采购数量、金额和物料身份作为来源事实保留。装箱计划是可选补充：没有时可先用采购数量作为默认发货数量。</div><div class="ocw-mf-source-actions"><button class="ocw-outline-btn" type="button" data-action="view-dingtalk-approval">查看钉钉 OA</button><button class="ocw-primary-btn" type="button" data-action="mf-import-xlsx">导入 Excel 补资料</button></div><div class="ocw-mf-source-list">${candidates.length ? candidates.map((row) => `<div><span><strong>${this.escape(row.file_name || row.attachment || "--")}</strong><small>${this.escape(row.source_type || "附件")} · ${this.escape(row.attachment_type || "未分类")} · ${this.escape(row.parse_status || "Draft")}</small></span>${row.file_url ? `<button class="ocw-outline-btn ocw-mini-btn" type="button" data-mf-preview-source="1" data-file-url="${this.escape(row.file_url)}" data-file-name="${this.escape(row.file_name || "")}">预览</button>` : ""}</div>`).join("") : `<div class="ocw-detail-empty"><strong>暂无附件资料</strong></div>`}</div></div>` }],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-mf-dialog");
    dialog.$wrapper.on("click", "[data-mf-preview-source]", (event) => {
      const $button = $(event.currentTarget);
      this.openOaAttachmentFilePreviewDialog($button.attr("data-file-url"), $button.attr("data-file-name"));
    });
    dialog.$wrapper.on("click", "[data-action='view-dingtalk-approval']", () => {
      dialog.hide();
      this.switchDetailTab("dingtalk");
    });
    dialog.$wrapper.on("click", "[data-action='mf-import-xlsx']", () => {
      dialog.hide();
      this.openMaterialXlsxUploader();
    });
  }

  openMaterialXlsxUploader() {
    const batch = this.getDetailBatch();
    if (!frappe.ui.FileUploader) return this.showPendingFeature("当前无法打开上传器，请刷新后重试。");
    this.ensureEditSession().then((ready) => {
      if (!ready) return;
      new frappe.ui.FileUploader({
        allow_multiple: false,
        restrictions: { allowed_file_types: [".xlsx"], max_file_size: 20 * 1024 * 1024 },
        on_success: (fileDoc) => {
          const uploaded = Array.isArray(fileDoc) ? fileDoc[0] : fileDoc;
          const fileName = String(uploaded?.file_name || uploaded?.name || "");
          if (!fileName.toLowerCase().endsWith(".xlsx")) {
            this.showPendingFeature("物料导入仅支持 .xlsx 文件。");
            return;
          }
          this.registerManualDocumentAttachment(batch, this.detailDocumentAdapter(), this.detectManualDocumentLogisticsType(batch), {
            code: "material_import_xlsx",
            label: "物料与装箱 Excel",
            attachmentType: "Packing List",
            required: false,
          }, uploaded).then((registered) => {
            const attachment = registered?.attachment?.name;
            if (attachment) this.previewMaterialXlsxImport(attachment);
          }).catch((error) => this.showError(error));
        },
      });
      [0, 100, 300].forEach((delay) => window.setTimeout(() => this.localizeFrappeFileUploader("物料与装箱 Excel"), delay));
    }).catch((error) => this.showError(error));
  }

  async openWikiMaterialImportDialog() {
    const dialog = new frappe.ui.Dialog({
      title: "从装箱计划表获取",
      fields: [{
        fieldtype: "HTML",
        fieldname: "wiki_sources",
        options: `<div class="ocw-mf-wiki-source-shell" data-area="mf-wiki-sources"><div class="ocw-detail-empty"><strong>正在读取装箱计划表</strong></div></div>`,
      }],
    });
    dialog.wikiMaterialSelectedSource = "";
    dialog.show();
    dialog.$wrapper.addClass("ocw-mf-dialog ocw-mf-wiki-dialog");
    dialog.$wrapper
      .off(".ocwMfWiki")
      .on("click.ocwMfWiki", "[data-mf-wiki-source]", (event) => {
        dialog.wikiMaterialSelectedSource = $(event.currentTarget).attr("data-source-id") || "";
        this.renderWikiMaterialSources(dialog);
      })
      .on("input.ocwMfWiki", "[data-action='mf-wiki-filter']", (event) => {
        const keyword = String($(event.currentTarget).val() || "").trim().toLowerCase();
        dialog.$wrapper.find("[data-mf-wiki-card]").each((_, node) => {
          $(node).toggle(!keyword || String($(node).attr("data-search") || "").includes(keyword));
        });
      })
      .on("click.ocwMfWiki", "[data-action='mf-wiki-refresh']", (event) => {
        const $button = $(event.currentTarget);
        this.refreshWikiMaterialSource(dialog, $button.attr("data-workbook-id"), $button.attr("data-sheet-id"))
          .catch((error) => this.showError(error));
      })
      .on("click.ocwMfWiki", "[data-action='mf-wiki-preview']", () => {
        this.previewWikiMaterialImport(dialog).catch((error) => this.showError(error));
      })
      .on("click.ocwMfWiki", "[data-action='mf-wiki-cancel']", () => dialog.hide());
    await this.loadWikiMaterialSources(dialog);
  }

  async loadWikiMaterialSources(dialog) {
    const result = await this.call("overseas_costing.api.packing_api.list_packing_sources", {
      batch_name: this.detailState.batchName,
    }, true);
    const sheets = (result?.wiki_workbooks || []).flatMap((workbook) =>
      (workbook.sheets || []).map((sheet) => ({ ...sheet, workbook_id: workbook.workbook_id, workbook_label: workbook.label }))
    );
    sheets.sort((left, right) => {
      const leftDate = String(left.business_date || left.source_updated_at || left.snapshot_updated_at || "");
      const rightDate = String(right.business_date || right.source_updated_at || right.snapshot_updated_at || "");
      return rightDate.localeCompare(leftDate) || String(left.source_label || "").localeCompare(String(right.source_label || ""));
    });
    dialog.wikiMaterialSources = sheets;
    dialog.wikiMaterialError = result?.wiki_error || "";
    if (!sheets.some((sheet) => String(sheet.source_id) === String(dialog.wikiMaterialSelectedSource))) {
      const recommended = sheets.find((sheet) => sheet.auto_select_recommended) || sheets.find((sheet) => sheet.is_recommended) || sheets[0];
      dialog.wikiMaterialSelectedSource = recommended?.source_id || "";
    }
    this.renderWikiMaterialSources(dialog);
  }

  renderWikiMaterialSources(dialog) {
    const $target = dialog.$wrapper.find("[data-area='mf-wiki-sources']");
    const sheets = dialog.wikiMaterialSources || [];
    const selectedId = String(dialog.wikiMaterialSelectedSource || "");
    const cards = sheets.map((sheet) => {
      const selected = String(sheet.source_id || "") === selectedId;
      const sheetId = String(sheet.source_id || "").split(":").slice(1).join(":");
      const confidence = { high: "高置信度", medium: "中置信度", low: "低置信度" }[sheet.recommendation_confidence] || "待确认";
      const updatedAt = sheet.snapshot_updated_at || sheet.source_updated_at;
      const status = sheet.snapshot_status === "ready"
        ? `已刷新 ${this.formatDateTimeMinute(updatedAt) || updatedAt || ""}`
        : sheet.snapshot_status === "unreadable" ? "缓存不可读取" : "待刷新";
      return `<article class="ocw-mf-wiki-card ${selected ? "selected" : ""} ${sheet.is_recommended ? "recommended" : ""}" data-mf-wiki-card="1" data-search="${this.escape(String(sheet.source_label || "").toLowerCase())}">
        <button type="button" data-mf-wiki-source="1" data-source-id="${this.escape(sheet.source_id || "")}">
          <span>${sheet.is_recommended ? "系统推荐" : "SHEET"}</span>
          <strong>${this.escape(sheet.source_label || sheet.source_id || "未命名 Sheet")}</strong>
          <small>${this.escape(sheet.workbook_label || "装箱计划表")} · 装箱日期 ${this.escape(sheet.business_date || "未识别")}</small>
        </button>
        ${sheet.is_recommended ? `<div class="ocw-mf-wiki-reasons"><b>系统推荐 · ${this.escape(confidence)}</b>${(sheet.recommendation_reasons || []).slice(0, 3).map((reason) => `<span>${this.escape(reason)}</span>`).join("")}</div>` : ""}
        <div class="ocw-mf-wiki-card-meta"><span>${this.escape(status)}</span><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="mf-wiki-refresh" data-workbook-id="${this.escape(sheet.workbook_id || "")}" data-sheet-id="${this.escape(sheetId)}">刷新最新数据</button></div>
      </article>`;
    }).join("");
    $target.html(`
      <div class="ocw-mf-dialog-note">系统只读取服务器已授权的钉钉装箱计划表。选择后先预览，不会直接改动物料数据。</div>
      ${dialog.wikiMaterialError ? `<div class="ocw-mf-wiki-error">${this.escape(dialog.wikiMaterialError)}</div>` : ""}
      <label class="ocw-mf-wiki-search"><span>查找 Sheet</span><input type="search" data-action="mf-wiki-filter" placeholder="输入装箱单、日期或品类"></label>
      <div class="ocw-mf-wiki-list">${cards || `<div class="ocw-detail-empty"><strong>暂无可用 Sheet</strong><span>请先确认服务端装箱计划表同步状态。</span></div>`}</div>
      <footer class="ocw-mf-import-sticky-footer"><span>${selectedId ? `已选：${this.escape((sheets.find((sheet) => String(sheet.source_id) === selectedId) || {}).source_label || selectedId)}` : "请选择一个 Sheet"}</span><div><button class="ocw-outline-btn" type="button" data-action="mf-wiki-cancel">取消</button><button class="ocw-primary-btn" type="button" data-action="mf-wiki-preview" ${selectedId ? "" : "disabled"}>预览所选 Sheet</button></div></footer>
    `);
  }

  async refreshWikiMaterialSource(dialog, workbookId, sheetId) {
    if (!workbookId || !sheetId) throw new Error("无法识别需要刷新的装箱计划 Sheet。");
    const requestId = this.packingFlowRequestId();
    await this.call("overseas_costing.api.packing_api.request_packing_sheet_refresh", {
      batch_name: this.detailState.batchName,
      workbook_id: workbookId,
      sheet_id: sheetId,
      request_id: requestId,
    }, false);
    frappe.show_alert({ message: "正在刷新钉钉装箱计划资料", indicator: "blue" });
    await this.waitPackingRefresh(this.getDetailBatch(), requestId);
    await this.loadWikiMaterialSources(dialog);
    frappe.show_alert({ message: "装箱计划资料已刷新", indicator: "green" });
  }

  async previewWikiMaterialImport(sourceDialog) {
    const sourceId = String(sourceDialog.wikiMaterialSelectedSource || "");
    if (!sourceId) throw new Error("请先选择装箱计划 Sheet。");
    const result = await this.call("overseas_costing.api.materials.preview_material_import", {
      batch_name: this.detailState.batchName,
      source_kind: "wiki_sheet",
      source_id: sourceId,
      sheet_name: null,
    }, true);
    if (!result || !result.ok) throw new Error(result?.message || "装箱计划表预览失败");
    sourceDialog.hide();
    this.openMaterialImportPreviewDialog(result);
  }

  async previewMaterialXlsxImport(attachmentName, sheetName = "") {
    const result = await this.call("overseas_costing.api.materials.preview_material_import", {
      batch_name: this.detailState.batchName,
      source_kind: "manual_xlsx",
      source_id: attachmentName,
      sheet_name: sheetName || null,
    }, true);
    if (!result || !result.ok) throw new Error(result?.message || "Excel 预览失败");
    this.openMaterialImportPreviewDialog(result);
  }

  openMaterialImportPreviewDialog(preview) {
    const rows = preview.rows || [];
    const isWiki = preview.source?.kind === "wiki_sheet";
    const dialog = new frappe.ui.Dialog({
      title: isWiki ? "装箱计划表导入预览" : "Excel 导入预览",
      fields: [{ fieldtype: "HTML", fieldname: "preview", options: isWiki ? this.renderWikiMaterialImportPreview(preview) : `<div class="ocw-mf-import-preview"><div class="ocw-mf-import-summary"><span>可补充 <strong>${preview.summary?.supplement || 0}</strong></span><span>冲突 <strong>${preview.summary?.conflict || 0}</strong></span><span>未匹配 <strong>${preview.summary?.unmatched || 0}</strong></span><span>不会新增未知行</span></div><div class="ocw-mf-import-table"><table><thead><tr><th>源行</th><th>分类</th><th>物料</th><th>字段变化 / 处理</th></tr></thead><tbody>${rows.map((row) => `<tr class="is-${this.escape(row.classification || "unmatched")}"><td>${this.escape(row.source_row || "--")}</td><td>${this.escape({ supplement: "可补充", conflict: "冲突", unmatched: "未匹配", no_change: "无变化" }[row.classification] || row.classification || "--")}</td><td>${this.escape(row.incoming?.material_code || "--")}${row.match_status === "choice_required" ? `<select data-mf-match-row="${this.escape(row.source_row)}"><option value="">请选择原行</option>${(row.candidates || []).map((candidate) => `<option value="${this.escape(candidate.stable_line_key || "")}">行 ${this.escape(candidate.row_no || "--")} · ${this.escape(candidate.material_code || "--")}</option>`).join("")}</select>` : ""}</td><td>${(row.changes || []).length ? row.changes.map((change) => `<div><span>${this.escape(change.field)}：${this.escape(this.formatValue(change.old ?? "--"))} → ${this.escape(this.formatValue(change.new ?? "--"))}</span>${change.conflict ? `<select data-mf-conflict-row="${this.escape(row.source_row)}" data-fieldname="${this.escape(change.field)}"><option value="keep_current">保留当前值</option><option value="use_source">采用 Excel</option></select>` : ""}</div>`).join("") : "--"}</td></tr>`).join("")}</tbody></table></div><div class="ocw-mf-dialog-note">仅补充发货数量、单位、重量、体积、计费重和项目归属；OA 采购事实不被覆盖。</div></div>` }],
      primary_action_label: isWiki ? undefined : "确认整体导入",
      primary_action: isWiki ? undefined : () => this.applyMaterialXlsxImport(dialog, preview),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-mf-dialog ocw-mf-import-dialog");
    if (isWiki) {
      dialog.$wrapper
        .on("click", "[data-action='mf-wiki-import-cancel']", () => dialog.hide())
        .on("click", "[data-action='mf-wiki-import-confirm']", () => {
          this.applyMaterialImport(dialog, dialog._ocwMaterialPreview || preview).catch((error) => this.showError(error));
        });
    }
  }

  materialImportFieldLabel(fieldname) {
    return {
      actual_shipped_qty: "发货数量",
      shipped_uom: "发货单位",
      net_weight_kg: "净重 kg",
      gross_weight_kg: "毛重 kg",
      volume_m3: "体积 m³",
      chargeable_weight_kg: "计费重 kg",
      project_collection: "项目归属",
    }[fieldname] || fieldname;
  }

  renderWikiMaterialImportPreview(preview) {
    const rows = preview.rows || [];
    const physicalLabels = { complete: "物理量完整", incomplete: "来源不完整，物理量暂不写", allocation_required: "合箱待分配", group_confirmation_required: "合并组待确认" };
    const rowHtml = rows.map((row) => {
      const incoming = row.incoming || {};
      const sourceChoiceAttribute = preview.is_merged_preview ? "data-mf-merged-source-field" : "data-mf-source-field";
      const sourceChoices = (row.source_conflicts || []).map((conflict) => `<label class="ocw-mf-source-choice"><span>${this.escape(this.materialImportFieldLabel(conflict.field))}${conflict.current ? `（当前：${this.escape(conflict.current)}）` : ""}</span><select ${sourceChoiceAttribute}="1" data-source-row="${this.escape(row.source_row)}" data-fieldname="${this.escape(conflict.field)}"><option value="">请选择来源值</option>${(conflict.options || []).map((value) => `<option value="${this.escape(value)}">${this.escape(value)}</option>`).join("")}</select></label>`).join("");
      const latentConflicts = ["net_weight_kg", "gross_weight_kg", "volume_m3"].map((fieldname) => `<label class="ocw-mf-latent-conflict"><span>${this.escape(this.materialImportFieldLabel(fieldname))}若与现有值冲突</span><select data-mf-conflict-row="${this.escape(row.source_row)}" data-fieldname="${fieldname}"><option value="keep_current">保留当前值</option><option value="use_source">采用装箱计划</option></select></label>`).join("");
      return `<tr class="is-${this.escape(row.classification || "unmatched")}"><td>${this.escape((row.source_rows || [row.source_row]).join("、"))}</td><td><strong>${this.escape(incoming.material_code || "--")}</strong>${row.match_status === "choice_required" ? `<select data-mf-match-row="${this.escape(row.source_row)}"><option value="">请选择采购明细</option>${(row.candidates || []).map((candidate) => `<option value="${this.escape(candidate.stable_line_key || "")}">行 ${this.escape(candidate.row_no || "--")} · ${this.escape(candidate.source_doc_no || "未写审批号")}</option>`).join("")}</select>` : row.match_status === "unmatched" ? `<small>未匹配，不会写入</small>` : ""}</td><td><span>${this.escape(this.formatValue(incoming.actual_shipped_qty || "--"))} ${this.escape(incoming.shipped_uom || "")}</span><small>${this.escape(physicalLabels[row.physical_status] || "")}${row.physical_missing_rows?.length ? ` · 缺失行 ${this.escape(row.physical_missing_rows.join("、"))}` : ""}</small></td><td><span>净 ${this.escape(this.formatValue(incoming.net_weight_kg || "--"))} / 毛 ${this.escape(this.formatValue(incoming.gross_weight_kg || "--"))} kg</span><span>体积 ${this.escape(this.formatValue(incoming.volume_m3 || "--"))} m³</span><span>项目 ${this.escape(incoming.project_collection || "--")}</span></td><td>${sourceChoices}${(row.changes || []).map((change) => `<label><span>${this.escape(this.materialImportFieldLabel(change.field))}：${this.escape(this.formatValue(change.old ?? "--"))} → ${this.escape(this.formatValue(change.new ?? "--"))}</span>${change.conflict ? `<select data-mf-conflict-row="${this.escape(row.source_row)}" data-fieldname="${this.escape(change.field)}"><option value="keep_current">保留当前值</option><option value="use_source">采用装箱计划</option></select>` : ""}</label>`).join("") || "--"}${["allocation_required", "group_confirmation_required"].includes(row.physical_status) ? `<details><summary>已有物理量冲突规则</summary>${latentConflicts}</details>` : ""}</td></tr>`;
    }).join("");
    const sharedGroups = (preview.shared_groups || []).filter((group) => group.allocation_required !== false).map((group) => `<article class="ocw-mf-allocation-group"><header><div><strong>${this.escape(group.group_id)}</strong><span>来源行 ${this.escape((group.row_numbers || []).join("、"))}</span></div><small>整箱：净 ${this.escape(group.metrics?.net_weight_kg?.value || "--")} kg · 毛 ${this.escape(group.metrics?.gross_weight_kg?.value || "--")} kg · 体积 ${this.escape(group.metrics?.volume_m3?.value || "--")} m³</small></header><div>${(group.participants || []).map((participant) => `<div class="ocw-mf-allocation-row"><span><strong>${this.escape(participant.material_code || "未识别物料")}</strong><small>${participant.in_batch ? "将写入本批次" : "批次外，仅用于核对合计"}</small></span>${["net_weight_kg", "gross_weight_kg", "volume_m3"].map((fieldname) => `<label>${this.escape(this.materialImportFieldLabel(fieldname))}<input inputmode="decimal" data-mf-allocation="1" data-group-id="${this.escape(group.group_id)}" data-source-key="${this.escape(participant.source_key)}" data-fieldname="${fieldname}" placeholder="0"></label>`).join("")}</div>`).join("")}</div></article>`).join("");
    const confirmationGroups = (preview.confirmation_groups || []).map((group) => `<label class="ocw-mf-group-confirm"><input type="checkbox" data-mf-group-confirmation="${this.escape(group.group_id)}"><span><strong>确认 ${this.escape(group.group_id)} 为同一包装组</strong><small>来源行 ${this.escape((group.row_numbers || []).join("、"))} · ${this.escape((group.material_codes || []).join("、"))}</small></span></label>`).join("");
    const outside = (preview.out_of_batch || []).map((row) => `<li>第 ${this.escape(row.source_row || "--")} 行 · ${this.escape(row.material_code || "未识别物料")} · 数量 ${this.escape(row.quantity || "--")}</li>`).join("");
    const sourceValidation = preview.source_validation || {};
    const validationIssues = [...(sourceValidation.blocking || []), ...(sourceValidation.warnings || [])].map((issue) => `<label class="ocw-mf-source-validation ${issue.confirmation_required ? "is-blocking" : ""}">${issue.confirmation_required ? `<input type="checkbox" data-mf-source-validation="${this.escape(issue.confirmation_key || issue.code || "")}">` : ""}<span><strong>${issue.confirmation_required ? "需要确认" : "来源提示"}：${this.escape(issue.message || issue.code || "待核对")}</strong>${issue.confirmation_required ? "<small>勾选后表示已核对，仍按装箱明细写入。</small>" : ""}</span></label>`).join("");
    return `<div class="ocw-mf-import-preview ocw-mf-wiki-import-preview"><div class="ocw-mf-dialog-note"><strong>${this.escape(preview.source?.label || preview.source?.sheet || "装箱计划表")}</strong><br>${preview.is_merged_preview ? "以下是选择采购明细后重新汇总的最终预览。" : ""}资料更新时间：${this.escape(this.formatDateTimeMinute(preview.source?.source_updated_at) || preview.source?.source_updated_at || "未提供")}。只有点击下方“确认写入物料表”才会修改数据。</div>${validationIssues ? `<section class="ocw-mf-source-validation-list"><h4>装箱计划表数据校验</h4>${validationIssues}</section>` : ""}<div class="ocw-mf-import-summary"><span>匹配 <strong>${preview.summary?.matched || 0}</strong></span><span>需选采购行 <strong>${preview.summary?.choice_required || 0}</strong></span><span>物理量不完整 <strong>${preview.summary?.physical_incomplete || 0}</strong></span><span>批次外 <strong>${preview.summary?.out_of_batch || 0}</strong></span></div><div class="ocw-mf-import-table"><table><thead><tr><th>来源行</th><th>物料与目标</th><th>发货数据</th><th>物理量</th><th>字段变化 / 处理</th></tr></thead><tbody>${rowHtml || `<tr><td colspan="5">没有匹配到当前批次物料</td></tr>`}</tbody></table></div>${sharedGroups ? `<section class="ocw-mf-allocation-section"><h4>跨 SKU 合箱分配</h4><p>填写每个物料的实际值；每列合计必须等于整箱来源值。</p>${sharedGroups}</section>` : ""}${confirmationGroups ? `<section class="ocw-mf-confirmation-section"><h4>候选合并组确认</h4>${confirmationGroups}</section>` : ""}${outside ? `<details class="ocw-mf-outside-list"><summary>批次外或未识别物料（不会导入）</summary><ul>${outside}</ul></details>` : ""}<footer class="ocw-mf-import-sticky-footer"><span>OA 采购数量、货值和物料身份不会被覆盖。</span><div><button class="ocw-outline-btn" type="button" data-action="mf-wiki-import-cancel">取消</button><button class="ocw-primary-btn" type="button" data-action="mf-wiki-import-confirm">确认写入物料表</button></div></footer></div>`;
  }

  async applyMaterialXlsxImport(dialog, preview) {
    return this.applyMaterialImport(dialog, preview);
  }

  async applyMaterialImport(dialog, preview) {
    if (!(await this.ensureEditSession())) return;
    const baseChoices = dialog._ocwMaterialImportBaseChoices || {};
    const choices = {
      fields: {},
      matches: { ...(baseChoices.matches || {}) },
      source_fields: { ...(baseChoices.source_fields || {}) },
      merged_source_fields: {},
      group_confirmations: { ...(baseChoices.group_confirmations || {}) },
      allocations: JSON.parse(JSON.stringify(baseChoices.allocations || {})),
      source_validation: { ...(baseChoices.source_validation || {}) },
    };
    dialog.$wrapper.find("[data-mf-conflict-row]").each((_, node) => {
      const row = $(node).attr("data-mf-conflict-row");
      choices.fields[row] = choices.fields[row] || {};
      choices.fields[row][$(node).attr("data-fieldname")] = $(node).val();
    });
    dialog.$wrapper.find("[data-mf-match-row]").each((_, node) => {
      choices.matches[$(node).attr("data-mf-match-row")] = $(node).val();
    });
    dialog.$wrapper.find("[data-mf-source-field]").each((_, node) => {
      const row = $(node).attr("data-source-row");
      choices.source_fields[row] = choices.source_fields[row] || {};
      choices.source_fields[row][$(node).attr("data-fieldname")] = $(node).val();
    });
    dialog.$wrapper.find("[data-mf-merged-source-field]").each((_, node) => {
      const row = $(node).attr("data-source-row");
      choices.merged_source_fields[row] = choices.merged_source_fields[row] || {};
      choices.merged_source_fields[row][$(node).attr("data-fieldname")] = $(node).val();
    });
    dialog.$wrapper.find("[data-mf-group-confirmation]").each((_, node) => {
      choices.group_confirmations[$(node).attr("data-mf-group-confirmation")] = $(node).is(":checked");
    });
    dialog.$wrapper.find("[data-mf-source-validation]").each((_, node) => {
      choices.source_validation[$(node).attr("data-mf-source-validation")] = $(node).is(":checked");
    });
    dialog.$wrapper.find("[data-mf-allocation]").each((_, node) => {
      const $input = $(node);
      const groupId = $input.attr("data-group-id");
      const sourceKey = $input.attr("data-source-key");
      choices.allocations[groupId] = choices.allocations[groupId] || {};
      choices.allocations[groupId][sourceKey] = choices.allocations[groupId][sourceKey] || {};
      choices.allocations[groupId][sourceKey][$input.attr("data-fieldname")] = String($input.val() || "").trim();
    });
    if (preview.merged_preview_hash) choices.merged_preview_hash = preview.merged_preview_hash;
    const validationError = this.validateWikiMaterialAllocations(preview, choices);
    if (validationError) throw new Error(validationError);
    const result = await this.call("overseas_costing.api.materials.apply_material_import", {
      batch_name: this.detailState.batchName,
      preview_revision: preview.preview_revision,
      choices_json: JSON.stringify(choices),
      edit_token: this.detailState.editToken,
      expected_modified: this.detailState.expectedModified,
    }, true);
    if (result?.code === "MERGED_PREVIEW_CONFIRMATION_REQUIRED" && result.merged_preview) {
      dialog._ocwMaterialImportBaseChoices = {
        matches: choices.matches,
        source_fields: choices.source_fields,
        group_confirmations: choices.group_confirmations,
        allocations: choices.allocations,
        source_validation: choices.source_validation,
      };
      const mergedPreview = {
        ...result.merged_preview,
        preview_revision: preview.preview_revision,
        merged_preview_hash: result.merged_preview_hash,
      };
      dialog._ocwMaterialPreview = mergedPreview;
      dialog.fields_dict.preview.$wrapper.html(this.renderWikiMaterialImportPreview(mergedPreview));
      frappe.show_alert({ message: "已生成合并后的最终预览，请核对后确认写入", indicator: "blue" });
      return;
    }
    if (!result || !result.ok) {
      const messages = {
        ALLOCATION_REQUIRED: "请填写所有合箱物料的净重、毛重和体积。",
        ALLOCATION_TOTAL_MISMATCH: "合箱分配合计与来源整箱数据不一致。",
        GROUP_CONFIRMATION_REQUIRED: "请确认所有候选合并包装组。",
        SOURCE_FIELD_CHOICE_REQUIRED: "请处理来源中的单位或项目归属冲突。",
        MERGED_PREVIEW_CONFIRMATION_REQUIRED: "请先核对合并后的最终预览。",
        LINE_CHOICE_REQUIRED: "请为重复物料选择对应的采购明细行。",
        DUPLICATE_TARGET_SELECTION: "两组来源行选中了同一采购明细，请重新预览并分别指定。",
        SOURCE_VALIDATION_CONFIRMATION_REQUIRED: "请先确认装箱计划表的数据校验提示。",
        SOURCE_CHANGED: "装箱计划表已经更新，请重新预览后再确认。",
        PREVIEW_CHANGED: "装箱计划解析结果已经变化，请重新预览。",
        BATCH_VERSION_CHANGED: "批次数据已经变化，请刷新页面后重新操作。",
      };
      throw new Error(result?.message || messages[result?.code] || result?.code || "资料导入失败");
    }
    this.updateMaterialFeeExpectedModified(result);
    dialog.hide();
    frappe.show_alert({ message: `已更新 ${result.updated_count || 0} 行、${result.changed_field_count || 0} 个字段`, indicator: "green" });
    await this.loadMaterialFeeWorkspace({ quiet: true });
  }

  validateWikiMaterialAllocations(preview, choices) {
    for (const group of preview.shared_groups || []) {
      if (group.allocation_required === false) continue;
      const values = choices.allocations?.[group.group_id] || {};
      for (const [fieldname, metric] of Object.entries(group.metrics || {})) {
        const rawValues = (group.participants || []).map((participant) => String(values?.[participant.source_key]?.[fieldname] ?? "").trim());
        if (rawValues.some((value) => value === "")) return `请完整填写 ${group.group_id} 的${this.materialImportFieldLabel(fieldname)}。`;
        const numbers = rawValues.map((value) => Number(value));
        if (numbers.some((value) => !Number.isFinite(value) || value < 0)) return `请完整填写 ${group.group_id} 的${this.materialImportFieldLabel(fieldname)}。`;
        const precision = Math.max(0, Number(metric.precision || 0));
        const factor = 10 ** precision;
        const actual = Math.round(numbers.reduce((sum, value) => sum + value, 0) * factor);
        const expected = Math.round(Number(metric.value || 0) * factor);
        if (actual !== expected) return `${group.group_id} 的${this.materialImportFieldLabel(fieldname)}分配合计应为 ${metric.value}。`;
      }
    }
    for (const group of preview.confirmation_groups || []) {
      if (choices.group_confirmations?.[group.group_id] !== true) return `请先确认 ${group.group_id} 的合并包装关系。`;
    }
    for (const issue of preview.source_validation?.blocking || []) {
      if (issue.confirmation_required && choices.source_validation?.[issue.confirmation_key] !== true) return `请先确认：${issue.message || issue.code}。`;
    }
    for (const row of preview.rows || []) {
      if (row.match_status === "choice_required" && !choices.matches?.[row.source_row]) return `请为来源行 ${row.source_row} 选择采购明细。`;
      for (const conflict of row.source_conflicts || []) {
        const selected = preview.is_merged_preview
          ? choices.merged_source_fields?.[row.source_row]?.[conflict.field]
          : choices.source_fields?.[row.source_row]?.[conflict.field];
        if (!selected) return `请处理来源行 ${row.source_row} 的${this.materialImportFieldLabel(conflict.field)}冲突。`;
      }
    }
    return "";
  }
