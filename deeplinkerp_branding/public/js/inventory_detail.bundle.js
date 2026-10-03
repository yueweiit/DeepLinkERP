(function (globalThis) {
	"use strict";

	const DEFAULT_PAGE_LENGTH = 200;
	const MIN_PAGE_LENGTH = 1;
	const MAX_PAGE_LENGTH = 2500;
	const COUNT_UOM_TOKENS = [
		"个",
		"件",
		"套",
		"卷",
		"包",
		"张",
		"片",
		"支",
		"条",
		"台",
		"pieza",
		"conjunto",
		"rollo",
		"paquete",
		"hoja",
		"ramo",
		"barra",
		"unidad",
	];
	const COMPLEX_PURPOSE_MESSAGE =
		"该类型需要在标准物料移动表单中补充工单、BOM、批次、序列号或物料角色等字段。";

	function resolveDefaultCompany(framework) {
		const getter = framework?.defaults?.get_default;
		return typeof getter === "function"
			? String(getter.call(framework.defaults, "company") || "").trim()
			: "";
	}

	function escapeHtml(value) {
		return String(value ?? "").replace(
			/[&<>"']/g,
			(character) =>
				({
					"&": "&amp;",
					"<": "&lt;",
					">": "&gt;",
					'"': "&quot;",
					"'": "&#39;",
				}[character])
		);
	}

	function isCountUom(stockUom) {
		const normalized = String(stockUom || "")
			.trim()
			.toLowerCase();
		return COUNT_UOM_TOKENS.some((token) => normalized.includes(token));
	}

	function formatQuantity(value, stockUom) {
		if (value === null || value === undefined || value === "") return "—";
		const number = Number(value || 0);
		const integerCount = isCountUom(stockUom) && Math.abs(number - Math.round(number)) <= 1e-9;
		return number.toLocaleString("zh-CN", {
			minimumFractionDigits: integerCount ? 0 : 2,
			maximumFractionDigits: integerCount ? 0 : 2,
		});
	}

	function normalizePageLength(value) {
		const parsed = Number(value);
		if (!Number.isInteger(parsed) || parsed < MIN_PAGE_LENGTH || parsed > MAX_PAGE_LENGTH) {
			throw new Error(`每页行数必须是 ${MIN_PAGE_LENGTH} 到 ${MAX_PAGE_LENGTH} 的整数。`);
		}
		return parsed;
	}

	function rowspanAttribute(size) {
		return size > 1 ? ` rowspan="${Number(size)}"` : "";
	}

	function selectionKey(group) {
		return encodeURIComponent(
			JSON.stringify([String(group.item_code || ""), String(group.warehouse || "")])
		);
	}

	function selectionCell(group, size, selectedKeys) {
		const rowspan = rowspanAttribute(size);
		const key = selectionKey(group);
		const selectable = Boolean(String(group.warehouse || "").trim());
		const checked = selectable && selectedKeys?.has(key) ? " checked" : "";
		const disabled = selectable ? "" : ' disabled title="无仓库占位行不可移动"';
		return (
			`<td class="id-select"${rowspan}><input type="checkbox" data-selection-key="${escapeHtml(
				key
			)}"` + ` aria-label="选择 ${escapeHtml(group.item_code)}"${checked}${disabled}></td>`
		);
	}

	function updateCurrentPageSelection(groups, selected, checked) {
		const next = new Map(selected || []);
		(groups || [])
			.filter((group) => group.warehouse)
			.forEach((group) => {
				const key = selectionKey(group);
				if (checked) {
					next.set(key, {
						item_code: group.item_code,
						...(group.item_name ? { item_name: group.item_name } : {}),
						source_warehouse: group.warehouse,
					});
				} else {
					next.delete(key);
				}
			});
		return next;
	}

	function renderMaterialRows(groups, selectedKeys = new Set()) {
		if (!Array.isArray(groups) || !groups.length) {
			return '<tr class="id-empty"><td colspan="12">没有符合条件的库存库位记录。</td></tr>';
		}
		return groups
			.map((group) => {
				const locations =
					Array.isArray(group.locations) && group.locations.length
						? group.locations
						: [{ original_location: "", location_qty: 0 }];
				const rowspan = rowspanAttribute(locations.length);
				const itemCode = escapeHtml(group.item_code);
				const sharedBefore = [
					selectionCell(group, locations.length, selectedKeys),
					`<td class="id-code"${rowspan}><a href="#" data-item-code="${itemCode}">${itemCode}</a></td>`,
					`<td class="id-name"${rowspan}>${escapeHtml(group.item_name)}</td>`,
					`<td${rowspan}>${escapeHtml(group.warehouse || "—")}</td>`,
				].join("");
				const sharedAfter = [
					`<td class="id-quantity id-total"${rowspan}>${formatQuantity(
						group.total_qty,
						group.stock_uom
					)}</td>`,
					`<td${rowspan}>${escapeHtml(group.stock_uom)}</td>`,
					`<td${rowspan}>${escapeHtml(group.item_group)}</td>`,
					`<td${rowspan}>${escapeHtml(group.dpci)}</td>`,
					`<td${rowspan}>${escapeHtml(group.external_code)}</td>`,
					`<td${rowspan}>${escapeHtml(group.original_identifier_alias)}</td>`,
				].join("");
				return locations
					.map((location, index) => {
						const before = index === 0 ? sharedBefore : "";
						const after = index === 0 ? sharedAfter : "";
						return (
							`<tr>${before}<td>${escapeHtml(location.original_location)}</td>` +
							`<td class="id-quantity">${formatQuantity(
								location.location_qty,
								group.stock_uom
							)}</td>${after}</tr>`
						);
					})
					.join("");
			})
			.join("");
	}

	function renderCategorizedRows(groups, selectedKeys = new Set()) {
		if (!Array.isArray(groups) || !groups.length) {
			return '<tr class="id-empty"><td colspan="15">没有符合条件的库存记录。</td></tr>';
		}
		return groups
			.map((group) => {
				const locations =
					Array.isArray(group.locations) && group.locations.length
						? group.locations
						: [
								{
									reference_location: "库位待维护",
									snapshot_location_qty: null,
									snapshot_date: "",
								},
						  ];
				const rowspan = rowspanAttribute(locations.length);
				const itemCode = escapeHtml(group.item_code);
				const status = escapeHtml(group.inventory_status || "库位待维护");
				const quantityClass = Number(group.actual_qty || 0) < 0 ? " id-negative" : "";
				const statusClass =
					group.inventory_status === "库存差异"
						? " is-difference"
						: group.inventory_status === "库存一致"
						? " is-balanced"
						: " is-pending";
				const sharedBefore = [
					selectionCell(group, locations.length, selectedKeys),
					`<td class="id-code"${rowspan}><a href="#" data-item-code="${itemCode}">${itemCode}</a></td>`,
					`<td class="id-name"${rowspan}>${escapeHtml(group.item_name)}</td>`,
					`<td${rowspan}>${escapeHtml(group.warehouse || "—")}</td>`,
				].join("");
				const sharedMiddle = [
					`<td class="id-quantity${quantityClass}"${rowspan}>${formatQuantity(
						group.actual_qty,
						group.stock_uom
					)}</td>`,
					`<td class="id-quantity"${rowspan}>${formatQuantity(
						group.difference_qty,
						group.stock_uom
					)}</td>`,
					`<td${rowspan}><span class="id-status${statusClass}">${status}</span></td>`,
				].join("");
				const sharedAfter = [
					`<td${rowspan}>${escapeHtml(group.stock_uom)}</td>`,
					`<td${rowspan}>${escapeHtml(group.item_group)}</td>`,
					`<td${rowspan}>${escapeHtml(group.dpci)}</td>`,
					`<td${rowspan}>${escapeHtml(group.external_code)}</td>`,
					`<td${rowspan}>${escapeHtml(group.original_identifier_alias)}</td>`,
				].join("");
				return locations
					.map((location, index) => {
						const before = index === 0 ? sharedBefore : "";
						const middle = index === 0 ? sharedMiddle : "";
						const after = index === 0 ? sharedAfter : "";
						return (
							`<tr>${before}<td>${escapeHtml(
								location.reference_location || "库位待维护"
							)}</td>` +
							`<td class="id-quantity">${formatQuantity(
								location.snapshot_location_qty,
								group.stock_uom
							)}</td>` +
							`${middle}<td>${escapeHtml(
								location.snapshot_date || "—"
							)}</td>${after}</tr>`
						);
					})
					.join("");
			})
			.join("");
	}

	function downloadBase64File(result) {
		const bytes = atob(result.content_base64 || "");
		const data = new Uint8Array(bytes.length);
		for (let index = 0; index < bytes.length; index += 1)
			data[index] = bytes.charCodeAt(index);
		const url = URL.createObjectURL(new Blob([data], { type: result.mime_type }));
		const anchor = document.createElement("a");
		anchor.href = url;
		anchor.download = result.file_name || "inventory-detail.xlsx";
		document.body.appendChild(anchor);
		anchor.click();
		anchor.remove();
		URL.revokeObjectURL(url);
	}

	function materialTable() {
		return `<table aria-label="物料库存明细表">
      <colgroup>
        <col class="id-col-select"><col class="id-col-code"><col class="id-col-name"><col class="id-col-warehouse">
        <col class="id-col-location"><col class="id-col-quantity"><col class="id-col-quantity">
        <col class="id-col-uom"><col class="id-col-group"><col class="id-col-code-extra">
        <col class="id-col-code-extra"><col class="id-col-alias">
      </colgroup>
      <thead><tr>
        <th class="id-select"><input type="checkbox" data-select-current-page aria-label="全选当前页"></th>
        <th>正式物料编码</th><th>物料名称（双语）</th><th>仓库</th><th>原始库位</th>
        <th>库位数量</th><th>总库存</th><th>库存单位</th><th>物料组</th>
        <th>DPCI</th><th>外部编码</th><th>原始标识/别名</th>
      </tr></thead><tbody></tbody>
    </table>`;
	}

	function categorizedTable(title) {
		return `<table aria-label="${escapeHtml(title)}表">
      <colgroup>
        <col class="id-col-select"><col class="id-col-code"><col class="id-col-name"><col class="id-col-warehouse">
        <col class="id-col-location"><col class="id-col-quantity"><col class="id-col-quantity">
        <col class="id-col-quantity"><col class="id-col-status"><col class="id-col-date">
        <col class="id-col-uom"><col class="id-col-group"><col class="id-col-code-extra">
        <col class="id-col-code-extra"><col class="id-col-alias">
      </colgroup>
      <thead><tr>
        <th class="id-select"><input type="checkbox" data-select-current-page aria-label="全选当前页"></th>
        <th>正式物料编码</th><th>物料名称（双语）</th><th>仓库</th><th>参考库位</th>
        <th>快照库位数量</th><th>实时库存</th><th>库存差异</th><th>库存状态</th>
        <th>快照日期</th><th>库存单位</th><th>物料组</th><th>DPCI</th>
        <th>外部编码</th><th>原始标识/别名</th>
      </tr></thead><tbody></tbody>
    </table>`;
	}

	class InventoryDetailPage {
		constructor(wrapper, config) {
			this.wrapper = wrapper;
			this.config = config;
			this.isMaterial = config.category === "material";
			this.start = 0;
			this.pageLength = DEFAULT_PAGE_LENGTH;
			this.requestId = 0;
			this.selected = new Map();
			this.currentGroups = [];
			this.canCreateStockEntry = false;
			this.page = frappe.ui.make_app_page({
				parent: wrapper,
				title: config.title,
				single_column: true,
			});
			this.makeFilters();
			this.renderShell();
			this.bindEvents();
			this.refresh();
		}

		makeFilters() {
			const resetAndRefresh = () => {
				if (!this.suppressFilterChanges) this.refresh(true);
			};
			const defaultCompany = resolveDefaultCompany(frappe);
			this.company = defaultCompany;
			this.fields = {};
			this.fields.company = this.page.add_field({
				fieldname: "company",
				label: "公司",
				fieldtype: "Link",
				options: "Company",
				default: defaultCompany,
				change: () => this.changeCompany(),
			});
			if (this.isMaterial) {
				this.fields.snapshot_key = this.page.add_field({
					fieldname: "snapshot_key",
					label: "盘点快照",
					fieldtype: "Select",
					options: [""],
					change: resetAndRefresh,
				});
			}
			this.fields.warehouse = this.page.add_field({
				fieldname: "warehouse",
				label: "仓库",
				fieldtype: "Link",
				options: "Warehouse",
				get_query: () => ({
					filters: {
						company: this.fields.company.get_value() || defaultCompany,
						is_group: 0,
					},
				}),
				change: resetAndRefresh,
			});
			if (this.isMaterial) {
				this.fields.original_location = this.page.add_field({
					fieldname: "original_location",
					label: "原始库位",
					fieldtype: "Data",
				});
			} else {
				this.fields.item_group = this.page.add_field({
					fieldname: "item_group",
					label: "下级物料组",
					fieldtype: "Select",
					options: [""],
					change: resetAndRefresh,
				});
			}
			this.fields.keyword = this.page.add_field({
				fieldname: "keyword",
				label: "物料编码/名称",
				fieldtype: "Data",
			});
			if (this.isMaterial) {
				this.fields.item_group = this.page.add_field({
					fieldname: "item_group",
					label: "物料组",
					fieldtype: "Link",
					options: "Item Group",
					change: resetAndRefresh,
				});
			} else {
				this.fields.reference_location = this.page.add_field({
					fieldname: "reference_location",
					label: "参考库位",
					fieldtype: "Data",
				});
				this.fields.only_with_stock = this.page.add_field({
					fieldname: "only_with_stock",
					label: "只看有库存",
					fieldtype: "Check",
					default: 0,
					change: resetAndRefresh,
				});
			}
			this.fields.page_length = this.page.add_field({
				fieldname: "page_length",
				label: "每页行数",
				fieldtype: "Int",
				default: DEFAULT_PAGE_LENGTH,
				description: `${MIN_PAGE_LENGTH}–${MAX_PAGE_LENGTH}`,
				change: () => {
					try {
						this.pageLength = normalizePageLength(this.fields.page_length.get_value());
						resetAndRefresh();
					} catch (error) {
						frappe.msgprint(error.message);
					}
				},
			});
			this.page.set_primary_action("筛选", () => this.refresh(true), "filter");
			this.page.add_inner_button("清除筛选", () => this.clearFilters());
			this.page.add_inner_button("导出 Excel", () => this.exportExcel());
		}

		async changeCompany() {
			if (this.suppressFilterChanges || this.companyChangePending) return;
			const nextCompany = this.fields.company.get_value() || "";
			const previousCompany = this.company || "";
			if (nextCompany === previousCompany) return;
			const interruptedRefresh = Boolean(this.loading);
			let changedCompany = false;
			this.companyChangePending = true;
			++this.requestId; // Invalidate responses from the company being left.
			this.suppressFilterChanges = true;
			const restored = this.fields.company.set_value(previousCompany);
			this.updateMovementButton();
			const decision = this.selected.size
				? new Promise((resolve) => {
					const confirmation = frappe.confirm(
						"切换公司将清空已选物料，是否继续？",
						() => resolve(true), () => resolve(false));
					confirmation?.$wrapper?.on("hidden.bs.modal", () => {
						// Resolve dismissal after the primary/secondary action callbacks.
						queueMicrotask(() => resolve(false));
					});
				})
				: Promise.resolve(true);
			try {
				await restored;
				if (await decision) {
					changedCompany = true;
					this.resetSelection();
					this.company = nextCompany;
					this.selectionCompany = nextCompany;
					this.effectiveCompany = "";
					this.canCreateStockEntry = false;
					await this.fields.company.set_value(nextCompany);
					for (const key of ["snapshot_key", "warehouse", ...(!this.isMaterial ? ["item_group"] : [])]) {
						if (this.fields[key]) await this.fields[key].set_value("");
					}
				}
			} finally {
				// A second edit while the confirmation is open must not commit a third company.
				await this.fields.company.set_value(this.company || "");
				this.companyChangePending = false;
				this.suppressFilterChanges = false;
				this.loading = false;
				this.$root?.removeClass("is-loading");
				this.updateMovementButton();
			}
			if (changedCompany || interruptedRefresh) return this.refresh(changedCompany);
		}

		renderShell() {
			this.$root = $(
				`<section class="inventory-detail" aria-label="${escapeHtml(this.config.title)}">
          <div class="id-actions">
            <button type="button" class="btn btn-default btn-sm" data-inventory-action="selected">已选物料 (0)</button>
            <button type="button" class="btn btn-default btn-sm" data-inventory-action="movement" disabled aria-disabled="true">物料移动 (0)</button>
          </div>
          <div class="id-summary" role="status">正在读取库存…</div>
          <div class="id-table-wrap">${
				this.isMaterial ? materialTable() : categorizedTable(this.config.title)
			}</div>
          <div class="id-pager">
            <button type="button" class="btn btn-default btn-sm" data-page-action="previous">上一页</button>
            <span class="id-page-label">第 1 页</span>
            <button type="button" class="btn btn-default btn-sm" data-page-action="next">下一页</button>
          </div>
        </section>`
			);
			$(this.page.body).children(":not(.page-form)").remove();
			$(this.page.body).append(this.$root);
			this.$movementButton = this.$root.find('[data-inventory-action="movement"]');
			this.$selectedButton = this.$root.find('[data-inventory-action="selected"]');
			this.updateMovementButton();
		}

		bindEvents() {
			this.$root.on("click", '[data-inventory-action="selected"]', () => this.openSelectionDialog());
			this.$root.on("click", '[data-inventory-action="movement"]', () =>
				this.openMovementDialog()
			);
			this.$root.on("click", "[data-item-code]", (event) => {
				event.preventDefault();
				frappe.set_route("Form", "Item", $(event.currentTarget).attr("data-item-code"));
			});
			this.$root.on("change", "[data-selection-key]", (event) => {
				if (this.loading || this.companyChangePending || !this.effectiveCompany) return;
				const key = $(event.currentTarget).attr("data-selection-key");
				const group = this.currentGroups.find((row) => selectionKey(row) === key);
				if (!group?.warehouse) return;
				if (event.currentTarget.checked) {
					this.selected.set(key, {
						item_code: group.item_code,
						item_name: group.item_name || "",
						source_warehouse: group.warehouse,
					});
				} else {
					this.selected.delete(key);
				}
				this.updateSelectionUi();
			});
			this.$root.on("change", "[data-select-current-page]", (event) => {
				if (this.loading || this.companyChangePending || !this.effectiveCompany) return;
				this.selected = updateCurrentPageSelection(
					this.currentGroups,
					this.selected,
					event.currentTarget.checked
				);
				this.renderRows();
			});
			this.$root.on("click", "[data-page-action]", (event) => {
				const action = $(event.currentTarget).attr("data-page-action");
				if (action === "previous" && this.start > 0) {
					this.start = Math.max(0, this.start - this.pageLength);
					this.refresh();
				}
				if (action === "next" && this.lastPayload?.has_next) {
					this.start += this.pageLength;
					this.refresh();
				}
			});
			["keyword", "original_location", "reference_location"].forEach((fieldname) => {
				this.fields[fieldname]?.$input?.on("keydown", (event) => {
					if (event.key === "Enter") this.refresh(true);
				});
			});
		}

		filters() {
			return Object.fromEntries(
				Object.entries(this.fields)
					.filter(([key]) => key !== "page_length")
					.map(([key, field]) => [key, field.get_value()])
					.filter(
						([, value]) =>
							value !== null && value !== undefined && String(value).trim() !== ""
					)
			);
		}

		resetSelection() {
			this.selected.clear();
			const $selectionInputs = this.$root?.find(
				"[data-selection-key], [data-select-current-page]"
			);
			if ($selectionInputs?.length) {
				$selectionInputs.prop("checked", false);
				$selectionInputs.prop("indeterminate", false);
			}
			this.updateSelectionUi();
		}

		updateSelectionUi() {
			this.$selectedButton?.text(`已选物料 (${this.selected.size})`);
			const selectableKeys = this.currentGroups
				.filter((group) => group.warehouse)
				.map(selectionKey);
			const selectedCount = selectableKeys.filter((key) => this.selected.has(key)).length;
			const header = this.$root?.find("[data-select-current-page]");
			if (header?.length) {
				header.prop(
					"checked",
					selectableKeys.length > 0 && selectedCount === selectableKeys.length
				);
				header.prop(
					"indeterminate",
					selectedCount > 0 && selectedCount < selectableKeys.length
				);
			}
			this.updateMovementButton();
		}

		updateMovementButton() {
			if (!this.$movementButton?.length) return;
			const label = `物料移动 (${this.selected.size})`;
			const reason = this.movementDisabledReason || "";
			const disabled = !this.canCreateStockEntry || this.selected.size === 0 ||
				Boolean(this.loading || this.companyChangePending) ||
				Boolean(this.fields && (!this.effectiveCompany ||
					this.effectiveCompany !== this.company ||
					this.effectiveCompany !== this.selectionCompany ||
					this.effectiveCompany !== this.fields.company.get_value()));
			this.$movementButton.text(label);
			this.$movementButton.prop("disabled", disabled);
			this.$movementButton.attr("aria-disabled", disabled ? "true" : "false");
			this.$movementButton.attr("title", reason);
		}

		renderRows() {
			const keys = new Set(this.selected.keys());
			const html = this.isMaterial
				? renderMaterialRows(this.currentGroups, keys)
				: renderCategorizedRows(this.currentGroups, keys);
			this.$root.find("tbody").html(html);
			this.updateSelectionUi();
		}

		async refresh(resetStart = false) {
			if (this.companyChangePending || this.suppressFilterChanges) return;
			if ((this.fields.company.get_value() || "") !== (this.company || "")) {
				return this.changeCompany();
			}
			if (resetStart) this.start = 0;
			try {
				this.pageLength = normalizePageLength(this.fields.page_length.get_value());
			} catch (error) {
				frappe.msgprint(error.message);
				return;
			}
			const requestId = ++this.requestId;
			const requestedCompany = this.company;
			this.loading = true;
			this.canCreateStockEntry = false;
			this.updateMovementButton();
			this.$root.addClass("is-loading");
			this.$root.find("[data-selection-key], [data-select-current-page]").prop("disabled", true);
			this.$root.find(".id-summary").text("正在读取库存…");
			try {
				const method = this.isMaterial
					? "deeplinkerp_branding.services.inventory_detail_service.get_inventory_location_detail"
					: "deeplinkerp_branding.services.inventory_detail_service.get_categorized_inventory_detail";
				const args = {
					filters: this.filters(),
					start: this.start,
					page_length: this.pageLength,
				};
				if (!this.isMaterial) args.category = this.config.category;
				const response = await frappe.call({ method, args });
				if (requestId !== this.requestId) return;
				const payload = response.message || {};
				if (payload.company && payload.company !== requestedCompany) {
					throw new Error("公司信息已变化，请重新选择公司后读取库存。");
				}
				this.lastPayload = payload;
				this.currentGroups = payload.groups || [];
				this.effectiveCompany = payload.company || "";
				this.selectionCompany = this.effectiveCompany;
				this.canCreateStockEntry = Boolean(payload.can_create_stock_entry) &&
					Boolean(this.effectiveCompany) && this.effectiveCompany === requestedCompany;
				this.movementDisabledReason = payload.movement_disabled_reason || "";
				if (this.isMaterial) this.setSnapshotOptions(payload.snapshot_options || []);
				else this.setItemGroupOptions(payload.item_group_options || []);
				this.renderRows();
				const snapshot = payload.snapshot_date || payload.snapshot_key || "暂无库位快照";
				const summary =
					payload.warning ||
					(this.isMaterial
						? `盘点快照 ${snapshot} · ${Number(
								payload.total_count || 0
						  )} 个物料仓库组 · 当前 ${Number(payload.page_count || 0)} 条`
						: `ERP 实时库存 · ${Number(
								payload.total_count || 0
						  )} 个物料仓库组 · 当前 ${Number(
								payload.page_count || 0
						  )} 条 · 参考快照 ${snapshot}`);
				this.$root.find(".id-summary").text(summary);
				this.renderPager(payload);
			} catch (error) {
				if (requestId !== this.requestId) return;
				this.canCreateStockEntry = false;
				this.currentGroups = [];
				this.renderRows();
				this.$root.find(".id-summary").text(error.message || "库存明细读取失败。");
			} finally {
				if (requestId === this.requestId) {
					this.loading = false;
					this.$root.removeClass("is-loading");
					this.updateMovementButton();
				}
			}
		}

		renderPager(payload) {
			const page = Math.floor(Number(payload.start || 0) / this.pageLength) + 1;
			const pages = Math.max(
				1,
				Math.ceil(Number(payload.total_count || 0) / this.pageLength)
			);
			this.$root.find(".id-page-label").text(`第 ${page} / ${pages} 页`);
			this.$root
				.find('[data-page-action="previous"]')
				.prop("disabled", !payload.has_previous);
			this.$root.find('[data-page-action="next"]').prop("disabled", !payload.has_next);
		}

		setSnapshotOptions(options) {
			const current = this.fields.snapshot_key.get_value() || "";
			const values = [
				"",
				...options.map((option) => String(option.snapshot_key || "")).filter(Boolean),
			];
			this.fields.snapshot_key.df.options = [...new Set(values)];
			this.fields.snapshot_key.refresh();
			if (current && !values.includes(current)) this.fields.snapshot_key.set_value("");
		}

		setItemGroupOptions(options) {
			const current = this.fields.item_group.get_value() || "";
			const values = ["", ...options.map(String).filter(Boolean)];
			this.fields.item_group.df.options = [...new Set(values)];
			this.fields.item_group.refresh();
			if (current && !values.includes(current)) this.fields.item_group.set_value("");
		}

		clearFilters() {
			Object.entries(this.fields).forEach(([key, field]) => {
				if (key === "company") return;
				if (key === "page_length") field.set_value(DEFAULT_PAGE_LENGTH);
				else field.set_value(key === "only_with_stock" ? 0 : "");
			});
			this.pageLength = DEFAULT_PAGE_LENGTH;
			this.refresh(true);
		}

		async exportExcel() {
			const method = this.isMaterial
				? "deeplinkerp_branding.services.inventory_detail_service.export_inventory_location_detail"
				: "deeplinkerp_branding.services.inventory_detail_service.export_categorized_inventory_detail";
			const args = { filters: this.filters() };
			if (!this.isMaterial) args.category = this.config.category;
			const response = await frappe.call({
				method,
				args,
				freeze: true,
				freeze_message: "正在生成 Excel…",
			});
			downloadBase64File(response.message || {});
		}

		canMoveSelection() {
			return !this.loading && !this.companyChangePending && this.canCreateStockEntry &&
				this.selected.size > 0 && Boolean(this.effectiveCompany) &&
				this.effectiveCompany === this.company &&
				this.effectiveCompany === this.selectionCompany &&
				this.effectiveCompany === this.fields.company.get_value();
		}

		openSelectionDialog() {
			const dialog = new frappe.ui.Dialog({
				title: "已选物料",
				fields: [{ fieldname: "selections", fieldtype: "HTML" }],
				primary_action_label: "清空已选",
				primary_action: () => { this.resetSelection(); this.renderRows(); render(); },
			});
			const wrapper = dialog.fields_dict.selections.$wrapper;
			const render = () => wrapper.html(this.selected.size
				? `<table class="table table-bordered"><thead><tr><th>物料编码</th><th>物料名称</th><th>来源仓库</th><th></th></tr></thead><tbody>${
					[...this.selected.entries()].map(([key, row]) => `<tr><td>${escapeHtml(row.item_code)}</td><td>${escapeHtml(row.item_name || "")}</td><td>${escapeHtml(row.source_warehouse)}</td><td><button type="button" class="btn btn-default btn-xs" data-remove-selection="${escapeHtml(key)}">移除</button></td></tr>`).join("")
				}</tbody></table>` : '<div class="text-muted">暂无已选物料</div>');
			wrapper.on("click", "[data-remove-selection]", (event) => {
				this.selected.delete($(event.currentTarget).attr("data-remove-selection"));
				this.renderRows();
				render();
			});
			render();
			dialog.show();
		}

		async openMovementDialog() {
			if (!this.canMoveSelection()) return;
			const company = this.effectiveCompany;
			const requestId = this.requestId;
			const selections = JSON.stringify([...this.selected.values()]);
			let response;
			try {
				response = await frappe.call({
					method: "deeplinkerp_branding.services.inventory_detail_service.get_inventory_movement_context",
					args: { company, selections },
					freeze: true,
					freeze_message: "正在重新核对实时库存…",
				});
			} catch (error) {
				if (requestId !== this.requestId) return;
				this.canCreateStockEntry = false;
				this.movementDisabledReason = error.message || "实时库存核对失败，请刷新库存后重试。";
				this.updateMovementButton();
				frappe.msgprint(this.movementDisabledReason);
				return;
			}
			if (requestId !== this.requestId || !this.canMoveSelection() ||
				selections !== JSON.stringify([...this.selected.values()])) return;
			const context = response.message || {};
			const typePurposes = new Map(
				(context.stock_entry_types || []).map((row) => [row.name, row.purpose])
			);
			const dialog = new frappe.ui.Dialog({
				title: `物料移动（${context.items?.length || 0} 项）`,
				size: "extra-large",
				fields: [
					{
						fieldname: "stock_entry_type",
						label: "移动类型",
						fieldtype: "Link",
						options: "Stock Entry Type",
						reqd: 1,
						get_query: () => ({
							filters: {
								purpose: [
									"not in",
									[
										"Receive from Customer",
										"Return Raw Material to Customer",
										"Subcontracting Delivery",
										"Subcontracting Return",
									],
								],
							},
						}),
						change: () => this.updateMovementPurpose(dialog, typePurposes),
					},
					{
						fieldname: "target_warehouse",
						label: "统一目标仓库",
						fieldtype: "Link",
						options: "Warehouse",
						hidden: 1,
						get_query: () => ({ filters: { company, is_group: 0 } }),
					},
					{ fieldname: "movement_notice", fieldtype: "HTML" },
					{
						fieldname: "items",
						label: "移动物料",
						fieldtype: "Table",
						cannot_add_rows: true,
						cannot_delete_rows: true,
						in_place_edit: true,
						data: (context.items || []).map((row) => ({
							...row,
							qty: Number(row.actual_qty || 0) > 0 ? 1 : 0,
						})),
						fields: [
							{
								fieldname: "item_code",
								label: "物料",
								fieldtype: "Link",
								options: "Item",
								in_list_view: 1,
								read_only: 1,
								columns: 2,
							},
							{
								fieldname: "item_name",
								label: "名称",
								fieldtype: "Data",
								in_list_view: 1,
								read_only: 1,
								columns: 2,
							},
							{
								fieldname: "source_warehouse",
								label: "来源仓库",
								fieldtype: "Link",
								options: "Warehouse",
								in_list_view: 1,
								read_only: 1,
								columns: 2,
							},
							{
								fieldname: "actual_qty",
								label: "实时可用量",
								fieldtype: "Float",
								in_list_view: 1,
								read_only: 1,
								columns: 2,
							},
							{
								fieldname: "qty",
								label: "移动数量",
								fieldtype: "Float",
								in_list_view: 1,
								reqd: 1,
								columns: 2,
							},
							{
								fieldname: "stock_uom",
								label: "单位",
								fieldtype: "Link",
								options: "UOM",
								in_list_view: 1,
								read_only: 1,
								columns: 1,
							},
						],
					},
				],
				primary_action_label: "打开未保存物料移动单",
				primary_action: (values) => this.prepareMovement(dialog, values, company, requestId, selections),
			});
			dialog.show();
		}

		updateMovementPurpose(dialog, typePurposes) {
			const stockEntryType = dialog.get_value("stock_entry_type");
			const purpose = typePurposes.get(stockEntryType) || "";
			const requiresTarget = ["Material Receipt", "Material Transfer"].includes(purpose);
			dialog.set_df_property("target_warehouse", "hidden", !requiresTarget);
			dialog.set_df_property("target_warehouse", "reqd", requiresTarget);
			const isComplex =
				purpose &&
				!["Material Receipt", "Material Issue", "Material Transfer"].includes(purpose);
			dialog.fields_dict.movement_notice.$wrapper.html(
				isComplex
					? `<div class="alert alert-warning">${escapeHtml(
							COMPLEX_PURPOSE_MESSAGE
					  )}</div>`
					: ""
			);
		}

		async prepareMovement(dialog, values, company, requestId = this.requestId,
			selections = JSON.stringify([...this.selected.values()])) {
			const isCurrent = () => this.canMoveSelection() && company === this.effectiveCompany &&
				requestId === this.requestId && selections === JSON.stringify([...this.selected.values()]);
			if (!isCurrent()) {
				frappe.msgprint("库存列表或已选物料已变化，请重新打开物料移动。");
				return;
			}
			const rows = (values.items || []).map((row) => ({
				item_code: row.item_code,
				source_warehouse: row.source_warehouse,
				qty: Number(row.qty),
			}));
			if (rows.some((row) => !Number.isFinite(row.qty) || row.qty <= 0)) {
				frappe.msgprint("每个物料的移动数量都必须大于零。");
				return;
			}
			const response = await frappe.call({
				method: "deeplinkerp_branding.services.inventory_detail_service.prepare_inventory_stock_entry",
				args: {
					company,
					stock_entry_type: values.stock_entry_type,
					target_warehouse: values.target_warehouse || "",
					items: JSON.stringify(rows),
				},
				freeze: true,
				freeze_message: "正在准备标准物料移动单…",
			});
			if (!isCurrent()) return;
			const result = response.message || {};
			dialog.hide();
			if (result.requires_completion && result.completion_message) {
				frappe.show_alert({ message: result.completion_message, indicator: "orange" }, 8);
			}
			this.openUnsavedStockEntry(result.stock_entry || {});
		}

		openUnsavedStockEntry(document) {
			frappe.model.sync(document);
			frappe.set_route("Form", "Stock Entry", document.name);
		}
	}

	function bootstrap(wrapper, config) {
		return new InventoryDetailPage(wrapper, config);
	}

	const api = {
		DEFAULT_PAGE_LENGTH,
		MIN_PAGE_LENGTH,
		MAX_PAGE_LENGTH,
		escapeHtml,
		formatQuantity,
		normalizePageLength,
		renderMaterialRows,
		renderCategorizedRows,
		selectionKey,
		updateCurrentPageSelection,
		resolveDefaultCompany,
		InventoryDetailPage,
		bootstrap,
	};
	globalThis.InventoryDetail = api;
	if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
