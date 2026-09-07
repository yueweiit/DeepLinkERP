  materialGridColumns() {
    return [
      { fieldname: "row_no", label: "行", group: "定位", editable: false },
      { fieldname: "material_code", label: "物料编码", group: "基础资料", editable: true },
      { fieldname: "product_name", label: "物料名称", group: "基础资料", editable: true },
      { fieldname: "spec_model", label: "规格型号", group: "基础资料", editable: true },
      { fieldname: "quantity", label: "采购数量", group: "采购口径", editable: true },
      { fieldname: "purchase_uom", label: "采购单位", group: "采购口径", editable: true },
      { fieldname: "unit_price", label: "采购单价", group: "采购口径", editable: true },
      { fieldname: "unit_price_uom", label: "计价单位", group: "采购口径", editable: true },
      { fieldname: "purchase_currency", label: "币种", group: "采购口径", editable: true },
      { fieldname: "goods_value", label: "采购货值", group: "采购口径", editable: true },
      { fieldname: "actual_shipped_qty", label: "发货数量", group: "发货与装箱", editable: true, quantity: true },
      { fieldname: "shipped_uom", label: "发货单位", group: "发货与装箱", editable: true },
      { fieldname: "gross_weight_kg", label: "毛重 kg", group: "发货与装箱", editable: true },
      { fieldname: "volume_m3", label: "体积 m³", group: "发货与装箱", editable: true },
      { fieldname: "chargeable_weight_kg", label: "计费重 kg", group: "发货与装箱", editable: true },
      { fieldname: "project_collection", label: "项目归属", group: "ERP 路由", editable: true },
      { fieldname: "subsidiary_code", label: "子公司", group: "ERP 路由", editable: false, route: true },
      { fieldname: "erp_site_code", label: "ERP 站点", group: "ERP 路由", editable: false, route: true },
      { fieldname: "total_unit_rmb", label: "综合单价 RMB", group: "成本结果", editable: false },
      { fieldname: "cost_output_uom", label: "成本单位", group: "成本结果", editable: false },
    ];
  }

  fetchMaterialGrid(batch, sku) {
    return this.call("overseas_costing.api.materials.get_material_grid", {
      batch_name: batch.name,
      version_name: this.detailState.versionName || batch.current_version || null,
      page: sku.page,
      page_length: sku.pageLength,
    });
  }

  renderMaterialGrid(result = {}) {
    const sku = this.detailState.sku;
    const columns = this.materialGridColumns();
    const items = result.items || [];
    const summary = result.requirements_summary || {};
    const calculated = OverseasCostWorkbenchState.summarizeMaterialRequirements(items);
    const calculationMissing = Number(summary.blocking_for_calculation ?? calculated.calculation ?? 0);
    const erpMissing = Number(summary.blocking_for_erp ?? calculated.erpPush ?? 0);
    const warnings = Number(summary.warnings ?? calculated.warnings ?? 0);
    const body = items.map((row, rowIndex) => `
      <tr data-material-row="${this.escape(row.name || "")}" data-stable-line-key="${this.escape(row.stable_line_key || "")}" data-row-index="${rowIndex}">
        ${columns.map((column, columnIndex) => this.renderMaterialGridCell(row, column, rowIndex, columnIndex)).join("")}
      </tr>
    `).join("");

    this.$root.find("[data-area='detail-content']").html(`
      <div class="ocw-material-page">
        <div class="ocw-material-flow" aria-label="本批次资料处理顺序">
          <span><b>1</b><strong>费用与凭证</strong><small>先看还有哪些费用未分摊</small></span>
          <i>→</i>
          <span class="active"><b>2</b><strong>物料与装箱</strong><small>有装箱计划就导入，没有也可补填</small></span>
          <i>→</i>
          <span><b>3</b><strong>成本结果</strong><small>先预览，推送前补齐 ERP 路由</small></span>
        </div>
        <div class="ocw-detail-section-head ocw-material-heading">
          <div><span>Excel 式补充与校验</span><h2>物料与装箱</h2></div>
          <div class="ocw-material-actions">
            <button class="ocw-outline-btn" type="button" data-action="open-packing-flow">获取装箱计划</button>
            <button class="ocw-outline-btn" type="button" data-action="material-import" data-source-tab="approval">从 OA 附件补充</button>
            <button class="ocw-primary-btn" type="button" data-action="material-import" data-source-tab="local">从 Excel 补充</button>
          </div>
        </div>
        <div class="ocw-material-no-plan">
          <div><strong>没有装箱计划也可以继续</strong><span>系统先使用 OA 已拉取的物料；发货数量默认等于采购数量。红格可直接人工补填，成本可先预览。</span></div>
          <button class="ocw-link-btn" type="button" data-action="material-focus-first-gap">人工补填</button>
        </div>
        <div class="ocw-material-summary" aria-label="物料资料完成度">
          <article class="${calculationMissing ? "danger" : "done"}"><small>成本预览前待补</small><strong>${calculationMissing}</strong><span>${calculationMissing ? "红格会阻断本次成本计算" : "计算所需物料字段已齐"}</span></article>
          <article class="${erpMissing ? "warning" : "done"}"><small>ERP 推送前待补</small><strong>${erpMissing}</strong><span>${erpMissing ? "可先预览成本，推送前补项目归属" : "ERP 路由字段已齐"}</span></article>
          <article class="neutral"><small>提醒</small><strong>${warnings}</strong><span>可选或非阻断提示</span></article>
          <div class="ocw-material-legend"><span class="calculation">成本必补</span><span class="erp">推送前补</span><span class="default">采购数量默认</span></div>
        </div>
        <div class="ocw-sku-toolbar ocw-material-toolbar">
          <label><span>搜索当前页物料</span><input class="form-control" type="search" data-role="material-keyword" value="" placeholder="输入物料编码、名称或项目" /></label>
          <span>可复制 Excel 区域后直接粘贴；系统不会接受稳定行标识或成本结果字段。</span>
        </div>
        <div class="ocw-material-grid-shell">
          <div class="ocw-material-grid-wrap" data-role="sku-table-scroll">
            <table class="ocw-material-grid" data-role="material-grid">
              <thead><tr>${columns.map((column, index) => `<th class="${index < 3 ? `is-sticky sticky-${index}` : ""}"><small>${this.escape(column.group)}</small><strong>${this.escape(column.label)}</strong></th>`).join("")}</tr></thead>
              <tbody>${body || `<tr><td colspan="${columns.length}"><div class="ocw-detail-empty"><strong>当前批次还没有物料</strong><span>可以保留 OA 资料继续补充，或从 Excel 导入。</span></div></td></tr>`}</tbody>
            </table>
          </div>
        </div>
        <div class="ocw-sku-pagination">
          <span>当前第 ${Number(result.page || 1)} 页，共 ${Number(result.total || 0)} 行</span>
          <button class="ocw-outline-btn" type="button" data-action="sku-page" data-page="${Number(result.page || 1) - 1}" ${Number(result.page || 1) <= 1 ? "disabled" : ""}>上一页</button>
          <strong>第 ${Number(result.page || 1)} / ${Math.max(Number(result.page_count || 0), 1)} 页</strong>
          <button class="ocw-outline-btn" type="button" data-action="sku-page" data-page="${Number(result.page || 1) + 1}" ${Number(result.page || 1) >= Number(result.page_count || 0) ? "disabled" : ""}>下一页</button>
        </div>
      </div>
    `);
  }

  renderMaterialGridCell(row, column, rowIndex, columnIndex) {
    const requirement = ((row || {}).cell_requirements || {})[column.fieldname] || null;
    const routeView = column.route ? OverseasCostWorkbenchState.erpRoutePresentation(row) : null;
    const isCalculationBlocking = requirement && requirement.severity === "blocking" && requirement.gate !== "erp_push";
    const isErpBlocking = (requirement && requirement.severity === "blocking" && requirement.gate === "erp_push") || Boolean(routeView?.needsRoute);
    const classes = [
      "ocw-material-cell",
      columnIndex < 3 ? `is-sticky sticky-${columnIndex}` : "",
      column.editable ? "is-editable" : "is-readonly",
      isCalculationBlocking ? "is-calculation-blocking" : "",
      isErpBlocking ? "is-erp-blocking" : "",
      this.columnAlignClass(column),
    ].filter(Boolean).join(" ");
    let rawValue = row[column.fieldname];
    let display = this.renderCell(rawValue, column);
    let sourceBadge = "";
    if (column.quantity) {
      const quantity = OverseasCostWorkbenchState.materialQuantityView(row);
      rawValue = quantity.value;
      display = `<button type="button" class="ocw-material-quantity-btn" data-action="edit-shipping-quantity" data-item-name="${this.escape(row.name || "")}"><strong>${this.escape(this.formatNumber(quantity.value) || "—")}</strong><span>${this.escape(quantity.uom)}</span></button>`;
      sourceBadge = `<em class="ocw-material-source ${quantity.isDefault ? "is-default" : ""}">${this.escape(quantity.sourceLabel)}</em>`;
    }
    if (column.route) {
      const route = routeView;
      rawValue = column.fieldname === "subsidiary_code" ? route.subsidiaryCode : route.siteCode;
      display = `<div class="ocw-material-route is-${route.tone}"><strong>${this.escape(rawValue || "待补")}</strong><small>${this.escape(route.needsRoute ? route.label : (row.route_status === "OVERRIDDEN" ? "整批人工归属" : "按项目解析"))}</small></div>`;
    }
    const issueBadge = isCalculationBlocking
      ? `<em class="ocw-material-issue is-calculation">${this.escape(requirement.message || "成本预览前请补充")}</em>`
      : isErpBlocking
        ? `<em class="ocw-material-issue is-erp">${this.escape(requirement?.message || "推送前补")}</em>`
        : "";
    const editable = Boolean(column.editable);
    const genericEditable = editable && !column.quantity;
    const title = requirement && requirement.severity !== "optional" ? requirement.message : this.formatCellValue(rawValue, column);
    return `
      <td class="${classes}" role="gridcell" tabindex="${editable ? "0" : "-1"}"
        aria-invalid="${isCalculationBlocking || isErpBlocking ? "true" : "false"}"
        aria-label="${this.escape(`${column.label}${title ? `：${title}` : ""}`)}" title="${this.escape(title || "")}"
        data-grid-editable="${editable ? "1" : "0"}" data-row-index="${rowIndex}" data-column-index="${columnIndex}"
        data-editable-cell="${genericEditable ? "1" : "0"}" data-batch-name="${this.escape(this.detailState.batchName)}"
        data-item-name="${this.escape(row.name || "")}" data-stable-line-key="${this.escape(row.stable_line_key || "")}"
        data-version-name="${this.escape(this.detailState.versionName || "")}" data-fieldname="${this.escape(column.fieldname)}"
        data-field-label="${this.escape(column.label)}" data-raw-value="${this.escape(this.normalizeEditorValue(rawValue))}"
        data-special-override="0"><div class="ocw-material-value">${display}</div>${sourceBadge}${issueBadge}</td>
    `;
  }

  focusFirstMaterialGap() {
    const $cell = this.$root.find(".ocw-material-cell.is-calculation-blocking, .ocw-material-cell.is-erp-blocking").first();
    if (!$cell.length) {
      frappe.show_alert({ message: "当前页没有待补红格", indicator: "green" });
      return;
    }
    $cell.get(0).scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    if ($cell.attr("data-fieldname") === "actual_shipped_qty") $cell.find("[data-action='edit-shipping-quantity']").trigger("click");
    else $cell.trigger("click");
  }

  async commitMaterialCellAndMove($cell, reverse = false) {
    const itemName = $cell.attr("data-item-name");
    const fieldname = $cell.attr("data-fieldname");
    await this.commitCellEdit($cell);
    const $current = this.$root.find(".ocw-material-cell").filter((_, cell) => {
      const $candidate = $(cell);
      return $candidate.attr("data-item-name") === itemName && $candidate.attr("data-fieldname") === fieldname;
    }).first();
    const cells = this.$root.find(".ocw-material-cell[data-grid-editable='1']").get().map((cell) => ({ editable: true, cell }));
    const currentIndex = cells.findIndex((entry) => entry.cell === $current.get(0));
    const nextIndex = OverseasCostWorkbenchState.nextMaterialEditableCell(cells, currentIndex, reverse);
    if (nextIndex < 0) return;
    const $next = $(cells[nextIndex].cell);
    $next.get(0)?.scrollIntoView({ block: "nearest", inline: "nearest" });
    if ($next.attr("data-fieldname") === "actual_shipped_qty") $next.find("button").focus();
    else $next.trigger("click");
  }

  openShippingQuantityDialog(itemName) {
    const row = ((this.detailState.skuResult || {}).items || []).find((item) => String(item.name) === String(itemName));
    if (!row) throw new Error("当前页未找到这条物料，请刷新后重试。");
    const quantity = OverseasCostWorkbenchState.materialQuantityView(row);
    const dialog = new frappe.ui.Dialog({
      title: `确认发货数量 · ${row.material_code || row.product_name || row.row_no || ""}`,
      fields: [
        { fieldtype: "HTML", fieldname: "help", options: `<div class="ocw-material-quantity-help"><strong>采购数量 ${this.escape(this.formatNumber(row.quantity) || "—")} ${this.escape(row.purchase_uom || row.unit || "")}</strong><span>默认模式会始终跟随采购数量；只有确实不同时才改为人工确认。</span></div>` },
        { fieldtype: "Select", fieldname: "mode", label: "数量来源", options: "采购数量默认\n人工确认", default: quantity.isDefault ? "采购数量默认" : "人工确认", reqd: 1 },
        { fieldtype: "Float", fieldname: "value", label: "实际发货数量", default: quantity.value || row.quantity || "", depends_on: "eval:doc.mode=='人工确认'", mandatory_depends_on: "eval:doc.mode=='人工确认'" },
        { fieldtype: "Data", fieldname: "uom", label: "发货单位", default: quantity.uom, reqd: 1 },
      ],
      primary_action_label: "保存数量口径",
      primary_action: async (values) => {
        try {
          if (!(await this.ensureEditSession())) return;
          const mode = values.mode === "采购数量默认" ? "DEFAULT_PURCHASE" : "MANUAL_CONFIRMED";
          const result = await this.call("overseas_costing.api.materials.set_shipping_quantity", {
            batch_name: this.detailState.batchName,
            item_name: row.name,
            mode,
            value: mode === "DEFAULT_PURCHASE" ? row.quantity : values.value,
            uom: values.uom,
            edit_token: this.detailState.editToken,
            expected_modified: this.detailState.expectedModified || this.getDetailBatch().modified || "",
          }, true);
          if (!result || !result.ok) throw new Error((result && result.message) || "发货数量保存失败。");
          this.detailState.expectedModified = result.batch_modified || this.detailState.expectedModified;
          dialog.hide();
          await this.refreshDetailSummary();
          frappe.show_alert({ message: mode === "DEFAULT_PURCHASE" ? "已恢复为采购数量默认" : "已保存实际发货数量", indicator: "green" });
        } catch (error) {
          this.showError(error);
        }
      },
    });
    dialog.show();
  }

  async handleMaterialGridPaste(event) {
    const nativeEvent = event.originalEvent || event;
    const text = String(nativeEvent.clipboardData?.getData("text/plain") || "");
    if (!text.trim()) return;
    const $start = $(event.target).closest(".ocw-material-cell");
    if (!$start.length) return;
    event.preventDefault();
    const matrix = text.replace(/\r/g, "").split("\n").filter((row) => row !== "").map((row) => row.split("\t"));
    const $rows = this.$root.find(".ocw-material-grid tbody tr[data-material-row]");
    const startRow = Number($start.attr("data-row-index") || 0);
    const startColumn = Number($start.attr("data-column-index") || 0);
    const regular = [];
    const quantities = [];
    matrix.forEach((values, offset) => {
      const $row = $rows.eq(startRow + offset);
      if (!$row.length) return;
      const $cells = $row.find(".ocw-material-cell").slice(startColumn, startColumn + values.length);
      const columns = $cells.get().map((cell) => ({ fieldname: $(cell).attr("data-fieldname"), editable: $(cell).attr("data-grid-editable") === "1" }));
      const itemName = $row.attr("data-material-row");
      OverseasCostWorkbenchState.buildMaterialPasteUpdates(columns, values).forEach((update) => {
        const payload = { item_name: itemName, fieldname: update.fieldname, value: update.value };
        if (update.fieldname === "actual_shipped_qty") quantities.push(payload);
        else regular.push(payload);
      });
    });
    if (!regular.length && !quantities.length) {
      frappe.show_alert({ message: "粘贴区域没有可写入字段", indicator: "orange" });
      return;
    }
    const confirmed = await new Promise((resolve) => frappe.confirm(
      `将粘贴 ${regular.length + quantities.length} 个物料字段。稳定行标识和成本结果不会被修改，是否继续？`,
      () => resolve(true),
      () => resolve(false)
    ));
    if (!confirmed || !(await this.ensureEditSession())) return;
    try {
      for (const update of quantities) {
        const row = ((this.detailState.skuResult || {}).items || []).find((item) => item.name === update.item_name) || {};
        const result = await this.call("overseas_costing.api.materials.set_shipping_quantity", {
          batch_name: this.detailState.batchName,
          item_name: update.item_name,
          mode: "MANUAL_CONFIRMED",
          value: update.value,
          uom: row.shipped_uom || row.purchase_uom || row.unit || "",
          edit_token: this.detailState.editToken,
          expected_modified: this.detailState.expectedModified || this.getDetailBatch().modified || "",
        }, true);
        if (!result || !result.ok) throw new Error((result && result.message) || "粘贴发货数量失败。");
        this.detailState.expectedModified = result.batch_modified || this.detailState.expectedModified;
      }
      if (regular.length) {
        const result = await this.call("overseas_costing.api.calculate.batch_update_items", {
          batch_name: this.detailState.batchName,
          version_name: this.detailState.versionName || null,
          updates: JSON.stringify(regular),
          remark: "从物料网格粘贴补充",
          edit_token: this.detailState.editToken,
          expected_modified: this.detailState.expectedModified || this.getDetailBatch().modified || "",
        }, true);
        if (!result || !result.ok) throw new Error((result && result.message) || "物料网格粘贴保存失败。");
      }
      await this.refreshDetailSummary();
      frappe.show_alert({ message: `已保存 ${regular.length + quantities.length} 个字段`, indicator: "green" });
    } catch (error) {
      this.showError(error);
    }
  }

  async openMaterialImportDialog(sourceTab = "local") {
    const batch = this.getDetailBatch();
    if (!batch || !batch.name) throw new Error("请先打开一个批次。");
    const dialog = new frappe.ui.Dialog({
      title: "从 Excel 补充物料与装箱信息",
      size: "extra-large",
      fields: [{ fieldtype: "HTML", fieldname: "material_import", options: `<div class="ocw-material-import" data-area="material-import"><div class="ocw-detail-state"><span class="ocw-spinner"></span><strong>正在读取可用资料</strong></div></div>` }],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.materialImportState = { step: 1, sourceTab, sources: null, sourceKind: "", sourceId: "", sheetName: "", preview: null, mappingConfirmed: false, choices: { matches: {}, fields: {} }, error: "" };
    dialog.show();
    dialog.$wrapper.addClass("ocw-material-import-dialog");
    this.bindMaterialImportEvents(dialog, batch);
    await this.loadMaterialImportSources(dialog, batch);
    return dialog;
  }

  async loadMaterialImportSources(dialog, batch) {
    try {
      dialog.materialImportState.sources = await this.call("overseas_costing.api.packing_api.list_packing_sources", { batch_name: batch.name }, false);
      dialog.materialImportState.error = "";
    } catch (error) {
      dialog.materialImportState.error = this.normalizeErrorMessage(error);
    }
    this.renderMaterialImportDialog(dialog, batch);
  }

  materialImportSources(state) {
    const sources = state.sources || {};
    if (state.sourceTab === "local") return sources.manual_attachments || [];
    if (state.sourceTab === "approval") return sources.approval_sources || [];
    return (sources.wiki_workbooks || []).flatMap((workbook) => workbook.sheets || []);
  }

  renderMaterialImportDialog(dialog, batch) {
    const state = dialog.materialImportState;
    const $target = dialog.$wrapper.find("[data-area='material-import']");
    const labels = ["第 1 步：选择资料和 Sheet", "第 2 步：确认列映射和行匹配", "第 3 步：确认差异和冲突"];
    $target.html(`
      <header class="ocw-material-import-head"><div><small>当前批次</small><strong>${this.escape(batch.batch_no || batch.name)}</strong></div><ol>${labels.map((label, index) => `<li class="${state.step === index + 1 ? "active" : state.step > index + 1 ? "done" : ""}"><b>${index + 1}</b><span>${label}</span></li>`).join("")}</ol></header>
      ${state.error ? `<div class="ocw-packing-flow-error"><strong>操作失败</strong><span>${this.escape(state.error)}</span></div>` : ""}
      ${state.step === 1 ? this.renderMaterialImportSourceStep(state) : ""}
      ${state.step === 2 ? this.renderMaterialImportMappingStep(state) : ""}
      ${state.step === 3 ? this.renderMaterialImportConflictStep(state) : ""}
    `);
  }

  renderMaterialImportSourceStep(state) {
    const rows = this.materialImportSources(state);
    const tabs = [["local", "本地 Excel"], ["approval", "OA 附件"], ["wiki", "装箱计划表"]];
    return `<section class="ocw-material-import-step">
      <div class="ocw-packing-source-tabs">${tabs.map(([key, label]) => `<button type="button" class="${state.sourceTab === key ? "active" : ""}" data-action="material-import-tab" data-source-tab="${key}">${label}</button>`).join("")}</div>
      <div class="ocw-material-import-note"><strong>没有装箱计划也可以继续</strong><span>可选择 OA 里已归档的 Excel，也可上传一份只用于补字段的 Excel；此处先预览，不直接写入。</span></div>
      ${state.sourceTab === "local" ? `<button class="ocw-outline-btn" type="button" data-action="material-import-upload">上传私有 Excel</button>` : ""}
      <div class="ocw-material-import-sources">${rows.length ? rows.map((source) => this.renderMaterialImportSource(source, state)).join("") : `<div class="ocw-detail-empty"><strong>暂无可用 Excel</strong><span>${state.sourceTab === "approval" ? "OA 已拉取的其他资料仍然保留，可直接人工补填红格。" : "上传 .xlsx 或 .xlsm 后选择 Sheet。"}</span></div>`}</div>
      <footer class="ocw-material-import-footer"><span>${state.sourceId ? `已选：${this.escape(state.sheetName || state.sourceId)}` : "请选择一个明确的 Sheet"}</span><button class="ocw-primary-btn" type="button" data-action="material-import-preview" ${state.sourceId ? "" : "disabled"}>生成字段预览</button></footer>
    </section>`;
  }

  renderMaterialImportSource(source, state) {
    if (source.source_kind === "approval_comment") {
      const selected = state.sourceKind === source.source_kind && String(state.sourceId) === String(source.source_id);
      return `<button type="button" class="ocw-material-import-source ${selected ? "selected" : ""}" data-action="material-import-select" data-source-kind="approval_comment" data-source-id="${this.escape(source.source_id || "")}" data-sheet-name=""><small>OA 评论资料 · 无需 Sheet</small><strong>${this.escape(source.source_label || source.source_id || "")}</strong><span>${this.escape(source.remark_preview || source.source_updated_at || "已归档")}</span></button>`;
    }
    if (source.source_kind === "wiki_sheet") {
      const selected = state.sourceKind === source.source_kind && String(state.sourceId) === String(source.source_id);
      return `<button type="button" class="ocw-material-import-source ${selected ? "selected" : ""}" data-action="material-import-select" data-source-kind="wiki_sheet" data-source-id="${this.escape(source.source_id || "")}" data-sheet-name="${this.escape(source.source_label || "")}"><small>装箱计划 Sheet</small><strong>${this.escape(source.source_label || source.source_id || "")}</strong><span>${this.escape(source.business_date || source.source_updated_at || "已归档")}</span></button>`;
    }
    const sheets = source.sheets || [];
    return `<article class="ocw-material-import-file"><div><small>${source.source_kind === "approval_attachment" ? "OA 附件" : "本地文件"}</small><strong>${this.escape(source.source_label || source.source_id || "")}</strong></div><div>${sheets.length ? sheets.map((sheet) => {
      const selected = state.sourceKind === source.source_kind && String(state.sourceId) === String(source.source_id) && state.sheetName === sheet;
      return `<button type="button" class="${selected ? "selected" : ""}" data-action="material-import-select" data-source-kind="${this.escape(source.source_kind || "")}" data-source-id="${this.escape(source.source_id || "")}" data-sheet-name="${this.escape(sheet)}">${this.escape(sheet)}</button>`;
    }).join("") : `<span>该附件不是可读取的 Excel，不会在此处猜测字段。</span>`}</div></article>`;
  }

  async previewMaterialImport(dialog, batch) {
    const state = dialog.materialImportState;
    try {
      const preview = await this.call("overseas_costing.api.materials.preview_material_import", {
        batch_name: batch.name,
        source_kind: state.sourceKind,
        source_id: state.sourceId,
        sheet_name: state.sheetName || null,
      }, true);
      if (!preview || !preview.ok) throw new Error((preview && preview.message) || "物料导入预览失败。");
      state.preview = preview;
      state.step = 2;
      state.mappingConfirmed = false;
      state.choices = { matches: {}, fields: {} };
      state.error = "";
    } catch (error) {
      state.error = this.normalizeErrorMessage(error);
    }
    this.renderMaterialImportDialog(dialog, batch);
  }

  renderMaterialImportMappingStep(state) {
    const preview = state.preview || {};
    const matchingReady = (preview.rows || []).every((row) => row.match_status !== "choice_required" || state.choices.matches[String(row.source_row)]);
    return `<section class="ocw-material-import-step">
      <div class="ocw-material-mapping"><h3>列映射</h3>${(preview.mapping || []).map((mapping) => `<span><b>${this.escape(mapping.source)}</b><i>→</i><strong>${this.escape(mapping.target)}</strong></span>`).join("") || `<p>未识别到可采用字段。</p>`}</div>
      <label class="ocw-material-confirm-line"><input type="checkbox" data-action="material-mapping-confirm" ${state.mappingConfirmed ? "checked" : ""} /> 我已确认列映射，不会把稳定行标识作为导入字段</label>
      <div class="ocw-material-match-list">${(preview.rows || []).map((row) => this.renderMaterialMatchRow(row, state)).join("") || `<div class="ocw-detail-empty">这个 Sheet 没有识别到物料行。</div>`}</div>
      <footer class="ocw-material-import-footer"><button class="ocw-outline-btn" type="button" data-action="material-import-back" data-step="1">返回选择资料</button><span>${matchingReady ? "行匹配已明确" : "请先为重复 SKU 选择具体目标行"}</span><button class="ocw-primary-btn" type="button" data-action="material-import-next" ${state.mappingConfirmed && matchingReady && (preview.mapping || []).length ? "" : "disabled"}>下一步：看差异</button></footer>
    </section>`;
  }

  renderMaterialMatchRow(row, state) {
    const statusLabels = { matched: "已匹配", choice_required: "需选择", unmatched: "未匹配，本次跳过" };
    const sourceRow = String(row.source_row ?? "");
    const incoming = row.incoming || {};
    return `<article class="ocw-material-match-row is-${this.escape(row.match_status || "")}"><div><small>Excel 第 ${this.escape(sourceRow)} 行</small><strong>${this.escape(incoming.material_code || incoming.product_name || "未命名物料")}</strong><span>${statusLabels[row.match_status] || row.match_status || ""}</span></div>${row.match_status === "choice_required" ? `<select data-action="material-match-choice" data-source-row="${this.escape(sourceRow)}"><option value="">选择同 SKU 目标行</option>${(row.candidates || []).map((candidate) => `<option value="${this.escape(candidate.stable_line_key || "")}" ${state.choices.matches[sourceRow] === candidate.stable_line_key ? "selected" : ""}>${this.escape(`第 ${candidate.row_no || "?"} 行 · ${candidate.material_code || ""} · ${candidate.source_doc_no || "无单号"}`)}</option>`).join("")}</select>` : `<em>${Number((row.changes || []).length)} 个字段变化</em>`}</article>`;
  }

  renderMaterialImportConflictStep(state) {
    const preview = state.preview || {};
    const canApply = OverseasCostWorkbenchState.materialImportCanApply(preview, state);
    return `<section class="ocw-material-import-step"><div class="ocw-material-diff-summary"><span>已匹配 <strong>${Number((preview.summary || {}).matched || 0)}</strong></span><span>字段变化 <strong>${Number((preview.summary || {}).changed_fields || 0)}</strong></span><span>未匹配跳过 <strong>${Number((preview.summary || {}).unmatched || 0)}</strong></span></div>
      <div class="ocw-material-diff-list">${(preview.rows || []).map((row) => (row.changes || []).map((change) => this.renderMaterialDiff(row, change, state)).join("")).join("") || `<div class="ocw-detail-empty"><strong>没有需写入的变化</strong><span>当前资料与系统已一致。</span></div>`}</div>
      <footer class="ocw-material-import-footer"><button class="ocw-outline-btn" type="button" data-action="material-import-back" data-step="2">返回行匹配</button><span>${canApply ? "所有冲突已确认" : "每个黄色冲突都要选择保留哪个值"}</span><button class="ocw-primary-btn" type="button" data-action="material-import-apply" ${canApply ? "" : "disabled"}>确认采用并写入</button></footer>
    </section>`;
  }

  renderMaterialDiff(row, change, state) {
    const sourceRow = String(row.source_row ?? "");
    const decision = ((state.choices.fields[sourceRow] || {})[change.field]) || "";
    return `<article class="ocw-material-diff ${change.conflict ? "has-conflict" : ""}"><header><small>Excel 第 ${this.escape(sourceRow)} 行</small><strong>${this.escape(change.field)}</strong>${change.conflict ? `<em>冲突</em>` : `<em>新增</em>`}</header><div><span><small>当前值</small><b>${this.escape(this.formatValue(change.old) || "空")}</b></span><i>→</i><span><small>Excel 值</small><b>${this.escape(this.formatValue(change.new) || "空")}</b></span></div>${change.conflict ? `<footer><label><input type="radio" name="material-diff-${this.escape(sourceRow)}-${this.escape(change.field)}" data-action="material-conflict-choice" data-source-row="${this.escape(sourceRow)}" data-fieldname="${this.escape(change.field)}" value="use_source" ${decision === "use_source" ? "checked" : ""} />采用 Excel</label><label><input type="radio" name="material-diff-${this.escape(sourceRow)}-${this.escape(change.field)}" data-action="material-conflict-choice" data-source-row="${this.escape(sourceRow)}" data-fieldname="${this.escape(change.field)}" value="keep_current" ${decision === "keep_current" ? "checked" : ""} />保留当前值</label></footer>` : ""}</article>`;
  }

  bindMaterialImportEvents(dialog, batch) {
    dialog.$wrapper.off(".ocwMaterialImport").on("click.ocwMaterialImport", "[data-action='material-import-tab']", (event) => {
      const state = dialog.materialImportState;
      Object.assign(state, { sourceTab: $(event.currentTarget).attr("data-source-tab") || "local", sourceKind: "", sourceId: "", sheetName: "" });
      this.renderMaterialImportDialog(dialog, batch);
    }).on("click.ocwMaterialImport", "[data-action='material-import-select']", (event) => {
      const $button = $(event.currentTarget);
      Object.assign(dialog.materialImportState, { sourceKind: $button.attr("data-source-kind") || "", sourceId: $button.attr("data-source-id") || "", sheetName: $button.attr("data-sheet-name") || "" });
      this.renderMaterialImportDialog(dialog, batch);
    }).on("click.ocwMaterialImport", "[data-action='material-import-upload']", () => this.uploadMaterialImportExcel(dialog, batch))
      .on("click.ocwMaterialImport", "[data-action='material-import-preview']", () => this.previewMaterialImport(dialog, batch))
      .on("change.ocwMaterialImport", "[data-action='material-mapping-confirm']", (event) => {
        dialog.materialImportState.mappingConfirmed = $(event.currentTarget).is(":checked");
        this.renderMaterialImportDialog(dialog, batch);
      }).on("change.ocwMaterialImport", "[data-action='material-match-choice']", (event) => {
        dialog.materialImportState.choices.matches[$(event.currentTarget).attr("data-source-row")] = $(event.currentTarget).val() || "";
        this.renderMaterialImportDialog(dialog, batch);
      }).on("click.ocwMaterialImport", "[data-action='material-import-next']", () => {
        dialog.materialImportState.step = 3;
        this.renderMaterialImportDialog(dialog, batch);
      }).on("click.ocwMaterialImport", "[data-action='material-import-back']", (event) => {
        dialog.materialImportState.step = Number($(event.currentTarget).attr("data-step") || 1);
        this.renderMaterialImportDialog(dialog, batch);
      }).on("change.ocwMaterialImport", "[data-action='material-conflict-choice']", (event) => {
        const $field = $(event.currentTarget);
        const sourceRow = $field.attr("data-source-row");
        dialog.materialImportState.choices.fields[sourceRow] = dialog.materialImportState.choices.fields[sourceRow] || {};
        dialog.materialImportState.choices.fields[sourceRow][$field.attr("data-fieldname")] = $field.val();
        this.renderMaterialImportDialog(dialog, batch);
      }).on("click.ocwMaterialImport", "[data-action='material-import-apply']", () => this.applyMaterialImport(dialog, batch));
  }

  uploadMaterialImportExcel(dialog, batch) {
    if (!frappe.ui.FileUploader) throw new Error("当前页面暂时无法打开文件上传器。");
    new frappe.ui.FileUploader({
      allow_multiple: false,
      is_private: 1,
      restrictions: { allowed_file_types: [".xlsx", ".xlsm"] },
      on_success: async (fileDoc) => {
        try {
          const file = Array.isArray(fileDoc) ? fileDoc[0] : fileDoc;
          const result = await this.call("overseas_costing.api.import_api.register_manual_document_attachment", {
            batch_name: batch.name,
            version_name: this.detailState.versionName || batch.current_version || null,
            logistics_type: this.detectManualDocumentLogisticsType(batch) || "GENERAL",
            slot_code: "material_excel",
            slot_label: "物料与装箱 Excel",
            attachment_type: "Packing List",
            file_url: file.file_url || file.file_url_private || "",
            file_name: file.file_name || file.name || "",
            required: 0,
          }, true);
          if (!result || !result.ok) throw new Error((result && result.message) || "Excel 登记失败。");
          dialog.materialImportState.sourceTab = "local";
          await this.loadMaterialImportSources(dialog, batch);
        } catch (error) {
          dialog.materialImportState.error = this.normalizeErrorMessage(error);
          this.renderMaterialImportDialog(dialog, batch);
        }
      },
    });
    [0, 100, 300, 800].forEach((delay) => window.setTimeout(() => this.localizeFrappeFileUploader("物料与装箱 Excel"), delay));
  }

  async applyMaterialImport(dialog, batch) {
    const state = dialog.materialImportState;
    if (!OverseasCostWorkbenchState.materialImportCanApply(state.preview, state)) return;
    try {
      if (!(await this.ensureEditSession())) return;
      const result = await this.call("overseas_costing.api.materials.apply_material_import", {
        batch_name: batch.name,
        preview_revision: state.preview.preview_revision,
        choices_json: JSON.stringify(state.choices),
        edit_token: this.detailState.editToken,
        expected_modified: this.detailState.expectedModified || batch.modified || "",
      }, true);
      if (!result || !result.ok) {
        if (result && result.source_changed) state.step = 1;
        throw new Error((result && result.message) || "导入预览已过期或冲突未确认，请重新预览。");
      }
      dialog.hide();
      await this.refreshDetailSummary();
      frappe.show_alert({ message: `已更新 ${Number(result.updated_count || 0)} 行、${Number(result.changed_field_count || 0)} 个字段`, indicator: "green" });
    } catch (error) {
      state.error = this.normalizeErrorMessage(error);
      this.renderMaterialImportDialog(dialog, batch);
    }
  }
