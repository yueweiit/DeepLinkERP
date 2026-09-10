  freightEvidence(evidence = {}) {
    return `${evidence.file_name || "审批正文"} · ${evidence.sheet || "明细"}${evidence.row != null ? ` · 第 ${evidence.row} 行` : ""}`;
  }

  renderFreightStrip(data) {
    const claims = data.freight?.claims || [];
    const amount = claims.length ? claims.map(r => `${r.applied_amount ?? r.amount} ${r.currency}`).join(" + ") : "待查找／待确认";
    return `<div class="ocw-settlement-strip"><div><strong>${data.historical ? "历史版本" : "本票"}已审批运费：${this.escape(amount)}</strong>
      <small>装箱：${this.escape(data.packing?.message || "保留当前资料，变更单独核对")}</small>
      ${(data.freight?.issues || []).map(v => `<small class="ocw-settlement-notice">${this.escape(v)}</small>`).join("")}</div>
      <div class="ocw-settlement-toolbar"><button class="ocw-outline-btn" data-settlement-strip-action="detail">${data.historical ? "查看历史运费／装箱" : "查找实际运费／装箱变更"}</button>
      ${data.logistics?.open_url ? '<button class="ocw-outline-btn" data-settlement-strip-action="source">打开国际物流原单</button>' : ""}</div></div>`;
  }

  renderFreightContent(data) {
    const claims = data.freight?.claims || [];
    return `<div class="ocw-settlement-toolbar"><strong>本票国际物流：${this.escape(data.logistics?.approval_no || "来源待整理")}</strong>
      <button class="ocw-outline-btn" data-settlement-action="refresh">刷新</button></div>
      <p class="ocw-settlement-hint">查找采购、运营、BU、月结、报销等支付流程中的本票主运费与运输附加费。清关、税费及末端费用沿用现有入口。</p>
      <section class="ocw-settlement-source"><strong>已审批运费</strong>
        ${claims.map(r => `<p>${this.escape(r.applied_amount ?? r.amount)} ${this.escape(r.currency)} · ${this.escape(r.approval_no || "结算原单")}<small>${this.escape(this.freightEvidence(r.evidence))}</small><button class="ocw-outline-btn" data-settlement-action="freight-evidence" data-line="${this.escape(r.line_id)}">查看账单行证据</button></p>`).join("") || "<p>尚未采用本票实际运费</p>"}
        <small>这里显示审批通过的账单费用；银行支付状态需凭证核实。</small>
        ${(data.freight?.issues || []).map(v => `<p class="ocw-settlement-notice">${this.escape(v)}</p>`).join("")}</section>
      <section class="ocw-settlement-source"><strong>装箱变更</strong><p>${this.escape(data.packing?.message || "尚未核对装箱变更")}</p></section>
      ${!data.historical && data.packing_checks?.length ? '<button class="ocw-outline-btn" data-settlement-action="packing-checks">核对保留的重量与体积</button>' : ''}
      ${data.message ? `<p class="ocw-settlement-notice">${this.escape(data.message)}</p>` : ""}
      ${data.historical ? "<p>历史版本按采用时的证据展示。</p>" : `${this.renderBatchSettlementMatching(data)}
        <button class="ocw-outline-btn" data-settlement-action="search">搜索本票支付证据</button>
        ${(data.candidates || []).map(c => `<section class="ocw-settlement-source"><strong>${this.escape(c.expense?.title || "支付流程")} ${this.escape(c.expense?.approval_no || c.expense?.instance)}</strong>
          <p>整单合计，仅供核对：${this.escape(c.expense?.amount ?? "待核对")} ${this.escape(c.expense?.currency || "")}</p>
          <p>${this.escape(c.reason || "待核对")} ${!c.expense?.approved ? " · 审批未通过，仅供查看" : ""}</p>
          ${(c.lines || []).map(r => `<p><b>${this.escape(r.amount)} ${this.escape(r.currency)}</b> · 运单 ${this.escape(r.waybill || "正文明确关联")}
            <small>${this.escape(this.freightEvidence(r.evidence))} ${r.adopted ? " · 已保存采用记录" : ""}</small><button class="ocw-outline-btn" data-settlement-action="freight-evidence" data-line="${this.escape(r.id)}">查看账单行证据</button>
            ${r.scope !== "freight" ? '<small>费用性质待核对或属于现有其他费用入口</small>' : ""}
            ${r.cargo_text ? `<details><summary>本票发货明细</summary><pre style="white-space:pre-wrap">${this.escape(r.cargo_text)}</pre></details>` : ""}</p>`).join("") || "<p>已找到相关单据，本票金额待核对；不会按整单总额或平均数采用。</p>"}
          ${(c.issues || []).map(v => `<p class="ocw-settlement-notice">${this.escape(v)}</p>`).join("")}
          <div class="ocw-settlement-toolbar"><button class="ocw-outline-btn" data-settlement-action="freight-source" data-id="${this.escape(c.id)}">打开支付原单</button>
          ${(c.lines || []).length ? `<button class="ocw-primary-btn" data-settlement-action="freight-review" data-id="${this.escape(c.id)}">核对本票费用</button>` : ""}
          ${c.packing_available ? `<button class="ocw-outline-btn" data-settlement-action="packing-review" data-id="${this.escape(c.id)}">比对装箱变更</button>` : '<span>未发现可核对的装箱变更资料</span>'}
          <button class="ocw-outline-btn" data-settlement-action="freight-reject" data-id="${this.escape(c.id)}">不是本票</button></div></section>`).join("")}`}
      ${data.audit?.length ? `<details><summary>采用与更正记录</summary>${data.audit.map(r => `<p>${this.escape(r.created_at)} · ${this.escape(r.action)} · ${this.escape(r.actor || "")} ${this.escape(r.reason || "")}</p>`).join("")}</details>` : ""}`;
  }

  async handleFreightAction(state, action, $button, afterWrite) {
    const data = state.data;
    if (action === "retry-matching") return this.startBatchSettlementMatching(state, true);
    if (action === "search") return this.openSettlementSearch(state.batchName, null, afterWrite, { versionName: state.versionName, logistics: data.logistics, freight: data.freight });
    if (action === 'freight-evidence') return this.openFreightEvidence(state.batchName,data.viewed_version,$button.attr('data-line'));
    if (action === 'packing-checks') return this.openFreightPackingChecks(state.batchName,data.viewed_version,data.packing_checks || [],afterWrite);
    const candidate = (data.candidates || []).find(c => c.id === $button.attr("data-id"));
    if (!candidate) return;
    if (action === "freight-source") return this.openSettlementSource(candidate.expense);
    if (action === "freight-review") return this.openFreightReview(state.batchName, data.viewed_version, candidate, data.freight, afterWrite);
    if (action === "packing-review") return this.openFreightPackingReview(state.batchName, data.viewed_version, candidate, afterWrite);
    if (action === "freight-reject") {
      const review = this.settlementDialog("否决本票候选", [{fieldtype:"Small Text",fieldname:"reason",label:"核对依据",reqd:1}]);
      this.settlementActions(review, '<button class="ocw-primary-btn" data-settlement-action="confirm">保存否决记录</button>');
      this.settlementEvents(review, async action => {
        if (action !== "confirm") return;
        const reason = String(review.dialog.get_value("reason") || "").trim();
        if (!reason) throw new Error("请填写依据");
        await this.settlementWrite(review, () => this.settlementApi("reject_freight_candidate", {batch_name:state.batchName,candidate_id:candidate.id,revision:candidate.revision,reason}));
        review.dialog.hide(); await afterWrite();
      });
    }
  }

  openFreightReview(batchName, versionName, candidate, freight = {}, onComplete = async () => {}) {
    const state=this.settlementDialog("核对本票运费明细",[
      {fieldtype:"Check",fieldname:"negative_confirmed",label:"已核对负数冲抵／折扣"},
      {fieldtype:"Small Text",fieldname:"reason",label:"更正原因（替换已有费用时必填）"}]);
    const rows=candidate.lines || [];
    this.settlementBody(state, `<p>支付审批 ${this.escape(candidate.expense?.approval_no || "")}；只采用勾选的本票明细，装箱资料保持独立。</p>
      ${rows.map(r => `<label class="ocw-settlement-search-row"><input type="checkbox" data-freight-line="${this.escape(r.id)}" ${r.available ? "" : "disabled"} ${r.available && !r.adopted ? "checked" : ""}>
        <span>${this.escape(r.amount)} ${this.escape(r.currency)} · ${this.escape(r.waybill || r.label)}<small>${this.escape(this.freightEvidence(r.evidence))} ${r.adopted ? " · 已采用" : ""}</small></span></label>`).join("")}
      ${(freight.claims || []).length ? `<details><summary>更正已有费用（仅勾选要替换的旧明细）</summary>${freight.claims.map(r => `<label class="ocw-settlement-search-row"><input type="checkbox" data-freight-replace="${this.escape(r.id)}"><span>${this.escape(r.amount)} ${this.escape(r.currency)} · ${this.escape(r.approval_no)}</span></label>`).join("")}</details>` : ""}`);
    this.settlementActions(state,'<button class="ocw-primary-btn" data-settlement-action="confirm">确认采用所选费用</button>');
    this.settlementEvents(state,async action=>{
      if(action!=="confirm")return;
      const selected=state.dialog.$wrapper.find('[data-freight-line]:checked').map((_,el)=>el.getAttribute('data-freight-line')).get();
      const replaced=state.dialog.$wrapper.find('[data-freight-replace]:checked').map((_,el)=>el.getAttribute('data-freight-replace')).get();
      if(!selected.length)throw new Error("请选择本票费用明细");
      const result=await this.settlementWrite(state,()=>this.settlementApi('confirm_freight_lines',{batch_name:batchName,version_name:versionName,
        candidate_id:candidate.id,candidate_revision:candidate.revision,line_ids:JSON.stringify(selected),replace_claim_ids:JSON.stringify(replaced),expected_revision:freight.revision,
        reason:String(state.dialog.get_value('reason')||''),negative_confirmed:!!state.dialog.get_value('negative_confirmed')}));
      this.settlementActions(state,'');this.settlementBody(state,`<p>${this.escape(result.message || (result.status==='queued'?'编辑结束后处理已确认的费用采用':'费用采用已保存，请重新试算；装箱资料未随费用切换。'))}</p>`);
      await this.refreshSettlementBatch(batchName);await onComplete();
    });
  }

  async openFreightPackingReview(batchName, versionName, candidate, onComplete=async()=>{}) {
    const state=this.settlementDialog('本票装箱变更对比',[{fieldtype:'Check',fieldname:'complete',label:'已核实来源为本票完整清单，并采用完整清单替换'}]);
    const detailContext=this.settlementDetailContext();
    const result=await this.settlementApi('preview_freight_packing',{batch_name:batchName,version_name:versionName,candidate_id:candidate.id,candidate_revision:candidate.revision});
    if(!state.open || detailContext!==this.settlementDetailContext())return;
    const preview=result.preview;if(!preview)throw new Error('未取得有效装箱预览');
    state.dialog.set_df_property('complete','hidden',!preview.complete);
    this.settlementBody(state,`<p>${this.escape(preview.message)}</p><p>付款单的计费重量不直接覆盖毛重。物料编码不同时请核对映射，商品采购价不会跨物料沿用。</p>
      <details open><summary>当前采用物料</summary>${(preview.current_items||[]).map(r=>`<p>${this.escape(r.material_code)} ${this.escape(r.product_name)} · ${this.escape(r.quantity)} ${this.escape(r.unit)} · 毛重 ${this.escape(r.gross_weight_kg??'待补')} kg</p>`).join('')}</details>
      <details><summary>国际物流原始明细</summary>${(preview.original_goods||[]).map(r=>`<p>${this.escape(r.material_code)} ${this.escape(r.product_name)} ${this.escape(r.quantity)} ${this.escape(r.unit)}</p>`).join('')||'原始明细待核对'}</details>
      ${(preview.goods||[]).map((r,index)=>{const matches=(preview.current_items||[]).filter(i=>i.material_code===r.material_code && i.unit===r.unit);return `<div class="ocw-settlement-source"><label><input type="checkbox" data-packing-line="${index}" checked> ${this.escape(r.material_code)} ${this.escape(r.product_name)} · ${this.escape(r.quantity)} ${this.escape(r.unit)}</label>
        <small>${this.escape(this.freightEvidence(r.evidence))}</small><select data-packing-target="${index}"><option value="">新增物料行</option>${(preview.current_items||[]).map(i=>`<option value="${this.escape(i.name)}" ${matches.length===1 && matches[0].name===i.name?'selected':''}>更新：${this.escape(i.material_code)} ${this.escape(i.product_name)}（${this.escape(i.quantity)} ${this.escape(i.unit)}）</option>`).join('')}</select></div>`;}).join('')}
      ${(preview.texts||[]).map(t=>`<details><summary>${this.escape(this.freightEvidence(t.evidence))}</summary><pre style="white-space:pre-wrap">${this.escape(t.text)}</pre></details>`).join('')}`);
    if(!preview.approved || preview.invalid || !(preview.goods||[]).length)return;
    this.settlementActions(state,'<button class="ocw-primary-btn" data-settlement-action="confirm">仅采用所选装箱变更</button>');
    this.settlementEvents(state,async action=>{
      if(action!=='confirm')return;
      if(detailContext!==this.settlementDetailContext())throw new Error('当前版本已变化，请重新预览');
      const selections=state.dialog.$wrapper.find('[data-packing-line]:checked').map((_,el)=>{const index=Number(el.getAttribute('data-packing-line'));return {line_key:preview.goods[index].line_key,item_name:state.dialog.$wrapper.find(`[data-packing-target="${index}"]`).val()||null};}).get();
      const saved=await this.settlementWrite(state,()=>this.settlementApi('confirm_freight_packing',{batch_name:batchName,version_name:versionName,preview_id:preview.id,revision:preview.revision,selections:JSON.stringify(selections),complete_confirmed:!!state.dialog.get_value('complete')}));
      this.settlementActions(state,'');this.settlementBody(state,`<p>${this.escape(saved.message || (saved.status==='queued'?'装箱采用已排队':'装箱变更已保存，费用未改变，请核对重量及商品价格后重新试算。'))}</p>`);
      await this.refreshSettlementBatch(batchName);await onComplete();
    });
  }

  renderFreightHistory(state,data) {
    const job=data.job || {};
    this.settlementBody(state, `<p>覆盖采购、运营、BU、月结、报销等支付来源，按运单费用明细查找。拒绝和撤销的单据不进入可采用候选；审批通过表示结算审批通过。</p>
      ${this.renderSettlementHealth(data)}
      <p>本轮状态：${this.escape(job.status || "尚未启动")} · 已处理 ${this.escape(job.processed_count || 0)} / ${this.escape(job.item_count || 0)} · 失败 ${this.escape(job.failed_count || 0)}</p>
      <div class="ocw-settlement-toolbar">${["running","queued"].includes(job.status)?'<button class="ocw-outline-btn" data-settlement-action="pause">暂停</button>': '<button class="ocw-primary-btn" data-settlement-action="start">更新历史来源与本票候选</button>'}
      ${["paused","partial","failed"].includes(job.status)?'<button class="ocw-outline-btn" data-settlement-action="retry">继续／重试</button>':''}
      <button class="ocw-outline-btn" data-settlement-action="refresh">刷新</button><button class="ocw-outline-btn" data-settlement-action="ai-match">DeepSeek 分析未解决／冲突票</button></div>
      <p>已找到候选物流 ${this.escape(data.shipments?.length || 0)} 票 · 已采用费用 ${this.escape(data.counts?.confirmed || 0)} 票 · 未匹配 ${this.escape(data.counts?.unmatched || 0)} 票。月结单可覆盖多票；费用和装箱均在对应批次内分别核对。</p>
      <details><summary>上游2026历史覆盖（最后同步保存的清单）</summary>${(data.health?.health?.financial_coverage||[]).map(r=>`<p>${this.escape(r.template_name)}：已完成 ${r.completed_windows}/${r.windows} 个时间段 · 已归档 ${r.processed_count??0} 条 · 失败 ${r.failed_windows} ${r.last_error?this.escape(r.last_error):''}</p>`).join('')||'尚未保存覆盖清单，不能据此判断历史单据为零。'}</details>
      <div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table"><thead><tr><th>支付流程</th><th>本地来源</th><th>有效来源</th><th>匹配物流票数</th><th>待归档附件</th></tr></thead><tbody>${(data.coverage||[]).map(r=>`<tr><td>${this.escape(r.template_name)}</td><td>${r.local_sources}</td><td>${r.qualified}</td><td>${r.matched_shipments}</td><td>${r.missing_attachments}</td></tr>`).join('')}</tbody></table></div>
      <div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table"><thead><tr><th>国际物流</th><th>候选支付单数</th><th>核对入口</th></tr></thead><tbody>${(data.shipments||[]).map(r=>`<tr><td>${this.escape(r.logistics.approval_no || r.logistics.instance)}</td><td>${r.candidate_count}</td><td>${r.batch?`<a href="/app/overseas-cost-workbench?batch=${encodeURIComponent(r.batch)}&screen=detail&tab=documents">打开本票资料与费用</a>`:'批次待建立／冲突待处理'}</td></tr>`).join('')}</tbody></table></div>
      ${(data.failures||[]).map(r=>`<p>${this.escape(r.source_id)}：${this.escape(r.error)}</p>`).join('')}`);
  }


  async openFreightEvidence(batchName,versionName,lineId) {
    const state=this.settlementDialog('本票账单行证据');
    const result=await this.settlementApi('freight_line_evidence',{batch_name:batchName,version_name:versionName,line_id:lineId});
    if(!state.open)return;
    const row=result.evidence;
    this.settlementBody(state,`<p>支付审批：${this.escape(row.source?.approval_no || '')}</p><p>${this.escape(this.freightEvidence(row.evidence))}</p>
      <p>本票运单：${this.escape(row.waybill || row.approval_no || '原单明确关联')}</p><p><b>${this.escape(row.amount)} ${this.escape(row.currency)}</b> · ${this.escape(row.label)}</p>
      <p>账单计费重量：${this.escape(row.billing_weight ?? '未提供')}（不直接覆盖装箱毛重）</p><pre style="white-space:pre-wrap">${this.escape(row.cargo_text || '本行未提供物料明细')}</pre>
      <small>本地归档证据；只展示本票行，来源快照 ${this.escape(row.source_snapshot)}</small>`);
    this.settlementActions(state,'<button class="ocw-outline-btn" data-settlement-action="source">打开支付原单</button>');
    this.settlementEvents(state,async action=>{if(action==='source')this.openSettlementSource(row.source);});
  }

  openFreightPackingChecks(batchName,versionName,items,onComplete) {
    const state=this.settlementDialog('核对保留的装箱重量与体积',[{fieldtype:'Small Text',fieldname:'reason',label:'核对依据',reqd:1}]);
    this.settlementBody(state,`<p>物料或数量已变化。请核实以下保留值仍适用于本票；需要修改时先在物料表补充，再重新打开此窗口。</p>${items.map(row=>`<label class="ocw-settlement-search-row"><input type="checkbox" data-packing-check="${this.escape(row.name)}"><span>${this.escape(row.material_code)} ${this.escape(row.product_name)} · ${this.escape(row.quantity)} ${this.escape(row.unit)}<small>毛重 ${this.escape(row.gross_weight_kg ?? '待补')} kg · 体积 ${this.escape(row.volume_m3 ?? '待补')} m³</small></span></label>`).join('')}`);
    this.settlementActions(state,'<button class="ocw-primary-btn" data-settlement-action="confirm">确认所选装箱资料适用</button>');
    this.settlementEvents(state,async action=>{
      if(action!=='confirm')return;
      const reason=String(state.dialog.get_value('reason') || '').trim();
      const selections=state.dialog.$wrapper.find('[data-packing-check]:checked').map((_,el)=>{const row=items.find(i=>i.name===el.getAttribute('data-packing-check'));return {item_name:row.name,expected_item_hash:row.revision};}).get();
      if(!reason || !selections.length)throw new Error('请选择核对项并填写依据');
      await this.settlementWrite(state,()=>this.settlementApi('resolve_freight_packing_checks',{batch_name:batchName,version_name:versionName,selections:JSON.stringify(selections),reason}));
      state.dialog.hide();await this.refreshSettlementBatch(batchName);await onComplete();
    });
  }
