frappe.pages["mobile-material-request"].on_page_load = function (wrapper) {
	new MobileMaterialRequestPage(wrapper);
};

frappe.pages["mobile-material-request"].on_page_show = function (wrapper) {
	if (wrapper.mobile_material_request_page) {
		wrapper.mobile_material_request_page.refresh();
	}
};

class MobileMaterialRequestPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("移动物料需求"),
			single_column: true,
		});
		this.active_bucket = "in_progress";
		this.request_sequence = 0;
		this.search_timer = null;
		wrapper.mobile_material_request_page = this;
		this.$body = $("<div class='mobile-material-request-page'></div>").appendTo(this.page.main);
		this.render_shell();
		this.bind_events();
		this.refresh();
	}

	render_shell() {
		this.$body.html(`
			<div class="mobile-mr-header">
				<div class="mobile-mr-heading">
					<h2>${__("物料需求")}</h2>
					<p>${__("库存与生产移动作业预览")}</p>
				</div>
				<button class="mobile-mr-refresh" type="button" data-action="refresh" aria-label="${__("刷新")}">
					<i class="fa fa-refresh"></i>
				</button>
			</div>
			<div class="mobile-mr-summary" data-region="summary"></div>
			<div class="mobile-mr-section-title"><h3>${__("快捷操作")}</h3></div>
			<div class="mobile-mr-quick-actions">
				<button class="mobile-mr-quick-action primary" type="button" data-action="new">
					<i class="fa fa-plus mr-1"></i>${__("新建需求")}
				</button>
				<button class="mobile-mr-quick-action" type="button" data-action="open-stock-entry">
					<i class="fa fa-exchange mr-1"></i>${__("物料移动")}
				</button>
				<button class="mobile-mr-quick-action" type="button" data-action="open-stock">
					<i class="fa fa-cubes mr-1"></i>${__("库存查询")}
				</button>
			</div>
			<div class="mobile-mr-section-title">
				<h3>${__("待处理物料需求")}</h3><span data-region="list-count"></span>
			</div>
			<div class="mobile-mr-filter">
				<i class="fa fa-search"></i>
				<input type="search" data-field="search" placeholder="${__("搜索编号、物料或需求标题")}" autocomplete="off" />
			</div>
			<div class="mobile-mr-request-list" data-region="requests"></div>
		`);
	}

	bind_events() {
		this.$body.on("click", "[data-action='refresh']", () => this.refresh());
		this.$body.on("click", "[data-action='new']", () => (window.location.href = "/mobile/material-request/new"));
		this.$body.on("click", "[data-action='open-stock-entry']", () => (window.location.href = "/mobile/stock-entry"));
		this.$body.on("click", "[data-action='open-stock']", () => (window.location.href = "/mobile/inventory"));
		this.$body.on("click", "[data-bucket]", (event) => {
			this.active_bucket = $(event.currentTarget).attr("data-bucket") || "all";
			this.render_summary();
			this.render_requests();
		});
		this.$body.on("click", "[data-open-request]", (event) => {
			const name = $(event.currentTarget).attr("data-open-request");
			if (name) this.open_detail(name);
		});
		this.$body.on("click", "[data-action='view-request']", (event) => {
			event.stopPropagation();
			const name = $(event.currentTarget).attr("data-name");
			if (name) this.open_detail(name);
		});
		this.$body.on("click", "[data-action='back']", () => this.render_dashboard());
		this.$body.on("click", "[data-action='open-form']", (event) => {
			const name = $(event.currentTarget).attr("data-name");
			if (name) window.location.href = `/desk/Form/Material Request/${encodeURIComponent(name)}`;
		});
		this.$body.on("input", "[data-field='search']", () => {
			window.clearTimeout(this.search_timer);
			this.search_timer = window.setTimeout(() => this.refresh(), 280);
		});
	}

	refresh() {
		const sequence = ++this.request_sequence;
		const search = this.$body.find("[data-field='search']").val() || "";
		this.render_loading();
		frappe.call({
			method: "mobile_operations.api.get_mobile_material_request_dashboard",
			args: { search, limit: 40 },
			freeze: false,
			callback: (response) => {
				if (sequence !== this.request_sequence) return;
				this.data = response.message || { summary: [], requests: [] };
				this.render_dashboard();
			},
			error: () => {
				if (sequence === this.request_sequence) this.render_error();
			},
		});
	}

	render_loading() {
		this.$body.find("[data-region='summary']").html(
			Array.from({ length: 5 }, () => "<div class='mobile-mr-skeleton'></div>").join("")
		);
		this.$body.find("[data-region='requests']").html(
			Array.from({ length: 3 }, () => "<div class='mobile-mr-skeleton'></div>").join("")
		);
	}

	render_error() {
		this.$body.find("[data-region='summary']").empty();
		this.$body.find("[data-region='requests']").html(
			`<div class="mobile-mr-error">${__("加载失败，请点击右上角重试")}</div>`
		);
	}

	render_dashboard() {
		if (!this.$body.find("[data-region='summary']").length) this.render_shell();
		this.render_summary();
		this.render_requests();
	}

	render_summary() {
		const summary = this.data?.summary || [];
		this.$body.find("[data-region='summary']").html(
			summary.map((card) => {
				const active = this.active_bucket === card.key ? " is-active" : "";
				const tone = card.tone ? ` is-${card.tone}` : "";
				return `
					<button class="mobile-mr-summary-card${active}${tone}" type="button" data-bucket="${escape_attribute(card.key)}">
						<div class="mobile-mr-summary-value">${format_integer(card.count)}</div>
						<div class="mobile-mr-summary-label">${escape_html(card.label)}</div>
					</button>
				`;
			}).join("")
		);
	}

	render_requests() {
		const all_requests = this.data?.requests || [];
		const requests = all_requests.filter((request) => this.matches_bucket(request, this.active_bucket));
		this.$body.find("[data-region='list-count']").text(
			requests.length ? __("{0} 条", [requests.length]) : __("无记录")
		);

		if (!requests.length) {
			this.$body.find("[data-region='requests']").html(
				`<div class="mobile-mr-empty">${__("当前筛选条件下没有物料需求")}</div>`
			);
			return;
		}
		this.$body.find("[data-region='requests']").html(
			requests.map((request) => this.request_card(request)).join("")
		);
	}

	matches_bucket(request, bucket) {
		if (bucket === "all") return true;
		if (bucket === "in_progress") return request.is_active;
		return request.primary_bucket === bucket;
	}

	request_card(request) {
		const progress = Math.max(0, Math.min(100, Number(request.progress || 0)));
		return `
			<article class="mobile-mr-request-card" data-open-request="${escape_attribute(request.name)}">
				<div class="mobile-mr-card-top">
					<div class="mobile-mr-card-number">${escape_html(request.request_no || request.name)}</div>
					<span class="mobile-mr-status ${status_tone(request.primary_bucket)}">${escape_html(request.status_label)}</span>
				</div>
				<div class="mobile-mr-card-title">${escape_html(request.item_preview || request.title || __("暂无明细"))}</div>
				<div class="mobile-mr-card-meta">
					<span>${escape_html(request.type_label || request.material_request_type || "-")}</span>
					<span>${escape_html(request.schedule_date || request.modified || "-")}</span>
				</div>
				<div class="mobile-mr-progress-label"><span>${__("处理进度")}</span><span>${progress}%</span></div>
				<div class="mobile-mr-progress"><div class="mobile-mr-progress-bar" style="width:${progress}%"></div></div>
				<div class="mobile-mr-card-footer">
					<div class="mobile-mr-card-warehouse"><i class="fa fa-map-marker mr-1"></i>${escape_html(request.warehouse || __("未设置仓库"))}</div>
					<button class="mobile-mr-view-button" type="button" data-action="view-request" data-name="${escape_attribute(request.name)}">${__("查看")}</button>
				</div>
			</article>
		`;
	}

	open_detail(name) {
		this.$body.html(`<div class="mobile-mr-loading">${__("正在加载物料需求...")}</div>`);
		frappe.call({
			method: "mobile_operations.api.get_mobile_material_request_detail",
			args: { name },
			freeze: false,
			callback: (response) => this.render_detail(response.message),
			error: () => this.$body.html(`<div class="mobile-mr-error">${__("物料需求加载失败")}</div>`),
		});
	}

	render_detail(detail) {
		if (!detail) {
			this.$body.html(`<div class="mobile-mr-error">${__("未找到物料需求")}</div>`);
			return;
		}
		const item_html = (detail.items || []).map((item) => `
			<div class="mobile-mr-detail-item">
				<div class="mobile-mr-detail-item-top">
					<div><h4>${escape_html(item.item_code || "-")}</h4><p>${escape_html(item.item_name || item.description || "")}</p></div>
					<div class="mobile-mr-qty"><strong>${format_number(item.remaining_qty)}</strong><span>${escape_html(item.uom || "")} ${__("剩余")}</span></div>
				</div>
				<div class="mobile-mr-detail-item-meta">
					<span>${__("需求")}: ${format_number(item.qty)} ${escape_html(item.uom || "")}</span>
					<span>${__("已发料")}: ${format_number(item.issued_qty)}</span>
					<span>${__("仓库")}: ${escape_html(item.warehouse || "-")}</span>
					<span>${__("要求日期")}: ${escape_html(item.schedule_date || "-")}</span>
				</div>
			</div>
		`).join("");

		this.$body.html(`
			<div class="mobile-mr-detail">
				<div class="mobile-mr-detail-header">
					<button class="mobile-mr-back" type="button" data-action="back" aria-label="${__("返回")}"><i class="fa fa-arrow-left"></i></button>
					<div class="mobile-mr-detail-heading"><h2>${escape_html(detail.request_no || detail.name)}</h2><p>${escape_html(detail.status_label)} · ${escape_html(detail.material_request_type || "-")}</p></div>
				</div>
				<div class="mobile-mr-detail-summary"><div class="mobile-mr-detail-summary-grid">
					${detail_field(__("需求标题"), detail.title || "-")}
					${detail_field(__("要求日期"), detail.schedule_date || "-")}
					${detail_field(__("目标仓库"), detail.target_warehouse || "-")}
					${detail_field(__("来源仓库"), detail.source_warehouse || "-")}
					${detail_field(__("处理进度"), `${format_number(detail.progress)}%`)}
					${detail_field(__("物料行数"), `${format_integer(detail.item_count)} ${__("行")}`)}
				</div></div>
				<div class="mobile-mr-section-title"><h3>${__("物料明细")}</h3></div>
				${item_html || `<div class="mobile-mr-empty">${__("暂无物料明细")}</div>`}
				<div class="mobile-mr-detail-actions">
					<button class="mobile-mr-detail-action primary" type="button" data-action="open-form" data-name="${escape_attribute(detail.name)}">${__("电脑端处理")}</button>
					<button class="mobile-mr-detail-action" type="button" data-action="back">${__("返回列表")}</button>
				</div>
			</div>
		`);
	}
}

function detail_field(label, value) {
	return `<div class="mobile-mr-detail-field"><label>${escape_html(label)}</label><div>${escape_html(value)}</div></div>`;
}

function status_tone(bucket) {
	if (bucket === "completed") return "is-success";
	if (bucket === "exception") return "is-danger";
	if (bucket === "to_issue" || bucket === "transit") return "is-warning";
	return "";
}

function escape_html(value) {
	return frappe.utils.escape_html(String(value ?? ""));
}

function escape_attribute(value) {
	return escape_html(value).replace(/`/g, "&#96;");
}

function format_integer(value) {
	return Number(value || 0).toLocaleString();
}

function format_number(value) {
	return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}
