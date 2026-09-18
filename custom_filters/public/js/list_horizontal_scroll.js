(function () {
	if (window.__custom_filters_list_horizontal_scroll_loaded) return;
	window.__custom_filters_list_horizontal_scroll_loaded = true;

	const VERSION = "2026.09.18.1";
	const SCROLLBAR_CLASS = "custom-filters-list-horizontal-scrollbar";

	class ListHorizontalScrollController {
		constructor() {
			this.states = new Set();
			this.scan_scheduled = false;
			this.observer = null;
		}

		start() {
			if (!document.body) {
				window.setTimeout(() => this.start(), 100);
				return;
			}

			this.observer = new MutationObserver(() => this.schedule_scan());
			this.observer.observe(document.body, { childList: true, subtree: true });

			if (window.$) {
				$(document).on("page-change.custom_filters_list_horizontal_scroll", () => {
					this.schedule_scan();
				});
			}

			window.addEventListener("resize", () => this.update_all());
			window.addEventListener("scroll", () => this.update_all(), { passive: true });
			this.schedule_scan();
			console.info(`[custom_filters list_horizontal_scroll] version ${VERSION}`);
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
			const containers = new Set(
				document.querySelectorAll(".list-view .frappe-list .result-container")
			);

			containers.forEach((container) => this.ensure_scrollbar(container));
			this.states.forEach((state) => {
				if (!state.container.isConnected || !containers.has(state.container)) {
					this.destroy_state(state);
				} else {
					this.update_state(state);
				}
			});
		}

		update_all() {
			this.states.forEach((state) => this.update_state(state));
		}

		ensure_scrollbar(container) {
			let state = [...this.states].find((item) => item.container === container);
			if (!state) {
				const scrollbar = document.createElement("div");
				scrollbar.className = SCROLLBAR_CLASS;
				scrollbar.setAttribute("aria-label", __("Horizontal scroll"));
				scrollbar.setAttribute("role", "scrollbar");

				const inner = document.createElement("div");
				inner.className = `${SCROLLBAR_CLASS}-inner`;
				scrollbar.appendChild(inner);
				document.body.appendChild(scrollbar);

				state = { container, scrollbar, inner, syncing: false };
				this.states.add(state);

				scrollbar.addEventListener("scroll", () => {
					if (state.syncing) return;
					state.syncing = true;
					container.scrollLeft = scrollbar.scrollLeft;
					state.syncing = false;
				});
				container.addEventListener("scroll", () => {
					if (state.syncing) return;
					state.syncing = true;
					scrollbar.scrollLeft = container.scrollLeft;
					state.syncing = false;
				});

				if (window.ResizeObserver) {
					state.resize_observer = new ResizeObserver(() => this.update_state(state));
					state.resize_observer.observe(container);
				}
			}

			this.update_state(state);
		}

		update_state(state) {
			if (!state.container.isConnected || !state.scrollbar.isConnected) return;

			const rect = state.container.getBoundingClientRect();
			const scroll_width = Math.max(state.container.scrollWidth, state.container.clientWidth);
			const has_overflow = state.container.scrollWidth > state.container.clientWidth + 1;
			const is_in_view = rect.bottom > 0 && rect.top < window.innerHeight;

			state.inner.style.width = `${scroll_width}px`;
			state.scrollbar.style.left = `${Math.max(0, rect.left)}px`;
			state.scrollbar.style.width = `${Math.max(0, Math.min(rect.width, window.innerWidth - rect.left))}px`;
			state.scrollbar.classList.toggle("is-visible", has_overflow && is_in_view);
			state.scrollbar.setAttribute("aria-valuemax", String(Math.max(0, scroll_width - rect.width)));
			state.scrollbar.setAttribute("aria-valuenow", String(state.container.scrollLeft));

			if (has_overflow && Math.abs(state.scrollbar.scrollLeft - state.container.scrollLeft) > 1) {
				state.scrollbar.scrollLeft = state.container.scrollLeft;
			}
		}

		destroy_state(state) {
			state.resize_observer?.disconnect();
			state.scrollbar.remove();
			this.states.delete(state);
		}
	}

	function boot() {
		if (!window.frappe) {
			window.setTimeout(boot, 100);
			return;
		}
		if (window.CustomFiltersListHorizontalScroll) return;
		window.CustomFiltersListHorizontalScroll = new ListHorizontalScrollController();
		window.CustomFiltersListHorizontalScroll.start();
	}

	window.__custom_filters_list_horizontal_scroll_version = VERSION;
	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", boot, { once: true });
	} else {
		boot();
	}
})();
