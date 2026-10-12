from __future__ import annotations

import unittest

from phone_watch.ui import render_app_html


class BreadcrumbNavigationTests(unittest.TestCase):
    def test_top_page_switcher_uses_hover_management_menu(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn('class="breadcrumb-nav"', html)
        self.assertIn("aria-label=", html)
        self.assertNotIn('<div class="tabs">', html)

        expected_order = [
            'data-page="candidates"',
            'data-page="phones"',
            'data-page="new-today"',
            'data-page="today"',
            'id="manage-menu-toggle"',
            'id="manage-menu" class="manage-menu hidden"',
            'class="manage-menu-item" data-action="tipo"',
            'data-page="rules"',
            'data-page="fields"',
            'data-page="news"',
            'id="open-manual-model-nav"',
            'id="open-trash"',
        ]
        positions = [html.index(marker) for marker in expected_order]
        self.assertEqual(positions, sorted(positions))

        self.assertNotIn('class="manage-menu-item" data-action="manual-model"', html)
        self.assertIn('class="manage-menu-item" data-action="tipo"', html)
        self.assertIn('class="manage-menu-item tab" data-page="rules"', html)
        self.assertIn('class="manage-menu-item tab" data-page="fields"', html)
        self.assertIn(".nav-menu:hover .manage-menu", html)
        self.assertIn(".nav-menu:focus-within .manage-menu", html)
        self.assertNotIn("overflow-y: auto", html)
        self.assertNotIn(".manage-menu { max-height:", html)
        self.assertIn('id="open-manual-model-nav" class="secondary" type="button"', html)
        self.assertLess(html.index('id="open-manual-model-nav"'), html.index('id="open-trash"'))
        self.assertIn('$("#open-manual-model-nav").addEventListener("click", openManualModel);', html)
        self.assertNotIn('id="open-manual-model" class="secondary"', html)

    def test_news_page_renders_it_home_news_sections_without_official_news(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn('data-page="news"', html)
        self.assertIn('id="news-panel"', html)
        self.assertIn('id="news-category-filter"', html)
        self.assertIn('id="news-category"', html)
        self.assertIn('<option value="HUAWEI">HUAWEI</option>', html)
        self.assertIn("function newsQuery()", html)
        self.assertIn('source_type: "ithome_brand_search"', html)
        self.assertIn('source_type: "ithome_phone_today"', html)
        self.assertNotIn('data-news-section="official"', html)
        self.assertNotIn('id="news-official"', html)
        self.assertIn('data-news-section="ithome_brand_search"', html)
        self.assertIn('data-news-section="ithome_phone_today"', html)
        self.assertIn("crawl_failed", html)

    def test_frontend_uses_page_scoped_loading_for_filter_changes(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn("async function loadCurrentListOnly()", html)
        self.assertIn("async function loadNewsOnly()", html)
        self.assertIn('event.target.matches("#news-category")', html)
        self.assertIn("loadNewsOnly().catch(console.error)", html)
        self.assertIn("loadCurrentListOnly().catch(console.error)", html)
        self.assertNotIn(
            'event.target.matches("#country, #brand, #news-category, #status',
            html,
        )

    def test_frontend_switch_page_reuses_loaded_page_state(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn("function pageHasData(page)", html)
        self.assertIn("if (pageHasData(page))", html)
        self.assertIn("applyFilters();", html)
        self.assertIn('if (page === "news")', html)

    def test_config_pages_hide_global_model_controls_but_keep_local_editors(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn('id="global-toolbar" class="toolbar list-control-row"', html)
        self.assertIn('id="global-batchbar" class="selection-toolbar compact"', html)
        self.assertIn('id="tipo-admin-panel" class="admin-panel hidden"', html)
        self.assertIn('const configMode = table === "rules" || table === "fields" || table === "tipo";', html)
        self.assertIn('const listMode = !newsMode && !configMode;', html)
        self.assertIn('$("#global-toolbar")?.classList.toggle("hidden", configMode);', html)
        self.assertIn('$("#global-batchbar")?.classList.toggle("hidden", !listMode);', html)
        self.assertIn('tipoPanel.classList.toggle("hidden", table !== "tipo");', html)
        self.assertNotIn('$("#global-tipo-panel")?.classList.toggle("collapsed");', html)
        self.assertNotIn('document.querySelector(".batchbar")', html)
        self.assertNotIn('document.querySelector(".tipo-panel")', html)

        self.assertIn('id="rules-panel"', html)
        self.assertIn('id="rule-brand"', html)
        self.assertIn('id="rule-series"', html)
        self.assertIn('id="fields-panel"', html)
        self.assertIn('id="field-name"', html)
        self.assertIn('id="field-value"', html)

    def test_list_pages_use_compact_filter_row_search_button_and_selection_actions(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn('id="global-toolbar" class="toolbar list-control-row"', html)
        self.assertIn('id="toggle-advanced-filter" class="quick-filter" type="button"', html)
        self.assertLess(html.index('id="export-current"'), html.index('id="model-query"'))
        self.assertIn('class="search-slot toolbar-search"', html)
        self.assertIn('class="search-control"', html)
        self.assertNotIn('class="search-slot toolbar-search">型号搜索', html)
        self.assertIn('aria-label="型号搜索"', html)
        self.assertIn('model_query: $("#model-query").value.trim()', html)
        self.assertIn('id="model-search-apply" class="secondary" type="button"', html)
        self.assertIn("function applyModelSearch()", html)
        self.assertIn('$("#model-search-apply").addEventListener("click", applyModelSearch);', html)
        self.assertIn('event.key === "Enter"', html)
        self.assertNotIn('event.target.matches("#model-query, #price-min, #price-max")', html)
        self.assertIn('id="advanced-filter-panel" class="advanced-filter-panel hidden"', html)
        self.assertIn('class="advanced-filter-actions"', html)
        self.assertIn('id="refresh" type="button"', html)
        self.assertIn('id="reset" class="secondary" type="button"', html)
        self.assertIn('id="global-batchbar" class="selection-toolbar compact"', html)
        self.assertIn("function updateSelectionToolbar()", html)
        self.assertIn('selectButton.textContent = hasSelection ? "取消全选" : "全选";', html)
        self.assertIn('$("#advanced-filter-panel")?.classList.toggle("hidden", configMode || newsMode || !state.advancedFilterOpen);', html)
        self.assertNotIn('id="sort-comprehensive"', html)
        self.assertNotIn('id="sort-sales"', html)
        self.assertNotIn('id="sort-price"', html)
        self.assertNotIn('id="toggle-price-range"', html)
        self.assertNotIn('$("#sort-price").addEventListener', html)
        self.assertNotIn('$("#sort-comprehensive").addEventListener', html)
        self.assertNotIn('$("#toggle-price-range").addEventListener', html)

    def test_batch_primary_actions_are_inline_with_page_title_and_hidden_until_selected(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn('class="list-title-row"', html)
        self.assertIn('id="page-title"', html)
        self.assertIn('id="title-primary-actions" class="title-primary-actions"', html)
        self.assertLess(html.index('id="page-title"'), html.index('id="title-primary-actions"'))
        self.assertLess(html.index('id="title-primary-actions"'), html.index('id="global-batchbar"'))

        self.assertIn('id="select-visible" class="secondary" type="button"', html)
        self.assertIn('id="bulk-dingtalk-apply" class="hidden" type="button"', html)
        self.assertIn('id="bulk-delete" class="danger hidden" type="button"', html)
        self.assertIn('id="selected-count" class="note hidden"', html)
        self.assertIn('id="export-selected" class="secondary hidden"', html)
        self.assertIn('id="bulk-status" class="hidden"', html)
        self.assertIn('id="bulk-apply" class="hidden"', html)
        self.assertNotIn('id="clear-selected"', html)
        self.assertNotIn('id="selection-actions"', html)

        self.assertNotIn('id="bulk-badge"', html)
        self.assertNotIn('id="bulk-sale"', html)
        self.assertNotIn('id="bulk-label-apply"', html)
        self.assertNotIn('$("#bulk-label-apply").addEventListener', html)
        self.assertNotIn('refreshSelect("#bulk-badge"', html)
        self.assertNotIn('refreshSelect("#bulk-sale"', html)

        self.assertIn('$("#title-primary-actions")?.classList.toggle("hidden", !listMode);', html)

    def test_row_tipo_selection_uses_global_picker_modal(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn('id="tipo-picker-modal" class="modal-backdrop hidden"', html)
        self.assertIn('id="tipo-picker-options"', html)
        self.assertIn("function openTipoPicker(table, id)", html)
        self.assertIn("function confirmTipoPicker()", html)
        self.assertIn('class="small-button open-row-tipo"', html)
        self.assertIn('event.target.matches(".open-row-tipo")', html)
        self.assertNotIn('class="tipo-menu hidden"', html)
        self.assertNotIn('class="row-tipo-check"', html)
        self.assertNotIn('event.target.matches(".toggle-row-tipo")', html)
        self.assertNotIn('event.target.matches(".confirm-row-tipo")', html)

    def test_tipo_picker_marks_done_tipos_and_skips_duplicate_submit(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn("function rowTipoRecords(row)", html)
        self.assertIn("function tipoRecordMap(row)", html)
        self.assertIn("function tipoStatusBadge(record)", html)
        self.assertIn("function mergeTipoSelections(localValues, records)", html)
        self.assertIn('const TIPO_STATUS_DONE = "已开模"', html)
        self.assertIn("tipo-status-badge done", html)
        self.assertIn("tipo-option-locked", html)
        self.assertIn("该 Tipo 已标记为已开模", html)
        self.assertIn("已开模的 Tipo 无需重复提交", html)
        self.assertIn("await loadCurrentListOnly();", html)

    def test_recycle_bin_ui_elements_and_scripts_are_rendered(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn('id="open-trash" class="icon-button secondary" type="button"', html)
        self.assertIn('id="trash-modal" class="modal-backdrop hidden"', html)
        self.assertIn('id="trash-list" class="trash-list"', html)
        self.assertIn('id="trash-cleanup" class="secondary" type="button"', html)
        self.assertIn("async function trashSelectedModels()", html)
        self.assertIn('postJson("/api/models/trash"', html)
        self.assertIn("async function openTrash()", html)
        self.assertIn("async function restoreTrashItem(table, id)", html)
        self.assertIn("async function purgeTrashItem(table, id)", html)

    def test_enterprise_blue_theme_tokens_present(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn("--bg: #f5f7fa", html)
        self.assertIn("--panel: #ffffff", html)
        self.assertIn("--ink: #1f2d3d", html)
        self.assertIn("--muted: #7a869a", html)
        self.assertIn("--line: #e5eaf0", html)
        self.assertIn("--accent: #1677ff", html)
        self.assertIn("--accent-hover: #2f7df6", html)
        self.assertIn("--accent-soft: #eaf2ff", html)
        self.assertIn("--accent-softer: #eef5ff", html)
        self.assertIn("--focus-ring: 0 0 0 3px rgba(22, 119, 255, .14)", html)
        self.assertNotIn("--accent: #0f8b6f", html)

    def test_visual_theme_keeps_navigation_and_action_structure(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn(".breadcrumb-item::after", html)
        self.assertIn('content: "/"', html)
        self.assertIn(".breadcrumb-item.active::before", html)
        self.assertIn('id="manage-menu-toggle"', html)
        self.assertIn('id="manage-menu" class="manage-menu hidden"', html)
        self.assertIn('id="open-manual-model-nav"', html)
        self.assertIn('id="open-trash"', html)
        self.assertLess(html.index('id="open-manual-model-nav"'), html.index('id="open-trash"'))
        self.assertIn(".nav-menu:hover .manage-menu", html)
        self.assertIn(".nav-menu:focus-within .manage-menu", html)


if __name__ == "__main__":
    unittest.main()
