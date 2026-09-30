(function () {
	if (window.__custom_filters_list_column_resize_loaded) return;
	window.__custom_filters_list_column_resize_loaded = true;

	const VERSION = "2026.09.30.1";
	const LIST_CLASS = "custom-filters-resizable-list";
	const HANDLE_CLASS = "custom-filters-grid-column-resize-handle";

	function boot() {
		if (!window.CustomFiltersColumnResizeController || !window.frappe?.model) {
			window.setTimeout(boot, 100);
			return;
		}
		if (window.CustomFiltersListColumnResize) return;

		class ListColumnResizeController extends window.CustomFiltersColumnResizeController {
			constructor() {
				super();
				this.feature_name = "list_column_resize";
				this.list_states = new WeakMap();
				this.scrollbar_update_scheduled = false;
			}

			scan() {
				if (this.active_resize) return;
				document.querySelectorAll(".list-view .frappe-list .result").forEach((result) => {
					// Mobile has a different row structure and retains its native layout.
					if (frappe.is_mobile?.() || window.innerWidth < 768) {
						result.classList.remove(LIST_CLASS);
						result.parentElement?.classList.remove(`${LIST_CLASS}-container`);
						return;
					}
					if (result.getBoundingClientRect().width > 0) this.enhance_list(result);
				});
			}

			get_context(result) {
				// Cached Desk pages coexist. Match the actual result node, never just cur_list.
				const views = [window.cur_list, ...Object.values(frappe.views?.list_view || {})];
				const view = views.find((candidate) => candidate?.$result?.[0] === result);
				if (!view || view.view_name !== "List" || !view.columns?.length) return null;
				return {
					form_grid: result,
					view,
					parent_doctype: view.doctype,
					table_fieldname: "List",
					settings_key: "ListColumnWidths",
				};
			}

			get_width_limits() {
				// Allow narrow status/number columns and wide document identifiers.
				return { min: 64, max: 1200 };
			}

			apply_width(result, fieldname, width) {
				const index = this.list_states.get(result)?.index_by_key.get(fieldname);
				if (index === undefined) return;
				// One CSS variable updates the header and every row, even on a 2500-row list.
				const property = `--cf-list-width-${index}`;
				const value = `${width}px`;
				if (result.style.getPropertyValue(property) !== value) result.style.setProperty(property, value);
				this.update_grid_scrollbar();
			}

			update_grid_scrollbar() {
				if (this.scrollbar_update_scheduled) return;
				this.scrollbar_update_scheduled = true;
				window.requestAnimationFrame(() => {
					this.scrollbar_update_scheduled = false;
					window.CustomFiltersListHorizontalScroll?.update_all();
				});
			}

			bind_column(element, index) {
				if (element.dataset.cfListColumn === String(index)) return;
				element.dataset.cfListColumn = String(index);
				element.style.setProperty("--cf-list-column-width", `var(--cf-list-width-${index})`);
			}

			enhance_list(result) {
				const context = this.get_context(result);
				if (!context) return;
				const header = result.querySelector(".list-row-head > .list-header-subject");
				if (!header || !header.getBoundingClientRect().width) return;
				const headers = [...header.children].filter((cell) => cell.classList.contains("list-row-col"));
				if (headers.length < context.view.columns.length) return;

				const index_by_key = new Map();
				const columns = context.view.columns.map((column, index) => {
					// Type distinguishes the native Status column from an explicit status field.
					// Stable field names survive reordered columns and translated labels.
					const key = `${column.type}:${column.df?.fieldname || column.type}`;
					index_by_key.set(key, index);
					return { key, index, header: headers[index], label: column.df?.label || column.type };
				});
				this.list_states.set(result, { index_by_key });

				// Measure all native widths before fixing any column's flex basis.
				columns.forEach(({ key, header }) => this.get_default_width(result, key, header));
				result.classList.add(LIST_CLASS);
				result.parentElement?.classList.add(`${LIST_CLASS}-container`);

				// Status and tag body cells have no field-name class in native ListView.
				// Map by the rendered column definitions, not labels or content selectors.
				const rows = result.querySelectorAll(":scope > .list-row-container > .list-row > .level-left");
				rows.forEach((row) => {
					const cells = [...row.children].filter((cell) => cell.classList.contains("list-row-col"));
					columns.forEach(({ index }) => {
						if (cells[index]) this.bind_column(cells[index], index);
					});
				});

				columns.forEach(({ key, index, header, label }) => {
					this.bind_column(header, index);
					const limits = this.get_width_limits(header);
					const default_width = this.get_default_width(result, key, header);
					const width = this.clamp_width(this.get_saved_width(context, key) || default_width, limits);
					this.apply_width(result, key, width);
					let handle = header.querySelector(`.${HANDLE_CLASS}`);
					if (handle && handle.dataset.resizeField !== key) {
						handle.remove();
						handle = null;
					}
					if (!handle) {
						this.create_resize_handle(header, context, key, limits, width);
						handle = header.querySelector(`.${HANDLE_CLASS}`);
					}
					handle.setAttribute("aria-label", __("Resize {0}", [__(label)]));
					this.update_handle(handle, width, limits);
				});
			}
		}

		window.CustomFiltersListColumnResize = new ListColumnResizeController();
		window.CustomFiltersListColumnResize.start();
	}

	window.__custom_filters_list_column_resize_version = VERSION;
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
	else boot();
})();
