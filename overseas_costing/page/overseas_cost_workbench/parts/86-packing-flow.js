  async openPackingFlowDialog(options = {}) {
    const batch = this.getDetailBatch();
    if (!batch || !batch.name) throw new Error("请先打开一个批次。");
    const dialog = new frappe.ui.Dialog({
      title: "获取装箱单与比较运费",
      size: "extra-large",
      fields: [{
        fieldtype: "HTML",
        fieldname: "packing_flow",
        options: `<div class="ocw-packing-flow" data-area="packing-flow"><div class="ocw-packing-flow-loading">正在读取可用来源…</div></div>`,
      }],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.packingFlowState = OverseasCostWorkbenchState.createPackingFlowState();
    dialog.packingFlowOptions = { ...options };
    dialog.packingFlowSources = null;
    dialog.packingFlowError = "";
    dialog.packingSourceTab = options.sourceTab || "local";
    dialog.show();
    dialog.$wrapper.addClass("ocw-packing-flow-dialog");
    this.bindPackingFlowEvents(dialog, batch);
    await this.loadPackingFlowSources(dialog, batch, options);
    return dialog;
  }

  renderPackingComparisonCardStatus(batch) {
    const rows = (this.packingComparisonHistoryByBatch || {})[batch.name] || [];
    const latest = rows[0];
    const labels = { weight: "按重量更优", volume: "按体积更优", equal: "两种相同", unconfirmed: "服务范围未确认" };
    return `<div class="ocw-packing-card-comparison">${latest ? `<span>最新试算：<strong>${this.escape(labels[latest.recommended_basis] || latest.recommended_basis || "--")}</strong></span><small>${this.escape(latest.currency || "")} ${this.escape(this.formatMoney(latest.difference_amount) || latest.difference_amount || "0.00")} 差额</small>` : `<span>尚无整票重量/体积试算</span>`}<button class="ocw-link-btn" type="button" data-action="open-packing-comparison-history">查看试算历史</button></div>`;
  }

  async openPackingComparisonHistory() {
    const batch = this.getDetailBatch();
    const rows = await this.call("overseas_costing.api.packing_api.list_freight_comparisons", {
      batch_name: batch.name,
    }, false);
    const labels = { weight: "按重量", volume: "按体积", equal: "两种相同", unconfirmed: "未确认范围" };
    const dialog = new frappe.ui.Dialog({
      title: "整票运费试算历史",
      size: "large",
      fields: [{ fieldtype: "HTML", fieldname: "history", options: `<div class="ocw-packing-history"><div class="ocw-packing-independent-note"><strong>独立试算，不修改正式费用</strong><span>历史结果始终保留其当时的装箱快照。</span></div>${Array.isArray(rows) && rows.length ? rows.map((row) => `<article class="ocw-packing-history-row"><div><strong>${this.escape(labels[row.recommended_basis] || row.recommended_basis || "--")}</strong><span>${this.escape(this.formatDateTimeMinute(row.creation) || row.creation || "--")}</span></div><dl><div><dt>毛重</dt><dd>${this.escape(row.gross_weight_kg || "--")} kg</dd></div><div><dt>体积</dt><dd>${this.escape(row.volume_m3 || "--")} m³</dd></div><div><dt>重量总价</dt><dd>${this.escape(row.currency || "")} ${this.escape(this.formatMoney(row.weight_total) || row.weight_total || "--")}</dd></div><div><dt>体积总价</dt><dd>${this.escape(row.currency || "")} ${this.escape(this.formatMoney(row.volume_total) || row.volume_total || "--")}</dd></div></dl>${row.based_on_superseded_snapshot ? `<em>基于历史装箱快照</em>` : ""}${row.quote_remark ? `<p>${this.escape(row.quote_remark)}</p>` : ""}</article>`).join("") : `<div class="ocw-detail-empty"><strong>尚无已保存试算</strong><span>先在装箱单中确认整票毛重和体积，再输入两套报价。</span></div>`}</div>` }],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
  }

  async openPackingFlowFromDingtalk(sourceKind, sourceId, processInstanceId = "", fileId = "") {
    let normalizedKind = sourceKind === "comment" ? "approval_comment" : "approval_attachment";
    let normalizedId = sourceId || "";
    if (normalizedKind === "approval_attachment") {
      normalizedId = await this.ensureDingtalkLocalAttachment(normalizedId, processInstanceId, fileId);
    }
    return this.openPackingFlowDialog({
      sourceTab: "approval",
      sourceKind: normalizedKind,
      sourceId: normalizedId,
    });
  }

  async loadPackingFlowSources(dialog, batch, options = {}) {
    try {
      const result = await this.call("overseas_costing.api.packing_api.list_packing_sources", {
        batch_name: batch.name,
      }, false);
      dialog.packingFlowSources = result || {};
      dialog.packingFlowError = "";
      const requestedKind = options.sourceKind || dialog.packingFlowOptions.sourceKind;
      const requestedId = options.sourceId || dialog.packingFlowOptions.sourceId;
      if (requestedKind && requestedId) {
        const source = this.findPackingFlowSource(result, requestedKind, requestedId);
        const sheetName = source && Array.isArray(source.sheets) && source.sheets.length === 1 ? source.sheets[0] : "";
        dialog.packingFlowState = OverseasCostWorkbenchState.selectPackingSource(
          dialog.packingFlowState, requestedKind, requestedId, sheetName
        );
      }
    } catch (error) {
      dialog.packingFlowError = this.normalizeErrorMessage(error);
    }
    this.renderPackingFlow(dialog, batch);
  }

  findPackingFlowSource(sources = {}, sourceKind = "", sourceId = "") {
    const rows = [
      ...(sources.manual_attachments || []),
      ...(sources.approval_sources || []),
      ...(sources.wiki_workbooks || []).flatMap((workbook) => workbook.sheets || []),
    ];
    return rows.find((row) => row.source_kind === sourceKind && String(row.source_id) === String(sourceId)) || null;
  }

  renderPackingFlow(dialog, batch) {
    const state = dialog.packingFlowState;
    const $target = dialog.$wrapper.find("[data-area='packing-flow']");
    const steps = ["选择来源", "预览与确认", "比较运费"];
    $target.html(`
      <div class="ocw-packing-flow-head">
        <div><span>当前批次</span><strong>${this.escape(batch.batch_no || batch.waybill_no || batch.name)}</strong></div>
        <ol>${steps.map((label, index) => `<li class="${state.step === index + 1 ? "active" : state.step > index + 1 ? "done" : ""}"><b>${index + 1}</b><span>${label}</span></li>`).join("")}</ol>
      </div>
      ${dialog.packingFlowError ? `<div class="ocw-packing-flow-error"><strong>来源读取失败</strong><span>${this.escape(dialog.packingFlowError)}</span></div>` : ""}
      ${state.step === 1 ? this.renderPackingSourceStep(dialog) : ""}
      ${state.step === 2 ? this.renderPackingPreviewStep(dialog) : ""}
      ${state.step === 3 ? this.renderPackingFreightStep(dialog) : ""}
    `);
  }

  renderPackingSourceStep(dialog) {
    const sources = dialog.packingFlowSources || {};
    const state = dialog.packingFlowState;
    const tab = dialog.packingSourceTab || "local";
    const tabs = [
      ["local", "本地上传"],
      ["approval", "钉钉审批附件/评论"],
      ["wiki", "知识库年度表"],
    ];
    let content = "";
    if (tab === "local") content = this.renderPackingLocalSources(sources.manual_attachments || [], state);
    if (tab === "approval") content = this.renderPackingApprovalSources(sources.approval_sources || [], state);
    if (tab === "wiki") content = this.renderPackingWikiSources(sources.wiki_workbooks || [], state, sources.wiki_error);
    return `
      <section class="ocw-packing-source-step">
        <div class="ocw-packing-source-tabs">${tabs.map(([key, label]) => `<button type="button" class="${tab === key ? "active" : ""}" data-action="packing-source-tab" data-source-tab="${key}">${label}</button>`).join("")}</div>
        <div class="ocw-packing-source-toolbar">
          <p>只会读取已授权、已归档的来源；选择后先预览，不会直接写入成本。</p>
          ${tab === "local" ? `<button class="ocw-outline-btn" type="button" data-action="packing-flow-upload">上传新装箱单</button>` : ""}
          ${tab === "wiki" ? `<button class="ocw-outline-btn" type="button" data-action="packing-refresh-list">刷新列表</button>` : ""}
        </div>
        <div class="ocw-packing-source-list">${content}</div>
        <footer class="ocw-packing-flow-footer">
          <span>${state.sourceId ? `已选：${this.escape(this.packingSourceLabel(dialog, state))}${state.sheetName ? ` / ${this.escape(state.sheetName)}` : ""}` : "请选择一个明确来源"}</span>
          <button class="ocw-primary-btn" type="button" data-action="packing-preview-source" ${state.sourceId && (state.sourceKind === "approval_comment" || state.sourceKind === "wiki_sheet" || state.sheetName) ? "" : "disabled"}>预览装箱数据</button>
        </footer>
      </section>
    `;
  }

  packingSourceLabel(dialog, state) {
    const row = this.findPackingFlowSource(dialog.packingFlowSources || {}, state.sourceKind, state.sourceId);
    return (row && row.source_label) || state.sourceId;
  }

  renderPackingLocalSources(items, state) {
    if (!items.length) return `<div class="ocw-detail-empty"><strong>尚未上传装箱单</strong><span>点击“上传新装箱单”，上传 .xlsx 或 .xlsm 文件。</span></div>`;
    return items.map((item) => this.renderPackingAttachmentSource(item, state, "本地文件")).join("");
  }

  renderPackingApprovalSources(items, state) {
    if (!items.length) return `<div class="ocw-detail-empty"><strong>暂无可用的钉钉装箱来源</strong><span>已拒绝、已撤销或已终止流程不会进入候选。</span></div>`;
    return items.map((item) => {
      if (item.source_kind === "approval_comment") {
        return this.renderPackingSourceChoice(item, state, "纯评论", item.remark_preview || "已识别数量、重量或尺寸信息");
      }
      return this.renderPackingAttachmentSource(item, state, item.origin === "Comment" ? "评论附件" : "表单附件");
    }).join("");
  }

  renderPackingAttachmentSource(item, state, typeLabel) {
    const sheets = Array.isArray(item.sheets) ? item.sheets : [];
    if (!item.available) {
      return `<article class="ocw-packing-source-card disabled"><div><span>${this.escape(typeLabel)}</span><strong>${this.escape(item.source_label || item.source_id)}</strong><small>文件尚未保存，暂不可解析</small></div></article>`;
    }
    return `<article class="ocw-packing-source-card"><div><span>${this.escape(typeLabel)}</span><strong>${this.escape(item.source_label || item.source_id)}</strong><small>${this.escape(this.formatDateTimeMinute(item.source_updated_at) || item.source_updated_at || "--")}</small></div><div class="ocw-packing-sheet-choices">${sheets.length ? sheets.map((sheet) => this.renderPackingSourceChoice(item, state, "Sheet", sheet, sheet)).join("") : `<span class="ocw-packing-source-disabled">未读取到可选 Sheet</span>`}</div></article>`;
  }

  renderPackingSourceChoice(item, state, typeLabel, description, sheetName = "") {
    const selected = state.sourceKind === item.source_kind && String(state.sourceId) === String(item.source_id) && String(state.sheetName || "") === String(sheetName || "");
    return `<button type="button" class="ocw-packing-source-choice ${selected ? "selected" : ""}" data-action="packing-select-source" data-source-kind="${this.escape(item.source_kind)}" data-source-id="${this.escape(item.source_id)}" data-sheet-name="${this.escape(sheetName)}"><span>${this.escape(typeLabel)}</span><strong>${this.escape(description || item.source_label || item.source_id)}</strong></button>`;
  }

  renderPackingWikiSources(workbooks, state, error = "") {
    if (error) return `<div class="ocw-detail-empty is-error"><strong>知识库缓存暂不可用</strong><span>${this.escape(error)}</span></div>`;
    if (!workbooks.length) return `<div class="ocw-detail-empty"><strong>尚未建立年度表缓存</strong><span>点击“刷新列表”由服务器应用身份更新，无需登录个人钉钉。</span></div>`;
    return workbooks.map((workbook) => `
      <article class="ocw-packing-workbook">
        <header><div><span>${this.escape(String(workbook.year || "年度表"))}</span><strong>${this.escape(workbook.label || workbook.workbook_id)}</strong></div><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="packing-refresh-list" data-workbook-id="${this.escape(workbook.workbook_id)}">刷新列表</button></header>
        <label class="ocw-packing-sheet-search"><span>查找 Sheet</span><input type="search" placeholder="输入装箱单、日期或品类" data-action="packing-filter-sheets"></label>
        <div class="ocw-packing-wiki-sheets">${(workbook.sheets || []).map((sheet) => `<div class="ocw-packing-wiki-sheet" data-sheet-search="${this.escape(String(sheet.source_label || "").toLowerCase())}">${this.renderPackingSourceChoice(sheet, state, "Sheet", sheet.source_label)}<button class="ocw-link-btn" type="button" data-action="packing-refresh-sheet" data-workbook-id="${this.escape(workbook.workbook_id)}" data-sheet-id="${this.escape(String(sheet.source_id || "").split(":").slice(1).join(":"))}">刷新资料</button><small>${this.escape(this.formatDateTimeMinute(sheet.source_updated_at) || sheet.source_updated_at || "待刷新")}</small></div>`).join("") || `<div class="ocw-packing-source-disabled">列表中暂无 Sheet</div>`}</div>
      </article>`).join("");
  }

  renderPackingPreviewStep(dialog) {
    const state = dialog.packingFlowState;
    const preview = state.preview || {};
    const totals = preview.totals || {};
    const blockers = (preview.validation || {}).blocking || [];
    return `
      <section class="ocw-packing-preview-step">
        <div class="ocw-packing-preview-main">
          <div class="ocw-packing-preview-title"><div><span>来源</span><strong>${this.escape(this.packingSourceLabel(dialog, state))}</strong></div><button class="ocw-outline-btn" type="button" data-action="packing-back-source">重新选择</button></div>
          <div class="ocw-packing-groups">${(preview.groups || []).map((group) => this.renderPackingGroup(preview, group, state)).join("")}</div>
        </div>
        <aside class="ocw-packing-preview-summary">
          <h3>整票汇总</h3>
          <dl><div><dt>物料行</dt><dd>${this.escape(String(preview.material_row_count || 0))}</dd></div><div><dt>包装组</dt><dd>${this.escape(String(preview.package_group_count || (preview.groups || []).length || 0))}</dd></div><div><dt>包装件数</dt><dd>${this.escape(String(preview.package_count || 0))}</dd></div><div><dt>整票毛重</dt><dd>${this.escape(this.packingMetricValue(totals.gross_weight_kg))} kg</dd></div><div><dt>整票体积</dt><dd>${this.escape(this.packingMetricValue(totals.volume_m3))} m³</dd></div><div><dt>整票净重</dt><dd>${this.escape(this.packingMetricValue(totals.net_weight_kg))} kg</dd></div></dl>
          ${blockers.length ? `<div class="ocw-packing-blockers"><strong>仍需确认</strong>${blockers.map((item) => `<span>${this.escape(item.message || item.code)}</span>`).join("")}</div>` : `<div class="ocw-packing-ready">汇总值已可用</div>`}
          <div class="ocw-packing-draft-note">保存草稿只保存当前浏览器中的分组选择，不会确认数据。</div>
        </aside>
        <footer class="ocw-packing-flow-footer full"><button class="ocw-outline-btn" type="button" data-action="packing-save-draft">保存草稿</button><button class="ocw-primary-btn" type="button" data-action="packing-confirm-snapshot" ${state.canCompare ? "" : "disabled"}>下一步：比较运费</button></footer>
      </section>
    `;
  }

  renderPackingGroup(preview, group, state) {
    const rows = (preview.material_rows || []).filter((row) => (group.row_numbers || []).includes(row.source_row));
    const decision = ((state.resolutions || {}).groups || {})[String(group.group_id || "")];
    const resolved = !group.needs_confirmation || Boolean(decision && decision.action);
    return `<article class="ocw-packing-group ${group.needs_confirmation && !resolved ? "needs-confirmation" : ""}">
      <header><div><strong>${this.escape(group.group_id || "包装组")}</strong><span>${this.escape((group.row_numbers || []).join("、"))} 行</span></div>${(group.row_numbers || []).length > 1 ? `<b>共享箱级数据</b>` : ""}</header>
      <div class="ocw-packing-group-metrics"><span>毛重 <strong>${this.escape(this.packingMetricValue(group.gross_weight_kg))} kg</strong></span><span>体积 <strong>${this.escape(this.packingMetricValue(group.volume_m3))} m³</strong></span><span>净重 <strong>${this.escape(this.packingMetricValue(group.net_weight_kg))} kg</strong></span><span>件数 <strong>${this.escape(this.packingMetricValue(group.package_count))}</strong></span></div>
      <div class="ocw-packing-group-rows">${rows.map((row) => `<div><span>${this.escape(String(row.source_row || ""))}</span><strong>${this.escape(row.material_code || "未填编码")}</strong><em>${this.escape(row.product_name || "--")}</em><small>${this.escape(row.quantity || "--")} ${this.escape(row.unit || "")}</small></div>`).join("")}</div>
      ${group.needs_confirmation ? `<div class="ocw-packing-group-decision"><span>${resolved ? `已选：${decision.action === "split" ? "拆分为独立包装组" : "关联到上一包装组"}` : this.escape(group.suggestion_reason || "请确认空白单元格是否为合并包装数据")}</span><div><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="packing-resolve-group" data-group-id="${this.escape(group.group_id)}" data-resolution="confirm_shared">关联到上一包装组</button><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="packing-resolve-group" data-group-id="${this.escape(group.group_id)}" data-resolution="split">拆分为独立包装组</button></div></div>` : ""}
    </article>`;
  }

  packingMetricValue(metric) {
    const value = metric && metric.value;
    return value === null || value === undefined || value === "" ? "--" : String(value);
  }

  renderPackingFreightStep(dialog) {
    const state = dialog.packingFlowState;
    const snapshot = state.snapshot || {};
    const quote = state.quote || {};
    const weight = quote.weight || {};
    const volume = quote.volume || {};
    return `<section class="ocw-packing-freight-step">
      <div class="ocw-packing-quote-panel">
        <div class="ocw-packing-independent-note"><strong>独立试算，不修改正式费用</strong><span>不会改变费用池、SKU 分摊、批次状态或 ERP 回写。</span></div>
        <div class="ocw-packing-confirmed-totals"><div><span>已确认毛重</span><strong>${this.escape(snapshot.total_gross_weight_kg || "--")} kg</strong></div><div><span>已确认体积</span><strong>${this.escape(snapshot.total_volume_m3 || "--")} m³</strong></div></div>
        <div class="ocw-packing-quote-common"><label>币种<select data-quote-field="currency">${["USD", "CNY", "MXN", "EUR"].map((currency) => `<option value="${currency}" ${(quote.currency || "USD") === currency ? "selected" : ""}>${currency}</option>`).join("")}</select></label><label class="check"><input type="checkbox" data-quote-field="scope_confirmed" ${quote.scope_confirmed ? "checked" : ""}><span>确认两套报价的服务范围、时效和附加条件一致</span></label></div>
        <div class="ocw-packing-basis-inputs">${this.renderPackingQuoteBasis("weight", "按重量报价", "kg", weight)}${this.renderPackingQuoteBasis("volume", "按体积报价", "m³", volume)}</div>
        <label class="ocw-packing-quote-remark">报价备注<textarea data-quote-field="quote_remark" maxlength="500" placeholder="承运商、航线、有效期和特别条件">${this.escape(quote.quote_remark || "")}</textarea></label>
        <div class="ocw-packing-quote-actions"><button class="ocw-outline-btn" type="button" data-action="packing-back-preview">上一步</button><button class="ocw-primary-btn" type="button" data-action="packing-calculate-freight">计算并比较</button></div>
      </div>
      <aside class="ocw-packing-result-panel">${state.calculation ? this.renderPackingFreightResult(state.calculation) : `<div class="ocw-detail-empty"><strong>等待输入两套报价</strong><span>系统将展开计费数量、最低收费、附加费和差额。</span></div>`}</aside>
    </section>`;
  }

  renderPackingQuoteBasis(prefix, title, unit, values = {}) {
    const value = (name) => this.escape(values[name] == null ? "" : String(values[name]));
    return `<fieldset><legend>${title}</legend><label>单价 / ${unit}<input type="number" min="0" step="any" data-quote-field="${prefix}_unit_price" value="${value("unit_price")}" required></label><label>附加费<input type="number" min="0" step="any" data-quote-field="${prefix}_surcharge" value="${value("surcharge")}"></label><details><summary>高级计费条件</summary><label>最低计费量<input type="number" min="0" step="any" data-quote-field="${prefix}_min_quantity" value="${value("min_quantity")}"></label><label>计费递增单位<input type="number" min="0" step="any" data-quote-field="${prefix}_rounding_increment" value="${value("rounding_increment")}"></label><label>最低基础运费<input type="number" min="0" step="any" data-quote-field="${prefix}_min_base_freight" value="${value("min_base_freight")}"></label></details></fieldset>`;
  }

  renderPackingFreightResult(result) {
    const display = result.display || {};
    const labels = { weight: "按重量", volume: "按体积", equal: "两者相同" };
    const recommendation = result.recommended_basis ? labels[result.recommended_basis] : "尚未确认同一报价范围";
    return `<div class="ocw-packing-result"><header><span>建议方式</span><strong>${this.escape(recommendation)}</strong></header><div class="ocw-packing-result-totals"><div><span>按重量总运费</span><strong>${this.escape(display.currency || "")} ${this.escape(display.weight_total || "--")}</strong></div><div><span>按体积总运费</span><strong>${this.escape(display.currency || "")} ${this.escape(display.volume_total || "--")}</strong></div></div><div class="ocw-packing-saving"><span>差额 ${this.escape(display.currency || "")} ${this.escape(display.difference_amount || "--")}</span><strong>最高可节省 ${this.escape(display.savings_percent || "--")}</strong></div>${this.renderPackingTrace("重量计算", result.weight)}${this.renderPackingTrace("体积计算", result.volume)}<button class="ocw-primary-btn" type="button" data-action="packing-save-comparison">保存比较结果</button><p>保存后仅形成可追溯试算历史，不会自动采用任一方案。</p></div>`;
  }

  renderPackingTrace(label, trace = {}) {
    return `<details class="ocw-packing-trace"><summary>${label}</summary><dl><div><dt>实际数量</dt><dd>${this.escape(trace.actual_quantity || "--")}</dd></div><div><dt>计费数量</dt><dd>${this.escape(trace.chargeable_quantity || "--")}</dd></div><div><dt>单价</dt><dd>${this.escape(trace.unit_price || "--")}</dd></div><div><dt>基础运费</dt><dd>${this.escape(trace.base_freight || "--")}</dd></div><div><dt>附加费</dt><dd>${this.escape(trace.surcharge || "0")}</dd></div><div><dt>合计</dt><dd>${this.escape(trace.total || "--")}</dd></div></dl></details>`;
  }

  bindPackingFlowEvents(dialog, batch) {
    const $wrapper = dialog.$wrapper;
    $wrapper.off("click.ocwPackingFlow change.ocwPackingFlow input.ocwPackingFlow")
      .on("click.ocwPackingFlow", "[data-action='packing-source-tab']", (event) => {
        dialog.packingSourceTab = $(event.currentTarget).attr("data-source-tab") || "local";
        this.renderPackingFlow(dialog, batch);
      })
      .on("click.ocwPackingFlow", "[data-action='packing-select-source']", (event) => {
        const $button = $(event.currentTarget);
        dialog.packingFlowState = OverseasCostWorkbenchState.selectPackingSource(
          dialog.packingFlowState,
          $button.attr("data-source-kind"),
          $button.attr("data-source-id"),
          $button.attr("data-sheet-name") || ""
        );
        this.renderPackingFlow(dialog, batch);
      })
      .on("click.ocwPackingFlow", "[data-action='packing-preview-source']", () => this.previewPackingFlowSource(dialog, batch).catch((error) => this.showPackingFlowError(dialog, batch, error)))
      .on("click.ocwPackingFlow", "[data-action='packing-back-source']", () => {
        dialog.packingFlowState = { ...dialog.packingFlowState, step: 1, preview: null, resolutions: { groups: {} }, canCompare: false };
        this.renderPackingFlow(dialog, batch);
      })
      .on("click.ocwPackingFlow", "[data-action='packing-resolve-group']", (event) => {
        const $button = $(event.currentTarget);
        dialog.packingFlowState = OverseasCostWorkbenchState.resolvePackageGroup(dialog.packingFlowState, $button.attr("data-group-id"), $button.attr("data-resolution"));
        this.renderPackingFlow(dialog, batch);
      })
      .on("click.ocwPackingFlow", "[data-action='packing-save-draft']", () => this.savePackingFlowDraft(dialog, batch))
      .on("click.ocwPackingFlow", "[data-action='packing-confirm-snapshot']", () => this.confirmPackingFlowSnapshot(dialog, batch).catch((error) => this.showPackingFlowError(dialog, batch, error)))
      .on("click.ocwPackingFlow", "[data-action='packing-back-preview']", () => {
        dialog.packingFlowState = { ...dialog.packingFlowState, step: 2, calculation: null };
        this.renderPackingFlow(dialog, batch);
      })
      .on("click.ocwPackingFlow", "[data-action='packing-calculate-freight']", () => this.calculatePackingFreight(dialog, batch).catch((error) => this.showPackingFlowError(dialog, batch, error)))
      .on("click.ocwPackingFlow", "[data-action='packing-save-comparison']", () => this.savePackingFreightComparison(dialog, batch).catch((error) => this.showPackingFlowError(dialog, batch, error)))
      .on("click.ocwPackingFlow", "[data-action='packing-flow-upload']", () => this.uploadPackingFlowFile(dialog, batch))
      .on("click.ocwPackingFlow", "[data-action='packing-refresh-list']", (event) => this.refreshPackingWorkbook(dialog, batch, $(event.currentTarget).attr("data-workbook-id")).catch((error) => this.showPackingFlowError(dialog, batch, error)))
      .on("click.ocwPackingFlow", "[data-action='packing-refresh-sheet']", (event) => {
        const $button = $(event.currentTarget);
        this.refreshPackingSheet(dialog, batch, $button.attr("data-workbook-id"), $button.attr("data-sheet-id")).catch((error) => this.showPackingFlowError(dialog, batch, error));
      })
      .on("input.ocwPackingFlow", "[data-action='packing-filter-sheets']", (event) => {
        const keyword = String($(event.currentTarget).val() || "").trim().toLowerCase();
        $(event.currentTarget).closest(".ocw-packing-workbook").find(".ocw-packing-wiki-sheet").each((_, element) => {
          $(element).toggle(!keyword || String($(element).attr("data-sheet-search") || "").includes(keyword));
        });
      });
  }

  async previewPackingFlowSource(dialog, batch) {
    const state = dialog.packingFlowState;
    const result = await this.call("overseas_costing.api.packing_api.preview_packing_source_v2", {
      batch_name: batch.name,
      source_kind: state.sourceKind,
      source_id: state.sourceId,
      sheet_name: state.sheetName || null,
    }, true);
    dialog.packingFlowError = "";
    dialog.packingFlowState = OverseasCostWorkbenchState.applyPackingPreview(state, result);
    this.renderPackingFlow(dialog, batch);
  }

  savePackingFlowDraft(dialog, batch) {
    const state = dialog.packingFlowState;
    const payload = {
      sourceKind: state.sourceKind,
      sourceId: state.sourceId,
      sheetName: state.sheetName,
      sourceRevision: state.preview && state.preview.source_revision,
      resolutions: state.resolutions,
    };
    window.localStorage.setItem(`ocw-packing-draft:${batch.name}`, JSON.stringify(payload));
    frappe.show_alert({ message: "装箱确认草稿已保存到当前浏览器", indicator: "green" });
  }

  async confirmPackingFlowSnapshot(dialog, batch) {
    const state = dialog.packingFlowState;
    const resolutions = { ...(state.resolutions || {}), sheet_name: state.sheetName || undefined };
    const result = await this.call("overseas_costing.api.packing_api.confirm_packing_snapshot", {
      batch_name: batch.name,
      source_revision: state.preview.source_revision,
      resolutions_json: JSON.stringify(resolutions),
    }, true);
    if (!result || !result.ok) throw new Error((result && result.message) || "装箱数据确认失败。");
    dialog.packingFlowState = { ...state, step: 3, snapshot: result.snapshot, calculation: null };
    this.renderPackingFlow(dialog, batch);
  }

  packingFlowQuoteFields(dialog) {
    const fields = {};
    dialog.$wrapper.find("[data-quote-field]").each((_, element) => {
      const $field = $(element);
      fields[$field.attr("data-quote-field")] = $field.is(":checkbox") ? $field.is(":checked") : $field.val();
    });
    return fields;
  }

  async calculatePackingFreight(dialog, batch) {
    const state = dialog.packingFlowState;
    const quote = OverseasCostWorkbenchState.buildFreightQuotePayload(state, this.packingFlowQuoteFields(dialog));
    const result = await this.call("overseas_costing.api.packing_api.preview_freight_comparison", {
      batch_name: batch.name,
      snapshot_revision: state.snapshot.idempotency_key,
      quote_json: JSON.stringify(quote),
    }, true);
    if (!result || !result.ok) throw new Error((result && result.message) || "运费试算失败。");
    dialog.packingFlowState = { ...state, quote, calculation: result.calculation };
    this.renderPackingFlow(dialog, batch);
  }

  async savePackingFreightComparison(dialog, batch) {
    const state = dialog.packingFlowState;
    if (!state.quote || !state.calculation) throw new Error("请先计算比较结果。");
    const result = await this.call("overseas_costing.api.packing_api.save_freight_comparison", {
      batch_name: batch.name,
      snapshot_revision: state.snapshot.idempotency_key,
      request_id: this.packingFlowRequestId(),
      quote_json: JSON.stringify(state.quote),
    }, true);
    if (!result || !result.ok) throw new Error((result && result.message) || "比较结果保存失败。");
    frappe.show_alert({ message: "运费比较结果已保存，正式费用未改变", indicator: "green" });
    if (this.detailState.tab === "documents") await this.refreshDetailSummary();
  }

  uploadPackingFlowFile(dialog, batch) {
    const logisticsType = this.detectManualDocumentLogisticsType(batch);
    const slot = this.manualDocumentPlans(logisticsType).find((item) => item.attachmentType === "Packing List");
    if (!slot) throw new Error("当前运输方式没有装箱单资料位。");
    this.openManualDocumentUploader(batch, dialog, logisticsType, slot, async () => {
      dialog.packingSourceTab = "local";
      await this.loadPackingFlowSources(dialog, batch);
    });
  }

  packingFlowRequestId() {
    const bytes = new Uint8Array(32);
    window.crypto.getRandomValues(bytes);
    return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  }

  async refreshPackingWorkbook(dialog, batch, workbookId = "") {
    const workbooks = (dialog.packingFlowSources || {}).wiki_workbooks || [];
    const id = workbookId || (workbooks.length === 1 ? workbooks[0].workbook_id : "");
    if (!id) throw new Error("请先选择需要刷新的年度表。");
    const requestId = this.packingFlowRequestId();
    await this.call("overseas_costing.api.packing_api.request_packing_workbook_refresh", {
      batch_name: batch.name, workbook_id: id, request_id: requestId,
    }, false);
    await this.waitPackingRefresh(batch, requestId);
    await this.loadPackingFlowSources(dialog, batch);
  }

  async refreshPackingSheet(dialog, batch, workbookId, sheetId) {
    const requestId = this.packingFlowRequestId();
    await this.call("overseas_costing.api.packing_api.request_packing_sheet_refresh", {
      batch_name: batch.name, workbook_id: workbookId, sheet_id: sheetId, request_id: requestId,
    }, false);
    await this.waitPackingRefresh(batch, requestId);
    await this.loadPackingFlowSources(dialog, batch);
  }

  async waitPackingRefresh(batch, requestId) {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const status = await this.call("overseas_costing.api.packing_api.get_packing_refresh_status", {
        batch_name: batch.name, request_id: requestId,
      }, false);
      if (status && status.status === "success") return status;
      if (status && status.status === "failed") throw new Error(status.error_message || "钉钉知识库刷新失败。");
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
    throw new Error("刷新仍在队列中，请稍后再点击刷新资料。");
  }

  showPackingFlowError(dialog, batch, error) {
    dialog.packingFlowError = this.normalizeErrorMessage(error);
    this.renderPackingFlow(dialog, batch);
  }
