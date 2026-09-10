  settlementApi(action, args = {}) {
    return this.call(`overseas_costing.api.logistics_settlement.${action}`, args);
  }

  settlementAmount(source = {}) {
    if (Array.isArray(source.fees) && source.fees.length) {
      return source.fees.map((fee) => `${fee.label || "费用"} ${fee.amount ?? "未识别"} ${fee.currency || source.currency || "币种待核对"}`).join("；");
    }
    return source.amount !== null && source.amount !== undefined && source.amount !== ""
      ? `${source.amount} ${source.currency || "币种待核对"}` : "金额未识别";
  }

  settlementAdoption(data = {}) {
    if (data.historical) return data.binding ? "历史采用来源 · 仅供追溯" : "历史版本 · 尚未采用物流采购支出";
    if (!data.binding) return "未关联采购支出";
    if (data.expense?.invalid) return "来源已失效 · 暂停采用";
    if (!data.expense?.approved) return "已关联 · 待审批通过";
    if (data.source_context?.fingerprint && data.application?.source_context?.fingerprint !== data.source_context.fingerprint) return "已关联 · 当前资料待采用";
    return ({ applied: "费用已采用 · 以当前试算结果为准", applied_pending: "费用已采用 · 资料／汇率待核对",
      queued: "已关联 · 编辑结束后重试采用", invalid: "来源已失效 · 暂停采用", pending: "已关联 · 费用待采用" })[data.binding.application_status] || "已关联 · 费用待采用";
  }

  settlementSelection(candidate, choices = {}) {
    if (!["pending", "conflict"].includes(candidate.status)) throw new Error("候选状态已变化，请刷新后复核。");
    const reason = String(choices.reason || "").trim();
    if (candidate.status === "conflict" && !reason) throw new Error("冲突关联须逐条填写确认依据。");
    return { id: candidate.id, revision: candidate.revision, resolve: candidate.status === "conflict", reason,
      ...(choices.coverage?.length ? { coverage: choices.coverage } : {}), negative_confirmed: choices.negative_confirmed === true };
  }

  settlementDialog(title, extraFields = [], fieldsFirst = false) {
    const body = { fieldtype: "HTML", fieldname: "settlement_body", options: "正在读取本地资料…" };
    const dialog = new frappe.ui.Dialog({ title, size: "extra-large", fields: [
      ...(fieldsFirst ? [...extraFields, body] : [body, ...extraFields]),
      { fieldtype: "HTML", fieldname: "settlement_actions", options: "" },
    ], primary_action_label: "关闭", primary_action: () => dialog.hide() });
    const state = { dialog, open: true, request: 0, timer: null, busy: false };
    dialog.onhide = () => this.stopSettlementDialog(state);
    dialog.$wrapper.on("hide.bs.modal.ocwSettlement", (event) => {
      if (event.target === dialog.$wrapper.get(0)) this.stopSettlementDialog(state);
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-settlement-modal");
    return state;
  }

  stopSettlementDialog(state) {
    state.open = false;
    state.request += 1;
    clearTimeout(state.timer);
    state.timer = null;
  }

  settlementBody(state, html) {
    if (state.open) state.dialog.fields_dict.settlement_body.$wrapper.html(html);
  }

  settlementActions(state, html) {
    if (state.open) state.dialog.fields_dict.settlement_actions.$wrapper.html(html);
  }

  settlementNotice(state, message, error = false) {
    if (!state.open) return;
    const $body = state.dialog.fields_dict.settlement_body.$wrapper;
    $body.find("[data-settlement-notice]").remove();
    $body.prepend(`<div class="ocw-settlement-notice ${error ? "is-error" : ""}" data-settlement-notice role="status">${this.escape(message)}</div>`);
  }

  settlementEvents(state, handler) {
    state.dialog.$wrapper.off("click.ocwSettlement").on("click.ocwSettlement", "[data-settlement-action]", async (event) => {
      event.preventDefault();
      if (!state.open || state.busy) return;
      const $button = $(event.currentTarget);
      try { await handler($button.attr("data-settlement-action"), $button); }
      catch (error) { this.settlementNotice(state, error.message || "操作失败，请刷新后重试。", true); }
    });
  }

  async settlementWrite(state, action) {
    if (!state.open || state.busy) return;
    state.busy = true;
    clearTimeout(state.timer);
    state.request += 1;
    state.dialog.$wrapper.find("button,input,select,textarea").prop("disabled", true);
    try { return await action(); }
    finally {
      state.busy = false;
      if (state.open) state.dialog.$wrapper.find("button,input,select,textarea").prop("disabled", false);
    }
  }

  async openSettlementHistory(start = false) {
    if (this.settlementHistoryState?.open) {
      this.settlementHistoryState.dialog.show();
      return;
    }
    const state = this.settlementDialog("历史采购支出匹配");
    Object.assign(state, { after: null, pages: [], status: "pending", selected: new Set(), data: {} });
    this.settlementHistoryState = state;
    this.settlementEvents(state, async (action, $button) => {
      if (action === "start") return this.startSettlementHistory(state);
      if (action === "refresh") return this.loadSettlementHistory(state);
      if (action === "pause" || action === "retry") {
        await this.settlementWrite(state, () => this.settlementApi("control_job", { job_id: state.jobId, action }));
        return this.loadSettlementHistory(state);
      }
      if (action === "filter") {
        state.status = $button.attr("data-status"); state.after = null; state.pages = []; state.selected.clear();
        return this.loadSettlementHistory(state);
      }
      if (action === "next" || action === "previous") {
        if (action === "next") { state.pages.push(state.after); state.after = state.data.next_cursor; }
        else state.after = state.pages.pop() ?? null;
        state.selected.clear();
        return this.loadSettlementHistory(state);
      }
      if (action === "review") {
        const candidate = (state.data.candidates || []).find((row) => row.id === $button.attr("data-id"));
        if (candidate) this.openSettlementCandidateReview([candidate], { history: state });
      }
      if (action === "review-selected") {
        const rows = (state.data.candidates || []).filter((row) => row.status === "pending" && state.selected.has(`${row.id}:${row.revision}`));
        if (!rows.length) throw new Error("请先勾选本页待确认候选。冲突需逐条复核。");
        this.openSettlementCandidateReview(rows, { history: state });
      }
    });
    state.dialog.fields_dict.settlement_body.$wrapper.on("change.ocwSettlement", "[data-settlement-select]", (event) => {
      const key = $(event.currentTarget).attr("data-settlement-select");
      if (event.currentTarget.checked) state.selected.add(key); else state.selected.delete(key);
    });
    if (start) await this.startSettlementHistory(state);
    else await this.loadSettlementHistory(state);
  }

  async startSettlementHistory(state) {
    try {
      this.settlementBody(state, "正在启动历史匹配… 此操作不使用近期拉取的日期、运输方式或条数限制。");
      const result = await this.settlementWrite(state, () => this.settlementApi("start_history_matching", {}));
      if (!state.open) return;
      if (!result?.ok) throw new Error(result?.message || "历史匹配启动失败");
      state.jobId = result.job?.id;
      state.after = null; state.pages = []; state.selected.clear();
      await this.loadSettlementHistory(state);
    } catch (error) {
      this.settlementBody(state, '<button class="ocw-outline-btn" data-settlement-action="start">重试历史匹配</button>');
      this.settlementNotice(state, error.message || "启动失败", true);
    }
  }

  async loadSettlementHistory(state) {
    if (!state.open || state.busy) return;
    clearTimeout(state.timer);
    const request = ++state.request;
    try {
      const result = await this.settlementApi("get_matching_status", { job_id: state.jobId || null, after: state.after || null, status: state.status || "pending" });
      if (!state.open || request !== state.request) return;
      if (!result?.ok) throw new Error(result?.message || "读取历史匹配失败");
      state.data = result;
      state.jobId = result.job?.id || state.jobId;
      this.renderSettlementHistory(state, result);
      if (["queued", "running"].includes(result.job?.status)) {
        state.timer = setTimeout(() => this.loadSettlementHistory(state), 3000);
      }
    } catch (error) {
      if (!state.open || request !== state.request) return;
      this.settlementBody(state, '<button class="ocw-outline-btn" data-settlement-action="refresh">重新读取</button>');
      this.settlementNotice(state, error.message || "读取失败", true);
    }
  }

  renderSettlementHistory(state, data) {
    const job = data.job || {};
    const labels = { queued: "排队中", running: "进行中", completed: "本轮完成", partial: "部分失败", paused: "已暂停", failed: "失败" };
    const phases = { inventory: "扫描历史来源", load: "整理资料", match: "生成候选", finished: "已结束" };
    const candidates = data.candidates || [];
    const scope = data.health?.scope_counts;
    this.settlementBody(state, `
      <p class="ocw-settlement-hint">采购支出先按「服务类采购 → 物流及运输服务」筛选：采购支出＝服务类采购，且服务类采购＝物流及运输服务；不限定海运、空运、快递等下级运输方式。再与历史国际物流匹配，忽略近期拉取的日期及条数。候选需确认后才建立关联。</p>
      ${scope ? `<p class="ocw-settlement-hint">上次范围核对：国际物流 ${this.escape(scope.logistics)} · 物流类采购支出 ${this.escape(scope.expense)}（审批通过 ${this.escape(scope.approved_expense)}）· 不符合分类 ${this.escape(scope.excluded)}。未通过审批的单据不作为最终核算依据。</p>` : ''}
      ${this.renderSettlementHealth(data)}
      <div class="ocw-settlement-toolbar"><strong>${this.escape(labels[job.status] || "尚未启动")} · ${this.escape(phases[job.phase] || "等待任务")}</strong>
        <span>已处理 ${this.escape(job.processed_count ?? 0)} / 本轮读取来源 ${this.escape(job.item_count ?? 0)}${job.excluded_count ? ` · 旧清单已排除 ${this.escape(job.excluded_count)}` : ''} · 失败 ${this.escape(job.failed_count ?? data.failures?.length ?? 0)}</span>
        ${!job.id || ["completed"].includes(job.status) ? '<button class="ocw-primary-btn" data-settlement-action="start">一键匹配历史采购支出</button>' : ""}
        ${["running", "queued"].includes(job.status) ? '<button class="ocw-outline-btn" data-settlement-action="pause">暂停</button>' : ""}
        ${["paused", "partial", "failed"].includes(job.status) ? '<button class="ocw-outline-btn" data-settlement-action="retry">继续／重试失败项</button>' : ""}
        <button class="ocw-outline-btn" data-settlement-action="refresh">刷新</button>
      </div>
      <p class="ocw-settlement-hint">关闭窗口后停止页面轮询，后台任务继续。暂停会在当前小批处理后生效。</p>
      <div class="ocw-settlement-toolbar">${[["pending", "待确认"], ["conflict", "冲突"], ["confirmed", "已关联"], ["rejected", "已忽略"]].map(([key, label]) => `<button class="${state.status === key ? "ocw-primary-btn" : "ocw-outline-btn"}" data-settlement-action="filter" data-status="${key}">${label} ${this.escape(data.counts?.[key] ?? 0)}</button>`).join("")}<span>未匹配 ${this.escape(data.counts?.unmatched ?? 0)}</span></div>
      ${job.error ? `<p class="ocw-settlement-notice is-error">${this.escape(job.error)}</p>` : ""}
      ${data.failures?.length ? `<details><summary>失败明细（${data.failures.length}，最多显示 50 条）</summary>${data.failures.map((row) => `<p>${this.escape(row.source_id || row.id)}：${this.escape(row.error || "整理失败")}</p>`).join("")}</details>` : ""}
      <div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table"><thead><tr><th>选择</th><th>国际物流审批</th><th>采购支出审批</th><th>费用</th><th>匹配依据</th><th>操作</th></tr></thead><tbody>${candidates.map((row) => `<tr>
        <td>${row.status === "pending" ? `<input type="checkbox" aria-label="选择候选" data-settlement-select="${this.escape(`${row.id}:${row.revision}`)}" ${state.selected.has(`${row.id}:${row.revision}`) ? "checked" : ""}>` : "—"}</td>
        <td>${this.escape(row.logistics?.approval_no || row.logistics?.instance)}</td><td>${this.escape(row.expense?.approval_no || row.expense?.instance)}<small>${this.escape(row.expense?.status || "审批状态待核对")}</small></td>
        <td>${this.escape(this.settlementAmount(row.expense || {}))}</td><td>${this.escape(row.reason || row.method || "待复核")}</td><td><button class="ocw-outline-btn" data-settlement-action="review" data-id="${this.escape(row.id)}">${row.status === "conflict" ? "逐条处理冲突" : "查看复核"}</button></td></tr>`).join("") || '<tr><td colspan="6">本页没有候选。未匹配来源可在对应批次中搜索关联。</td></tr>'}</tbody></table></div>
      <div class="ocw-settlement-toolbar">${state.status === "pending" ? '<button class="ocw-primary-btn" data-settlement-action="review-selected">复核所选并批量确认</button>' : ""}
        ${state.pages?.length ? '<button class="ocw-outline-btn" data-settlement-action="previous">上一页</button>' : ""}${data.has_more ? '<button class="ocw-outline-btn" data-settlement-action="next">下一页</button>' : ""}<span>每页最多 50 条</span></div>`);
  }

  renderSettlementHealth(data = {}) {
    const upstream = data.health?.health || {};
    const error = upstream.last_error || data.health?.last_error || data.health?.error;
    return `<div class="ocw-settlement-hint">本地同步：${this.escape(data.sync?.last_success || "未知／未同步")} · 上游归档最近成功：${this.escape(upstream.last_success_at || "未知／未同步")}
      <br>待归档 ${this.escape(upstream.pending_count ?? "未知")} · 待重试 ${this.escape(upstream.retry_count ?? "未知")} · 需人工处理 ${this.escape(upstream.manual_required_count ?? "未知")}
      ${data.pending_failure_count !== undefined ? ` · 未解决任务失败 ${this.escape(data.pending_failure_count)}` : ""}${data.control?.enabled === false ? " · 后台同步已暂停" : ""}
      ${error ? `<p class="ocw-settlement-notice is-error">最近异常：${this.escape(error)}</p>` : ""}</div>`;
  }

  renderSettlementSource(source = {}, heading = "采购支出") {
    return `<section class="ocw-settlement-source"><h4>${this.escape(heading)}</h4><strong>${this.escape(source.approval_no || source.instance || "尚未关联")}</strong>
      <p>${this.escape(source.status || "状态待核对")} · ${source.invalid ? "来源失效" : source.approved ? "审批已通过" : "尚未审批通过"}</p>
      <p>${this.escape(this.settlementAmount(source))}</p>
      <small>${source.fees?.length ? "采用费用明细，不叠加审批总额。" : source.amount !== null && source.amount !== undefined && source.amount !== "" ? "未识别费用明细，使用总额；范围需核对。" : "尚未识别明确费用或总额，请核对原单。"} 更新：${this.escape(source.source_updated_at || "未提供")}</small>
      ${(source.issues || []).map((issue) => `<p class="ocw-settlement-notice">${this.escape(typeof issue === "string" ? issue : JSON.stringify(issue))}</p>`).join("")}</section>`;
  }

  renderSettlementComparison(logistics = {}, expense = {}, labels = {}) {
    const goods = (source) => (source.goods || []).map((row) => `<tr>${[row.material_code, row.product_name, row.spec_model, row.quantity, row.unit].map((value) => `<td>${this.escape(value ?? "—")}</td>`).join("")}</tr>`).join("");
    const signature = (source) => JSON.stringify((source.goods || []).map((row) => [row.material_code, row.product_name, row.spec_model, String(row.quantity ?? ""), row.unit]));
    return `<details class="ocw-settlement-comparison" open><summary>货物与来源核对 · ${!logistics.goods?.length || !expense.goods?.length ? "一方或双方货物尚未识别，请核对原单" : signature(logistics) === signature(expense) ? "识别字段一致" : "存在差异，采用前请核对"}</summary>
      <div class="ocw-settlement-source-grid">${[[logistics, labels.left || "国际物流货物"], [expense, labels.right || "采购支出货物"]].map(([source, title]) => `<div><h4>${this.escape(title)}</h4><div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table"><thead><tr><th>物料</th><th>品名</th><th>规格</th><th>数量</th><th>单位</th></tr></thead><tbody>${goods(source) || '<tr><td colspan="5">未识别货物行，需核对原单资料</td></tr>'}</tbody></table></div></div>`).join("")}</div>
      <p class="ocw-settlement-hint">确认关联后，物料、数量、装箱资料和费用统一采用采购支出。商品单价缺失时才补充原商品采购价格。</p></details>`;
  }

  settlementChoiceFields(source = {}, currentCoverage = []) {
    const fields = [{ fieldtype: "Small Text", fieldname: "settlement_reason", label: "确认／更正依据", description: "冲突、更正和忽略须填写；普通候选可填写核对说明。" }];
    if (source.coverage === "unknown" || currentCoverage.length) {
      fields.push({ fieldtype: "HTML", fieldname: "coverage_note", options: `<p class="ocw-settlement-notice">${currentCoverage.length ? "下方保留了原关联的覆盖范围；请对照当前原单重新核对，必要时取消旧范围。" : "费用覆盖范围不明确：请按原单选择。"}当前费用统一采用采购支出；勾选项说明它的覆盖范围，未确认时保留关联并等待采用。</p>` });
      for (const [key, label] of this.settlementCoverageOptions()) fields.push({ fieldtype: "Check", fieldname: `coverage_${key}`, label, default: currentCoverage.includes(key) ? 1 : 0 });
    }
    const negative = (source.fees?.length ? source.fees : [{ amount: source.amount }]).some((row) => Number(row.amount) < 0);
    if (negative) fields.push({ fieldtype: "Check", fieldname: "negative_confirmed", label: "已核对负数为退款／冲销，并确认采用" });
    return fields;
  }

  settlementCoverageOptions() {
    return [["freight", "国际运输费"], ["customs", "清关费"], ["tax", "税费"], ["mexico_inland", "墨西哥内陆费"]];
  }

  settlementChoices(state) {
    return { reason: String(state.dialog.get_value("settlement_reason") || "").trim(),
      coverage: this.settlementCoverageOptions().filter(([key]) => state.dialog.get_value(`coverage_${key}`)).map(([key]) => key),
      negative_confirmed: Boolean(state.dialog.get_value("negative_confirmed")) };
  }

  openSettlementCandidateReview(candidates, context = {}) {
    const single = candidates.length === 1;
    const candidate = candidates[0];
    const editable = candidates.every((row) => ["pending", "conflict"].includes(row.status));
    const state = this.settlementDialog(context.correction ? "更正关联 · 核对旧单与新单" : "确认采购支出关联", context.correction
      ? [{ fieldtype: "Small Text", fieldname: "settlement_reason", label: "更正依据", description: "更正后如费用范围或负数待核对，请在批次中继续处理。" }]
      : single ? this.settlementChoiceFields(candidate.expense) : []);
    this.settlementBody(state, `<p class="ocw-settlement-hint">请核对审批、费用和货物。确认后资料来源切为采购支出；正文、评论、附件及 AI 分析均使用该单。资料不全或审批未通过时保持待处理，旧物流资料仅供历史查看。</p>
      ${context.correction ? `<div class="ocw-settlement-notice">将替换当前关联，保留更正记录和已确认版本。请说明更正原因。</div>${this.renderSettlementSource(context.correction.expense, "当前关联（旧单）")}` : ""}
      ${candidates.map((row) => `<article class="ocw-settlement-review"><div class="ocw-settlement-source-grid">${this.renderSettlementSource(row.logistics, "国际物流审批")}${this.renderSettlementSource(row.expense, context.correction ? "拟关联（新单）" : "采购支出审批")}</div>
        <p>匹配依据：${this.escape(row.reason || row.method || "人工复核")} ${this.escape(JSON.stringify(row.evidence || []))}</p>
        ${row.status === "conflict" ? '<p class="ocw-settlement-notice is-error">存在关联冲突，须逐条填写依据。已被其他有效关联占用的来源需要先处理原关联。</p>' : ""}
        ${context.correction ? this.renderSettlementComparison(context.correction.expense, row.expense, { left: "当前关联货物（旧单）", right: "拟关联货物（新单）" }) : this.renderSettlementComparison(row.logistics, row.expense)}
        <button class="ocw-outline-btn" data-settlement-action="source" data-id="${this.escape(row.id)}">打开采购支出原单</button></article>`).join("")}
      ${!single ? '<p class="ocw-settlement-notice">本次仅确认所选候选的关联；范围未知或负数未确认的费用会保留为待采用，请随后进入对应批次逐条处理。</p>' : ""}`);
    this.settlementActions(state, `<div class="ocw-settlement-toolbar">${editable ? `<button class="ocw-primary-btn" data-settlement-action="confirm">${context.correction ? "确认更正关联" : `确认 ${candidates.length} 个关联`}</button>${single && !context.correction ? '<button class="ocw-outline-btn" data-settlement-action="reject">忽略此候选</button>' : ""}` : '<span>此候选已处理，请刷新列表查看最新状态。</span>'}</div>`);
    this.settlementEvents(state, async (action, $button) => {
      if (action === "source") return this.openSettlementSource(candidates.find((row) => row.id === $button.attr("data-id"))?.expense);
      const choices = single ? this.settlementChoices(state) : {};
      if ((action === "reject" || context.correction) && !choices.reason) throw new Error("请填写核对／更正依据。");
      let result;
      if (action === "confirm") {
        if (context.correction) {
          result = await this.settlementWrite(state, () => this.settlementApi("correct_match", {
            batch_name: context.batchName, binding_id: context.correction.binding.id, expected_revision: context.correction.binding.revision,
            candidate_id: candidate.id, candidate_revision: candidate.revision, reason: choices.reason,
          }));
        } else {
          const selections = candidates.map((row) => this.settlementSelection(row, choices));
          result = await this.settlementWrite(state, () => this.settlementApi("confirm_matches", { selections: JSON.stringify(selections) }));
        }
      } else if (action === "reject") {
        result = await this.settlementWrite(state, () => this.settlementApi("reject_match", { candidate_id: candidate.id, revision: candidate.revision, reason: choices.reason }));
      } else return;
      if (!result) return;
      this.settlementActions(state, "");
      this.settlementBody(state, this.renderSettlementWriteResult(result));
      // Refresh behind the receipt without replacing its partial-failure details.
      if (context.history?.open) await this.loadSettlementHistory(context.history);
      if (context.batchName) await this.refreshSettlementBatch(context.batchName);
      if (context.onComplete) await context.onComplete();
    });
  }

  renderSettlementWriteResult(result = {}) {
    const rows = result.results || [];
    return `<div class="ocw-settlement-notice ${result.ok === false ? "is-error" : ""}" role="status">${rows.length ? `关联成功 ${this.escape(result.confirmed_count ?? 0)}，失败 ${this.escape(result.failed_count ?? 0)}` : result.ok ? "操作已保存" : this.escape(result.message || "操作未完成")}</div>
      <p>关联成功不代表费用已采用或计算完成；请在批次「资料与费用」查看采用状态。</p>
      ${rows.map((row) => `<p>${this.escape(row.candidate_id)}：${row.ok ? this.escape(this.settlementAdoption({ binding: { application_status: row.application_status }, expense: { approved: true } })) : this.escape(row.message || "处理失败")} ${this.escape((row.issues || []).join("；"))}</p>`).join("")}
      ${result.application_status ? `<p>采用状态：${this.escape(this.settlementAdoption({ binding: { application_status: result.application_status }, expense: { approved: true } }))}</p>` : ""}
      ${(result.issues || []).map((issue) => `<p>${this.escape(issue)}</p>`).join("")}
      ${result.ok === false ? '<p>成功项已保留。请关闭此窗口，刷新候选或批次状态后重新复核失败项。</p>' : ""}`;
  }

  openSettlementSource(source) {
    const url = String(source?.open_url || "");
    if (!/^dingtalk:\/\/dingtalkclient\//i.test(url) && !/^https:\/\/([a-z0-9-]+\.)*dingtalk\.com\//i.test(url)) {
      throw new Error("原单链接缺失或无效，请刷新本地来源。");
    }
    this.openDingtalkLink(url);
  }

  async loadSettlementStrip(batchName, cachedData = null) {
    const request = this.settlementStripRequest = (this.settlementStripRequest || 0) + 1;
    const viewedVersion = this.detailState.versionName || null;
    const current = () => request === this.settlementStripRequest && this.detailState.batchName === batchName && this.detailState.tab === "documents" && (this.detailState.versionName || null) === viewedVersion;
    try {
      const data = cachedData && cachedData.viewed_version === viewedVersion ? cachedData
        : await this.settlementApi("get_batch_settlement", { batch_name: batchName, version_name: viewedVersion });
      if (!current()) return;
      if (!data.ok) throw new Error(data.message || "读取关联失败");
      if (this.materialFeeState?.batchName === batchName) this.materialFeeState.settlementData = data;
      const currentSource = data.binding ? data.expense : data.logistics;
      const sourceLabel = data.binding ? "采购支出" : "国际物流";
      const $strip = this.$root.find("[data-area='settlement-strip']");
      $strip.html(`<div class="ocw-settlement-strip"><div><strong>${data.historical ? "此版本资料来源" : "当前资料来源"}：${sourceLabel}</strong><span>${this.escape(this.settlementAdoption(data))}</span>
        <small>${this.escape(data.binding ? `${data.expense?.approval_no || data.expense?.instance || ""} · ${this.settlementAmount(data.expense || {})}` : data.message || "确认匹配后，装箱、SKU、运费及 AI 资料统一切换至采购支出")}</small></div>
        <div class="ocw-settlement-toolbar"><button class="ocw-outline-btn" data-settlement-strip-action="detail">${data.historical ? "查看历史明细与费用" : data.binding ? "查看明细与费用" : "搜索／匹配采购支出"}</button>
        ${currentSource?.open_url ? `<button class="ocw-outline-btn" data-settlement-strip-action="source">打开${sourceLabel}原单</button>` : ""}${data.binding && !data.historical ? '<button class="ocw-outline-btn" data-settlement-strip-action="correct">更正关联</button>' : ""}</div></div>`);
      $strip.off("click.ocwSettlementStrip").on("click.ocwSettlementStrip", "[data-settlement-strip-action]", (event) => {
        const action = $(event.currentTarget).attr("data-settlement-strip-action");
        if (action === "source") { try { this.openSettlementSource(currentSource); } catch (error) { this.showError(error); } }
        else if (action === "correct") this.openSettlementSearch(batchName, data);
        else this.openBatchSettlementDialog(batchName, viewedVersion);
      });
    } catch (error) {
      if (!current()) return;
      this.$root.find("[data-area='settlement-strip']").html(`<div class="ocw-settlement-notice">物流采购支出：${this.escape(error.message || "读取失败")} <button class="ocw-outline-btn" data-settlement-strip-retry>重试</button></div>`)
        .off("click.ocwSettlementStrip").on("click.ocwSettlementStrip", "[data-settlement-strip-retry]", () => this.loadSettlementStrip(batchName));
    }
  }

  async refreshSettlementBatch(batchName) {
    if (this.detailState?.batchName === batchName) {
      // Adoption can create an adjustment version; fetch current header without the old version pin.
      await this.openBatchDetail(batchName, this.detailState.tab || "documents", { updateUrl: false });
    } else if (this.markBatchDirty) this.markBatchDirty(batchName);
  }

  async openBatchSettlementDialog(batchName, viewedVersion = null) {
    const state = this.settlementDialog("物流采购支出 · 明细与费用");
    state.versionName = viewedVersion || (this.detailState?.batchName === batchName ? this.detailState.versionName : null);
    const load = async () => {
      const request = ++state.request;
      try {
        if (state.data && !state.data.historical && this.detailState?.batchName === batchName) state.versionName = this.detailState.versionName;
        const data = await this.settlementApi("get_batch_settlement", { batch_name: batchName, version_name: state.versionName });
        if (!state.open || request !== state.request) return;
        state.data = data;
        this.renderBatchSettlementDialog(state, data);
      } catch (error) {
        if (state.open && request === state.request) {
          this.settlementBody(state, '<button class="ocw-outline-btn" data-settlement-action="refresh">重新读取</button>');
          this.settlementNotice(state, error.message || "读取失败", true);
        }
      }
    };
    this.settlementEvents(state, async (action, $button) => {
      const data = state.data || {};
      if (action === "refresh") return load();
      if (action === "source") return this.openSettlementSource(data.expense);
      if (data.historical) throw new Error("历史版本仅供追溯，请返回当前调整草稿处理。");
      if (action === "search" || action === "correct") return this.openSettlementSearch(batchName, action === "correct" ? data : null, load);
      if (action === "history") return this.openSettlementHistory(true);
      if (action === "candidate") {
        const candidate = (data.candidates || []).find((row) => row.id === $button.attr("data-id"));
        if (candidate) this.openSettlementCandidateReview([candidate], { batchName, onComplete: load });
      }
      if (action === "apply") return this.openSettlementApplicationReview(batchName, data, load);
      if (action === "items") return this.openSettlementItemReview(batchName, data, load);
    });
    await load();
  }

  renderBatchSettlementDialog(state, data) {
    const issues = [...new Set([...(data.binding?.issues || []), ...(data.blocking_reasons || [])])];
    this.settlementBody(state, `<div class="ocw-settlement-toolbar"><strong>${this.escape(this.settlementAdoption(data))}</strong><button class="ocw-outline-btn" data-settlement-action="refresh">刷新</button></div>
      ${this.renderSettlementHealth(data)}
      ${data.message ? `<p>${this.escape(data.message)}</p>` : ""}
      ${data.binding ? `<div class="ocw-settlement-source-grid">${this.renderSettlementSource(data.logistics, "国际物流来源")}${this.renderSettlementSource(data.expense)}</div>
        ${this.renderSettlementComparison(data.logistics, data.expense)}
        <p>费用覆盖范围：${this.escape((data.binding.coverage || []).map((key) => Object.fromEntries(this.settlementCoverageOptions())[key] || key).join("、") || (data.expense?.coverage === "unknown" ? "待确认" : "国际运输费"))} · 采用版本：${this.escape(data.binding.version || "尚未采用")}</p>
        ${issues.map((issue) => `<p class="ocw-settlement-notice">${this.escape(issue)}</p>`).join("")}
        <p class="ocw-settlement-hint">${data.historical ? "显示此版本采用时的采购支出快照，当前原单后续变化不会改写历史结果。" : "已采用的费用仍需重新试算。装箱、货值或汇率待核对时，请先补充对应资料；已确认版本保留历史。"}</p>
        <div class="ocw-settlement-toolbar"><button class="ocw-outline-btn" data-settlement-action="source">打开原单</button>${data.historical ? "" : '<button class="ocw-outline-btn" data-settlement-action="correct">更正关联</button><button class="ocw-primary-btn" data-settlement-action="apply">核对范围／重试采用</button>'}
          ${!data.historical && (data.item_reviews || []).some((row) => row.packing_pending || row.goods_value_pending) ? '<button class="ocw-outline-btn" data-settlement-action="items">核对装箱与货值</button>' : ""}</div>`
        : data.historical ? '<p>此历史版本没有物流采购支出采用记录。</p>' : `<div class="ocw-settlement-toolbar"><button class="ocw-primary-btn" data-settlement-action="search">搜索采购支出</button><button class="ocw-outline-btn" data-settlement-action="history">一键匹配历史采购支出</button></div>
          ${(data.candidates || []).filter((row) => ["pending", "conflict"].includes(row.status)).map((row) => `<p>${this.escape(row.expense?.approval_no || row.expense?.instance)} · ${this.escape(this.settlementAmount(row.expense || {}))} · ${row.status === "conflict" ? "冲突" : "待确认"} <button class="ocw-outline-btn" data-settlement-action="candidate" data-id="${this.escape(row.id)}">复核关联</button></p>`).join("")}`}
      ${data.audit?.length ? `<details><summary>关联与采用记录</summary>${data.audit.map((row) => `<p>${this.escape(row.created_at || row.at || "")} · ${this.escape(row.action || "记录")} · ${this.escape(row.actor || "")} ${this.escape(row.reason || "")}</p>`).join("")}</details>` : ""}`);
  }

  async openSettlementSearch(batchName, correction = null, onComplete = null) {
    const state = this.settlementDialog(correction ? "更正关联 · 搜索新采购支出" : "搜索采购支出", [
      { fieldtype: "Data", fieldname: "settlement_query", label: "审批号、单据号或原单关键词" },
      { fieldtype: "Small Text", fieldname: "settlement_reason", label: "人工关联依据" },
    ], true);
    Object.assign(state, { after: null, pages: [], query: "", data: {} });
    const load = async () => {
      const request = ++state.request;
      try {
        const result = await this.settlementApi("find_expenses", { batch_name: batchName, query: state.query, after: state.after });
        if (!state.open || request !== state.request) return;
        state.data = result;
        this.settlementBody(state, `${correction ? this.renderSettlementSource(correction.expense, "当前关联（旧单）") : ""}<p class="ocw-settlement-hint">仅搜索本地归档、同一企业的物流类采购支出。填写人工依据后，选择候选进入新旧资料复核。</p>
          <button class="ocw-primary-btn" data-settlement-action="search">搜索</button>${result.message ? `<p>${this.escape(result.message)}</p>` : ""}
          ${(result.items || []).map((row) => `<div class="ocw-settlement-search-row"><div><strong>${this.escape(row.approval_no || row.instance)}</strong><p>${this.escape(this.settlementAmount(row))} · ${this.escape(row.status || "待核对")} ${row.occupied ? "· 已有关联" : ""} ${row.invalid ? "· 已失效" : ""}</p></div>
            ${!row.invalid ? `<button class="ocw-outline-btn" data-settlement-action="choose" data-id="${this.escape(row.id)}">选择并复核</button>` : ""}</div>`).join("") || "<p>没有可显示的采购支出。可修改关键词或先运行历史匹配。</p>"}
          <div class="ocw-settlement-toolbar">${state.pages.length ? '<button class="ocw-outline-btn" data-settlement-action="previous">上一页</button>' : ""}${result.has_more ? '<button class="ocw-outline-btn" data-settlement-action="next">下一页</button>' : ""}</div>`);
      } catch (error) {
        if (state.open && request === state.request) {
          this.settlementBody(state, '<button class="ocw-outline-btn" data-settlement-action="search">重新搜索</button>');
          this.settlementNotice(state, error.message || "搜索失败", true);
        }
      }
    };
    this.settlementEvents(state, async (action, $button) => {
      if (action === "search") { state.query = String(state.dialog.get_value("settlement_query") || "").trim(); state.after = null; state.pages = []; return load(); }
      if (action === "next") { state.pages.push(state.after); state.after = state.data.next_cursor; return load(); }
      if (action === "previous") { state.after = state.pages.pop() ?? null; return load(); }
      if (action === "choose") {
        const reason = String(state.dialog.get_value("settlement_reason") || "").trim();
        if (!reason) throw new Error("请填写人工关联依据，再选择候选。");
        const result = await this.settlementWrite(state, () => this.settlementApi("prepare_manual_candidate", { batch_name: batchName, expense_id: $button.attr("data-id"), reason }));
        if (!state.open) return;
        if (!result?.ok || !result.candidate) throw new Error(result?.message || "候选准备失败，请刷新重试");
        this.openSettlementCandidateReview([result.candidate], { batchName, correction, onComplete });
      }
    });
    await load();
  }

  openSettlementApplicationReview(batchName, data, onComplete) {
    const state = this.settlementDialog("核对费用范围并重试采用", this.settlementChoiceFields(data.expense, data.binding.coverage || []));
    this.settlementBody(state, `${this.renderSettlementSource(data.expense)}<p class="ocw-settlement-hint">仅提交范围和核对选择，费用与货物值由服务端读取当前原单。汇率和装箱资料请在原入口补齐。</p>`);
    this.settlementActions(state, '<button class="ocw-primary-btn" data-settlement-action="apply">重试采用当前原单</button>');
    this.settlementEvents(state, async (action) => {
      if (action !== "apply") return;
      const choices = this.settlementChoices(state);
      const result = await this.settlementWrite(state, () => this.settlementApi("retry_application", { batch_name: batchName, expected_revision: data.binding.revision,
        expected_snapshot: data.expense.snapshot, expected_version: data.viewed_version,
        ...(choices.coverage.length ? { coverage: JSON.stringify(choices.coverage) } : {}), negative_confirmed: choices.negative_confirmed }));
      this.settlementActions(state, "");
      this.settlementBody(state, this.renderSettlementWriteResult(result));
      await this.refreshSettlementBatch(batchName);
      await onComplete();
    });
  }

  renderSettlementItemReviews(items) {
    return `<div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table"><thead><tr><th>物料／品名</th><th>最终数量／单位</th><th>装箱数量／毛重／体积／计费重</th><th>采购货值</th><th>核对选择</th></tr></thead><tbody>${items.filter((row) => row.packing_pending || row.goods_value_pending).map((row, index) => `<tr><td>${this.escape(row.material_code)}<small>${this.escape(row.product_name)} ${this.escape(row.spec_model)}</small></td><td>${this.escape(row.quantity ?? "—")} ${this.escape(row.unit)}</td>
      <td>装箱数量 ${this.escape(row.packing_quantity ?? "—")}<small>毛重 ${this.escape(row.gross_weight_kg ?? "—")} kg · 体积 ${this.escape(row.volume_m3 ?? "—")} m³ · 计费重 ${this.escape(row.chargeable_weight_kg ?? "—")} kg</small>${this.renderSettlementPackingCandidates(row.packing_candidates || [])}</td><td>${this.escape(row.goods_value ?? "—")}<small>单价 ${this.escape(row.unit_price ?? "—")}</small></td><td>
      ${row.packing_pending ? `<label><input type="checkbox" data-review-index="${index}" data-check="packing_confirmed"> 已核对装箱对应关系</label>` : ""}${row.goods_value_pending ? `<label><input type="checkbox" data-review-index="${index}" data-check="goods_value_confirmed"> 已核对采购货值</label>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
  }

  renderSettlementPackingCandidates(candidates) {
    if (!candidates.length) return "";
    const labels = { actual_shipped_qty: "实发数量", quantity_applicability: "最终数量／装箱数量", gross_weight_kg: "毛重 kg", volume_m3: "体积 m³", chargeable_weight_kg: "计费重 kg", volume_weight_kg: "体积重 kg", weight_ratio: "重量比例" };
    return `<details open><summary>归档候选与现有值</summary>${candidates.map((candidate) => `<p>${this.escape(candidate.reason || "装箱资料待核对")}<small>附件 ${this.escape(candidate.document_id || "")} · 行 ${this.escape(candidate.line ?? "—")}</small></p>
      ${(candidate.conflicts || []).map((row) => `<p>${this.escape(labels[row.field] || row.field)}：现有 ${this.escape(row.existing ?? "—")} → 归档候选 ${this.escape(row.candidate ?? "—")}</p>`).join("")}
      ${candidate.retired ? `<p>原依据已撤销，受影响字段：${this.escape((candidate.fields || []).map((field) => labels[field] || field).join("、"))}</p>` : ""}`).join("")}</details>`;
  }

  openSettlementItemReview(batchName, data, onComplete) {
    const items = (data.item_reviews || []).filter((row) => row.packing_pending || row.goods_value_pending);
    const state = this.settlementDialog("核对装箱与采购货值", [{ fieldtype: "Small Text", fieldname: "settlement_reason", label: "核对说明" }]);
    this.settlementBody(state, `<p class="ocw-settlement-hint">先在装箱或 SKU 入口修正资料，再刷新并逐项确认；这里只记录核对结果，不修改数量、重量或金额。</p>${this.renderSettlementItemReviews(items)}`);
    this.settlementActions(state, '<button class="ocw-primary-btn" data-settlement-action="verify">保存已勾选核对结果</button>');
    this.settlementEvents(state, async (action) => {
      if (action !== "verify") return;
      const reason = String(state.dialog.get_value("settlement_reason") || "").trim();
      if (!reason) throw new Error("请填写核对说明。");
      const selections = items.map((row, index) => {
        const choices = {};
        state.dialog.fields_dict.settlement_body.$wrapper.find(`[data-review-index='${index}']:checked`).each((_, node) => { choices[$(node).attr("data-check")] = true; });
        return Object.keys(choices).length ? { item_name: row.item_name, expected_item_hash: row.revision, ...choices } : null;
      }).filter(Boolean);
      if (!selections.length) throw new Error("请逐项勾选已完成核对的资料。");
      const result = await this.settlementWrite(state, () => this.settlementApi("resolve_item_checks", { batch_name: batchName, expected_revision: data.binding.revision, selections: JSON.stringify(selections), reason }));
      this.settlementActions(state, "");
      this.settlementBody(state, this.renderSettlementWriteResult(result));
      await this.refreshSettlementBatch(batchName);
      await onComplete();
    });
  }
