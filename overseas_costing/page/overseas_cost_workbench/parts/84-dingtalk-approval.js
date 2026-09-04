  async loadDingtalkApprovalDetail() {
    const batch = this.getDetailBatch();
    const result = await this.call("overseas_costing.api.workbench.get_batch_dingtalk_approval_detail", {
      batch_name: batch.name,
    });
    if (!result || !result.ok) throw new Error((result && result.message) || "钉钉审批读取失败");
    this.syncPurchaseApprovalStatusFromDingtalk(result);
    this.detailState.dingtalkApproval = result;
    return result;
  }

  syncPurchaseApprovalStatusFromDingtalk(result = {}) {
    const approvals = Array.isArray(result.linked_purchase_approvals) ? result.linked_purchase_approvals : [];
    const excluded = Array.isArray(result.excluded_linked_purchase_approvals) ? result.excluded_linked_purchase_approvals : [];
    if (!approvals.length && !excluded.length) return;
    const batch = this.getDetailBatch();
    const sourceStatus = { ...(batch.source_status || {}) };
    if (sourceStatus.invalid_business && sourceStatus.invalid_business_scope === "source_approval") return;
    sourceStatus.linked_purchase_count = approvals.length + excluded.length;
    sourceStatus.excluded_purchase_count = excluded.length;
    sourceStatus.linked_purchase_approval_statuses = [...approvals, ...excluded]
      .map((approval) => approval.effective_status || approval.status || approval.result)
      .filter(Boolean);
    sourceStatus.purchase_approval_sync_state = excluded.length ? (approvals.length ? "partial" : "excluded") : "valid";
    sourceStatus.purchase_approval_sync_message = excluded.length
      ? `已排除 ${excluded.length} 条拒绝、撤销或终止的关联采购审批；其数据不参与成本写入。`
      : `已关联 ${approvals.length} 条有效采购审批，状态已同步。`;
    if (excluded.length && !approvals.length) {
      sourceStatus.invalid_business = true;
      sourceStatus.invalid_business_scope = "linked_purchase_approval";
      sourceStatus.invalid_business_reason = "关联采购审批均已拒绝、撤销或终止，当前批次不能确认成本或推送 ERP。";
    } else if (sourceStatus.invalid_business_scope === "linked_purchase_approval") {
      sourceStatus.invalid_business = false;
      sourceStatus.invalid_business_scope = "";
      sourceStatus.invalid_business_reason = "";
    }
    batch.source_status = sourceStatus;
    if (this.detailState.header && this.detailState.header.name === batch.name) {
      this.detailState.header.source_status = sourceStatus;
    }
  }

  async renderDingtalkApprovalTab() {
    const requestId = Number(this.detailState.dingtalkRequestId || 0) + 1;
    this.detailState.dingtalkRequestId = requestId;
    const requestedBatch = this.detailState.batchName;
    this.renderDetailTabLoading("正在读取钉钉审批");
    try {
      const result = await this.loadDingtalkApprovalDetail();
      if (this.detailState.dingtalkRequestId !== requestId || this.detailState.batchName !== requestedBatch || this.detailState.tab !== "dingtalk") return;
      const health = result.archive_health || {};
      this.$root.find("[data-area='detail-content']").html(`
        <div class="ocw-detail-section-head">
          <div><span>数据源·${this.escape(result.data_source || "postgres")}</span><h2>钉钉审批</h2></div>
          <button class="ocw-outline-btn" type="button" data-action="detail-dingtalk">在钉钉中打开</button>
        </div>
        <div class="ocw-dingtalk-health">
          <span>最近同步：<strong>${this.escape(this.formatDateTimeMinute(result.source_updated_at) || result.source_updated_at || "--")}</strong></span>
          <span>延迟：<strong>${this.escape(result.source_lag_seconds == null ? "--" : `${result.source_lag_seconds} 秒`)}</strong></span>
          <span>附件：<strong>${this.escape(`${health.archived || 0}/${health.total || 0} 已归档`)}</strong></span>
          ${Number(health.manual_required || 0) ? `<span class="is-warning">需人工：<strong>${this.escape(String(health.manual_required))}</strong></span>` : ""}
          ${Number(health.preview_only || 0) ? `<span class="is-warning">仅预览图：<strong>${this.escape(String(health.preview_only))}</strong></span>` : ""}
        </div>
        ${this.renderDingtalkApprovalCard(result.main_approval || {}, "国际物流主审批", false)}
        <section class="ocw-dingtalk-linked">
          <div class="ocw-detail-section-head"><div><span>关联流程</span><h3>采购审批</h3></div><span>${this.escape(String((result.linked_purchase_approvals || []).length))} 条</span></div>
          ${(result.linked_purchase_approvals || []).length
            ? result.linked_purchase_approvals.map((approval) => this.renderDingtalkApprovalCard(approval, "关联采购审批", true)).join("")
            : `<div class="ocw-detail-empty"><strong>暂无关联采购审批</strong></div>`}
        </section>
        ${(result.excluded_linked_purchase_approvals || []).length ? `
          <section class="ocw-dingtalk-linked is-excluded">
            <div class="ocw-detail-section-head"><div><span>仅供审计查看</span><h3>已排除审批</h3></div><span>${this.escape(String(result.excluded_linked_purchase_approvals.length))} 条</span></div>
            ${result.excluded_linked_purchase_approvals.map((approval) => this.renderDingtalkApprovalCard(approval, "已排除的关联采购审批", true)).join("")}
          </section>` : ""}
      `);
    } catch (error) {
      if (this.detailState.dingtalkRequestId !== requestId || this.detailState.batchName !== requestedBatch || this.detailState.tab !== "dingtalk") return;
      this.renderDetailTabError("钉钉审批", error);
    }
  }

  renderDingtalkApprovalCard(approval = {}, label = "审批", collapsible = false) {
    const content = `
      ${approval.excluded ? `<div class="ocw-dingtalk-excluded-note"><strong>已排除审批</strong><span>${this.escape(approval.exclusion_reason || "撤销、终止或拒绝的审批不参与成本计算。")}</span></div>` : ""}
      <div class="ocw-dingtalk-summary-grid">
        ${this.renderDingtalkSummaryField("审批编号", approval.business_id)}
        ${this.renderDingtalkSummaryField("状态 / 结果", [approval.status, approval.result].filter(Boolean).join(" / "))}
        ${this.renderDingtalkActorField("发起人", approval.originator_user_name, approval.originator_user_id, approval.originator_name_source, approval.originator_name_unresolved)}
        ${this.renderDingtalkSummaryField("部门", approval.originator_dept_name)}
        ${this.renderDingtalkSummaryField("发起时间", this.formatDateTimeMinute(approval.create_time) || approval.create_time)}
        ${this.renderDingtalkSummaryField("完成时间", this.formatDateTimeMinute(approval.finish_time) || approval.finish_time)}
      </div>
      <section class="ocw-dingtalk-subsection"><h4>表单字段</h4>${this.renderDingtalkFormFields(approval.form_fields || [])}</section>
      <section class="ocw-dingtalk-subsection"><h4>操作与评论</h4>${this.renderDingtalkTimeline(approval.timeline || [], !approval.excluded)}</section>
      <section class="ocw-dingtalk-subsection"><h4>审批附件</h4>${this.renderDingtalkAttachments(approval.attachments || [], !approval.excluded)}</section>
    `;
    if (collapsible) {
      return `<details class="ocw-dingtalk-approval-card${approval.excluded ? " is-excluded" : ""}"><summary><strong>${this.escape(approval.title || label)}</strong><span>${this.escape(approval.business_id || approval.instance_id || "--")}</span></summary><div class="ocw-dingtalk-card-body">${content}</div></details>`;
    }
    return `<article class="ocw-dingtalk-approval-card is-main"><header><div><span>${this.escape(label)}</span><h3>${this.escape(approval.title || approval.business_id || approval.instance_id || "--")}</h3></div><span>${this.escape(approval.status || "--")}</span></header><div class="ocw-dingtalk-card-body">${content}</div></article>`;
  }

  renderDingtalkSummaryField(label, value) {
    return `<div><span>${this.escape(label)}</span><strong>${this.escape(value || "--")}</strong></div>`;
  }

  renderDingtalkActor(userName, userId, nameSource = "", unresolved = false) {
    const name = String(userName || "").trim();
    const id = String(userId || "").trim();
    const primary = name || id || "系统";
    let secondary = "";
    if (id && name && id !== name) secondary = `ID：${id}`;
    else if (unresolved || nameSource === "unresolved") secondary = "姓名未同步";
    return `<span class="ocw-dingtalk-actor"><strong>${this.escape(primary)}</strong>${secondary ? `<small class="ocw-dingtalk-actor-id">${this.escape(secondary)}</small>` : ""}</span>`;
  }

  renderDingtalkActorField(label, userName, userId, nameSource = "", unresolved = false) {
    return `<div><span>${this.escape(label)}</span>${this.renderDingtalkActor(userName, userId, nameSource, unresolved)}</div>`;
  }

  renderDingtalkFormFields(fields = []) {
    if (!fields.length) return `<div class="ocw-purchase-empty-line">无可展示表单字段</div>`;
    return `<dl class="ocw-dingtalk-form-fields">${fields.map((field) => `<div><dt>${this.escape(field.label || "未命名字段")}</dt><dd>${this.escape(field.value || "--")}</dd></div>`).join("")}</dl>`;
  }

  renderDingtalkTimeline(items = [], allowCostSource = true) {
    if (!items.length) return `<div class="ocw-purchase-empty-line">无操作或评论记录</div>`;
    return `<ol class="ocw-dingtalk-timeline">${items.map((item) => `
      <li>
        <div>${this.renderDingtalkActor(item.user_name, item.user_id, item.user_name_source, item.user_name_unresolved)}<span>${this.escape(this.formatDateTimeMinute(item.operation_time) || item.operation_time || "--")}</span></div>
        <p>${this.escape(item.remark || [item.operation_type, item.result].filter(Boolean).join(" / ") || "--")}</p>
        ${allowCostSource && item.packing_candidate && item.source_id ? `<button class="ocw-link-btn" type="button" data-action="use-dingtalk-packing-source" data-source-kind="comment" data-source-id="${this.escape(item.source_id)}">作为装箱信息预览</button>` : ""}
      </li>`).join("")}</ol>`;
  }

  dingtalkArchiveStatus(item = {}) {
    const labels = {
      archived: "已归档",
      pending: "待归档",
      archiving: "归档中",
      retry: "等待重试",
      manual_required: "需人工处理",
    };
    const status = item.archive_status || "pending";
    const quality = item.content_quality === "preview" ? "·仅预览图" : "";
    return `${labels[status] || status}${quality}`;
  }

  renderDingtalkAttachments(items = [], allowCostSource = true) {
    if (!items.length) return `<div class="ocw-purchase-empty-line">无附件</div>`;
    return `<div class="ocw-dingtalk-attachments">${items.map((item) => {
      const canFetch = Boolean(item.downloadable);
      const actions = [];
      if (canFetch) {
        actions.push(`<button class="ocw-link-btn" type="button" data-action="preview-dingtalk-attachment" data-attachment-name="${this.escape(item.attachment_name || "")}" data-process-instance-id="${this.escape(item.process_instance_id || "")}" data-file-id="${this.escape(item.file_id || "")}" data-file-url="${this.escape(item.file_url || "")}" data-file-name="${this.escape(item.file_name || "")}">预览</button>`);
        actions.push(`<button class="ocw-link-btn" type="button" data-action="download-dingtalk-attachment" data-attachment-name="${this.escape(item.attachment_name || "")}" data-process-instance-id="${this.escape(item.process_instance_id || "")}" data-file-id="${this.escape(item.file_id || "")}">下载</button>`);
      }
      if (allowCostSource && item.packing_candidate && item.downloadable) {
        actions.push(`<button class="ocw-link-btn" type="button" data-action="use-dingtalk-packing-source" data-source-kind="attachment" data-source-id="${this.escape(item.attachment_name || "")}" data-process-instance-id="${this.escape(item.process_instance_id || "")}" data-file-id="${this.escape(item.file_id || "")}">作为装箱单使用</button>`);
      }
      return `<div class="ocw-dingtalk-attachment-row">
        <div><strong>${this.escape(item.file_name || item.file_id || "--")}</strong><span>${this.escape(item.origin === "Comment" ? "评论附件" : "表单附件")} · ${this.escape(this.dingtalkArchiveStatus(item))}</span>${item.origin === "Comment" && (item.comment_user_name || item.comment_user_id) ? this.renderDingtalkActor(item.comment_user_name, item.comment_user_id, item.comment_user_name_source, item.comment_user_name_unresolved) : ""}${item.comment_remark ? `<em>${this.escape(item.comment_remark)}</em>` : ""}${item.failure_reason ? `<em class="is-error">${this.escape(item.failure_reason)}</em>` : ""}</div>
        <div class="ocw-attachment-actions">${actions.join("") || `<span class="ocw-purchase-source-disabled">暂不可下载</span>`}</div>
      </div>`;
    }).join("")}</div>`;
  }

  async ensureDingtalkLocalAttachment(attachmentName, processInstanceId, fileId) {
    if (attachmentName) return attachmentName;
    const batch = this.getDetailBatch();
    const result = await this.call("overseas_costing.api.import_api.prepare_dingtalk_archive_attachment", {
      batch_name: batch.name,
      process_instance_id: processInstanceId,
      file_id: fileId,
    }, true);
    if (!result || !result.ok || !result.attachment_name) throw new Error((result && result.message) || "无法准备钉钉归档附件");
    return result.attachment_name;
  }

  async downloadDingtalkAttachmentFromDetail(attachmentName, $button = null, processInstanceId = "", fileId = "") {
    const batch = this.getDetailBatch();
    attachmentName = await this.ensureDingtalkLocalAttachment(attachmentName, processInstanceId, fileId);
    await this.downloadOaFormAttachment(batch, null, attachmentName, $button, false);
    if (this.detailState.tab === "dingtalk") await this.renderDingtalkApprovalTab();
  }

  async previewDingtalkAttachmentFromDetail(attachmentName, fileUrl, fileName, $button = null, processInstanceId = "", fileId = "") {
    const batch = this.getDetailBatch();
    attachmentName = await this.ensureDingtalkLocalAttachment(attachmentName, processInstanceId, fileId);
    await this.openOaAttachmentFilePreview(batch, null, attachmentName, fileUrl, fileName, $button);
    if (!fileUrl && this.detailState.tab === "dingtalk") await this.renderDingtalkApprovalTab();
  }

  dingtalkPackingCandidates(detail = {}) {
    const approvals = [detail.main_approval, ...(detail.linked_purchase_approvals || [])]
      .filter((approval) => approval && !approval.excluded);
    const candidates = [];
    approvals.forEach((approval) => {
      (approval.attachments || []).forEach((item) => {
        if (!item.packing_candidate || !item.downloadable) return;
        candidates.push({ kind: "attachment", id: item.attachment_name || "", instanceId: item.process_instance_id || approval.instance_id, fileId: item.file_id, label: item.file_name, meta: `${item.origin === "Comment" ? "评论附件" : "表单附件"} · ${approval.business_id || approval.instance_id}` });
      });
      (approval.timeline || []).forEach((item) => {
        if (!item.packing_candidate || !item.source_id) return;
        candidates.push({ kind: "comment", id: item.source_id, label: item.remark, meta: `纯评论 · ${item.user_name || item.user_id || "--"} · ${this.formatDateTimeMinute(item.operation_time) || item.operation_time || "--"}` });
      });
    });
    return candidates;
  }

  async openDingtalkPackingSourcePicker() {
    const detail = await this.loadDingtalkApprovalDetail();
    const candidates = this.dingtalkPackingCandidates(detail);
    const dialog = new frappe.ui.Dialog({
      title: "从钉钉获取装箱单",
      size: "large",
      fields: [{ fieldtype: "HTML", fieldname: "sources", options: `
        <div class="ocw-purchase-target"><span>当前批次</span><strong>${this.escape(detail.batch_name || "--")}</strong><em>可选表单附件、评论附件或纯评论文字；选择后先预览，不会直接写入。</em></div>
        <div class="ocw-dingtalk-source-picker">${candidates.length ? candidates.map((item) => `<button type="button" data-action="pick-dingtalk-packing-source" data-source-kind="${item.kind}" data-source-id="${this.escape(item.id)}" data-process-instance-id="${this.escape(item.instanceId || "")}" data-file-id="${this.escape(item.fileId || "")}"><strong>${this.escape(item.label || "--")}</strong><span>${this.escape(item.meta)}</span></button>`).join("") : `<div class="ocw-detail-empty"><strong>未找到装箱候选</strong><span>系统会识别装箱单、装箱计划、packing list、发货/装柜/物品清单，以及包含数量重量的评论。</span></div>`}</div>
      ` }],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.on("click.ocwDingtalkPackingPicker", "[data-action='pick-dingtalk-packing-source']", (event) => {
      const $button = $(event.currentTarget);
      dialog.hide();
      this.openDingtalkPackingPreview($button.attr("data-source-kind"), $button.attr("data-source-id"), $button.attr("data-process-instance-id"), $button.attr("data-file-id")).catch((error) => this.showError(error));
    });
  }

  async openDingtalkPackingPreview(sourceKind, sourceId, processInstanceId = "", fileId = "") {
    const batch = this.getDetailBatch();
    if (sourceKind === "attachment") sourceId = await this.ensureDingtalkLocalAttachment(sourceId, processInstanceId, fileId);
    const dialog = new frappe.ui.Dialog({
      title: "钉钉装箱资料预览",
      size: "large",
      fields: [{ fieldtype: "HTML", fieldname: "preview", options: `<div class="ocw-purchase-loading" data-area="dingtalk-packing-preview">正在解析，当前不会写入数据</div>` }],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    const load = async () => {
      let result = await this.call("overseas_costing.api.import_api.preview_packing_source", {
        batch_name: batch.name,
        version_name: batch.current_version || null,
        source_kind: sourceKind,
        source_id: sourceId,
      }, true);
      if (result && result.download_required && result.attachment_name) {
        const saved = await this.call("overseas_costing.api.import_api.download_oa_form_attachment", { attachment_name: result.attachment_name }, true);
        if (!saved || !saved.ok) throw new Error((saved && saved.message) || "附件尚未归档");
        result = await this.call("overseas_costing.api.import_api.preview_packing_source", {
          batch_name: batch.name,
          version_name: batch.current_version || null,
          source_kind: sourceKind,
          source_id: sourceId,
        }, true);
      }
      this.renderDingtalkPackingPreview(dialog, result, batch);
    };
    try { await load(); } catch (error) {
      dialog.$wrapper.find("[data-area='dingtalk-packing-preview']").html(`<div class="ocw-detail-empty is-error"><strong>装箱资料预览失败</strong><span>${this.escape(this.normalizeErrorMessage(error))}</span></div>`);
    }
  }

  renderDingtalkPackingPreview(dialog, result, batch) {
    const $target = dialog.$wrapper.find("[data-area='dingtalk-packing-preview']");
    if (!result || !result.ok) {
      $target.html(`<div class="ocw-detail-empty is-error"><strong>无法生成装箱预览</strong><span>${this.escape((result && result.message) || "请检查来源内容。")}</span></div>`);
      return;
    }
    const preview = result.writeback_preview || {};
    const matched = preview.matched_rows || [];
    const fillable = matched.filter((row) => row.has_fillable);
    const conflicts = matched.filter((row) => row.has_conflict);
    $target.html(`
      <div class="ocw-purchase-target"><span>来源</span><strong>${this.escape(result.source_kind === "comment" ? "钉钉评论" : "钉钉附件")}</strong><em>${this.escape(result.message || "预览已生成，尚未写入。")}</em></div>
      <div class="ocw-purchase-summary"><div><span>匹配行</span><strong>${this.escape(String(preview.matched_count || 0))}</strong></div><div><span>可写入</span><strong>${this.escape(String(preview.fillable_row_count || 0))}</strong></div><div><span>冲突</span><strong>${this.escape(String(preview.conflict_row_count || 0))}</strong></div><div><span>未匹配</span><strong>${this.escape(String(preview.unmatched_count || 0))}</strong></div></div>
      <div class="ocw-purchase-note">只自动填充空值或 0；已有值差异须选择处理方式，多物料歧义不会自动写入。</div>
      ${this.renderDingtalkPackingApplyActions(preview)}
      ${this.renderPurchasePreviewSection("可写入装箱字段", fillable, "fillable")}
      ${this.renderPackingConflictSection(conflicts)}
      ${this.renderPackingUnmatchedSection(preview.unmatched_rows || [], preview.ambiguous_rows || [])}
    `);
    dialog.$wrapper.off("click.ocwDingtalkPackingPreview")
      .on("click.ocwDingtalkPackingPreview", "[data-action='apply-dingtalk-packing']", (event) => {
        const createUnmatched = $(event.currentTarget).attr("data-create-unmatched") === "1";
        this.applyDingtalkPackingSource(dialog, result, batch, { create_unmatched_items: createUnmatched }).catch((error) => this.showError(error));
      })
      .on("click.ocwDingtalkPackingPreview", "[data-action='resolve-packing-conflict']", (event) => {
        const $button = $(event.currentTarget);
        this.applyDingtalkPackingSource(dialog, result, batch, { conflicts: [{ target_item_name: $button.attr("data-target-item-name"), action: $button.attr("data-resolution-action") }] }).catch((error) => this.showError(error));
      });
  }

  renderDingtalkPackingApplyActions(preview = {}) {
    const fillable = Number(preview.fillable_row_count || 0);
    const unmatched = Number(preview.unmatched_count || 0);
    if (!fillable && !unmatched) return "";
    return `<div class="ocw-purchase-apply"><div><strong>确认后才写入</strong><span>写入后将重新计算批次并记录钉钉来源。</span></div><div class="ocw-attachment-actions">${fillable ? `<button class="ocw-primary-btn ocw-mini-btn" type="button" data-action="apply-dingtalk-packing">写入可补字段</button>` : ""}${unmatched ? `<button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="apply-dingtalk-packing" data-create-unmatched="1">确认并新建未匹配物料</button>` : ""}</div></div>`;
  }

  async applyDingtalkPackingSource(dialog, previewResult, batch, resolutions = {}) {
    const confirmed = await new Promise((resolve) => frappe.confirm(
      "确认按预览结果写入当前批次并重新计算？",
      () => resolve(true),
      () => resolve(false)
    ));
    if (!confirmed) return;
    const result = await this.call("overseas_costing.api.import_api.apply_packing_source", {
      batch_name: batch.name,
      version_name: batch.current_version || null,
      source_revision: previewResult.source_revision,
      resolutions_json: JSON.stringify(resolutions),
    }, true);
    if (!result || !result.ok) throw new Error((result && result.message) || "装箱资料写入失败");
    frappe.show_alert({ message: result.message || "装箱资料已写入", indicator: "green" });
    dialog.hide();
    await this.refreshDetailSummary();
  }
