frappe.pages["operations-kpi-dashboard"].on_page_load = function (wrapper) {
	new OperationsKPIDashboard(wrapper);
};

class OperationsKPIDashboard {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("Operations KPI Dashboard"), single_column: true });
		this.company = this.page.add_field({ fieldtype: "Link", fieldname: "company", label: __("Company"), options: "Company", default: frappe.defaults.get_user_default("Company"), reqd: 1, change: () => this.refresh() });
		this.from_date = this.page.add_field({ fieldtype: "Date", fieldname: "from_date", label: __("From Date"), default: frappe.datetime.year_start(), reqd: 1, change: () => this.refresh() });
		this.to_date = this.page.add_field({ fieldtype: "Date", fieldname: "to_date", label: __("To Date"), default: frappe.datetime.get_today(), reqd: 1, change: () => this.refresh() });
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.set_secondary_action(__("Export Excel"), () => this.export_excel(), "download");
		this.$body = $("<div class='operations-kpi-dashboard'></div>").appendTo(this.page.main);
		this.request_sequence = 0;
		this.add_style();
		this.refresh();
	}

	filters() {
		return { company: this.company.get_value(), from_date: this.from_date.get_value(), to_date: this.to_date.get_value() };
	}

	export_excel() {
		if (!this.company.get_value() || !this.from_date.get_value() || !this.to_date.get_value()) {
			frappe.msgprint(__("Please select Company, From Date and To Date."));
			return;
		}
		open_url_post(frappe.request.url, {
			cmd: "client_akivision.client_akivision.api.operations_kpi_export.export_kpi_dashboard",
			filters: this.filters(),
		});
	}

	refresh() {
		if (!this.company.get_value() || !this.from_date.get_value() || !this.to_date.get_value()) return;
		const request_sequence = ++this.request_sequence;
		this.render_loading();
		frappe.call({
			method: "client_akivision.client_akivision.api.operations_kpi.get_kpi_dashboard_data",
			args: { filters: this.filters() },
			freeze: false,
			callback: (r) => {
				if (request_sequence === this.request_sequence) this.render(r.message || {});
			},
			error: () => {
				if (request_sequence === this.request_sequence) this.render_error();
			},
		});
	}

	render(data) {
		this.data = data;
		this.$body.empty();
		const overviewCharts = this.get_overview_charts(data);
		// Follow the section order of the first worksheet in ERP表格模板.xlsx.
		this.section(__("Sales Overview"), [
			this.card(__("Total Orders"), data.sales?.total_orders, "Sales Order List"),
			this.card(__("Total Sales Amount"), data.sales?.total_sales_amount, "Sales Order List", {}, { featured: true }),
			this.card(__("High-tech Revenue Amount"), data.sales?.high_tech_revenue, "Sales Order List", { is_high_tech: "是" }),
			this.card(__("High-tech Revenue Ratio"), data.sales?.high_tech_ratio),
		], overviewCharts.sales);
		this.section(__("Order Fulfillment"), [
			this.card(__("Completed Orders"), data.delivery?.completed_orders, "Sales Order List", { status: "已交货" }),
			this.card(__("Pending Orders"), data.delivery?.pending_orders, "Sales Order List"),
			this.card(__("Delivered Orders"), data.delivery?.delivered_orders, "Sales Order List", { status: "已交货" }),
			this.card(__("Delivering Orders"), data.delivery?.delivering_orders, "Sales Order List", { status: "交货中" }),
			this.card(__("Undelivered Orders"), data.delivery?.undelivered_orders, "Sales Order List", { status: "未交货" }),
		], overviewCharts.fulfillment);
		this.section(__("Collection and Receivables"), [
			this.card(__("Collection Amount"), data.receivable?.received_amount, "Receipt Record"),
			this.card(__("Receivable Amount"), data.receivable?.receivable_amount, "Receivable Aging Analysis", {}, { featured: true }),
			this.card(__("Settled Documents"), data.receivable?.settled_documents, "Receivable Aging Analysis"),
			this.card(__("Unsettled Documents"), data.receivable?.unsettled_documents, "Receivable Aging Analysis"),
			this.card(__("Over 90 Days Overdue"), data.receivable?.overdue_over_90, "Receivable Aging Analysis"),
			this.card(__("Monthly Collection Target Completion"), data.receivable?.monthly_collection_completion),
		], overviewCharts.receivable);
		this.table_section(__("Salesperson Performance"), data.salesperson || [], ["sales_person", "delivery_count", "delivery_amount", "personal_received", "personal_receivable", "delivery_rate", "collection_rate"], {
			permission: "sales_order_list", report: "Sales Order List", filter: "sales_person",
		});
		this.section(__("Year-over-year Indicators"), [
			this.card(__("Prior-period Sales Amount"), data.year_over_year?.prior_sales_amount),
			this.card(__("Sales Growth Rate"), data.year_over_year?.sales_growth_rate),
			this.card(__("Receivable Growth Rate"), data.year_over_year?.receivable_growth_rate),
		]);
		this.section(__("Reconciliation Warning"), [
			this.card(__("Unfinished Orders"), data.reconciliation?.unfinished_orders, "Sales Order List"),
			this.card(__("Status Mismatch Count"), data.reconciliation?.status_mismatch_count, "Sales Order List"),
		]);
		this.render_receivable_control(data);
		this.render_operations(data);
		this.render_high_tech(data);
	}

	render_loading() {
		this.$body.empty();
		const $loading = $("<div class='kpi-loading-dashboard'></div>").appendTo(this.$body);
		for (let index = 0; index < 5; index++) {
			$("<section class='kpi-loading-section'><span class='kpi-skeleton kpi-skeleton-title'></span><div class='kpi-loading-grid'><span class='kpi-skeleton'></span><span class='kpi-skeleton'></span><span class='kpi-skeleton'></span><span class='kpi-skeleton'></span></div></section>").appendTo($loading);
		}
	}

	render_error() {
		this.$body.empty();
		this.empty_state(this.$body, __("Unable to load KPI data."));
	}

	section(title, cards, overview_chart = null) {
		const $section = $("<section class='kpi-section'><h4></h4><div class='kpi-card-grid'></div></section>").appendTo(this.$body);
		$section.find("h4").text(title);
		if (cards.some((card) => card.hasClass("kpi-featured-card"))) $section.find(".kpi-card-grid").addClass("kpi-card-grid-featured");
		if (overview_chart) {
			this.donut_chart($("<div class='kpi-donut-chart kpi-module-chart'></div>").insertAfter($section.find("h4"))[0], overview_chart);
		}
		cards.forEach((card) => $section.find(".kpi-card-grid").append(card));
	}

	card(label, value, report, route_options = {}, { featured = false } = {}) {
		value = value || { value: 0, datatype: "Float", status: "未设置" };
		const $card = $("<div class='kpi-card'><div class='kpi-card-header'><div class='kpi-card-label'></div><div class='kpi-card-status'></div></div><div class='kpi-card-value'></div><div class='kpi-card-meta'></div></div>");
		if (featured) $card.addClass("kpi-featured-card");
		$card.find(".kpi-card-label").text(label);
		$card.find(".kpi-card-value").text(this.format(value));
		const meta = [];
		$card.find(".kpi-card-status").html(this.metric_status(value, ""));
		if (value.target != null) {
			meta.push(`<div class='kpi-target-block'><span class='kpi-target'>${__("Target")}: ${this.format({ value: value.target, datatype: value.datatype })}</span>${this.target_progress(value)}</div>`);
		}
		$card.find(".kpi-card-meta").html(meta.join(""));
		if (report) $card.addClass("kpi-clickable").on("click", () => this.open_report(report, route_options));
		return $card;
	}

	table_section(title, rows, fields, drilldown = null) {
		const $section = $("<section class='kpi-section'></section>").appendTo(this.$body);
		this.table($section, title, rows, fields, drilldown);
	}

	get_overview_charts(data) {
		const sales = data.sales || {};
		const delivery = data.delivery || {};
		const receivable = data.receivable || {};
		const totalSales = sales.total_sales_amount?.value || 0;
		const highTechRevenue = sales.high_tech_revenue?.value || 0;
		const charts = {
			sales: {
				title: __("Sales Revenue Composition"),
				labels: [__("High-tech Revenue"), __("Other Revenue")],
				values: [highTechRevenue, Math.max(0, totalSales - highTechRevenue)],
				colors: ["#2490ef", "#c9d8f2"],
			},
			fulfillment: {
				title: __("Order Fulfillment Distribution"),
				labels: [__("Delivered Orders"), __("Delivering Orders"), __("Undelivered Orders")],
				values: [delivery.delivered_orders?.value || 0, delivery.delivering_orders?.value || 0, delivery.undelivered_orders?.value || 0],
				colors: ["#52ba8a", "#f0ad4e", "#e36d6d"],
			},
			receivable: {
				title: __("Collection and Receivable Composition"),
				labels: [__("Collection Amount"), __("Receivable Amount")],
				values: [receivable.received_amount?.value || 0, receivable.receivable_amount?.value || 0],
				colors: ["#52ba8a", "#f0ad4e"],
			},
		};
		for (const key of Object.keys(charts)) {
			if (!charts[key].values.some((value) => value > 0)) charts[key] = null;
		}
		return charts;
	}

	donut_chart(parent, chart) {
		$(parent).append(`<h5>${frappe.utils.escape_html(chart.title)}</h5>`);
		const $chart = $("<div class='kpi-donut-canvas'></div>").appendTo(parent);
		const legend = chart.labels.map((label, index) => `
			<span class='kpi-donut-legend-item'>
				<i style='background:${chart.colors[index]}'></i>
				<span>${frappe.utils.escape_html(label)}</span>
				<b>${format_number(chart.values[index], null, 0)}</b>
			</span>`).join("");
		$("<div class='kpi-donut-legend'></div>").html(legend).appendTo(parent);
		new frappe.Chart($chart[0], {
			type: "donut",
			height: 180,
			data: { labels: chart.labels, datasets: [{ values: chart.values }] },
			colors: chart.colors,
			showLegend: false,
		});
	}

	render_receivable_control(data) {
		const receivable = data.receivable || {};
		const total = receivable.total_receivable_balance?.value || 0;
		const ratio = (metric) => (total ? (metric?.value || 0) / total : 0);
		this.metric_table(__("Receivable Core Control Indicators"), __("Receivable Core Indicators"), [
			{ label: __("Receivable Balance"), metric: receivable.total_receivable_balance, ratio: 1 },
			{ label: __("Due Within 30 Days"), metric: receivable.aging_0_30, ratio: ratio(receivable.aging_0_30) },
			{ label: __("31-90 Days Overdue"), metric: receivable.aging_31_90, ratio: ratio(receivable.aging_31_90) },
			{ label: __("Over 90 Days Overdue"), metric: receivable.aging_over_90, ratio: ratio(receivable.aging_over_90) },
			{ label: __("Monthly Collection Target Completion"), metric: receivable.monthly_collection_completion, ratio: receivable.monthly_collection_completion?.achievement },
		], [__("Amount"), __("Ratio"), __("Warning Status")]);
		this.pair_section(
			($left) => this.chart($left[0], __("Receivable Aging Distribution"), data.aging?.distribution || [], "label", [{ name: __("Amount"), values: (data.aging?.distribution || []).map((row) => row.amount) }], "bar"),
			($right) => this.table($right, __("Top 10 Overdue Customers"), data.aging?.top_customers || [], ["customer_name", "overdue_amount", "overdue_days", "risk_level"], {
				permission: "receivable_aging_analysis", report: "Receivable Aging Analysis", filter: "customer",
			}),
		);
	}

	render_operations(data) {
		const operations = data.operations || {};
		const productionTrend = data.production_trend || [];
		this.metric_table(__("Production and Purchasing Operations"), __("Operations Core Indicators"), [
			{ key: "production_completion_rate", label: __("Production Completion Rate"), metric: operations.production_completion_rate },
			{ key: "purchase_on_time_rate", label: __("Purchase On-time Rate"), metric: operations.purchase_on_time_rate },
			{ key: "realtime_inventory_amount", label: __("Realtime Inventory Amount"), metric: operations.realtime_inventory_amount },
			{ key: "safety_stock_warning_count", label: __("Safety Stock Warning Count"), metric: operations.safety_stock_warning_count },
			{ key: "purchase_in_transit_amount", label: __("Purchase In-transit Amount"), metric: operations.purchase_in_transit_amount },
			{ key: "material_over_consumption_rate", label: __("Material Over-consumption Rate"), metric: operations.material_over_consumption_rate },
		], [__("Value"), __("Target Value"), __("Achievement Rate"), __("Warning Status")], data.operations_drilldowns || {});
		this.pair_section(
			productionTrend.length
				? ($left) => this.chart($left[0], __("Monthly Production Completion Trend"), productionTrend, "period", [{ name: __("Completion Rate"), chartType: "line", values: productionTrend.map((row) => row.completion_rate * 100) }], "line")
				: null,
			($right) => this.table($right, __("Top 10 Delayed Suppliers"), data.delayed_suppliers || [], ["supplier_name", "delayed_order_count", "average_delay_days", "risk_level"], {
				permission: "purchase_delay_analysis", report: "Purchase Delay Analysis", filter: "supplier",
			}),
		);
	}

		render_high_tech(data) {
		const highTech = data.high_tech || {};
		this.metric_table(__("High-tech Compliance"), __("High-tech Core Indicators"), [
			{ label: __("High-tech Revenue Amount"), metric: highTech.high_tech_revenue },
			{ label: __("Total Revenue"), metric: highTech.total_revenue },
			{ label: __("High-tech Revenue Ratio"), metric: highTech.high_tech_ratio, featured: true },
			{ label: __("RD Project Count"), metric: highTech.rd_project_count },
			{ label: __("RD Expense Amount"), metric: highTech.rd_expense_amount },
			{ label: __("RD Expense Ratio"), metric: highTech.rd_expense_ratio },
		], [__("Year-to-date"), __("Annual Target"), __("Achievement Rate"), __("Compliance Status")]);
		this.pair_section(
			($left) => this.chart($left[0], __("3-Year High-tech Trend"), data.high_tech_trend || [], "year", [{ name: __("High-tech Revenue Amount"), values: (data.high_tech_trend || []).map((row) => row.high_tech_revenue) }, { name: __("Total Revenue"), values: (data.high_tech_trend || []).map((row) => row.total_revenue) }], "bar"),
			($right) => this.table($right, __("Top 10 RD Projects"), data.high_tech_projects || [], ["project_name", "high_tech_revenue"]),
		);
	}

	pair_section(render_left, render_right) {
		const $section = $("<section class='kpi-section kpi-template-pair'></section>").appendTo(this.$body);
		const $grid = $("<div class='kpi-pair-grid'></div>").appendTo($section);
		if (render_left) {
			const $left = $("<div class='kpi-chart'></div>").appendTo($grid);
			render_left($left);
		} else {
			$grid.addClass("kpi-pair-single");
		}
		const $right = $("<div class='kpi-table'></div>").appendTo($grid);
		render_right($right);
	}

	metric_table(section_title, table_title, rows, headers, drilldowns = {}) {
		const $section = $("<section class='kpi-section'></section>").appendTo(this.$body);
		$("<h4></h4>").text(section_title).appendTo($section);
		const $card = $("<div class='kpi-table-card kpi-metric-table'><h5></h5><div class='table-responsive'><table><thead></thead><tbody></tbody></table></div></div>").appendTo($section);
		$card.find("h5").text(table_title);
		$card.find("thead").html(`<tr><th>${__("Metric")}</th>${headers.map((header) => `<th>${frappe.utils.escape_html(header)}</th>`).join("")}</tr>`);
		$card.find("tbody").html(rows.map((row) => {
			const metric = row.metric || {};
			const drilldown = row.key ? drilldowns[row.key] : null;
			const values = headers.length === 3
				? [this.format(metric), this.format({ value: row.ratio, datatype: "Percent" }), this.metric_status(metric)]
				: [row.featured ? this.metric_value_with_progress(metric) : this.format(metric), metric.target == null ? "—" : this.format({ value: metric.target, datatype: metric.datatype }), metric.achievement == null ? "—" : this.format({ value: metric.achievement, datatype: "Percent" }), this.metric_status(metric)];
			const classes = [row.featured ? "kpi-featured-row" : "", drilldown ? "kpi-drilldown-row" : ""].filter(Boolean).join(" ");
			const attributes = drilldown
				? ` class='${classes}' role='link' tabindex='0' data-metric-key='${frappe.utils.escape_html(row.key)}' title='${frappe.utils.escape_html(__("Click to view details"))}'`
				: classes ? ` class='${classes}'` : "";
			return `<tr${attributes}><td>${frappe.utils.escape_html(row.label)}</td>${values.map((value) => `<td>${value}</td>`).join("")}</tr>`;
		}).join(""));
		$card.on("click keydown", ".kpi-drilldown-row", (event) => {
			if (event.type === "keydown" && !["Enter", " ", "Spacebar"].includes(event.key)) return;
			if (event.type === "keydown") event.preventDefault();
			const drilldown = drilldowns[$(event.currentTarget).data("metric-key")];
			if (drilldown) this.open_route(drilldown.route, drilldown.route_options);
		});
	}

	metric_status(metric, empty = "<span class='text-muted'>—</span>") {
		if (!metric || metric.status === "未设置" || !metric.status) return empty;
		const title = metric.target_direction
			? __("Status is based on the configured evaluation direction and thresholds.")
			: __("Status is based on the KPI calculation rules.");
		return `<span class='indicator-pill ${this.status_color(metric.status)}' title='${frappe.utils.escape_html(title)}'>${frappe.utils.escape_html(__(metric.status))}</span>`;
	}

	target_progress(metric) {
		const progress = Number(metric?.target_progress);
		if (metric?.target == null || !Number.isFinite(progress)) return "";
		const percent = Math.max(0, Math.min(100, progress));
		return `<div class='kpi-target-progress' title='${frappe.utils.escape_html(__("Target Progress"))}: ${format_number(percent, null, 1)}%'><span class='${this.progress_color(metric.status)}' style='width:${percent}%'></span></div>`;
	}

	metric_value_with_progress(metric) {
		return `<div class='kpi-featured-value'>${this.format(metric)}${this.target_progress(metric)}</div>`;
	}

	chart(parent, title, rows, label_field, datasets, type) {
		$(parent).append(`<h5>${frappe.utils.escape_html(title)}</h5>`);
		if (!rows.length || !datasets.some((dataset) => dataset.values.some((value) => Number(value || 0) !== 0))) {
			this.empty_state($(parent), __("No data matching the current filters."));
			return;
		}
		new frappe.Chart(parent, { type, height: 230, data: { labels: rows.map((row) => typeof row[label_field] === "string" ? __(row[label_field]) : row[label_field]), datasets }, colors: ["#2490ef", "#52ba8a"] });
	}

	table($container, title, rows, fields, drilldown = null) {
		const labels = { customer_name: __("Customer"), supplier_name: __("Supplier"), project_name: __("Project"), sales_person: __("Sales Person"), overdue_amount: __("Overdue Amount"), overdue_days: __("Overdue Days"), risk_level: __("Risk Level"), delayed_order_count: __("Delayed Orders"), average_delay_days: __("Average Delay Days"), high_tech_revenue: __("High-tech Revenue Amount"), delivery_count: __("Delivery Count"), delivery_amount: __("Delivery Amount"), personal_received: __("Personal Collection"), personal_receivable: __("Personal Receivable"), delivery_rate: __("Delivery Rate"), collection_rate: __("Collection Rate") };
		const $table = $("<div class='kpi-table-card'><h5></h5><div class='table-responsive'><table><thead></thead><tbody></tbody></table></div></div>").appendTo($container);
		const can_drilldown = drilldown && this.data?.drilldown_permissions?.[drilldown.permission];
		$table.find("h5").text(title);
		$table.find("thead").html(`<tr>${fields.map((field) => `<th class='${this.table_column_class(field)}'>${frappe.utils.escape_html(labels[field] || field)}</th>`).join("")}</tr>`);
		if (!rows.length) {
			$table.find("tbody").html(`<tr><td colspan='${fields.length}'>${this.empty_state_markup(__("No data matching the current filters."))}</td></tr>`);
			return;
		}

		$table.find("tbody").html(rows.map((row) => {
			const drill_value = can_drilldown ? row[drilldown.filter] : null;
			const is_clickable = Boolean(drill_value);
			const row_attributes = is_clickable
				? ` class='kpi-drilldown-row' role='link' tabindex='0' data-drill-value='${frappe.utils.escape_html(String(drill_value))}' title='${frappe.utils.escape_html(__("Click to view details"))}'`
				: "";
			return `<tr${row_attributes}>${fields.map((field) => `<td class='${this.table_column_class(field)}'>${this.table_cell_value(row[field], field)}</td>`).join("")}</tr>`;
		}).join(""));

		if (can_drilldown) {
			$table.on("click keydown", ".kpi-drilldown-row", (event) => {
				if (event.type === "keydown" && !["Enter", " ", "Spacebar"].includes(event.key)) return;
				if (event.type === "keydown") event.preventDefault();
				this.open_report(drilldown.report, { [drilldown.filter]: $(event.currentTarget).data("drill-value") });
			});
		}
	}

	empty_state($container, message) {
		$(this.empty_state_markup(message)).appendTo($container);
	}

	empty_state_markup(message) {
		return `<div class='kpi-empty-state'><span class='kpi-empty-mark'>—</span><span>${frappe.utils.escape_html(message)}</span></div>`;
	}

	open_report(report, options) {
		this.open_route(["query-report", report], { ...this.filters(), ...options });
	}

	open_route(route, options = {}) {
		frappe.route_options = options;
		frappe.set_route(...route);
	}

	format(metric = {}) {
		if (metric.value == null) return "—";
		if (metric.datatype === "Currency") return format_currency(metric.value);
		if (metric.datatype === "Percent") return format_number(metric.value * 100, null, 1) + "%";
		return format_number(metric.value, null, metric.datatype === "Int" ? 0 : 2);
	}

	table_value(value, field) {
		if (["overdue_amount", "high_tech_revenue", "delivery_amount", "personal_received", "personal_receivable"].includes(field)) return format_currency(value || 0);
		if (["delivery_rate", "collection_rate"].includes(field)) return format_number((value || 0) * 100, null, 1) + "%";
		if (["average_delay_days", "overdue_days", "delayed_order_count", "delivery_count"].includes(field)) return format_number(value || 0, null, 2);
		return value == null ? "" : String(value);
	}

	table_cell_value(value, field) {
		const text = frappe.utils.escape_html(this.table_value(value, field));
		if (field === "risk_level") {
			const color_map = { "Low Risk": "green", "Medium Risk": "orange", "High Risk": "red" };
			const color = color_map[value] || "gray";
			const display_text = frappe.utils.escape_html(__(value || ""));
			return `<span class="indicator-pill ${color} no-indicator-dot ellipsis"><span class="ellipsis">${display_text}</span></span>`;
		}
		if (!["delivery_rate", "collection_rate"].includes(field)) return text;
		const percent = Math.max(0, Math.min(100, Number(value || 0) * 100));
		return `<div class='kpi-table-rate'><span>${text}</span><i><b style='width:${percent}%'></b></i></div>`;
	}

	table_column_class(field) {
		if (["customer_name", "supplier_name", "project_name", "sales_person"].includes(field)) return "kpi-table-name";
		if (["overdue_amount", "high_tech_revenue", "delivery_amount", "personal_received", "personal_receivable"].includes(field)) return "kpi-table-amount";
		if (["overdue_days", "delayed_order_count", "average_delay_days", "delivery_count", "delivery_rate", "collection_rate"].includes(field)) return "kpi-table-number";
		return "";
	}

	status_color(status) { return { "正常": "green", "达标": "green", "合规": "green", "预警": "orange", "危险": "red", "未达标": "red", "不合规": "red", "未设置": "gray" }[status] || "gray"; }

	progress_color(status) { return { "预警": "orange", "危险": "red", "未达标": "red", "不合规": "red" }[status] || "blue"; }

	add_style() {
		if (document.getElementById("operations-kpi-style")) return;
		$(
			`<style id="operations-kpi-style">
				.operations-kpi-dashboard {
					box-sizing: border-box;
					max-width: 1520px;
					margin: 0 auto;
					padding: 24px clamp(20px, 3vw, 48px) 56px;
					--kpi-hero-from: #1d4ed8;
					--kpi-hero-via: #2490ef;
					--kpi-hero-to: #60a5fa;
				}
				.kpi-section { margin: 0 0 36px; }
				.kpi-section h4 {
					position: relative;
					margin: 0 0 16px;
					padding-left: 12px;
					color: var(--text-color);
					font-size: 15px;
					font-weight: 700;
					letter-spacing: .02em;
				}
				.kpi-section h4::before {
					content: "";
					position: absolute;
					left: 0;
					top: 50%;
					width: 3px;
					height: 16px;
					border-radius: 999px;
					background: linear-gradient(180deg, var(--kpi-hero-via), var(--kpi-hero-from));
					transform: translateY(-50%);
				}
				.kpi-card-grid {
					display: grid;
					grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
					gap: 16px;
				}
				.kpi-card-grid-featured { grid-template-columns: repeat(5, minmax(0, 1fr)); }
				.kpi-card-grid-featured .kpi-featured-card { grid-column: span 2; }
				.kpi-card, .kpi-chart, .kpi-table-card, .kpi-donut-chart {
					box-sizing: border-box;
					border: 1px solid var(--border-color);
					border-radius: 14px;
					background: var(--card-bg);
					box-shadow: 0 1px 3px rgba(16, 24, 40, .06), 0 1px 2px rgba(16, 24, 40, .04);
				}
				.kpi-card { min-height: 128px; padding: 18px 20px; }
				.kpi-chart, .kpi-table-card, .kpi-donut-chart { padding: 18px 20px; }
				.kpi-featured-card {
					border: 0;
					background: linear-gradient(135deg, var(--kpi-hero-from) 0%, var(--kpi-hero-via) 55%, var(--kpi-hero-to) 100%);
					box-shadow: 0 6px 18px rgba(36, 144, 239, .28);
				}
				.kpi-featured-card .kpi-card-label { color: rgba(255, 255, 255, .82); }
				.kpi-featured-card .kpi-card-value {
					color: #fff;
					font-size: clamp(30px, 2.6vw, 40px);
					letter-spacing: -.02em;
				}
				.kpi-featured-card .kpi-target { color: rgba(255, 255, 255, .78); }
				.kpi-featured-card .kpi-target-progress { background: rgba(255, 255, 255, .25); }
				.kpi-featured-card .kpi-target-progress > span { background: #fff; }
				.kpi-featured-card .kpi-card-status .indicator-pill {
					background: rgba(255, 255, 255, .16);
					color: #fff;
				}
				.kpi-clickable { cursor: pointer; transition: box-shadow .18s ease, transform .18s ease; }
				.kpi-clickable:hover { box-shadow: 0 10px 24px rgba(16, 24, 40, .1); transform: translateY(-2px); }
				.kpi-featured-card.kpi-clickable:hover { box-shadow: 0 12px 28px rgba(36, 144, 239, .36); }
				.kpi-card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
				.kpi-card-label { min-height: 20px; color: var(--text-muted); font-size: 12px; font-weight: 500; letter-spacing: .02em; }
				.kpi-card-status { flex: 0 0 auto; min-height: 20px; }
				.kpi-card-value {
					margin: 10px 0;
					color: var(--text-color);
					font-size: 26px;
					font-weight: 700;
					font-variant-numeric: tabular-nums;
					letter-spacing: -.01em;
					line-height: 1.15;
				}
				.kpi-card-meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
				.kpi-target-block { display: grid; gap: 6px; width: 100%; }
				.kpi-target { color: var(--text-muted); font-size: 12px; }
				.kpi-target-progress { height: 5px; overflow: hidden; border-radius: 999px; background: var(--control-bg); }
				.kpi-target-progress > span { display: block; height: 100%; min-width: 0; border-radius: inherit; background: var(--blue-500); transition: width .2s ease; }
				.kpi-target-progress > .orange { background: var(--orange-500); }
				.kpi-target-progress > .red { background: var(--red-500); }
				.kpi-module-chart {
					display: grid;
					grid-template-columns: minmax(200px, 240px) minmax(0, 1fr);
					align-items: center;
					column-gap: 24px;
					margin: 0 0 16px;
				}
				.kpi-module-chart h5 { grid-column: 1 / -1; }
				.kpi-donut-canvas .chart-container { margin: 0 auto; }
				.kpi-donut-legend { display: flex; flex-direction: column; gap: 10px; font-size: 13px; }
				.kpi-donut-legend-item { display: flex; align-items: center; gap: 8px; color: var(--text-muted); }
				.kpi-donut-legend-item i { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 9px; }
				.kpi-donut-legend-item b { margin-left: auto; color: var(--text-color); font-weight: 600; font-variant-numeric: tabular-nums; }
				.kpi-visual-grid, .kpi-pair-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
				.kpi-pair-grid.kpi-pair-single { grid-template-columns: minmax(0, 1fr); }
				.kpi-template-pair { margin-top: -14px; }
				.kpi-table-card h5, .kpi-chart h5, .kpi-donut-chart h5 {
					margin: 0 0 12px;
					color: var(--text-muted);
					font-size: 13px;
					font-weight: 600;
					letter-spacing: .02em;
				}
				.kpi-table-card table { width: 100%; font-size: 12.5px; }
				.kpi-table-card th {
					color: var(--text-muted);
					font-size: 11px;
					font-weight: 600;
					letter-spacing: .04em;
					text-transform: uppercase;
					white-space: nowrap;
				}
				.kpi-table-card th, .kpi-table-card td { padding: 10px 8px; border-bottom: 1px solid var(--border-color); text-align: left; vertical-align: middle; }
				.kpi-table-card tbody tr:last-child td { border-bottom: 0; }
				.kpi-metric-table td:first-child { width: 34%; font-weight: 500; }
				.kpi-metric-table td:not(:first-child), .kpi-metric-table th:not(:first-child) { text-align: right; }
				.kpi-table-name { width: 38%; min-width: 156px; }
				.kpi-table-number, .kpi-table-amount { min-width: 92px; text-align: right !important; white-space: nowrap; }
				.kpi-table-amount { font-weight: 600; }
				.kpi-table-card tbody tr { transition: background-color .16s ease; }
				.kpi-table-card tbody tr:not(.kpi-featured-row):hover td { background: var(--highlight-color); }
				.kpi-drilldown-row { cursor: pointer; outline: none; }
				.kpi-drilldown-row:focus-visible td { background: var(--highlight-color); box-shadow: inset 0 1px 0 var(--blue-500), inset 0 -1px 0 var(--blue-500); }
				.kpi-drilldown-row td:first-child { position: relative; }
				.kpi-drilldown-row td:first-child::after { content: "›"; display: inline-block; margin-left: 6px; color: var(--blue-500); font-size: 15px; line-height: 0; }
				.kpi-table-rate { display: grid; justify-items: end; gap: 4px; }
				.kpi-table-rate i { display: block; width: 72px; height: 4px; overflow: hidden; border-radius: 999px; background: var(--control-bg); }
				.kpi-table-rate b { display: block; height: 100%; border-radius: inherit; background: var(--blue-500); }
				.kpi-empty-state { display: flex; min-height: 112px; align-items: center; justify-content: center; gap: 8px; color: var(--text-muted); font-size: 13px; text-align: center; }
				.kpi-empty-mark { display: inline-flex; width: 22px; height: 22px; align-items: center; justify-content: center; border: 1px solid var(--border-color); border-radius: 50%; color: var(--blue-500); }
				.kpi-loading-dashboard { display: grid; gap: 30px; }
				.kpi-loading-section { display: grid; gap: 14px; }
				.kpi-loading-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
				.kpi-skeleton { display: block; min-height: 126px; border-radius: 14px; background: linear-gradient(90deg, var(--control-bg) 25%, var(--highlight-color) 50%, var(--control-bg) 75%); background-size: 200% 100%; animation: kpi-skeleton-shimmer 1.4s ease infinite; }
				.kpi-skeleton-title { min-height: 18px; width: 180px; border-radius: 5px; }
				@keyframes kpi-skeleton-shimmer { to { background-position: -200% 0; } }
				.kpi-metric-table tr.kpi-featured-row td { background: var(--highlight-color); font-weight: 600; }
				.kpi-metric-table tr.kpi-featured-row td:first-child { box-shadow: inset 3px 0 0 var(--kpi-hero-via); }
				.kpi-featured-value { display: grid; justify-items: end; gap: 6px; font-size: 15px; font-weight: 700; }
				.kpi-featured-value .kpi-target-progress { width: min(100%, 148px); }
				@media (max-width: 1199px) {
					.kpi-card-grid-featured { grid-template-columns: repeat(3, minmax(0, 1fr)); }
				}
				@media (max-width: 900px) {
					.operations-kpi-dashboard { padding: 18px 16px 36px; }
					.kpi-visual-grid, .kpi-pair-grid { grid-template-columns: 1fr; }
					.kpi-card-grid-featured, .kpi-loading-grid { grid-template-columns: 1fr; }
					.kpi-card-grid-featured .kpi-featured-card { grid-column: span 1; }
					.kpi-module-chart { grid-template-columns: 1fr; row-gap: 12px; }
					.kpi-donut-legend { flex-direction: row; flex-wrap: wrap; gap: 8px 16px; }
					.kpi-donut-legend-item b { margin-left: 0; }
				}
				@media (max-width: 640px) {
					.kpi-card-value { font-size: 22px; }
				}
			</style>`
		).appendTo(document.head);
	}
}
