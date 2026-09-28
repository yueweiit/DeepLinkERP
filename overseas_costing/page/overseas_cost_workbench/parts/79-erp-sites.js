  /**
   * 多站点 ERP 同步界面：站点级冻结预览、账本状态、只重试失败站点。
   *
   * 服务端这条链（`preview_site_sync_plan` / `save_site_sync_plan` /
   * `get_site_sync_requests` / `reconcile_erp_request` / `retry_erp_request`）早已就绪，
   * 缺的只是界面。站点、公司、仓库、单据分组、可推送与否全部取自服务端返回值：
   * 站点是 `project_collection` 经服务端路由解析出来的，前端复算一定会漂。
   */
  ensureErpSiteState() {
    const batchName = String(this.detailState?.batchName || this.drawerBatchName || this.activeBatchName || "");
    if (!this.erpSiteState || this.erpSiteState.batchName !== batchName) {
      this.erpSiteState = {
        batchName,
        plan: null,
        ledger: null,
        failure: "",
        loading: false,
        requestId: 0,
        inFlight: new Set(),
      };
    }
    return this.erpSiteState;
  }

  /**
   * 同步状态的中文标签与色调。取值只认服务端给的那几个。
   *
   * `MANUAL_REQUIRED` 是"远端单据要人去认领"，必须落在 warn 上 —— 渲染成成功会让
   * 人以为可以收工，而远端可能压根没建单。
   */
  erpSiteStatusMeta(status) {
    const table = {
      PENDING: { label: "待推送", tone: "pending" },
      RUNNING: { label: "推送中", tone: "pending" },
      SUCCESS: { label: "已推送", tone: "done" },
      FAILED: { label: "推送失败", tone: "error" },
      UNCERTAIN: { label: "结果待核对", tone: "warn" },
      MANUAL_REQUIRED: { label: "需人工处理", tone: "warn" },
      SUPERSEDED: { label: "已被新版本取代", tone: "muted" },
    };
    const key = String(status || "").trim().toUpperCase();
    return table[key] || { label: key || "未知状态", tone: "muted" };
  }

  erpSiteIsReconcilable(status) {
    // 与服务端 RECONCILABLE_STATUSES 对齐：其余状态没有"核对/重试"这回事。
    return ["FAILED", "UNCERTAIN"].includes(String(status || "").trim().toUpperCase());
  }

  /** 还欠处理的请求（成功的和被取代的不再占地方，其余都要露出来，含 MANUAL_REQUIRED）。 */
  erpSiteNeedsAttention(row = {}) {
    return !["SUCCESS", "SUPERSEDED"].includes(String(row.status || "").trim().toUpperCase());
  }

  /**
   * 一条请求的"下一步该干什么"。
   *
   * 只有 FAILED / UNCERTAIN 能核对重试（服务端 `RECONCILABLE_STATUSES` 只认这两个，其余
   * 状态调过去会被直接判成 `SKIP`），所以别给必然被拒的按钮 —— `MANUAL_REQUIRED` 是终态，
   * 写清"不会再自动重试"比放个点了没用的按钮诚实。
   */
  erpSiteLedgerHint(row = {}) {
    if (this.erpSiteIsReconcilable(row.status)) return "";
    const status = String(row.status || "").trim().toUpperCase();
    if (status === "PENDING" || status === "RUNNING") return "推送队列处理中，稍后刷新状态即可。";
    return "该请求已定论，不会再自动重试；请在 ERP 侧处理后再刷新状态。";
  }

  /** 把服务端站点预览归一成渲染用的形状，缺失字段一律兜空，别让模板崩。 */
  erpSitePlanPreview(plan = {}) {
    const preview = plan?.push_state?.preview || {};
    const sites = Array.isArray(preview.sites) ? preview.sites : [];
    return {
      sites: sites.map((site) => {
        const groups = Array.isArray(site.groups) ? site.groups : [];
        return {
          site_code: String(site.site_code || ""),
          groups,
          itemCount: groups.reduce((total, group) => total + (Array.isArray(group.items) ? group.items.length : 0), 0),
          companies: [...new Set(groups.map((group) => String(group.subsidiary_code || "")).filter(Boolean))],
          total_cost_rmb: site.total_cost_rmb || 0,
          allocated_fee_rmb: site.allocated_fee_rmb || 0,
        };
      }),
      blocking: Array.isArray(preview.blocking) ? preview.blocking : [],
      sourceTotalRmb: preview.source_total_cost_rmb || 0,
      previewTotalRmb: preview.preview_total_cost_rmb || 0,
      sourceFeeRmb: preview.source_fee_total_rmb || 0,
      previewFeeRmb: preview.preview_allocated_fee_rmb || 0,
      complete: plan?.complete !== false,
      ready: plan?.ready === true,
      hash: String(plan?.cost_result_hash || ""),
    };
  }

  /** 账本按站点分组，方便和预览里的站点对齐。 */
  erpSiteLedgerBySite(ledger = {}) {
    const grouped = {};
    (Array.isArray(ledger.items) ? ledger.items : []).forEach((row) => {
      const site = String(row.site_code || "");
      (grouped[site] ||= []).push(row);
    });
    return grouped;
  }

  erpSiteStatusCounts(rows = []) {
    const counts = {};
    rows.forEach((row) => {
      const key = String(row.status || "").trim().toUpperCase() || "PENDING";
      counts[key] = (counts[key] || 0) + 1;
    });
    return counts;
  }

  renderErpSiteStatusChips(rows = []) {
    const counts = this.erpSiteStatusCounts(rows);
    if (!Object.keys(counts).length) return `<span class="ocw-erp-sites-chip is-muted">尚无推送记录</span>`;
    return Object.entries(counts).map(([status, count]) => {
      const meta = this.erpSiteStatusMeta(status);
      return `<span class="ocw-erp-sites-chip is-${this.escape(meta.tone)}">${this.escape(meta.label)} ${this.escape(String(count))}</span>`;
    }).join("");
  }

  renderErpSiteHash(hash = "") {
    const text = String(hash || "");
    if (!text) return `<span class="ocw-erp-sites-hash is-muted">无结果哈希</span>`;
    return `<span class="ocw-erp-sites-hash" title="${this.escape(text)}">结果哈希 ${this.escape(text.slice(0, 12))}</span>`;
  }

  /**
   * 读取站点同步计划与本地账本。
   *
   * 账本读失败（例如成本还没确认，服务端拿不到推送上下文）不算整块失败：
   * 预览仍要能显示，否则用户看不到"为什么推不了"。
   */
  async loadErpSiteSync({ batchName = "", readLedger = true } = {}) {
    const batch = this.findBatch(batchName || this.drawerBatchName || this.activeBatchName || this.detailState?.batchName || "");
    if (!batch) return null;
    const state = this.ensureErpSiteState();
    const requestId = ++state.requestId;
    state.loading = true;
    this.renderErpSitePanelInto();
    try {
      const plan = await this.call("overseas_costing.api.writeback.preview_site_sync_plan", {
        batch_name: batch.name,
        version_name: batch.current_version || null,
      });
      if (requestId !== state.requestId) return null;
      state.plan = plan || null;
      state.failure = "";
      if (readLedger && plan?.batch_name) {
        try {
          const ledger = await this.call("overseas_costing.api.writeback.get_site_sync_requests", {
            batch_name: batch.name,
            version_name: batch.current_version || null,
            limit: 100,
          });
          if (requestId !== state.requestId) return null;
          state.ledger = ledger && ledger.ok !== false ? ledger : null;
        } catch (error) {
          console.warn("[overseas-cost-workbench] ERP 站点账本读取失败", error);
          state.ledger = null;
        }
      }
      return state.plan;
    } catch (error) {
      if (requestId !== state.requestId) return null;
      state.plan = null;
      state.ledger = null;
      state.failure = this.normalizeErrorMessage?.(error) || String(error?.message || error || "站点同步状态读取失败");
      return null;
    } finally {
      if (requestId === state.requestId) {
        state.loading = false;
        this.renderErpSitePanelInto();
      }
    }
  }

  /**
   * 详情页概览里的站点面板。只有成本已确认（或正处于 ERP 队列）才出现 ——
   * 146 个未确认批次不该多出一块永远空的区域。
   */
  renderDetailErpSites(batch = {}) {
    if (!this.erpSitePanelVisible(batch)) return "";
    return `<section class="ocw-erp-sites" data-area="detail-erp-sites">${this.renderErpSiteStatusPanel()}</section>`;
  }

  erpSitePanelVisible(batch = {}) {
    const status = [batch.confirm_status, batch.status].map((value) => String(value || "").toLowerCase());
    return status.some((value) => value.includes("confirmed")) || this.viewState?.task === "erp";
  }

  renderErpSitePanelInto() {
    const $area = this.$root.find("[data-area='detail-erp-sites']");
    if (!$area.length) return;
    $area.html(this.renderErpSiteStatusPanel());
  }

  async refreshErpSitePanel() {
    const batch = this.getDetailBatch?.();
    if (!batch || !this.erpSitePanelVisible(batch)) return;
    await this.loadErpSiteSync({ batchName: batch.name });
    this.renderErpSitePanelInto();
  }

  renderErpSiteStatusPanel() {
    const state = this.ensureErpSiteState();
    if (state.loading && !state.plan) {
      return `<div class="ocw-erp-sites-loading">正在读取站点同步状态…</div>`;
    }
    if (state.failure) {
      return `
        <div class="ocw-erp-sites-head"><div><span>ERP 站点推送</span><strong>状态读取失败</strong></div>
          <div class="ocw-erp-sites-actions"><button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="erp-site-refresh">重试</button></div>
        </div>
        <p class="ocw-erp-sites-note is-error">${this.escape(state.failure)}</p>`;
    }
    const plan = state.plan;
    if (!plan) {
      return `
        <div class="ocw-erp-sites-head"><div><span>ERP 站点推送</span><strong>尚未生成同步草稿</strong></div>
          <div class="ocw-erp-sites-actions">
            <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="erp-site-refresh">刷新</button>
            <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="erp-site-preview">站点推送预览</button>
          </div>
        </div>`;
    }
    const preview = this.erpSitePlanPreview(plan);
    const ledgerBySite = this.erpSiteLedgerBySite(state.ledger || {});
    const rows = preview.sites.map((site) => {
      const ledgerRows = ledgerBySite[site.site_code] || [];
      const companyText = site.companies.length ? site.companies.join(" / ") : "--";
      return `
        <tr>
          <td><strong>${this.escape(site.site_code || "--")}</strong>${site.site_code ? `<small>${this.escape(companyText)}</small>` : ""}</td>
          <td>${this.escape(String(site.groups.length))} 组 / ${this.escape(String(site.itemCount))} 行</td>
          <td>${this.escape(this.formatMoney(site.total_cost_rmb))}</td>
          <td>${this.escape(this.formatMoney(site.allocated_fee_rmb))}</td>
          <td>${this.renderErpSiteStatusChips(ledgerRows)}</td>
        </tr>`;
    }).join("");
    const pendingRows = (state.ledger?.items || []).filter((row) => this.erpSiteNeedsAttention(row));
    const blockingNote = preview.complete
      ? ""
      : `<p class="ocw-erp-sites-note is-warn">还有 ${this.escape(String(preview.blocking.length))} 个物料组未通过路由、供应商或仓库门槛，不会随本次推送发出。</p>`;
    return `
      <div class="ocw-erp-sites-head">
        <div>
          <span>ERP 站点推送</span>
          <strong>${this.escape(String(preview.sites.length))} 个站点 · ${this.escape(String(preview.sites.reduce((total, site) => total + site.groups.length, 0)))} 个单据组 · ${this.escape(this.formatMoney(preview.previewTotalRmb))} RMB</strong>
          <small>${preview.ready ? "已通过推送门槛" : "存在阻断项，暂不能推送"}${preview.complete ? "" : " · 仅部分可推送"}</small>
        </div>
        <div class="ocw-erp-sites-actions">
          <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="erp-site-refresh">刷新状态</button>
          <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="erp-site-preview">站点推送预览</button>
        </div>
      </div>
      <div class="ocw-erp-sites-scroll">
        <table class="ocw-erp-sites-table">
          <thead><tr><th>站点 / ERP 公司</th><th>目标单据</th><th>综合成本</th><th>分摊费用</th><th>推送状态</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="5" class="ocw-erp-sites-empty">当前没有可推送的站点分组</td></tr>`}</tbody>
        </table>
      </div>
      ${blockingNote}
      ${pendingRows.length ? `
        <div class="ocw-erp-sites-ledger">
          <h4>需要处理的推送请求（${this.escape(String(pendingRows.length))} 条）</h4>
          <ul>${pendingRows.map((row) => this.renderErpSiteLedgerRow(row)).join("")}</ul>
        </div>` : ""}
    `;
  }

  renderErpSiteLedgerRow(row = {}) {
    const meta = this.erpSiteStatusMeta(row.status);
    const requestId = String(row.request_id || "");
    const reason = String(row.error_message || row.error_code || "").trim();
    const retries = Number(row.attempt_count || 0);
    const hint = this.erpSiteLedgerHint(row);
    const actions = hint
      ? `<span class="ocw-erp-sites-hint">${this.escape(hint)}</span>`
      : `
          <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="erp-site-reconcile" data-request-id="${this.escape(requestId)}">核对远端</button>
          <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="erp-site-retry" data-request-id="${this.escape(requestId)}">核对后重试</button>`;
    return `
      <li class="ocw-erp-sites-ledger-row">
        <div>
          <strong>${this.escape(String(row.site_code || "--"))}</strong>
          <span class="ocw-erp-sites-state is-${this.escape(meta.tone)}">${this.escape(meta.label)}</span>
          ${retries ? `<em>已尝试 ${this.escape(String(retries))} 次</em>` : ""}
          <small>${this.renderErpSiteHash(row.cost_result_hash)}</small>
          ${reason ? `<p>${this.escape(reason)}</p>` : ""}
        </div>
        <div class="ocw-erp-sites-ledger-actions">${actions}</div>
      </li>`;
  }

  /** 冻结预览：推送前把要发到哪些站点/公司、多少钱、哪些行被拦，一次摊开。 */
  renderErpSiteSyncPreview(plan = {}) {
    const preview = this.erpSitePlanPreview(plan);
    const estimated = this.erpEstimatedFeeCount();
    const cards = preview.sites.map((site) => {
      const groups = site.groups.map((group) => `
        <tr>
          <td>${this.escape(String(group.subsidiary_code || "--"))}</td>
          <td>${this.escape(String(group.supplier || "未设置"))}</td>
          <td>${this.escape(String(group.warehouse || "--"))}</td>
          <td>${this.escape(String(group.purchase_currency || "CNY"))} / ${this.escape(String(group.erp_stock_uom || "--"))}</td>
          <td>${this.escape(String((group.items || []).length))} 行</td>
          <td>${this.escape(this.formatMoney(group.total_cost_rmb))}</td>
        </tr>`).join("");
      return `
        <article class="ocw-erp-site-card">
          <header>
            <div><span>站点</span><strong>${this.escape(site.site_code || "--")}</strong></div>
            <div><span>ERP 公司</span><strong>${this.escape(site.companies.join(" / ") || "--")}</strong></div>
            <div><span>单据组</span><strong>${this.escape(String(site.groups.length))}</strong></div>
            <div><span>物料行</span><strong>${this.escape(String(site.itemCount))}</strong></div>
            <div><span>综合成本</span><strong>${this.escape(this.formatMoney(site.total_cost_rmb))}</strong></div>
          </header>
          <table class="ocw-erp-site-groups">
            <thead><tr><th>ERP 公司</th><th>供应商</th><th>收货仓库</th><th>币种 / 单位</th><th>行数</th><th>综合成本</th></tr></thead>
            <tbody>${groups || `<tr><td colspan="6" class="ocw-erp-sites-empty">该站点没有可推送的分组</td></tr>`}</tbody>
          </table>
        </article>`;
    }).join("");
    return `
      <div class="ocw-erp-sites-preview">
        <div class="ocw-erp-sites-preview-summary">
          <div><span>站点</span><strong>${this.escape(String(preview.sites.length))}</strong></div>
          <div><span>单据组</span><strong>${this.escape(String(preview.sites.reduce((total, site) => total + site.groups.length, 0)))}</strong></div>
          <div><span>物料行</span><strong>${this.escape(String(preview.sites.reduce((total, site) => total + site.itemCount, 0)))}</strong></div>
          <div><span>综合成本</span><strong>${this.escape(this.formatMoney(preview.previewTotalRmb))} RMB</strong></div>
          <div><span>分摊费用</span><strong>${this.escape(this.formatMoney(preview.previewFeeRmb))} RMB</strong></div>
        </div>
        <p class="ocw-erp-sites-note">${this.renderErpSiteHash(preview.hash)} —— 确认后按这个哈希生成幂等请求，重复点击不会在远端多建一张采购单。</p>
        ${estimated ? `<p class="ocw-erp-sites-note is-warn">本次含 ${this.escape(String(estimated))} 项暂估费用；实际费用出来后需要另行更新远端成本。</p>` : ""}
        ${preview.complete ? "" : `<p class="ocw-erp-sites-note is-warn">另有 ${this.escape(String(preview.blocking.length))} 个物料组未通过路由、供应商或仓库门槛，本次不会发出；补齐后可再次推送。</p>`}
        ${cards || `<p class="ocw-erp-sites-note is-warn">当前没有可推送的站点分组。</p>`}
      </div>`;
  }

  /** 暂估费用计数只读已加载的费用状态，不为它额外发一次请求。 */
  erpEstimatedFeeCount() {
    const fees = this.materialFeeState?.fees?.fees;
    if (!Array.isArray(fees)) return 0;
    return fees.filter((fee) => String(fee.amount_state || fee.amount_status || "").toUpperCase() === "ESTIMATED").length;
  }

  async openErpSiteSyncDialog(batchName = "") {
    const batch = this.findBatch(batchName || this.drawerBatchName || this.activeBatchName || "");
    if (!batch) return null;
    const plan = await this.loadErpSiteSync({ batchName: batch.name });
    if (!plan) return null;
    if (!plan.ready) {
      // 阻断原因与待补资料继续走既有弹窗，不在这里另造一套文案。
      this.showErpFlowBlock({ ...plan, batch_name: batch.name }, "暂不能推送 ERP");
      return null;
    }
    const sizes = this.erpSitePlanPreview(plan).sites.length;
    let pushing = false;
    const dialog = new frappe.ui.Dialog({
      title: `ERP 站点推送预览（${sizes} 个站点）`,
      fields: [{ fieldtype: "HTML", fieldname: "plan", options: this.renderErpSiteSyncPreview(plan) }],
      primary_action_label: "确认并推送",
      primary_action: async () => {
        // 双击不该变成第二次业务：第一条推送没回来之前直接吞掉后续点击。
        if (pushing) return;
        pushing = true;
        dialog.hide();
        try {
          await this.queueErpWriteback(batch.name);
        } catch (error) {
          this.showError(error);
        } finally {
          pushing = false;
        }
      },
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-erp-site-dialog");
    return dialog;
  }

  async reconcileErpSiteRequest(requestId = "") {
    return this.runErpSiteRequestAction({
      requestId,
      action: "reconcile",
      busyLabel: "正在核对远端单据",
      method: "overseas_costing.api.writeback.reconcile_erp_request",
      done: (result) => {
        const meta = this.erpSiteStatusMeta(result?.status);
        return `远端核对结果：${meta.label}${result?.remote_docname ? `（${result.remote_docname}）` : ""}`;
      },
    });
  }

  async retryErpSiteRequest(requestId = "") {
    return this.runErpSiteRequestAction({
      requestId,
      action: "retry",
      busyLabel: "正在核对远端并重试",
      method: "overseas_costing.api.writeback.retry_erp_request",
      done: (result) => String(result?.message || "重试请求已处理。"),
    });
  }

  /**
   * 核对/重试共用的入口：同一个按钮不可能连点两次发出两次请求。
   *
   * 重试本身会先在服务端核对远端，这里不做任何"跳过核对直接重发"的快捷路径 ——
   * 远端已经建单的情况下重发会在 ERP 里多出一张采购单。
   */
  async runErpSiteRequestAction({ requestId = "", action = "", busyLabel = "", method = "", done = null } = {}) {
    const id = String(requestId || "");
    if (!id) return null;
    const state = this.ensureErpSiteState();
    const key = `${action}:${id}`;
    if (state.inFlight.has(key)) return null;
    state.inFlight.add(key);
    frappe.show_alert?.({ message: busyLabel || "处理中", indicator: "blue" });
    try {
      const result = await this.call(method, { batch_name: state.batchName, request_id: id }, true);
      const ok = result?.ok !== false;
      frappe.show_alert?.({
        message: ok ? (done?.(result) || "已处理") : String(result?.message || "请求未处理成功"),
        indicator: ok ? "green" : "orange",
      });
      if (ok) {
        this.recordUsage?.("PUSH_ERP", { batch: this.findBatch(state.batchName), remark: `ERP 请求${action === "retry" ? "重试" : "核对"}：${id}` });
      }
      await this.loadErpSiteSync({ batchName: state.batchName });
      return result;
    } catch (error) {
      this.showError(error);
      return null;
    } finally {
      state.inFlight.delete(key);
      this.renderErpSitePanelInto();
    }
  }
