  feeRuleForWorkItem(item = {}) {
    const key = String(item.fee_key || item.logical_fee_key || "");
    return (this.detailState.detail?.allocation_rules || this.getDetailBatch().allocation_rule_snapshot || []).find(
      (rule) => String(rule.logical_fee_key || rule.rule_code || "") === key
    ) || {};
  }

  feeAmountStatePresentation(state) {
    return {
      MISSING: { label: "金额待补", tone: "error" },
      ESTIMATED: { label: "暂估待实际", tone: "warning" },
      ACTUAL: { label: "已确认实际", tone: "ok" },
      NOT_INCURRED: { label: "已确认未发生", tone: "neutral" },
      INCLUDED: { label: "已包含", tone: "neutral" },
    }[String(state || "MISSING")] || { label: "待确认", tone: "warning" };
  }

  feeWorkItems(work = {}) {
    const rows = Array.isArray(work.items) ? work.items.slice() : [];
    return rows.sort((left, right) => {
      const leftTodos = (left.todos || []).length;
      const rightTodos = (right.todos || []).length;
      if (Boolean(leftTodos) !== Boolean(rightTodos)) return leftTodos ? -1 : 1;
      return String(left.expense_category || left.fee_key || "").localeCompare(String(right.expense_category || right.fee_key || ""), "zh-CN");
    });
  }

  renderFeeWorklist(work = {}, options = {}) {
    if (options.loading) {
      return `<section class="ocw-fee-worklist is-loading"><span class="ocw-spinner"></span><strong>正在读取费用待办</strong></section>`;
    }
    if (options.error) {
      return `<section class="ocw-fee-worklist"><div class="ocw-detail-empty is-error"><strong>费用待办加载失败</strong><span>${this.escape(options.error)}</span><button class="ocw-outline-btn" type="button" data-action="fee-retry">重试</button></div></section>`;
    }

    const summary = OverseasCostWorkbenchState.summarizeFeeWork(work);
    const allItems = this.feeWorkItems(work);
    const showAll = Boolean(this.detailState.showAllFees);
    const items = showAll ? allItems : allItems.filter((item) => (item.todos || []).length);
    const serverSummary = work.summary || {};
    const estimated = Object.entries(serverSummary.estimated_by_currency || {}).map(([currency, amount]) => `${currency} ${this.formatMoney(amount)}`).join("、") || "0";
    const unallocated = Object.entries(serverSummary.unallocated_by_currency || {}).map(([currency, amount]) => `${currency} ${this.formatMoney(amount)}`).join("、") || "0";
    return `
      <section class="ocw-fee-worklist" aria-label="费用与凭证待办">
        <div class="ocw-fee-summary">
          <div><span>费用待办</span><strong class="${summary.todoCount ? "is-danger" : "is-complete"}">${summary.affectedFeeCount} 笔费用 / ${summary.todoCount} 项待办</strong><small>${summary.todoCount ? "可先预览成本，首次 ERP 推送前必须补齐" : "当前费用已满足最终确认条件"}</small></div>
          <div><span>暂估金额</span><strong>${this.escape(estimated)}</strong><small>推送后仍持续提醒替换为实际费用</small></div>
          <div><span>待分摊金额</span><strong>${this.escape(unallocated)}</strong><small>未分摊费用不会悄悄消失</small></div>
          <div class="ocw-fee-summary-actions">
            <button class="ocw-outline-btn" type="button" data-action="fee-toggle-all">${showAll ? "只看待办" : "全部费用"}</button>
            <button class="ocw-outline-btn" type="button" data-action="fee-add">+ 新增费用</button>
            <button class="ocw-primary-btn" type="button" data-action="fee-confirm-complete" ${summary.isComplete && allItems.length ? "" : "title=\"需先处理所有费用待办\""}>确认本批费用已齐</button>
          </div>
        </div>
        <div class="ocw-fee-legend"><span><i class="is-error"></i>红色：金额或分摊缺失</span><span><i class="is-warning"></i>橙色：暂估、凭证或最终确认待处理</span><span><i class="is-ok"></i>绿色：已完成</span></div>
        <div class="ocw-fee-list">
          ${items.length ? items.map((item) => this.renderFeeWorkRow(item)).join("") : this.renderFeeWorkEmpty(allItems, summary)}
        </div>
      </section>
    `;
  }

  renderFeeWorkEmpty(allItems = [], summary = {}) {
    if (!allItems.length) {
      return `<div class="ocw-detail-empty is-error"><strong>尚未建立费用清单</strong><span>从 OA 资料带入费用，或先人工新增运费、税费、清关费等记录。</span><button class="ocw-primary-btn" type="button" data-action="fee-add">+ 新增第一笔费用</button></div>`;
    }
    return `<div class="ocw-detail-empty"><strong>${summary.isComplete ? "待办已清空" : "当前筛选无结果"}</strong><span>点击「全部费用」查看 ${allItems.length} 笔已建立费用。</span></div>`;
  }

  renderFeeWorkRow(item = {}) {
    const todos = Array.isArray(item.todos) ? item.todos : [];
    const presentations = todos.map((todo) => ({ ...todo, ...OverseasCostWorkbenchState.feeTodoPresentation(todo.code) }));
    const hasError = presentations.some((todo) => todo.tone === "error");
    const state = this.feeAmountStatePresentation(item.amount_state);
    const rule = this.feeRuleForWorkItem(item);
    const feeKey = item.fee_key || item.logical_fee_key || rule.logical_fee_key || rule.rule_code || "";
    const title = item.expense_category || rule.expense_category || feeKey || "未命名费用";
    const amount = item.amount === "" || item.amount === null || item.amount === undefined ? "—" : `${item.currency || rule.currency || "RMB"} ${this.formatMoney(item.amount)}`;
    const scopeKeys = (() => {
      try { return JSON.parse(rule.scope_value_json || "[]"); } catch (_error) { return []; }
    })();
    return `
      <article class="ocw-fee-row ${hasError ? "is-error" : todos.length ? "is-warning" : "is-ok"}" data-fee-key="${this.escape(feeKey)}" tabindex="-1">
        <div class="ocw-fee-main">
          <div class="ocw-fee-title"><span>${this.escape(feeKey || "FEE")}</span><h3>${this.escape(title)}</h3></div>
          <div class="ocw-fee-amount"><strong>${this.escape(amount)}</strong><span class="is-${state.tone}">${this.escape(state.label)}</span></div>
        </div>
        <div class="ocw-fee-todos">
          ${presentations.length ? presentations.map((todo) => `<button type="button" class="ocw-fee-todo is-${todo.tone}" data-action="fee-todo-action" data-fee-key="${this.escape(feeKey)}" data-fee-action="${this.escape(todo.action)}"><b>${this.escape(todo.icon)}</b><span>${this.escape(todo.label)}</span></button>`).join("") : `<span class="ocw-fee-done">✓ 金额、分摊和凭证已完成</span>`}
        </div>
        <div class="ocw-fee-row-actions">
          <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="fee-edit" data-fee-key="${this.escape(feeKey)}">编辑费用</button>
          <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="fee-link-evidence" data-fee-key="${this.escape(feeKey)}">关联凭证</button>
          <button class="ocw-link-btn" type="button" data-action="fee-focus" data-fee-key="${this.escape(feeKey)}">定位此费用</button>
        </div>
        <details class="ocw-fee-scope"><summary>费用归属与分摊细节</summary><span>分摊依据：${this.escape(rule.allocation_basis || rule.basis_field || "goods_value")}</span><span>适用范围：${this.escape(rule.scope_type || "ALL_ITEMS")}${scopeKeys.length ? ` · ${this.escape(scopeKeys.join("、"))}` : ""}</span><span>凭证要求：${this.escape(item.required_evidence_role || rule.required_evidence_role || "无")}</span></details>
      </article>
    `;
  }

  async loadFeeWorklist(options = {}) {
    const batch = this.getDetailBatch();
    if (!batch || !batch.name) return null;
    const requestId = ++this.detailState.feeRequestId;
    const $area = this.$root.find("[data-area='fee-worklist']");
    if (options.loading !== false && $area.length) $area.html(this.renderFeeWorklist({}, { loading: true }));
    try {
      const result = await this.call("overseas_costing.api.fees.get_fee_worklist", {
        batch_name: batch.name,
        version_name: this.detailState.versionName || batch.current_version || null,
      });
      if (requestId !== this.detailState.feeRequestId || this.detailState.batchName !== batch.name) return null;
      if (!result || !result.ok) throw new Error((result && result.message) || "费用待办加载失败。");
      this.detailState.feeWork = result;
      if ($area.length) {
        $area.html(this.renderFeeWorklist(result));
        this.focusFeeWorkItem(OverseasCostWorkbenchState.feeFocusFromIssue(this.viewState.issue), { updateUrl: false });
      }
      return result;
    } catch (error) {
      if (requestId !== this.detailState.feeRequestId) return null;
      if ($area.length) $area.html(this.renderFeeWorklist({}, { error: this.normalizeErrorMessage(error) }));
      throw error;
    }
  }

  feeEditorInitialValue(rule = {}, fieldname, fallback = "") {
    const value = rule[fieldname];
    return value === undefined || value === null ? fallback : value;
  }

  async loadFeeScopeOptions() {
    const cacheKey = `${this.detailState.batchName}:${this.detailState.versionName}`;
    if (this.detailState.feeScopeCache?.key === cacheKey) return this.detailState.feeScopeCache.items;
    const rows = [];
    let page = 1;
    let pageCount = 1;
    do {
      const result = await this.call("overseas_costing.api.materials.get_material_grid", {
        batch_name: this.detailState.batchName,
        version_name: this.detailState.versionName || null,
        page,
        page_length: 100,
      });
      if (!result || !result.ok) throw new Error((result && result.message) || "物料列表加载失败。");
      rows.push(...(result.items || []));
      pageCount = Number(result.page_count || 1);
      page += 1;
    } while (page <= pageCount);
    const items = rows.map((row) => ({
      label: `${row.material_code || row.stable_line_key || row.name} · ${row.product_name || "未命名物料"}`,
      value: String(row.stable_line_key || row.name || ""),
    })).filter((row) => row.value);
    this.detailState.feeScopeCache = { key: cacheKey, items };
    return items;
  }

  async openFeeEditor(feeKey = "") {
    const workItem = (this.detailState.feeWork?.items || []).find((item) => String(item.fee_key || item.logical_fee_key || "") === String(feeKey));
    const rule = this.feeRuleForWorkItem(workItem || { fee_key: feeKey });
    const statusLabels = { MISSING: "金额待补", ESTIMATED: "暂估金额", ACTUAL: "实际金额", NOT_INCURRED: "确认未发生", INCLUDED: "已包含于其他费用" };
    const statusValues = Object.fromEntries(Object.entries(statusLabels).map(([key, value]) => [value, key]));
    const basisLabels = { goods_value: "按货值", gross_weight: "按毛重", volume: "按体积", chargeable_weight: "按计费重量" };
    const basisValues = Object.fromEntries(Object.entries(basisLabels).map(([key, value]) => [value, key]));
    const scopeLabels = { ALL_ITEMS: "整批全部物料", ITEMS: "指定多条物料", DIRECT_ITEM: "直接归属单条物料" };
    const scopeValues = Object.fromEntries(Object.entries(scopeLabels).map(([key, value]) => [value, key]));
    let scopeKeys = [];
    try { scopeKeys = JSON.parse(rule.scope_value_json || "[]"); } catch (_error) { scopeKeys = []; }
    let scopeOptions = [];
    try {
      scopeOptions = await this.loadFeeScopeOptions();
    } catch (error) {
      this.showError(error);
    }
    const dialog = new frappe.ui.Dialog({
      title: feeKey ? `编辑费用 · ${feeKey}` : "新增费用",
      size: "large",
      fields: [
        { fieldtype: "Data", fieldname: "logical_fee_key", label: "费用标识", default: feeKey || rule.logical_fee_key || rule.rule_code || "", reqd: 1, read_only: Boolean(feeKey) },
        { fieldtype: "Data", fieldname: "expense_category", label: "费用名称", default: this.feeEditorInitialValue(rule, "expense_category"), reqd: 1 },
        { fieldtype: "Select", fieldname: "amount_status", label: "金额状态", options: Object.values(statusLabels).join("\n"), default: statusLabels[workItem?.amount_state || rule.amount_status || "MISSING"], reqd: 1 },
        { fieldtype: "Column Break" },
        { fieldtype: "Data", fieldname: "currency", label: "币种", default: workItem?.currency || rule.currency || "RMB", reqd: 1 },
        { fieldtype: "Currency", fieldname: "amount", label: "费用金额", default: workItem?.amount ?? rule.amount ?? "" },
        { fieldtype: "Select", fieldname: "allocation_basis", label: "分摊依据", options: Object.values(basisLabels).join("\n"), default: basisLabels[rule.allocation_basis || rule.basis_field || "goods_value"], reqd: 1 },
        { fieldtype: "Select", fieldname: "required_evidence_role", label: "最终凭证要求", options: "\n运费发票\n完税凭证\n报关单\n付款凭证\n实际费用发票\n其他最终凭证", default: this.feeEvidenceRoleLabel(rule.required_evidence_role || "") },
        { fieldtype: "Small Text", fieldname: "remark", label: "说明", default: this.feeEditorInitialValue(rule, "remark") },
        { fieldtype: "Section Break", label: "费用归属（通常无需修改）", collapsible: 1, collapsed: 1 },
        { fieldtype: "Select", fieldname: "scope_type", label: "适用范围", options: Object.values(scopeLabels).join("\n"), default: scopeLabels[rule.scope_type || "ALL_ITEMS"], reqd: 1 },
        { fieldtype: "MultiCheck", fieldname: "scope_item_keys", label: "选择相关物料", options: scopeOptions.map((option) => ({ ...option, checked: scopeKeys.includes(option.value) })), columns: 2, depends_on: "eval:doc.scope_type!='整批全部物料'" },
        { fieldtype: "Data", fieldname: "included_in_fee_key", label: "已包含于", default: this.feeEditorInitialValue(rule, "included_in_fee_key") },
      ],
      primary_action_label: "保存费用",
      primary_action: async (values) => {
        try {
          if (!(await this.ensureEditSession())) return;
          const payload = {
            logical_fee_key: values.logical_fee_key,
            rule_code: rule.rule_code || values.logical_fee_key,
            expense_category: values.expense_category,
            amount_status: statusValues[values.amount_status] || "MISSING",
            amount: values.amount,
            currency: values.currency,
            allocation_basis: basisValues[values.allocation_basis] || "goods_value",
            scope_type: scopeValues[values.scope_type] || "ALL_ITEMS",
            scope_item_keys: Array.isArray(values.scope_item_keys) ? values.scope_item_keys : String(values.scope_item_keys || "").split(/[,\n]/).map((value) => value.trim()).filter(Boolean),
            required_evidence_role: this.feeEvidenceRoleValue(values.required_evidence_role),
            included_in_fee_key: values.included_in_fee_key,
            remark: values.remark,
            is_active: 1,
            is_enabled: 1,
          };
          const result = await this.call("overseas_costing.api.fees.save_fee", {
            batch_name: this.detailState.batchName,
            version_name: this.detailState.versionName,
            fee_json: JSON.stringify(payload),
            edit_token: this.detailState.editToken,
            expected_modified: this.detailState.expectedModified || this.getDetailBatch().modified || "",
          }, true);
          if (!result || !result.ok) throw new Error((result && result.message) || "费用保存失败。");
          dialog.hide();
          await this.refreshDetailSummary();
          frappe.show_alert({ message: result.message || "费用已保存，请重新计算。", indicator: result.cost_inputs_changed ? "orange" : "green" });
        } catch (error) {
          this.showError(error);
        }
      },
    });
    dialog.show();
  }

  feeEvidenceRoleLabel(value) {
    return { freight_invoice: "运费发票", tax_certificate: "完税凭证", customs_declaration: "报关单", payment_voucher: "付款凭证", expense_invoice: "实际费用发票", other_final: "其他最终凭证" }[String(value || "")] || "";
  }

  feeEvidenceRoleValue(label) {
    return { "运费发票": "freight_invoice", "完税凭证": "tax_certificate", "报关单": "customs_declaration", "付款凭证": "payment_voucher", "实际费用发票": "expense_invoice", "其他最终凭证": "other_final" }[String(label || "")] || "";
  }

  openFeeEvidenceDialog(feeKey) {
    const item = (this.detailState.feeWork?.items || []).find((row) => String(row.fee_key || row.logical_fee_key || "") === String(feeKey)) || {};
    const rule = this.feeRuleForWorkItem(item);
    if (!rule.name) {
      frappe.msgprint("请先保存这笔费用，再关联凭证。");
      return;
    }
    const preferredRole = item.required_evidence_role || rule.required_evidence_role || "other_final";
    const dialog = new frappe.ui.Dialog({
      title: `关联最终凭证 · ${feeKey}`,
      fields: [
        { fieldtype: "Link", fieldname: "attachment", label: "已上传附件", options: "Overseas Cost Attachment", reqd: 1, get_query: () => ({ filters: { batch: this.detailState.batchName } }) },
        { fieldtype: "Select", fieldname: "evidence_role", label: "凭证类型", options: "运费发票\n完税凭证\n报关单\n付款凭证\n实际费用发票\n其他最终凭证", default: this.feeEvidenceRoleLabel(preferredRole), reqd: 1 },
        { fieldtype: "HTML", fieldname: "tip", options: `<div class="ocw-fee-evidence-tip"><span>可从本批已有附件中选择，也可以直接上传新凭证。</span><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="fee-upload-evidence">上传新凭证</button></div>` },
      ],
      primary_action_label: "关联凭证",
      primary_action: async (values) => {
        try {
          if (!(await this.ensureEditSession())) return;
          const result = await this.call("overseas_costing.api.fees.link_fee_evidence", {
            batch_name: this.detailState.batchName,
            fee_rule: rule.name,
            attachment: values.attachment,
            evidence_role: this.feeEvidenceRoleValue(values.evidence_role),
            edit_token: this.detailState.editToken,
            expected_modified: this.detailState.expectedModified || this.getDetailBatch().modified || "",
          }, true);
          if (!result || !result.ok) throw new Error((result && result.message) || "凭证关联失败。");
          dialog.hide();
          await this.loadFeeWorklist({ loading: false });
          frappe.show_alert({ message: result.message || "凭证已关联。", indicator: "green" });
        } catch (error) {
          this.showError(error);
        }
      },
    });
    dialog.show();
    dialog.$wrapper.on("click.ocwFeeEvidence", "[data-action='fee-upload-evidence']", () => {
      this.uploadFeeEvidence(dialog, feeKey).catch((error) => this.showError(error));
    });
  }

  async uploadFeeEvidence(dialog, feeKey) {
    if (!frappe.ui.FileUploader) throw new Error("当前页面暂时无法打开文件上传器。");
    const batch = this.getDetailBatch();
    new frappe.ui.FileUploader({
      allow_multiple: false,
      is_private: 1,
      restrictions: { allowed_file_types: [".pdf", ".png", ".jpg", ".jpeg", ".xlsx", ".xls"] },
      on_success: async (fileDoc) => {
        try {
          const file = Array.isArray(fileDoc) ? fileDoc[0] : fileDoc;
          const fileUrl = file.file_url || file.file_url_private || "";
          if (!fileUrl) throw new Error("文件上传成功但没有返回文件地址，请重试。");
          const result = await this.call("overseas_costing.api.import_api.register_manual_document_attachment", {
            batch_name: batch.name,
            version_name: this.detailState.versionName || batch.current_version || null,
            logistics_type: this.detectManualDocumentLogisticsType(batch) || "GENERAL",
            slot_code: `fee_evidence_${String(feeKey || "other").toLowerCase()}`,
            slot_label: `费用凭证·${feeKey || "其他"}`,
            attachment_type: "Other",
            file_url: fileUrl,
            file_name: file.file_name || file.name || "",
            required: 0,
          }, true);
          if (!result || !result.ok || !result.attachment?.name) throw new Error((result && result.message) || "凭证登记失败。");
          dialog.set_value("attachment", result.attachment.name);
          frappe.show_alert({ message: "凭证已上传，请点击「关联凭证」完成关联。", indicator: "green" });
        } catch (error) {
          this.showError(error);
        }
      },
    });
    [0, 100, 300, 800].forEach((delay) => window.setTimeout(() => this.localizeFrappeFileUploader("费用最终凭证"), delay));
  }

  async handleFeeTodoAction(feeKey, action) {
    if (["enter_amount", "enter_actual", "fix_allocation", "review"].includes(action)) return this.openFeeEditor(feeKey);
    if (action === "link_evidence") return this.openFeeEvidenceDialog(feeKey);
    if (["validate_evidence", "review_completion"].includes(action)) return this.switchDetailTab("vouchers");
    if (action === "recalculate") return this.recalculate(this.detailState.batchName);
  }

  async confirmFeeWorkComplete() {
    const work = this.detailState.feeWork || await this.loadFeeWorklist();
    if (!work) return;
    const summary = OverseasCostWorkbenchState.summarizeFeeWork(work);
    if (!summary.isComplete || !(work.items || []).length) {
      const blockers = (work.items || []).flatMap((item) => (item.todos || []).map((todo) => `${item.expense_category || item.fee_key}：${OverseasCostWorkbenchState.feeTodoPresentation(todo.code).label}`));
      frappe.msgprint({ title: "费用还未补齐", message: blockers.length ? `<ul>${blockers.map((label) => `<li>${this.escape(label)}</li>`).join("")}</ul>` : "请先新建本批费用清单。", indicator: "orange" });
      return;
    }
    if (!(await this.ensureEditSession())) return;
    const result = await this.call("overseas_costing.api.fees.confirm_all_fees_complete", {
      batch_name: this.detailState.batchName,
      version_name: this.detailState.versionName,
      expected_input_hash: work.input_hash,
      edit_token: this.detailState.editToken,
      expected_modified: this.detailState.expectedModified || this.getDetailBatch().modified || "",
    }, true);
    if (!result || !result.ok) {
      await this.loadFeeWorklist({ loading: false });
      throw new Error((result && result.message) || "费用完整确认失败。");
    }
    await this.loadFeeWorklist({ loading: false });
    frappe.show_alert({ message: result.message || "已确认本批费用完整。", indicator: "green" });
  }

  focusFeeWorkItem(feeKey, options = {}) {
    const normalized = String(feeKey || "");
    if (!normalized) return false;
    const $row = this.$root.find("[data-fee-key]").filter((_, node) => $(node).attr("data-fee-key") === normalized).first();
    if (!$row.length) return false;
    if (options.updateUrl !== false) {
      this.viewState.issue = `fee:${normalized}`;
      this.replaceViewState({ issue: this.viewState.issue });
    }
    $row.addClass("is-focused");
    $row.get(0)?.scrollIntoView({ behavior: "smooth", block: "center" });
    $row.trigger("focus");
    window.setTimeout(() => $row.removeClass("is-focused"), 1800);
    return true;
  }

  async refreshFeeWorkAfterVoucherChange(batchName = "") {
    if (!this.detailState || String(this.detailState.batchName || "") !== String(batchName || this.detailState.batchName || "")) return;
    try {
      await this.loadFeeWorklist({ loading: false });
    } catch (error) {
      this.showError(error);
    }
  }
