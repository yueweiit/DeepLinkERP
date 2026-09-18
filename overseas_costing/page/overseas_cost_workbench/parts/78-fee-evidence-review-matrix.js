  feeEvidenceMatrixColumns() {
    return [
      { key: "IGI", label: "IGI", feeLogicalKey: "import_tax" },
      { key: "IVA", label: "IVA", feeLogicalKey: "import_tax" },
      { key: "DTA", label: "DTA", feeLogicalKey: "import_tax" },
      { key: "PRV", label: "PRV", feeLogicalKey: "import_tax" },
      { key: "PRV_IVA", label: "PRV IVA", feeLogicalKey: "import_tax" },
      { key: "CUSTOMS_SERVICE", label: "清关服务费", feeLogicalKey: "customs_clearance_fee" },
    ];
  }

  feeEvidenceMatrixColumnKey(component = {}) {
    const type = String(component.component_type || "").toUpperCase();
    const taxCode = String(component.tax_code || "").toUpperCase();
    const feeKey = String(component.fee_logical_key || component.logical_fee_key || "");
    if (type === "CUSTOMS_SERVICE" || taxCode === "CUSTOMS_SERVICE" || feeKey === "customs_clearance_fee") return "CUSTOMS_SERVICE";
    return this.feeEvidenceMatrixColumns().some((column) => column.key === taxCode && column.feeLogicalKey === "import_tax") ? taxCode : "";
  }

  feeEvidenceMaterialMatrix(draft = {}) {
    const matrix = draft.material_matrix;
    if (matrix && Array.isArray(matrix.rows)) return matrix;
    const rows = (draft.item_options || []).map((item) => ({
      item: String(item.item || item.name || ""),
      stable_line_key: String(item.stable_line_key || item.item || item.name || ""),
      material_code: String(item.material_code || ""),
      product_name: String(item.product_name || ""),
      hs_code: String(item.hs_code || ""),
      hs_suggestions: [],
      cells: {},
    }));
    const byItem = new Map(rows.map((row) => [row.item, row]));
    (draft.components || []).forEach((component, index) => {
      if (this.feeEvidenceIsLedgerComponent(component || {})) return;
      const row = byItem.get(String(component?.item || ""));
      const columnKey = this.feeEvidenceMatrixColumnKey(component || {});
      if (!row || !columnKey) return;
      row.cells[columnKey] = row.cells[columnKey] || { proposals: [], saved: [] };
      row.cells[columnKey].proposals.push(index);
    });
    return {
      columns: this.feeEvidenceMatrixColumns().map((column) => ({
        key: column.key,
        label: column.label,
        fee_logical_key: column.feeLogicalKey,
      })),
      rows,
      saved_components: [],
      unmatched_lines: draft.unmatched_lines || [],
      missing_fx: Boolean(draft.missing_fx),
    };
  }

  feeEvidenceIsLedgerComponent(component = {}) {
    return String(component.component_type || "").toUpperCase() === "REFUND_REVERSAL" ||
      String(component.accounting_role || "").toUpperCase() === "SETTLEMENT" ||
      String(component.cost_effect || "").toUpperCase() === "LEDGER_ONLY";
  }

  feeEvidenceLedgerComponentLabel(component = {}) {
    if (String(component.component_type || "").toUpperCase() === "REFUND_REVERSAL") return "退款／冲回";
    if (String(component.accounting_role || "").toUpperCase() === "SETTLEMENT") return "结算台账";
    return "仅记台账";
  }

  feeEvidenceComponentSourceRefs(component = {}) {
    const refs = [];
    const seen = new Set();
    const append = (ref) => {
      if (!ref || typeof ref !== "object" || Array.isArray(ref)) return;
      const key = JSON.stringify(ref);
      if (seen.has(key)) return;
      seen.add(key);
      refs.push(ref);
    };
    (component.source_refs || []).forEach(append);
    append(component.source_evidence);
    return refs;
  }

  feeEvidenceLedgerComponents(draft = {}) {
    const result = [];
    const seen = new Set();
    const append = (component) => {
      if (!component || !this.feeEvidenceIsLedgerComponent(component)) return;
      const proposalId = String(component.proposal_id || "");
      if (!proposalId || seen.has(proposalId)) return;
      seen.add(proposalId);
      result.push(component);
    };
    if (String(draft.component_contract?.mode || "") === "INDEXED_COLUMNS_V1") {
      const matrix = this.feeEvidenceMaterialMatrix(draft);
      (matrix.unmatched_lines || []).forEach((line) => {
        if (String(line?.reason_code || "") !== "MATERIAL_MATRIX_LEDGER_ONLY") return;
        append(this.feeEvidenceComponentAt(draft, line.proposal_index));
      });
    } else {
      (draft.components || []).forEach(append);
    }
    return result;
  }

  defaultFeeEvidenceReviewSelections(draft = {}) {
    const matrix = this.feeEvidenceMaterialMatrix(draft);
    const columnFeeKeys = new Map(this.feeEvidenceMatrixColumns().map((column) => [column.key, column.feeLogicalKey]));
    const matrixFeeKeys = new Set();
    (matrix.rows || []).forEach((row) => Object.entries(row.cells || {}).forEach(([columnKey, cell]) => {
      if ((cell?.proposals || []).length || (cell?.saved || []).length) matrixFeeKeys.add(columnFeeKeys.get(columnKey));
    }));
    const ledgerComponents = this.feeEvidenceLedgerComponents(draft);
    const hasDefaultLedgerComponent = ledgerComponents.some((row) => row.default_selected && String(row.proposal_id || ""));
    const selected = new Set();
    const evidence = draft.evidence || {};
    if (evidence.default_selected || matrixFeeKeys.size || hasDefaultLedgerComponent) {
      selected.add(String(evidence.proposal_id || "evidence:classification"));
    }
    (draft.fee_splits || []).forEach((row) => {
      if (row.default_selected || matrixFeeKeys.has(String(row.logical_fee_key || ""))) {
        const proposalId = String(row.proposal_id || "");
        if (proposalId) selected.add(proposalId);
      }
    });
    ledgerComponents.forEach((row) => {
      const proposalId = String(row.proposal_id || "");
      if (row.default_selected && proposalId) selected.add(proposalId);
    });
    return selected;
  }

  feeEvidenceIndexedValue(store = {}, fieldname, rowIndex) {
    const column = store?.columns?.[fieldname];
    if (!column || typeof column !== "object") return undefined;
    let valueIndex = rowIndex;
    if (Array.isArray(column.rows)) {
      let low = 0;
      let high = column.rows.length - 1;
      let found = -1;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        const candidate = Number(column.rows[middle]);
        if (candidate === rowIndex) { found = middle; break; }
        if (candidate < rowIndex) low = middle + 1;
        else high = middle - 1;
      }
      if (found < 0) return undefined;
      valueIndex = found;
    }
    if (Object.prototype.hasOwnProperty.call(column, "constant")) return column.constant;
    if (Array.isArray(column.values)) return column.values[valueIndex];
    if (Array.isArray(column.dictionary) && Array.isArray(column.indices)) {
      return column.dictionary[column.indices[valueIndex]];
    }
    return undefined;
  }

  feeEvidenceComponentAt(draft = {}, rowIndex) {
    if (!Number.isInteger(rowIndex) || rowIndex < 0) return null;
    const store = draft.component_store || {};
    if (String(draft.component_contract?.mode || "") !== "INDEXED_COLUMNS_V1" || store.format !== "INDEXED_COLUMNS_V1") {
      const component = (draft.components || [])[rowIndex];
      return component && typeof component === "object" ? component : null;
    }
    if (rowIndex >= Number(store.count || 0)) return null;
    const component = {};
    Object.keys(store.columns || {}).forEach((fieldname) => {
      const value = this.feeEvidenceIndexedValue(store, fieldname, rowIndex);
      if (value !== undefined) component[fieldname] = value;
    });
    return Object.keys(component).length ? component : null;
  }

  feeEvidencePlainNumber(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "";
    return Number(number.toFixed(6)).toString();
  }

  feeEvidenceAggregateComponents(components = []) {
    const originalByCurrency = {};
    let amountRmb = 0;
    let hasRmb = false;
    let missingFx = false;
    const sourceProposalIds = new Set();
    const warnings = [];
    components.forEach((component) => {
      const original = Number(component?.original_amount);
      const currency = String(component?.currency || "").toUpperCase() || "UNKNOWN";
      const rawRmb = component?.amount_rmb;
      if (Number.isFinite(original)) {
        originalByCurrency[currency] = (originalByCurrency[currency] || 0) + original;
        if (rawRmb === null || rawRmb === undefined || rawRmb === "") missingFx = true;
      }
      const rmb = Number(rawRmb);
      if (rawRmb !== null && rawRmb !== undefined && rawRmb !== "" && Number.isFinite(rmb)) {
        amountRmb += rmb;
        hasRmb = true;
      }
      const proposalId = String(component?.proposal_id || "");
      if (proposalId) sourceProposalIds.add(proposalId);
      if (component?.warning) warnings.push(String(component.warning));
      if (component?.needs_review) warnings.push("建议需人工复核。");
      if (component?.has_conflict) warnings.push("建议存在冲突。");
    });
    const currencies = Object.keys(originalByCurrency);
    return {
      originalAmount: currencies.length === 1 ? this.feeEvidencePlainNumber(originalByCurrency[currencies[0]]) : "",
      currency: currencies.length === 1 ? currencies[0] : (currencies.length ? "MIXED" : ""),
      amountRmb: missingFx ? null : (hasRmb ? this.feeEvidencePlainNumber(amountRmb) : ""),
      missingFx,
      sourceProposalIds: [...sourceProposalIds],
      warning: [...new Set(warnings)].join(" "),
    };
  }

  resolveFeeEvidenceMatrixCell(draft = {}, rowIndex, columnKey) {
    const matrix = this.feeEvidenceMaterialMatrix(draft);
    const row = matrix.rows?.[rowIndex] || {};
    const compact = row.cells?.[columnKey] || { proposals: [], saved: [] };
    const proposals = (compact.proposals || []).map((index) => this.feeEvidenceComponentAt(draft, index)).filter(Boolean);
    const savedRows = matrix.saved_components || [];
    const saved = (compact.saved || []).map((index) => savedRows[index]).filter((value) => value && typeof value === "object");
    const suggestion = this.feeEvidenceAggregateComponents(proposals);
    const current = this.feeEvidenceAggregateComponents(saved.length ? saved : proposals);
    const proposalIndexes = new Set((compact.proposals || []).filter(Number.isInteger));
    const savedIndexes = new Set((compact.saved || []).filter(Number.isInteger));
    const suggestionDetails = (row.hs_suggestion_details || []).filter((detail) => detail && typeof detail === "object");
    const hsSuggestions = suggestionDetails.length ? suggestionDetails.filter((detail) =>
      (detail.proposals || []).some((index) => proposalIndexes.has(index)) ||
      (detail.saved || []).some((index) => savedIndexes.has(index))
    ).map((detail) => detail.hs_code).filter(Boolean) :
      (proposalIndexes.size || savedIndexes.size ? (row.hs_suggestions || []).filter(Boolean) : []);
    const warnings = [current.warning, suggestion.warning];
    if (hsSuggestions.length) warnings.push(`HS 差异：凭证建议 ${hsSuggestions.join("、")}，当前物料为 ${row.hs_code || "未填写"}。`);
    if (current.missingFx || suggestion.missingFx) warnings.push("缺汇率");
    if (saved.length && proposals.length) warnings.push("已保存值优先，AI／规则建议仅供对照。");
    return {
      originalAmount: current.originalAmount,
      currency: current.currency,
      amountRmb: current.amountRmb,
      missingFx: current.missingFx,
      origin: saved.length ? "SAVED" : (proposals.length ? "AI" : "EMPTY"),
      suggestedOriginalAmount: suggestion.originalAmount,
      suggestedCurrency: suggestion.currency,
      suggestedAmountRmb: suggestion.amountRmb,
      sourceProposalIds: suggestion.sourceProposalIds,
      warning: [...new Set(warnings.filter(Boolean))].join(" "),
    };
  }

  feeEvidenceMatrixEditKey(item, columnKey) {
    return `${String(item || "")}\u001f${String(columnKey || "")}`;
  }

  ensureFeeEvidenceMatrixState(review = {}, draft = {}) {
    review.matrixEdits = review.matrixEdits || {};
    if (review.matrixDetailsOpen === undefined) review.matrixDetailsOpen = false;
    return review.matrixEdits;
  }

  feeEvidenceMatrixRowIndex(draft = {}, item) {
    return this.feeEvidenceMaterialMatrix(draft).rows.findIndex((row) => String(row.item || "") === String(item || ""));
  }

  setFeeEvidenceMatrixValue(review, draft, item, columnKey, rawValue) {
    this.ensureFeeEvidenceMatrixState(review, draft);
    const rowIndex = this.feeEvidenceMatrixRowIndex(draft, item);
    if (rowIndex < 0 || !this.feeEvidenceMatrixColumns().some((column) => column.key === columnKey)) throw new Error("物料或税费列已变更，请刷新草稿。");
    const base = this.resolveFeeEvidenceMatrixCell(draft, rowIndex, columnKey);
    const value = String(rawValue ?? "").trim();
    review.matrixEdits[this.feeEvidenceMatrixEditKey(item, columnKey)] = {
      value,
      dirty: true,
      cleared: value === "",
      sourceProposalIds: [...base.sourceProposalIds],
    };
  }

  adoptFeeEvidenceMatrixSuggestion(review, draft, item, columnKey) {
    this.ensureFeeEvidenceMatrixState(review, draft);
    const rowIndex = this.feeEvidenceMatrixRowIndex(draft, item);
    const base = this.resolveFeeEvidenceMatrixCell(draft, rowIndex, columnKey);
    review.matrixEdits[this.feeEvidenceMatrixEditKey(item, columnKey)] = {
      value: String(base.suggestedOriginalAmount || ""),
      dirty: true,
      cleared: !base.suggestedOriginalAmount,
      adoptedAI: true,
      sourceProposalIds: [...base.sourceProposalIds],
    };
  }

  feeEvidenceMatrixEffectiveCell(draft, review, rowIndex, columnKey) {
    const matrix = this.feeEvidenceMaterialMatrix(draft);
    const row = matrix.rows[rowIndex] || {};
    const base = this.resolveFeeEvidenceMatrixCell(draft, rowIndex, columnKey);
    const edit = review?.matrixEdits?.[this.feeEvidenceMatrixEditKey(row.item, columnKey)];
    const value = edit ? String(edit.value ?? "") : String(base.originalAmount || "");
    const column = this.feeEvidenceMatrixColumns().find((candidate) => candidate.key === columnKey);
    const feeCurrency = this.feeEvidenceFeeTotals(draft, review)[column?.feeLogicalKey]?.currency || "";
    const currency = base.currency || feeCurrency || String(draft.evidence?.currency || "").toUpperCase();
    let amountRmb = base.amountRmb;
    let missingFx = base.missingFx;
    const baseAmount = Number(base.originalAmount);
    const editedAmount = Number(value);
    if (edit?.adoptedAI && value) {
      amountRmb = base.suggestedAmountRmb;
      missingFx = base.suggestedAmountRmb === null;
    } else if (edit && value && Number.isFinite(baseAmount) && baseAmount > 0 && base.amountRmb !== null && base.amountRmb !== "") {
      amountRmb = this.feeEvidencePlainNumber(editedAmount * Number(base.amountRmb) / baseAmount);
      missingFx = false;
    } else if (edit && value && (!Number.isFinite(baseAmount) || baseAmount <= 0)) {
      amountRmb = currency === "RMB" ? this.feeEvidencePlainNumber(editedAmount) : null;
      missingFx = currency !== "RMB";
    } else if (!value) {
      amountRmb = "";
      missingFx = false;
    }
    return {
      ...base,
      value,
      currency,
      amountRmb,
      missingFx,
      dirty: Boolean(edit?.dirty),
      cleared: Boolean(edit?.cleared),
      adoptedAI: Boolean(edit?.adoptedAI),
      sourceProposalIds: edit ? [...(edit.sourceProposalIds || [])] : [...base.sourceProposalIds],
    };
  }

  normalizeFeeEvidenceMatrixAmount(rawValue) {
    const value = String(rawValue ?? "").trim();
    if (!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(value) || !Number.isFinite(Number(value)) || Number(value) < 0) {
      throw new Error("物料税费金额必须是非负有限数。");
    }
    const [integerRaw, decimalRaw = ""] = (value.startsWith(".") ? `0${value}` : value).split(".");
    const integer = integerRaw.replace(/^0+(?=\d)/, "") || "0";
    const decimal = decimalRaw.replace(/0+$/, "");
    if (decimal.length > 2) throw new Error("物料税费金额最多保留两位小数。");
    return decimal ? `${integer}.${decimal}` : integer;
  }

  serializeFeeEvidenceMatrix(draft = {}, review = {}) {
    const matrix = this.feeEvidenceMaterialMatrix(draft);
    const cells = [];
    matrix.rows.forEach((row, rowIndex) => {
      this.feeEvidenceMatrixColumns().forEach((column) => {
        const effective = this.feeEvidenceMatrixEffectiveCell(draft, review, rowIndex, column.key);
        if (!String(effective.value || "").trim()) return;
        cells.push({
          item: String(row.item || ""),
          column_key: column.key,
          original_amount: this.normalizeFeeEvidenceMatrixAmount(effective.value),
          source_proposal_ids: [...new Set((effective.sourceProposalIds || []).map(String).filter(Boolean))],
        });
      });
    });
    return { cells };
  }

  feeEvidenceFeeTotals(draft = {}, review = {}) {
    const result = { import_tax: { feeTotal: 0, currency: "" }, customs_clearance_fee: { feeTotal: 0, currency: "" } };
    (draft.fee_splits || []).forEach((split) => {
      const key = String(split.logical_fee_key || "");
      if (!result[key]) return;
      const edit = review.edits?.[String(split.proposal_id || "")] || {};
      const amount = Number(edit.amount ?? split.amount);
      if (Number.isFinite(amount)) result[key].feeTotal += amount;
      const currency = String(edit.currency ?? split.currency ?? "").toUpperCase();
      if (currency) result[key].currency = result[key].currency && result[key].currency !== currency ? "MIXED" : currency;
    });
    return result;
  }

  feeEvidenceMatrixTotals(draft = {}, review = {}) {
    const feeTotals = this.feeEvidenceFeeTotals(draft, review);
    const totals = {
      import_tax: { ...feeTotals.import_tax, allocatedOriginal: 0, allocatedRmb: 0, missingFx: false },
      customs_clearance_fee: { ...feeTotals.customs_clearance_fee, allocatedOriginal: 0, allocatedRmb: 0, missingFx: false },
    };
    const matrix = this.feeEvidenceMaterialMatrix(draft);
    matrix.rows.forEach((_row, rowIndex) => {
      this.feeEvidenceMatrixColumns().forEach((column) => {
        const cell = this.feeEvidenceMatrixEffectiveCell(draft, review, rowIndex, column.key);
        if (!String(cell.value || "").trim()) return;
        const amount = Number(cell.value);
        if (Number.isFinite(amount)) totals[column.feeLogicalKey].allocatedOriginal += amount;
        if (cell.missingFx || cell.amountRmb === null) totals[column.feeLogicalKey].missingFx = true;
        else if (Number.isFinite(Number(cell.amountRmb))) totals[column.feeLogicalKey].allocatedRmb += Number(cell.amountRmb);
      });
    });
    Object.values(totals).forEach((group) => {
      group.remaining = group.feeTotal - group.allocatedOriginal;
      group.overage = group.remaining < -0.000001;
    });
    return totals;
  }

  validateFeeEvidenceMatrix(draft = {}, review = {}) {
    const payload = this.serializeFeeEvidenceMatrix(draft, review);
    const totals = this.feeEvidenceMatrixTotals(draft, review);
    const overage = Object.values(totals).find((group) => group.overage);
    if (overage) throw new Error("已分摊金额超过费用总额，请调整后再确认。");
    return payload;
  }

  feeEvidenceSourceLabel(ref = {}) {
    const region = ref.region || ref.image_region;
    return [
      ref.file_name || ref.attachment || ref.file,
      ref.sheet,
      ref.page ? `第 ${ref.page} 页` : "",
      ref.text_line ? `文本第 ${ref.text_line} 行` : "",
      ref.row ? `表格第 ${ref.row} 行` : "",
      ref.cell ? `单元格 ${ref.cell}` : "",
      region ? `图片区域 ${typeof region === "string" ? region : JSON.stringify(region)}` : "",
      ref.path,
    ].filter(Boolean).join(" · ");
  }

  renderFeeEvidenceReviewWarning(row = {}) {
    if (!row.has_conflict && !row.needs_review && !row.warning) return "";
    const message = row.warning || (row.has_conflict ? "AI 与规则结果冲突，已纳入预览，请人工核对。" : "证据或匹配信心不足，已纳入预览，可修改或清空。");
    return `<em class="ocw-mf-review-warning">${this.escape(message)}</em>`;
  }

  renderFeeEvidenceVoucherDetails(draft = {}, review = {}) {
    const evidence = draft.evidence || {};
    const evidenceId = this.escape(evidence.proposal_id || "evidence:classification");
    const statusOptions = [["ESTIMATED", "暂估"], ["ACTUAL", "实际"]];
    const refundParents = draft.refund_parent_options || [];
    const hasSelectionState = review.selections && typeof review.selections.has === "function";
    const selected = (row) => (hasSelectionState ? review.selections.has(String(row?.proposal_id || "")) : Boolean(row?.default_selected)) ? "checked" : "";
    const editValue = (row, fieldname, fallback = "") => review.edits?.[String(row?.proposal_id || "")]?.[fieldname] ?? row?.[fieldname] ?? fallback;
    const open = review.matrixDetailsOpen ? " open" : "";
    const feeRows = draft.fee_splits || [];
    const ledgerRows = this.feeEvidenceLedgerComponents(draft);
    return `<details class="ocw-mf-voucher-details" data-mf-fee-voucher-details${open}>
      <summary><span><b>凭证摘要</b><small>${this.escape(evidence.evidence_type || "待核对")} · ${this.escape(evidence.accounting_role || "待核对")} · ${this.escape(evidence.currency || "")} ${this.escape(evidence.original_amount || "待补录")}</small></span><em>展开核对详情</em></summary>
      <div class="ocw-mf-voucher-detail-body">
        ${this.renderCurrentSourceReviewControls(draft.source_context || {}, null, { fees: true })}
        ${this.renderFeeEvidenceReviewWarning(evidence)}
        <label class="ocw-mf-review-choice"><input type="checkbox" data-mf-fee-review-select data-proposal-id="${evidenceId}" ${selected(evidence)}><span><strong>采纳凭证事实</strong><small>${this.escape(evidence.reason || "请核对凭证类型和会计作用")}</small></span></label>
        <div class="ocw-mf-review-fields">
          <label>凭证类型<select data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="evidence_type">${[["QUOTE","报价"],["PREPAYMENT","预付款／暂缴"],["FINAL_INVOICE","最终发票／结算单"],["TAX_CERTIFICATE","完税凭证"],["PAYMENT","付款流水"],["REFUND","退款／贷项"],["OTHER","其他"]].map(([value,label]) => `<option value="${value}" ${value === editValue(evidence,"evidence_type") ? "selected" : ""}>${label}</option>`).join("")}</select></label>
          <label>会计作用<select data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="accounting_role">${[["ESTIMATE","更新暂估"],["FINAL_BILL","最终账单"],["SETTLEMENT","付款／退款流水"],["REFERENCE","仅作参考"]].map(([value,label]) => `<option value="${value}" ${value === editValue(evidence,"accounting_role") ? "selected" : ""}>${label}</option>`).join("")}</select></label>
          <label>凭证总额<input data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="original_amount" value="${this.escape(editValue(evidence,"original_amount"))}" inputmode="decimal"></label>
          <label>币种<select data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="currency">${this.materialFeeCurrencyOptions().map((option) => `<option value="${option.value}" ${option.value === editValue(evidence,"currency","RMB") ? "selected" : ""}>${option.label}</option>`).join("")}</select></label>
          <label>方向<select data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="direction"><option value="DEBIT" ${editValue(evidence,"direction","DEBIT") !== "CREDIT" ? "selected" : ""}>付款／应付</option><option value="CREDIT" ${editValue(evidence,"direction") === "CREDIT" ? "selected" : ""}>退款／冲回</option></select></label>
          <label>关联原付款<select data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="related_evidence"><option value="">无／待核对</option>${refundParents.map((row) => `<option value="${this.escape(row.name || "")}" ${String(row.name || "") === String(editValue(evidence,"related_evidence")) ? "selected" : ""}>${this.escape([row.currency,row.original_amount,row.attachment || row.name].filter(Boolean).join(" · "))}</option>`).join("")}</select></label>
          <label class="is-checkbox"><input type="checkbox" data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="is_final" ${Number(editValue(evidence,"is_final",0)) ? "checked" : ""}> 最终凭证</label>
        </div>
        <div class="ocw-mf-voucher-fee-splits"><h4>费用拆分</h4>${feeRows.length ? feeRows.map((row) => `<label class="ocw-mf-review-choice ${row.has_conflict || row.needs_review ? "is-warning" : ""}"><input type="checkbox" data-mf-fee-review-select data-proposal-id="${this.escape(row.proposal_id || "")}" ${selected(row)}><span><strong>${this.escape(row.label || row.logical_fee_key)} · ${this.escape(editValue(row,"currency",row.currency || ""))} <input data-mf-fee-review-edit data-proposal-id="${this.escape(row.proposal_id || "")}" data-fieldname="amount" value="${this.escape(editValue(row,"amount"))}" inputmode="decimal"></strong><small><select data-mf-fee-review-edit data-proposal-id="${this.escape(row.proposal_id || "")}" data-fieldname="amount_status">${statusOptions.map(([value,label]) => `<option value="${value}" ${value === editValue(row,"amount_status",evidence.suggested_amount_status) ? "selected" : ""}>${label}</option>`).join("")}</select></small>${this.renderFeeEvidenceReviewWarning(row)}</span></label>`).join("") : "<p>未识别出可安全拆分的金额，可保留凭证后人工补录。</p>"}</div>
        ${ledgerRows.length ? `<section class="ocw-mf-ledger-components"><header><h4>矩阵外台账分项</h4><p>结算、退款或冲回只记入台账，不重复计入物料成本。</p></header>${ledgerRows.map((row) => {
          const proposalId = this.escape(row.proposal_id || "");
          const refs = this.feeEvidenceComponentSourceRefs(row).map((ref) => this.feeEvidenceSourceLabel(ref)).filter(Boolean);
          return `<label class="ocw-mf-ledger-component ${row.has_conflict || row.needs_review || row.warning ? "is-warning" : ""}"><input type="checkbox" data-mf-fee-review-select data-proposal-id="${proposalId}" ${selected(row)}><span><strong>${this.feeEvidenceLedgerComponentLabel(row)} · ${this.escape(row.currency || "")} ${this.escape(row.original_amount ?? "--")}</strong><small>${refs.map((value) => this.escape(value)).join("；") || "来源位置待核对"}</small>${this.renderFeeEvidenceReviewWarning(row)}</span></label>`;
        }).join("")}</section>` : ""}
        <div class="ocw-mf-voucher-unclassified"><b>凭证待归类差额</b><span>${this.escape(draft.unclassified_difference || "0.00")} ${this.escape(evidence.currency || "")}</span><small>未明确归属前不伪造物料分摊。</small></div>
      </div>
    </details>`;
  }

  renderFeeEvidenceMatrixCell(draft, review, rowIndex, column) {
    const matrix = this.feeEvidenceMaterialMatrix(draft);
    const row = matrix.rows[rowIndex] || {};
    const cell = this.feeEvidenceMatrixEffectiveCell(draft, review, rowIndex, column.key);
    const classes = [cell.warning ? "is-warning" : "", cell.dirty ? "is-dirty" : "", cell.origin === "SAVED" ? "is-manual" : ""].filter(Boolean).join(" ");
    const rmb = cell.value ? (cell.missingFx || cell.amountRmb === null ? "缺汇率" : `¥ ${this.escape(cell.amountRmb || "0")}`) : "未分摊";
    const suggestion = cell.origin === "SAVED" && cell.suggestedOriginalAmount ? `<div class="ocw-mf-matrix-suggestion"><span>AI 建议 ${this.escape(cell.suggestedCurrency || cell.currency)} ${this.escape(cell.suggestedOriginalAmount)}</span><button type="button" data-action="mf-fee-matrix-use-ai" data-item="${this.escape(row.item || "")}" data-column-key="${column.key}">采用 AI 建议</button></div>` : "";
    return `<td class="ocw-mf-matrix-cell ${classes}" data-mf-fee-matrix-cell="${this.escape(row.item || "")}:${column.key}">
      <label><span class="sr-only">${this.escape(row.material_code || row.item || "")} ${column.label}</span><input data-mf-fee-matrix-input="1" data-item="${this.escape(row.item || "")}" data-column-key="${column.key}" inputmode="decimal" value="${this.escape(cell.value)}" placeholder="补录"></label>
      <small>${this.escape(cell.currency || this.feeEvidenceFeeTotals(draft, review)[column.feeLogicalKey]?.currency || draft.evidence?.currency || "")} · ${rmb}</small>
      ${cell.dirty && !cell.adoptedAI ? `<b class="ocw-mf-matrix-manual-badge">人工调整</b>` : (cell.origin === "SAVED" && !cell.adoptedAI ? `<b class="ocw-mf-matrix-manual-badge">人工值</b>` : (cell.value ? `<b class="ocw-mf-matrix-ai-badge">AI／规则</b>` : ""))}
      ${suggestion}${cell.warning ? `<em>${this.escape(cell.warning)}</em>` : ""}
    </td>`;
  }

  renderFeeEvidenceMatrixFooter(draft, review) {
    const totals = this.feeEvidenceMatrixTotals(draft, review);
    const render = (label, group) => `<div class="${group.overage ? "is-overage" : ""}"><b>${label}已分摊</b><span>${this.escape(group.currency || draft.evidence?.currency || "")} ${this.feeEvidencePlainNumber(group.allocatedOriginal)}${group.missingFx ? " · RMB 缺汇率" : ` · RMB ${this.feeEvidencePlainNumber(group.allocatedRmb)}`}</span><small>费用总额 ${this.feeEvidencePlainNumber(group.feeTotal)} · 剩余差额 ${this.feeEvidencePlainNumber(group.remaining)}</small></div>`;
    return `<div class="ocw-mf-matrix-totals" data-mf-fee-matrix-totals>${render("进口税费", totals.import_tax)}${render("清关费", totals.customs_clearance_fee)}<p>确认应用仅写入费用分项，不会自动试算、确认版本或推送 ERP。</p></div>`;
  }

  renderFeeEvidenceReviewDraft(draft = {}, review = {}) {
    this.ensureFeeEvidenceMatrixState(review, draft);
    const matrix = this.feeEvidenceMaterialMatrix(draft);
    const columns = this.feeEvidenceMatrixColumns();
    const unmatched = (matrix.unmatched_lines || draft.unmatched_lines || []).filter(
      (row) => String(row?.reason_code || "") !== "MATERIAL_MATRIX_LEDGER_ONLY"
    );
    const sourceRefs = [
      ...(draft.evidence?.source_refs || []),
      ...(draft.fee_splits || []).flatMap((row) => row.source_refs || []),
      ...this.feeEvidenceLedgerComponents(draft).flatMap((row) => this.feeEvidenceComponentSourceRefs(row)),
    ];
    const rows = matrix.rows.map((row, rowIndex) => {
      const cells = columns.map((column) => this.renderFeeEvidenceMatrixCell(draft, review, rowIndex, column)).join("");
      const rowCells = columns.map((column) => this.feeEvidenceMatrixEffectiveCell(draft, review, rowIndex, column.key));
      const active = rowCells.filter((cell) => String(cell.value || "").trim());
      const originalCurrencies = [...new Set(active.map((cell) => cell.currency).filter(Boolean))];
      const originalTotal = active.reduce((sum, cell) => sum + (Number(cell.value) || 0), 0);
      const rmbTotal = active.reduce((sum, cell) => cell.missingFx ? sum : sum + (Number(cell.amountRmb) || 0), 0);
      const hasWarning = rowCells.some((cell) => cell.warning);
      const dirty = rowCells.some((cell) => cell.dirty);
      const hsSuggestions = (row.hs_suggestions || []).filter(Boolean);
      return `<tr class="${hasWarning || hsSuggestions.length ? "is-warning" : ""}">
        <th scope="row"><strong>${this.escape(row.material_code || row.item || "--")}</strong><small>${this.escape(row.product_name || row.item || "")}</small></th>
        <td class="ocw-mf-matrix-hs" data-mf-fee-matrix-hs="${this.escape(row.item || "")}"><span>${this.escape(row.hs_code || "--")}</span>${hsSuggestions.length ? `<em>HS 差异：${hsSuggestions.map((value) => this.escape(value)).join("、")}</em>` : ""}</td>
        ${cells}
        <td class="ocw-mf-matrix-row-total"><strong>${originalCurrencies.length === 1 ? `${this.escape(originalCurrencies[0])} ${this.feeEvidencePlainNumber(originalTotal)}` : (active.length ? "多币种" : "--")}</strong><small>RMB ${this.feeEvidencePlainNumber(rmbTotal)}${active.some((cell) => cell.missingFx) ? " + 缺汇率" : ""}</small></td>
        <td class="ocw-mf-matrix-status"><b>${dirty ? "已人工调整" : (hasWarning || hsSuggestions.length ? "待核对" : "已预览")}</b><small>${active.length} 个分项</small></td>
      </tr>`;
    }).join("");
    const warnings = unmatched.length ? `<aside class="ocw-mf-matrix-unmatched"><b>无法归属到具体物料的凭证明细</b>${unmatched.map((row) => `<p>${this.escape(row.message || row.reason || row.reason_code || "请核对原附件")}</p>`).join("")}</aside>` : "";
    return `<div class="ocw-mf-fee-review-draft ocw-mf-fee-review-a1">
      ${this.renderFeeEvidenceVoucherDetails(draft, review)}
      ${warnings}
      ${matrix.missing_fx || draft.missing_fx ? `<div class="ocw-mf-review-warning is-block">缺汇率：可保存原币事实，RMB 小计不计入试算。</div>` : ""}
      <section class="ocw-mf-matrix-section"><header><div><h4>物料税费预览</h4><p>每个物料一行；AI／规则建议已默认纳入，清空单元格即不采用。</p></div></header>
        <div class="ocw-mf-matrix-scroll"><table class="ocw-mf-matrix-table"><thead><tr><th>物料 / SKU</th><th>HS</th>${columns.map((column) => `<th>${column.label}</th>`).join("")}<th>物料合计</th><th>核对状态</th></tr></thead><tbody>${rows || `<tr><td colspan="10">当前批次暂无物料</td></tr>`}</tbody></table></div>
      </section>
      ${sourceRefs.length ? `<details class="ocw-mf-matrix-sources"><summary>来源证据</summary><p>${sourceRefs.map((ref) => this.escape(this.feeEvidenceSourceLabel(ref))).filter(Boolean).join("；")}</p></details>` : ""}
      ${this.renderFeeEvidenceMatrixFooter(draft, review)}
    </div>`;
  }
