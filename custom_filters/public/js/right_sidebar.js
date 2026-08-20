(function () {
	if (window.__custom_filters_right_sidebar_loaded) return;
	window.__custom_filters_right_sidebar_loaded = true;

	const RIGHT_SIDEBAR_VERSION = "2026.08.07.3";
	const BAR_ID = "custom-filters-right-sidebar";
	const FLYOUT_ID = "custom-filters-right-sidebar-flyout";
	const FLYOUT_CLOSE_DELAY = 200;

	function translate(text, args) {
		if (typeof __ === "function") return __(text, args);
		return text;
	}

	function normalize_path(path) {
		return String(path || "")
			.split("?")[0]
			.split("/")
			.map(function (part) {
				return decodeURIComponent(String(part || "").trim());
			})
			.filter(Boolean)
			.join("/")
			.toLowerCase();
	}

	class RightSidebarController {
		constructor() {
			this.container = null;
			this.bar = null;
			this.flyout = null;
			this.items = [];
			this.children_by_label = {};
			this.route_cache = new Map();
			this.active_label = null;
			this.flyout_folder = null;
			this.flyout_trigger = null;
			this.close_timer = null;
			this.route_frame = null;
			this.bound = false;
		}

		init() {
			if (this.bound) return;
			this.bound = true;
			this.prepare_icons();
			if (!this.items.length) return;

			this.container = this.build_container();
			document.body.appendChild(this.container);
			this.flyout = this.build_flyout();
			document.body.appendChild(this.flyout);
			this.bind_events();
			this.bind_route();
			this.update_visibility();
			this.update_active();
			console.info(`[custom_filters right_sidebar] version ${RIGHT_SIDEBAR_VERSION}`);
		}

		prepare_icons() {
			const icons = (frappe.boot.desktop_icons || []).filter(function (icon) {
				return icon && icon.hidden != 1;
			});
			const by_parent = {};
			icons.forEach(function (icon) {
				if (icon.parent_icon) {
					(by_parent[icon.parent_icon] = by_parent[icon.parent_icon] || []).push(icon);
				}
			});
			this.children_by_label = by_parent;
			this.items = icons.filter(function (icon) {
				return !icon.parent_icon;
			});
		}

		is_folder(icon) {
			// 显式 Folder，或带子图标的 App 类图标（如 DLP Framework）——桌面首页同样按文件夹展开
			return (
				icon.icon_type === "Folder" ||
				(this.children_by_label[icon.label] || []).length > 0
			);
		}

		build_container() {
			const container = document.createElement("div");
			container.className = "custom-filters-right-sidebar-container";

			const bar = document.createElement("div");
			bar.id = BAR_ID;
			bar.className = "custom-filters-right-sidebar";
			bar.setAttribute("role", "navigation");
			bar.setAttribute("aria-label", translate("Desktop icons"));

			const items = document.createElement("div");
			items.className = "custom-filters-right-sidebar-items";
			this.items.forEach((icon) => items.appendChild(this.make_item(icon)));
			bar.appendChild(items);

			container.appendChild(bar);
			this.bar = bar;
			return container;
		}

		build_flyout() {
			const flyout = document.createElement("div");
			flyout.id = FLYOUT_ID;
			flyout.className = "custom-filters-right-sidebar-flyout";
			flyout.setAttribute("role", "menu");
			return flyout;
		}

		make_item(icon) {
			const is_folder = this.is_folder(icon);
			const item = document.createElement("button");
			item.type = "button";
			item.className = "custom-filters-right-sidebar-item";
			item.dataset.iconLabel = icon.label;
			item.setAttribute("aria-label", translate(icon.label || ""));

			const visual = document.createElement("span");
			visual.className = "custom-filters-right-sidebar-item-icon";
			visual.setAttribute("aria-hidden", "true");
			visual.innerHTML = this.icon_visual(icon);
			item.appendChild(visual);

			const label = document.createElement("span");
			label.className = "custom-filters-right-sidebar-item-label";
			label.textContent = translate(icon.label || "");
			item.appendChild(label);

			item.title = translate(icon.label || "");
			item.setAttribute("data-toggle", "tooltip");
			item.setAttribute("data-placement", "left");

			item.addEventListener("click", () => {
				item.blur();
				if (is_folder) {
					const is_open = this.flyout_folder === icon.label && this.flyout.classList.contains("show");
					if (is_open) {
						this.close_flyout();
					} else {
						this.cancel_close();
						this.open_flyout(icon, item);
					}
					return;
				}
				if (this.flyout_folder) this.close_flyout();
				this.navigate_icon(icon);
			});

			if (is_folder) {
				item.setAttribute("aria-haspopup", "menu");
				item.setAttribute("aria-expanded", "false");
				item.addEventListener("mouseenter", () => {
					this.cancel_close();
					this.open_flyout(icon, item);
				});
				item.addEventListener("mouseleave", () => this.schedule_close());
			}

			return item;
		}

		make_flyout_item(icon) {
			const item = document.createElement("button");
			item.type = "button";
			item.className = "custom-filters-right-sidebar-flyout-item";
			item.dataset.iconLabel = icon.label;
			item.setAttribute("role", "menuitem");
			item.title = translate(icon.label || "");

			const visual = document.createElement("span");
			visual.setAttribute("aria-hidden", "true");
			visual.style.display = "inline-flex";
			visual.innerHTML = this.icon_visual(icon);
			item.appendChild(visual);

			const title = document.createElement("span");
			title.className = "custom-filters-right-sidebar-flyout-title";
			title.textContent = translate(icon.label || "");
			item.appendChild(title);

			item.addEventListener("click", () => {
				this.close_flyout();
				this.navigate_icon(icon);
			});
			return item;
		}

		icon_visual(icon) {
			if (icon.icon_type === "Folder") {
				return frappe.utils.icon("folder-normal", "md");
			}

			const themed = frappe.utils.get_desktop_icon
				? frappe.utils.get_desktop_icon(icon.label, frappe.boot.desktop_icon_style || "Subtle")
				: false;
			if (themed) {
				return `<img class="custom-filters-right-sidebar-icon-img" src="${themed}" alt="" />`;
			}

			if (icon.logo_url || icon.icon_image) {
				return `<img class="custom-filters-right-sidebar-icon-img" src="${icon.logo_url || icon.icon_image}" alt="" />`;
			}

			return frappe.utils.desktop_icon(icon.label || "?", icon.bg_color || "gray", "sm");
		}

		resolve_route(icon) {
			if (this.route_cache.has(icon.label)) return this.route_cache.get(icon.label);
			let route = null;
			try {
				route = frappe.utils.get_route_for_icon(icon) || null;
			} catch (error) {
				route = null;
			}
			if (typeof route !== "string" || !route) route = null;
			this.route_cache.set(icon.label, route);
			return route;
		}

		navigate_icon(icon) {
			const route = this.resolve_route(icon);
			if (!route) return;
			if (/^https?:\/\//i.test(route)) {
				window.open(route, "_blank", "noopener");
				return;
			}
			// Workspace Sidebar icons jump straight to the sidebar's first link
			// (e.g. Balance Sheet) and bypass the workspace page, so core's sidebar
			// resolver keeps the previous workspace. Hand the target sidebar to core
			// via route_options (consumed by frappe.app.sidebar on route change).
			const sidebar = frappe.boot.workspace_sidebar_item[(icon.label || "").toLowerCase()];
			if (icon.link_type === "Workspace Sidebar" && sidebar) {
				frappe.route_options = Object.assign({}, frappe.route_options, { sidebar: icon.label });
			}
			frappe.set_route(route.replace(/^\/+/, ""));
		}

		open_flyout(folder_icon, trigger) {
			const children = this.children_by_label[folder_icon.label] || [];
			if (!children.length) return;

			if (this.flyout_trigger && this.flyout_trigger !== trigger) {
				this.flyout_trigger.setAttribute("aria-expanded", "false");
			}
			this.flyout_folder = folder_icon.label;
			this.flyout_trigger = trigger;
			trigger.setAttribute("aria-expanded", "true");

			this.flyout.replaceChildren();
			children.forEach((child) => this.flyout.appendChild(this.make_flyout_item(child)));

			this.flyout.classList.add("show");
			const rect = trigger.getBoundingClientRect();
			const top = Math.max(8, Math.min(rect.top, window.innerHeight - this.flyout.offsetHeight - 8));
			Object.assign(this.flyout.style, {
				left: `${rect.right + 6}px`,
				right: "auto",
				top: `${top}px`,
			});
		}

		close_flyout(restore_focus) {
			if (!this.flyout) return;
			this.flyout.classList.remove("show");
			if (this.flyout_trigger) this.flyout_trigger.setAttribute("aria-expanded", "false");
			if (restore_focus && this.flyout_trigger && document.contains(this.flyout_trigger)) {
				this.flyout_trigger.focus();
			}
			this.flyout_folder = null;
			this.flyout_trigger = null;
		}

		schedule_close() {
			this.cancel_close();
			this.close_timer = window.setTimeout(() => this.close_flyout(), FLYOUT_CLOSE_DELAY);
		}

		cancel_close() {
			if (this.close_timer) window.clearTimeout(this.close_timer);
			this.close_timer = null;
		}

		setup_tooltips() {
			if (!window.$ || !$.fn || !$.fn.tooltip || !this.container) return;
			const $items = $(this.container).find('[data-toggle="tooltip"]');
			$items.tooltip({ boundary: "window", container: "body", trigger: "hover" });
		}

		bind_events() {
			this.flyout.addEventListener("mouseenter", () => this.cancel_close());
			this.flyout.addEventListener("mouseleave", () => this.schedule_close());

			this.flyout.addEventListener("keydown", (event) => {
				if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
				const items = [...this.flyout.querySelectorAll('[role="menuitem"]')];
				if (!items.length) return;
				event.preventDefault();
				const current_index = Math.max(0, items.indexOf(document.activeElement));
				let target_index = current_index;
				if (event.key === "ArrowUp") target_index = (current_index - 1 + items.length) % items.length;
				if (event.key === "ArrowDown") target_index = (current_index + 1) % items.length;
				if (event.key === "Home") target_index = 0;
				if (event.key === "End") target_index = items.length - 1;
				items[target_index].focus();
			});

			document.addEventListener("keydown", (event) => {
				if (event.key !== "Escape") return;
				if (!this.flyout.classList.contains("show")) return;
				event.preventDefault();
				this.close_flyout(true);
			});

			document.addEventListener("click", (event) => {
				if (!this.flyout.classList.contains("show")) return;
				if (this.flyout.contains(event.target)) return;
				if (event.target.closest(".custom-filters-right-sidebar-item")) return;
				this.close_flyout();
			});

			window.addEventListener(
				"scroll",
				(event) => {
					if (this.flyout.contains(event.target)) return;
					this.close_flyout();
				},
				true
			);
			window.addEventListener("resize", () => this.close_flyout());
		}

		bind_route() {
			frappe.router.on("change", () => {
				if (this.route_frame) return;
				this.route_frame = window.requestAnimationFrame(() => {
					this.route_frame = null;
					this.update_visibility();
					this.update_active();
				});
			});

			// 与左侧边栏同一触发源：页面渲染完成后同步显隐（desktop.js 设置 hide_sidebar）
			$(document).on("page-change", () => {
				this.update_visibility();
				this.update_active();
				window.setTimeout(() => this.update_active(), 100);
				window.setTimeout(() => this.update_active(), 300);
			});
		}

		update_visibility() {
			if (!this.container) return;
			const page = frappe.container && frappe.container.page && frappe.container.page.page;
			const hidden = !!(page && page.hide_sidebar);
			this.container.classList.toggle("is-hidden", hidden);
			if (hidden) {
				this.close_flyout();
				if (window.$ && $.fn && $.fn.tooltip) {
					$(this.container).find('[data-toggle="tooltip"]').tooltip("dispose");
				}
			} else {
				this.setup_tooltips();
			}
		}

		update_active() {
			if (!this.container) return;

			const sidebar = frappe.app && frappe.app.sidebar;
			const sidebar_titles = new Set(
				[
					sidebar && sidebar.sidebar_title,
					sidebar && sidebar.workspace_title,
					sidebar && sidebar.header_title,
					sidebar && sidebar.app,
					sidebar && sidebar.module,
				]
					.filter(Boolean)
					.map((title) => normalize_path(title))
			);

			let active_label = null;
			const icon_matches_sidebar = (icon) => {
				const labels = [
					icon.label,
					translate(icon.label || ""),
					icon.app,
					icon.module,
					icon.label === "Accounting" ? "Accounts" : null,
				]
					.filter(Boolean)
					.map((label) => normalize_path(label));
				return labels.some((label) => sidebar_titles.has(label));
			};

			this.items.some((icon) => {
				const related_icons = [icon, ...(this.children_by_label[icon.label] || [])];
				if (related_icons.some(icon_matches_sidebar)) {
					active_label = icon.label;
					return true;
				}
				return false;
			});

			const candidates = new Set();
		const current_route = frappe.get_route ? frappe.get_route() : [];
		const route_key = normalize_path((current_route || []).join("/"));
			const path_key = normalize_path(window.location.pathname);
			if (route_key) candidates.add(route_key);
			if (path_key) candidates.add(path_key);

			this.items.forEach((icon) => {
				if (active_label) return;
				const related_icons = [icon, ...(this.children_by_label[icon.label] || [])];
				if (
					related_icons.some((related_icon) => {
						const route = this.resolve_route(related_icon);
						return (
							route &&
							!/^https?:\/\//i.test(route) &&
							candidates.has(normalize_path(route))
						);
					})
				) {
					active_label = icon.label;
				}
			});

			if (active_label === this.active_label) return;
			this.active_label = active_label;
			this.container
				.querySelectorAll(".custom-filters-right-sidebar-item")
				.forEach((el) => {
					const is_active = el.dataset.iconLabel === active_label;
					el.classList.toggle("active", is_active);
					if (is_active) {
						el.setAttribute("aria-current", "page");
					} else {
						el.removeAttribute("aria-current");
					}
				});
		}
	}

	function boot() {
		if (
			!window.frappe ||
			!frappe.router ||
			!frappe.session ||
			!frappe.utils ||
			!frappe.boot ||
			!frappe.boot.desktop_icons
		) {
			window.setTimeout(boot, 100);
			return;
		}

		if (window.CustomFiltersRightSidebar) return;
		window.CustomFiltersRightSidebar = new RightSidebarController();
		window.CustomFiltersRightSidebar.init();
	}

	window.__custom_filters_right_sidebar_version = RIGHT_SIDEBAR_VERSION;

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", boot, { once: true });
	} else {
		boot();
	}
})();
