  erpSiteLabel(siteCode = "") {
    const code = String(siteCode || "");
    const configs = ((this.detailState.erpPush || {}).site_configs || []);
    const config = configs.find((row) => String(row.site_code || "") === code) || {};
    return config.label ? `${config.label} (${code})` : code || "未知站点";
  }

  erpRequestKey(prefix = "erp") {
    if (window.crypto && typeof window.crypto.randomUUID === "function") return `${prefix}:${window.crypto.randomUUID()}`;
    return `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}`;
  }

  renderErpSitePanel(batch = {}) {
    const push = this.detailState.erpPush || this.detailState.detail?.erp_push || {};
    const work = this.detailState.erpWork || this.detailState.detail?.erp_work || {};
    const previewSites = ((push.preview || {}).sites || []);
    const workBySite = Object.fromEntries((work.sites || []).map((site) => [String(site.site_code || ""), site]));
    const siteCodes = [...new Set([
      ...previewSites.map((site) => String(site.site_code || "")),
      ...(work.sites || []).map((site) => String(site.site_code || "")),
    ].filter(Boolean))];
    const overall = OverseasCostWorkbenchState.erpWorkPresentation(work);
    const feeSummary = OverseasCostWorkbenchState.summarizeFeeWork(this.detailState.feeWork || batch.fee_work || {});
    const blockers = push.blocking || [];
    const canCreate = OverseasCostWorkbenchState.erpCreateCanStart(push);
    const retryable = OverseasCostWorkbenchState.erpRetryableSites(work);
    const updateRequired = (work.sites || []).some((site) => String(site.state || "") === "UPDATE_REQUIRED");
    const siteCards = siteCodes.map((siteCode) => {
      const sitePreview = previewSites.find((site) => String(site.site_code || "") === siteCode) || {};
      const siteWork = workBySite[siteCode] || { site_code: siteCode, state: "CREATE_REQUIRED" };
      const presentation = OverseasCostWorkbenchState.erpWorkPresentation({ overall: siteWork.state });
      const totalQuantity = (sitePreview.groups || []).reduce((sum, group) => sum + Number(group.total_quantity || 0), 0);
      const documents = (siteWork.remote_documents || []).length
        ? (siteWork.remote_documents || []).map((name) => `<span>${this.escape(name)}</span>`).join("")
        : `<span class="is-empty">尚无目标单据</span>`;
      const estimated = sitePreview.estimated_fee_keys || [];
      const retry = retryable.find((row) => row.siteCode === siteCode);
      return `
        <article class="ocw-erp-site-card">
          <header><div><small>目标站点</small><strong>${this.escape(this.erpSiteLabel(siteCode))}</strong></div><span class="ocw-erp-site-status is-${presentation.tone}">${this.escape(presentation.label)}</span></header>
          <div class="ocw-erp-site-metrics">
            <span><small>物料数</small><b>${Number((sitePreview.groups || []).reduce((sum, group) => sum + Number(group.item_count || 0), 0))}</b></span>
            <span><small>发货数量</small><b>${this.escape(this.formatNumber(totalQuantity) || "0")}</b></span>
            <span><small>分摊费用</small><b>${this.escape(this.formatMoney(sitePreview.allocated_fee_rmb || 0))} RMB</b></span>
            <span><small>综合金额</small><b>${this.escape(this.formatMoney(sitePreview.total_cost_rmb || 0))} RMB</b></span>
          </div>
          <div class="ocw-erp-site-meta"><span>当前成本哈希 <code>${this.escape(siteWork.last_hash || work.current_hash || "尚未生成")}</code></span><span>目标单据 ${documents}</span></div>
          ${estimated.length ? `<div class="ocw-erp-estimated"><strong>暂估费用</strong>${estimated.map((key) => `<span>${this.escape(key)}</span>`).join("")}<small>可先推送，实际金额到账后再更新成本。</small></div>` : ""}
          ${siteWork.todo ? `<p class="ocw-erp-site-todo">${this.escape(siteWork.todo.label || "待处理")}</p>` : ""}
          ${retry ? `<footer><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="erp-retry-site" data-request-id="${this.escape(retry.requestId)}" data-site-code="${this.escape(siteCode)}">只重试失败站点</button></footer>` : ""}
        </article>`;
    }).join("");
    return `
      <section class="ocw-erp-site-panel">
        <div class="ocw-erp-site-panel-head">
          <div><span>ERP 分站点处理</span><h2>项目归属与推送</h2><p>成本先在本批次统一计算，推送时再按物料所属子公司进入不同 ERP 站点。</p></div>
          <span class="ocw-erp-site-status is-${overall.tone}">${this.escape(overall.label)}</span>
        </div>
        <div class="ocw-erp-panel-actions">
          <button class="ocw-outline-btn" type="button" data-action="erp-bulk-route">整批归属</button>
          <button class="ocw-primary-btn" type="button" data-action="erp-create-preview">按站点推送预览</button>
          ${updateRequired ? `<button class="ocw-outline-btn" type="button" data-action="erp-update-preview">预览实际费用更新</button>` : ""}
        </div>
        ${blockers.length ? `<div class="ocw-erp-blockers"><strong>当前可预览成本，但不能推送 ERP</strong>${blockers.map((row) => `<span>${this.escape(row.message || row.code || "请补齐资料")}</span>`).join("")}</div>` : ""}
        ${siteCards ? `<div class="ocw-erp-site-grid">${siteCards}</div>` : `<div class="ocw-erp-site-empty"><strong>尚未形成站点分组</strong><span>先在物料表补齐项目归属，或使用“整批归属”预览变更。</span></div>`}
        <div class="ocw-erp-fee-reminder ${feeSummary.todoCount ? "has-todo" : "is-done"}"><strong>费用待办仍需单独处理</strong><span>${feeSummary.todoCount ? `当前还有 ${feeSummary.affectedFeeCount} 笔费用、${feeSummary.todoCount} 项待办；ERP 站点成功不会自动消除。` : "当前费用待办已处理完。"}</span><button class="ocw-link-btn" type="button" data-action="erp-open-fees">查看费用与凭证</button></div>
        <p class="ocw-erp-action-note">${canCreate ? "推送前会再显示本次冻结的站点、数量和金额，确认后才会发起。" : "请先处理上方阻断项；当前综合单价仍可查看。"}</p>
      </section>`;
  }

  async openBulkErpRouteDialog() {
    const batch = this.getDetailBatch();
    const route = await this.call("overseas_costing.api.erp_sync.get_route_preview", {
      batch_name: batch.name,
      version_name: this.detailState.versionName || null,
    });
    const options = (route.site_options || (this.detailState.erpPush || {}).site_configs || []).filter((site) => site.enabled !== 0);
    if (!options.length) throw new Error("尚未配置可用 ERP 站点。");
    const dialog = new frappe.ui.Dialog({
      title: "整批归属·先看差异",
      fields: [
        { fieldtype: "Select", fieldname: "site_code", label: "目标站点", options: options.map((site) => site.site_code).join("\n"), reqd: 1 },
        { fieldtype: "HTML", fieldname: "preview", options: `<div class="ocw-erp-route-help">会将本批所有物料指向一个站点；不拆数量、不修改项目名、不重算费用。</div>` },
      ],
      primary_action_label: "预览差异",
      primary_action: async (values) => {
        try {
          const preview = await this.call("overseas_costing.api.erp_sync.preview_bulk_route", {
            batch_name: batch.name,
            target_site_code: values.site_code,
          });
          dialog.erpRoutePreview = preview;
          const changes = Object.entries(preview.updates || {});
          dialog.fields_dict.preview.$wrapper.html(`
            <div class="ocw-erp-route-diff">
              <header><strong>${this.escape(this.erpSiteLabel(values.site_code))}</strong><span>${changes.length} 行将变更，${(preview.unchanged_item_keys || []).length} 行无变化</span></header>
              ${preview.requires_confirmation ? `<p>其中 ${(preview.overwritten_item_keys || []).length} 行会覆盖现有站点，请确认差异。</p>` : ""}
              <div>${changes.slice(0, 100).map(([key, change]) => `<span><code>${this.escape(key)}</code><b>→</b><strong>${this.escape(change.subsidiary_code || "--")} · ${this.escape(change.erp_site_code || "--")}</strong></span>`).join("")}</div>
              <button class="ocw-primary-btn" type="button" data-action="erp-apply-bulk-route" ${changes.length ? "" : "disabled"}>确认采用这个归属</button>
            </div>`);
        } catch (error) {
          this.showError(error);
        }
      },
    });
    dialog.show();
    dialog.$wrapper.on("click.ocwErpRoute", "[data-action='erp-apply-bulk-route']", async () => {
      try {
        if (!(await this.ensureEditSession())) return;
        const preview = dialog.erpRoutePreview || {};
        const result = await this.call("overseas_costing.api.erp_sync.apply_bulk_route", {
          batch_name: batch.name,
          preview_revision: preview.preview_revision,
          edit_token: this.detailState.editToken,
          expected_modified: this.detailState.expectedModified || batch.modified || "",
        }, true);
        if (!result?.ok) throw new Error(result?.message || "整批归属保存失败。");
        dialog.hide();
        await this.refreshDetailSummary();
        frappe.show_alert({ message: `已更新 ${Number((result.changed_item_keys || []).length)} 行 ERP 归属`, indicator: "green" });
      } catch (error) {
        this.showError(error);
      }
    });
  }

  renderErpCreatePreview(preview = {}) {
    const push = preview.erp_push || {};
    const sites = (push.preview || {}).sites || [];
    const blockers = push.blocking || [];
    return `
      <div class="ocw-erp-push-preview">
        <div class="ocw-erp-preview-summary"><strong>按站点推送预览</strong><span>${sites.length} 个站点 · ${Number((push.preview || {}).group_count || 0)} 张目标单据分组</span></div>
        ${sites.map((site) => `<article><header><strong>${this.escape(this.erpSiteLabel(site.site_code))}</strong><span>${Number(site.group_count || 0)} 个分组</span></header><div><span>采购货值 <b>${this.escape(this.formatMoney(site.goods_value_rmb || 0))} RMB</b></span><span>分摊费用 <b>${this.escape(this.formatMoney(site.allocated_fee_rmb || 0))} RMB</b></span><span>综合金额 <b>${this.escape(this.formatMoney(site.total_cost_rmb || 0))} RMB</b></span></div>${(site.groups || []).map((group) => `<p>${this.escape(group.supplier || "未标供应商")} · ${this.escape(group.currency || "--")} · ${this.escape(group.stock_uom || "--")} · 数量 ${this.escape(group.total_quantity || "0")}</p>`).join("")}${(site.estimated_fee_keys || []).length ? `<footer><strong>暂估费用</strong>${(site.estimated_fee_keys || []).map((key) => `<span>${this.escape(key)}</span>`).join("")}</footer>` : ""}</article>`).join("")}
        ${blockers.length ? `<div class="ocw-erp-blockers"><strong>推送前必须补齐</strong>${blockers.map((row) => `<span>${this.escape(row.message || row.code)}</span>`).join("")}</div>` : ""}
        <button class="ocw-primary-btn" type="button" data-action="erp-confirm-create" ${OverseasCostWorkbenchState.erpCreateCanStart(push) ? "" : "disabled"}>确认推送到 ${sites.length} 个站点</button>
      </div>`;
  }

  async openErpCreatePreview(batchName = "") {
    const batch = this.findBatch(batchName) || this.getDetailBatch();
    const preview = await this.call("overseas_costing.api.erp_sync.preview_erp_sync", {
      batch_name: batch.name,
      version_name: this.detailState.versionName || batch.current_version || null,
    });
    const dialog = new frappe.ui.Dialog({
      title: "ERP 分站点推送确认",
      fields: [{ fieldtype: "HTML", fieldname: "content", options: this.renderErpCreatePreview(preview) }],
    });
    dialog.show();
    dialog.$wrapper.on("click.ocwErpCreate", "[data-action='erp-confirm-create']", async (event) => {
      const $button = $(event.currentTarget).prop("disabled", true).text("正在按站点推送…");
      try {
        const push = preview.erp_push || {};
        const result = await this.call("overseas_costing.api.erp_sync.start_erp_create", {
          batch_name: batch.name,
          cost_result_hash: push.cost_result_hash,
          request_key: this.erpRequestKey("create"),
        }, true);
        if (!result?.ok && !["PARTIAL", "FAILED", "UNCERTAIN"].includes(String(result?.status || ""))) {
          throw new Error(result?.message || result?.code || "ERP 推送未启动。");
        }
        dialog.hide();
        await this.refreshDetailSummary();
        frappe.show_alert({ message: result.status === "SUCCESS" ? "ERP 各站点已同步" : "ERP 站点部分完成，请在页面中查看待办", indicator: result.status === "SUCCESS" ? "green" : "orange" });
        this.pollErpSyncStatus(batch.name, push.cost_result_hash).catch((error) => this.showError(error));
      } catch (error) {
        $button.prop("disabled", false).text("确认推送");
        this.showError(error);
      }
    });
  }

  renderErpUpdatePreview(preview = {}) {
    return `
      <div class="ocw-erp-update-preview">
        <p>只更新费用和综合成本字段，不会修改采购/发货数量。</p>
        ${(preview.sites || []).map((site) => `<article><label><input type="checkbox" data-role="erp-update-site" value="${this.escape(site.site_code)}" checked />${this.escape(this.erpSiteLabel(site.site_code))}</label>${(site.items || []).map((item) => `<div><code>${this.escape(item.stable_line_key || "")}</code><span>旧金额 <b>${this.escape(this.formatMoney((item.old || {}).total_cost_rmb || 0))}</b></span><i>→</i><span>新金额 <b>${this.escape(this.formatMoney((item.new || {}).total_cost_rmb || 0))}</b></span><small>${this.escape((item.changed_fields || []).join("、"))}</small></div>`).join("")}</article>`).join("")}
        ${(preview.blocking || []).length ? `<div class="ocw-erp-blockers"><strong>需人工处理</strong>${(preview.blocking || []).map((row) => `<span>${this.escape(row.message || row.code)}</span>`).join("")}</div>` : ""}
        <button class="ocw-primary-btn" type="button" data-action="erp-confirm-update" ${preview.ready && (preview.sites || []).length ? "" : "disabled"}>确认更新所选站点</button>
      </div>`;
  }

  async openErpUpdatePreview() {
    const batch = this.getDetailBatch();
    const push = this.detailState.erpPush || {};
    const work = this.detailState.erpWork || {};
    const hashes = [...new Set((work.sites || []).map((site) => String(site.last_hash || "")).filter(Boolean))];
    if (hashes.length !== 1) throw new Error(hashes.length ? "各站点当前成本版本不一致，需人工处理。" : "尚无可更新的 ERP 历史结果。");
    const preview = await this.call("overseas_costing.api.erp_sync.preview_erp_updates", {
      batch_name: batch.name,
      from_hash: hashes[0],
      to_hash: push.cost_result_hash,
    });
    const dialog = new frappe.ui.Dialog({
      title: "ERP 实际费用更新差异",
      fields: [{ fieldtype: "HTML", fieldname: "content", options: this.renderErpUpdatePreview(preview) }],
    });
    dialog.show();
    dialog.$wrapper.on("click.ocwErpUpdate", "[data-action='erp-confirm-update']", async (event) => {
      const selected = dialog.$wrapper.find("[data-role='erp-update-site']:checked").get().map((node) => $(node).val());
      const accepted = OverseasCostWorkbenchState.erpUpdateSelection(preview, selected);
      if (!accepted.length) return frappe.show_alert({ message: "请至少选择一个本次预览中的站点", indicator: "orange" });
      const $button = $(event.currentTarget).prop("disabled", true);
      try {
        const result = await this.call("overseas_costing.api.erp_sync.start_erp_updates", {
          batch_name: batch.name,
          to_hash: push.cost_result_hash,
          accepted_site_codes_json: JSON.stringify(accepted),
          request_key: this.erpRequestKey("update"),
        }, true);
        if (!result?.ok && String(result?.status || "") !== "PARTIAL") throw new Error(result?.message || result?.code || "ERP 成本更新失败。");
        dialog.hide();
        await this.refreshDetailSummary();
        frappe.show_alert({ message: result.status === "SUCCESS" ? "所选 ERP 站点成本已更新" : "部分站点更新未完成", indicator: result.status === "SUCCESS" ? "green" : "orange" });
      } catch (error) {
        $button.prop("disabled", false);
        this.showError(error);
      }
    });
  }

  async retryErpSite(requestId = "", siteCode = "") {
    const batch = this.getDetailBatch();
    const result = await this.call("overseas_costing.api.erp_sync.retry_erp_request", {
      batch_name: batch.name,
      request_id: requestId,
    }, true);
    if (!result?.ok && String(result?.status || "") !== "PARTIAL") {
      const manual = String(result?.status || "") === "MANUAL_REQUIRED" ? "需人工处理" : (result?.message || result?.code || "重试失败");
      throw new Error(`${this.erpSiteLabel(siteCode)}：${manual}`);
    }
    await this.refreshDetailSummary();
    const succeeded = String(result.status || "") === "SUCCESS";
    frappe.show_alert({ message: succeeded ? `${this.erpSiteLabel(siteCode)} 已完成安全重试` : `${this.erpSiteLabel(siteCode)} 重试后仍有待办`, indicator: succeeded ? "green" : "orange" });
  }

  async pollErpSyncStatus(batchName, expectedHash, attempt = 0) {
    if (attempt > 20 || this.detailState.batchName !== batchName) return;
    const currentHash = String((this.detailState.erpPush || {}).cost_result_hash || "");
    if (currentHash && currentHash !== String(expectedHash || "")) return this.refreshDetailSummary();
    const status = await this.call("overseas_costing.api.erp_sync.get_erp_sync_status", { batch_name: batchName });
    if (this.detailState.batchName !== batchName) return;
    this.detailState.erpWork = status.erp_work || this.detailState.erpWork;
    const pending = (this.detailState.erpWork.sites || []).some((site) => ["PENDING", "RUNNING"].includes(String(site.status || site.state || "").toUpperCase()));
    if (!pending) return this.refreshDetailSummary();
    await new Promise((resolve) => window.setTimeout(resolve, 1500));
    return this.pollErpSyncStatus(batchName, expectedHash, attempt + 1);
  }
