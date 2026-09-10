  freightEvidence(evidence = {}) {
    return `${evidence.file_name || "审批正文"} · ${evidence.sheet || "明细"}${evidence.row != null ? ` · 第 ${evidence.row} 行` : ""}`;
  }

  renderFreightStrip(data) {
    const claims = data.freight?.claims || [];
    const amount = claims.length ? claims.map(r => `${r.applied_amount ?? r.amount} ${r.currency}`).join(" + ") : "待查找／待确认";
    return `<div class="ocw-settlement-strip"><div><strong>${data.historical ? "历史版本" : "本票"}当前采用运费：${this.escape(amount)}</strong>
      <small>装箱：${this.escape(data.packing?.message || "保留当前资料，变更单独核对")}</small>
      ${(data.freight?.issues || []).map(v => `<small class="ocw-settlement-notice">${this.escape(v)}</small>`).join("")}</div>
      <div class="ocw-settlement-toolbar"><button class="ocw-outline-btn" data-settlement-strip-action="detail">${data.historical ? "查看历史运费／装箱" : "查找实际运费／装箱变更"}</button>
      ${data.logistics?.open_url ? '<button class="ocw-outline-btn" data-settlement-strip-action="source">打开国际物流原单</button>' : ""}</div></div>`;
  }

  freightMoney(amount, currency) {
    return `${this.escape(amount ?? '待核对')} ${this.escape(currency || '')}`;
  }

  freightSourceCell(row = {}, source = {}) {
    return `<span class="ocw-freight-source-no">${this.escape(source.approval_no || row.approval_no || '结算原单')}</span><small>${this.escape(this.freightEvidence(row.evidence || {}))}</small>`;
  }

  freightActionButton(action, label, attributes = '', primary = false, disabled = false) {
    return `<button type="button" class="${primary ? 'ocw-primary-btn' : 'ocw-outline-btn'}" data-settlement-action="${action}" ${attributes} ${disabled ? 'disabled' : ''}>${label}</button>`;
  }

  renderFreightContent(data, state = {}) {
    const tab = state.freightTab || 'freight';
    const tabs = [['freight', '运费'], ['packing', '装箱来源'], ['audit', '操作记录']];
    const view = state.freightView;
    let body;
    if (view?.kind === 'evidence') body = this.renderFreightInlineEvidence(state);
    else if (tab === 'packing') body = this.renderFreightPackingSources(data, state);
    else if (tab === 'audit') body = this.renderFreightAudit(data);
    else if (view?.kind === 'search') body = this.renderFreightSearch(state);
    else if (view) body = this.renderFreightEditor(data, state);
    else body = this.renderFreightFees(data);
    return `<div class="ocw-freight-workspace"><div class="ocw-freight-heading"><div><small>本票国际物流</small><strong>${this.escape(data.logistics?.approval_no || state.batchName || '来源待整理')}</strong></div>${this.freightActionButton('refresh', '刷新', '', false, !!state.freightWriting)}</div>
      <nav class="ocw-freight-tabs" role="tablist" aria-label="运费与装箱核对">${tabs.map(([key, label]) => this.freightActionButton('freight-tab', label, `data-freight-tab="${key}" role="tab" aria-selected="${key === tab}"`, false, !!state.freightWriting)).join('')}</nav>
      ${data.historical ? '<p class="ocw-settlement-hint">历史版本仅供追溯，展示采用时的资料与证据。</p>' : ''}
      ${state.freightMessage ? `<p class="ocw-settlement-notice" role="status">${this.escape(state.freightMessage)}</p>` : ''}
      ${state.freightError ? `<p class="ocw-settlement-notice is-error" role="alert">${this.escape(state.freightError)}</p>` : ''}
      <div class="ocw-freight-panel" role="tabpanel">${body}</div></div>`;
  }

  renderFreightFees(data) {
    const claims = data.freight?.claims || [];
    const header = '<thead><tr><th>费用名称</th><th>运单号</th><th>原始金额</th><th>当前采用金额</th><th>来源</th><th>状态</th><th>操作</th></tr></thead>';
    return `<section><h4 class="ocw-freight-section-title">已审批运费</h4><div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table ocw-freight-fee-table">${header}<tbody>${claims.map(row => `<tr><td>${this.escape(row.label || '运输费')}</td><td>${this.escape(row.waybill || '原单明确关联')}</td><td class="ocw-freight-money">${this.freightMoney(row.original_amount ?? (row.manual_corrected ? null : row.amount), row.currency)}</td><td class="ocw-freight-money"><strong>${this.freightMoney(row.applied_amount ?? row.amount, row.currency)}</strong></td><td>${this.freightSourceCell(row)}</td><td><span class="ocw-freight-status">${row.manual_corrected ? '人工更正' : '已采用'}</span></td><td><div class="ocw-freight-row-actions">${row.line_id ? this.freightActionButton('freight-evidence', '查看证据', `data-line="${this.escape(row.line_id)}"`) : ''}${!data.historical ? ['amount', 'replace', 'revoke'].map((action, index) => this.freightActionButton(`freight-${action}`, ['改金额', '换来源', '撤销采用'][index], `data-claim="${this.escape(row.id)}"`)).join('') : ''}</div></td></tr>`).join('') || '<tr><td colspan="7">尚未采用本票实际运费</td></tr>'}</tbody></table></div>
      <p class="ocw-settlement-hint">这里显示审批通过的账单费用；银行支付状态需凭证核实。</p>${(data.freight?.issues || []).map(issue => `<p class="ocw-settlement-notice">${this.escape(issue)}</p>`).join('')}</section>
      <p class="ocw-settlement-hint">装箱：${this.escape(data.packing?.message || '保留当前资料，变更单独核对')}</p>
      ${data.historical ? '' : `${this.renderBatchSettlementMatching(data)}<div class="ocw-settlement-toolbar"><h4 class="ocw-freight-section-title">本票费用候选</h4>${this.freightActionButton('search', '搜索本票支付证据')}</div>
      ${(data.candidates || []).map(candidate => `<section class="ocw-settlement-source"><div class="ocw-freight-heading"><div><strong>${this.escape(candidate.expense?.title || '支付流程')}</strong><small>${this.escape(candidate.expense?.approval_no || candidate.expense?.instance || '')}</small></div>${this.freightActionButton('freight-source', '打开支付原单', `data-id="${this.escape(candidate.id)}"`)}</div>
        <p class="ocw-settlement-hint">整单合计，仅供核对：${this.freightMoney(candidate.expense?.amount, candidate.expense?.currency)}</p><p>${this.escape(candidate.reason || '请核对本票费用明细')}${candidate.expense?.approved === false ? ' · 审批未通过，仅供查看' : ''}</p>
        <div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table">${header}<tbody>${(candidate.lines || []).map(row => `<tr><td>${this.escape(row.label || '运输费')}</td><td>${this.escape(row.waybill || '正文明确关联')}</td><td class="ocw-freight-money">${this.freightMoney(row.amount, row.currency)}</td><td>${row.adopted ? '已采用，见上表' : '—'}</td><td>${this.freightSourceCell(row, candidate.expense)}</td><td>${row.adopted ? '已采用' : row.available ? '可采用' : '待核对'}</td><td>${this.freightActionButton('freight-evidence', '查看证据', `data-line="${this.escape(row.id)}"`)}</td></tr>`).join('') || '<tr><td colspan="7">已找到相关单据，本票金额待核对；不会按整单总额或平均数采用。</td></tr>'}</tbody></table></div>
        ${(candidate.issues || []).map(issue => `<p class="ocw-settlement-notice">${this.escape(issue)}</p>`).join('')}<div class="ocw-settlement-toolbar">${(candidate.lines || []).length ? this.freightActionButton('freight-review', '核对本票费用', `data-id="${this.escape(candidate.id)}"`, true) : ''}${candidate.packing_available ? this.freightActionButton('packing-review', '查看装箱来源', `data-id="${this.escape(candidate.id)}"`) : ''}${this.freightActionButton('freight-reject', '不是本票', `data-id="${this.escape(candidate.id)}"`)}</div></section>`).join('')}`}`;
  }

  freightSelectedLines(state) {
    const draft = state.freightDraft || {};
    const candidate = (state.data.candidates || []).find(row => row.id === draft.candidate_id);
    return { candidate, lines: (candidate?.lines || []).filter(row => (draft.line_ids || []).includes(row.id)) };
  }

  freightNeedsNegative(state) {
    return state.freightView?.kind === 'amount' ? Number(state.freightDraft?.amount) < 0 : this.freightSelectedLines(state).lines.some(row => Number(row.amount) < 0);
  }

  renderFreightChangeSummary(state) {
    const view = state.freightView || {};
    const claim = (state.data.freight?.claims || []).find(row => row.id === view.claim_id);
    const { lines } = this.freightSelectedLines(state);
    const totals = {};
    for (const line of lines) totals[line.currency || ''] = (totals[line.currency || ''] || 0) + Number(line.amount);
    if (view.kind === 'amount' && claim) totals[claim.currency] = Number(state.freightDraft?.amount);
    const after = Object.entries(totals).map(([currency, amount]) => this.freightMoney(Number(amount.toFixed(6)), currency)).join(' + ') || (view.kind === 'revoke' ? '撤销该费用' : '请选择明细');
    let difference = '';
    if (claim && Object.keys(totals).length === 1 && Object.hasOwn(totals, claim.currency)) difference = this.freightMoney(Number((totals[claim.currency] - Number(claim.applied_amount ?? claim.amount)).toFixed(6)), claim.currency);
    return `<div class="ocw-freight-change-summary">${claim ? `<div><small>更正前</small><strong>${this.freightMoney(claim.applied_amount ?? claim.amount, claim.currency)}</strong><small>${this.escape(claim.approval_no || '')}</small></div>` : ''}<div><small>${claim ? '更正后' : '所选费用合计'}</small><strong>${after}</strong></div>${difference ? `<div><small>差额</small><strong>${difference}</strong></div>` : ''}</div>`;
  }

  renderFreightEditor(data, state) {
    const view = state.freightView || {};
    const draft = state.freightDraft || {};
    const claim = (data.freight?.claims || []).find(row => row.id === view.claim_id);
    const titles = { amount: '修改当前采用金额', replace: '更换费用来源', revoke: '撤销费用采用', adopt: '核对本票费用', reject: '标记不是本票', checks: '核对保留的重量与体积' };
    const { candidate } = this.freightSelectedLines(state);
    const choices = ['adopt', 'replace'].includes(view.kind);
    return `<h4 class="ocw-freight-section-title">${titles[view.kind] || '本票费用核对'}</h4>${claim ? `<p>${this.escape(claim.label || '运输费')} · 运单 ${this.escape(claim.waybill || '原单明确关联')}</p><p class="ocw-settlement-hint">原始证据金额：${this.freightMoney(claim.original_amount ?? claim.amount, claim.currency)}<br>来源审批：${this.escape(claim.approval_no || '')}</p>` : ''}
      ${view.kind === 'amount' ? `<label class="ocw-freight-field">当前采用金额（${this.escape(claim?.currency || '')}）<input type="number" step="any" data-freight-field="amount" value="${this.escape(draft.amount ?? '')}"></label><p class="ocw-settlement-hint">保留原始证据金额，人工更正值用于本票核算。</p>` : ''}
      ${choices ? `${view.kind === 'replace' ? `<label class="ocw-freight-field">选择新的费用来源<select data-freight-field="candidate_id"><option value="">请选择来源</option>${(data.candidates || []).filter(row => row.expense?.approved !== false).map(row => `<option value="${this.escape(row.id)}" ${draft.candidate_id === row.id ? 'selected' : ''}>${this.escape(row.expense?.approval_no || row.expense?.title || '支付流程')}</option>`).join('')}</select></label>` : `<p>支付审批：${this.escape(candidate?.expense?.approval_no || '')}</p>`}
      <p class="ocw-settlement-hint">勾选本票明细，提交后采用所选金额。</p><div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table"><thead><tr><th>采用</th><th>费用名称</th><th>运单号</th><th>金额</th><th>来源</th><th>状态</th><th>证据</th></tr></thead><tbody>${(candidate?.lines || []).map(row => `<tr><td><input type="checkbox" aria-label="采用${this.escape(row.label || '费用')}" data-freight-line="${this.escape(row.id)}" ${(draft.line_ids || []).includes(row.id) ? 'checked' : ''} ${row.available && !row.adopted && candidate.expense?.approved !== false ? '' : 'disabled'}></td><td>${this.escape(row.label || '运输费')}</td><td>${this.escape(row.waybill || '正文明确关联')}</td><td class="ocw-freight-money">${this.freightMoney(row.amount, row.currency)}</td><td>${this.freightSourceCell(row, candidate?.expense)}</td><td>${row.adopted ? '已采用' : row.available ? '可采用' : '不可采用'}</td><td>${this.freightActionButton('freight-evidence', '查看证据', `data-line="${this.escape(row.id)}"`)}</td></tr>`).join('') || '<tr><td colspan="7">请选择有可采用费用行的来源</td></tr>'}</tbody></table></div>` : ''}
      ${view.kind === 'checks' ? `<p>请核实保留值仍适用于本票。需要修改时先在物料表补充。</p>${(data.packing_checks || []).map(row => `<label class="ocw-settlement-search-row"><input type="checkbox" data-freight-check="${this.escape(row.name)}" ${(draft.check_ids || []).includes(row.name) ? 'checked' : ''}><span>${this.escape(row.material_code)} ${this.escape(row.product_name)}<small>毛重 ${this.escape(row.gross_weight_kg ?? '待补')} kg · 体积 ${this.escape(row.volume_m3 ?? '待补')} m³</small></span></label>`).join('')}` : ''}
      ${['amount', 'replace', 'revoke', 'adopt'].includes(view.kind) ? `<div data-freight-summary>${this.renderFreightChangeSummary(state)}</div>` : ''}
      ${view.kind === 'revoke' ? '<p class="ocw-settlement-notice">保存后，本票不再采用这条费用。原始来源与更正记录仍可追溯。</p>' : ''}
      ${view.kind === 'reject' ? '<p>请说明该支付来源与本票不对应的依据。</p>' : ''}
      ${['amount', 'replace', 'adopt'].includes(view.kind) ? `<label class="ocw-freight-negative" data-freight-negative ${this.freightNeedsNegative(state) ? '' : 'hidden'}><input type="checkbox" data-freight-field="negative_confirmed" ${draft.negative_confirmed ? 'checked' : ''}>已核对负数冲抵／折扣</label>` : ''}
      ${view.kind !== 'adopt' ? `<label class="ocw-freight-field">${view.kind === 'checks' || view.kind === 'reject' ? '核对依据' : '更正原因'}<textarea rows="3" data-freight-field="reason" placeholder="请填写本次核对的依据">${this.escape(draft.reason || '')}</textarea></label>` : ''}`;
  }

  renderFreightPackingSources(data, state) {
    const sourceGroups = [['approval_form', '正文'], ['approval_attachment', '附件'], ['approval_comment_attachment', '评论附件'], ['approval_comment', '评论']];
    const preview = state.packingPreview;
    const sources = state.packingSources || [];
    const missing = value => value === null || value === undefined || value === '' ? '<span class="ocw-freight-missing">待补</span>' : this.escape(value);
    return `<div class="ocw-settlement-toolbar"><h4 class="ocw-freight-section-title">选择整票装箱来源</h4>${this.freightActionButton('packing-sources-refresh', '刷新来源', '', false, !!state.freightLoading)}</div>
      <p class="ocw-settlement-hint">${this.escape(data.packing?.message || '选择一个具体来源，预览后替换本票装箱资料。')}</p>
      ${state.freightLoading ? '<p role="status">正在读取来源与预览…</p>' : ''}
      <div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table ocw-freight-packing-sources"><thead><tr><th>类型</th><th>来源名称</th><th>审批号</th><th>人员／时间</th><th>明细</th><th>状态</th><th>操作</th></tr></thead><tbody>${sourceGroups.map(([kind, label]) => { const rows = sources.filter(row => row.source_kind === kind); return rows.length ? rows.map((row, index) => `<tr class="${state.packingSelected === row.id ? 'is-selected' : ''}"><td>${index ? '' : label}</td><td>${this.escape(row.source_label || label)}</td><td>${this.escape(row.approval_no || '')}</td><td>${this.escape(row.actor_name || '未提供')}<small>${this.escape(row.occurred_at || '')}</small></td><td>${this.escape(row.row_count ?? 0)} 行</td><td>${row.can_adopt ? row.complete ? '可采用' : '资料待补' : '仅供查看'}${(row.issues || []).map(issue => `<small>${this.escape(issue)}</small>`).join('')}</td><td>${this.freightActionButton('packing-source-preview', '预览来源', `data-id="${this.escape(row.id)}"`, false, !!state.freightLoading)}</td></tr>`).join('') : `<tr><td>${label}</td><td colspan="6" class="ocw-settlement-hint">${state.packingSources ? '暂无可用来源' : '来源尚未读取'}</td></tr>`; }).join('')}</tbody></table></div>
      ${preview ? `<section class="ocw-settlement-source" data-freight-packing-preview><div class="ocw-freight-heading"><div><strong>来源预览</strong><small>${this.escape(preview.selection?.descriptor?.source_label || preview.selection?.source_label || sources.find(row => row.id === state.packingSelected)?.source_label || '')}</small></div></div>
      <div class="ocw-freight-change-summary"><div><small>本次采用</small><strong>${this.escape((preview.goods || []).length)} 行</strong></div><div><small>相对当前资料</small><strong>新增 ${this.escape(preview.new_count ?? 0)} · 移除 ${this.escape(preview.removed_count ?? 0)}</strong></div></div>
      <p class="ocw-settlement-notice">采用后将完整替换本票装箱资料，旧行会从新版本移除。${preview.complete ? '' : '此来源资料不完整，缺失值保持待补。'}${(preview.missing_fields || []).length ? ` 待补：${this.escape(preview.missing_fields.join('、'))}` : ''}</p>
      <div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table ocw-freight-packing-goods"><thead><tr><th>SKU／物料编码</th><th>品名</th><th>规格</th><th>数量</th><th>单位</th><th>毛重 kg</th><th>净重 kg</th><th>体积 m³</th><th>包装</th></tr></thead><tbody>${(preview.goods || []).map(row => `<tr><td>${missing(row.material_code)}</td><td>${missing(row.product_name)}</td><td>${missing(row.spec_model)}</td><td>${missing(row.quantity)}</td><td>${missing(row.unit)}</td><td>${missing(row.physical?.gross_weight_kg ?? row.gross_weight_kg)}</td><td>${missing(row.physical?.net_weight_kg ?? row.net_weight_kg)}</td><td>${missing(row.physical?.volume_m3 ?? row.volume_m3)}</td><td>${missing(row.packaging && typeof row.packaging === 'object' ? Object.entries(row.packaging).map(([key, value]) => `${({package_count:'件数',package_type:'包装',carton_count:'箱数',length_cm:'长 cm',width_cm:'宽 cm',height_cm:'高 cm'})[key] || key}：${value}`).join('；') : row.packaging)}</td></tr>`).join('') || '<tr><td colspan="9">未取得可采用的装箱明细</td></tr>'}</tbody></table></div>
      ${!this.canAdoptFreightPacking(state) ? '<p class="ocw-settlement-notice">此预览不可采用，请核对审批状态、来源和解析结果。</p>' : ''}
      <details open><summary>原始来源与证据</summary>${this.renderFreightScopedEvidence(preview.selection || {})}</details></section>` : '<p class="ocw-settlement-hint">点击具体来源预览整票明细，预览不会修改当前资料。</p>'}
      ${!data.historical && data.packing_checks?.length ? this.freightActionButton('packing-checks', '核对保留的重量与体积') : ''}`;
  }

  renderFreightScopedEvidence(selection) {
    const descriptor = selection.descriptor || selection;
    const goods = selection.goods || [];
    return `<p>审批号：${this.escape(descriptor.approval_no || '')}</p><p>${this.escape(this.freightEvidence(descriptor.evidence || {}))}</p>${selection.text ? `<pre class="ocw-freight-evidence-text">${this.escape(selection.text)}</pre>` : ''}${goods.map(row => `<p>${this.escape(row.material_code || row.product_name || '明细')}<small>${this.escape(this.freightEvidence(row.evidence || {}))}</small></p>`).join('')}${!selection.text && !goods.length ? '<p class="ocw-settlement-hint">此来源未提供可展示的原始文本，请查看来源文件。</p>' : ''}`;
  }

  canAdoptFreightPacking(state) {
    const preview = state.packingPreview;
    return !state.data?.historical && preview?.selection?.can_adopt === true && !preview.invalid && preview.approved !== false && (preview.goods || []).length > 0;
  }

  renderFreightInlineEvidence(state) {
    const row = state.freightEvidenceRow;
    if (!row) return '<p role="status">正在读取本票账单行证据…</p>';
    return `<h4 class="ocw-freight-section-title">本票账单行证据</h4><div class="ocw-freight-change-summary"><div><small>支付审批</small><strong>${this.escape(row.source?.approval_no || '')}</strong></div><div><small>本票运单</small><strong>${this.escape(row.waybill || row.approval_no || '原单明确关联')}</strong></div><div><small>${this.escape(row.label || '费用金额')}</small><strong>${this.freightMoney(row.amount, row.currency)}</strong></div></div><p>${this.escape(this.freightEvidence(row.evidence || {}))}</p><p>账单计费重量：${this.escape(row.billing_weight ?? '未提供')}（不直接覆盖装箱毛重）</p><pre class="ocw-freight-evidence-text">${this.escape(row.cargo_text || '本行未提供物料明细')}</pre><small>本地归档证据；只展示本票行。</small>`;
  }

  renderFreightAudit(data) {
    const labels = { freight_amount:'更正费用金额', freight_replace:'更换费用来源', freight_revoke:'撤销费用采用', freight_lines_adopted:'采用运费', packing_source_replaced:'替换装箱来源', packing_changes_adopted:'采用装箱资料', freight_packing_verified:'核对装箱资料', freight_source_pending:'来源已更新，等待核对', freight_application_recovered:'恢复费用采用', freight_amount_corrected:'更正费用金额', amount:'更正费用金额', freight_claim_amount:'更正费用金额', freight_claim_replaced:'更换费用来源', replace:'更换费用来源', freight_claim_revoked:'撤销费用采用', revoke:'撤销费用采用', freight_confirmed:'采用运费', confirm:'采用运费', freight_rejected:'标记不是本票', rejected:'标记不是本票', packing_source_confirmed:'替换装箱来源', packing_adopted:'采用装箱资料', freight_packing_confirmed:'采用装箱资料', packing_checks_resolved:'核对装箱资料', amount_corrected:'更正费用金额', source_replaced:'更换费用来源', claim_revoked:'撤销费用采用' };
    const values = claims => (Array.isArray(claims) ? claims : []).map(c => `${c.applied_amount ?? c.amount ?? '待核对'} ${c.currency || ''} · ${c.approval_no || ''}`).join('；') || '无采用费用';
    const changes = row => row.action === 'packing_source_replaced'
      ? `来源：${row.source || '资料'}；${row.old_version || ''} → ${row.version || ''}`
      : (row.before || row.after) ? `${values(row.before)} → ${values(row.after)}` : '';
    return `<h4 class="ocw-freight-section-title">操作记录</h4><div class="ocw-settlement-table-wrap"><table class="ocw-settlement-table"><thead><tr><th>时间</th><th>操作</th><th>操作人</th><th>变更前后／来源</th><th>依据</th></tr></thead><tbody>${(data.audit || []).map(row => `<tr><td>${this.escape(row.created_at || '')}</td><td>${this.escape(labels[row.action] || '来源与采用记录更新')}</td><td>${this.escape(row.actor || '')}</td><td>${this.escape(changes(row))}</td><td>${this.escape(row.reason || '—')}</td></tr>`).join('') || '<tr><td colspan="5">暂无操作记录</td></tr>'}</tbody></table></div>`;
  }

  renderFreightSearch(state) {
    const search = state.freightSearch || {};
    const draft = state.freightDraft || {};
    return `<h4 class="ocw-freight-section-title">搜索本票支付证据</h4><label class="ocw-freight-field">审批号、单据号或原单关键词<input data-freight-field="query" value="${this.escape(draft.query || '')}"></label><label class="ocw-freight-field">人工关联依据<textarea data-freight-field="reason" rows="2">${this.escape(draft.reason || '')}</textarea></label><p class="ocw-settlement-hint">请填写该支付来源与本票国际物流的对应关系，选择后在当前窗口核对费用。</p>${this.freightActionButton('freight-search-run', '搜索', '', true, !!state.freightLoading)}${state.freightLoading ? '<p role="status">正在搜索…</p>' : ''}
      ${(search.items || []).map(row => `<div class="ocw-settlement-source"><strong>${this.escape(row.title || '支付流程')}</strong><p>${this.escape(row.approval_no || row.instance || '')}</p><p>${this.escape(this.settlementAmount(row))}</p>${row.invalid ? '<small>来源已失效</small>' : this.freightActionButton('freight-search-choose', '选择并复核', `data-id="${this.escape(row.id)}"`)}</div>`).join('') || (search.loaded ? '<p>没有符合关键词的支付来源，请调整关键词。</p>' : '')}<div class="ocw-settlement-toolbar">${search.pages?.length ? this.freightActionButton('freight-search-previous', '上一页') : ''}${search.has_more ? this.freightActionButton('freight-search-next', '下一页') : ''}</div>`;
  }

  renderFreightWorkspace(state) {
    if (!state.open) return;
    const $wrapper = state.dialog.$wrapper;
    $wrapper?.addClass?.('ocw-freight-modal');
    if (state.packingVersion && state.packingVersion !== state.versionName) { state.packingSources = null; state.packingPreview = null; state.packingSelected = null; }
    this.settlementBody(state, this.renderFreightContent(state.data || {}, state));
    const view = state.freightView;
    const disabled = !!(state.freightWriting || state.freightLoading);
    let actions = '';
    if (view) actions += this.freightActionButton('freight-back', view.kind === 'evidence' ? '返回核对' : '返回列表', '', false, disabled);
    if (view?.kind === 'evidence' && state.freightEvidenceRow?.source?.open_url) actions += this.freightActionButton('freight-evidence-source', '打开支付原单');
    if (!state.data?.historical && view && ['amount','replace','revoke','adopt','reject','checks'].includes(view.kind)) actions += this.freightActionButton('freight-save', ({amount:'保存金额更正',replace:'确认更换来源',revoke:'确认撤销采用',adopt:'确认采用所选费用',reject:'保存否决记录',checks:'确认所选装箱资料适用'})[view.kind], '', true, disabled);
    if (state.freightTab === 'packing' && !view && this.canAdoptFreightPacking(state)) actions += this.freightActionButton('packing-source-confirm', '采用此来源并替换本票装箱资料', '', true, disabled);
    this.settlementActions(state, `<div class="ocw-freight-footer"><span>${state.freightWriting ? '正在保存，请稍候…' : state.data?.historical ? '历史版本 · 只读' : '费用与装箱资料分别核对、分别采用'}</span><div class="ocw-freight-row-actions">${actions}</div></div>`);
    this.bindFreightInputs(state);
  }

  captureFreightDraft(state) {
    const $wrapper = state.dialog.$wrapper;
    const draft = state.freightDraft ||= {};
    $wrapper.find('[data-freight-field]').each((_, element) => { const key = element.getAttribute('data-freight-field'); draft[key] = element.type === 'checkbox' ? element.checked : element.value; });
    if ($wrapper.find('[data-freight-line]').length) draft.line_ids = $wrapper.find('[data-freight-line]:checked').map((_, element) => element.getAttribute('data-freight-line')).get();
    if ($wrapper.find('[data-freight-check]').length) draft.check_ids = $wrapper.find('[data-freight-check]:checked').map((_, element) => element.getAttribute('data-freight-check')).get();
  }

  bindFreightInputs(state) {
    const $wrapper = state.dialog.$wrapper;
    $wrapper.off('input.ocwFreight change.ocwFreight').on('input.ocwFreight change.ocwFreight', '[data-freight-field],[data-freight-line],[data-freight-check]', event => {
      if (state.busy || state.freightWriting) return;
      this.captureFreightDraft(state);
      const key = event.currentTarget.getAttribute('data-freight-field');
      if (key === 'candidate_id') { state.freightDraft.line_ids = []; state.freightDraft.negative_confirmed = false; this.renderFreightWorkspace(state); }
      else {
        if (!this.freightNeedsNegative(state)) { state.freightDraft.negative_confirmed = false; $wrapper.find('[data-freight-field="negative_confirmed"]').prop('checked', false); }
        $wrapper.find('[data-freight-negative]').prop('hidden', !this.freightNeedsNegative(state));
        $wrapper.find('[data-freight-summary]').html(this.renderFreightChangeSummary(state));
      }
    });
  }

  async readFreightWorkspace(state, action, args, receive) {
    const request = state.freightRequest = (state.freightRequest || 0) + 1;
    const version = state.versionName;
    state.freightLoading = true; state.freightError = ''; this.renderFreightWorkspace(state);
    const current = () => this.isBatchSettlementCurrent(state) && request === state.freightRequest && version === state.versionName;
    try {
      const result = await this.settlementApi(action, { batch_name: state.batchName, version_name: version, ...args });
      if (!current()) return;
      if (!result?.ok) throw new Error(result?.message || '读取来源失败，请重试');
      receive(result);
    } catch (error) { if (current()) state.freightError = error.message || '读取失败，请重试'; }
    finally { if (current()) { state.freightLoading = false; this.renderFreightWorkspace(state);
      if (action === "preview_shipment_packing_source" && state.packingPreview) state.dialog.$wrapper?.find?.("[data-freight-packing-preview]")?.[0]?.scrollIntoView?.({block:"start",behavior:"smooth"});
    } }
  }

  async writeFreightWorkspace(state, action, args, afterWrite) {
    if (state.freightWriting || state.busy || !state.open) return;
    if (!this.isBatchSettlementCurrent(state)) throw new Error('当前批次或版本已变化，请重新打开本票资料。');
    state.freightWriting = true; state.freightError = ''; this.renderFreightWorkspace(state);
    const version = state.versionName;
    try {
      const result = await this.settlementWrite(state, () => this.settlementApi(action, args));
      if (!result?.ok) throw new Error(result?.message || '操作未保存，请核对后重试');
      if (!this.isBatchSettlementCurrent(state) || version !== state.versionName) return;
      state.freightView = null; state.freightDraft = {}; state.packingSources = null; state.packingPreview = null; state.packingSelected = null;
      state.freightMessage = result.message || (result.status === 'queued' ? '已保存确认，当前编辑结束后处理。' : '已保存，请核对当前资料并重新试算。');
      try { await this.refreshSettlementBatch(state.batchName, result.version); }
      catch (error) { state.freightError = `已保存，新版本资料读取失败：${error.message || "请刷新重试"}`; }
      if (state.open) await afterWrite(result);
    } finally { state.freightWriting = false; if (state.open) this.renderFreightWorkspace(state); }
  }

  async handleFreightAction(state, action, $button, afterWrite = async () => {}) {
    if (!state.open || state.busy || state.freightWriting) return;
    const data = state.data;
    this.captureFreightDraft(state);
    if (action === 'freight-tab' || action === 'packing-review') {
      state.freightRequest = (state.freightRequest || 0) + 1; state.freightLoading = false;
      state.freightTab = action === 'packing-review' ? 'packing' : $button.attr('data-freight-tab');
      state.freightView = null; state.freightReturnView = null; state.freightError = '';
      this.renderFreightWorkspace(state);
      if (state.freightTab === 'packing' && !state.packingSources) return this.handleFreightAction(state, 'packing-sources-refresh', $button, afterWrite);
      return;
    }
    if (action === 'freight-back') {
      state.freightRequest = (state.freightRequest || 0) + 1; state.freightLoading = false;
      state.freightView = state.freightView?.kind === 'evidence' ? state.freightReturnView || null : null;
      state.freightReturnView = null; state.freightError = ''; return this.renderFreightWorkspace(state);
    }
    if (action === 'freight-source') return this.openSettlementSource((data.candidates || []).find(row => row.id === $button.attr('data-id'))?.expense);
    if (action === 'freight-evidence-source') return this.openSettlementSource(state.freightEvidenceRow?.source);
    if (action === 'freight-evidence') {
      state.freightReturnView = state.freightView || null; state.freightView = { kind: 'evidence' }; state.freightEvidenceRow = null;
      return this.readFreightWorkspace(state, 'freight_line_evidence', { line_id: $button.attr('data-line') }, result => { state.freightEvidenceRow = result.evidence; });
    }
    if (action === 'packing-sources-refresh') {
      state.packingPreview = null; state.packingSelected = null;
      return this.readFreightWorkspace(state, 'list_shipment_packing_sources', {}, result => { state.packingSources = result.sources || []; state.packingVersion = state.versionName; });
    }
    if (action === 'packing-source-preview') {
      const source = (state.packingSources || []).find(row => row.id === $button.attr('data-id'));
      if (!source) throw new Error('来源已变化，请刷新来源列表');
      state.packingSelected = source.id; state.packingPreview = null;
      return this.readFreightWorkspace(state, 'preview_shipment_packing_source', { source_id: source.id, source_revision: source.revision }, result => { if (!result.preview) throw new Error('未取得有效装箱预览'); state.packingPreview = result.preview; });
    }
    if (data.historical) throw new Error('历史版本仅供追溯，请返回当前调整草稿处理。');
    if (!this.isBatchSettlementCurrent(state)) throw new Error('当前批次或版本已变化，请重新打开本票资料。');
    if (action === 'retry-matching') return this.startBatchSettlementMatching(state, true);
    if (action === 'search') { state.freightTab = 'freight'; state.freightView = { kind: 'search' }; state.freightDraft = { query: '', reason: '' }; state.freightSearch = {}; return this.renderFreightWorkspace(state); }
    if (['freight-search-run', 'freight-search-next', 'freight-search-previous'].includes(action)) {
      const search = state.freightSearch ||= {};
      if (action === 'freight-search-run') { search.pages = []; search.after = null; search.query = String(state.freightDraft.query || '').trim(); }
      if (!search.query) throw new Error('请输入审批号、单据号或原单关键词');
      if (action === 'freight-search-next') { (search.pages ||= []).push(search.after); search.after = search.next_cursor; }
      if (action === 'freight-search-previous') search.after = search.pages.pop() ?? null;
      return this.readFreightWorkspace(state, 'find_expenses', { query: search.query, after: search.after }, result => { Object.assign(search, result, { loaded: true }); });
    }
    if (action === 'freight-search-choose') {
      const reason = String(state.freightDraft.reason || '').trim();
      if (!reason) throw new Error('请填写人工关联依据，再选择候选');
      const result = await this.settlementWrite(state, () => this.settlementApi('prepare_manual_candidate', { batch_name: state.batchName, expense_id: $button.attr('data-id'), reason }));
      if (!this.isBatchSettlementCurrent(state)) return;
      if (!result?.ok || !result.candidate) throw new Error(result?.message || '候选准备失败');
      data.candidates = [...(data.candidates || []).filter(row => row.id !== result.candidate.id), result.candidate];
      state.freightView = { kind: 'adopt' }; state.freightDraft = { candidate_id: result.candidate.id, line_ids: [], negative_confirmed: false };
      return this.renderFreightWorkspace(state);
    }
    if (action === 'packing-source-confirm') {
      if (!this.canAdoptFreightPacking(state)) throw new Error('此预览不可采用，请重新核对来源');
      return this.writeFreightWorkspace(state, 'confirm_shipment_packing_source', { batch_name: state.batchName, version_name: state.versionName, preview_id: state.packingPreview.id, revision: state.packingPreview.revision, replace_all: 1 }, afterWrite);
    }
    if (['freight-amount', 'freight-replace', 'freight-revoke'].includes(action)) {
      const claim = (data.freight?.claims || []).find(row => row.id === $button.attr('data-claim'));
      if (!claim) throw new Error('费用记录已变化，请刷新后重试');
      state.freightTab = 'freight'; state.freightView = { kind: action.replace('freight-', ''), claim_id: claim.id, expected_revision: data.freight.revision };
      state.freightDraft = { amount: String(claim.applied_amount ?? claim.amount), reason: '', line_ids: [], candidate_id: '', negative_confirmed: false };
      state.freightMessage = ''; return this.renderFreightWorkspace(state);
    }
    if (['freight-review', 'freight-reject', 'packing-checks'].includes(action)) {
      const candidate = (data.candidates || []).find(row => row.id === $button.attr('data-id'));
      if (action !== 'packing-checks' && !candidate) throw new Error('来源候选已变化，请刷新');
      state.freightTab = 'freight'; state.freightView = { kind: action === 'packing-checks' ? 'checks' : action === 'freight-review' ? 'adopt' : 'reject' };
      state.freightDraft = { candidate_id: candidate?.id, line_ids: [], check_ids: [], reason: '', negative_confirmed: false }; state.freightMessage = '';
      return this.renderFreightWorkspace(state);
    }
    if (action !== 'freight-save') return;
    const view = state.freightView || {};
    const draft = state.freightDraft || {};
    const reason = String(draft.reason || '').trim();
    const args = { batch_name: state.batchName, version_name: state.versionName };
    if (view.kind !== 'adopt' && !reason) throw new Error('请填写核对依据或更正原因');
    if (view.kind === 'checks') {
      const selections = (data.packing_checks || []).filter(row => (draft.check_ids || []).includes(row.name)).map(row => ({ item_name: row.name, expected_item_hash: row.revision }));
      if (!selections.length) throw new Error('请选择核对项并填写依据');
      return this.writeFreightWorkspace(state, 'resolve_freight_packing_checks', { ...args, selections: JSON.stringify(selections), reason }, afterWrite);
    }
    const { candidate, lines } = this.freightSelectedLines(state);
    if (view.kind === 'reject') return this.writeFreightWorkspace(state, 'reject_freight_candidate', { ...args, candidate_id: candidate.id, revision: candidate.revision, reason }, afterWrite);
    if (['replace','adopt'].includes(view.kind)) {
      if (!candidate || !lines.length) throw new Error('请选择本票费用明细');
      if (candidate.expense?.approved === false || lines.some(row => !row.available || row.adopted)) throw new Error('所选明细不可采用，请刷新后复核');
      Object.assign(args, { candidate_id: candidate.id, candidate_revision: candidate.revision, line_ids: JSON.stringify(lines.map(row => row.id)) });
    }
    if (view.kind === 'amount') {
      if (String(draft.amount ?? '').trim() === '' || !Number.isFinite(Number(draft.amount))) throw new Error('请填写有效金额，可填 0');
      args.amount = String(draft.amount).trim();
    }
    if (this.freightNeedsNegative(state) && draft.negative_confirmed !== true) throw new Error('请先确认已核对负数冲抵／折扣');
    if (['amount','replace','adopt'].includes(view.kind)) args.negative_confirmed = this.freightNeedsNegative(state) && draft.negative_confirmed === true;
    if (view.kind === 'adopt') return this.writeFreightWorkspace(state, 'confirm_freight_lines', args, afterWrite);
    if (!['amount','replace','revoke'].includes(view.kind)) return;
    return this.writeFreightWorkspace(state, 'amend_freight_claim', { ...args, claim_id: view.claim_id, expected_revision: view.expected_revision, action: view.kind, reason }, afterWrite);
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
