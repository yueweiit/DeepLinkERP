(function () {
	if (window.__custom_filters_grid_column_resize_loaded) return;
	window.__custom_filters_grid_column_resize_loaded = true;

	const VERSION = "2026.08.31.2";
	const MAX_COLUMN_WIDTH = 420;
	const MIN_COLUMN_WIDTH = 48;
	const RESIZE_HANDLE_CLASS = "custom-filters-grid-column-resize-handle";
	const TOP_SCROLLBAR_CLASS = "custom-filters-grid-top-scrollbar";
	const SETTINGS_KEY = "GridColumnWidths";
	const NATIVE_COLUMN_WIDTHS = {
		1: 60,
		2: 100,
		3: 140,
		4: 200,
		5: 250,
		6: 300,
		7: 350,
		8: 400,
		9: 450,
		10: 500,
		11: 550,
		12: 600,
	};

	function get_text(text, args) {
		return typeof __ === "function" ? __(text, args) : text;
	}

	class GridColumnResizeController {
		constructor() {
			this.scan_scheduled = false;
			this.active_resize = null;
			this.default_widths = new WeakMap();
			this.top_scrollbars = new WeakMap();
			this.save_queue = Promise.resolve();
			this.observer = null;

			this.handle_pointer_move = this.handle_pointer_move.bind(this);
			this.handle_pointer_up = this.handle_pointer_up.bind(this);
		}

		start() {
			if (!document.body) {
				window.setTimeout(() => this.start(), 100);
				return;
			}

			this.observer = new MutationObserver(() => this.schedule_scan());
			this.observer.observe(document.body, { childList: true, subtree: true });

			if (window.$) {
				$(document).on("page-change.custom_filters_grid_column_resize", () => {
					this.schedule_scan();
				});
				$(document).on("change.custom_filters_grid_column_resize", ".grid-field", () => {
					this.schedule_scan();
				});
			}

			window.addEventListener("resize", () => this.schedule_scan());
			this.schedule_scan();
			console.info(`[custom_filters grid_column_resize] version ${VERSION}`);
		}

		schedule_scan() {
			if (this.scan_scheduled) return;
			this.scan_scheduled = true;

			const run = () => {
				this.scan_scheduled = false;
				this.scan();
			};
			if (window.requestAnimationFrame) window.requestAnimationFrame(run);
			else window.setTimeout(run, 0);
		}

		scan() {
			document.querySelectorAll(".grid-field .form-grid").forEach((form_grid) => {
				this.enhance_grid(form_grid);
			});
		}

		get_context(form_grid) {
			const field_wrapper = form_grid.closest(".frappe-control");
			const field = field_wrapper && field_wrapper.fieldobj;
			const grid = field && field.grid;
			const parent_doctype = grid?.frm?.doctype || window.cur_frm?.doctype || null;
			const table_fieldname = grid?.df?.fieldname || field_wrapper?.dataset.fieldname || null;
			const child_doctype = grid?.doctype || grid?.df?.options || null;

			return {
				form_grid,
				grid,
				parent_doctype,
				table_fieldname,
				child_doctype,
			};
		}

		get_settings(context) {
			if (!context.parent_doctype || !window.frappe?.get_user_settings) return {};
			return frappe.get_user_settings(context.parent_doctype, SETTINGS_KEY) || {};
		}

		get_saved_width(context, fieldname) {
			if (!context.table_fieldname) return null;
			const table_settings = this.get_settings(context)[context.table_fieldname] || {};
			const width = Number(table_settings[fieldname]);
			return Number.isFinite(width) && width > 0 ? width : null;
		}

		ensure_settings_loaded(parent_doctype) {
			if (!parent_doctype || !frappe.model?.user_settings) return Promise.resolve();
			if (frappe.model.user_settings[parent_doctype]) return Promise.resolve();
			if (!frappe.model.user_settings.get) return Promise.resolve();

			return frappe.model.user_settings.get(parent_doctype).then((settings) => {
				frappe.model.user_settings[parent_doctype] = settings || {};
			});
		}

		save_width(context, fieldname, width) {
			if (!context.parent_doctype || !context.table_fieldname) return;

			const value = {
				[context.table_fieldname]: {
					[fieldname]: width === null ? null : Math.round(width),
				},
			};

			this.save_queue = this.save_queue
				.catch(() => undefined)
				.then(() => {
					if (!frappe.model?.user_settings?.save) return undefined;
					return this.ensure_settings_loaded(context.parent_doctype).then(() =>
						frappe.model.user_settings.save(
							context.parent_doctype,
							SETTINGS_KEY,
							value
						)
					);
				});
		}

		get_header_row(form_grid) {
			return [...form_grid.querySelectorAll(".grid-heading-row .data-row")].find(
				(row) => !row.classList.contains("filter-row")
			);
		}

		get_header_columns(header_row) {
			return [...header_row.children].filter(
				(column) => column.classList.contains("grid-static-col") && column.dataset.fieldname
			);
		}

		prepare_search_columns(form_grid, fieldnames) {
			const search_row = form_grid.querySelector(".grid-heading-row .data-row.filter-row");
			if (!search_row) return;

			const search_columns = [...search_row.children].filter((column) =>
				column.classList.contains("grid-static-col") && column.classList.contains("search")
			);
			search_columns.forEach((column, index) => {
				if (fieldnames[index]) column.dataset.fieldname = fieldnames[index];
			});
		}

		measure_label_width(header_column) {
			const label = header_column.querySelector(".static-area") || header_column;
			const text = (label.textContent || "").trim();
			if (!text || !document.body) return MIN_COLUMN_WIDTH;

			const style = window.getComputedStyle(label);
			const measure = document.createElement("span");
			Object.assign(measure.style, {
				position: "fixed",
				left: "-10000px",
				top: "-10000px",
				visibility: "hidden",
				whiteSpace: "nowrap",
				fontFamily: style.fontFamily,
				fontSize: style.fontSize,
				fontWeight: style.fontWeight,
				letterSpacing: style.letterSpacing,
			});
			measure.textContent = text;
			document.body.appendChild(measure);
			const text_width = measure.getBoundingClientRect().width;
			measure.remove();

			// Include cell padding and enough room for the resize handle.
			return Math.max(MIN_COLUMN_WIDTH, Math.ceil(text_width + 24));
		}

		get_native_width(form_grid, header_column) {
			const rendered_width = Math.round(header_column.getBoundingClientRect().width);
			if (rendered_width > 0) return rendered_width;

			const size_class = [...header_column.classList].find((name) => /^col-xs-\d+$/.test(name));
			const size = size_class && Number(size_class.replace("col-xs-", ""));
			return NATIVE_COLUMN_WIDTHS[size] || 140;
		}

		get_default_width(form_grid, fieldname, header_column) {
			let widths = this.default_widths.get(form_grid);
			if (!widths) {
				widths = new Map();
				this.default_widths.set(form_grid, widths);
			}

			if (!widths.has(fieldname)) {
				widths.set(fieldname, this.get_native_width(form_grid, header_column));
			}
			return widths.get(fieldname);
		}

		get_width_limits(header_column) {
			const min_width = this.measure_label_width(header_column);
			return {
				min: min_width,
				max: Math.max(MAX_COLUMN_WIDTH, min_width),
			};
		}

		clamp_width(width, limits) {
			return Math.round(Math.max(limits.min, Math.min(limits.max, width)));
		}

		apply_width(form_grid, fieldname, width) {
			form_grid.querySelectorAll(".grid-static-col").forEach((column) => {
				if (column.dataset.fieldname !== fieldname) return;
				column.style.setProperty("width", `${width}px`, "important");
				column.style.setProperty("min-width", `${width}px`, "important");
				column.style.setProperty("max-width", `${width}px`, "important");
				column.style.setProperty("flex", `0 0 ${width}px`, "important");
			});
			this.update_grid_scrollbar(form_grid);
		}

		update_top_scrollbar(state) {
			if (!state || !state.top.isConnected || !state.container.isConnected) return;

			const scroll_width = Math.max(state.container.scrollWidth, state.container.clientWidth);
			state.inner.style.width = `${scroll_width}px`;
			const has_horizontal_overflow = state.container.scrollWidth > state.container.clientWidth + 1;
			state.top.classList.toggle("is-visible", has_horizontal_overflow);

			if (has_horizontal_overflow && Math.abs(state.top.scrollLeft - state.container.scrollLeft) > 1) {
				state.top.scrollLeft = state.container.scrollLeft;
			}
		}

		update_grid_scrollbar(form_grid) {
			this.update_top_scrollbar(this.top_scrollbars.get(form_grid));
		}

		ensure_top_scrollbar(form_grid) {
			const container = form_grid.closest(".form-grid-container");
			if (!container || !container.parentElement) return;

			let state = this.top_scrollbars.get(form_grid);
			if (state && (state.container !== container || !state.top.isConnected)) {
				state.resize_observer?.disconnect();
				state.top.remove();
				state = null;
			}

			if (!state) {
				const top = document.createElement("div");
				top.className = TOP_SCROLLBAR_CLASS;
				top.setAttribute("aria-label", get_text("Horizontal scroll"));
				top.setAttribute("role", "scrollbar");

				const inner = document.createElement("div");
				inner.className = `${TOP_SCROLLBAR_CLASS}-inner`;
				top.appendChild(inner);
				container.parentElement.insertBefore(top, container);

				state = {
					top,
					inner,
					container,
					syncing: false,
					resize_observer: null,
				};
				this.top_scrollbars.set(form_grid, state);

				top.addEventListener("scroll", () => {
					if (state.syncing) return;
					state.syncing = true;
					container.scrollLeft = top.scrollLeft;
					state.syncing = false;
				});
				container.addEventListener("scroll", () => {
					if (state.syncing) return;
					state.syncing = true;
					top.scrollLeft = container.scrollLeft;
					state.syncing = false;
				});

				if (window.ResizeObserver) {
					state.resize_observer = new ResizeObserver(() => this.update_top_scrollbar(state));
					state.resize_observer.observe(container);
					state.resize_observer.observe(form_grid);
				}
			}

			this.update_top_scrollbar(state);
		}

		update_handle(handle, width, limits) {
			handle.setAttribute("aria-valuemin", limits.min);
			handle.setAttribute("aria-valuemax", limits.max);
			handle.setAttribute("aria-valuenow", width);
		}

		create_resize_handle(header_column, context, fieldname, limits, width) {
			const handle = document.createElement("span");
			handle.className = RESIZE_HANDLE_CLASS;
			handle.setAttribute("role", "separator");
			handle.setAttribute("aria-orientation", "vertical");
			handle.setAttribute("aria-label", get_text("Resize {0}", [fieldname]));
			handle.tabIndex = 0;
			handle.title = get_text("Drag to resize; double-click to reset");

			handle.addEventListener("pointerdown", (event) => {
				this.begin_resize(event, context, fieldname, header_column, handle, limits);
			});
			handle.addEventListener("dblclick", (event) => {
				event.preventDefault();
				event.stopPropagation();
				const default_width = this.get_default_width(context.form_grid, fieldname, header_column);
				const reset_width = this.clamp_width(default_width, limits);
				this.apply_width(context.form_grid, fieldname, reset_width);
				this.update_handle(handle, reset_width, limits);
				this.save_width(context, fieldname, null);
			});
			handle.addEventListener("click", (event) => event.stopPropagation());
			handle.addEventListener("keydown", (event) => {
				const current_width = header_column.getBoundingClientRect().width;
				let next_width = null;
				if (event.key === "ArrowLeft") next_width = current_width - 10;
				if (event.key === "ArrowRight") next_width = current_width + 10;
				if (event.key === "Home") next_width = limits.min;
				if (event.key === "End") next_width = limits.max;
				if (next_width === null) return;

				event.preventDefault();
				event.stopPropagation();
				next_width = this.clamp_width(next_width, limits);
				this.apply_width(context.form_grid, fieldname, next_width);
				this.update_handle(handle, next_width, limits);
				this.save_width(context, fieldname, next_width);
			});

			this.update_handle(handle, width, limits);
			header_column.appendChild(handle);
		}

		begin_resize(event, context, fieldname, header_column, handle, limits) {
			if (event.button !== undefined && event.button !== 0) return;
			event.preventDefault();
			event.stopPropagation();

			this.finish_resize(false);
			this.active_resize = {
				context,
				fieldname,
				header_column,
				handle,
				limits,
				start_x: event.clientX,
				start_width: header_column.getBoundingClientRect().width,
				width: header_column.getBoundingClientRect().width,
			};

			handle.classList.add("is-resizing");
			document.body.classList.add("custom-filters-grid-column-resizing");
			window.addEventListener("pointermove", this.handle_pointer_move, true);
			window.addEventListener("pointerup", this.handle_pointer_up, true);
			window.addEventListener("pointercancel", this.handle_pointer_up, true);
		}

		handle_pointer_move(event) {
			if (!this.active_resize) return;
			event.preventDefault();
			const state = this.active_resize;
			state.width = this.clamp_width(
				state.start_width + event.clientX - state.start_x,
				state.limits
			);
			this.apply_width(state.context.form_grid, state.fieldname, state.width);
			this.update_handle(state.handle, state.width, state.limits);
			this.update_grid_scrollbar(state.context.form_grid);
		}

		handle_pointer_up(event) {
			if (!this.active_resize) return;
			if (event) event.preventDefault();
			const state = this.active_resize;
			this.finish_resize(true);
			this.save_width(state.context, state.fieldname, state.width);
		}

		finish_resize(clear_state) {
			if (!this.active_resize) return;
			this.active_resize.handle.classList.remove("is-resizing");
			document.body.classList.remove("custom-filters-grid-column-resizing");
			window.removeEventListener("pointermove", this.handle_pointer_move, true);
			window.removeEventListener("pointerup", this.handle_pointer_up, true);
			window.removeEventListener("pointercancel", this.handle_pointer_up, true);
			if (clear_state) this.active_resize = null;
		}

		enhance_grid(form_grid) {
			const header_row = this.get_header_row(form_grid);
			if (!header_row) return;

			const header_columns = this.get_header_columns(header_row);
			if (!header_columns.length) return;

			const context = this.get_context(form_grid);
			const fieldnames = header_columns.map((column) => column.dataset.fieldname);
			this.prepare_search_columns(form_grid, fieldnames);

			header_columns.forEach((header_column) => {
				const fieldname = header_column.dataset.fieldname;
				const limits = this.get_width_limits(header_column);
				const default_width = this.get_default_width(form_grid, fieldname, header_column);
				const saved_width = this.get_saved_width(context, fieldname);
				const width = this.clamp_width(saved_width || default_width, limits);

				this.apply_width(form_grid, fieldname, width);
				const handle = header_column.querySelector(`.${RESIZE_HANDLE_CLASS}`);
					if (handle) {
						this.update_handle(handle, width, limits);
					} else {
						this.create_resize_handle(header_column, context, fieldname, limits, width);
					}
			});
			this.ensure_top_scrollbar(form_grid);
		}
	}

	function boot() {
		if (!window.frappe || !frappe.ui || !frappe.model) {
			window.setTimeout(boot, 100);
			return;
		}
		if (window.CustomFiltersGridColumnResize) return;
		window.CustomFiltersGridColumnResize = new GridColumnResizeController();
		window.CustomFiltersGridColumnResize.start();
	}

	window.__custom_filters_grid_column_resize_version = VERSION;
	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", boot, { once: true });
	} else {
		boot();
	}
})();
