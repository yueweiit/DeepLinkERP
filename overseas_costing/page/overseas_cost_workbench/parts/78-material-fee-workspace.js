  ensureMaterialFeeState() {
    const batchName = String(this.detailState?.batchName || "");
    if (!this.materialFeeState || this.materialFeeState.batchName !== batchName) {
      this.materialFeeState = {
        batchName,
        page: 1,
        pageLength: 200,
        onlyMissing: false,
        showAuxiliary: false,
        loading: false,
        requestId: 0,
        feeRequestId: 0,
        feeDrafts: {},
        focusedFeeInput: null,
        materials: null,
        fees: null,
        preview: null,
        aiFill: null,
        aiPendingReady: null,
        aiProgressDialog: null,
        aiProgressMinimized: false,
        aiStartPromise: null,
        activeAICandidate: null,
        feeEvidenceReview: null,
        feeEvidenceReviewDialog: null,
        feeEvidenceReviewStartPromise: null,
      };
    }
    if (!Number.isFinite(this.materialFeeState.requestId)) this.materialFeeState.requestId = 0;
    if (!Number.isFinite(this.materialFeeState.feeRequestId)) this.materialFeeState.feeRequestId = 0;
    this.materialFeeState.feeDrafts = this.materialFeeState.feeDrafts || {};
    this.materialFeeState.pendingWrites = this.materialFeeState.pendingWrites || new Set();
    this.materialFeeState.materialSaveErrors = this.materialFeeState.materialSaveErrors || {};
    this.materialFeeState.materialDrafts = this.materialFeeState.materialDrafts || {};
    this.materialFeeState.aiFill = this.materialFeeState.aiFill || null;
    this.materialFeeState.aiPendingReady = this.materialFeeState.aiPendingReady || null;
    if (this.materialFeeState.aiClarification === undefined) this.materialFeeState.aiClarification = "";
    if (this.materialFeeState.aiClarificationSaved === undefined) this.materialFeeState.aiClarificationSaved = "";
    if (!Number.isFinite(this.materialFeeState.aiClarificationRevision)) this.materialFeeState.aiClarificationRevision = 0;
    if (!this.materialFeeState.aiClarificationStatus) this.materialFeeState.aiClarificationStatus = "saved";
    if (!Number.isFinite(this.materialFeeState.inputRevision)) this.materialFeeState.inputRevision = 0;
    if (this.materialFeeState.focusedFeeInput === undefined) this.materialFeeState.focusedFeeInput = null;
    return this.materialFeeState;
  }

  bindMaterialFeeWorkspaceEvents() {
    this.$root.on("click", "[data-action='mf-reload']", () => this.loadMaterialFeeWorkspace());
    this.$root.on("click", "[data-action='mf-view-settlement-source']", () => {
      this.openBatchSettlementDialog(this.detailState.batchName, this.detailState.versionName || null);
    });
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
      this.closeMaterialAICandidatePopover();
      const state = this.ensureMaterialFeeState();
      state.page = Math.max(1, Number($(event.currentTarget).attr("data-page") || 1));
      this.loadMaterialFeeWorkspace();
    });
    this.$root.on("click", "[data-action='mf-edit-fee']", (event) => {
      this.openMaterialFeeDialog($(event.currentTarget).attr("data-fee-key"));
    });
    this.$root.on("click", "[data-mf-freight-action]", (event) => {
      const $button = $(event.currentTarget);
      const action = $button.attr("data-mf-freight-action");
      const state = this.ensureMaterialFeeState();
      if (state.freightEditor?.freightWriting) return;
      if (action === "cancel") { state.freightEditor = null; this.renderMaterialFeeFreightSurface(); }
      else if (action === "save") this.saveMaterialFeeFreightEditor();
      else if (action === "refresh") this.refreshMaterialFeeFreightEditor();
      else this.openMaterialFeeFreightEditor($button.attr("data-fee-key"), action);
    });
    this.$root.on("input change", "[data-mf-freight-editor] [data-freight-field],[data-mf-freight-editor] [data-freight-line]", (event) => {
      this.updateMaterialFeeFreightDraft($(event.currentTarget));
    });
    this.$root.on("click", "[data-action='mf-link-evidence']", (event) => {
      this.openMaterialFeeEvidenceDialog($(event.currentTarget).attr("data-fee-key"));
    });
    this.$root.on("change", "[data-mf-fee-status='1']", (event) => {
      this.changeMaterialFeeStatus($(event.currentTarget)).catch((error) => this.showError(error));
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
    this.$root.on("click", "[data-action='mf-import-wiki']", async () => {
      const state = this.ensureMaterialFeeState();
      try {
      if (!state.settlementData) {
        const batchName = this.detailState.batchName;
        const data = await this.settlementApi("get_batch_settlement", {batch_name: batchName, version_name: this.detailState.versionName || null});
        if (this.materialFeeState !== state || this.detailState.batchName !== batchName) return;
        if (!data?.ok) throw new Error(data?.message || "资料来源读取失败，请重试");
        state.settlementData = data;
      }
      const freightEnabled = state.settlementData.freight_mode === true;
      const action = freightEnabled
        ? this.openBatchSettlementDialog(this.detailState.batchName, this.detailState.versionName || this.getDetailBatch().current_version, "packing")
        : this.openWikiMaterialImportDialog();
      await action;
      } catch (error) { this.showError(error); }
    });
    this.$root.on("click", "[data-action='mf-ai-fill']", () => {
      const fill = this.ensureMaterialFeeState().aiFill;
      if (["STARTING", "QUEUED", "RUNNING", "READY", "FAILED", "STALE"].includes(String(fill?.status || ""))) {
        this.openMaterialAIProgressDialog();
        return;
      }
      this.startMaterialAIFill();
    });
    this.$root.on("click", "[data-action='mf-ai-progress-restore']", () => this.openMaterialAIProgressDialog());
    this.$root.on("click", "[data-action='mf-ai-apply']", () => {
      this.applyMaterialAIFill().catch((error) => this.showError(error));
    });
    this.$root.on("click", "[data-action='mf-ai-discard']", () => {
      this.discardMaterialAIFill().catch((error) => this.showError(error));
    });
    this.$root.on("click", "[data-action='mf-ai-open-candidate']", (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.openMaterialAICandidatePopover($(event.currentTarget));
    });
    this.$root.on("click", "[data-action='mf-ai-adopt-candidate']", (event) => {
      const $button = $(event.currentTarget);
      this.adoptMaterialAICandidate(
        $button.attr("data-item-name"),
        $button.attr("data-fieldname"),
        Number($button.attr("data-candidate-index") || 0)
      );
      this.closeMaterialAICandidatePopover();
    });
    this.$root.on("click", "[data-action='mf-correct-purchase']", (event) => {
      const $button = $(event.currentTarget);
      this.openMaterialPurchaseCorrectionDialog(
        $button.attr("data-item-name"),
        $button.attr("data-fieldname")
      );
    });
    this.$root.on("input", "[data-mf-ai-clarification]", (event) => {
      const state = this.ensureMaterialFeeState();
      state.aiClarification = String($(event.currentTarget).val() || "").slice(0, 4000);
      state.aiClarificationDirty = state.aiClarification.trim() !== state.aiClarificationSaved;
      state.aiClarificationStatus = state.aiClarificationSavePromise ? "saving" : (state.aiClarificationDirty ? "unsaved" : "saved");
      state.aiClarificationError = "";
      this.updateMaterialAIClarificationStatus();
    });
    this.$root.on("click", "[data-action='mf-ai-clarification-save']", () =>
      this.saveMaterialAIClarification().catch((error) => this.showError(error)));
    this.$root.on("click", "[data-action='mf-ai-clarification-rerun']", () =>
      this.reanalyzeMaterialAIClarification().catch((error) => this.showError(error)));
    this.$root.on("change", "[data-mf-ai-proposal-select]", (event) => {
      const fill = this.ensureMaterialFeeState().aiFill;
      if (!fill?.selections) return;
      const proposalId = String($(event.currentTarget).attr("data-proposal-id") || "");
      if ($(event.currentTarget).prop("checked")) fill.selections.add(proposalId);
      else fill.selections.delete(proposalId);
      this.renderMaterialFeeWorkspacePreservingPosition();
    });
    this.$root.on("input", "[data-mf-ai-edit]", (event) => {
      this.updateSourceAIReviewEdit($(event.currentTarget));
    });
    this.$root.on("change", "select[data-mf-ai-edit]", (event) => {
      this.updateSourceAIReviewEdit($(event.currentTarget));
    });
    this.$root.on("click", "[data-action='mf-grid-scroll-left'], [data-action='mf-grid-scroll-right']", (event) => {
      this.closeMaterialAICandidatePopover();
      const direction = $(event.currentTarget).attr("data-action") === "mf-grid-scroll-left" ? -1 : 1;
      const viewport = this.$root.find("[data-mf-grid-viewport]").get(0);
      if (viewport) viewport.scrollBy({ left: direction * Math.max(240, viewport.clientWidth * 0.65), behavior: "smooth" });
    });
    this.$root.on("focus", "[data-mf-fee-input]", (event) => {
      const $input = $(event.currentTarget);
      const state = this.ensureMaterialFeeState();
      state.focusedFeeInput = {
        feeKey: String($input.attr("data-fee-key") || ""),
        field: String($input.attr("data-mf-fee-input") || ""),
      };
    });
    this.$root.on("input", "[data-mf-fee-input]", (event) => {
      this.updateMaterialFeeDraftFromInput($(event.currentTarget));
    });
    this.$root.on("change", "select[data-mf-fee-currency]", (event) => {
      this.updateMaterialFeeDraftFromInput($(event.currentTarget));
      this.saveMaterialFeeInlineAmount($(event.currentTarget)).catch((error) => this.showError(error));
    });
    this.$root.on("input", "[data-mf-cell-input]", (event) => {
      this.updateMaterialDraftFromInput($(event.currentTarget));
    });
    this.$root.on("change", "select[data-mf-cell-input]", (event) => {
      this.updateMaterialDraftFromInput($(event.currentTarget));
      this.saveMaterialFeeCell($(event.currentTarget)).catch((error) => this.showError(error));
    });
    this.$root.on("keydown", "[data-mf-fee-input]", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      event.currentTarget.blur();
    });
    this.$root.on("blur", "[data-mf-fee-input]", (event) => {
      const $input = $(event.currentTarget);
      const feeKey = typeof $input.attr === "function" ? String($input.attr("data-fee-key") || "") : "";
      const $related = event.relatedTarget ? $(event.relatedTarget) : null;
      if (
        $related
        && typeof $related.attr === "function"
        && $related.attr("data-mf-fee-input")
        && String($related.attr("data-fee-key") || "") === feeKey
      ) return;
      const state = this.ensureMaterialFeeState();
      const field = typeof $input.attr === "function" ? String($input.attr("data-mf-fee-input") || "") : "";
      if (state.focusedFeeInput?.feeKey === feeKey && state.focusedFeeInput?.field === field) {
        state.focusedFeeInput = null;
      }
      this.saveMaterialFeeInlineAmount($input).catch((error) => this.showError(error));
    });
    this.$root.on("focus", "[data-mf-cell-input]", (event) => {
      const $input = $(event.currentTarget);
      this.ensureMaterialFeeState().focusedMaterialInput = {
        itemName: $input.attr("data-item-name"),
        fieldname: $input.attr("data-fieldname"),
      };
      $(event.currentTarget).closest(".ocw-mf-cell").removeClass("is-save-error").attr("title", "");
    });
    this.$root.on("keydown", "[data-mf-cell-input]", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      event.currentTarget.blur();
    });
    this.$root.on("blur", "[data-mf-cell-input]", (event) => {
      const $input = $(event.currentTarget);
      const state = this.ensureMaterialFeeState();
      if (state.focusedMaterialInput?.itemName === $input.attr("data-item-name") && state.focusedMaterialInput?.fieldname === $input.attr("data-fieldname")) state.focusedMaterialInput = null;
      this.saveMaterialFeeCell($(event.currentTarget)).catch((error) => this.showError(error));
    });
    this.$root.on("paste", "[data-mf-cell-input]", (event) => {
      const clipboard = event.originalEvent?.clipboardData?.getData("text/plain") || "";
      if (!clipboard.includes("\t") && !clipboard.includes("\n") && !clipboard.includes("\r")) return;
      event.preventDefault();
      this.previewMaterialPaste($(event.currentTarget), clipboard);
    });
    if (typeof document !== "undefined") {
      $(document).off("click.ocwMfCandidate").on("click.ocwMfCandidate", (event) => {
        if ($(event.target).closest("[data-mf-ai-candidate-popover], [data-action='mf-ai-open-candidate']").length) return;
        this.closeMaterialAICandidatePopover();
      });
      $(document).off("keydown.ocwMfCandidate").on("keydown.ocwMfCandidate", (event) => {
        if (event.key === "Escape") this.closeMaterialAICandidatePopover();
      });
    }
  }

  invalidateMaterialAIClarification(note) {
    const state = this.ensureMaterialFeeState();
    if (Number(note.revision || 0) > Number(state.aiFill?.clarification_revision ?? state.aiClarificationRevision ?? 0) && state.aiFill
        && ["STARTING","QUEUED","RUNNING","READY"].includes(state.aiFill.status)) {
      state.aiRunGeneration = Number(state.aiRunGeneration || 0) + 1;
      state.aiFill = { ...state.aiFill, status: "STALE", draftVisible: false, stale: true };
      state.aiPendingReady = null;
      state.aiStartPromise = null;
    }
  }

  acceptMaterialAIClarification(note) {
    const state = this.ensureMaterialFeeState();
    if (!note || Number(note.revision || 0) < Number(state.aiClarificationRevision || 0)) return;
    this.invalidateMaterialAIClarification(note);
    if (state.aiClarificationDirty || state.aiClarificationSavePromise) return;
    state.aiClarification = String(note.text || "");
    state.aiClarificationSaved = state.aiClarification;
    state.aiClarificationRevision = Number(note.revision || 0);
    state.aiClarificationLoaded = true;
    state.aiClarificationStatus = "saved";
    state.aiClarificationError = "";
  }

  materialAIClarificationStatusText() {
    const state = this.ensureMaterialFeeState();
    return { unsaved: "未保存", saving: "保存中…", saved: "已保存", failed: "保存失败" }[state.aiClarificationStatus] || "未保存";
  }

  renderMaterialAIClarification() {
    const state = this.ensureMaterialFeeState();
    const busy = Boolean(state.aiClarificationSavePromise || state.aiClarificationRerunPromise);
    return `<div class="ocw-mf-ai-clarification"><label><span>告诉 AI 如何理解</span><input data-mf-ai-clarification="1" value="${this.escape(state.aiClarification || "")}" maxlength="4000" placeholder="例如：两款是一套，共四套；每种数量相同" /></label><div class="ocw-mf-ai-clarification-actions"><span data-mf-ai-clarification-status="${state.aiClarificationStatus}" role="status" title="${this.escape(state.aiClarificationError || "")}">${this.materialAIClarificationStatusText()}</span><button type="button" class="ocw-outline-btn" data-action="mf-ai-clarification-save" ${busy ? "disabled" : ""}>保存说明</button><button type="button" class="ocw-outline-btn" data-action="mf-ai-clarification-rerun" ${busy ? "disabled" : ""}>按说明重新分析</button></div></div>`;
  }

  updateMaterialAIClarificationStatus() {
    if (!this.$root?.find) return;
    const state = this.ensureMaterialFeeState();
    this.$root.find("[data-mf-ai-clarification-status]").text(this.materialAIClarificationStatusText())
      .attr("data-mf-ai-clarification-status", state.aiClarificationStatus)
      .attr("title", state.aiClarificationError || "");
    this.$root.find("[data-action='mf-ai-clarification-save'], [data-action='mf-ai-clarification-rerun']")
      .prop("disabled", Boolean(state.aiClarificationSavePromise || state.aiClarificationRerunPromise));
  }

  saveMaterialAIClarification() {
    const state = this.ensureMaterialFeeState();
    if (state.aiClarificationSavePromise) return state.aiClarificationSavePromise;
    const submittedText = String(state.aiClarification || "").trim();
    const expectedRevision = Number(state.aiClarificationRevision || 0);
    state.aiClarificationStatus = "saving";
    state.aiClarificationError = "";
    const savePromise = (async () => {
      try {
        const result = await this.call("overseas_costing.api.materials.save_source_ai_clarification", {
          batch_name: state.batchName, clarification_text: submittedText, expected_revision: expectedRevision,
        }, false);
        if (this.materialFeeState !== state) return false;
        if (!result?.ok) {
          if (result?.conflict && result.clarification) {
            this.invalidateMaterialAIClarification(result.clarification);
            state.aiClarificationRevision = Number(result.clarification.revision || 0);
            state.aiClarificationSaved = String(result.clarification.text || "");
          }
          throw new Error(result?.message || "说明保存失败，请重试。");
        }
        const note = result.clarification;
        this.invalidateMaterialAIClarification(note);
        state.aiClarificationSaved = String(note.text || "");
        state.aiClarificationRevision = Number(note.revision || 0);
        state.aiClarificationLoaded = true;
        state.aiClarificationDirty = String(state.aiClarification || "").trim() !== state.aiClarificationSaved;
        if (!state.aiClarificationDirty) state.aiClarification = state.aiClarificationSaved;
        state.aiClarificationStatus = state.aiClarificationDirty ? "unsaved" : "saved";
        this.updateMaterialAIProgressSurface();
        return result;
      } catch (error) {
        if (this.materialFeeState === state) {
          state.aiClarificationStatus = "failed";
          state.aiClarificationDirty = true;
          state.aiClarificationError = error.message || "说明保存失败，请重试。";
        }
        throw error;
      } finally {
        state.aiClarificationSavePromise = null;
        if (this.materialFeeState === state) this.updateMaterialAIClarificationStatus();
      }
    })();
    state.aiClarificationSavePromise = savePromise;
    this.updateMaterialAIClarificationStatus();
    return savePromise;
  }

  reanalyzeMaterialAIClarification() {
    const state = this.ensureMaterialFeeState();
    if (state.aiClarificationRerunPromise) return state.aiClarificationRerunPromise;
    const rerun = (async () => {
      const saved = await this.saveMaterialAIClarification();
      if (!saved || this.materialFeeState !== state) return;
      if (state.aiClarificationDirty) throw new Error("说明仍有未保存修改，请保存后重新分析。");
      // Retire the old polling generation even when its start promise is still pending.
      state.aiRunGeneration = Number(state.aiRunGeneration || 0) + 1;
      state.aiStartPromise = null;
      return this.startMaterialAIFill({ force: false, restart: true });
    })().finally(() => {
      state.aiClarificationRerunPromise = null;
      if (this.materialFeeState === state) this.updateMaterialAIClarificationStatus();
    });
    state.aiClarificationRerunPromise = rerun;
    return rerun;
  }

  async loadMaterialFeeWorkspace(options = {}) {
    const state = this.ensureMaterialFeeState();
    const batch = this.getDetailBatch();
    const batchName = String(batch.name || this.detailState.batchName || "");
    const requestedVersion = this.detailState.versionName;
    const requestId = ++state.requestId;
    state.loading = true;
    if (!options.quiet) this.renderDetailTabLoading("正在读取费用、凭证和物料表");
    try {
      const shouldRestoreAI = !state.aiFill;
      const restoreGeneration = state.aiRunGeneration || 0;
      const [detail, materials, fees, preview, latestAI, savedClarification] = await Promise.all([
        this.call("overseas_costing.api.batch.get_batch_detail", {
          batch_name: batchName,
          version_name: this.detailState.versionName || batch.current_version || null,
        }),
        this.call("overseas_costing.api.materials.get_material_grid", {
          batch_name: batchName,
          version_name: this.detailState.versionName || batch.current_version || null,
          page: state.page,
          page_length: state.pageLength,
        }),
        this.call("overseas_costing.api.fees.get_fee_worklist", {
          batch_name: batchName,
          version_name: this.detailState.versionName || batch.current_version || null,
        }),
        this.call("overseas_costing.api.calculate.preview_comprehensive_cost", {
          batch_name: batchName,
          version_name: this.detailState.versionName || batch.current_version || null,
        }),
        shouldRestoreAI
          ? this.call("overseas_costing.api.materials.get_source_ai_review_status", {
              batch_name: batchName,
              version_name: this.detailState.versionName || batch.current_version || null,
              run_id: "",
            }, false, { inlineErrors: true })
          : Promise.resolve(null),
        shouldRestoreAI ? Promise.resolve(null)
          : this.call("overseas_costing.api.materials.get_source_ai_clarification", { batch_name: batchName }, false),
      ]);
      if (
        requestId !== state.requestId
        || this.materialFeeState !== state
        || this.detailState.batchName !== batchName
        || this.detailState.versionName !== requestedVersion
        || this.detailState.tab !== "documents"
      ) return false;
      this.applyMaterialFeeHeaderSnapshot(detail, batchName);
      state.materials = materials;
      state.fees = fees;
      state.preview = preview;
      state.settlementData = null;
      this.acceptMaterialAIClarification(savedClarification?.clarification || latestAI?.clarification);
      if (!state.aiFill && restoreGeneration === (state.aiRunGeneration || 0) && latestAI?.ok && latestAI.status && latestAI.status !== "NONE") {
        if (Number(latestAI.clarification_revision || 0) < Number(state.aiClarificationRevision || 0)
            && ["QUEUED","RUNNING","READY"].includes(latestAI.status)) latestAI.status = "STALE";
        state.aiFill = { ...latestAI, runId: latestAI.run_id, draftVisible: false };
        state.aiPendingReady = latestAI.status === "READY" ? latestAI : null;
      }
      state.loading = false;
      this.renderMaterialFeeWorkspace();
      if (["QUEUED", "RUNNING"].includes(String(state.aiFill?.status || "")) && !state.aiFill.polling && !state.aiFill.polling_paused) {
        state.aiFill.polling = true;
        this.pollMaterialAIFill(
          state,
          batchName,
          this.detailState.versionName || batch.current_version || "",
          state.aiFill.runId
        ).catch((error) => this.failMaterialAIProgress(error, "AI 分析状态读取失败，正在等待重试。"));
      }
      return true;
    } catch (error) {
      if (
        requestId !== state.requestId
        || this.materialFeeState !== state
        || this.detailState.batchName !== batchName
        || this.detailState.versionName !== requestedVersion
        || this.detailState.tab !== "documents"
      ) return false;
      state.loading = false;
      this.renderDetailTabError("资料与费用", error);
      return false;
    }
  }

  materialFeeBasisLabel(value) {
    return {
      goods_value: "本次发货货值",
      project_gross_weight: "按项目毛重及项目内毛重分摊",
      gross_weight: "毛重",
      volume: "体积",
      chargeable_weight: "计费重",
      direct: "指定物料直接承担",
      zero_amount: "金额为 0，无需分摊",
    }[String(value || "")] || String(value || "--");
  }

  materialFeeCurrencyOptions() {
    return [
      { value: "RMB", label: "人民币（RMB）" },
      { value: "MXN", label: "比索（MXN）" },
      { value: "USD", label: "美金（USD）" },
    ];
  }

  normalizeMaterialFeeCurrency(value) {
    const currency = String(value ?? "RMB").trim().toUpperCase();
    return currency === "CNY" ? "RMB" : currency;
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
    this.closeMaterialAICandidatePopover();
    const materialSummary = state.materials || {};
    const hasSettlementCargo = (materialSummary.items || []).some((item) => item.settlement_cargo);
    const feeSummary = state.fees.summary || {};
    const evidencePending = Number(feeSummary.missing_evidence_fee_count || 0);
    const aiActive = ["STARTING", "QUEUED", "RUNNING", "READY"].includes(String(state.aiFill?.status || ""));
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
        <div data-area="settlement-strip" aria-live="polite"><p class="ocw-settlement-hint">正在读取物流采购支出关联…</p></div>
        ${feeSummary.source_pending ? `<p class="ocw-mf-dialog-note">${this.escape(feeSummary.source_message)}</p>` : ""}
        <div class="ocw-mf-alert-strip" aria-label="当前待办摘要">
          ${this.renderMaterialFeeMetric("计算红格", materialSummary.missing_cell_count || 0, "danger")}
          ${this.renderMaterialFeeMetric("费用未定", feeSummary.missing_amount_fee_count || 0, "danger")}
          ${this.renderMaterialFeeMetric("凭证待补", evidencePending, evidencePending ? "warn" : "ok")}
          ${this.renderMaterialFeeMetric("暂估待核", feeSummary.estimated_fee_count || 0, Number(feeSummary.estimated_fee_count || 0) ? "warn" : "ok")}
        </div>
        <section class="ocw-mf-section ocw-mf-material-section">
          <div class="ocw-mf-section-title ocw-mf-material-title">
            <div><span>01</span><h3>物料与装箱数据</h3><p>采购标识与数量保持只读；缺失的采购金额、币种和单位可直接补录。${hasSettlementCargo ? "发货数量按结算采购支出采用，原装箱数量单独保留。" : "蓝色发货数量默认等于采购数量。"}</p></div>
            <div class="ocw-mf-material-actions">
              <button class="ocw-outline-btn ${state.onlyMissing ? "is-active" : ""}" type="button" data-action="mf-toggle-missing">只看缺项</button>
              <button class="ocw-outline-btn ${state.showAuxiliary ? "is-active" : ""}" type="button" data-action="mf-toggle-aux">展开辅助列</button>
              <button class="ocw-primary-btn" type="button" data-action="mf-import-wiki">获取装箱资料</button>
              ${this.renderMaterialAIProgressChip()}
              <button class="ocw-primary-btn" type="button" data-action="mf-ai-fill">${aiActive ? (state.aiFill?.status === "READY" ? "查看填充预览" : "查看填充进度") : "自动填充资料"}</button>
            </div>
          </div>
          ${this.renderMaterialAIClarification()}
          ${this.renderMaterialFeeGrid()}
          <div class="ocw-mf-ai-candidate-popover" data-mf-ai-candidate-popover="1" role="dialog" aria-label="AI 候选详情" hidden></div>
        </section>
        <section class="ocw-mf-section ocw-mf-fee-section">
          <div class="ocw-mf-section-title"><div><span>02</span><h3>费用与凭证</h3><p>录入金额后自动保存；凭证可稍后补充，系统会在 SKU 试算时统一分摊。</p></div></div>
          <div class="ocw-mf-fee-layout">
            <div class="ocw-mf-fee-table-wrap">${this.renderMaterialFeeTable(state.fees.fees || state.fees.items || [])}</div>
          </div>
        </section>
        ${this.renderMaterialFeeCostTable()}
        ${this.renderMaterialFeeTodos()}
      </div>
    `);
    this.loadSettlementStrip?.(state.batchName, state.settlementData);
    this.bindMaterialGridScrollControls();
    this.restoreMaterialFeeInputFocus();
  }

  renderMaterialFeeMetric(label, value, tone) {
    const number = Number(value || 0);
    return `<div class="ocw-mf-metric is-${this.escape(tone)}"><span>${this.escape(label)}</span><strong>${this.escape(String(number))}</strong><em>${number ? "待处理" : "已清零"}</em></div>`;
  }

  renderMaterialFeeTable(fees) {
    if (!fees.length) return `<div class="ocw-detail-empty"><strong>暂无费用清单</strong></div>`;
    return `
      <table class="ocw-mf-fee-table">
        <thead><tr><th>费用项目</th><th>状态</th><th>原币金额</th><th>凭证</th><th>操作</th></tr></thead>
        <tbody>${fees.map((fee) => this.renderMaterialFeeRow(fee)).join("")}</tbody>
      </table>
    `;
  }

  renderMaterialFeeRow(fee) {
    if (fee.duplicate_rule_names?.length) {
      const evidence = fee.evidence || [];
      return `<tr class="is-review">
        <td><strong>${this.escape(fee.expense_category || fee.logical_fee_key || "费用")}</strong><small>记录：${this.escape(fee.name || "未命名")}</small></td>
        <td><span class="ocw-mf-badge is-danger">费用重复 · 未计入</span><small>${this.escape(this.materialFeeAmountStatus(fee.amount_state || fee.amount_status).label)}</small></td>
        <td>${this.escape(fee.currency || "RMB")} ${this.escape(fee.amount ?? "未填写")}<small>请先核对并停用重复记录，再保存或试算。</small></td>
        <td>${evidence.map((row) => `<span>${this.escape(row.evidence_role || "凭证")} · ${this.escape(row.attachment || row.name || "")}</span>`).join("") || "暂无关联凭证"}</td>
        <td><strong>冲突记录</strong><small>${fee.duplicate_rule_names.map((name) => this.escape(name)).join("、")}</small></td>
      </tr>`;
    }
    const amountInfo = this.materialFeeAmountStatus(fee.amount_state || fee.amount_status);
    const evidenceInfo = this.materialFeeEvidenceLabel(fee.evidence_state);
    const scopeLabel = String(fee.scope_type || "ALL_ITEMS") === "ALL_ITEMS" ? "全批物料" : String(fee.scope_type) === "DIRECT_ITEM" ? "指定单行" : "指定物料";
    const amountStatus = String(fee.amount_state || fee.amount_status || "MISSING").toUpperCase();
    const feeKey = String(fee.logical_fee_key || fee.fee_key || "");
    const sourceOwned = Boolean(fee.source_binding_id);
    const aiFill = this.materialFeeState?.aiFill;
    const aiFeeProposal = !sourceOwned && !aiFill?.row_review && aiFill?.status === "READY" && aiFill.draftVisible
      ? (aiFill.proposals || []).find((proposal) => proposal.proposal_type === "fee_update" && String(proposal.payload?.logical_fee_key || "") === feeKey)
      : null;
    const aiFeeEdit = aiFeeProposal ? aiFill.edits?.[String(aiFeeProposal.proposal_id || "")] : null;
    const aiFeeValues = aiFeeEdit || aiFeeProposal?.payload || null;
    const draft = sourceOwned || aiFeeProposal ? null : (this.materialFeeState?.feeDrafts?.[feeKey] || null);
    const amount = aiFeeValues ? aiFeeValues.amount : draft ? draft.amount : (fee.amount ?? "");
    const currency = this.normalizeMaterialFeeCurrency(aiFeeValues ? aiFeeValues.currency : draft ? draft.currency : fee.currency || "RMB");
    const currencyOptions = this.materialFeeCurrencyOptions();
    const supportedCurrency = currencyOptions.some((option) => option.value === currency);
    const savedPreview = this.materialFeeSavedCostPreview();
    const savedCurrent = savedPreview && this.detailState?.header?.status !== "Dirty"
      && !Object.keys(this.materialFeeState?.feeDrafts || {}).length
      && !Object.keys(this.materialFeeState?.materialDrafts || {}).length
      && !Object.keys(this.materialFeeState?.materialSaveErrors || {}).length;
    const preview = (savedCurrent ? savedPreview : this.materialFeeState?.preview) || {};
    const excludedFee = (preview.excluded_fees || []).find((row) => row.fee_key === feeKey);
    const inclusionLabel = aiFeeProposal ? "AI 草稿 · 未保存" : draft ? "修改待保存" : (preview.included_fees || []).some((row) => row.fee_key === feeKey) ? (savedCurrent ? "已计入试算" : "可计入 · 待试算") : excludedFee ? this.materialFeeExclusionReason(excludedFee) : "";
    const missingSavedAmount = amountStatus === "MISSING" && amount !== "";
    const defaultZero = !draft && fee.virtual && fee.is_default_zero && amountStatus === "ESTIMATED";
    const mexicoEntry = fee.entry_responsibility === "MEXICO";
    const forceActual = Boolean(draft?.forceActual || missingSavedAmount);
    const inlineError = String(draft?.error || "");
    const errorId = this.materialFeeErrorId(feeKey);
    const feeLabel = String(fee.expense_category || feeKey || "费用");
    const evidence = fee.evidence || [];
    const evidenceAttachmentCount = new Set(evidence.map((row) => row.attachment).filter(Boolean)).size || evidence.length;
    const evidenceFinancials = fee.evidence_financials || {};
    const settlementRows = Object.entries(evidenceFinancials.settlement_net_by_currency || {}).map(([code, value]) => `${code} ${this.formatMoney(value)}`);
    const finalRows = Object.entries(evidenceFinancials.final_bill_by_currency || {}).map(([code, value]) => `${code} ${this.formatMoney(value)}`);
    if (sourceOwned) {
      const sourceLabel = fee.source_label || "支付来源";
      const editor = this.materialFeeState?.freightEditor;
      const readonly = this.materialFeeState?.settlementData?.historical || this.detailState?.readOnly;
      return `<tr class="is-readonly" data-mf-source-fee="${this.escape(feeKey)}">
        <td><strong>${this.escape(feeLabel)}</strong><small>${this.escape(sourceLabel)} · 最终来源费用</small></td>
        <td><span class="ocw-mf-badge is-${amountInfo.tone}">${this.escape(amountInfo.label)}</span>${inclusionLabel ? `<small>${this.escape(inclusionLabel)}</small>` : ""}</td>
        <td><small>当前采用金额</small><strong>${this.escape(currency)} ${this.escape(fee.applied_amount ?? amount)}</strong><small>原始证据金额：${this.escape(currency)} ${this.escape(fee.original_amount ?? "待核对")}</small></td>
        <td><span>${this.escape(sourceLabel)}</span><small>${this.escape(fee.source_approval_no || "来源与更正记录可追溯")}</small></td>
        <td><div class="ocw-mf-row-actions">${readonly ? "" : ["amount", "replace", "revoke"].map((action, index) => `<button type="button" data-mf-freight-action="${action}" data-fee-key="${this.escape(feeKey)}" ${editor?.freightWriting ? "disabled" : ""}>${["改金额", "换来源", "撤销采用"][index]}</button>`).join("")}<button type="button" data-action="mf-view-settlement-source">查看支付来源与记录</button></div>
          <details class="ocw-mf-row-details"><summary>范围与分摊说明</summary><div><span>适用：${this.escape(scopeLabel)}</span><span>分摊：${this.escape(this.materialFeeBasisLabel(fee.allocation?.basis || fee.allocation_basis))}</span>${inclusionLabel ? `<span>${this.escape(inclusionLabel)}</span>` : ""}</div></details>
        </td>
      </tr>${this.renderMaterialFeeFreightEditor(feeKey)}`;
    }
    const statusOptions = [
      ["MISSING", "待补"], ["ESTIMATED", "暂估"], ["ACTUAL", "实际"],
      ["NOT_INCURRED", "未发生"], ["INCLUDED", "已包含"],
    ];
    return `
      <tr class="${[fee.legacy_unmapped || fee.requires_review ? "is-review" : "", aiFeeProposal ? "is-ai-draft" : ""].filter(Boolean).join(" ")}">
        <td><strong>${this.escape(fee.expense_category || fee.logical_fee_key || "--")}</strong><small>${fee.virtual ? "默认项 · 未入库" : fee.legacy_unmapped ? "历史费用 · 请核对" : "已保存"}</small>${mexicoEntry ? "<small>由墨西哥同事补充</small>" : ""}</td>
        <td><select data-mf-fee-status="1" data-fee-key="${this.escape(feeKey)}" data-original-value="${this.escape(amountStatus)}" aria-label="${this.escape(feeLabel)}状态">${statusOptions.map(([value, label]) => `<option value="${value}" ${value === amountStatus ? "selected" : ""}>${label}</option>`).join("")}</select>${inclusionLabel ? `<small>${this.escape(inclusionLabel)}</small>` : ""}</td>
        <td class="ocw-mf-fee-amount-cell ${inlineError ? "is-save-error" : ""}" ${inlineError ? `title="${this.escape(inlineError)}"` : ""}>
          <div class="ocw-mf-fee-inline-fields">
            ${aiFeeProposal
              ? `<select data-mf-ai-edit="1" data-proposal-id="${this.escape(aiFeeProposal.proposal_id || "")}" data-fieldname="currency" aria-label="AI 草稿 ${this.escape(feeLabel)}币种">${currencyOptions.map((option) => `<option value="${option.value}" ${option.value === currency ? "selected" : ""}>${option.label}</option>`).join("")}</select>
                 <input data-mf-ai-edit="1" data-proposal-id="${this.escape(aiFeeProposal.proposal_id || "")}" data-fieldname="amount" value="${this.escape(amount)}" inputmode="decimal" aria-label="AI 草稿 ${this.escape(feeLabel)}原币金额" />`
              : `<select data-mf-fee-input="currency" data-mf-fee-currency="1" data-fee-key="${this.escape(feeKey)}" data-original-value="${this.escape(this.normalizeMaterialFeeCurrency(fee.currency || "RMB"))}" aria-label="${this.escape(feeLabel)}币种" aria-invalid="${inlineError ? "true" : "false"}" aria-describedby="${this.escape(errorId)}">${supportedCurrency ? "" : `<option value="" selected disabled>请选择币种（原 ${this.escape(currency || "未设置")}）</option>`}${currencyOptions.map((option) => `<option value="${option.value}" ${option.value === currency ? "selected" : ""}>${option.label}</option>`).join("")}</select>
                 <input data-mf-fee-input="amount" data-mf-fee-amount="1" data-fee-key="${this.escape(feeKey)}" data-original-value="${this.escape(fee.amount ?? "")}" value="${this.escape(amount)}" ${forceActual ? 'data-mf-force-actual="1"' : ""} inputmode="decimal" aria-label="${this.escape(feeLabel)}原币金额" aria-invalid="${inlineError ? "true" : "false"}" aria-describedby="${this.escape(errorId)}" />`}
          </div>
          <small data-mf-fee-amount-hint="1">${aiFeeProposal ? "AI 草稿 · 确认所选草稿后才会保存" : defaultZero ? "默认暂估 0，待墨西哥确认" : missingSavedAmount ? "首次金额默认暂估" : "Enter 或失焦自动保存；状态可单独调整"}</small>
          <small id="${this.escape(errorId)}" class="ocw-mf-fee-inline-error-text ${inlineError ? "is-visible" : ""}" data-mf-fee-error="1">${this.escape(inlineError)}</small>
        </td>
        <td><span class="ocw-mf-badge is-${evidenceInfo.tone}">${this.escape(evidenceInfo.label)}</span><small>${evidenceAttachmentCount ? `${evidenceAttachmentCount} 份已关联` : "可上传或关联已有资料"}</small></td>
        <td><div class="ocw-mf-row-actions"><button type="button" data-action="mf-edit-fee" data-fee-key="${this.escape(fee.logical_fee_key || "")}">更多设置</button><button type="button" data-action="mf-link-evidence" data-fee-key="${this.escape(fee.logical_fee_key || "")}">关联并解析凭证</button></div>
          <details class="ocw-mf-row-details"><summary>范围与凭证详情</summary><div><span>适用：${this.escape(scopeLabel)}</span>${finalRows.length ? `<span>最终账单：${this.escape(finalRows.join("；"))}</span>` : ""}${settlementRows.length ? `<span>已付款净额：${this.escape(settlementRows.join("；"))}（不与账单重复计费）</span>` : ""}${evidence.length ? evidence.map((row) => `<span>${this.escape(row.evidence_role || "凭证")} · ${this.escape(row.evidence_type || "待分类")} · ${this.escape(row.currency || "")} ${this.escape(row.original_amount ?? "待补金额")}${row.related_evidence ? ` · 原付款 ${this.escape(row.related_evidence)}` : ""} · 终核状态：${this.escape(this.materialFeeEvidenceFinalLabel(row.validation_status))} <button type="button" data-action="mf-evidence-status" data-evidence-name="${this.escape(row.name || "")}" data-status="VALID">确认有效</button><button type="button" data-action="mf-evidence-status" data-evidence-name="${this.escape(row.name || "")}" data-status="INVALID">标记无效</button></span>`).join("") : "<span>暂无关联凭证</span>"}</div></details>
        </td>
      </tr>
    `;
  }

  materialFeeFreightEditorCurrent(editor) {
    return this.materialFeeState?.freightEditor === editor && this.detailState.batchName === editor.batchName
      && this.detailState.versionName === editor.versionName && this.detailState.tab === "documents";
  }

  renderMaterialFeeFreightSurface() {
    this.renderMaterialFeeWorkspacePreservingPosition();
  }

  async openMaterialFeeFreightEditor(feeKey, kind) {
    if (!["amount", "replace", "revoke"].includes(kind)) return;
    const state = this.ensureMaterialFeeState();
    if (state.freightEditor?.freightWriting) return;
    const fee = (state.fees?.fees || state.fees?.items || []).find(row => (row.logical_fee_key || row.fee_key) === feeKey);
    if (!fee?.source_binding_id) return;
    const editor = state.freightEditor = {feeKey, inline: true, batchName: state.batchName, versionName: this.detailState.versionName,
      freightLoading: true, freightWriting: false, freightError: "", data: {}, freightDraft: {}};
    this.renderMaterialFeeFreightSurface();
    try {
      const data = await this.call("overseas_costing.api.logistics_settlement.get_batch_settlement", {batch_name: editor.batchName, version_name: editor.versionName}, false);
      if (!this.materialFeeFreightEditorCurrent(editor)) return;
      if (!data?.ok) throw new Error(data?.message || "费用来源读取失败，请重试。");
      if (data.historical) throw new Error("历史版本仅供追溯，请返回当前调整草稿更正。");
      const claimId = String(fee.freight_claim_id || fee.source_binding_id);
      const claim = (data.freight?.claims || []).find(row => String(row.id) === claimId);
      if (!claim) throw new Error("当前费用来源已变化，请刷新费用清单后重试。");
      editor.data = data;
      state.settlementData = data;
      editor.freightView = {kind, claim_id: claim.id, expected_revision: data.freight.revision};
      editor.freightDraft = {amount: String(claim.applied_amount ?? claim.amount ?? ""), reason: "", candidate_id: "", line_ids: [], negative_confirmed: false};
    } catch (error) {
      if (this.materialFeeFreightEditorCurrent(editor)) editor.freightError = this.materialAIErrorMessage(error, "费用来源读取失败。");
    } finally {
      editor.freightLoading = false;
      if (this.materialFeeFreightEditorCurrent(editor)) this.renderMaterialFeeFreightSurface();
    }
  }

  renderMaterialFeeFreightEditor(feeKey) {
    const editor = this.materialFeeState?.freightEditor;
    if (!editor || editor.feeKey !== feeKey) return "";
    const busy = editor.freightLoading || editor.freightWriting;
    return `<tr class="ocw-mf-freight-editor-row" data-mf-freight-editor="${this.escape(feeKey)}"><td colspan="5"><div class="ocw-mf-freight-editor"><fieldset ${busy || editor.saved ? "disabled" : ""}>
      ${editor.freightLoading ? '<p role="status">正在读取本票费用来源…</p>' : editor.saved ? '<p>费用更正已保存。</p>' : editor.freightView ? this.renderFreightEditor(editor.data, editor) : ""}</fieldset>
      ${editor.freightError ? `<p class="ocw-mf-ai-review-error" role="alert">${this.escape(editor.freightError)}</p>` : ""}
      <div class="ocw-mf-row-actions"><button type="button" data-mf-freight-action="cancel" ${busy ? "disabled" : ""}>${editor.saved ? "关闭" : "取消"}</button>${editor.saved ? '<button type="button" data-mf-freight-action="refresh">重新读取已保存费用</button>' : editor.freightView ? `<button class="ocw-primary-btn" type="button" data-mf-freight-action="save" ${busy ? "disabled" : ""}>${editor.freightWriting ? "正在保存…" : {amount: "保存金额更正", replace: "保存并更换来源", revoke: "保存并撤销采用"}[editor.freightView.kind]}</button>` : ""}</div></div></td></tr>`;
  }

  updateMaterialFeeFreightDraft($input) {
    const editor = this.ensureMaterialFeeState().freightEditor;
    if (!editor || editor.freightWriting || editor.saved) return;
    const draft = editor.freightDraft;
    const field = $input.attr("data-freight-field");
    const lineId = $input.attr("data-freight-line");
    if (field) draft[field] = field === "negative_confirmed" ? Boolean($input.prop("checked")) : String($input.val() ?? "");
    if (lineId) draft.line_ids = $input.prop("checked") ? [...new Set([...(draft.line_ids || []), lineId])] : (draft.line_ids || []).filter(id => id !== lineId);
    editor.freightError = "";
    if (field === "candidate_id") { draft.line_ids = []; draft.negative_confirmed = false; this.renderMaterialFeeFreightSurface(); }
    else {
      const $host = this.$root.find("[data-mf-freight-editor]");
      if (!this.freightNeedsNegative(editor)) { draft.negative_confirmed = false; $host.find('[data-freight-field="negative_confirmed"]').prop("checked", false); }
      $host.find("[data-freight-negative]").prop("hidden", !this.freightNeedsNegative(editor));
      $host.find("[data-freight-summary]").html(this.renderFreightChangeSummary(editor));
      $host.find('[role="alert"]').text("");
    }
  }

  async refreshMaterialFeeFreightEditor() {
    const editor = this.ensureMaterialFeeState().freightEditor;
    if (!editor?.saved || editor.freightWriting || !this.materialFeeFreightEditorCurrent(editor)) return;
    editor.freightWriting = true;
    try {
      const loaded = await this.loadMaterialFeeWorkspace({quiet: true});
      if (loaded === false) throw new Error("请刷新重试");
      if (this.materialFeeState?.freightEditor === editor) this.materialFeeState.freightEditor = null;
    } catch (error) { editor.freightError = `已保存，新版本资料读取失败：${this.materialAIErrorMessage(error, "请刷新重试")}`; }
    finally { editor.freightWriting = false; if (this.detailState.batchName === editor.batchName) this.renderMaterialFeeFreightSurface(); }
  }

  async saveMaterialFeeFreightEditor() {
    const state = this.ensureMaterialFeeState();
    const editor = state.freightEditor;
    if (!editor || editor.freightLoading || editor.freightWriting || editor.saved) return;
    editor.freightError = "";
    const draft = editor.freightDraft;
    const view = editor.freightView;
    try {
      if (!this.materialFeeFreightEditorCurrent(editor)) throw new Error("当前批次或版本已变化，请重新打开费用更正。");
      if (editor.data.historical || !view) throw new Error("当前费用不可更正，请刷新后重试。");
      const reason = String(draft.reason || "").trim();
      if (!reason) throw new Error("请填写更正原因。");
      const args = {batch_name: editor.batchName, version_name: editor.versionName, claim_id: view.claim_id,
        expected_revision: view.expected_revision, action: view.kind, reason};
      if (view.kind === "amount") {
        if (String(draft.amount ?? "").trim() === "" || !Number.isFinite(Number(draft.amount))) throw new Error("请填写有效金额，可填 0。");
        args.amount = String(draft.amount).trim();
      } else if (view.kind === "replace") {
        const {candidate, lines} = this.freightSelectedLines(editor);
        if (!candidate || !lines.length) throw new Error("请选择新的来源及本票费用明细。");
        if (candidate.expense?.approved === false || lines.some(line => !line.available || line.adopted)) throw new Error("所选费用不可采用，请重新核对。");
        Object.assign(args, {candidate_id: candidate.id, candidate_revision: candidate.revision, line_ids: JSON.stringify(lines.map(line => line.id))});
      }
      if (this.freightNeedsNegative(editor) && draft.negative_confirmed !== true) throw new Error("请先确认已核对负数冲抵／折扣。");
      if (["amount", "replace"].includes(view.kind)) args.negative_confirmed = this.freightNeedsNegative(editor) && draft.negative_confirmed === true;
      editor.freightWriting = true;
      this.renderMaterialFeeFreightSurface();
      const result = await this.call("overseas_costing.api.logistics_settlement.amend_freight_claim", args, false);
      if (!this.materialFeeFreightEditorCurrent(editor)) return;
      if (!result?.ok) throw new Error(result?.message || "费用更正未保存，请重试。");
      editor.saved = true;
      this.updateMaterialFeeExpectedModified(result);
      const version = result.version || result.version_name;
      if (version) { editor.versionName = version; this.detailState.versionName = version; }
      // Invalidate old detail and fee reads before reading the newly created version.
      state.requestId += 1; state.feeRequestId += 1; state.settlementData = null;
      try {
        const loaded = await this.loadMaterialFeeWorkspace({quiet: true});
        if (loaded === false) throw new Error("请刷新重试");
        if (this.materialFeeState?.freightEditor === editor) state.freightEditor = null;
      } catch (error) { editor.freightError = `已保存，新版本资料读取失败：${this.materialAIErrorMessage(error, "请刷新重试")}`; }
    } catch (error) { editor.freightError = this.materialAIErrorMessage(error, "费用更正未保存，请重试。"); }
    finally { editor.freightWriting = false; if (this.detailState.batchName === editor.batchName) this.renderMaterialFeeFreightSurface(); }
  }

  materialFeeGridColumns() {
    const state = this.ensureMaterialFeeState();
    const compact = Boolean(globalThis.window?.matchMedia?.("(max-width: 1050px)")?.matches);
    const columns = [
      { field: "row_no", label: "行", readonly: true, width: 54 },
      { field: "source_doc_no", label: "采购审批号", readonly: true, width: 220 },
      { field: "material_code", label: "物料编码", readonly: true, width: 120 },
      { field: "product_name", label: "物料名称", readonly: true, width: 260 },
      { field: "quantity", label: "采购数量", readonly: true, numeric: true, width: 130 },
      { field: "actual_shipped_qty", label: "发货数量", numeric: true, width: 140 },
      { field: "shipped_uom", label: "发货单位", width: 130 },
      { field: "shipment_value_rmb", label: "本次发货货值 RMB", numeric: true, readonly: true, width: 160 },
      { field: "gross_weight_kg", label: "毛重 kg", numeric: true, width: 130 },
      { field: "volume_m3", label: "体积 m³", numeric: true, width: 130 },
      { field: "chargeable_weight_kg", label: "计费重 kg", numeric: true, width: 140 },
      { field: "project_collection", label: "项目归属", width: 180 },
    ];
    if (compact) [54, 190, 110, 220].forEach((width, index) => { columns[index].width = width; });
    if (state.showAuxiliary) {
      columns.push(
        { field: "goods_value", label: "原采购全额 RMB", numeric: true, purchaseField: true, width: 150 },
        { field: "net_weight_kg", label: "净重 kg", numeric: true, width: 130 },
        { field: "unit_price", label: "原币单价", numeric: true, purchaseField: true, width: 130 },
        { field: "purchase_uom", label: "采购单位", purchaseField: true, width: 120 },
        { field: "unit_price_uom", label: "计价单位", purchaseField: true, width: 120 },
        { field: "purchase_currency", label: "采购币种", purchaseField: true, options: this.materialFeeCurrencyOptions(), width: 130 },
        { field: "supplier", label: "供应商", readonly: true, width: 220 },
        { field: "source_file_name", label: "来源文件", readonly: true, width: 240 }
      );
    }
    return columns;
  }

  renderMaterialFeeGrid() {
    const state = this.ensureMaterialFeeState();
    const materialData = state.materials || {};
    const columns = this.materialFeeGridColumns();
    let items = materialData.items || [];
    items = this.materialReplacementRows(items);
    if (state.onlyMissing) items = items.filter((row) => row.__aiReplacement || (row.requirements?.missing_fields || []).length);
    const page = Number(materialData.page || state.page || 1);
    const pageCount = Math.max(1, Number(materialData.page_count || 1));
    const tableWidth = columns.reduce((sum, column) => sum + Number(column.width || 130), 0);
    return `
      <div class="ocw-mf-grid-shell">
        <div class="ocw-mf-grid-note"><span>${state.aiFill?.status === "READY" && state.aiFill?.draftVisible ? "AI 草稿中，单格修改只更新草稿" : "单格离开或按 Enter 自动保存"}</span><span>Tab 可连续操作</span><span>多格粘贴会先预览再整体确认</span><span>项目归属缺失不阻断试算</span></div>
        <div class="ocw-mf-grid-scroll" data-mf-grid-viewport>
          <table class="ocw-mf-grid-table" style="width:${tableWidth}px;min-width:${tableWidth}px">
            <colgroup>${columns.map((column) => `<col style="width:${Number(column.width || 130)}px">`).join("")}</colgroup>
            <thead><tr>${columns.map((column) => `<th>${this.escape(column.label)}</th>`).join("")}</tr></thead>
            <tbody>${items.length ? items.map((item, index) => item.__aiReplacement ? this.renderMaterialReplacementGridRow(item, columns, index) : this.renderMaterialFeeGridRow(item, columns, index)).join("") : `<tr><td class="ocw-mf-grid-empty" colspan="${columns.length}">${state.onlyMissing ? "当前页没有缺项" : "当前批次暂无物料行"}</td></tr>`}</tbody>
          </table>
        </div>
        <div class="ocw-mf-grid-scroll-controls"><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="mf-grid-scroll-left" aria-label="向左滚动">‹</button><div class="ocw-mf-grid-scrollbar" data-mf-grid-scrollbar><div style="width:${tableWidth}px"></div></div><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="mf-grid-scroll-right" aria-label="向右滚动">›</button></div>
        <div class="ocw-mf-grid-footer"><span>共 ${items.length !== (materialData.items || []).length ? `${items.length} 行（含 AI 临时明细）` : `${Number(materialData.total || 0)} 行`} · 当前第 ${page}/${pageCount} 页</span><div><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="mf-material-page" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>上一页</button><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="mf-material-page" data-page="${page + 1}" ${page >= pageCount ? "disabled" : ""}>下一页</button></div></div>
      </div>
    `;
  }

  materialReplacementRows(items = []) {
    const fill = this.ensureMaterialFeeState().aiFill;
    if (fill?.status !== "READY" || !fill.draftVisible || !fill.review_mode) return items;
    const replacements = new Map();
    (fill.proposals || []).filter((proposal) => proposal.proposal_type === "material_replace").forEach((proposal) => {
      const proposalId = String(proposal.proposal_id || "");
      const rows = fill.edits?.[proposalId]?.replacement_rows || proposal.payload?.replacement_rows || [];
      if (!proposal.target_item_name || !rows.length) return;
      replacements.set(String(proposal.target_item_name), { proposal, rows });
    });
    if (!replacements.size) return items;
    return items.flatMap((item) => {
      const replacement = replacements.get(String(item.name || ""));
      if (!replacement) return [item];
      return replacement.rows.map((row, rowIndex) => ({
        ...item,
        ...row,
        name: `ai:${replacement.proposal.proposal_id}:${rowIndex}`,
        row_no: `${item.row_no || ""}.${rowIndex + 1}`,
        material_code: "待建档",
        actual_shipped_qty: row.actual_shipped_qty ?? row.quantity,
        shipped_uom: row.shipped_uom || row.purchase_uom || item.shipped_uom,
        effective_shipping_quantity: row.actual_shipped_qty ?? row.quantity,
        effective_shipping_uom: row.shipped_uom || row.purchase_uom || item.shipped_uom,
        requirements: { missing_fields: [] },
        __aiReplacement: {
          proposalId: String(replacement.proposal.proposal_id || ""),
          rowIndex,
          originalItemName: String(item.name || ""),
        },
      }));
    });
  }

  renderMaterialReplacementGridRow(item, columns, rowIndex) {
    return `<tr class="is-ai-replacement" data-mf-row-index="${rowIndex}" data-item-name="${this.escape(item.name || "")}">${columns.map((column, columnIndex) => this.renderMaterialReplacementGridCell(item, column, columnIndex)).join("")}</tr>`;
  }

  renderMaterialReplacementGridCell(item, column, columnIndex) {
    const meta = item.__aiReplacement || {};
    const editable = new Set([
      "product_name", "spec_model", "quantity", "purchase_uom", "unit_price",
      "unit_price_uom", "purchase_currency", "goods_value", "actual_shipped_qty",
      "shipped_uom", "net_weight_kg", "gross_weight_kg", "volume_m3",
      "chargeable_weight_kg", "project_collection",
    ]);
    let fieldname = column.field;
    let value = item[fieldname];
    if (fieldname === "source_doc_no") value = item.source_doc_no || "原审批行";
    if (fieldname === "material_code") value = "待建档";
    if (fieldname === "actual_shipped_qty") value = item.actual_shipped_qty ?? item.quantity;
    if (fieldname === "shipped_uom") value = item.shipped_uom || item.purchase_uom;
    if (!editable.has(fieldname)) {
      return `<td class="ocw-mf-cell is-readonly is-ai-replacement" data-mf-column-index="${columnIndex}" title="AI 临时明细，确认后替换原模糊物料行"><span>${this.escape(this.formatValue(value || "--"))}</span></td>`;
    }
    return `<td class="ocw-mf-cell is-ai-draft is-ai-replacement" data-mf-column-index="${columnIndex}"><input data-mf-ai-edit="1" data-proposal-id="${this.escape(meta.proposalId || "")}" data-row-index="${Number(meta.rowIndex || 0)}" data-fieldname="${this.escape(fieldname)}" value="${this.escape(value ?? "")}" ${column.numeric ? 'inputmode="decimal"' : ""} aria-label="AI 临时明细 ${this.escape(column.label)}" /><small>AI 临时明细 · 可修改</small></td>`;
  }

  approvalLinkNeedsReview(link) {
    return Boolean(link?.status && link.status !== "linked");
  }

  renderApprovalLinkMarker(link) {
    if (!this.approvalLinkNeedsReview(link)) return "";
    return `<details class="ocw-approval-marker"><summary>${this.escape(link.label || "采购审批待核实")}</summary><div><p>${this.escape(link.reason || "请核对采购审批来源。")}</p>${link.approval_no ? `<p>审批号：${this.escape(link.approval_no)}</p>` : ""}${link.instance_id ? `<p>审批实例：${this.escape(link.instance_id)}</p>` : ""}</div></details>`;
  }

  renderMaterialFeeGridRow(item, columns, rowIndex) {
    const missingFields = new Set(item.requirements?.missing_fields || []);
    return `<tr class="${this.approvalLinkNeedsReview(item.approval_link) ? "ocw-approval-row" : ""}" data-mf-row-index="${rowIndex}" data-item-name="${this.escape(item.name || "")}">${columns.map((column, columnIndex) => this.renderMaterialFeeGridCell(item, column, missingFields, columnIndex)).join("")}</tr>`;
  }

  materialValueIsPlaceholder(fieldname, value, item = {}) {
    if (value === null || value === undefined) return true;
    const text = String(value).trim().replace(/\s+/g, " ").toLowerCase();
    if (["", "-", "--", "/", "\\", "n/a", "na", "null", "none", "无", "暂无"].includes(text)) return true;
    const zeroMissing = ["goods_value", "unit_price", "net_weight_kg", "gross_weight_kg", "volume_m3", "chargeable_weight_kg"];
    if (zeroMissing.includes(String(fieldname || "")) && Number(text) === 0) return true;
    if (fieldname === "actual_shipped_qty" && Number(text) === 0) {
      const mode = String(item.actual_shipped_qty_mode || item.effective_shipping?.mode || "").toUpperCase();
      return !["MANUAL_CONFIRMED", "EXPLICIT_SOURCE"].includes(mode);
    }
    return false;
  }

  materialPurchaseCorrectionFields() {
    return new Set(["goods_value", "unit_price", "purchase_currency", "purchase_uom", "unit_price_uom"]);
  }

  renderMaterialFeeGridCell(item, column, missingFields, columnIndex) {
    let value = item[column.field];
    if (item.source_adoption_state === "historical_pending" && ["material_code", "product_name"].includes(column.field)) {
      return `<td class="ocw-mf-cell is-readonly" data-mf-column-index="${columnIndex}"><span>${this.escape(value ?? "--")}</span><small>历史行 · 当前未采用</small></td>`;
    }
    if (item.adopted_price && ["unit_price", "purchase_currency", "unit_price_uom"].includes(column.field)) {
      const price = item.adopted_price;
      const current = { unit_price: price.value, purchase_currency: price.currency, unit_price_uom: price.unit }[column.field];
      return `<td class="ocw-mf-cell is-readonly" data-mf-column-index="${columnIndex}"><span>${this.escape(current ?? "待补")}</span><small>${price.error ? "商品价待核对" : price.source_type === "expense" ? "采购支出商品价" : "原商品采购价"}</small></td>`;
    }
    const shippingField = ["actual_shipped_qty", "shipped_uom"].includes(column.field);
    if (column.field === "actual_shipped_qty") value = item.effective_shipping_quantity;
    if (column.field === "shipped_uom") value = item.effective_shipping_uom;
    if (shippingField && item.settlement_cargo) {
      const rawPacking = [item.actual_shipped_qty ?? "未识别", item.shipped_uom || "单位待核对"].join(" ");
      return `<td class="ocw-mf-cell is-readonly ocw-mf-settlement-quantity" data-mf-column-index="${columnIndex}"><span>${this.escape(this.formatValue(value ?? "--"))}</span><small>${item.source_adoption_state === "historical_pending" ? "当前来源待补" : item.source_context?.packing?.selected_source ? "资料来源采用" : "采购支出采用"}</small>${column.field === "actual_shipped_qty" ? `<small>装箱原值 ${this.escape(rawPacking)}</small>` : ""}</td>`;
    }
    const originalValue = value;
    const draft = this.materialFeeState?.materialDrafts?.[`${item.name}:${column.field}`];
    if (draft && !column.readonly) value = draft.value;
    const aiFill = this.materialFeeState?.aiFill;
    const aiVisible = aiFill?.status === "READY" && aiFill.draftVisible;
    const aiCell = this.materialAICell(item.name, column.field);
    const aiUpdate = aiVisible ? aiFill.updates?.[`${item.name}:${column.field}`] : null;
    const manualUpdate = aiVisible ? aiFill.manualUpdates?.[`${item.name}:${column.field}`] : null;
    if (!column.readonly && aiUpdate) value = aiUpdate.value;
    if (!column.readonly && manualUpdate) value = manualUpdate.value;
    const isMissing = missingFields.has(column.field);
    const isDefault = shippingField && item.effective_shipping?.is_default;
    const requiresCorrection = Boolean(
      column.purchaseField
      && !this.materialValueIsPlaceholder(column.field, originalValue, item)
      && !draft
      && !aiUpdate
      && !manualUpdate
    );
    const classes = ["ocw-mf-cell", isMissing ? "is-missing" : "", isDefault ? "is-default" : "", column.readonly ? "is-readonly" : "", requiresCorrection ? "is-protected-purchase" : "", draft?.error ? "is-save-error" : "", aiUpdate || manualUpdate ? "is-ai-draft" : "", aiCell && !aiUpdate ? "has-ai-candidate" : ""].filter(Boolean).join(" ");
    const reason = draft?.error || (item.requirements?.field_reasons?.[column.field] || []).map((row) => row.message || row.code).join("；");
    if (column.readonly) {
      const fullValue = this.formatValue(value ?? "--");
      if (column.field === "shipment_value_rmb") {
        const valuation = item.shipment_valuation || {};
        const sourceLabel = valuation.error ? "估值待核对" : ["packing_row_total", "packing_unit_price"].includes(valuation.method)
          ? "装箱货值已取得" : valuation.method === "purchase_unit_price" ? "采购单价 × 本次发货数"
            : valuation.method === "settlement_expense_unit_price" ? "采购支出商品价 × 当前数量" : valuation.method === "settlement_purchase_unit_price" ? "原商品采购价 × 当前数量" : valuation.method === "LEGACY_PURCHASE" ? "历史采购口径" : "本次发货估值";
        return `<td class="${classes}" data-mf-column-index="${columnIndex}" title="${this.escape(valuation.error_detail || reason)}"><span>${this.escape(fullValue)}</span><small>${this.escape(sourceLabel)}</small></td>`;
      }
      return `<td class="${classes}" data-mf-column-index="${columnIndex}" title="${this.escape(column.field === "product_name" || column.field === "source_doc_no" ? fullValue : reason)}"><span>${this.escape(fullValue)}</span>${column.field === "source_doc_no" ? this.renderApprovalLinkMarker(item.approval_link) : ""}</td>`;
    }
    if (requiresCorrection) {
      return `<td class="${classes}" data-mf-column-index="${columnIndex}" title="已有有效采购值；修正时需填写原因"><span>${this.escape(this.formatValue(value ?? "--"))}</span><button type="button" class="ocw-mf-purchase-correct" data-action="mf-correct-purchase" data-item-name="${this.escape(item.name || "")}" data-fieldname="${this.escape(column.field)}">修正</button>${this.renderMaterialAICandidates(item.name, column.field, aiCell, false)}</td>`;
    }
    const editor = Array.isArray(column.options)
      ? `<select data-mf-cell-input="1" data-item-name="${this.escape(item.name || "")}" data-fieldname="${this.escape(column.field)}" data-original-value="${this.escape(originalValue ?? "")}" aria-label="${this.escape(column.label)}"><option value="">请选择</option>${column.options.map((option) => `<option value="${this.escape(option.value)}" ${String(value || "") === String(option.value) ? "selected" : ""}>${this.escape(option.label)}</option>`).join("")}</select>`
      : `<input data-mf-cell-input="1" data-item-name="${this.escape(item.name || "")}" data-fieldname="${this.escape(column.field)}" data-original-value="${this.escape(originalValue ?? "")}" value="${this.escape(value ?? "")}" ${column.numeric ? 'inputmode="decimal"' : ""} aria-label="${this.escape(column.label)}" />`;
    return `<td class="${classes}" data-mf-column-index="${columnIndex}" title="${this.escape(reason)}">${editor}${aiUpdate ? `<small>AI 草稿${aiUpdate.user_edited ? " · 已修改" : ""}</small>` : manualUpdate ? `<small>人工草稿</small>` : isDefault && column.field === "actual_shipped_qty" ? `<small>默认=采购数</small>` : ""}${this.renderMaterialAICandidates(item.name, column.field, aiCell, Boolean(aiUpdate))}</td>`;
  }

  materialAICell(itemName, fieldname) {
    const fill = this.ensureMaterialFeeState().aiFill;
    if (fill?.status !== "READY" || !fill.draftVisible) return null;
    return fill.draft?.rows?.[String(itemName)]?.[String(fieldname)] || null;
  }

  renderMaterialAICandidates(itemName, fieldname, cell, hasDraft) {
    const candidates = cell?.candidates || [];
    if (!candidates.length || (hasDraft && cell.status === "AI_DRAFT")) return "";
    const label = cell.status === "EXISTING_VALUE" ? "已有值 · 查看 AI" : `候选 ${candidates.length}`;
    return `<button type="button" class="ocw-mf-ai-candidate-trigger" data-action="mf-ai-open-candidate" data-item-name="${this.escape(itemName)}" data-fieldname="${this.escape(fieldname)}" aria-haspopup="dialog">${label}</button>`;
  }

  renderMaterialAICandidatePopoverContent(itemName, fieldname, cell) {
    const candidates = cell?.candidates || [];
    return `<header><strong>AI 候选详情</strong><button type="button" aria-label="关闭" data-action="mf-ai-close-candidate">×</button></header><div>${candidates.map((candidate, index) => `<article><span><b>${this.escape(this.formatValue(candidate.suggested_value))}</b><em>${Math.round(Number(candidate.confidence || 0) * 100)}%</em></span><p>${this.escape(candidate.reason || "待人工核对")}</p><p>${(candidate.source_refs || []).map((ref) => this.escape([ref.file, ref.sheet, ref.page ? `第 ${ref.page} 页` : "", ref.row ? `第 ${ref.row} 行` : "", ref.cell].filter(Boolean).join(" · "))).join("；") || "来源位置未标注"}</p><button type="button" class="ocw-outline-btn ocw-mini-btn" data-action="mf-ai-adopt-candidate" data-item-name="${this.escape(itemName)}" data-fieldname="${this.escape(fieldname)}" data-candidate-index="${index}">采用此值</button></article>`).join("")}</div>`;
  }

  openMaterialAICandidatePopover($trigger) {
    const itemName = String($trigger.attr("data-item-name") || "");
    const fieldname = String($trigger.attr("data-fieldname") || "");
    const cell = this.materialAICell(itemName, fieldname);
    if (!cell?.candidates?.length) return;
    const state = this.ensureMaterialFeeState();
    state.activeAICandidate = { itemName, fieldname };
    const $popover = this.$root.find("[data-mf-ai-candidate-popover]");
    if (!$popover.length) return;
    $popover.html(this.renderMaterialAICandidatePopoverContent(itemName, fieldname, cell)).prop("hidden", false);
    $popover.off("click.ocwMfCandidateClose").on("click.ocwMfCandidateClose", "[data-action='mf-ai-close-candidate']", () => this.closeMaterialAICandidatePopover());
    const trigger = $trigger.get(0);
    const popover = $popover.get(0);
    if (!trigger || !popover) return;
    const triggerRect = trigger.getBoundingClientRect();
    const viewportWidth = Number(window.innerWidth || document.documentElement.clientWidth || 0);
    const viewportHeight = Number(window.innerHeight || document.documentElement.clientHeight || 0);
    const margin = 10;
    const width = Math.min(340, Math.max(260, viewportWidth - margin * 2));
    $popover.css({ width: `${width}px`, left: `${Math.max(margin, Math.min(triggerRect.right - width, viewportWidth - width - margin))}px`, top: `${Math.min(viewportHeight - margin, triggerRect.bottom + 6)}px` });
    const popoverHeight = popover.getBoundingClientRect().height;
    const belowTop = triggerRect.bottom + 6;
    const aboveTop = triggerRect.top - popoverHeight - 6;
    const top = belowTop + popoverHeight <= viewportHeight - margin || aboveTop < margin ? belowTop : aboveTop;
    $popover.css("top", `${Math.max(margin, Math.min(top, viewportHeight - popoverHeight - margin))}px`);
  }

  closeMaterialAICandidatePopover() {
    const state = this.materialFeeState;
    if (state) state.activeAICandidate = null;
    const $popover = this.$root?.find?.("[data-mf-ai-candidate-popover]");
    if ($popover?.length) $popover.prop("hidden", true).empty();
  }

  renderMaterialAIFillBanner() {
    const fill = this.ensureMaterialFeeState().aiFill;
    if (!fill) return "";
    const steps = ["读取资料", "解析/OCR", "DeepSeek 识别", "合并候选"];
    const progress = Math.max(0, Math.min(100, Number(fill.progress_percent || 0)));
    const warning = fill.ai_warning || fill.error_message || "";
    const title = fill.status === "READY" ? "AI 资料审核草稿已生成" : fill.status === "FAILED" ? "AI 分析失败" : fill.status === "STALE" ? "AI 草稿已过期" : "正在分析当前批次资料";
    return `<div class="ocw-mf-ai-banner is-${this.escape(String(fill.status || "running").toLowerCase())}"><div><strong>${title}</strong><span>${this.escape(fill.progress_step || "读取资料")}</span></div><div class="ocw-mf-ai-progress" aria-label="AI 分析进度"><i style="width:${progress}%"></i></div><div class="ocw-mf-ai-steps">${steps.map((step) => `<span class="${step === fill.progress_step ? "active" : ""}">${step}</span>`).join("")}</div>${warning ? `<p>${this.escape(warning)}</p>` : ""}</div>`;
  }

  materialAIProgressStatus(value) {
    return {
      WAITING: { label: "等待", tone: "waiting" },
      DOWNLOADING: { label: "下载中", tone: "running" },
      READING: { label: "读取中", tone: "running" },
      PARSED: { label: "已解析", tone: "parsed" },
      ANALYZING: { label: "AI 分析中", tone: "running" },
      COMPLETED: { label: "已完成", tone: "complete" },
      PARTIAL: { label: "部分读取", tone: "partial" },
      FAILED: { label: "失败", tone: "failed" },
      SKIPPED: { label: "跳过", tone: "skipped" },
      EXCLUDED: { label: "已排除", tone: "skipped" },
      NO_RESULT: { label: "未产生结果", tone: "skipped" },
      NEEDS_SELECTION: { label: "待选择 Sheet", tone: "waiting" },
    }[String(value || "WAITING").toUpperCase()] || { label: String(value || "等待"), tone: "waiting" };
  }

  materialAISourceGroupKey(source, index = 0) {
    const kind = String(source?.source_kind || "unknown");
    const sourceId = String(source?.source_id || source?.source_key || source?.id || "").trim();
    const explicitParent = String(source?.parent_source_id || "").trim();
    const inferredParent = !explicitParent && /:sheet:[0-9a-f]{20,64}$/i.test(sourceId)
      ? sourceId.replace(/:sheet:[0-9a-f]{20,64}$/i, "")
      : "";
    const logicalSourceId = explicitParent || inferredParent || sourceId || `unidentified:${index}`;
    return {
      group_key: JSON.stringify([kind, logicalSourceId]),
      logical_source_id: logicalSourceId,
      source_kind: kind,
    };
  }

  materialAISourceSheetInfo(source) {
    const name = String(source?.sheet_name || source?.sheet || "").trim();
    const sourceId = String(source?.source_id || source?.source_key || source?.id || "").trim();
    return {
      name,
      is_sheet: Boolean(name || source?.parent_source_id || /:sheet:[0-9a-f]{20,64}$/i.test(sourceId)),
    };
  }

  materialAISourceGroups(sources) {
    const grouped = new Map();
    (Array.isArray(sources) ? sources : []).forEach((source, index) => {
      const identity = this.materialAISourceGroupKey(source, index);
      if (!grouped.has(identity.group_key)) grouped.set(identity.group_key, { ...identity, rows: [] });
      grouped.get(identity.group_key).rows.push(source);
    });
    return Array.from(grouped.values()).map((group) => {
      const sheetRows = group.rows.filter((source) => this.materialAISourceSheetInfo(source).is_sheet);
      const auditRows = sheetRows.length ? group.rows.filter((source) => {
        if (this.materialAISourceSheetInfo(source).is_sheet) return false;
        const readStatus = String(source?.read_status || "").toUpperCase();
        const status = String(source?.status || "").toUpperCase();
        return source?.selectable === false
          || source?.analysis_allowed === false
          || ["EXCLUDED", "NO_RESULT", "FAILED"].includes(readStatus)
          || ["EXCLUDED", "SKIPPED", "FAILED"].includes(status);
      }) : [];
      const contentRows = group.rows.filter((source) => !auditRows.includes(source));
      const failedRows = contentRows.filter((source) => String(source?.read_status || "").toUpperCase() === "FAILED"
        || String(source?.status || "").toUpperCase() === "FAILED");
      const successfulRows = contentRows.filter((source) => {
        const readStatus = String(source?.read_status || "").toUpperCase();
        const status = String(source?.status || "").toUpperCase();
        return !failedRows.includes(source) && (readStatus === "READ" || ["PARSED", "COMPLETED"].includes(status));
      });
      const readRows = successfulRows.filter((source) => {
        const readStatus = String(source?.read_status || "").toUpperCase();
        return readStatus === "READ" || !readStatus;
      });
      const activeRows = contentRows.filter((source) => ["WAITING", "DOWNLOADING", "READING", "ANALYZING"].includes(String(source?.status || "").toUpperCase()));
      const primary = readRows[0] || successfulRows[0] || activeRows[0] || failedRows[0] || contentRows[0] || group.rows[0] || {};
      let status = String(primary?.status || "WAITING").toUpperCase();
      let readStatus = String(primary?.read_status || "NO_RESULT").toUpperCase();
      if (successfulRows.length && failedRows.length && !activeRows.length) {
        status = "PARTIAL";
        readStatus = "PARTIAL";
      } else if (activeRows.length) {
        status = String(activeRows[0]?.status || "WAITING").toUpperCase();
      } else if (successfulRows.length) {
        status = successfulRows.some((source) => String(source?.status || "").toUpperCase() === "COMPLETED") ? "COMPLETED" : "PARSED";
        readStatus = readRows.length ? "READ" : String(primary?.read_status || "NO_RESULT").toUpperCase();
      } else if (failedRows.length) {
        status = "FAILED";
        readStatus = "FAILED";
      }
      const metricRows = sheetRows.length ? contentRows.filter((source) => this.materialAISourceSheetInfo(source).is_sheet) : contentRows;
      const sum = (name, fallback = "") => metricRows.reduce((total, source) => {
        const value = fallback && source?.[name] == null ? source?.[fallback] : source?.[name];
        const number = Number(value || 0);
        return total + (Number.isFinite(number) ? number : 0);
      }, 0);
      return {
        ...group,
        primary,
        label: String(primary?.label || group.rows[0]?.label || "未命名资料"),
        status,
        read_status: readStatus,
        sheet_names: [...new Set(sheetRows.map((source) => this.materialAISourceSheetInfo(source).name).filter(Boolean))],
        field_count: sum("field_count"),
        candidate_count: sum("candidate_count", "result_count"),
        result_count: sum("result_count", "candidate_count"),
        failed_count: failedRows.length,
        audit_count: auditRows.length,
        audit_rows: auditRows,
      };
    });
  }

  materialAISourceGroupSummary(groups) {
    const rows = Array.isArray(groups) ? groups : [];
    return {
      source_count: rows.length,
      failed_source_count: rows.filter((group) => ["FAILED", "PARTIAL"].includes(String(group?.status || "").toUpperCase())).length,
    };
  }

  renderMaterialAIProgressChip() {
    const fill = this.ensureMaterialFeeState().aiFill;
    const active = ["STARTING", "QUEUED", "RUNNING", "READY", "FAILED", "STALE"].includes(String(fill?.status || ""));
    const minimized = Boolean(this.ensureMaterialFeeState().aiProgressMinimized);
    const label = fill?.status === "READY"
      ? "AI 草稿待查看"
      : fill?.status === "FAILED"
        ? "AI 分析失败"
        : fill?.status === "STALE"
          ? "AI 草稿已过期"
          : `AI ${Math.max(0, Math.min(100, Number(fill?.progress_percent || 0)))}%`;
    return `<button class="ocw-mf-ai-progress-chip" type="button" data-action="mf-ai-progress-restore" data-mf-ai-progress-chip="1" ${active && minimized ? "" : "hidden"}><i></i><span>${this.escape(label)}</span></button>`;
  }

  renderMaterialAIProgressDialogContent() {
    const fill = this.ensureMaterialFeeState().aiFill || {};
    const progress = Math.max(0, Math.min(100, Number(fill.progress_percent || 0)));
    const sources = Array.isArray(fill.source_progress) ? fill.source_progress : [];
    const sourceGroups = this.materialAISourceGroups(sources);
    const sourceSummary = this.materialAISourceGroupSummary(sourceGroups);
    const summary = fill.completion_summary || {};
    const warning = this.materialAIProgressWarning(fill);
    const ready = fill.status === "READY";
    const failed = ["FAILED", "STALE"].includes(String(fill.status || ""));
    const canRetry = failed || Boolean(fill.stalled || fill.is_stalled || fill.connection_error || fill.polling_paused);
    const title = ready ? "AI 资料草稿已生成" : fill.polling_paused ? "AI 状态读取已暂停" : failed ? "AI 分析未完成" : "AI 正在分析当前批次资料";
    return `<div class="ocw-mf-ai-progress-dialog" data-mf-ai-progress-host="1">
      <header><div><strong data-mf-ai-progress-title>${this.escape(title)}</strong><span data-mf-ai-progress-step>${this.escape(fill.progress_step || "等待读取资料")}</span></div><b data-mf-ai-progress-percent>${progress}%</b></header>
      <main class="ocw-mf-ai-dialog-body">
      <div class="ocw-mf-ai-progress" aria-label="AI 分析进度"><i data-mf-ai-progress-bar style="width:${progress}%"></i></div>
      <div class="ocw-mf-ai-progress-summary">
        <span data-mf-ai-summary="source_count">资料 ${sourceSummary.source_count} 份</span>
        <span data-mf-ai-summary="material_proposal_count">物料 ${Number(summary.material_proposal_count || 0)} 项</span>
        <span data-mf-ai-summary="packing_proposal_count">装箱 ${Number(summary.packing_proposal_count || 0)} 项</span>
        <span data-mf-ai-summary="fee_proposal_count">费用 ${Number(summary.fee_proposal_count || 0)} 项</span>
        <span class="is-failed" data-mf-ai-summary="failed_source_count" ${sourceSummary.failed_source_count ? "" : "hidden"}>失败 ${sourceSummary.failed_source_count} 份</span>
      </div>
      <div class="ocw-mf-ai-source-progress" data-mf-ai-source-progress>${sourceGroups.map((group) => this.renderMaterialAIProgressSourceGroup(group)).join("")}<div class="ocw-mf-ai-progress-empty" data-mf-ai-progress-empty ${sourceGroups.length ? "hidden" : ""}>正在建立当前批次的资料清单…</div></div>
      <div class="ocw-mf-ai-progress-warning" data-mf-ai-progress-warning ${warning ? "" : "hidden"}>${this.escape(warning)}</div>
      </main>
      <footer class="ocw-mf-ai-dialog-footer">
        <button class="ocw-outline-btn" type="button" data-action="mf-ai-minimize">最小化</button>
        <div><button class="ocw-outline-btn" type="button" data-action="mf-ai-progress-retry" ${canRetry ? "" : "hidden"}>重试</button><button class="ocw-outline-btn" type="button" data-action="mf-ai-review-cancel">取消</button><button class="ocw-outline-btn" type="button" data-action="mf-ai-discard">放弃任务</button><button class="ocw-primary-btn" type="button" data-action="mf-ai-apply" disabled>确认填充</button></div>
      </footer>
    </div>`;
  }

  materialAIProgressSourceKey(source, index) {
    if (source?.group_key) return String(source.group_key);
    return this.materialAISourceGroupKey(source, index).group_key;
  }

  materialAIProgressSourceView(source) {
    const status = this.materialAIProgressStatus(source?.status);
    const location = [source?.sheet ? `Sheet ${source.sheet}` : "", Number(source?.page_count || 0) ? `${Number(source.page_count)} 页` : "", Number(source?.field_count || 0) ? `${Number(source.field_count)} 个字段` : ""].filter(Boolean).join(" · ");
    return {
      status,
      label: String(source?.label || "未命名资料"),
      detail: [source?.approval_no ? `审批 ${source.approval_no}` : "", source?.detail, location].filter(Boolean).join(" · ") || status.label,
      error: source?.error ? this.materialAIErrorMessage(source.error, "资料读取失败") : "",
      restriction: this.materialAISourceRestriction(source),
    };
  }

  renderMaterialAIProgressSourceRow(source, index) {
    const key = this.materialAIProgressSourceKey(source, index);
    const view = this.materialAIProgressSourceView(source);
    return `<article class="is-${view.status.tone}" data-mf-ai-source-key="${this.escape(key)}"><i></i><div><strong data-mf-ai-source-label>${this.escape(view.label)}</strong><span data-mf-ai-source-detail>${this.escape(view.detail)}</span><small data-mf-ai-source-restriction ${view.restriction ? "" : "hidden"}>${this.escape(view.restriction)}</small><small data-mf-ai-source-error ${view.error ? "" : "hidden"}>${this.escape(view.error)}</small></div><em data-mf-ai-source-status>${view.status.label}</em></article>`;
  }

  renderMaterialAIProgressSourceRecord(source, auditOnly = false) {
    const view = this.materialAIProgressSourceView(source);
    const sheet = this.materialAISourceSheetInfo(source);
    const identity = sheet.name ? `Sheet ${sheet.name}` : sheet.is_sheet ? "工作表记录" : "附件归档";
    return `<div class="ocw-mf-ai-source-record is-${view.status.tone}${auditOnly ? " is-audit" : ""}"><i></i><div><strong>${this.escape(identity)}</strong><span>${this.escape([source?.detail, Number(source?.field_count || 0) ? `${Number(source.field_count)} 个字段` : "", Number(source?.candidate_count || source?.result_count || 0) ? `${Number(source.candidate_count || source.result_count)} 个候选` : ""].filter(Boolean).join(" · ") || view.status.label)}</span>${view.error ? `<small>${this.escape(view.error)}</small>` : ""}</div><em>${view.status.label}</em>${auditOnly ? "<b>仅审计</b>" : ""}</div>`;
  }

  renderMaterialAIProgressSourceGroup(group) {
    const key = this.materialAIProgressSourceKey(group);
    const status = this.materialAIProgressStatus(group?.status);
    const primary = group?.primary || {};
    const sheets = Array.isArray(group?.sheet_names) ? group.sheet_names : [];
    const location = sheets.length === 1 ? `Sheet ${sheets[0]}` : sheets.length > 1 ? `${sheets.length} 个 Sheet` : "";
    const detail = [primary?.approval_no ? `审批 ${primary.approval_no}` : "", location, primary?.detail,
      Number(group?.field_count || 0) ? `${Number(group.field_count)} 个字段` : "",
      Number(group?.candidate_count || 0) ? `${Number(group.candidate_count)} 个候选` : "",
      group?.status === "PARTIAL" ? `${Number(group.failed_count || 0)} 个工作表读取失败` : "",
    ].filter(Boolean).join(" · ") || status.label;
    const restriction = this.materialAISourceRestriction(primary);
    const error = group?.status === "FAILED" && primary?.error ? this.materialAIErrorMessage(primary.error, "资料读取失败") : "";
    const rows = Array.isArray(group?.rows) ? group.rows : [];
    const auditRows = Array.isArray(group?.audit_rows) ? group.audit_rows : [];
    const records = rows.length > 1 ? `<details class="ocw-mf-ai-source-records" data-mf-ai-source-records><summary>同步记录 ${rows.length} 条${auditRows.length ? ` · ${auditRows.length} 条仅审计` : ""}</summary><div>${rows.map((source) => this.renderMaterialAIProgressSourceRecord(source, auditRows.includes(source))).join("")}</div></details>` : "";
    return `<article class="ocw-mf-ai-source-group is-${status.tone}" data-mf-ai-source-key="${this.escape(key)}"><i></i><div><strong data-mf-ai-source-label>${this.escape(group?.label || "未命名资料")}</strong><span data-mf-ai-source-detail>${this.escape(detail)}</span><small data-mf-ai-source-restriction ${restriction ? "" : "hidden"}>${this.escape(restriction)}</small><small data-mf-ai-source-error ${error ? "" : "hidden"}>${this.escape(error)}</small>${records}</div><em data-mf-ai-source-status>${status.label}</em></article>`;
  }

  updateMaterialAIProgressSources($host, sources) {
    const $list = $host.find("[data-mf-ai-source-progress]");
    if (!$list.length) return;
    const groups = this.materialAISourceGroups(sources);
    const scrollTop = $list.scrollTop();
    const remaining = new Map();
    $list.children("[data-mf-ai-source-key]").each((_index, element) => {
      const $row = $(element);
      remaining.set(String($row.attr("data-mf-ai-source-key") || ""), $row);
    });
    groups.forEach((group) => {
      const key = this.materialAIProgressSourceKey(group);
      let $row = remaining.get(key);
      if (!$row?.length) {
        $list.find("[data-mf-ai-progress-empty]").before(this.renderMaterialAIProgressSourceGroup(group));
        $row = $list.children("[data-mf-ai-source-key]").last();
      } else {
        remaining.delete(key);
        const wasOpen = Boolean($row.find("[data-mf-ai-source-records]").prop("open"));
        const $next = $(this.renderMaterialAIProgressSourceGroup(group));
        $row.replaceWith($next);
        $row = $next;
        if (wasOpen) $row.find("[data-mf-ai-source-records]").prop("open", true);
      }
    });
    remaining.forEach(($row) => $row.remove());
    $list.find("[data-mf-ai-progress-empty]").prop("hidden", Boolean(groups.length));
    $list.scrollTop(scrollTop);
  }

  openMaterialAIProgressDialog() {
    const state = this.ensureMaterialFeeState();
    if (!state.aiFill) return;
    state.aiProgressMinimized = false;
    if (!state.aiProgressDialog) {
      const dialog = new frappe.ui.Dialog({
        title: "自动填充资料",
        fields: [{ fieldtype: "HTML", fieldname: "progress_html", options: this.renderMaterialAIProgressDialogContent() }],
      });
      state.aiProgressDialog = dialog;
      dialog.show();
      dialog.$wrapper.addClass("ocw-mf-ai-progress-modal");
      dialog.$wrapper.off("click.ocwAIProgress").on("click.ocwAIProgress", "[data-action]", (event) => {
        const action = String($(event.currentTarget).attr("data-action") || "");
        if (action === "mf-ai-minimize") {
          state.aiProgressMinimized = true;
          dialog.hide();
          this.updateMaterialAIProgressSurface();
        } else if (action === "mf-ai-review-cancel") {
          state.aiProgressMinimized = false;
          if (state.aiFill) state.aiFill.reviewDialogVisible = false;
          dialog.hide();
        } else if (action === "mf-ai-discard") {
          this.discardMaterialAIFill().catch((error) => this.showError(error));
        } else if (action === "mf-ai-change-sources") {
          this.restartMaterialAIWithSources(dialog).catch((error) => this.showError(error));
        } else if (action === "mf-ai-apply") {
          this.applyMaterialAIFill().catch((error) => this.showError(error));
        } else if (action === "mf-ai-row-all" || action === "mf-ai-row-none") {
          this.changeMaterialAIRowSelection("rows", "all", action === "mf-ai-row-all");
        } else if (action === "mf-ai-row-preview") {
          this.previewMaterialAIRowSelection();
        } else if (action === "mf-ai-progress-retry") {
          this.retryMaterialAIProgress();
        }
      });
      dialog.$wrapper
        .off("change.ocwAIReview input.ocwAIReview")
        .on("change.ocwAIReview", "[data-mf-ai-row-select],[data-mf-ai-fee-select],[data-mf-ai-row-mode]", (event) => {
          const $input = $(event.currentTarget);
          if ($input.attr("data-mf-ai-row-mode") !== undefined) this.changeMaterialAIRowSelection("mode", $input.val());
          else this.changeMaterialAIRowSelection($input.attr("data-mf-ai-row-select") !== undefined ? "rows" : "fees", $input.attr("data-mf-ai-row-select") ?? $input.attr("data-mf-ai-fee-select"), $input.prop("checked"));
        })
        .on("change.ocwAIReview", "[data-mf-ai-proposal-select]", (event) => {
          const fill = state.aiFill;
          if (!fill?.selections) return;
          const proposalId = String($(event.currentTarget).attr("data-proposal-id") || "");
          const checked = $(event.currentTarget).prop("checked");
          const proposal = (fill.proposals || []).find((row) => String(row.proposal_id || "") === proposalId);
          if (checked && proposal?.conflict_group) {
            (fill.proposals || []).forEach((row) => {
              if (row.conflict_group === proposal.conflict_group) fill.selections.delete(String(row.proposal_id || ""));
            });
          }
          if (checked) fill.selections.add(proposalId);
          else fill.selections.delete(proposalId);
          this.renderMaterialAIReviewDialog();
        })
        .on("change.ocwAIReview", "[data-mf-ai-source-select]", (event) => {
          const fill = state.aiFill;
          const sourceId = String($(event.currentTarget).val() || "");
          const source = (fill?.source_progress || []).find((row) => String(row.source_id || "") === sourceId);
          if (this.materialAICanSelectSource(source)) {
            source.selected = Boolean($(event.currentTarget).prop("checked"));
          }
        })
        .on("input.ocwAIReview", "[data-mf-ai-edit]", (event) => {
          this.updateSourceAIReviewEdit($(event.currentTarget));
        });
    } else {
      state.aiProgressDialog.show();
      if (state.aiFill?.status !== "READY" && !state.aiProgressDialog.$wrapper.find("[data-mf-ai-progress-host]").length) {
        state.aiProgressDialog.$wrapper.removeClass("is-review");
        state.aiProgressDialog.fields_dict.progress_html.$wrapper.html(this.renderMaterialAIProgressDialogContent());
      }
    }
    this.updateMaterialAIProgressSurface();
    if (state.aiFill?.status === "READY") this.showMaterialAIReadyDraft();
  }

  updateMaterialAIProgressSurface() {
    const state = this.ensureMaterialFeeState();
    const $chip = this.$root?.find?.("[data-mf-ai-progress-chip]");
    const fill = state.aiFill || {};
    const active = ["STARTING", "QUEUED", "RUNNING", "READY", "FAILED", "STALE"].includes(String(fill.status || ""));
    const chipLabel = fill.status === "READY" ? "AI 草稿待查看" : fill.status === "FAILED" ? "AI 分析失败" : fill.status === "STALE" ? "AI 草稿已过期" : `AI ${Math.max(0, Math.min(100, Number(fill.progress_percent || 0)))}%`;
    if ($chip?.length) {
      $chip.prop("hidden", !(active && state.aiProgressMinimized));
      $chip.find("span").text(chipLabel);
    }
    const $button = this.$root?.find?.("[data-action='mf-ai-fill']");
    if ($button?.length) {
      const status = String(state.aiFill?.status || "");
      $button.text(status === "READY" ? "查看填充预览" : ["STARTING", "QUEUED", "RUNNING"].includes(status) ? "查看填充进度" : "自动填充资料");
    }
    const dialog = state.aiProgressDialog;
    if (dialog?.$wrapper?.length) {
      const $host = dialog.$wrapper.find("[data-mf-ai-progress-host]");
      if (!$host.length) return;
      const progress = Math.max(0, Math.min(100, Number(fill.progress_percent || 0)));
      const ready = fill.status === "READY";
      const failed = ["FAILED", "STALE"].includes(String(fill.status || ""));
      const title = ready ? "AI 资料草稿已生成" : fill.polling_paused ? "AI 状态读取已暂停" : failed ? "AI 分析未完成" : "AI 正在分析当前批次资料";
      const sources = Array.isArray(fill.source_progress) ? fill.source_progress : [];
      const sourceGroups = this.materialAISourceGroups(sources);
      const sourceSummary = this.materialAISourceGroupSummary(sourceGroups);
      const summary = fill.completion_summary || {};
      const warning = this.materialAIProgressWarning(fill);
      $host.find("[data-mf-ai-progress-title]").text(title);
      $host.find("[data-mf-ai-progress-step]").text(fill.progress_step || "等待读取资料");
      $host.find("[data-mf-ai-progress-percent]").text(`${progress}%`);
      $host.find("[data-mf-ai-progress-bar]").css("width", `${progress}%`);
      const labels = {
        source_count: `资料 ${sourceSummary.source_count} 份`,
        material_proposal_count: `物料 ${Number(summary.material_proposal_count || 0)} 项`,
        packing_proposal_count: `装箱 ${Number(summary.packing_proposal_count || 0)} 项`,
        fee_proposal_count: `费用 ${Number(summary.fee_proposal_count || 0)} 项`,
        failed_source_count: `失败 ${sourceSummary.failed_source_count} 份`,
      };
      Object.entries(labels).forEach(([key, label]) => $host.find(`[data-mf-ai-summary='${key}']`).text(label));
      $host.find("[data-mf-ai-summary='failed_source_count']").prop("hidden", !sourceSummary.failed_source_count);
      $host.find("[data-mf-ai-progress-warning]").text(warning).prop("hidden", !warning);
      $host.find("[data-action='mf-ai-progress-retry']").prop("hidden", !(failed || fill.stalled || fill.is_stalled || fill.connection_error || fill.polling_paused));
      this.updateMaterialAIProgressSources($host, sources);
    }
  }

  showMaterialAIReadyDraft() {
    const state = this.ensureMaterialFeeState();
    const ready = state.aiPendingReady || state.aiFill;
    if (ready?.status !== "READY") return;
    state.aiFill = ready.selections instanceof Set
      ? ready
      : this.initializeMaterialAIDraft({ ...ready, draftVisible: true });
    state.aiFill.draftVisible = !state.aiFill.row_review;
    state.aiFill.reviewDialogVisible = true;
    state.aiPendingReady = null;
    state.aiProgressMinimized = false;
    this.renderMaterialAIReviewDialog();
    if (state.aiFill.row_review && !state.aiFill.rowSelection?.preview && !state.aiFill.rowSelection?.loading) this.scheduleMaterialAIRowPreview();
  }

  materialAIReadStatusLabel(source) {
    return {
      READ: "已读取",
      PARTIAL: "部分读取",
      FAILED: "读取失败",
      NO_RESULT: "未产生结果",
      EXCLUDED: "已排除",
      NEEDS_SELECTION: "待选择 Sheet",
    }[String(source?.read_status || "NO_RESULT")] || "未产生结果";
  }

  materialAICanSelectSource(source) {
    return Boolean(source) && !source.locked && source.selectable !== false && source.analysis_allowed !== false;
  }

  materialAIAuditSourceRows(sources) {
    return new Set(this.materialAISourceGroups(sources).flatMap((group) => group.audit_rows || []));
  }

  materialAISelectedSourceIds(sources) {
    const rows = Array.isArray(sources) ? sources : [];
    const auditRows = this.materialAIAuditSourceRows(rows);
    return rows.filter((source) => !auditRows.has(source) && source.selected && this.materialAICanSelectSource(source))
      .map((source) => String(source.source_id || "")).filter(Boolean);
  }

  materialAISourceRestriction(source) {
    if (source?.analysis_allowed === false) return `不可分析：${source.analysis_reason || source.adoption_restriction || "当前资料不可用于分析"}`;
    if (source?.adoption_allowed === false) return `仅供分析：${source.adoption_restriction || "当前资料暂不能采用"}`;
    return String(source?.adoption_restriction || source?.analysis_reason || "");
  }

  renderMaterialAIReviewSources(fill) {
    const sources = Array.isArray(fill?.source_progress) ? fill.source_progress : [];
    const groups = this.materialAISourceGroups(sources);
    const order = { READ: 0, PARTIAL: 1, NEEDS_SELECTION: 2, NO_RESULT: 3, FAILED: 4, EXCLUDED: 5 };
    const cards = [...groups].sort((left, right) => (order[left.read_status] ?? 9) - (order[right.read_status] ?? 9)).map((group) => {
      const rows = Array.isArray(group.rows) ? group.rows : [];
      const auditRows = Array.isArray(group.audit_rows) ? group.audit_rows : [];
      const records = rows.map((source) => {
        const auditOnly = auditRows.includes(source);
        const sheet = this.materialAISourceSheetInfo(source);
        const identity = [sheet.name ? `Sheet ${sheet.name}` : sheet.is_sheet ? "工作表记录" : "附件归档", source.actor_name || "", source.occurred_at || ""].filter(Boolean).join(" · ");
        const canToggle = this.materialAICanSelectSource(source);
        const restriction = this.materialAISourceRestriction(source);
        const input = auditOnly ? "" : `<input type="checkbox" data-mf-ai-source-select="1" value="${this.escape(source.source_id || "")}" ${source.selected && source.analysis_allowed !== false ? "checked" : ""} ${canToggle ? "" : "disabled"}>`;
        return `<label class="ocw-mf-ai-review-source-record is-${String(source.read_status || "no_result").toLowerCase()}${auditOnly ? " is-audit" : ""}">${input}<span><strong>${this.escape(identity || this.materialAIReadStatusLabel(source))}</strong>${restriction ? `<small data-mf-ai-source-restriction>${this.escape(restriction)}</small>` : ""}${source.error ? `<em>${this.escape(this.materialAIErrorMessage(source.error, "资料读取失败"))}</em>` : ""}<i>${Number(source.result_count || source.candidate_count || 0)} 个候选 · ${this.escape(source.parse_method || "NONE")}</i></span>${auditOnly ? "<b>仅审计</b>" : source.locked ? "<b>锁定纳入</b>" : ""}</label>`;
      }).join("");
      return `<article class="ocw-mf-ai-review-source-group is-${String(group.read_status || "no_result").toLowerCase()}"><header><div><strong>${this.escape(group.label)}</strong><small>${this.escape(group.primary?.approval_no ? `审批 ${group.primary.approval_no}` : group.logical_source_id)}</small></div><b>${this.materialAIReadStatusLabel(group)}</b></header><details><summary>同步记录 ${rows.length} 条${auditRows.length ? ` · ${auditRows.length} 条仅审计` : ""}</summary><div>${records}</div></details></article>`;
    }).join("");
    return `<details class="ocw-mf-ai-review-sources"><summary>资料来源 <span>${groups.length} 份</span></summary><div>${cards || `<p>未找到可用资料来源。</p>`}</div></details>`;
  }

  renderCurrentSourceReviewControls(context = {}, cargo = null, { fees = false, values = {} } = {}) {
    if (context.root_kind !== "expense") return "";
    const cargoControl = cargo ? (cargo.complete
      ? `<label class="ocw-mf-review-choice"><input type="checkbox" data-source-review-complete ${values.complete_cargo ? "checked" : ""}><span>已核对完整货物表（${Number(cargo.row_count || cargo.rows?.length || 0)} 行），采用为本票最终 SKU 和数量</span></label>`
      : `<p class="ocw-mf-review-warning">${this.escape(cargo.reason || "货物清单完整性待核对，仅作为候选。")}</p>`) : "";
    const cargoRows = (cargo?.rows || []).map(row => `<tr>${[
      row.source_row, row.material_code, row.product_name,
      row.quantity ?? row.actual_shipped_qty, row.unit || row.shipped_uom,
      row.gross_weight_kg, row.volume_m3,
    ].map(value => `<td>${this.escape(value ?? "--")}</td>`).join("")}</tr>`).join("");
    const cargoTable = cargoRows ? `<p>本次来源货物清单（确认后按稳定行身份更新本票物料）</p><div style="max-height:260px;overflow:auto"><table class="table table-bordered"><thead><tr>${["原表行", "SKU", "品名", "数量", "单位", "毛重 kg", "体积 m³"].map(label => `<th>${label}</th>`).join("")}</tr></thead><tbody>${cargoRows}</tbody></table></div>` : "";
    const feeControls = fees ? `<p>本次费用明细须与采购支出总额核对一致；请选择它实际覆盖的费用。</p>${this.settlementCoverageOptions().map(([key, label]) => `<label class="ocw-mf-review-choice"><input type="checkbox" data-source-review-coverage="${key}" ${(values.coverage || []).includes(key) ? "checked" : ""}><span>${this.escape(label)}</span></label>`).join("")}<label class="ocw-mf-review-choice"><input type="checkbox" data-source-review-negative ${values.negative_confirmed ? "checked" : ""}><span>已核对本次负数、折扣或冲抵（如有）</span></label>` : "";
    return `<section class="ocw-mf-dialog-note" data-current-source-review><strong>采购支出资料采用</strong>${cargoTable}${cargoControl}${feeControls}<label>核对说明<input data-source-review-reason value="${this.escape(values.reason || "")}" placeholder="记录本次核对依据" maxlength="1000"></label></section>`;
  }

  collectCurrentSourceReviewControls($wrapper) {
    return {
      complete_cargo: $wrapper.find("[data-source-review-complete]").is(":checked"),
      coverage: $wrapper.find("[data-source-review-coverage]:checked").map((_, node) => $(node).attr("data-source-review-coverage")).get(),
      negative_confirmed: $wrapper.find("[data-source-review-negative]").is(":checked"),
      reason: String($wrapper.find("[data-source-review-reason]").val() || "").trim(),
    };
  }

  renderMaterialAIReviewDialogContent() {
    const fill = this.ensureMaterialFeeState().aiFill || {};
    if (fill.row_review) return this.renderMaterialAIRowReview(fill);
    const physical = this.materialAIPhysicalSummary(fill);
    const physicalSummary = physical.itemCount
      ? `<div class="ocw-mf-ai-physical-summary"><b>明细 ${physical.itemCount} 条</b><b>净重 ${this.escape(physical.netWeight)} kg</b><b>毛重 ${this.escape(physical.grossWeight)} kg</b></div>`
      : "";
    return `<div class="ocw-mf-ai-review-dialog" data-mf-ai-review-host="1"><header><div><strong>填充预览</strong><span>请核对物料和费用，确认后一次填充到当前批次。</span></div></header><main class="ocw-mf-ai-dialog-body">${physicalSummary}${fill.ai_warning ? `<div class="ocw-mf-ai-progress-warning">${this.escape(fill.ai_warning)}</div>` : ""}<div data-mf-ai-autofill-preview="1">${this.renderMaterialAIAutofillPreview(fill)}</div>${this.renderCurrentSourceReviewControls(fill.source_context || fill.draft?.source_context || {}, fill.draft?.cargo_review, { fees: (fill.proposals || []).some(p => p.proposal_type === "fee_update"), values: fill.edits?._source_review || {} })}<details class="ocw-mf-ai-review-advanced"><summary>高级：来源与其他方案</summary><div>${this.renderMaterialAIReviewSources(fill)}<button class="ocw-outline-btn" type="button" data-action="mf-ai-change-sources" ${fill.applying ? "disabled" : ""}>更换来源并重新生成</button>${this.renderSourceAIReviewProposals(true)}</div></details></main><footer class="ocw-mf-ai-dialog-footer"><span>确认前不会修改已保存数据</span><div><button class="ocw-outline-btn" type="button" data-action="mf-ai-review-cancel" ${fill.applying ? "disabled" : ""}>取消</button><button class="ocw-outline-btn" type="button" data-action="mf-ai-discard" ${fill.applying ? "disabled" : ""}>放弃草稿</button><button class="ocw-primary-btn" type="button" data-action="mf-ai-apply" ${this.canApplyMaterialAIFill(fill) ? "" : "disabled"}>${fill.applying ? "正在填充…" : "确认填充"}</button></div></footer></div>`;
  }

  ensureMaterialAIRowSelection(fill) {
    if (!fill.rowSelection) fill.rowSelection = {
      mode: "fill_missing",
      rows: new Set((fill.row_review.rows || []).filter(row => row.can_fill && row.default_selected).map(row => String(row.row_id))),
      fees: new Set((fill.row_review.fees || []).filter(fee => fee.can_apply && fee.default_selected).map(fee => String(fee.proposal_id))),
      request: 0, loading: false, preview: null, error: "", timer: null,
    };
    return fill.rowSelection;
  }

  materialAIRowSelectionKey(fill) {
    const selection = this.ensureMaterialAIRowSelection(fill);
    return JSON.stringify([this.detailState.batchName, this.detailState.versionName, fill.runId || fill.run_id,
      fill.row_review.fingerprint, selection.mode, [...selection.rows].sort(), [...selection.fees].sort()]);
  }

  changeMaterialAIRowSelection(kind, id, checked) {
    const fill = this.ensureMaterialFeeState().aiFill;
    if (!fill?.row_review || fill.applying || fill.discarding) return;
    const selection = this.ensureMaterialAIRowSelection(fill);
    const rows = fill.row_review.rows || [];
    if (kind === "mode") {
      if (!["fill_missing", "replace_all"].includes(id)) return;
      selection.mode = id;
      selection.rows.forEach(rowId => {
        const row = rows.find(item => String(item.row_id) === rowId);
        if (!row || !(id === "replace_all" ? row.can_replace : row.can_fill)) selection.rows.delete(rowId);
      });
    } else {
      const items = kind === "rows" ? rows : fill.row_review.fees || [];
      for (const item of items) {
        const itemId = String(kind === "rows" ? item.row_id : item.proposal_id);
        const allowed = kind === "fees" ? item.can_apply : selection.mode === "replace_all" ? item.can_replace : item.can_fill;
        if (id !== "all" && itemId !== id) continue;
        if (checked && allowed) selection[kind].add(itemId);
        else selection[kind].delete(itemId);
      }
    }
    this.scheduleMaterialAIRowPreview();
  }

  scheduleMaterialAIRowPreview() {
    const fill = this.ensureMaterialFeeState().aiFill;
    if (!fill?.row_review || fill.applying || fill.discarding) return;
    const selection = this.ensureMaterialAIRowSelection(fill);
    clearTimeout(selection.timer);
    selection.request += 1;
    selection.preview = null;
    selection.loading = true;
    selection.error = "";
    this.renderMaterialAIReviewDialog();
    selection.timer = setTimeout(() => {
      if (this.ensureMaterialFeeState().aiFill === fill) this.previewMaterialAIRowSelection();
    }, 180);
  }

  async previewMaterialAIRowSelection() {
    const state = this.ensureMaterialFeeState();
    const fill = state.aiFill;
    if (!fill?.row_review || fill.applying || fill.discarding) return;
    const selection = this.ensureMaterialAIRowSelection(fill);
    clearTimeout(selection.timer);
    const request = ++selection.request;
    const key = this.materialAIRowSelectionKey(fill);
    const current = () => this.materialFeeState === state && state.aiFill === fill && request === selection.request
      && key === this.materialAIRowSelectionKey(fill) && this.detailState.tab === "documents";
    const previous = selection.inFlight;
    let release;
    const inFlight = new Promise(resolve => { release = resolve; });
    selection.inFlight = inFlight;
    selection.preview = null; selection.loading = true; selection.error = "";
    this.renderMaterialAIReviewDialog();
    try {
      // Preserve server ordering. Intermediate queued selections exit before making a request.
      if (previous) await previous;
      if (!current()) return;
      const result = await this.call("overseas_costing.api.materials.preview_source_ai_selection", {
        batch_name: state.batchName, run_id: fill.runId || fill.run_id,
        row_ids_json: JSON.stringify([...selection.rows]), fee_ids_json: JSON.stringify([...selection.fees]),
        mode: selection.mode, expected_version: this.detailState.versionName || null,
      }, false);
      if (!current()) return;
      if (!result?.ok || !result.preview) throw new Error(result?.message || "未取得有效预览，请重新预览。");
      if (result.row_review) fill.row_review = result.row_review;
      // The server owns the final rows, counts and eligibility; never merge business values here.
      selection.preview = result.preview;
      selection.previewKey = this.materialAIRowSelectionKey(fill);
    } catch (error) {
      if (current()) selection.error = this.materialAIErrorMessage(error, "预览失败，请重试。");
    } finally {
      release();
      if (selection.inFlight === inFlight) selection.inFlight = null;
      if (this.materialFeeState === state && state.aiFill === fill && request === selection.request) {
        selection.loading = false;
        this.renderMaterialAIReviewDialog();
      }
    }
  }

  canConfirmMaterialAIRowSelection(fill) {
    const selection = this.ensureMaterialAIRowSelection(fill);
    return fill.status === "READY" && !this.isMaterialFeeCalculationBusy() && !fill.applying && !fill.discarding && !selection.loading
      && selection.preview?.can_apply === true && selection.previewKey === this.materialAIRowSelectionKey(fill)
      && (selection.mode !== "replace_all" || selection.rows.size > 0);
  }

  renderMaterialAIRowReview(fill) {
    const selection = this.ensureMaterialAIRowSelection(fill);
    const catalog = fill.row_review;
    const preview = selection.previewKey === this.materialAIRowSelectionKey(fill) ? selection.preview : null;
    const value = input => this.escape(input === null || input === undefined || input === "" ? "—" : input);
    const columns = [["material_code", "物料编码"], ["product_name", "物料名称"], ["quantity", "采购数量"], ["actual_shipped_qty", "实发数量"], ["shipped_uom", "单位"], ["package_count", "箱数"], ["net_weight_kg", "净重 kg"], ["gross_weight_kg", "毛重 kg"], ["volume_m3", "体积 m³"], ["project_collection", "项目归属"]];
    const cells = row => columns.map(([field]) => `<td>${value(row[field])}</td>`).join("");
    const busy = fill.applying || fill.discarding ? "disabled" : "";
    const missing = preview?.missing_fields || [];
    const missingCount = Array.isArray(missing) ? missing.length : Number(missing.count ?? missing) || Object.keys(missing).length;
    const notices = [...(preview?.unresolved || []), ...(Array.isArray(missing) ? missing : [])];
    return `<div class="ocw-mf-ai-review-dialog" data-mf-ai-review-host="1"><header><div><strong>填充预览</strong><span>逐行选择物料，费用单独选择；最终明细由服务器预览。</span></div></header>
      <main class="ocw-mf-ai-dialog-body"><section class="ocw-mf-ai-row-controls"><label>填充方式 <select data-mf-ai-row-mode ${busy}><option value="fill_missing" ${selection.mode === "fill_missing" ? "selected" : ""}>只补缺失（默认）</option><option value="replace_all" ${selection.mode === "replace_all" ? "selected" : ""}>按所选行替换整表</option></select></label><p>${selection.mode === "replace_all" ? "所选行将成为本票完整物料表。请勾选需要保留的当前已有行，至少选择一行。" : "只补真正缺失的字段；已填金额、数量和 0 值保留。新识别的物料行将新增。匹配不唯一的行需核对。"}</p></section>
      <section class="ocw-mf-ai-preview-section"><h4>物料行 <span>已选 ${selection.rows.size} / ${(catalog.rows || []).length}</span></h4><div class="ocw-mf-ai-row-toolbar"><button type="button" class="ocw-outline-btn" data-action="mf-ai-row-all" ${busy}>全选可用行</button><button type="button" class="ocw-outline-btn" data-action="mf-ai-row-none" ${busy}>全不选</button></div>
      <div class="ocw-mf-ai-preview-table"><table class="ocw-mf-ai-row-catalog"><thead><tr><th>选择</th><th>行来源</th>${columns.map(([, label]) => `<th>${label}</th>`).join("")}<th>核对提示</th></tr></thead><tbody>${(catalog.rows || []).map(row => {
        const allowed = selection.mode === "replace_all" ? row.can_replace : row.can_fill;
        const origin = row.origin === "current" ? "当前已有" : "本次识别";
        return `<tr class="${allowed ? "" : "is-review"}"><td><input type="checkbox" data-mf-ai-row-select="${this.escape(row.row_id)}" ${!allowed || fill.applying ? "disabled" : ""} ${selection.rows.has(String(row.row_id)) ? "checked" : ""} aria-label="选择 ${this.escape(row.values?.product_name || row.values?.material_code || row.row_id)}"></td><td>${origin}${row.label === "待核对" || row.blocked_reason && row.origin !== "current" ? "<small>待核对</small>" : ""}</td>${cells(row.values || {})}<td>${value(row.blocked_reason || row.label || "")}</td></tr>`;
      }).join("") || `<tr><td colspan="${columns.length + 3}">没有可选物料行</td></tr>`}</tbody></table></div></section>
      <section class="ocw-mf-ai-preview-section"><h4>费用 <span>已选 ${selection.fees.size} / ${(catalog.fees || []).length}</span></h4><div class="ocw-mf-ai-preview-table"><table class="ocw-mf-ai-fee-catalog"><thead><tr><th>选择</th><th>费用项目</th><th>采用金额</th><th>原金额</th><th>来源与说明</th></tr></thead><tbody>${(catalog.fees || []).map(fee => {
        const values = fee.payload || fee;
        return `<tr><td><input type="checkbox" data-mf-ai-fee-select="${this.escape(fee.proposal_id)}" ${!fee.can_apply || fill.applying ? "disabled" : ""} ${selection.fees.has(String(fee.proposal_id)) ? "checked" : ""} aria-label="选择费用 ${this.escape(values.expense_category || values.logical_fee_key || "")}"></td><td>${value(values.expense_category || values.logical_fee_key)}</td><td>${value(values.amount)} ${value(values.currency)}</td><td>${value(fee.previous_amount ?? values.previous_amount)}</td><td>${value(fee.blocked_reason || values.remark || values.source_label || fee.reason || "")}${!fee.can_apply ? "<small>只读 · 不可采用</small>" : ""}</td></tr>`;
      }).join("") || '<tr><td colspan="5">本次没有费用候选</td></tr>'}</tbody></table></div></section>
      <section class="ocw-mf-ai-preview-section" data-mf-ai-final-preview><h4>确认后物料清单</h4>${selection.loading ? '<p role="status">正在更新服务器预览…</p>' : preview ? `<p>最终 ${preview.rows?.length || 0} 行 · 新增 ${Number(preview.added_count || 0)} · 移除 ${Number(preview.removed_count || 0)} · 补充 ${Number(preview.updated_count || 0)} · 缺项 ${missingCount}</p><div class="ocw-mf-ai-preview-table"><table class="ocw-mf-ai-final-table"><thead><tr>${columns.map(([, label]) => `<th>${label}</th>`).join("")}</tr></thead><tbody>${(preview.rows || []).map(row => `<tr>${cells(row)}</tr>`).join("")}</tbody></table></div>` : '<p>等待服务器预览。</p>'}${notices.length ? `<ul>${notices.map(row => `<li>${this.escape(typeof row === "string" ? row : row.message || row.reason || row.fieldname || "待核对")}</li>`).join("")}</ul>` : ""}</section>
      ${selection.error ? `<p class="ocw-mf-ai-review-error" role="alert">${this.escape(selection.error)}</p>` : ""}
      <details class="ocw-mf-ai-review-advanced"><summary>资料来源与报价记录</summary>${this.renderMaterialAIReviewSources(fill)}${(catalog.fees || []).map(fee => this.renderSourceAIReviewAlternativeQuotes({...fee, proposal_type: "fee_update"})).join("")}<button class="ocw-outline-btn" type="button" data-action="mf-ai-change-sources" ${busy}>更换来源并重新生成</button></details></main>
      <footer class="ocw-mf-ai-dialog-footer"><span>确认前不会修改已保存数据</span><div><button class="ocw-outline-btn" type="button" data-action="mf-ai-review-cancel" ${busy}>取消</button><button class="ocw-outline-btn" type="button" data-action="mf-ai-discard" ${busy}>放弃草稿</button><button class="ocw-outline-btn" type="button" data-action="mf-ai-row-preview" ${selection.loading || fill.applying ? "disabled" : ""}>重新预览</button><button class="ocw-primary-btn" type="button" data-action="mf-ai-apply" ${this.canConfirmMaterialAIRowSelection(fill) ? "" : "disabled"}>${fill.applying ? "正在填充…" : "确认填充"}</button></div></footer></div>`;
  }

  async confirmMaterialAIRowSelection() {
    const state = this.ensureMaterialFeeState();
    const fill = state.aiFill;
    if (!fill?.row_review || !this.canConfirmMaterialAIRowSelection(fill)) return;
    const selection = fill.rowSelection;
    const key = this.materialAIRowSelectionKey(fill);
    const current = () => this.materialFeeState === state && state.aiFill === fill && key === this.materialAIRowSelectionKey(fill) && this.detailState.tab === "documents";
    fill.applying = true; selection.error = ""; this.updateMaterialFeeWriteControls(state); this.renderMaterialAIReviewDialog();
    try {
      if (!(await this.ensureEditSession()) || !current()) return;
      const result = await this.call("overseas_costing.api.materials.confirm_source_ai_selection", {
        batch_name: state.batchName, run_id: fill.runId || fill.run_id,
        preview_id: selection.preview.id, preview_revision: selection.preview.revision,
        edit_token: this.detailState.editToken, expected_modified: this.detailState.expectedModified,
      }, false);
      if (!current()) return;
      if (!result?.ok) throw new Error(result?.message || "填充未保存，请核对后重试。");
      this.updateMaterialFeeExpectedModified(result);
      if (result.version_name) this.detailState.versionName = result.version_name;
      state.requestId += 1; state.feeRequestId += 1;
      state.aiFill = null; state.aiPendingReady = null;
      state.aiProgressDialog?.hide(); state.aiProgressDialog = null;
      frappe.show_alert({ message: result.message || "所选资料已填充，请重新试算", indicator: "green" });
      await this.loadMaterialFeeWorkspace({ quiet: true });
    } catch (error) {
      if (current()) selection.error = this.materialAIErrorMessage(error, "填充未保存，请重试。");
    } finally { fill.applying = false; this.updateMaterialFeeWriteControls(state); if (current()) this.renderMaterialAIReviewDialog(); }
  }

  materialAIAutofillPreview(fill) {
    const state = this.ensureMaterialFeeState();
    const preview = fill?.draft?.autofill_preview;
    const proposals = fill?.proposals || [];
    const selected = (proposal) => fill.selections?.has(String(proposal.proposal_id || ""));
    let items = (preview?.items || state.materials?.items || []).map((row) => {
      let metadata = row.extra_json || {};
      if (typeof metadata === "string") {
        try { metadata = JSON.parse(metadata); } catch (_error) { metadata = {}; }
      }
      return { ...row, package_count: row.package_count ?? metadata?.logistics_row?.packing?.package_count };
    });
    let fees = (preview?.fees || []).map((row) => ({ ...row }));
    // The server preview contains default choices. Restore fields before applying changed choices.
    proposals.filter((proposal) => proposal.proposal_type === "item_update" && proposal.default_selected && !selected(proposal)).forEach((proposal) => {
      const row = items.find((item) => String(item.name || "") === String(proposal.target_item_name || ""));
      const original = (state.materials?.items || []).find((item) => String(item.name || "") === String(proposal.target_item_name || ""));
      if (!row) return;
      Object.keys(proposal.payload?.fields || {}).forEach((field) => {
        const change = (preview?.changes || []).find((change) => String(change.item_name || change.name || "") === String(row.name || "") && change.fieldname === field);
        if (change && Object.prototype.hasOwnProperty.call(change, "previous_value")) row[field] = change.previous_value;
        else if (original) row[field] = original[field];
      });
    });
    proposals.filter(selected).forEach((proposal) => {
      const edit = fill.edits?.[String(proposal.proposal_id || "")];
      if (proposal.proposal_type === "item_update") {
        const row = items.find((item) => String(item.name || "") === String(proposal.target_item_name || ""));
        if (row) Object.assign(row, edit || proposal.payload?.fields || {});
      } else if (proposal.proposal_type === "material_replace") {
        const replacementRows = edit?.replacement_rows || proposal.payload?.replacement_rows || [];
        items = items.flatMap((item) => String(item.name || "") === String(proposal.target_item_name || "") && replacementRows.length ? replacementRows.map((row) => ({ ...row })) : [item]);
      } else if (proposal.proposal_type === "fee_update") {
        const row = fees.find((fee) => String(fee.proposal_id || "") === String(proposal.proposal_id || ""));
        const values = { ...proposal.payload, ...edit, proposal_id: proposal.proposal_id };
        if (Object.prototype.hasOwnProperty.call(values, "expense_category")) values.fee_type = values.expense_category;
        if (row) Object.assign(row, values);
        else fees.push(values);
      }
    });
    fees = fees.filter((fee) => {
      const proposal = proposals.find((proposal) => String(proposal.proposal_id || "") === String(fee.proposal_id || ""));
      return !proposal || selected(proposal);
    });
    Object.values(fill.manualUpdates || {}).forEach((update) => {
      const row = items.find((item) => String(item.name || "") === String(update.item_name || ""));
      if (row) row[update.fieldname] = update.value;
    });
    const summaryStale = Object.keys(fill.manualUpdates || {}).length > 0 || Object.keys(fill.edits || {}).length > 0
      || proposals.some(proposal => Boolean(proposal.default_selected) !== Boolean(selected(proposal)));
    return { items, fees, notes: preview?.notes || [], project_summary: summaryStale ? [] : preview?.project_summary || [], summaryStale, unresolved: preview?.unresolved || [] };
  }

  renderMaterialAIAutofillPreview(fill) {
    const preview = this.materialAIAutofillPreview(fill);
    const columns = [["row_no", "行"], ["material_code", "物料编码"], ["product_name", "物料名称"], ["quantity", "采购数量"], ["actual_shipped_qty", "实发数量"], ["shipped_uom", "发运单位"], ["package_count", "箱数"], ["net_weight_kg", "净重 kg"], ["gross_weight_kg", "毛重 kg"], ["volume_m3", "体积 m³"], ["shipment_value_rmb", "本次发货货值 RMB"], ["project_collection", "项目归属"]];
    const value = (input) => this.escape(input === null || input === undefined || input === "" ? "—" : input);
    const money = (input) => {
      if (input === null || input === undefined || String(input).trim() === "") return "—";
      return Number.isFinite(Number(input)) ? Number(input).toFixed(2) : value(input);
    };
    if (preview.summaryStale) preview.unresolved = [...preview.unresolved, {message: "草稿选择或数据已修改，项目汇总已隐藏；确认填充后请重新试算。"}];
    const notes = preview.notes.length ? `<details class="ocw-mf-ai-review-notes"><summary>资料说明（已保留人工值与采购关联状态）</summary><ul>${preview.notes.map(note => `<li>${this.escape(note.message || "")}</li>`).join("")}</ul></details>` : "";
    return `${notes}${this.renderShipmentProjectSummary(preview.project_summary)}<section class="ocw-mf-ai-preview-section"><h4>物料明细 <span>${preview.items.length} 条</span></h4><div class="ocw-mf-ai-preview-table"><table><thead><tr>${columns.map(([, label]) => `<th>${label}</th>`).join("")}</tr></thead><tbody>${preview.items.map((row, index) => `<tr data-mf-ai-preview-item="${this.escape(row.name || row.stable_line_key || "")}">${columns.map(([field]) => `<td>${value(field === "row_no" ? row.row_no ?? index + 1 : row[field])}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${columns.length}">暂无可填充的物料明细。</td></tr>`}</tbody></table></div></section><section class="ocw-mf-ai-preview-section"><h4>费用</h4>${preview.fees.length ? `<div class="ocw-mf-ai-preview-table"><table><thead><tr><th>费用项目</th><th>填充金额</th><th>币种</th><th>原金额</th><th>金额变更</th><th>承运人 / 说明</th></tr></thead><tbody>${preview.fees.map((fee) => `<tr><td>${value(fee.fee_type || fee.expense_category || fee.logical_fee_key)}</td><td>${money(fee.amount)}</td><td>${value(fee.currency)}</td><td>${money(fee.previous_amount)}</td><td>${money(fee.previous_amount)} → ${money(fee.amount)} ${value(fee.currency)}</td><td>${value([fee.carrier, fee.remark].filter(Boolean).join(" · "))}</td></tr>`).join("")}</tbody></table></div>` : `<p class="ocw-mf-ai-preview-empty">本次没有费用变更。</p>`}</section>${preview.unresolved.length ? `<section class="ocw-mf-ai-preview-unresolved"><h4>仍需补充 / 核对</h4><ul>${preview.unresolved.map((row) => `<li>${this.escape(typeof row === "string" ? row : row.message || row.reason || "待核对")}</li>`).join("")}</ul></section>` : ""}`;
  }

  renderShipmentProjectSummary(projects = []) {
    if (!projects.length) return "";
    const fields = ["project_collection", "goods_value_rmb", "gross_weight_kg", "allocated_fees_rmb", "total_cost_rmb"];
    return `<section class="ocw-mf-ai-preview-section"><h4>项目汇总</h4><div class="ocw-mf-ai-preview-table"><table><thead><tr><th>项目归属</th><th>本次发货货值 RMB</th><th>毛重 kg</th><th>分摊费用 RMB</th><th>综合成本 RMB</th></tr></thead><tbody>${projects.map(row => `<tr>${fields.map(field => `<td>${this.escape(row[field] ?? "—")}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>`;
  }

  materialAIPhysicalSummary(fill) {
    const rows = this.materialAIAutofillPreview(fill).items;
    const compact = (value) => {
      const rounded = Math.round(Number(value || 0) * 1000000) / 1000000;
      return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(6);
    };
    return {
      itemCount: rows.length,
      netWeight: compact(rows.reduce((sum, row) => sum + (Number(row.net_weight_kg) || 0), 0)),
      grossWeight: compact(rows.reduce((sum, row) => sum + (Number(row.gross_weight_kg) || 0), 0)),
    };
  }

  renderMaterialAIReviewDialog() {
    const state = this.ensureMaterialFeeState();
    const dialog = state.aiProgressDialog;
    if (!dialog?.$wrapper?.length || state.aiFill?.status !== "READY") return;
    const scrollTop = dialog.$wrapper.find(".ocw-mf-ai-dialog-body").scrollTop?.() || 0;
    const tableScroll = [];
    dialog.$wrapper.find(".ocw-mf-ai-preview-table").each?.((index, element) => { tableScroll[index] = $(element).scrollLeft(); });
    dialog.$wrapper.addClass("is-review");
    dialog.fields_dict.progress_html.$wrapper.html(this.renderMaterialAIReviewDialogContent());
    dialog.$wrapper.find(".ocw-mf-ai-dialog-body").scrollTop?.(scrollTop);
    dialog.$wrapper.find(".ocw-mf-ai-preview-table").each?.((index, element) => { $(element).scrollLeft(tableScroll[index] || 0); });
  }

  updateMaterialAIReviewSelectionSurface() {
    const state = this.ensureMaterialFeeState();
    const fill = state.aiFill;
    const $wrapper = state.aiProgressDialog?.$wrapper;
    if (!$wrapper?.length || !fill) return;
    $wrapper.find("[data-mf-ai-proposal-select]").each((_index, node) => {
      const proposalId = String($(node).attr("data-proposal-id") || "");
      $(node).prop("checked", fill.selections.has(proposalId));
    });
    $wrapper.find("[data-mf-ai-autofill-preview]").html(this.renderMaterialAIAutofillPreview(fill));
    const physical = this.materialAIPhysicalSummary(fill);
    $wrapper.find(".ocw-mf-ai-physical-summary").html(`<b>明细 ${physical.itemCount} 条</b><b>净重 ${this.escape(physical.netWeight)} kg</b><b>毛重 ${this.escape(physical.grossWeight)} kg</b>`);
    $wrapper.find("[data-action='mf-ai-apply']")
      .prop("disabled", !this.canApplyMaterialAIFill(fill))
      .text(fill.applying ? "正在填充…" : "确认填充");
  }

  async restartMaterialAIWithSources(dialog) {
    const state = this.ensureMaterialFeeState();
    const sources = state.aiFill?.source_progress || [];
    const selectedSourceIds = this.materialAISelectedSourceIds(sources);
    state.aiPendingReady = null;
    dialog.$wrapper.removeClass("is-review");
    await this.startMaterialAIFill({ force: true, restart: true, selectedSourceIds });
  }

  sourceAIReviewProposalLabel(proposal) {
    return { logistics_reconcile: "同步物流审批明细", material_replace: "拆分临时物料", item_update: "补充物料字段", fee_update: "补充费用" }[proposal?.proposal_type] || "资料候选";
  }

  renderSourceAIReviewProposals(forDialog = false) {
    const fill = this.ensureMaterialFeeState().aiFill;
    if (!forDialog || fill?.status !== "READY" || !fill.draftVisible || !Array.isArray(fill.proposals)) return "";
    if (!fill.proposals.length) return `<div class="ocw-mf-ai-proposals is-empty">当前资料没有形成可保存候选，请补充说明或资料后重新分析。</div>`;
    return `<div class="ocw-mf-ai-proposals">${fill.proposals.map((proposal) => {
      const selected = fill.selections?.has(String(proposal.proposal_id || ""));
      const tone = proposal.conflict || Number(proposal.confidence || 0) < 0.9 ? "review" : "ready";
      const sources = (proposal.source_refs || []).map((ref) => {
        const source = (fill.source_progress || []).find((row) => String(row.label || "") === String(ref.file || "") && (!ref.sheet || String(row.sheet_name || row.sheet || "") === String(ref.sheet || ""))) || {};
        return [
          ref.file,
          ref.approval_no ? `审批 ${ref.approval_no}` : source.approval_no || source.source_context?.instance_id ? `审批 ${source.approval_no || source.source_context.instance_id}` : "",
          ref.sheet,
          ref.field,
          ref.row ? `第 ${ref.row} 行` : "",
          ref.cell,
          ref.actor_name || source.actor_name || "",
          ref.occurred_at || source.occurred_at || "",
        ].filter(Boolean).join(" · ");
      }).join("；");
      const origin = proposal.result_origin === "SYSTEM" ? "系统直读" : "AI 识别";
      return `<article class="is-${tone}">
        <header><label>${proposal.proposal_type === "logistics_reconcile" ? "" : `<input type="checkbox" data-mf-ai-proposal-select="1" data-proposal-id="${this.escape(proposal.proposal_id || "")}" ${selected ? "checked" : ""} />`}<strong>${this.escape(this.sourceAIReviewProposalLabel(proposal))}</strong></label><span>${this.escape(origin)} · ${Math.round(Number(proposal.confidence || 0) * 100)}%${proposal.recommended ? " · 推荐" : ""}</span></header>
        ${this.renderSourceAIReviewProposalFields(proposal)}
        ${this.renderSourceAIReviewAlternativeQuotes(proposal)}
        <details><summary>依据与说明</summary><p>${this.escape(proposal.reason || "待人工核对")}</p><p>${this.escape(sources || "来源位置未标注")}</p></details>
      </article>`;
    }).join("")}</div>`;
  }

  renderSourceAIReviewProposalFields(proposal) {
    if (proposal.proposal_type === "logistics_reconcile") return `<p>确认后按物流审批同步整表明细，预览见上方物料表。</p>`;
    if (String(proposal.target_item_name || "").startsWith("draft-")) return `<p>此行为待新增的物流明细，填充后可在物料表中补充资料。</p>`;
    const proposalId = String(proposal.proposal_id || "");
    const edit = this.ensureMaterialFeeState().aiFill?.edits?.[proposalId];
    if (proposal.proposal_type === "material_replace") {
      const rows = edit?.replacement_rows || proposal.payload?.replacement_rows || [];
      const fields = ["product_name", "spec_model", "quantity", "purchase_uom", "unit_price", "unit_price_uom", "purchase_currency", "goods_value"];
      const labels = { product_name: "物料名称", spec_model: "规格", quantity: "数量", purchase_uom: "单位", unit_price: "原币单价", unit_price_uom: "计价单位", purchase_currency: "币种", goods_value: "人民币货值" };
      return `<div class="ocw-mf-ai-replacement"><p>替换原行：${this.escape(proposal.target_item_name || "--")}</p>${rows.map((row, rowIndex) => `<div class="ocw-mf-ai-replacement-row">${fields.map((field) => `<label><span>${labels[field]}</span><input data-mf-ai-edit="1" data-proposal-id="${this.escape(proposalId)}" data-row-index="${rowIndex}" data-fieldname="${field}" value="${this.escape(row?.[field] ?? "")}" /></label>`).join("")}</div>`).join("")}</div>`;
    }
    const values = edit || (proposal.proposal_type === "item_update" ? proposal.payload?.fields : proposal.payload) || {};
    const fields = proposal.proposal_type === "fee_update"
      ? ["expense_category", "amount", "currency", "amount_status", "remark"]
      : Object.keys(values);
    const labels = { expense_category: "费用项目", amount: "原币金额", currency: "币种", amount_status: "状态", remark: "备注" };
    return `<div class="ocw-mf-ai-fields">${fields.map((field) => `<label><span>${this.escape(labels[field] || field)}</span><input data-mf-ai-edit="1" data-proposal-id="${this.escape(proposalId)}" data-fieldname="${this.escape(field)}" value="${this.escape(values[field] ?? "")}" /></label>`).join("")}</div>`;
  }

  renderSourceAIReviewAlternativeQuotes(proposal) {
    const quotes = proposal.proposal_type === "fee_update" && Array.isArray(proposal.alternatives)
      ? proposal.alternatives.filter((quote) => quote && typeof quote === "object" && !Array.isArray(quote)) : [];
    if (!quotes.length) return "";
    const value = (input) => this.escape(input === null || input === undefined || input === "" ? "—" : input);
    return `<section data-mf-ai-alternative-quotes="1"><h4>报价记录（只读）</h4><div class="ocw-mf-ai-preview-table"><table><thead><tr><th>承运人</th><th>报价金额</th><th>币种</th><th>单价</th><th>计价依据</th><th>来源与原文</th></tr></thead><tbody>${quotes.map((quote) => {
      const basis = { volume: "体积", weight: "重量" }[quote.pricing_basis] || quote.pricing_basis;
      const location = [quote.source_field, quote.evidence_line_no ? `第 ${quote.evidence_line_no} 行` : ""].filter(Boolean).join(" · ");
      return `<tr><td>${value(quote.carrier)}<small>${String(quote.carrier || "") === String(proposal.carrier || "") ? "审批采用" : "其他报价"}</small></td><td>${value(quote.amount)}</td><td>${value(quote.currency)}</td><td>${value(quote.unit_rate)}</td><td>${value(basis)}</td><td>${value(location)}<br>${value(quote.evidence_line || quote.source_value)}</td></tr>`;
    }).join("")}</tbody></table></div></section>`;
  }

  updateSourceAIReviewEdit($input) {
    const fill = this.ensureMaterialFeeState().aiFill;
    if (fill?.status !== "READY") return;
    const proposalId = String($input.attr("data-proposal-id") || "");
    const fieldname = String($input.attr("data-fieldname") || "");
    const proposal = (fill.proposals || []).find((row) => String(row.proposal_id) === proposalId);
    if (!proposal || !fieldname) return;
    if (proposal.proposal_type === "logistics_reconcile" || String(proposal.target_item_name || "").startsWith("draft-")) return;
    fill.edits = fill.edits || {};
    if (proposal.proposal_type === "material_replace") {
      if (!fill.edits[proposalId]) fill.edits[proposalId] = { replacement_rows: JSON.parse(JSON.stringify(proposal.payload?.replacement_rows || [])) };
      const rowIndex = Number($input.attr("data-row-index") || 0);
      fill.edits[proposalId].replacement_rows[rowIndex][fieldname] = String($input.val() ?? "");
    } else {
      if (!fill.edits[proposalId]) fill.edits[proposalId] = JSON.parse(JSON.stringify(proposal.proposal_type === "item_update" ? proposal.payload?.fields || {} : proposal.payload || {}));
      fill.edits[proposalId][fieldname] = String($input.val() ?? "");
    }
    if (proposal.conflict_group) {
      (fill.proposals || []).forEach((row) => {
        if (row.conflict_group === proposal.conflict_group) fill.selections.delete(String(row.proposal_id || ""));
      });
    }
    fill.selections.add(proposalId);
    this.updateMaterialAIReviewSelectionSurface();
  }

  renderMaterialAIFillFooter() {
    const fill = this.ensureMaterialFeeState().aiFill;
    if (fill?.status !== "READY" || !fill.draftVisible) return "";
    const updateCount = (fill.selections?.size ?? 0) + Object.keys(fill.manualUpdates || {}).length;
    const candidateCount = Number(fill.draft?.proposal_count || fill.draft?.candidate_count || 0);
    const mutating = Boolean(fill.applying || fill.discarding);
    return `<div class="ocw-mf-ai-footer"><span>AI 草稿 · 已选择 ${updateCount} 项${candidateCount ? ` · 共 ${candidateCount} 个提案` : ""}</span><div><button class="ocw-outline-btn" type="button" data-action="mf-ai-discard" ${mutating ? "disabled" : ""}>${fill.discarding ? "正在放弃…" : "放弃草稿"}</button><button class="ocw-primary-btn" type="button" data-action="mf-ai-apply" ${this.canApplyMaterialAIFill(fill) ? "" : "disabled"}>${fill.applying ? "正在保存…" : "确认所选草稿"}</button></div></div>`;
  }

  bindMaterialGridScrollControls() {
    const $viewport = this.$root.find("[data-mf-grid-viewport]");
    const $scrollbar = this.$root.find("[data-mf-grid-scrollbar]");
    if (!$viewport.length || !$scrollbar.length) return;
    let syncing = false;
    const sync = ($from, $to) => {
      if (syncing) return;
      syncing = true;
      $to.scrollLeft($from.scrollLeft());
      syncing = false;
    };
    $viewport.off(".ocwMfGrid").on("scroll.ocwMfGrid", () => {
      this.closeMaterialAICandidatePopover();
      sync($viewport, $scrollbar);
    });
    $scrollbar.off(".ocwMfGrid").on("scroll.ocwMfGrid", () => {
      this.closeMaterialAICandidatePopover();
      sync($scrollbar, $viewport);
    });
  }

  initializeMaterialAIDraft(status) {
    const fill = {
      ...status,
      runId: status.run_id,
      updates: {},
      manualUpdates: {},
      draft: status.draft || { rows: {} },
      proposals: status.proposals || status.draft?.proposals || [],
      selections: new Set((status.proposals || status.draft?.proposals || []).filter((proposal) => proposal.default_selected).map((proposal) => String(proposal.proposal_id))),
      edits: {},
      draftVisible: status.draftVisible !== false,
    };
    if (fill.row_review) {
      fill.draftVisible = false;
      this.ensureMaterialAIRowSelection(fill);
      return fill;
    }
    fill.proposals.filter((proposal) => proposal.proposal_type === "item_update" && proposal.default_selected).forEach((proposal) => {
      Object.entries(proposal.payload?.fields || {}).forEach(([fieldname, value]) => {
        fill.updates[`${proposal.target_item_name}:${fieldname}`] = {
          item_name: proposal.target_item_name,
          fieldname,
          value,
          proposal_id: String(proposal.proposal_id || ""),
          user_edited: false,
        };
      });
    });
    Object.entries(fill.draft.rows || {}).forEach(([itemName, fields]) => {
      Object.entries(fields || {}).forEach(([fieldname, cell]) => {
        if (cell?.status !== "AI_DRAFT" || !cell.can_auto_adopt) return;
        fill.updates[`${itemName}:${fieldname}`] = {
          item_name: itemName,
          fieldname,
          value: cell.value,
          user_edited: false,
        };
      });
    });
    return fill;
  }

  materialAIErrorPayload(error) {
    let payload = error?.responseJSON || error?.responseText || error?.xhr?.responseJSON || error?.xhr?.responseText || error;
    if (typeof payload === "string") {
      try { payload = JSON.parse(payload); } catch (_error) { return payload; }
    }
    if (payload?.message && typeof payload.message === "object") payload = payload.message;
    return payload;
  }

  materialAIErrorMessage(error, fallback = "AI 分析暂时不可用，请稍后重试。") {
    const payload = this.materialAIErrorPayload(error);
    if (!payload?.error?.reason && payload?.ok !== false) {
      const status = error?.status ?? error?.xhr?.status;
      if (status !== undefined) {
        const transportMessage = {
          0: "网络连接已中断，请检查连接后重试。",
          401: "登录已失效，请重新登录后重试。",
          403: "当前账号没有访问权限，请确认账号权限后重试。",
          408: "请求超时，请稍后重试。",
          502: "服务暂时不可用，请稍后重试。",
          503: "服务暂时不可用，请稍后重试。",
          504: "服务响应超时，请稍后重试。",
        }[Number(status)];
        if (transportMessage) return transportMessage;
      }
    }
    const readable = payload?.error?.reason || payload?.reason || payload;
    const message = String(this.normalizeErrorMessage?.(readable)
      || this.extractReadableError?.(readable)
      || (typeof readable === "string" ? readable : typeof readable?.message === "string" ? readable.message : "")).trim();
    if (/QueryDeadlockError|changed since last read|\(1020\)/i.test(message)) {
      return "任务状态正在同步，请稍后重试。";
    }
    if (!message || message === "操作失败" || /^\s*[\[{]/.test(message) || /\[object Object\]|Traceback|frappe\.exceptions/i.test(message)) return fallback;
    return message.slice(0, 500);
  }

  materialAIProgressWarning(fill) {
    const payload = this.materialAIErrorPayload(fill.request_error || fill);
    const detail = payload?.error || {};
    const message = this.materialAIErrorMessage(fill.connection_error || fill.ai_warning || fill.error_message || fill.request_error, "");
    return [message,
      detail.stage ? `环节：${detail.stage}` : "",
      detail.scope ? `范围：${detail.scope}` : "",
      detail.source_label || detail.source_id || detail.approval_no
        ? `来源：${[detail.source_label || detail.source_id, detail.approval_no ? `审批 ${detail.approval_no}` : ""].filter(Boolean).join(" · ")}` : "",
      detail.next_action ? `下一步：${detail.next_action}` : "",
      payload?.trace_id ? `参考编号：${payload.trace_id}` : "",
    ].filter(Boolean).join("\n");
  }

  materialAIRequestRetryable(error) {
    const payload = this.materialAIErrorPayload(error);
    if (payload?.ok === false || payload?.retryable === false || payload?.error?.retryable === false) return false;
    const status = error?.status ?? error?.xhr?.status;
    if (status !== undefined) return [0, 408, 502, 503, 504].includes(Number(status));
    const message = this.materialAIErrorMessage(error, "");
    return /network|fetch failed|failed to fetch|load failed|timeout|timed out|connection (?:failed|reset|lost|refused)|网络|连接中断|连接超时/i.test(message);
  }

  failMaterialAIProgress(error, fallback, { resumePolling = false } = {}) {
    const state = this.ensureMaterialFeeState();
    state.aiFill = {
      ...(state.aiFill || {}),
      status: resumePolling ? state.aiFill?.status || "RUNNING" : "FAILED",
      progress_step: resumePolling ? state.aiFill?.progress_step || "状态读取已暂停" : "分析未完成",
      error_message: this.materialAIErrorMessage(error, fallback),
      request_error: this.materialAIErrorPayload(error),
      connection_error: "",
      polling: false,
      polling_paused: resumePolling,
    };
    this.openMaterialAIProgressDialog();
    this.updateMaterialAIProgressSurface();
  }

  retryMaterialAIProgress() {
    const state = this.ensureMaterialFeeState();
    const fill = state.aiFill;
    const workerStalled = Boolean(fill?.stalled || fill?.is_stalled);
    if (state.aiPollRetryPromise && !workerStalled) return state.aiPollRetryPromise;
    if (fill?.runId && !workerStalled && !["READY", "FAILED", "STALE", "DISCARDED", "APPLIED"].includes(fill.status)) {
      const generation = state.aiRunGeneration = Number(state.aiRunGeneration || 0) + 1;
      fill.polling_paused = false;
      delete fill.connection_error;
      delete fill.error_message;
      delete fill.request_error;
      this.openMaterialAIProgressDialog();
      const polling = this.pollMaterialAIFill(state, this.detailState.batchName, this.detailState.versionName, fill.runId)
        .catch((error) => {
          if (this.materialFeeState === state && state.aiRunGeneration === generation) {
            this.failMaterialAIProgress(error, "AI 分析状态读取失败，请重试。", { resumePolling: true });
          }
        }).finally(() => {
          if (state.aiPollRetryPromise === polling) state.aiPollRetryPromise = null;
        });
      state.aiPollRetryPromise = polling;
      return polling;
    }
    state.aiStartPromise = null;
    state.aiPollRetryPromise = null;
    const options = { ...(state.aiStartOptions || {}) };
    // A failed start may have reached the server. Keep its key until a run is known.
    if (fill?.runId) {
      options.force = true;
      options.restart = true;
      delete options.request_id;
      delete options.requestPayload;
      if (fill?.source_progress?.length) options.selectedSourceIds = this.materialAISelectedSourceIds(fill.source_progress);
    }
    return this.startMaterialAIFill(options);
  }

  materialAINewRequestId() {
    if (globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID();
    return Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  startMaterialAIFill(options = {}) {
    const state = this.ensureMaterialFeeState();
    if (state.aiStartPromise) {
      this.openMaterialAIProgressDialog();
      return state.aiStartPromise;
    }
    const currentStatus = String(state.aiFill?.status || "");
    if (!options.restart && ["STARTING", "QUEUED", "RUNNING", "READY"].includes(currentStatus)) {
      this.openMaterialAIProgressDialog();
      return Promise.resolve();
    }
    state.aiStartOptions = { ...options, request_id: options.request_id || this.materialAINewRequestId(), ...(Array.isArray(options.selectedSourceIds) ? { selectedSourceIds: [...options.selectedSourceIds] } : {}) };
    state.aiFill = { status: "STARTING", progress_step: "正在启动分析任务", progress_percent: 0, progress_revision: 0, source_progress: state.aiFill?.source_progress || [] };
    state.aiPendingReady = null;
    state.aiProgressMinimized = false;
    const generation = state.aiRunGeneration = Number(state.aiRunGeneration || 0) + 1;
    this.openMaterialAIProgressDialog();
    const startPromise = this.runMaterialAIFillStart(state, state.aiStartOptions)
      .catch((error) => {
        if (this.materialFeeState === state && state.aiRunGeneration === generation) this.failMaterialAIProgress(error, "AI 分析任务启动失败，请稍后重试。");
      })
      .finally(() => {
        if (state.aiStartPromise === startPromise) state.aiStartPromise = null;
      });
    state.aiStartPromise = startPromise;
    return startPromise;
  }

  restartMaterialAIForChangedSources() {
    const state = this.ensureMaterialFeeState();
    if (state.aiProgressDialog) {
      state.aiProgressDialog.hide();
      state.aiProgressDialog = null;
    }
    state.aiFill = null;
    state.aiPendingReady = null;
    return this.startMaterialAIFill({ force: false });
  }

  async runMaterialAIFillStart(state, options = {}) {
    const generation = state.aiRunGeneration;
    const batchName = this.detailState.batchName;
    const versionName = this.detailState.versionName;
    const isCurrent = () => this.materialFeeState === state && state.aiRunGeneration === generation
      && this.detailState.batchName === batchName && this.detailState.versionName === versionName
      && this.detailState.tab === "documents";
    if (state.calculationWrite) await state.calculationWrite;
    while (state.pendingWrites.size) await Promise.all([...state.pendingWrites]);
    if (!isCurrent()) return;
    if (Object.keys(state.materialDrafts || {}).length || Object.keys(state.feeDrafts || {}).length || Object.keys(state.materialSaveErrors || {}).length) {
      throw new Error("当前页面有未保存修改，请先完成保存再分析资料。");
    }
    const requestId = options.request_id || this.materialAINewRequestId();
    let payload = options.requestPayload?.request_id === requestId ? { ...options.requestPayload } : null;
    if (!payload) {
      payload = {
        batch_name: batchName,
        version_name: versionName,
        request_id: requestId,
        ...(state.aiClarificationLoaded
          ? { expected_clarification_revision: state.aiClarificationRevision }
          : { clarification_text: state.aiClarification || "" }),
        force: options.force === true ? 1 : 0,
      };
      if (Array.isArray(options.selectedSourceIds)) {
        const currentSources = state.aiFill?.source_progress || [];
        const sources = new Map(currentSources.map((source) => [String(source.source_id || ""), source]));
        const auditRows = this.materialAIAuditSourceRows(currentSources);
        payload.selected_source_ids_json = JSON.stringify(options.selectedSourceIds.filter((id) => {
          const source = sources.get(String(id));
          return !source || (!auditRows.has(source) && this.materialAICanSelectSource(source));
        }));
      }
    }
    // Retry the exact request: note edits and source refreshes may happen while its response is missing.
    state.aiStartOptions = { ...options, request_id: requestId, requestPayload: { ...payload } };
    let started = null;
    let lastError = null;
    for (let attempt = 0; attempt < 3 && !started; attempt += 1) {
      if (!isCurrent()) return;
      try {
        started = await this.call("overseas_costing.api.materials.start_source_ai_review", { ...payload }, false, { inlineErrors: true });
        if (!isCurrent()) return;
        if (!started?.ok) throw started || new Error("AI 分析任务启动失败。");
      } catch (error) {
        if (!isCurrent()) return;
        if (!this.materialAIRequestRetryable(error)) throw error;
        started = null;
        lastError = error;
        state.aiFill = { ...state.aiFill, progress_step: attempt < 2 ? "连接中断，正在重试" : "启动请求未完成", connection_error: this.materialAIErrorMessage(error, "启动请求暂时失败，正在自动重试。") };
        this.updateMaterialAIProgressSurface();
        if (attempt < 2) await new Promise((resolve) => window.setTimeout(resolve, 700 * (attempt + 1)));
      }
    }
    if (!isCurrent()) return;
    if (!started && lastError) throw lastError;
    if (!started?.ok) throw started || new Error("AI 分析任务启动失败。");
    state.aiFill = { ...started, runId: started.run_id, status: started.status, progress_step: "读取资料", progress_percent: 5, progress_revision: Number(started.progress_revision || 0), source_progress: started.source_progress || state.aiFill?.source_progress || [], reused: Boolean(started.reused), reuse_reason: started.reuse_reason || "" };
    state.aiPendingReady = null;
    this.openMaterialAIProgressDialog();
    this.updateMaterialAIProgressSurface();
    const polling = this.pollMaterialAIFill(state, batchName, versionName, started.run_id);
    if (options.restart) {
      polling.catch((error) => {
        if (isCurrent()) this.failMaterialAIProgress(error, "AI 分析状态读取失败，请重试。", { resumePolling: true });
      });
      return;
    }
    await polling;
  }

  async pollMaterialAIFill(state, batchName, versionName, runId) {
    let failureCount = 0;
    const generation = state.aiRunGeneration;
    const isCurrent = () => this.materialFeeState === state
      && state.aiRunGeneration === generation
      && this.detailState.batchName === batchName
      && this.detailState.versionName === versionName
      && this.detailState.tab === "documents"
      && (!state.aiFill?.runId || state.aiFill.runId === runId);
    if (!isCurrent()) return;
    state.aiFill = { ...state.aiFill, runId, polling: true, polling_paused: false };
    try {
      for (let attempt = 0; attempt < 300; attempt += 1) {
        if (!isCurrent()) return;
        let status = null;
        try {
          status = await this.call("overseas_costing.api.materials.get_source_ai_review_status", {
            batch_name: batchName,
            run_id: runId,
            after_revision: Number(state.aiFill?.progress_revision || 0),
          }, false, { inlineErrors: true });
          if (!isCurrent()) return;
          if (!status?.ok) throw status || new Error("AI 分析状态读取失败。");
          failureCount = 0;
        } catch (error) {
          if (!isCurrent()) return;
          failureCount += 1;
          if (!this.materialAIRequestRetryable(error) || failureCount >= 3) {
            this.failMaterialAIProgress(error, "状态读取暂时中断，点击重试继续查看当前任务。", { resumePolling: true });
            return;
          }
          state.aiFill = { ...state.aiFill, connection_error: this.materialAIErrorMessage(error, "状态连接暂时中断，正在自动重试。") };
          this.updateMaterialAIProgressSurface();
          await new Promise((resolve) => window.setTimeout(resolve, Math.min(5000, 800 * failureCount)));
          continue;
        }
        const hadRequestError = Boolean(state.aiFill.connection_error || state.aiFill.request_error || state.aiFill.polling_paused);
        delete state.aiFill.connection_error;
        delete state.aiFill.request_error;
        delete state.aiFill.error_message;
        state.aiFill.polling_paused = false;
        if (status.unchanged) {
          if (hadRequestError) this.updateMaterialAIProgressSurface();
          await new Promise((resolve) => window.setTimeout(resolve, 1200));
          continue;
        }
        state.aiFill = { ...state.aiFill, ...status, runId, polling: true, draftVisible: false };
        if (status.status === "READY") {
          state.aiPendingReady = status;
          this.showMaterialAIReadyDraft();
        }
        this.updateMaterialAIProgressSurface();
        if (["READY", "FAILED", "STALE", "DISCARDED", "APPLIED"].includes(status.status)) return;
        await new Promise((resolve) => window.setTimeout(resolve, 1200));
      }
      if (isCurrent()) this.failMaterialAIProgress(new Error("状态读取等待时间较长，点击重试继续查看当前任务。"), undefined, { resumePolling: true });
    } finally {
      if (isCurrent()) state.aiFill.polling = false;
    }
  }

  updateMaterialAIDraftFromInput($input) {
    const itemName = String($input.attr("data-item-name") || "");
    const fieldname = String($input.attr("data-fieldname") || "");
    const value = String($input.val() ?? "").trim();
    const original = String($input.attr("data-original-value") ?? "").trim();
    return this.updateMaterialAIDraftValue(itemName, fieldname, value, original);
  }

  updateMaterialAIDraftValue(itemName, fieldname, value, original = "") {
    const fill = this.ensureMaterialFeeState().aiFill;
    if (fill?.status !== "READY") return false;
    if (String(itemName || "").startsWith("draft-")) return false;
    const key = `${itemName}:${fieldname}`;
    const proposalUpdate = fill.updates?.[key];
    if (fill.review_mode && proposalUpdate?.proposal_id) {
      const proposalId = String(proposalUpdate.proposal_id);
      const proposal = (fill.proposals || []).find((row) => String(row.proposal_id || "") === proposalId);
      if (!proposal) return false;
      fill.edits = fill.edits || {};
      if (!fill.edits[proposalId]) fill.edits[proposalId] = JSON.parse(JSON.stringify(proposal.payload?.fields || {}));
      fill.edits[proposalId][fieldname] = value;
      fill.selections.add(proposalId);
      fill.updates[key] = { ...proposalUpdate, value, user_edited: true };
      return true;
    }
    if (fill.review_mode) {
      fill.manualUpdates = fill.manualUpdates || {};
      if (value === original) delete fill.manualUpdates[key];
      else {
        const previous = fill.manualUpdates[key] || {};
        fill.manualUpdates[key] = {
          item_name: itemName,
          fieldname,
          value,
          reason: previous.reason || "",
        };
      }
      return true;
    }
    if (value === original) delete fill.updates[key];
    else fill.updates[key] = { item_name: itemName, fieldname, value, user_edited: true };
    return true;
  }

  adoptMaterialAICandidate(itemName, fieldname, candidateIndex) {
    const fill = this.ensureMaterialFeeState().aiFill;
    const cell = fill?.draft?.rows?.[String(itemName)]?.[String(fieldname)];
    const candidate = cell?.candidates?.[candidateIndex];
    if (!candidate) return;
    fill.updates[`${itemName}:${fieldname}`] = {
      item_name: String(itemName),
      fieldname: String(fieldname),
      value: candidate.suggested_value,
      user_edited: true,
    };
    this.renderMaterialFeeWorkspacePreservingPosition();
  }

  async applyMaterialAIFill() {
    const state = this.ensureMaterialFeeState();
    const fill = state.aiFill;
    if (fill?.row_review) return this.confirmMaterialAIRowSelection();
    if (!this.canApplyMaterialAIFill(fill)) return;
    const batchName = String(this.detailState.batchName || "");
    const versionName = String(this.detailState.versionName || "");
    const isCurrent = () => this.materialFeeState === state
      && state.aiFill === fill
      && String(this.detailState.batchName || "") === batchName
      && String(this.detailState.versionName || "") === versionName
      && this.detailState.tab === "documents";
    if (state.aiProgressDialog?.$wrapper?.find("[data-current-source-review]").length) {
      fill.edits = { ...(fill.edits || {}), _source_review: this.collectCurrentSourceReviewControls(state.aiProgressDialog.$wrapper) };
    }
    fill.applying = true;
    this.updateMaterialFeeWriteControls(state);
    this.renderMaterialAIReviewDialog();
    try {
      if (!(await this.ensureEditSession())) {
        fill.applying = false;
        if (isCurrent()) this.renderMaterialAIReviewDialog();
        return;
      }
      if (!isCurrent()) return;
      const result = await this.call("overseas_costing.api.materials.apply_source_ai_review", {
        batch_name: batchName,
        run_id: fill.runId || fill.run_id,
        selections_json: JSON.stringify(Array.from(fill.selections || [])),
        edits_json: JSON.stringify(fill.edits || {}),
        manual_updates_json: JSON.stringify(Object.values(fill.manualUpdates || {})),
        edit_token: this.detailState.editToken,
        expected_modified: this.detailState.expectedModified,
      });
      if (!isCurrent()) return;
      if (!result?.ok && result?.stale) {
        fill.applying = false;
        fill.status = "STALE";
        fill.error_message = result.message || "资料或物料数据已变化，请重新运行 AI 填充。";
        this.openMaterialAIProgressDialog();
        return;
      }
      if (!result?.ok) throw new Error(result?.message || "AI 草稿保存失败。 ");
      this.updateMaterialFeeExpectedModified(result);
      if (state.aiProgressDialog) {
        state.aiProgressDialog.hide();
        state.aiProgressDialog = null;
      }
      state.aiFill = null;
      frappe.show_alert({ message: result.message || "所选 AI 资料草稿已保存", indicator: "green" });
      await this.loadMaterialFeeWorkspace({ quiet: true });
    } catch (error) {
      fill.applying = false;
      if (!isCurrent()) return;
      this.renderMaterialAIReviewDialog();
      throw error;
    } finally {
      fill.applying = false;
      this.updateMaterialFeeWriteControls(state);
    }
  }

  async discardMaterialAIFill() {
    const state = this.ensureMaterialFeeState();
    const fill = state.aiFill;
    if (!fill || fill.applying || fill.discarding) return;
    const batchName = String(this.detailState.batchName || "");
    const versionName = String(this.detailState.versionName || "");
    const isCurrent = () => this.materialFeeState === state
      && state.aiFill === fill
      && String(this.detailState.batchName || "") === batchName
      && String(this.detailState.versionName || "") === versionName
      && this.detailState.tab === "documents";
    fill.discarding = true;
    if (fill.row_review) this.renderMaterialAIReviewDialog();
    else this.renderMaterialFeeWorkspace();
    try {
      const result = await this.call("overseas_costing.api.materials.discard_source_ai_review", {
        batch_name: batchName,
        run_id: fill.runId || fill.run_id,
      });
      if (!isCurrent()) return;
      if (!result?.ok) throw new Error(result?.message || "AI 草稿放弃失败。 ");
      state.aiFill = null;
      state.aiProgressDialog?.hide();
      state.aiProgressDialog = null;
      await this.loadMaterialFeeWorkspace({ quiet: true });
    } catch (error) {
      fill.discarding = false;
      if (!isCurrent()) return;
      if (fill.row_review) {
        this.ensureMaterialAIRowSelection(fill).error = this.materialAIErrorMessage(error, "草稿放弃失败，请重试。");
        this.renderMaterialAIReviewDialog();
        return;
      }
      this.renderMaterialFeeWorkspace();
      throw error;
    }
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

  applyMaterialFeeHeaderSnapshot(detail, batchName) {
    if (!detail || !detail.ok) throw new Error(detail?.message || "批次最新状态读取失败");
    const header = {
      ...(this.detailState.header || {}),
      ...(detail.header || {}),
      name: detail.batch_name || detail.header?.name || batchName,
      summary_snapshot: detail.summary || this.detailState.header?.summary_snapshot || {},
    };
    this.detailState.header = header;
    const batchIndex = (this.batches || []).findIndex((row) => row.name === batchName);
    if (batchIndex >= 0) this.batches[batchIndex] = { ...this.batches[batchIndex], ...header };
    this.detailState.versionName = detail.version_name || header.current_version || this.detailState.versionName || "";
    if (header.modified) this.detailState.expectedModified = header.modified;
  }

  async saveMaterialFeeCell($input) {
    return this.trackMaterialFeeWrite(() => this.persistMaterialFeeCell($input));
  }

  renderMaterialFeeWorkspacePreservingPosition() {
    const viewport = this.$root.find("[data-mf-grid-viewport]").get(0);
    const horizontal = viewport?.scrollLeft || 0;
    const scrollY = Number(globalThis.window?.scrollY || 0);
    this.renderMaterialFeeWorkspace();
    const restore = () => {
      const nextViewport = this.$root.find("[data-mf-grid-viewport]").get(0);
      if (nextViewport) nextViewport.scrollLeft = horizontal;
      if (globalThis.window?.scrollTo) globalThis.window.scrollTo({ top: scrollY, behavior: "instant" });
    };
    if (globalThis.window?.requestAnimationFrame) globalThis.window.requestAnimationFrame(restore);
    else restore();
  }

  openMaterialPurchaseCorrectionDialog(itemName, fieldname) {
    const item = this.findMaterialFeeItem(itemName);
    if (!item) {
      frappe.show_alert({ message: "物料行已变化，请刷新后重试", indicator: "red" });
      return;
    }
    const column = this.materialFeeGridColumns().find((entry) => entry.field === fieldname) || { label: fieldname };
    const valueField = column.options
      ? { fieldtype: "Select", fieldname: "value", label: column.label, options: column.options.map((option) => option.value).join("\n"), default: item[fieldname] || "" }
      : { fieldtype: column.numeric ? "Float" : "Data", fieldname: "value", label: column.label, default: item[fieldname] ?? "", reqd: 1 };
    const dialog = new frappe.ui.Dialog({
      title: `修正${column.label}`,
      fields: [
        valueField,
        { fieldtype: "Small Text", fieldname: "reason", label: "修改原因", reqd: 1, description: "将记录原值、新值、原因和操作者。" },
      ],
      primary_action_label: "保存修正",
      primary_action: async (values) => {
        const value = String(values.value ?? "").trim();
        const reason = String(values.reason || "").trim();
        if (!reason) return;
        const state = this.ensureMaterialFeeState();
        const key = `${itemName}:${fieldname}`;
        if (state.aiFill?.status === "READY" && state.aiFill.draftVisible) {
          state.aiFill.manualUpdates = state.aiFill.manualUpdates || {};
          state.aiFill.manualUpdates[key] = { item_name: itemName, fieldname, value, reason };
          dialog.hide();
          this.renderMaterialFeeWorkspacePreservingPosition();
          return;
        }
        if (!(await this.ensureMaterialFeeEditSession())) return;
        const result = await this.call("overseas_costing.api.calculate.update_item_field", {
          item_name: itemName,
          fieldname,
          value,
          version_name: this.detailState.versionName || null,
          remark: reason,
          edit_token: this.detailState.editToken,
          expected_modified: this.detailState.expectedModified,
        }, true);
        if (!result?.ok) throw new Error(result?.message || "采购字段修正失败");
        this.updateMaterialFeeExpectedModified(result);
        dialog.hide();
        frappe.show_alert({ message: "采购字段修正已保存", indicator: "green" });
        await this.loadMaterialFeeWorkspace({ quiet: true });
      },
    });
    dialog.show();
  }

  updateMaterialDraftFromInput($input) {
    const state = this.ensureMaterialFeeState();
    if (state.aiFill?.status === "READY" && state.aiFill.draftVisible) {
      this.updateMaterialAIDraftFromInput($input);
      return;
    }
    const itemName = $input.attr("data-item-name");
    const fieldname = $input.attr("data-fieldname");
    const key = `${itemName}:${fieldname}`;
    const value = String($input.val() ?? "").trim();
    const original = String($input.attr("data-original-value") ?? "").trim();
    if (state.materialDrafts[key]?.value !== value) state.inputRevision += 1;
    if (value === original) {
      delete state.materialDrafts[key];
      delete state.materialSaveErrors[key];
    } else {
      const previous = state.materialDrafts[key];
      state.materialDrafts[key] = { itemName, fieldname, value, error: previous?.value === value ? previous.error : "" };
    }
  }

  async persistMaterialFeeCell($input) {
    if (!$input.length || $input.data("saving")) return;
    if (this.ensureMaterialFeeState().aiFill?.status === "READY" && this.ensureMaterialFeeState().aiFill.draftVisible) {
      this.updateMaterialAIDraftFromInput($input);
      const $cell = $input.closest(".ocw-mf-cell");
      const key = `${$input.attr("data-item-name")}:${$input.attr("data-fieldname")}`;
      const fill = this.ensureMaterialFeeState().aiFill;
      const isDraft = Boolean(fill?.updates?.[key] || fill?.manualUpdates?.[key]);
      $cell.toggleClass("is-ai-draft", isDraft);
      return;
    }
    this.updateMaterialDraftFromInput($input);
    const original = String($input.attr("data-original-value") ?? "");
    const value = String($input.val() ?? "").trim();
    const itemName = $input.attr("data-item-name");
    const fieldname = $input.attr("data-fieldname");
    const saveState = this.ensureMaterialFeeState();
    const errorKey = `${itemName}:${fieldname}`;
    const $cell = $input.closest(".ocw-mf-cell");
    if (value === original) {
      delete saveState.materialSaveErrors[errorKey];
      $cell.removeClass("is-save-error").attr("title", "");
      return;
    }
    const batchName = this.detailState.batchName;
    const versionName = this.detailState.versionName;
    const isCurrent = () => this.materialFeeState === saveState
      && this.detailState.batchName === batchName
      && this.detailState.versionName === versionName
      && this.detailState.tab === "documents";
    const item = this.findMaterialFeeItem(itemName);
    $input.data("saving", true).prop("disabled", true);
    $cell.addClass("is-saving").removeClass("is-save-error");
    try {
      if (!item) throw new Error("物料行已变更，请刷新后重试。");
      if (!(await this.ensureMaterialFeeEditSession())) throw new Error("未能获取编辑权，物料未保存。");
      if (!isCurrent()) return;
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
      if (!isCurrent()) return;
      delete saveState.materialSaveErrors[errorKey];
      if (saveState.materialDrafts[errorKey]?.value === value) delete saveState.materialDrafts[errorKey];
      this.updateMaterialFeeExpectedModified(result);
      this.detailState.dirty = false;
      frappe.show_alert({ message: "已保存", indicator: "green" });
      await this.loadMaterialFeeWorkspace({ quiet: true });
    } catch (error) {
      if (!isCurrent()) return;
      saveState.materialSaveErrors[errorKey] = this.normalizeErrorMessage(error);
      if (saveState.materialDrafts[errorKey]) saveState.materialDrafts[errorKey].error = this.normalizeErrorMessage(error);
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
    const protectedPurchaseCorrections = [];
    const purchaseCorrectionFields = this.materialPurchaseCorrectionFields();
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
        if (
          purchaseCorrectionFields.has(column.field)
          && !this.materialValueIsPlaceholder(column.field, effectiveCurrent, this.findMaterialFeeItem(itemName) || {})
        ) {
          protectedPurchaseCorrections.push({ item_name: itemName, fieldname: column.field });
          return;
        }
        updates.push({ item_name: itemName, fieldname: column.field, value: String(value).trim(), old_value: effectiveCurrent, label: column.label });
      });
    });
    if (protectedPurchaseCorrections.length) {
      frappe.show_alert({ message: "粘贴内容包含已有有效采购值，请在对应单元格使用“修正”并填写原因。", indicator: "orange" });
      return;
    }
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
    const fill = this.ensureMaterialFeeState().aiFill;
    if (fill?.status === "READY" && fill.draftVisible) {
      updates.forEach(({ item_name, fieldname, value, old_value }) => {
        this.updateMaterialAIDraftValue(
          String(item_name || ""),
          String(fieldname || ""),
          String(value ?? "").trim(),
          String(old_value ?? "").trim()
        );
      });
      dialog.hide();
      this.renderMaterialFeeWorkspace();
      frappe.show_alert({ message: `已更新 ${updates.length} 个 AI 草稿单元格`, indicator: "blue" });
      return;
    }
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

  materialFeeErrorId(feeKey) {
    const safeKey = String(feeKey || "fee").replace(/[^A-Za-z0-9_-]/g, (character) => `_${character.charCodeAt(0)}_`);
    return `ocw-mf-fee-error-${safeKey}`;
  }

  restoreMaterialFeeInputFocus() {
    const state = this.ensureMaterialFeeState();
    const focused = state.focusedFeeInput;
    const material = state.focusedMaterialInput;
    if ((!focused?.feeKey || !focused?.field) && !material?.itemName) return;
    let target = null;
    this.$root.find(material?.itemName ? "[data-mf-cell-input]" : "[data-mf-fee-input]").each((_, element) => {
      if (target) return;
      const $element = $(element);
      if (material?.itemName) {
        if ($element.attr("data-item-name") === material.itemName && $element.attr("data-fieldname") === material.fieldname) target = element;
      } else if (
        String($element.attr("data-fee-key") || "") === String(focused.feeKey)
        && String($element.attr("data-mf-fee-input") || "") === String(focused.field)
      ) target = element;
    });
    if (!target) return;
    target.focus();
    if (typeof target.setSelectionRange === "function") {
      const position = String(target.value ?? "").length;
      target.setSelectionRange(position, position);
    }
  }

  clearMaterialFeeEditSession() {
    if (!this.detailState) return;
    const clearIntervalFn = globalThis.window?.clearInterval || globalThis.clearInterval;
    if (this.detailState.renewTimer && clearIntervalFn) clearIntervalFn(this.detailState.renewTimer);
    this.detailState.renewTimer = null;
    this.detailState.editToken = "";
    this.detailState.editExpiresAt = "";
  }

  materialFeeEditSessionExpired() {
    if (!this.detailState?.editToken || !this.detailState?.editExpiresAt) return false;
    const expiresAt = Date.parse(this.detailState.editExpiresAt);
    return Number.isFinite(expiresAt) && expiresAt <= Date.now() + 1000;
  }

  async ensureMaterialFeeEditSession() {
    if (this.materialFeeEditSessionExpired()) this.clearMaterialFeeEditSession();
    if (this.detailState?.editToken) return true;
    const state = this.ensureMaterialFeeState();
    if (state.editSessionPromise) return state.editSessionPromise;
    const promise = (async () => Boolean(await this.ensureEditSession()))();
    state.editSessionPromise = promise;
    try {
      return await promise;
    } finally {
      if (state.editSessionPromise === promise) state.editSessionPromise = null;
    }
  }

  materialFeeEditSessionInvalid(error) {
    const message = String(this.normalizeErrorMessage ? this.normalizeErrorMessage(error) : error?.message || error || "");
    return /(?:编辑权|编辑会话|租约|token).*(?:失效|过期|无效|不存在)|(?:失效|过期|无效).*(?:编辑权|编辑会话|租约|token)|当前批次正在被.*编辑/i.test(message);
  }

  updateMaterialFeeDraftFromInput($input) {
    if (!$input?.length) return null;
    const $cell = $input.closest(".ocw-mf-fee-amount-cell");
    const $amount = $cell.find("[data-mf-fee-amount]");
    const $currency = $cell.find("[data-mf-fee-currency]");
    const feeKey = String($input.attr("data-fee-key") || "");
    const state = this.ensureMaterialFeeState();
    state.feeDrafts = state.feeDrafts || {};
    const previous = state.feeDrafts[feeKey] || {};
    const rawCurrency = String($currency.val() ?? "");
    const currency = this.normalizeMaterialFeeCurrency(rawCurrency);
    if (currency !== rawCurrency) $currency.val(currency);
    const draft = {
      ...previous,
      amount: String($amount.val() ?? ""),
      currency,
      forceActual: previous.forceActual || $amount.attr("data-mf-force-actual") === "1",
      touched: true,
    };
    state.feeDrafts[feeKey] = draft;
    if (previous.amount !== draft.amount || previous.currency !== draft.currency) state.inputRevision += 1;
    if (draft.error) {
      const validationError = this.validateMaterialFeeInlineDraft(draft);
      this.setMaterialFeeInlineError($cell, feeKey, validationError);
    }
    return draft;
  }

  validateMaterialFeeInlineDraft(draft) {
    const amountText = String(draft?.amount ?? "").trim();
    if (!amountText) return "费用金额不能为空。";
    const amount = Number(amountText);
    if (!Number.isFinite(amount)) return "费用金额必须是有限数值。";
    if (amount < 0) return "费用金额不能小于 0。";
    const currency = String(draft?.currency ?? "");
    if (!currency) return "费用币种不能为空。";
    if (!this.materialFeeCurrencyOptions().some((option) => option.value === currency)) return "费用币种只能选择人民币、比索或美金。";
    return "";
  }

  setMaterialFeeInlineError($cell, feeKey, message) {
    const errorMessage = String(message || "");
    const state = this.ensureMaterialFeeState();
    state.feeDrafts = state.feeDrafts || {};
    const draft = state.feeDrafts[feeKey] || { amount: "", currency: "", touched: true };
    draft.error = errorMessage;
    state.feeDrafts[feeKey] = draft;
    const errorId = this.materialFeeErrorId(feeKey);
    const $inputs = $cell.find("[data-mf-fee-input]");
    $cell.toggleClass ? $cell.toggleClass("is-save-error", Boolean(errorMessage)) : (errorMessage ? $cell.addClass("is-save-error") : $cell.removeClass("is-save-error"));
    $cell.attr("title", errorMessage);
    $inputs.attr("aria-invalid", errorMessage ? "true" : "false").attr("aria-describedby", errorId);
    $cell.find("[data-mf-fee-error]").text(errorMessage).toggleClass("is-visible", Boolean(errorMessage));
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
      status_change_reason: overrides.status_change_reason || fee.status_change_reason || "",
      is_active: fee.is_active === undefined ? 1 : fee.is_active,
      is_enabled: fee.is_enabled === undefined ? 1 : fee.is_enabled,
    };
  }

  async saveMaterialFeeInlineAmount($input) {
    return this.trackMaterialFeeWrite(() => this.persistMaterialFeeInlineAmount($input));
  }

  async trackMaterialFeeWrite(operation) {
    const state = this.ensureMaterialFeeState();
    const versionName = this.detailState.versionName;
    const pending = (async () => {
      if (state.calculationWrite) {
        try { await state.calculationWrite; } catch (_error) { /* The trial reports its own failure. */ }
        if (this.materialFeeState !== state || this.detailState.batchName !== state.batchName || this.detailState.versionName !== versionName) return false;
      }
      return operation();
    })();
    state.pendingWrites.add(pending);
    try {
      return await pending;
    } finally {
      state.pendingWrites.delete(pending);
    }
  }

  async persistMaterialFeeInlineAmount($input) {
    if (!$input.length) return;
    const $cell = $input.closest(".ocw-mf-fee-amount-cell");
    if ($cell.data("saving")) return;
    const $amount = $cell.find("[data-mf-fee-amount]");
    const $currency = $cell.find("[data-mf-fee-currency]");
    const feeKey = String($input.attr("data-fee-key") || "");
    const draft = this.updateMaterialFeeDraftFromInput($input);
    const amount = String(draft?.amount ?? "").trim();
    const currency = String(draft?.currency ?? "");
    const originalAmount = String($amount.attr("data-original-value") ?? "").trim();
    const originalCurrency = String($currency.attr("data-original-value") ?? "").trim().toUpperCase();
    const forceActual = Boolean(draft?.forceActual);
    if (!forceActual && amount === originalAmount && currency === originalCurrency) {
      this.setMaterialFeeInlineError($cell, feeKey, "");
      delete this.ensureMaterialFeeState().feeDrafts?.[feeKey];
      return;
    }
    const validationError = this.validateMaterialFeeInlineDraft(draft);
    if (validationError) {
      this.setMaterialFeeInlineError($cell, feeKey, validationError);
      return;
    }
    this.setMaterialFeeInlineError($cell, feeKey, "");
    if (!this.findMaterialFee(feeKey)) return;
    const batchName = String(this.detailState.batchName || "");
    const versionName = this.detailState.versionName;
    const saveState = this.ensureMaterialFeeState();
    const fullRequestId = saveState.requestId;

    const $inputs = $cell.find("[data-mf-fee-input]");
    $cell.data("saving", true).addClass("is-saving").removeClass("is-save-error").attr("title", "");
    $inputs.prop("disabled", true);
    try {
      if (!(await this.ensureMaterialFeeEditSession())) throw new Error("未能获取编辑权，费用未保存");
      if (
        this.detailState.batchName !== batchName
        || this.detailState.tab !== "documents"
        || this.materialFeeState !== saveState
        || saveState.requestId !== fullRequestId
      ) return;
      const latestFee = this.findMaterialFee(feeKey);
      if (!latestFee) throw new Error("费用项已变更，请刷新后重试");
      const expectedModified = this.detailState.expectedModified;
      const amountStatus = String(latestFee.amount_state || latestFee.amount_status || "MISSING").toUpperCase();
      const payload = this.materialFeeSavePayload(latestFee, {
        amount_status: amountStatus === "MISSING" ? "ESTIMATED" : amountStatus,
        amount,
        currency,
      });
      const result = await this.call("overseas_costing.api.fees.save_fee", {
        batch_name: batchName,
        version_name: versionName,
        fee_payload: JSON.stringify(payload),
        edit_token: this.detailState.editToken,
        expected_modified: expectedModified,
      });
      if (!result || !result.ok) throw new Error(result?.message || "费用保存失败");
      if (this.detailState.batchName !== batchName || this.materialFeeState !== saveState) return;
      this.updateMaterialFeeExpectedModified(result);
      this.detailState.dirty = false;
      delete this.ensureMaterialFeeState().feeDrafts?.[feeKey];
      if (this.detailState.tab !== "documents") return;
      if (saveState.requestId === fullRequestId && !saveState.loading) {
        $amount.attr("data-original-value", amount).attr("data-mf-force-actual", "0");
        $currency.val(currency).attr("data-original-value", currency);
        $cell.data("saving", false).removeClass("is-saving");
        $inputs.prop("disabled", false);
      }
      const loaded = await this.loadMaterialFeeWorkspace({ quiet: true });
      if (
        !loaded
        || this.detailState.batchName !== batchName
        || this.detailState.tab !== "documents"
        || this.materialFeeState !== saveState
        || saveState.loading
      ) return;
      frappe.show_alert({ message: result.message || "费用已保存", indicator: "green" });
    } catch (error) {
      const originalMessage = this.normalizeErrorMessage(error);
      if (this.detailState.batchName !== batchName || this.materialFeeState !== saveState) return;
      if (this.materialFeeEditSessionInvalid(error)) this.clearMaterialFeeEditSession();
      const initialErrorMessage = `${originalMessage}；当前输入已保留；请再次按 Enter 或失焦重试，必要时使用页面刷新`;
      if (this.detailState.tab !== "documents" || saveState.requestId !== fullRequestId) {
        saveState.feeDrafts = saveState.feeDrafts || {};
        saveState.feeDrafts[feeKey] = {
          ...(saveState.feeDrafts[feeKey] || draft),
          error: initialErrorMessage,
          touched: true,
        };
        if (this.detailState.tab === "documents") this.renderMaterialFeeWorkspace();
        return;
      }
      const failureState = this.ensureMaterialFeeState();
      failureState.feeDrafts = failureState.feeDrafts || {};
      failureState.feeDrafts[feeKey] = { ...draft, error: initialErrorMessage, touched: true };
      $cell.removeClass("is-saving");
      $inputs.prop("disabled", false);
      this.setMaterialFeeInlineError($cell, feeKey, initialErrorMessage);
      let recovered = false;
      try {
        recovered = await this.recoverMaterialFeeReadonlyState(batchName);
      } catch (_recoveryError) {
        recovered = false;
      }
      if (
        this.detailState.batchName !== batchName
        || this.detailState.tab !== "documents"
        || this.materialFeeState !== saveState
        || saveState.requestId !== fullRequestId
      ) return;
      $cell.data("saving", false).addClass("is-save-error");
      const recoveryMessage = recovered
        ? "已同步最新数据，请再次按 Enter 或失焦重试"
        : "最新状态同步失败，请使用页面刷新后重试";
      const finalErrorMessage = `${originalMessage}；当前输入已保留；${recoveryMessage}。`;
      this.setMaterialFeeInlineError($cell, feeKey, finalErrorMessage);
      frappe.show_alert({ message: finalErrorMessage, indicator: "red" });
    }
  }

  async recoverMaterialFeeReadonlyState(batchName) {
    const state = this.ensureMaterialFeeState();
    const expectedBatchName = String(batchName || "");
    const versionName = this.detailState.versionName || null;
    const fullRequestId = state.requestId;
    const requestId = ++state.feeRequestId;
    const [detail, fees, preview] = await Promise.all([
      this.call("overseas_costing.api.batch.get_batch_detail", {
        batch_name: expectedBatchName,
        version_name: versionName,
      }),
      this.call("overseas_costing.api.fees.get_fee_worklist", {
        batch_name: expectedBatchName,
        version_name: versionName,
      }),
      this.call("overseas_costing.api.calculate.preview_comprehensive_cost", {
        batch_name: expectedBatchName,
        version_name: versionName,
      }),
    ]);
    if (
      this.detailState.batchName !== expectedBatchName
      || this.materialFeeState !== state
      || requestId !== state.feeRequestId
      || fullRequestId !== state.requestId
      || this.detailState.tab !== "documents"
    ) return false;
    this.applyMaterialFeeHeaderSnapshot(detail, expectedBatchName);
    state.fees = fees;
    state.preview = preview;
    return true;
  }

  async refreshMaterialFeeData() {
    const state = this.ensureMaterialFeeState();
    const batchName = String(this.detailState.batchName || "");
    const fullRequestId = state.requestId;
    const requestId = ++state.feeRequestId;
    const [fees, preview] = await Promise.all([
      this.call("overseas_costing.api.fees.get_fee_worklist", {
        batch_name: batchName,
        version_name: this.detailState.versionName || null,
      }),
      this.call("overseas_costing.api.calculate.preview_comprehensive_cost", {
        batch_name: batchName,
        version_name: this.detailState.versionName || null,
      }),
    ]);
    if (
      this.detailState.batchName !== batchName
      || this.materialFeeState !== state
      || requestId !== state.feeRequestId
      || fullRequestId !== state.requestId
      || this.detailState.tab !== "documents"
    ) return false;
    state.fees = fees;
    state.preview = preview;
    this.renderMaterialFeeWorkspace();
    return true;
  }

  openMaterialFeeDialog(feeKey, candidate = null) {
    const fee = this.findMaterialFee(feeKey);
    if (!fee) return;
    let selectedKeys = [];
    try { selectedKeys = JSON.parse(fee.scope_value_json || "[]"); } catch (_error) { selectedKeys = []; }
    const materials = this.ensureMaterialFeeState().materials?.items || [];
    const otherFees = (this.ensureMaterialFeeState().fees?.fees || []).filter((row) => row.logical_fee_key !== fee.logical_fee_key);
    const currency = this.normalizeMaterialFeeCurrency(candidate?.currency || fee.currency || "RMB");
    const currencies = this.materialFeeCurrencyOptions();
    const supportedCurrency = currencies.some((option) => option.value === currency);
    const dialog = new frappe.ui.Dialog({
      title: `编辑费用：${fee.expense_category || fee.logical_fee_key}`,
      fields: [
        ...(candidate ? [{ fieldtype: "HTML", fieldname: "candidate_note", options: `<div class="ocw-mf-dialog-note">已带入凭证识别候选 ${this.escape(candidate.currency || "")} ${this.escape(candidate.amount || "")}。请仍由你确认金额状态；系统不会自动认定为实际费用。</div>` }] : []),
        { fieldtype: "Select", fieldname: "amount_status", label: "金额状态", reqd: 1, options: "MISSING\nESTIMATED\nACTUAL\nNOT_INCURRED\nINCLUDED", default: fee.amount_state || fee.amount_status || "MISSING" },
        { fieldtype: "Data", fieldname: "amount", label: "原币金额", default: candidate?.amount ?? fee.amount ?? "" },
        { fieldtype: "Select", fieldname: "currency", label: "币种", reqd: 1, options: supportedCurrency ? currencies : [{ value: "", label: `请选择币种（原 ${currency}）` }, ...currencies], default: supportedCurrency ? currency : "" },
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
      allocation_basis: fee.allocation_basis || fee.basis_field || "goods_value",
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

  materialFeeStatusNeedsReason(fee, nextStatus) {
    const previous = String(fee.amount_state || fee.amount_status || "MISSING").toUpperCase();
    const next = String(nextStatus || "MISSING").toUpperCase();
    if (previous === next) return false;
    if (["NOT_INCURRED", "INCLUDED"].includes(next)) return true;
    if (previous === "ACTUAL" && next === "ESTIMATED") return true;
    if (next === "ACTUAL") {
      return !(fee.evidence || []).some((row) => String(row.validation_status || "") === "VALID" && Number(row.is_final || 0));
    }
    return false;
  }

  requestMaterialFeeStatusReason(fee, nextStatus) {
    return new Promise((resolve) => {
      const dialog = new frappe.ui.Dialog({
        title: `调整费用状态：${fee.expense_category || fee.logical_fee_key}`,
        fields: [
          { fieldtype: "Small Text", fieldname: "reason", label: "修改原因", reqd: 1, description: "将记录前后状态、操作者和时间。" },
        ],
        primary_action_label: "确认修改",
        primary_action: (values) => {
          const reason = String(values?.reason || "").trim();
          if (!reason) return;
          dialog.hide();
          resolve(reason);
        },
      });
      dialog.$wrapper.on("hidden.bs.modal", () => resolve(""));
      dialog.show();
    });
  }

  async changeMaterialFeeStatus($select) {
    const feeKey = String($select.attr("data-fee-key") || "");
    const fee = this.findMaterialFee(feeKey);
    if (!fee) return;
    const previous = String($select.attr("data-original-value") || fee.amount_state || fee.amount_status || "MISSING").toUpperCase();
    const nextStatus = String($select.val() || "MISSING").toUpperCase();
    if (previous === nextStatus) return;
    const reason = this.materialFeeStatusNeedsReason(fee, nextStatus)
      ? await this.requestMaterialFeeStatusReason(fee, nextStatus)
      : "";
    if (this.materialFeeStatusNeedsReason(fee, nextStatus) && !reason) {
      $select.val(previous);
      return;
    }
    const currentAmount = String(fee.amount ?? "").trim();
    if (["ESTIMATED", "ACTUAL"].includes(nextStatus) && !currentAmount) {
      $select.val(previous);
      frappe.show_alert({ message: "暂估或实际费用需要金额；也可以先关联并解析凭证。", indicator: "orange" });
      return;
    }
    if (!(await this.ensureMaterialFeeEditSession())) {
      $select.val(previous);
      return;
    }
    $select.prop("disabled", true);
    try {
      const payload = this.materialFeeSavePayload(fee, {
        amount_status: nextStatus,
        status_change_reason: reason,
      });
      if (["NOT_INCURRED", "INCLUDED"].includes(nextStatus) && reason) payload.remark = reason;
      const result = await this.call("overseas_costing.api.fees.save_fee", {
        batch_name: this.detailState.batchName,
        version_name: this.detailState.versionName,
        fee_payload: JSON.stringify(payload),
        edit_token: this.detailState.editToken,
        expected_modified: this.detailState.expectedModified,
      }, false);
      if (!result?.ok) throw new Error(result?.message || "费用状态保存失败");
      this.updateMaterialFeeExpectedModified(result);
      frappe.show_alert({ message: "费用状态已保存，试算结果待更新", indicator: "green" });
      await this.loadMaterialFeeWorkspace({ quiet: true });
    } catch (error) {
      $select.val(previous).prop("disabled", false);
      throw error;
    }
  }

  openMaterialFeeEvidenceDialog(feeKey) {
    const fee = this.findMaterialFee(feeKey);
    if (!fee) return;
    const candidates = this.ensureMaterialFeeState().fees?.evidence_candidates || [];
    const linked = new Set((fee.evidence || []).map((row) => row.attachment));
    const dialog = new frappe.ui.Dialog({
      title: `关联并解析凭证：${fee.expense_category || fee.logical_fee_key}`,
      fields: [{ fieldtype: "HTML", fieldname: "evidence", options: `<div class="ocw-mf-evidence-picker"><div class="ocw-mf-dialog-note">可先选凭证，系统再提取金额、币种、费用类别及 SKU／税种关系。所有结果都要在审核草稿中确认。</div>${candidates.length ? candidates.map((candidate) => `<label class="ocw-mf-evidence-option"><input type="radio" name="mf-evidence-attachment" data-mf-evidence-attachment="${this.escape(candidate.attachment || "")}"/><span><strong>${this.escape(candidate.file_name || candidate.attachment || "--")}</strong><small>${this.escape(candidate.source_type || "附件")} · ${this.escape(candidate.parse_status || "Draft")}${linked.has(candidate.attachment) ? " · 已关联，可重新解析" : ""}</small></span></label>`).join("") : `<div class="ocw-detail-empty"><strong>暂无可关联资料</strong><span>可先上传新凭证。</span></div>`}<button class="ocw-outline-btn" type="button" data-action="mf-upload-evidence">上传新凭证并解析</button></div>` }],
      primary_action_label: "开始解析所选凭证",
      primary_action: () => this.linkSelectedMaterialFeeEvidence(dialog, fee),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-mf-dialog");
    dialog.$wrapper.on("click", "[data-action='mf-upload-evidence']", () => {
      this.uploadMaterialFeeEvidence(dialog, fee);
    });
  }

  async linkSelectedMaterialFeeEvidence(dialog, fee) {
    if (!(await this.ensureEditSession())) return;
    const attachments = dialog.$wrapper.find("[data-mf-evidence-attachment]:checked").toArray().map((node) => $(node).attr("data-mf-evidence-attachment"));
    if (!attachments.length) {
      frappe.show_alert({ message: "请选择一份凭证", indicator: "orange" });
      return;
    }
    dialog.hide();
    await this.openFeeEvidenceReviewDialog(fee.logical_fee_key, attachments[0]);
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
      dialog.hide();
      await this.openFeeEvidenceReviewDialog(fee.logical_fee_key, attachment);
      if (!recognitionOk) frappe.show_alert({ message: "规则预解析未完成，AI 审核中仍可关联并人工补录", indicator: "orange" });
    });
  }

  renderFeeEvidenceReviewProgressShell() {
    return `<div class="ocw-mf-evidence-review-dialog" data-mf-fee-review-host="1">
      <header><div><strong data-mf-fee-review-title>正在启动凭证分析</strong><span data-mf-fee-review-step>建立审核任务</span></div><b data-mf-fee-review-percent>0%</b></header>
      <div class="ocw-mf-ai-progress"><i data-mf-fee-review-bar style="width:0%"></i></div>
      <div class="ocw-mf-fee-review-source"><i></i><div><strong data-mf-fee-review-source-name>读取凭证资料</strong><span data-mf-fee-review-source-detail>等待后台任务</span></div><em data-mf-fee-review-source-status>等待</em></div>
      <div class="ocw-mf-ai-progress-warning" data-mf-fee-review-warning hidden></div>
      <div data-mf-fee-review-draft></div>
      <footer><button class="ocw-outline-btn" type="button" data-action="mf-fee-review-discard" hidden>放弃草稿</button><button class="ocw-primary-btn" type="button" data-action="mf-fee-review-apply" hidden>确认所选草稿</button></footer>
    </div>`;
  }

  feeEvidenceReviewStatusLabel(status) {
    return {
      WAITING: "等待", DOWNLOADING: "下载中", READING: "读取中", PARSED: "已解析",
      ANALYZING: "AI 分析中", COMPLETED: "已完成", FAILED: "失败", SKIPPED: "跳过",
    }[String(status || "WAITING").toUpperCase()] || String(status || "等待");
  }

  async openFeeEvidenceReviewDialog(feeKey, attachment, options = {}) {
    const state = this.ensureMaterialFeeState();
    if (state.feeEvidenceReviewStartPromise) {
      state.feeEvidenceReviewDialog?.show();
      return state.feeEvidenceReviewStartPromise;
    }
    if (!(await this.ensureMaterialFeeEditSession())) return;
    state.feeEvidenceReview = {
      status: "STARTING", logicalFeeKey: String(feeKey || ""), attachment: String(attachment || ""),
      batchName: String(options.batchName || this.detailState.batchName || ""),
      versionName: String(options.versionName || this.detailState.versionName || ""),
      progress_percent: 0, progress_step: "正在启动凭证分析", progress_revision: 0,
    };
    if (!state.feeEvidenceReviewDialog) {
      const dialog = new frappe.ui.Dialog({
        title: "AI 凭证解析与 SKU 分摊审核",
        fields: [{ fieldtype: "HTML", fieldname: "fee_review", options: this.renderFeeEvidenceReviewProgressShell() }],
      });
      state.feeEvidenceReviewDialog = dialog;
      dialog.$wrapper.addClass("ocw-mf-evidence-review-modal");
      dialog.$wrapper.on("change", "[data-mf-fee-review-select]", (event) => {
        const review = state.feeEvidenceReview;
        const id = String($(event.currentTarget).attr("data-proposal-id") || "");
        if ($(event.currentTarget).prop("checked")) review.selections.add(id);
        else review.selections.delete(id);
      });
      dialog.$wrapper.on("input change", "[data-mf-fee-review-edit]", (event) => {
        const $input = $(event.currentTarget);
        const proposalId = String($input.attr("data-proposal-id") || "");
        const fieldname = String($input.attr("data-fieldname") || "");
        const review = state.feeEvidenceReview;
        review.edits[proposalId] = review.edits[proposalId] || {};
        review.edits[proposalId][fieldname] = $input.attr("type") === "checkbox" ? ($input.prop("checked") ? 1 : 0) : String($input.val() ?? "");
        review.selections.add(proposalId);
        dialog.$wrapper.find(`[data-mf-fee-review-select][data-proposal-id='${proposalId.replace(/'/g, "\\'")}']`).prop("checked", true);
      });
      dialog.$wrapper.on("click", "[data-action='mf-fee-review-apply']", () => this.applyFeeEvidenceReview().catch((error) => this.showError(error)));
      dialog.$wrapper.on("click", "[data-action='mf-fee-review-discard']", () => this.discardFeeEvidenceReview().catch((error) => this.showError(error)));
    }
    state.feeEvidenceReviewDialog.show();
    state.feeEvidenceReviewDialog.$wrapper.find("[data-mf-fee-review-draft]").empty().removeData("rendered");
    this.updateFeeEvidenceReviewProgress();
    const startPromise = (async () => {
      const fee = this.findMaterialFee(feeKey) || {};
      const started = await this.call("overseas_costing.api.fees.start_fee_evidence_review", {
        batch_name: state.feeEvidenceReview.batchName,
        version_name: state.feeEvidenceReview.versionName,
        logical_fee_key: feeKey,
        attachment,
        evidence_role: options.evidenceRole || fee.required_evidence_role || "expense_invoice",
        force: options.force ? 1 : 0,
        edit_token: this.detailState.editToken,
        expected_modified: this.detailState.expectedModified,
      }, false);
      if (!started?.ok) throw new Error(started?.message || "凭证分析任务启动失败");
      state.feeEvidenceReview = {
        ...state.feeEvidenceReview, runId: started.run_id, status: started.status,
        progress_revision: Number(started.progress_revision || 0), progress_step: "读取凭证", progress_percent: 5,
      };
      this.updateFeeEvidenceReviewProgress();
      await this.pollFeeEvidenceReview(state, state.feeEvidenceReview.batchName, started.run_id);
    })().catch((error) => {
      state.feeEvidenceReview = { ...state.feeEvidenceReview, status: "FAILED", progress_step: "分析失败", error_message: this.materialAIErrorMessage(error, "凭证分析失败，请重试。") };
      this.updateFeeEvidenceReviewProgress();
    }).finally(() => {
      if (state.feeEvidenceReviewStartPromise === startPromise) state.feeEvidenceReviewStartPromise = null;
    });
    state.feeEvidenceReviewStartPromise = startPromise;
    return startPromise;
  }

  async pollFeeEvidenceReview(state, batchName, runId) {
    let failures = 0;
    for (let attempt = 0; attempt < 300; attempt += 1) {
      if (this.materialFeeState !== state) return;
      let result;
      try {
        result = await this.call("overseas_costing.api.fees.get_fee_evidence_review_status", {
          batch_name: batchName,
          run_id: runId,
          after_revision: Number(state.feeEvidenceReview?.progress_revision || 0),
        }, false);
        failures = 0;
      } catch (error) {
        failures += 1;
        state.feeEvidenceReview.connection_error = this.materialAIErrorMessage(error, "状态连接暂时中断，正在重试。 ");
        this.updateFeeEvidenceReviewProgress();
        await new Promise((resolve) => window.setTimeout(resolve, Math.min(5000, 800 * failures)));
        continue;
      }
      if (!result?.ok) throw new Error(result?.message || "凭证分析状态读取失败");
      if (!result.unchanged) {
        state.feeEvidenceReview = { ...state.feeEvidenceReview, ...result, runId };
        delete state.feeEvidenceReview.connection_error;
        if (result.status === "READY") {
          const draft = result.draft || {};
          const proposals = [draft.evidence, ...(draft.fee_splits || []), ...(draft.components || [])].filter(Boolean);
          state.feeEvidenceReview.selections = new Set(proposals.filter((row) => row.default_selected).map((row) => String(row.proposal_id || "")));
          state.feeEvidenceReview.edits = {};
        }
        this.updateFeeEvidenceReviewProgress();
      }
      if (["READY", "FAILED", "STALE", "APPLIED", "DISCARDED"].includes(String(result.status || ""))) return;
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
    }
    throw new Error("凭证分析超时，请稍后重新分析。 ");
  }

  updateFeeEvidenceReviewProgress() {
    const state = this.ensureMaterialFeeState();
    const review = state.feeEvidenceReview || {};
    const dialog = state.feeEvidenceReviewDialog;
    if (!dialog?.$wrapper?.length) return;
    const $host = dialog.$wrapper.find("[data-mf-fee-review-host]");
    const progress = Math.max(0, Math.min(100, Number(review.progress_percent || 0)));
    const source = (review.source_progress || [])[0] || {};
    const warning = String(review.connection_error || review.ai_warning || review.error_message || "");
    $host.find("[data-mf-fee-review-title]").text(review.status === "READY" ? "凭证审核草稿已生成" : review.status === "FAILED" ? "凭证分析未完成" : "正在解析凭证");
    $host.find("[data-mf-fee-review-step]").text(review.progress_step || "读取凭证");
    $host.find("[data-mf-fee-review-percent]").text(`${progress}%`);
    $host.find("[data-mf-fee-review-bar]").css("width", `${progress}%`);
    $host.find("[data-mf-fee-review-source-name]").text(source.display_name || source.label || review.attachment || "凭证资料");
    $host.find("[data-mf-fee-review-source-detail]").text(source.detail || "后台处理中");
    $host.find("[data-mf-fee-review-source-status]").text(this.feeEvidenceReviewStatusLabel(source.status));
    $host.find("[data-mf-fee-review-warning]").text(warning).prop("hidden", !warning);
    const ready = review.status === "READY";
    $host.find("[data-action='mf-fee-review-apply'], [data-action='mf-fee-review-discard']").prop("hidden", !ready);
    if (ready && !$host.find("[data-mf-fee-review-draft]").data("rendered")) {
      $host.find("[data-mf-fee-review-draft]").html(this.renderFeeEvidenceReviewDraft(review.draft || {})).data("rendered", true);
    }
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
    const message = row.warning || (row.has_conflict ? "AI 与规则结果冲突，请人工核对；默认不勾选。" : "证据或匹配信心不足，请人工核对；默认不勾选。");
    return `<em class="ocw-mf-review-warning">${this.escape(message)}</em>`;
  }

  renderFeeEvidenceReviewDraft(draft) {
    const evidence = draft.evidence || {};
    const selected = (row) => row?.default_selected ? "checked" : "";
    const statusOptions = [["ESTIMATED", "暂估"], ["ACTUAL", "实际"]];
    const feeRows = draft.fee_splits || [];
    const componentRows = draft.components || [];
    const itemOptions = draft.item_options || [];
    const refundParents = draft.refund_parent_options || [];
    const evidenceId = this.escape(evidence.proposal_id || "evidence:classification");
    const sourceRefs = [
      ...(evidence.source_refs || []),
      ...feeRows.flatMap((row) => row.source_refs || []),
      ...componentRows.map((row) => row.source_evidence || {}).filter((row) => Object.keys(row).length),
    ];
    return `<div class="ocw-mf-fee-review-draft">
      ${this.renderCurrentSourceReviewControls(draft.source_context || {}, null, { fees: true })}
      <section class="${evidence.has_conflict || evidence.needs_review ? "is-warning" : ""}"><h4>凭证总额</h4>${this.renderFeeEvidenceReviewWarning(evidence)}<label class="ocw-mf-review-choice"><input type="checkbox" data-mf-fee-review-select data-proposal-id="${evidenceId}" ${selected(evidence)}><span><strong>${this.escape(evidence.currency || "RMB")} ${this.escape(evidence.original_amount || "待人工补录")}</strong><small>${this.escape(evidence.reason || "请核对凭证类型和会计作用")}</small></span></label><div class="ocw-mf-review-fields"><label>凭证类型<select data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="evidence_type">${[["QUOTE","报价"],["PREPAYMENT","预付款／暂缴"],["FINAL_INVOICE","最终发票／结算单"],["TAX_CERTIFICATE","完税凭证"],["PAYMENT","付款流水"],["REFUND","退款／贷项"],["OTHER","其他"]].map(([value,label]) => `<option value="${value}" ${value === evidence.evidence_type ? "selected" : ""}>${label}</option>`).join("")}</select></label><label>会计作用<select data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="accounting_role">${[["ESTIMATE","更新暂估"],["FINAL_BILL","最终账单"],["SETTLEMENT","付款／退款流水"],["REFERENCE","仅作参考"]].map(([value,label]) => `<option value="${value}" ${value === evidence.accounting_role ? "selected" : ""}>${label}</option>`).join("")}</select></label><label>金额<input data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="original_amount" value="${this.escape(evidence.original_amount || "")}" inputmode="decimal"></label><label>币种<select data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="currency">${this.materialFeeCurrencyOptions().map((option) => `<option value="${option.value}" ${option.value === (evidence.currency || "RMB") ? "selected" : ""}>${option.label}</option>`).join("")}</select></label><label>方向<select data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="direction"><option value="DEBIT" ${evidence.direction !== "CREDIT" ? "selected" : ""}>付款／应付</option><option value="CREDIT" ${evidence.direction === "CREDIT" ? "selected" : ""}>退款／冲回</option></select></label><label>关联原付款<select data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="related_evidence"><option value="">无／待核对</option>${refundParents.map((row) => `<option value="${this.escape(row.name || "")}" ${String(row.name || "") === String(evidence.related_evidence || "") ? "selected" : ""}>${this.escape([row.currency, row.original_amount, row.attachment || row.name].filter(Boolean).join(" · "))}</option>`).join("")}</select></label><label class="is-checkbox"><input type="checkbox" data-mf-fee-review-edit data-proposal-id="${evidenceId}" data-fieldname="is_final" ${evidence.is_final ? "checked" : ""}> 已确认是最终凭证</label></div></section>
      <section><h4>费用拆分</h4>${feeRows.length ? feeRows.map((row) => `<label class="ocw-mf-review-choice ${row.has_conflict || row.needs_review ? "is-warning" : ""}"><input type="checkbox" data-mf-fee-review-select data-proposal-id="${this.escape(row.proposal_id || "")}" ${selected(row)}><span><strong>${this.escape(row.label || row.logical_fee_key)} · ${this.escape(row.currency)} <input data-mf-fee-review-edit data-proposal-id="${this.escape(row.proposal_id || "")}" data-fieldname="amount" value="${this.escape(row.amount || "")}" inputmode="decimal"></strong><small><select data-mf-fee-review-edit data-proposal-id="${this.escape(row.proposal_id || "")}" data-fieldname="amount_status">${statusOptions.map(([value,label]) => `<option value="${value}" ${value === (row.amount_status || evidence.suggested_amount_status) ? "selected" : ""}>${label}</option>`).join("")}</select></small>${this.renderFeeEvidenceReviewWarning(row)}</span></label>`).join("") : "<p>未识别出可安全拆分的金额，可保留凭证后人工补录。</p>"}</section>
      ${draft.missing_fx ? `<div class="ocw-mf-review-warning is-block">缺汇率：可保存原币事实，本次试算不会计入。</div>` : ""}
      <section><h4>税种 · HS / SKU 匹配与分摊结果</h4><div class="ocw-mf-review-table"><table><thead><tr><th>选择</th><th>税种</th><th>HS</th><th>SKU 匹配</th><th>原币金额</th><th>RMB</th><th>依据</th></tr></thead><tbody>${componentRows.length ? componentRows.map((row) => `<tr class="${row.has_conflict || row.needs_review ? "is-warning" : ""}"><td><input type="checkbox" data-mf-fee-review-select data-proposal-id="${this.escape(row.proposal_id || "")}" ${selected(row)}></td><td>${this.escape(row.tax_code || "--")}</td><td>${this.escape(row.hs_code || "--")}</td><td><select data-mf-fee-review-edit data-proposal-id="${this.escape(row.proposal_id || "")}" data-fieldname="item" aria-label="选择税费分项对应 SKU">${itemOptions.map((option) => `<option value="${this.escape(option.item || "")}" ${String(option.item || "") === String(row.item || "") ? "selected" : ""}>${this.escape([option.material_code, option.product_name].filter(Boolean).join(" · ") || option.stable_line_key || option.item)}</option>`).join("")}</select></td><td>${this.escape(row.currency || "MXN")} ${this.escape(row.original_amount || "--")}</td><td>${this.escape(row.amount_rmb || "缺汇率")}</td><td>${row.refund_parent ? `<small>原付款 ${this.escape(row.refund_parent)}</small>` : ""}${this.escape(row.allocation_basis || "--")}${this.renderFeeEvidenceReviewWarning(row)}</td></tr>`).join("") : `<tr><td colspan="7">暂无可精确归集的 SKU 税费分项</td></tr>`}</tbody></table></div></section>
      <section class="is-difference"><h4>待归类差额</h4><strong>${this.escape(draft.unclassified_difference || "0.00")} ${this.escape(evidence.currency || "")}</strong><small>人工确认前不计入成本。</small></section>
      <section><h4>来源证据</h4><p>${sourceRefs.map((ref) => this.escape(this.feeEvidenceSourceLabel(ref))).filter(Boolean).join("；") || "证据位置未完整提取，请人工核对原附件。"}</p></section>
    </div>`;
  }

  async applyFeeEvidenceReview() {
    const state = this.ensureMaterialFeeState();
    const review = state.feeEvidenceReview;
    if (review?.status !== "READY" || !(await this.ensureMaterialFeeEditSession())) return;
    if (state.feeEvidenceReviewDialog?.$wrapper?.find("[data-current-source-review]").length) {
      review.edits = { ...(review.edits || {}), _source_review: this.collectCurrentSourceReviewControls(state.feeEvidenceReviewDialog.$wrapper) };
    }
    const result = await this.call("overseas_costing.api.fees.apply_fee_evidence_review", {
      batch_name: review.batchName || this.detailState.batchName,
      run_id: review.runId,
      selections_json: JSON.stringify([...review.selections]),
      edits_json: JSON.stringify(review.edits || {}),
      edit_token: this.detailState.editToken,
      expected_modified: this.detailState.expectedModified,
    }, false);
    if (!result?.ok) throw new Error(result?.message || "凭证审核草稿保存失败");
    this.updateMaterialFeeExpectedModified(result);
    state.feeEvidenceReviewDialog?.hide();
    state.feeEvidenceReviewDialog = null;
    state.feeEvidenceReview = null;
    frappe.show_alert({ message: result.message || "凭证草稿已保存", indicator: "green" });
    if (this.detailState.tab === "documents") await this.loadMaterialFeeWorkspace({ quiet: true });
  }

  async discardFeeEvidenceReview() {
    const state = this.ensureMaterialFeeState();
    const review = state.feeEvidenceReview;
    if (!review?.runId) return;
    const result = await this.call("overseas_costing.api.fees.discard_fee_evidence_review", {
      batch_name: review.batchName || this.detailState.batchName,
      run_id: review.runId,
    }, false);
    if (!result?.ok) throw new Error(result?.message || "放弃凭证草稿失败");
    state.feeEvidenceReviewDialog?.hide();
    state.feeEvidenceReviewDialog = null;
    state.feeEvidenceReview = null;
    frappe.show_alert({ message: result.message, indicator: "green" });
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

  isMaterialFeeCalculationBusy(state = this.materialFeeState) {
    return Boolean(state?.previewRunning || state?.calculationWrite);
  }

  canApplyMaterialAIFill(fill) {
    if (fill?.status !== "READY" || fill.applying || fill.discarding || this.isMaterialFeeCalculationBusy()) return false;
    if (fill.row_review) return this.canConfirmMaterialAIRowSelection(fill);
    return (fill.selections?.size || 0) + Object.keys(fill.manualUpdates || {}).length > 0;
  }

  updateMaterialFeeWriteControls(state) {
    if (this.materialFeeState !== state) return;
    const calculating = this.isMaterialFeeCalculationBusy(state);
    this.$root?.find("[data-action='mf-preview-cost']")?.prop?.("disabled", calculating || Boolean(state.aiFill?.applying))
      ?.text?.(calculating ? "计算中…" : "开始试算");
    for (const root of [this.$root, state.aiProgressDialog?.$wrapper]) {
      root?.find("[data-action='mf-ai-apply']")?.prop?.("disabled", !this.canApplyMaterialAIFill(state.aiFill));
    }
  }

  async flushMaterialFeeInputs(state) {
    // Analysis proposals are independent of saved facts. Only an actual AI write blocks a trial.
    if (state.aiFill?.applying) throw new Error("AI 资料正在保存，请保存完成后再开始试算。");
    if (state.calculationWrite) await state.calculationWrite;
    while (state.pendingWrites.size) await Promise.all([...state.pendingWrites]);
    if (this.materialFeeState !== state || this.detailState.batchName !== state.batchName) return false;
    if (this.detailState.tab !== "documents") {
      if (Object.keys(state.materialDrafts).length || Object.keys(state.feeDrafts).length || Object.keys(state.materialSaveErrors).length) {
        throw new Error("有资料与费用修改尚未保存，请返回资料与费用完成保存后再试算。");
      }
      return true;
    }
    for (const key of Object.keys(state.materialDrafts)) {
      const draft = state.materialDrafts[key];
      if (draft.error) throw new Error(`请先处理物料输入：${draft.error}`);
      let input = null;
      this.$root.find("[data-mf-cell-input]").each((_, element) => {
        if ($(element).attr("data-item-name") === draft.itemName && $(element).attr("data-fieldname") === draft.fieldname) input = element;
      });
      if (!input) throw new Error("有物料修改尚未保存，请返回对应物料行保存后再试算。");
      await this.saveMaterialFeeCell($(input));
      if (this.materialFeeState !== state || this.detailState.tab !== "documents") return false;
      if (state.materialDrafts[key]) throw new Error(state.materialDrafts[key].error || "物料尚未保存，请重试后再试算。");
    }
    for (const feeKey of Object.keys(state.feeDrafts)) {
      const draft = state.feeDrafts[feeKey];
      const error = draft.error || this.validateMaterialFeeInlineDraft(draft);
      if (error) throw new Error(`请先处理费用输入：${error}`);
      let input = null;
      this.$root.find("[data-mf-fee-amount]").each((_, element) => {
        if (String($(element).attr("data-fee-key")) === feeKey) input = element;
      });
      if (!input) throw new Error("有费用修改尚未保存，请返回费用区保存后再试算。");
      await this.saveMaterialFeeInlineAmount($(input));
      if (this.materialFeeState !== state || this.detailState.tab !== "documents") return false;
      if (state.feeDrafts[feeKey]) throw new Error(state.feeDrafts[feeKey].error || "费用尚未保存，请重试后再试算。");
    }
    if (Object.keys(state.materialSaveErrors).length) throw new Error("物料数据保存失败，请修正红色输入并保存后再试算。");
    if (state.pendingWrites.size || Object.keys(state.materialDrafts).length || Object.keys(state.feeDrafts).length) {
      throw new Error("试算准备期间有新的修改尚未保存，请完成录入后再次试算。");
    }
    return true;
  }

  async refreshMaterialFeeCostPreview(scrollToResult = false) {
    const state = this.ensureMaterialFeeState();
    if (this.isMaterialFeeCalculationBusy(state)) return false;
    const batchName = this.detailState.batchName;
    const versionName = this.detailState.versionName;
    const isCurrent = () => this.materialFeeState === state
      && this.detailState.batchName === batchName
      && this.detailState.versionName === versionName
      && this.detailState.tab === "documents";
    state.previewRunning = true;
    this.updateMaterialFeeWriteControls(state);
    try {
      if (!(await this.flushMaterialFeeInputs(state)) || !isCurrent()) return false;
      if (this.ensureEditSession && !(await this.ensureEditSession())) return false;
      if (!isCurrent()) return false;
      const requestId = state.requestId;
      const feeRequestId = state.feeRequestId;
      const inputRevision = state.inputRevision;
      const isUnchangedView = () => isCurrent() && state.requestId === requestId
        && state.feeRequestId === feeRequestId && state.inputRevision === inputRevision;
      const calculationWrite = (async () => {
        const result = await this.call("overseas_costing.api.calculate.calculate_comprehensive_cost", {
          batch_name: batchName,
          version_name: versionName || null,
          edit_token: this.detailState.editToken,
          expected_modified: this.detailState.expectedModified,
        });
        if (!result?.ok) throw new Error(result?.message || "试算失败，请稍后重试。");
        // A saved trial changed the server revision even when its original view is stale.
        if (result.saved) this.acceptSavedComprehensiveCost(result, batchName, {
          versionName, preserveDirty: !isUnchangedView(),
        });
        return result;
      })();
      state.calculationWrite = calculationWrite;
      let preview;
      try {
        preview = await calculationWrite;
      } finally {
        if (state.calculationWrite === calculationWrite) state.calculationWrite = null;
      }
      if (!isUnchangedView()) return false;
      if (preview.saved && preview.batch_modified && this.detailState.expectedModified
        && String(this.detailState.expectedModified) > String(preview.batch_modified)) return false;
      state.preview = preview;
      this.renderDetailShell?.();
      if (this.detailState.editToken) this.updateEditLeaseStatus?.();
      this.renderMaterialFeeWorkspace();
      if (scrollToResult) this.$root.find(".ocw-mf-cost-section").get(0)?.scrollIntoView({ behavior: "smooth", block: "start" });
      frappe.show_alert({ message: "试算完成", indicator: "green" });
      return true;
    } finally {
      state.previewRunning = false;
      this.updateMaterialFeeWriteControls(state);
    }
  }

  acceptSavedComprehensiveCost(result, batchName, { versionName = result.version_name, preserveDirty = false } = {}) {
    const summary = result.summary_snapshot || {};
    const updates = { status: "Calculated", modified: result.batch_modified,
      estimated_total_cost_rmb: result.summary?.total_cost_rmb, summary_snapshot: summary,
      item_count: summary.item_count, total_goods_value: summary.total_goods_value };
    const index = (this.batches || []).findIndex((row) => row.name === batchName);
    const hasNewerRevision = (modified) => Boolean(modified && result.batch_modified && String(modified) > String(result.batch_modified));
    if (index >= 0 && (!versionName || !this.batches[index].current_version || this.batches[index].current_version === versionName)
      && !hasNewerRevision(this.batches[index].modified)) {
      this.batches[index] = { ...this.batches[index], ...updates };
    }
    if (this.detailState.batchName === batchName && (!versionName || this.detailState.versionName === versionName)
      && !hasNewerRevision(this.detailState.expectedModified)) {
      this.detailState.header = { ...(this.detailState.header || {}), ...updates };
      this.detailState.expectedModified = result.batch_modified || this.detailState.expectedModified;
      this.detailState.skuRequestId = (this.detailState.skuRequestId || 0) + 1;
      this.detailState.skuResult = null;
      if (!preserveDirty) this.detailState.dirty = false;
      if (this.materialFeeState?.batchName === batchName) this.materialFeeState.preview = result;
    }
    if (this.resetBatchResultPreview) this.resetBatchResultPreview({ clearCache: true, render: false });
  }

  materialFeeExclusionReason(fee) {
    return {
      AMOUNT_MISSING: "金额尚未填写",
      FX_RATE_MISSING: "缺少该币种的批次汇率，请先补充汇率",
      CURRENCY_UNSUPPORTED: "币种暂不支持，请选择人民币、比索或美金",
      FEE_AMOUNT_INVALID: "金额无效，请填写不小于 0 的有效金额",
      AMOUNT_STATUS_INVALID: "金额状态无效，请重新确认",
      DUPLICATE_LOGICAL_FEE: "费用重复，请核对并停用重复记录",
      ALLOCATION_BASIS_INCOMPLETE: "体积或重量资料不完整，采购货值也未齐全，请补充资料后重试",
      ALLOCATION_DENOMINATOR_ZERO: "体积或重量尚未提供，采购货值也未齐全，请补充资料后重试",
      FEE_SCOPE_EMPTY: "没有可分摊的物料，请检查物料与适用范围",
      DIRECT_ITEM_SCOPE_INVALID: "直接费用需要指定一条有效物料",
      FEE_SCOPE_INVALID: "费用适用范围无效，请重新选择",
      STABLE_ITEM_KEY_REQUIRED: "物料标识缺失，请先核对物料数据",
      STABLE_ITEM_KEY_DUPLICATED: "物料标识重复，请先核对物料数据",
    }[fee.reason_code] || "费用资料尚不完整，请核对后重试";
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

  materialFeeSavedCostPreview() {
    // Only persisted results can be shared with the overview and SKU details.
    return this.detailState?.header?.summary_snapshot?.comprehensive_cost
      || (this.materialFeeState?.preview?.saved === true && this.materialFeeState.preview.read_only === false ? this.materialFeeState.preview : null);
  }

  renderMaterialFeeCostTable() {
    const state = this.ensureMaterialFeeState();
    const header = this.detailState.header || {};
    const preview = this.materialFeeSavedCostPreview();
    const legacyTotal = header.summary_snapshot?.total_cost_rmb;
    const hasLegacyTotal = legacyTotal !== undefined && legacyTotal !== null && legacyTotal !== "" && Number.isFinite(Number(legacyTotal));
    const sourcePending = state.materials?.calculation_stale || state.fees?.summary?.source_pending;
    const staleCost = (header.status === "Dirty" || sourcePending) && Boolean(preview || hasLegacyTotal);
    const sectionTitle = `<div class="ocw-mf-section-title">
      <div><span>03</span><h3>SKU 综合单价试算</h3><p>开始试算后保存当前计算结果，并同步总览与 SKU 明细；确认和 ERP 推送需单独操作。</p><p>本次按已保存资料试算，未采用的 AI 结果不计入。</p></div>
      <div class="ocw-mf-cost-actions"><span class="ocw-mf-completeness ${!staleCost && preview?.summary?.is_complete ? "is-complete" : "is-partial"}">${staleCost ? "待重新试算" : preview ? (preview.summary?.is_complete ? "完整成本" : "非完整成本") : (hasLegacyTotal ? "待重新试算" : "尚未试算")}</span><button class="ocw-primary-btn" type="button" data-action="mf-preview-cost" ${this.isMaterialFeeCalculationBusy(state) || state.aiFill?.applying ? "disabled" : ""}>${this.isMaterialFeeCalculationBusy(state) ? "计算中…" : "开始试算"}</button></div>
    </div>`;
    if (!preview) {
      return `<section class="ocw-mf-section ocw-mf-cost-section">${sectionTitle}
        ${hasLegacyTotal ? `<div class="ocw-mf-cost-summary"><div class="ocw-mf-cost-total"><span>上次已保存成本 · 待重新试算</span><strong>RMB ${this.escape(Number(legacyTotal).toFixed(2))}</strong></div></div>` : ""}
        <div class="ocw-detail-empty"><strong>${hasLegacyTotal ? "当前费用尚未汇总到已保存成本" : "尚未保存试算结果"}</strong><p>点击“开始试算”，按当前物料和费用更新总览、SKU 明细及本区结果。</p></div>
      </section>`;
    }
    const summary = preview.summary || {};
    const items = preview.items || [];
    const hasUnsaved = Object.keys(state.feeDrafts).length || Object.keys(state.materialDrafts).length || Object.keys(state.materialSaveErrors).length;
    const allocationNotes = (preview.included_fees || []).map((fee) => {
      const method = this.materialFeeBasisLabel(fee.allocation_basis);
      const explanation = fee.fallback_reason ? `${this.materialFeeBasisLabel(fee.preferred_basis)}数据不完整，已自动按采购货值分摊` : method;
      return `<li><strong>${this.escape(fee.expense_category || fee.fee_key || "费用")}</strong><span>${this.escape(explanation)}</span><em>RMB ${this.escape(fee.amount_rmb || "0.00")}</em></li>`;
    }).join("");
    return `<section class="ocw-mf-section ocw-mf-cost-section">
      ${sectionTitle}
      ${staleCost ? '<p class="ocw-mf-trial-note">资料已更新，请点击“开始试算”。以下为历史结果。</p><details class="ocw-mf-cost-history"><summary>查看上次试算</summary>' : ""}
      ${this.renderShipmentProjectSummary(preview.project_summary || [])}
      <div class="ocw-mf-cost-summary">
        <div class="ocw-mf-cost-total"><span>${hasUnsaved ? "上次试算 · 有修改待保存" : header.status === "Dirty" ? "上次试算 · 结果待更新" : "当前试算总成本"}</span><strong>RMB ${this.escape(summary.total_cost_rmb || "0.00")}</strong></div>
        <dl><div><dt>本次发货货值</dt><dd>${this.escape(summary.purchase_goods_value_rmb || "0.00")}</dd></div><div><dt>直接费用</dt><dd>${this.escape(summary.direct_fees_rmb || "0.00")}</dd></div><div><dt>分摊费用</dt><dd>${this.escape(summary.allocated_fees_rmb || "0.00")}</dd></div><div><dt>已计入费用</dt><dd>${Number(summary.included_fee_count || 0)} 笔</dd></div></dl>
      </div>
      <p class="ocw-mf-trial-note">试算不生成正式成本版本；凭证待补单独保留，已知金额可先参与计算。${summary.estimated_fee_count ? `含 ${Number(summary.estimated_fee_count)} 笔暂估费用，需后续核实。` : ""}</p>
      <div class="ocw-mf-cost-scroll"><table><thead><tr><th>物料编码</th><th>物料名称</th><th>本次发货货值</th><th>直接费用</th><th>分摊费用</th><th>综合成本</th><th>每发货单位</th><th>每采购计价单位</th></tr></thead><tbody>${items.length ? items.map((item) => `<tr><td>${this.escape(item.material_code || "--")}</td><td>${this.escape(item.product_name || "--")}${Number(item.shipping_quantity_difference) < 0 ? `<small class="ocw-mf-warning">少发 ${this.escape(String(-Number(item.shipping_quantity_difference)))} ${this.escape(item.shipping_unit_cost?.uom || "")}</small>` : ""}</td><td>${this.escape(item.goods_value_rmb || "0.00")}</td><td>${this.escape(item.direct_fees_rmb || "0.00")}</td><td>${this.escape(item.allocated_fees_rmb || "0.00")}</td><td><strong>${this.escape(item.total_cost_rmb || "0.00")}</strong></td><td>${item.shipping_unit_cost ? `${this.escape(item.shipping_unit_cost.amount_rmb)} / ${this.escape(item.shipping_unit_cost.uom)}` : "--"}</td><td>${item.purchase_pricing_unit_cost ? `${this.escape(item.purchase_pricing_unit_cost.amount_rmb)} / ${this.escape(item.purchase_pricing_unit_cost.uom)}` : `<span class="ocw-mf-muted">单位换算未明确</span>`}</td></tr>`).join("") : `<tr><td colspan="8">暂无可试算物料</td></tr>`}</tbody></table></div>
      ${preview.excluded_fees?.length ? `<div class="ocw-mf-excluded"><strong>未计入费用</strong>${preview.excluded_fees.map((fee) => `<span>${this.escape(fee.expense_category || fee.fee_key || "费用")} · ${this.escape(this.materialFeeExclusionReason(fee))}</span>`).join("")}</div>` : ""}
      ${(preview.incomplete_reasons || []).filter((reason) => reason.item_key || reason.reason_code === "MATERIAL_ITEMS_REQUIRED").length ? `<div class="ocw-mf-excluded"><strong>物料待补</strong>${preview.incomplete_reasons.filter((reason) => reason.item_key || reason.reason_code === "MATERIAL_ITEMS_REQUIRED").map((reason) => `<span>${this.escape(items.find((item) => item.stable_line_key === reason.item_key)?.material_code || "")} ${this.escape(reason.message || "请补充物料资料")}</span>`).join("")}</div>` : ""}
      <details class="ocw-mf-allocation-notes"><summary>查看系统分摊说明</summary><p>已确认的项目规则优先按项目毛重，再按项目内发货行毛重分摊，缺项时不会切换依据。其他费用：海运与港杂优先按体积，空运与快递按计费重，配送按毛重，清关与税费按采购货值。适用物料的体积或重量不齐全时，整笔费用自动按完整的采购货值分摊。</p><ul>${allocationNotes || "<li>本次暂无已计入费用。</li>"}</ul></details>
      ${staleCost ? "</details>" : ""}
    </section>`;
  }

  renderMaterialFeeSourcesContent(candidates = [], context = {}, history = []) {
    const label = context.packing?.selected_source?.source_label || (context.root_kind === "expense" ? (context.separate_adoption ? "支付单据" : "采购支出") : "国际物流");
    const rows = candidates.map((row) => `<div><span><strong>${this.escape(row.source_label || row.file_name || row.attachment || "资料")}</strong><small>${this.escape(row.approval_no || "")} · ${this.escape(row.source_kind || row.source_type || "附件")}${row.sheet_name ? ` · ${this.escape(row.sheet_name)}` : ""} · ${row.excluded || row.available === false ? this.escape(row.exclude_reason || "资料待处理") : "当前来源"}</small>${row.cache_refreshed_at ? `<small>本地缓存：${this.escape(row.cache_refreshed_at)}</small>` : ""}${row.refresh_error ? `<small>上次刷新失败，资料待核对：${this.escape(row.refresh_error)}</small>` : ""}</span></div>`).join("");
    const old = history.map((row) => `<div><span><strong>${this.escape(row.file_name || "历史资料")}</strong><small>${this.escape(row.source_doc_no || "")} · 历史留存，不参与当前核算与 AI</small></span>${row.file_url ? `<button class="ocw-outline-btn ocw-mini-btn" data-mf-preview-source="1" data-file-url="${this.escape(row.file_url)}" data-file-name="${this.escape(row.file_name || "")}">查看历史附件</button>` : ""}</div>`).join("");
    return `<div class="ocw-mf-sources"><div class="ocw-mf-dialog-note"><strong>当前资料来源：${this.escape(label)}</strong><p>${context.separate_adoption ? "以下资料用于当前装箱、物料及 AI 分析；实际运费按已采用费用明细单独核对。" : "装箱、物料、费用及 AI 使用以下同一份资料清单。"}</p></div><div class="ocw-mf-source-actions"><button class="ocw-outline-btn" data-action="view-current-source">打开当前原单</button></div><div class="ocw-mf-source-list">${rows || '<div class="ocw-detail-empty"><strong>当前来源资料待补</strong></div>'}</div>${old ? `<details><summary>历史资料（${history.length}）</summary><div class="ocw-mf-source-list">${old}</div></details>` : ""}</div>`;
  }

  openMaterialFeeSourcesDialog() {
    const state = this.ensureMaterialFeeState();
    const dialog = new frappe.ui.Dialog({
      title: "查看资料来源",
      fields: [{ fieldtype: "HTML", fieldname: "sources", options: '<div class="ocw-detail-empty">正在读取当前来源…</div>' }],
      primary_action_label: "关闭", primary_action: () => dialog.hide(),
    });
    dialog.show(); dialog.$wrapper.addClass("ocw-mf-dialog");
    dialog.$wrapper.on("click", "[data-mf-preview-source]", (event) => {
      const $button = $(event.currentTarget);
      this.openOaAttachmentFilePreviewDialog($button.attr("data-file-url"), $button.attr("data-file-name"));
    });
    dialog.$wrapper.on("click", "[data-action='view-current-source']", () => {
      const data = state.settlementData;
      const sourceId = dialog.sourceContext?.root_source_id;
      const source = (data?.candidates || []).map(row => row.expense).find(row => row?.id === sourceId)
        || (data?.binding ? data.expense : data?.logistics);
      if (source?.open_url) this.openSettlementSource(source);
      else if (data?.binding || dialog.sourceContext?.root_kind === "expense") {
        frappe.show_alert({ message: "当前采购支出原单入口待补，请刷新关联资料。", indicator: "orange" });
      } else { dialog.hide(); this.switchDetailTab("dingtalk"); }
    });
    const batchName = this.detailState.batchName;
    const versionName = this.detailState.versionName || null;
    let open = true; dialog.onhide = () => { open = false; };
    const current = () => open && this.materialFeeState === state && this.detailState.batchName === batchName && (this.detailState.versionName || null) === versionName;
    this.call("overseas_costing.api.packing_api.list_current_source_documents", {
      batch_name: batchName, version_name: versionName,
    }, false).then((result) => {
      if (!current()) return;
      if (!result?.ok) throw new Error(result?.message || "资料清单读取失败");
      dialog.sourceContext = result.source_context || {};
      dialog.fields_dict.sources.$wrapper.html(this.renderMaterialFeeSourcesContent(result.items || [], result.source_context || {}, result.historical_items || []));
    }).catch((error) => {
      if (current()) dialog.fields_dict.sources.$wrapper.html(`<div class="ocw-detail-empty is-error">${this.escape(error.message || "当前资料读取失败，请重试")}</div>`);
    });
  }

  openMaterialXlsxUploader() {
    const batch = this.getDetailBatch();
    if (!frappe.ui.FileUploader) return this.showPendingFeature("当前无法打开上传器，请刷新后重试。");
    this.ensureEditSession().then((ready) => {
      if (!ready) return;
      new frappe.ui.FileUploader({
        allow_multiple: false,
        restrictions: { allowed_file_types: [".xlsx", ".xlsm", ".xls", ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".doc", ".docx"], max_file_size: 20 * 1024 * 1024 },
        on_success: (fileDoc) => {
          const uploaded = Array.isArray(fileDoc) ? fileDoc[0] : fileDoc;
          const fileName = String(uploaded?.file_name || uploaded?.name || "");
          if (fileName.toLowerCase().endsWith(".xls")) {
            this.showPendingFeature("暂不支持旧版 .xls，请先在 Excel 中另存为 .xlsx 后上传。");
            return;
          }
          this.registerManualDocumentAttachment(batch, this.detailDocumentAdapter(), this.detectManualDocumentLogisticsType(batch), {
            code: "material_packing_document",
            label: "本地上传装箱单",
            attachmentType: "Packing List",
            required: false,
          }, uploaded).then((registered) => {
            const attachment = registered?.attachment?.name;
            if (!attachment) return;
            this.openWikiMaterialImportDialog({ sourceTab: "local" }).then((sourceDialog) => {
              if ([".xlsx", ".xlsm"].some((suffix) => fileName.toLowerCase().endsWith(suffix))) {
                this.previewMaterialAttachmentSource(sourceDialog, attachment).catch((error) => this.showWikiMaterialSourceError(sourceDialog, error));
              } else {
                frappe.show_alert({ message: "装箱资料已加入，AI 将在后台分析", indicator: "green" });
                this.restartMaterialAIForChangedSources();
              }
            }).catch((error) => this.showError(error));
          }).catch((error) => this.showError(error));
        },
      });
      [0, 100, 300].forEach((delay) => window.setTimeout(() => this.localizeFrappeFileUploader("本地上传装箱单"), delay));
    }).catch((error) => this.showError(error));
  }

  async openWikiMaterialImportDialog(options = {}) {
    const dialog = new frappe.ui.Dialog({
      title: "获取装箱资料",
      fields: [{
        fieldtype: "HTML",
        fieldname: "wiki_sources",
        options: `<div class="ocw-mf-wiki-source-shell" data-area="mf-wiki-sources"><div class="ocw-detail-empty"><strong>正在读取装箱计划表</strong></div></div>`,
      }],
    });
    dialog.wikiMaterialSelectedSource = "";
    dialog.materialBatchName = this.detailState.batchName;
    dialog.materialVersionName = this.detailState.versionName;
    dialog.materialSourceTab = options.sourceTab || "wiki";
    dialog.materialAttachmentSources = [];
    dialog.wikiMaterialRefreshedSources = new Set();
    dialog.wikiMaterialWorkbooks = [];
    dialog.wikiMaterialBusy = "";
    dialog.wikiMaterialProgress = "";
    dialog.wikiMaterialOperationError = "";
    dialog.wikiMaterialClosed = false;
    dialog.wikiMaterialOpeningPreview = false;
    dialog.show();
    dialog.$wrapper.addClass("ocw-mf-dialog ocw-mf-wiki-dialog");
    dialog.$wrapper.on("hide.bs.modal.ocwMfWiki", () => {
      if (!dialog.wikiMaterialOpeningPreview) dialog.wikiMaterialClosed = true;
    });
    dialog.$wrapper
      .off(".ocwMfWiki")
      .on("click.ocwMfWiki", "[data-mf-source-tab]", (event) => {
        if (dialog.wikiMaterialBusy) return;
        dialog.materialSourceTab = $(event.currentTarget).attr("data-mf-source-tab");
        this.renderWikiMaterialSources(dialog);
      })
      .on("click.ocwMfWiki", "[data-mf-attachment-source]", (event) => {
        const $button = $(event.currentTarget);
        this.previewMaterialAttachmentSource(dialog, $button.attr("data-mf-attachment-source"), $button.attr("data-sheet-name") || "")
          .catch((error) => this.showWikiMaterialSourceError(dialog, error));
      })
      .on("click.ocwMfWiki", "[data-action='mf-source-upload']", () => {
        dialog.hide(); this.openMaterialXlsxUploader();
      })
      .on("click.ocwMfWiki", "[data-action='mf-source-reload']", () => {
        this.loadWikiMaterialSources(dialog).catch((error) => this.showWikiMaterialSourceError(dialog, error));
      })
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
      .on("click.ocwMfWiki", "[data-action='mf-wiki-refresh-all']", () => {
        this.refreshWikiMaterialCatalogs(dialog)
          .catch((error) => this.showWikiMaterialSourceError(dialog, error));
      })
      .on("click.ocwMfWiki", "[data-action='mf-wiki-preview-card']", (event) => {
        const $button = $(event.currentTarget);
        this.previewFreshWikiMaterialImport(
          dialog,
          $button.attr("data-workbook-id"),
          $button.attr("data-sheet-id"),
          $button.attr("data-source-id"),
        ).catch((error) => this.showWikiMaterialSourceError(dialog, error));
      })
      .on("click.ocwMfWiki", "[data-action='mf-wiki-cancel']", () => {
        dialog.wikiMaterialClosed = true;
        dialog.hide();
      });
    await this.loadWikiMaterialSources(dialog);
    return dialog;
  }

  async loadWikiMaterialSources(dialog, { preserveOnError = false } = {}) {
    const result = await this.call("overseas_costing.api.packing_api.list_packing_sources", {
      batch_name: this.detailState.batchName,
    }, true);
    const nextWorkbooks = result?.wiki_workbooks || [];
    const previousFingerprint = dialog.sourceContext?.fingerprint || "";
    dialog.sourceContext = result?.source_context || {};
    const sameSource = previousFingerprint === (dialog.sourceContext.fingerprint || "");
    if (!sameSource) {
      dialog.wikiMaterialSelectedSource = "";
      dialog.wikiMaterialSources = [];
      dialog.wikiMaterialWorkbooks = [];
      dialog.wikiMaterialPreview = null;
    }
    dialog.materialAttachmentSources = dialog.sourceContext.root_kind === "expense"
      ? [...(result?.approval_sources || [])].filter((row) => row.source_kind === "approval_attachment")
      : [...(result?.manual_attachments || [])];
    if (
      preserveOnError
      && sameSource
      && result?.wiki_error
      && !nextWorkbooks.length
      && (dialog.wikiMaterialSources || []).length
    ) {
      dialog.wikiMaterialError = result.wiki_error;
      if (!dialog.wikiMaterialClosed) this.renderWikiMaterialSources(dialog);
      return false;
    }
    dialog.wikiMaterialWorkbooks = nextWorkbooks;
    const sheets = dialog.wikiMaterialWorkbooks.flatMap((workbook) =>
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
    if (!dialog.wikiMaterialClosed) this.renderWikiMaterialSources(dialog);
    return true;
  }

  renderWikiMaterialSources(dialog) {
    const $target = dialog.$wrapper.find("[data-area='mf-wiki-sources']");
    if (dialog.materialSourceTab && dialog.materialSourceTab !== "wiki") {
      $target.html(this.renderMaterialSourceTabs(dialog) + this.renderMaterialAttachmentSources(dialog));
      return;
    }
    const sheets = dialog.wikiMaterialSources || [];
    const selectedId = String(dialog.wikiMaterialSelectedSource || "");
    const busy = String(dialog.wikiMaterialBusy || "");
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
        <div class="ocw-mf-wiki-card-meta"><span>${this.escape(status)}</span><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="mf-wiki-preview-card" data-source-id="${this.escape(sheet.source_id || "")}" data-workbook-id="${this.escape(sheet.workbook_id || "")}" data-sheet-id="${this.escape(sheetId)}" ${busy ? "disabled" : ""}>${busy === `sheet:${sheet.source_id}` ? "正在刷新…" : "预览"}</button></div>
      </article>`;
    }).join("");
    $target.html(`
      ${this.renderMaterialSourceTabs(dialog)}
      <div class="ocw-mf-wiki-toolbar">
        <label class="ocw-mf-wiki-search"><span>查找 Sheet</span><input type="search" data-action="mf-wiki-filter" placeholder="输入装箱单、日期或品类"></label>
        <button class="ocw-outline-btn" type="button" data-action="mf-wiki-refresh-all" ${busy ? "disabled" : ""}>${busy === "global" ? this.escape(dialog.wikiMaterialProgress || "正在刷新…") : "刷新最新数据"}</button>
      </div>
      ${dialog.wikiMaterialError ? `<div class="ocw-mf-wiki-error">${this.escape(dialog.wikiMaterialError)}</div>` : ""}
      ${dialog.wikiMaterialOperationError ? `<div class="ocw-mf-wiki-error">${this.escape(dialog.wikiMaterialOperationError)}</div>` : ""}
      <div class="ocw-mf-wiki-list">${cards || `<div class="ocw-detail-empty"><strong>暂无可用 Sheet</strong><span>请先确认服务端装箱计划表同步状态。</span></div>`}</div>
      <footer class="ocw-mf-import-sticky-footer"><span>${selectedId ? `已选：${this.escape((sheets.find((sheet) => String(sheet.source_id) === selectedId) || {}).source_label || selectedId)}` : "请选择一个 Sheet"}</span><div><button class="ocw-outline-btn" type="button" data-action="mf-wiki-cancel">取消</button></div></footer>
    `);
  }

  renderMaterialSourceTabs(dialog) {
    return `<div class="ocw-packing-source-tabs">${[["wiki", "装箱计划表"], ["local", dialog.sourceContext?.root_kind === "expense" ? "采购支出附件" : "本地上传装箱单"]].map(([key,label]) => `<button type="button" data-mf-source-tab="${key}" class="${(dialog.materialSourceTab || "wiki") === key ? "active" : ""}" ${dialog.wikiMaterialBusy ? "disabled" : ""}>${label}</button>`).join("")}</div>`;
  }

  renderMaterialAttachmentSources(dialog) {
    const bound = dialog.sourceContext?.root_kind === "expense";
    const rows = (dialog.materialAttachmentSources || []).filter((row) => row.source_kind === (bound ? "approval_attachment" : "manual_attachment"));
    const cards = rows.map((row) => {
      const sheets = row.sheets?.length ? row.sheets : [""];
      const semanticOnly = row.supported_for_material_import === false;
      const status = semanticOnly ? (row.available ? "可供 AI 识别" : "选择 AI 填充后自动获取并识别") : row.available ? "可预览" : ({ archived: "已归档，选择后自动获取", pending: "等待归档，可重试", manual_required: "需从钉钉下载后手动上传" }[row.archive_status] || "选择后获取附件");
      return `<article class="ocw-mf-wiki-card"><strong>${this.escape(row.source_label || row.source_id)}</strong><small>${this.escape(status)}</small><div class="ocw-mf-wiki-card-meta">${semanticOnly ? `<span>AI 资料</span>` : sheets.map((sheet) => `<button class="ocw-outline-btn" type="button" data-mf-attachment-source="${this.escape(row.source_id)}" data-sheet-name="${this.escape(sheet)}" ${dialog.wikiMaterialBusy ? "disabled" : ""}>${dialog.wikiMaterialBusy === `attachment:${row.source_id}` ? "正在获取…" : sheet ? `预览 ${this.escape(sheet)}` : row.available ? "预览" : "获取并预览"}</button>`).join("")}</div></article>`;
    }).join("");
    return `<div class="ocw-mf-wiki-toolbar"><span>${bound ? "当前资料来源：采购支出。正文、评论和附件也会纳入“AI 分析资料”。" : "本地装箱单；国际物流正文、附件和评论由 AI 自动收集。"}</span><button class="ocw-outline-btn" type="button" data-action="mf-source-reload" ${dialog.wikiMaterialBusy ? "disabled" : ""}>刷新来源</button>${bound ? "" : '<button class="ocw-primary-btn" type="button" data-action="mf-source-upload">本地上传装箱单</button>'}</div>${dialog.wikiMaterialOperationError ? `<div class="ocw-mf-wiki-error">${this.escape(dialog.wikiMaterialOperationError)}</div>` : ""}<div class="ocw-mf-wiki-list">${cards || `<div class="ocw-detail-empty"><strong>${bound ? "采购支出装箱附件待补" : "暂无本地装箱单"}</strong></div>`}</div>`;
  }

  async previewMaterialAttachmentSource(dialog, sourceId, sheetName = "") {
    if (dialog.wikiMaterialBusy) return;
    let source = (dialog.materialAttachmentSources || []).find((row) => row.source_id === sourceId);
    if (!source) throw new Error("资料来源已变化，请刷新来源列表。");
    const isCurrent = () => !dialog.wikiMaterialClosed && this.detailState.batchName === dialog.materialBatchName && this.detailState.versionName === dialog.materialVersionName;
    if (!isCurrent()) return;
    dialog.wikiMaterialBusy = `attachment:${sourceId}`;
    dialog.wikiMaterialOperationError = "";
    this.renderWikiMaterialSources(dialog);
    try {
      const attachment = source.attachment_name || source.source_id;
      if (!isCurrent()) return;
      let sheets = source.sheets || [];
      if (!sheets.length) {
        const catalog = await this.call("overseas_costing.api.packing_api.list_packing_attachment_sheets", {
          batch_name: dialog.materialBatchName, source_kind: source.source_kind, source_id: attachment,
        });
        if (!isCurrent()) return;
        if (catalog.source_context?.fingerprint !== dialog.sourceContext?.fingerprint) throw new Error("当前来源已变化，请关闭并重新获取资料。");
        sheets = catalog.sheets || [];
        source.sheets = sheets;
      }
      const selectedSheet = sheetName || (sheets.length === 1 ? sheets[0] : "");
      if (!selectedSheet) {
        if (!sheets.length) throw new Error("未读取到工作表，请检查文件或重新上传。");
        dialog.wikiMaterialOperationError = "文件包含多个工作表，请选择要导入的工作表。";
        return;
      }
      const preview = await this.call("overseas_costing.api.materials.preview_material_import", {
        batch_name: dialog.materialBatchName, source_kind: source.source_kind,
        source_id: attachment || source.source_id, sheet_name: selectedSheet || null,
      });
      if (!isCurrent()) return;
      if (!preview?.ok) throw new Error(preview?.message || "装箱资料预览失败。");
      dialog.wikiMaterialOpeningPreview = true;
      dialog.hide();
      this.openMaterialImportPreviewDialog(preview);
    } finally {
      dialog.wikiMaterialBusy = "";
      if (isCurrent() && !dialog.wikiMaterialOpeningPreview) this.renderWikiMaterialSources(dialog);
    }
  }

  showWikiMaterialSourceError(dialog, error) {
    dialog.wikiMaterialBusy = "";
    dialog.wikiMaterialProgress = "";
    dialog.wikiMaterialOperationError = this.normalizeErrorMessage(error);
    if (!dialog.wikiMaterialClosed) this.renderWikiMaterialSources(dialog);
  }

  async refreshWikiMaterialCatalogs(dialog) {
    if (dialog.wikiMaterialBusy) return;
    const workbooks = (dialog.wikiMaterialWorkbooks || []).filter((workbook) => workbook.workbook_id);
    if (!workbooks.length) throw new Error("没有可刷新的装箱计划年度表。");
    dialog.wikiMaterialBusy = "global";
    dialog.wikiMaterialOperationError = "";
    const failures = [];
    let succeeded = 0;
    try {
      for (let index = 0; index < workbooks.length; index += 1) {
        const workbook = workbooks[index];
        dialog.wikiMaterialProgress = `正在刷新 ${index + 1}/${workbooks.length}`;
        this.renderWikiMaterialSources(dialog);
        const requestId = this.packingFlowRequestId();
        try {
          await this.call("overseas_costing.api.packing_api.request_packing_workbook_refresh", {
            batch_name: this.detailState.batchName,
            workbook_id: workbook.workbook_id,
            request_id: requestId,
          }, false);
          await this.waitPackingRefresh(this.getDetailBatch(), requestId);
          succeeded += 1;
        } catch (error) {
          failures.push(`${workbook.label || workbook.workbook_id}：${this.normalizeErrorMessage(error)}`);
        }
      }
      const loaded = await this.loadWikiMaterialSources(dialog, { preserveOnError: true });
      if (!loaded) throw new Error(dialog.wikiMaterialError || "刷新后的装箱计划目录读取失败。");
      dialog.wikiMaterialOperationError = failures.length
        ? `部分装箱计划表刷新失败（${failures.length}/${workbooks.length}）：${failures.join("；")}`
        : "";
      if (succeeded) frappe.show_alert({ message: `已刷新 ${succeeded} 个装箱计划年度表`, indicator: "green" });
    } finally {
      dialog.wikiMaterialBusy = "";
      dialog.wikiMaterialProgress = "";
      if (!dialog.wikiMaterialClosed) this.renderWikiMaterialSources(dialog);
    }
  }

  async refreshWikiMaterialSource(dialog, workbookId, sheetId, sourceId) {
    if (!workbookId || !sheetId) throw new Error("无法识别需要刷新的装箱计划 Sheet。");
    const requestId = this.packingFlowRequestId();
    await this.call("overseas_costing.api.packing_api.request_packing_sheet_refresh", {
      batch_name: this.detailState.batchName,
      workbook_id: workbookId,
      sheet_id: sheetId,
      request_id: requestId,
    }, false);
    await this.waitPackingRefresh(this.getDetailBatch(), requestId);
    dialog.wikiMaterialRefreshedSources.add(String(sourceId || `${workbookId}:${sheetId}`));
    const loaded = await this.loadWikiMaterialSources(dialog, { preserveOnError: true });
    if (!loaded) throw new Error(dialog.wikiMaterialError || "刷新后的 Sheet 目录读取失败。");
  }

  async previewFreshWikiMaterialImport(dialog, workbookId, sheetId, sourceId) {
    if (dialog.wikiMaterialBusy) return;
    const normalizedSourceId = String(sourceId || "");
    if (!normalizedSourceId) throw new Error("无法识别需要预览的装箱计划 Sheet。");
    dialog.wikiMaterialSelectedSource = normalizedSourceId;
    dialog.wikiMaterialBusy = `sheet:${normalizedSourceId}`;
    dialog.wikiMaterialOperationError = "";
    this.renderWikiMaterialSources(dialog);
    try {
      if (!dialog.wikiMaterialRefreshedSources.has(normalizedSourceId)) {
        await this.refreshWikiMaterialSource(dialog, workbookId, sheetId, normalizedSourceId);
      }
      if (dialog.wikiMaterialClosed) return;
      await this.previewWikiMaterialImport(dialog, normalizedSourceId);
    } finally {
      dialog.wikiMaterialBusy = "";
      if (!dialog.wikiMaterialClosed && !dialog.wikiMaterialOpeningPreview) {
        this.renderWikiMaterialSources(dialog);
      }
    }
  }

  async previewWikiMaterialImport(sourceDialog, requestedSourceId = "") {
    const sourceId = String(requestedSourceId || sourceDialog.wikiMaterialSelectedSource || "");
    if (!sourceId) throw new Error("请先选择装箱计划 Sheet。");
    const result = await this.call("overseas_costing.api.materials.preview_material_import", {
      batch_name: this.detailState.batchName,
      source_kind: "wiki_sheet",
      source_id: sourceId,
      sheet_name: null,
    }, true);
    if (!result || !result.ok) throw new Error(result?.message || "装箱计划表预览失败");
    if (sourceDialog.wikiMaterialClosed) return;
    sourceDialog.wikiMaterialOpeningPreview = true;
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
    const isGrid = isWiki || Boolean(preview.source_grid?.cells?.length);
    const dialog = new frappe.ui.Dialog({
      title: isWiki ? "装箱计划表导入预览" : "Excel 导入预览",
      fields: [{ fieldtype: "HTML", fieldname: "preview", options: isGrid ? this.renderWikiMaterialImportPreview(preview) : `<div class="ocw-mf-import-preview"><div class="ocw-mf-import-summary"><span>可补充 <strong>${preview.summary?.supplement || 0}</strong></span><span>冲突 <strong>${preview.summary?.conflict || 0}</strong></span><span>未匹配 <strong>${preview.summary?.unmatched || 0}</strong></span><span>不会新增未知行</span></div><div class="ocw-mf-import-table"><table><thead><tr><th>源行</th><th>分类</th><th>物料</th><th>字段变化 / 处理</th></tr></thead><tbody>${rows.map((row) => `<tr class="is-${this.escape(row.classification || "unmatched")}"><td>${this.escape(row.source_row || "--")}</td><td>${this.escape({ supplement: "可补充", conflict: "冲突", unmatched: "未匹配", no_change: "无变化" }[row.classification] || row.classification || "--")}</td><td>${this.escape(row.incoming?.material_code || "--")}${row.match_status === "choice_required" ? `<select data-mf-match-row="${this.escape(row.source_row)}"><option value="">请选择原行</option>${(row.candidates || []).map((candidate) => `<option value="${this.escape(candidate.stable_line_key || "")}">行 ${this.escape(candidate.row_no || "--")} · ${this.escape(candidate.material_code || "--")}</option>`).join("")}</select>` : ""}</td><td>${(row.changes || []).length ? row.changes.map((change) => `<div><span>${this.escape(change.field)}：${this.escape(this.formatValue(change.old ?? "--"))} → ${this.escape(this.formatValue(change.new ?? "--"))}</span>${change.conflict ? `<select data-mf-conflict-row="${this.escape(row.source_row)}" data-fieldname="${this.escape(change.field)}"><option value="keep_current">保留当前值</option><option value="use_source">采用 Excel</option></select>` : ""}</div>`).join("") : "--"}</td></tr>`).join("")}</tbody></table></div><div class="ocw-mf-dialog-note">仅补充发货数量、单位、重量、体积、计费重和项目归属；OA 采购事实不被覆盖。</div></div>` }],
      primary_action_label: isGrid ? undefined : "确认整体导入",
      primary_action: isGrid ? undefined : () => this.applyMaterialXlsxImport(dialog, preview),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-mf-dialog ocw-mf-import-dialog");
    if (!isGrid && preview.source_context?.root_kind === "expense") {
      dialog.fields_dict.preview.$wrapper.prepend(this.renderCurrentSourceReviewControls(preview.source_context, preview.cargo_review));
    }
    if (isGrid) {
      this.setupPackingSpreadsheetDialog(dialog, preview);
      dialog.$wrapper
        .on("click", "[data-action='mf-wiki-import-cancel']", () => dialog.hide())
        .on("click", "[data-action='mf-wiki-import-confirm']", () => {
          this.confirmPackingSpreadsheet(dialog).catch((error) => this.showError(error));
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
    return this.renderPackingSpreadsheetPreview(preview);
  }

  async applyMaterialXlsxImport(dialog, preview) {
    return this.applyMaterialImport(dialog, preview);
  }

  collectMaterialImportChoices(dialog, preview) {
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
    if (preview.merge_reviews) choices.merge_reviews = preview.merge_reviews;
    return choices;
  }

  async applyMaterialImport(dialog, preview) {
    const choices = this.collectMaterialImportChoices(dialog, preview);
    if (preview.source_context?.root_kind === "expense") {
      const sourceReview = this.collectCurrentSourceReviewControls(dialog.$wrapper);
      choices.confirm_complete_cargo = sourceReview.complete_cargo;
      choices._source_review = sourceReview;
    }
    const validationError = this.validateWikiMaterialAllocations(preview, choices);
    if (validationError) throw new Error(validationError);
    if (!(await this.ensureEditSession()) || dialog._pg?.closed) return;
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
        source_grid: result.merged_preview.source_grid || preview.source_grid,
        merge_reviews: result.merged_preview.merge_reviews || preview.merge_reviews,
        preview_revision: preview.preview_revision,
        merged_preview_hash: result.merged_preview_hash,
      };
      dialog._ocwMaterialPreview = mergedPreview;
      dialog.fields_dict.preview.$wrapper.html(this.renderWikiMaterialImportPreview(mergedPreview));
      if (dialog._pg) this.switchPackingPreviewTab(dialog, "result");
      frappe.show_alert({ message: "已生成合并后的最终预览，请核对后确认写入", indicator: "blue" });
      return;
    }
    if (!result || !result.ok) {
      const messages = {
        ALLOCATION_REQUIRED: "请填写所有合箱物料的净重、毛重和体积。",
        ALLOCATION_TOTAL_MISMATCH: "合箱分配合计与来源整箱数据不一致。",
        GROUP_CONFIRMATION_REQUIRED: "请确认所有候选合并包装组。",
        MERGE_REVIEW_REQUIRED: "请返回原表核对黄色边框的合并范围。",
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
    if (dialog._pg) dialog._pg.allowClose = true;
    dialog.hide();
    frappe.show_alert({ message: result.review_saved ? `已采用采购支出货物清单，共 ${preview.cargo_review?.rows?.length || 0} 行` : `已更新 ${result.updated_count || 0} 行、${result.changed_field_count || 0} 个字段`, indicator: "green" });
    await this.loadMaterialFeeWorkspace({ quiet: true });
    if (!result.review_saved) this.restartMaterialAIForChangedSources();
  }

  validateWikiMaterialAllocations(preview, choices) {
    for (const group of preview.confirmation_groups || []) {
      if (group.source_correction_required) return `第 ${(group.row_numbers || []).join("、")} 行的真实合并跨度矛盾，请修正原表后重新预览。`;
    }
    for (const group of preview.shared_groups || []) {
      if (group.allocation_required === false) continue;
      const groupLabel = `第 ${(group.row_numbers || []).join("、")} 行共箱`;
      const values = choices.allocations?.[group.group_id] || {};
      for (const [fieldname, metric] of Object.entries(group.metrics || {})) {
        const rawValues = (group.participants || []).map((participant) => String(values?.[participant.source_key]?.[fieldname] ?? "").trim());
        if (rawValues.some((value) => value === "")) return `请完整填写 ${groupLabel} 的${this.materialImportFieldLabel(fieldname)}。`;
        const numbers = rawValues.map((value) => Number(value));
        if (numbers.some((value) => !Number.isFinite(value) || value < 0)) return `请完整填写 ${groupLabel} 的${this.materialImportFieldLabel(fieldname)}。`;
        const precision = Math.max(0, Number(metric.precision || 0));
        const factor = 10 ** precision;
        const actual = Math.round(numbers.reduce((sum, value) => sum + value, 0) * factor);
        const expected = Math.round(Number(metric.value || 0) * factor);
        if (actual !== expected) return `${groupLabel} 的${this.materialImportFieldLabel(fieldname)}分配合计应为 ${metric.value}。`;
      }
    }
    for (const group of preview.confirmation_groups || []) {
      if (preview.source_grid?.cells?.length || choices.group_confirmations?.[group.group_id] !== true) return `请返回原表核对第 ${(group.row_numbers || []).join("、")} 行的合并关系。`;
    }
    for (const issue of preview.source_validation?.blocking || []) {
      if (issue.confirmation_required && choices.source_validation?.[issue.confirmation_key] !== true) return `请先确认：${issue.message || issue.code}。`;
      if (!issue.confirmation_required) return issue.message || "原表存在待修正数据，请核对来源单元格。";
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
