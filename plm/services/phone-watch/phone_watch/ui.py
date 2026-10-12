from __future__ import annotations

import json
from typing import Any


def render_app_html(*, api_mode: bool, data: dict[str, Any] | None = None) -> str:
    payload = "null" if data is None else json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__API_MODE__", "true" if api_mode else "false").replace("__DATA__", payload)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>手机上新监控</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --ink: #1f2d3d;
      --muted: #7a869a;
      --line: #e5eaf0;
      --accent: #1677ff;
      --accent-hover: #2f7df6;
      --accent-soft: #eaf2ff;
      --accent-softer: #eef5ff;
      --warn: #faad14;
      --warn-soft: #fff7e6;
      --danger: #ff4d4f;
      --danger-soft: #fff1f0;
      --shadow: 0 8px 24px rgba(31, 45, 61, .06);
      --focus-ring: 0 0 0 3px rgba(22, 119, 255, .14);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      padding: 24px clamp(16px, 4vw, 44px) 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 {
      margin: 0 0 16px;
      font-size: 26px;
      letter-spacing: 0;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
      gap: 10px;
      max-width: 980px;
    }
    .metric {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
      box-shadow: var(--shadow);
    }
    .metric b {
      display: block;
      font-size: 24px;
      line-height: 1.1;
      margin-top: 4px;
      color: var(--ink);
    }
    main { padding: 18px clamp(16px, 4vw, 44px) 42px; }
    .nav-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
      overflow: visible;
    }
    .breadcrumb-nav {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0;
      min-width: 0;
      color: var(--muted);
      font-size: 14px;
    }
    .breadcrumb-item {
      position: relative;
      min-height: 36px;
      border: 0;
      border-radius: 0;
      background: transparent;
      color: var(--ink);
      padding: 0 18px 0 0;
      font-weight: 600;
    }
    .breadcrumb-item::after {
      content: "/";
      position: absolute;
      right: 6px;
      color: var(--line);
      font-weight: 400;
    }
    .breadcrumb-item:last-child::after {
      content: "";
    }
    .breadcrumb-item:hover,
    .breadcrumb-item:focus {
      background: var(--accent-softer);
      color: var(--accent);
    }
    .breadcrumb-item.active {
      color: var(--accent);
      background: var(--accent-soft);
    }
    .breadcrumb-item.active::before {
      content: "";
      position: absolute;
      left: 0;
      right: 18px;
      bottom: 3px;
      height: 2px;
      background: var(--accent);
    }
    .nav-menu {
      position: relative;
      display: inline-flex;
    }
    .nav-menu > .breadcrumb-item::after {
      content: "/";
    }
    .manage-menu {
      position: absolute;
      top: calc(100% + 4px);
      left: 0;
      z-index: 18;
      display: grid;
      min-width: 160px;
      padding: 6px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .manage-menu.hidden {
      display: none;
    }
    .nav-menu:hover .manage-menu,
    .nav-menu:focus-within .manage-menu {
      display: grid;
    }
    .manage-menu-item {
      min-height: 34px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--ink);
      padding: 0 10px;
      text-align: left;
      white-space: nowrap;
    }
    .manage-menu-item:hover,
    .manage-menu-item:focus {
      background: var(--accent-softer);
      color: var(--accent);
    }
    .nav-actions {
      display: flex;
      flex: 0 0 auto;
      align-items: center;
      gap: 8px;
    }
    .icon-button {
      width: 36px;
      padding: 0;
      display: inline-grid;
      place-items: center;
      font-size: 16px;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: end;
      gap: 10px;
      margin-bottom: 14px;
    }
    .list-control-row {
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .quick-filter-group {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      width: 100%;
    }
    .quick-filter {
      min-height: 36px;
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      border: 1px solid var(--line);
      padding: 0 14px;
    }
    .quick-filter.active {
      color: var(--accent);
      border-color: rgba(22, 119, 255, .35);
      background: var(--accent-softer);
    }
    .search-slot {
      min-width: min(320px, 36vw);
    }
    .search-slot input {
      width: 100%;
    }
    .search-control {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .search-control input {
      flex: 1 1 auto;
      min-width: 0;
    }
    .search-control button {
      flex: 0 0 auto;
    }
    .toolbar-search {
      flex: 1 1 320px;
      min-width: min(320px, 42vw);
      max-width: 520px;
    }
    .advanced-filter-panel {
      display: flex;
      flex-wrap: wrap;
      align-items: end;
      gap: 10px;
      margin: -4px 0 14px;
      padding: 10px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .advanced-filter-panel.hidden {
      display: none;
    }
    .advanced-filter-actions {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 8px;
      margin-left: auto;
      min-width: 180px;
    }
    .selection-toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin: 8px 0 18px;
    }
    .selection-toolbar.compact {
      margin-top: 0;
    }
    .list-title-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin: 0 0 10px;
    }
    .list-title-row h2 {
      margin: 0;
    }
    .title-primary-actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
    }
    .selection-actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .selection-actions.hidden {
      display: none;
    }
    .title-primary-actions .note {
      margin-left: 4px;
    }
    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 13px;
    }
    select, button {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
      padding: 0 10px;
      font: inherit;
    }
    button {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      cursor: pointer;
    }
    button:hover {
      background: var(--accent-hover);
      border-color: var(--accent-hover);
    }
    button.secondary {
      background: var(--panel);
      color: var(--ink);
      border-color: var(--line);
    }
    button.secondary:hover {
      background: var(--accent-softer);
      color: var(--accent);
      border-color: rgba(22, 119, 255, .35);
    }
    button.danger {
      background: var(--danger);
      border-color: var(--danger);
    }
    button:disabled {
      cursor: not-allowed;
      opacity: .55;
    }
    .batchbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin: 8px 0 18px;
      padding: 10px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .tipo-panel,
    .admin-panel {
      display: grid;
      gap: 10px;
      margin-bottom: 18px;
      padding: 10px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .tipo-panel.hidden,
    .admin-panel.hidden { display: none; }
    .tipo-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .tipo-list label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 32px;
      padding: 0 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
    }
    .tipo-admin-row {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 8px;
      align-items: center;
    }
    .tipo-admin-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .tipo-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 32px;
      padding: 0 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
    }
    .tipo-options {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 6px;
    }
    .tipo-options label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 30px;
      padding: 0 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
    }
    .tipo-option {
      justify-content: space-between;
    }
    .tipo-option-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .tipo-status-badge {
      margin-left: auto;
      flex: 0 0 auto;
      padding: 2px 6px;
      border-radius: 999px;
      font-size: 12px;
      line-height: 1.4;
      font-weight: 600;
    }
    .tipo-status-badge.done {
      color: #0f766e;
      background: #ccfbf1;
      border: 1px solid #99f6e4;
    }
    .tipo-option-locked {
      background: #f8fafc;
    }
    .tipo-option-locked input {
      cursor: not-allowed;
    }
    .tipo-summary {
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    input {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
      padding: 0 10px;
      font: inherit;
    }
    input:focus,
    select:focus,
    button:focus-visible {
      outline: none;
      border-color: var(--accent);
      box-shadow: var(--focus-ring);
    }
    .note {
      color: var(--muted);
      font-size: 13px;
      margin-left: auto;
    }
    .news-filter-actions {
      display: flex;
      align-items: end;
      gap: 10px;
    }
    .news-filter-actions.hidden {
      display: none;
    }
    .news-status-note {
      color: var(--muted);
      font-size: 13px;
      margin: 0 0 4px;
    }
    h2 {
      margin: 0 0 10px;
      font-size: 18px;
      letter-spacing: 0;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
      gap: 12px;
    }
    .card {
      display: grid;
      grid-template-columns: 24px 88px 1fr;
      gap: 10px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      min-height: 132px;
      box-shadow: var(--shadow);
    }
    .card:hover {
      border-color: rgba(22, 119, 255, .28);
      box-shadow: 0 10px 26px rgba(31, 45, 61, .08);
    }
    .pick {
      display: flex;
      justify-content: center;
      padding-top: 4px;
    }
    .pick input {
      width: 17px;
      height: 17px;
    }
    .thumb {
      width: 88px;
      height: 110px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: #f8fafd;
      object-fit: contain;
    }
    .empty-thumb {
      display: grid;
      place-items: center;
      color: var(--muted);
      font-size: 12px;
    }
    .model {
      font-weight: 700;
      font-size: 16px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 7px 0;
      color: var(--muted);
      font-size: 12px;
    }
    .pill {
      border-radius: 999px;
      padding: 3px 7px;
      background: var(--accent-soft);
      color: var(--accent);
      white-space: nowrap;
    }
    .pill.warn { background: var(--warn-soft); color: #ad6800; }
    .pill.ignore { background: var(--danger-soft); color: var(--danger); }
    .pill.unreleased { background: var(--danger-soft); color: var(--danger); }
    .dates {
      display: grid;
      gap: 3px;
      color: var(--muted);
      font-size: 13px;
      margin: 6px 0 8px;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .row-status {
      min-height: 30px;
      font-size: 13px;
      padding: 0 7px;
    }
    .small-button {
      min-height: 30px;
      padding: 0 9px;
      font-size: 13px;
    }
    a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }
    a:hover { text-decoration: underline; }
    .empty {
      background: var(--panel);
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 22px;
      color: var(--muted);
    }
    .news-stack {
      display: grid;
      gap: 12px;
    }
    .news-section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      box-shadow: var(--shadow);
    }
    .news-section h3 {
      margin: 0 0 10px;
      font-size: 16px;
      letter-spacing: 0;
    }
    .news-list {
      display: grid;
      gap: 10px;
    }
    .news-item {
      padding-top: 10px;
      border-top: 1px solid var(--line);
    }
    .news-item:first-child {
      padding-top: 0;
      border-top: 0;
    }
    .news-title {
      display: inline-block;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .news-error {
      background: var(--danger-soft);
      border: 1px solid rgba(255, 77, 79, .22);
      color: var(--danger);
    }
    .hidden { display: none; }
    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      z-index: 30;
      max-width: min(360px, calc(100vw - 36px));
      padding: 10px 12px;
      border-radius: 8px;
      background: var(--ink);
      color: #fff;
      box-shadow: var(--shadow);
      font-size: 13px;
      line-height: 1.4;
    }
    .toast.success { background: var(--accent); }
    .toast.error { background: var(--danger); }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      display: grid;
      place-items: center;
      padding: 18px;
      background: rgba(31, 45, 61, .28);
      z-index: 20;
    }
    .modal-backdrop.hidden { display: none; }
    .manual-modal {
      width: min(760px, 100%);
      max-height: calc(100vh - 36px);
      overflow: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 16px;
    }
    .tipo-picker-modal {
      width: min(560px, 100%);
    }
    .tipo-picker-model {
      margin: 0 0 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .manual-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .manual-grid label { width: auto; }
    .manual-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 14px;
    }
    .trash-modal {
      width: min(860px, 100%);
    }
    .trash-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
    }
    .trash-list {
      display: grid;
      gap: 8px;
    }
    .trash-row {
      display: grid;
      grid-template-columns: minmax(130px, 1fr) 90px 94px 130px auto;
      gap: 8px;
      align-items: center;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }
    .trash-row .model {
      font-size: 14px;
    }
    .trash-actions {
      display: flex;
      gap: 6px;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
    @media (max-width: 600px) {
      h1 { font-size: 22px; }
      .grid { grid-template-columns: 1fr; }
      .card { grid-template-columns: 22px 74px 1fr; }
      .thumb { width: 74px; height: 96px; }
      label { width: calc(50% - 5px); }
      .manual-grid { grid-template-columns: 1fr; }
      .batchbar button, .batchbar select { flex: 1 1 140px; }
      .list-control-row { align-items: stretch; }
      .quick-filter-group { flex-wrap: wrap; }
      .search-slot { width: 100%; min-width: 100%; }
      .toolbar-search { flex-basis: 100%; max-width: none; }
      .advanced-filter-actions { width: 100%; margin-left: 0; }
      .selection-actions { width: 100%; }
      .list-title-row { align-items: flex-start; flex-direction: column; }
      .title-primary-actions { justify-content: flex-start; width: 100%; }
      .trash-row { grid-template-columns: 1fr; }
      .trash-actions { justify-content: flex-start; }
      .nav-row { align-items: flex-start; }
      .note { margin-left: 0; width: 100%; }
    }
  </style>
</head>
<body>
  <header>
    <h1>手机上新监控</h1>
    <div class="metrics">
      <div class="metric">候选机型<b id="m-candidates">0</b></div>
      <div class="metric">未开模候选<b id="m-unreviewed">0</b></div>
      <div class="metric">部分开模<b id="m-pending">0</b></div>
      <div class="metric">全部机型<b id="m-phones">0</b></div>
    </div>
  </header>
  <main>
    <div class="nav-row">
      <nav class="breadcrumb-nav" aria-label="页面导航">
        <button class="breadcrumb-item tab active" data-page="candidates" type="button">候选机型</button>
        <button class="breadcrumb-item tab" data-page="phones" type="button">全部机型</button>
        <button class="breadcrumb-item tab" data-page="new-today" type="button">&#20170;&#26085;&#19978;&#26032;</button>
        <button class="breadcrumb-item tab" data-page="today" type="button">当日抓取</button>
        <div class="nav-menu">
          <button id="manage-menu-toggle" class="breadcrumb-item" type="button" aria-expanded="false">添加/管理</button>
          <div id="manage-menu" class="manage-menu hidden" role="menu">
            <button class="manage-menu-item" data-action="tipo" type="button">TIPO类型管理</button>
            <button class="manage-menu-item tab" data-page="rules" type="button">系列规则</button>
            <button class="manage-menu-item tab" data-page="fields" type="button">字段管理</button>
          </div>
        </div>
        <button class="breadcrumb-item tab" data-page="news" type="button">新闻板块</button>
      </nav>
      <div class="nav-actions">
        <button id="open-manual-model-nav" class="secondary" type="button">手动添加型号</button>
        <button id="open-trash" class="icon-button secondary" type="button" aria-label="回收站" title="回收站">🗑</button>
      </div>
    </div>
    <div id="global-toolbar" class="toolbar list-control-row">
      <div class="quick-filter-group" aria-label="列表筛选">
        <button id="toggle-advanced-filter" class="quick-filter" type="button">筛选</button>
        <button id="export-current" class="secondary" type="button">导出当前页</button>
        <span class="search-slot toolbar-search">
          <span class="search-control">
            <input id="model-query" type="search" placeholder="输入型号关键词" aria-label="型号搜索">
            <button id="model-search-apply" class="secondary" type="button">搜索</button>
          </span>
        </span>
      </div>
      <div id="news-filter-actions" class="news-filter-actions hidden">
        <label id="news-category-filter">新闻分类
          <select id="news-category">
            <option value="ithome_phone_today">手机分区当日新闻</option>
            <option value="MOTOROLA">MOTOROLA</option>
            <option value="OPPO">OPPO</option>
            <option value="VIVO">VIVO</option>
            <option value="HONOR">HONOR</option>
            <option value="XIAOMI">XIAOMI</option>
            <option value="ZTE">ZTE</option>
            <option value="SAMSUNG">SAMSUNG</option>
            <option value="HUAWEI">HUAWEI</option>
          </select>
        </label>
        <button id="news-refresh" class="secondary" type="button">刷新</button>
      </div>
    </div>
    <div id="advanced-filter-panel" class="advanced-filter-panel hidden">
      <label>国家
        <select id="country">
          <option value="">全部</option>
          <option value="MX">墨西哥 MX</option>
          <option value="CN">中国 CN</option>
          <option value="KR">韩国 KR</option>
          <option value="GLOBAL">全球参考 GLOBAL</option>
        </select>
      </label>
      <label>品牌
        <select id="brand">
          <option value="">全部</option>
          <option>MOTOROLA</option><option>OPPO</option><option>VIVO</option>
          <option>HONOR</option><option>XIAOMI</option><option>ZTE</option><option>SAMSUNG</option>
        </select>
      </label>
      <label>状态
        <select id="status">
          <option value="">全部</option>
          <option value="未开模">未开模</option>
          <option value="部分开模">部分开模</option>
          <option value="已开模">已开模</option>
        </select>
      </label>
      <label>&#26631;&#31614;
        <select id="badge">
          <option value="">全部</option>
          <option value="新品">新品</option>
          <option value="官网当前机型">官网当前机型</option>
          <option value="Walmart MX 在售">Walmart MX 在售</option>
          <option value="新品预告">新品预告</option>
        </select>
      </label>
      <label>货币
        <select id="price-currency">
          <option value="">全部</option>
          <option value="MXN">MXN</option>
          <option value="CNY">CNY</option>
          <option value="KRW">KRW</option>
          <option value="USD">USD</option>
        </select>
      </label>
      <label>最低价
        <input id="price-min" type="number" min="0" step="1" placeholder="不限">
      </label>
      <label>最高价
        <input id="price-max" type="number" min="0" step="1" placeholder="不限">
      </label>
      <label>价格分类
        <select id="price-bucket">
          <option value="all">全部</option>
          <option value="priced">有价格</option>
          <option value="unpriced">无价格/未识别</option>
        </select>
      </label>
      <div class="advanced-filter-actions" aria-label="筛选操作">
        <button id="refresh" type="button">确认</button>
        <button id="reset" class="secondary" type="button">重置</button>
      </div>
    </div>
    <section id="tipo-admin-panel" class="admin-panel hidden">
      <h2>TIPO类型管理</h2>
      <div id="tipo-list" class="tipo-list"></div>
      <div class="tipo-admin-row">
        <input id="tipo-name" placeholder="新增或修改 TIPO类型">
        <button id="tipo-save" type="button">保存</button>
        <button id="tipo-clear" class="secondary" type="button">清空</button>
      </div>
      <div id="tipo-admin-list" class="tipo-admin-list"></div>
    </section>
    <section>
      <div class="list-title-row">
        <h2 id="page-title">墨西哥未上新候选</h2>
        <div id="title-primary-actions" class="title-primary-actions" aria-label="批量操作">
          <button id="select-visible" class="secondary" type="button">全选</button>
          <button id="bulk-dingtalk-apply" class="hidden" type="button">批量送审</button>
          <button id="bulk-delete" class="danger hidden" type="button">删除</button>
          <span id="selected-count" class="note hidden">已选择 0 项</span>
          <button id="export-selected" class="secondary hidden" type="button">导出选中项</button>
          <select id="bulk-status" class="hidden" aria-label="批量状态">
            <option value="未开模">未开模</option>
            <option value="部分开模">部分开模</option>
            <option value="已开模">已开模</option>
          </select>
          <button id="bulk-apply" class="hidden" type="button">批量改开模</button>
        </div>
      </div>
      <div id="global-batchbar" class="selection-toolbar compact">
        <span class="note" id="mode-note"></span>
      </div>
      <div id="rules-panel" class="hidden">
        <div class="batchbar">
          <label>品牌
            <select id="rule-brand">
              <option>OPPO</option><option>VIVO</option><option>XIAOMI</option>
              <option>SAMSUNG</option><option>HONOR</option><option>MOTOROLA</option><option>ZTE</option>
            </select>
          </label>
          <label>自定义系列名
            <input id="rule-series" placeholder="例如 Nova、Ace、Note Air">
          </label>
          <button id="add-rule" type="button">添加系列</button>
          <span class="note">保存后下次采集自动生效</span>
        </div>
        <div id="rules-list" class="grid"></div>
      </div>
      <div id="fields-panel" class="hidden">
        <div class="batchbar">
          <label>字段类型
            <select id="field-name">
              <option value="brand">品牌</option>
              <option value="sampling_status">开模状态</option>
              <option value="badge">展示标签</option>
              <option value="sale_status">销售状态</option>
              <option value="tipo_status">Tipo状态</option>
              <option value="country">国家/地区</option>
              <option value="price_currency">价格货币</option>
              <option value="price_bucket">价格分类</option>
              <option value="manual_model_type">入库类型</option>
            </select>
          </label>
          <label>字段值
            <input id="field-value" placeholder="例如 IPHONE">
          </label>
          <label>显示名称
            <input id="field-label" placeholder="例如 iPhone">
          </label>
          <button id="field-save" type="button">保存字段</button>
          <button id="field-clear" class="secondary" type="button">清空</button>
        </div>
        <div id="field-list" class="grid"></div>
      </div>
      <div id="news-panel" class="hidden">
        <div class="news-stack">
          <div id="news-status"></div>
          <section class="news-section" data-news-section="ithome_brand_search">
            <h3>IT之家品牌搜索</h3>
            <div id="news-ithome-brand" class="news-list"></div>
          </section>
          <section class="news-section" data-news-section="ithome_phone_today">
            <h3>IT之家手机分区当日新闻</h3>
            <div id="news-ithome-phone" class="news-list"></div>
          </section>
        </div>
      </div>
      <div id="list" class="grid"></div>
    </section>
  </main>
  <div id="manual-model-modal" class="modal-backdrop hidden">
    <form id="manual-model-form" class="manual-modal">
      <h2>手动添加手机型号</h2>
      <div class="manual-grid">
        <label>入库类型
          <select name="type">
            <option value="candidates">候选机型</option>
            <option value="phones">全部机型</option>
          </select>
        </label>
        <label>品牌
          <select name="brand" required>
            <option value="">请选择</option>
            <option>MOTOROLA</option><option>OPPO</option><option>VIVO</option>
            <option>HONOR</option><option>XIAOMI</option><option>ZTE</option><option>SAMSUNG</option>
          </select>
        </label>
        <label>型号
          <input name="model" required placeholder="例如 moto g power 5G 2026">
        </label>
        <label>来源国家
          <select name="source_country">
            <option value="CN">中国 CN</option>
            <option value="KR">韩国 KR</option>
            <option value="GLOBAL">全球 GLOBAL</option>
            <option value="MX">墨西哥 MX</option>
          </select>
        </label>
        <label>缺失国家
          <select name="missing_country">
            <option value="MX">墨西哥 MX</option>
          </select>
        </label>
        <label>来源链接
          <input name="source_url" required placeholder="https://...">
        </label>
        <label>来源名称
          <input name="source_name" placeholder="Manual">
        </label>
        <label>图片链接
          <input name="image_url" placeholder="https://...">
        </label>
        <label>价格
          <input name="price" placeholder="例如 $299">
        </label>
        <label>发布日期
          <input name="release_date" placeholder="YYYY-MM-DD">
        </label>
        <label>上市日期
          <input name="launch_date" placeholder="YYYY-MM-DD">
        </label>
        <label>标签
          <select name="badge">
            <option value="">无标签</option>
            <option value="新品">新品</option>
            <option value="新品预告">新品预告</option>
            <option value="官网当前机型">官网当前机型</option>
            <option value="Walmart MX 在售">Walmart MX 在售</option>
          </select>
        </label>
        <label>销售状态
          <select name="sale_status">
            <option value="">自动判断</option>
            <option value="已售">已售</option>
            <option value="未发售">未发售</option>
            <option value="未发布">未发布</option>
            <option value="未上市">未上市</option>
          </select>
        </label>
        <label>开模状态
          <select name="sampling_status">
            <option value="未开模">未开模</option>
            <option value="部分开模">部分开模</option>
            <option value="已开模">已开模</option>
            <option value="忽略">忽略</option>
          </select>
        </label>
        <label>备注原因
          <input name="reason" placeholder="人工添加">
        </label>
      </div>
      <div class="manual-actions">
        <button id="close-manual-model" class="secondary" type="button">取消</button>
        <button type="submit">保存型号</button>
      </div>
    </form>
  </div>
  <div id="trash-modal" class="modal-backdrop hidden">
    <section class="manual-modal trash-modal" role="dialog" aria-modal="true" aria-labelledby="trash-title">
      <h2 id="trash-title">回收站</h2>
      <div class="trash-toolbar">
        <span class="note">删除的型号保留 7 天，过期后彻底删除</span>
        <button id="trash-cleanup" class="secondary" type="button">清理过期</button>
        <button id="close-trash" class="secondary" type="button">关闭</button>
      </div>
      <div id="trash-list" class="trash-list"></div>
    </section>
  </div>
  <div id="tipo-picker-modal" class="modal-backdrop hidden">
    <section class="manual-modal tipo-picker-modal" role="dialog" aria-modal="true" aria-labelledby="tipo-picker-title">
      <h2 id="tipo-picker-title">选择 Tipo</h2>
      <div id="tipo-picker-model" class="tipo-picker-model"></div>
      <div id="tipo-picker-options" class="tipo-options"></div>
      <div class="manual-actions">
        <button id="tipo-picker-cancel" class="secondary" type="button">取消</button>
        <button id="tipo-picker-confirm" type="button">确认</button>
      </div>
    </section>
  </div>
  <div id="toast" class="toast hidden" role="status" aria-live="polite"></div>
  <script id="initial-data" type="application/json">__DATA__</script>
  <script>
    const API_MODE = __API_MODE__;
    const INITIAL_DATA = JSON.parse(document.querySelector("#initial-data").textContent);
    const STORAGE_KEY = "phone_watch_status_overrides_v2";
    const STATUSES = ["未开模", "部分开模", "已开模"];
    const BADGES = ["", "新品", "新品预告", "官网当前机型", "Walmart MX 在售"];
    const SALE_STATUSES = ["", "已售", "未发售", "未发布", "未上市"];
    const FIELD_LABELS = {
      brand: "品牌",
      sampling_status: "开模状态",
      badge: "展示标签",
      sale_status: "销售状态",
      tipo_status: "Tipo状态",
      country: "国家/地区",
      price_currency: "价格货币",
      price_bucket: "价格分类",
      manual_model_type: "入库类型",
    };
    const FIELD_NAMES = Object.keys(FIELD_LABELS);
    const DEFAULT_FIELD_OPTIONS = {
      brand: ["MOTOROLA", "OPPO", "VIVO", "HONOR", "XIAOMI", "ZTE", "SAMSUNG"].map((value, index) => ({ value, label: value, enabled: 1, sort_order: index })),
      sampling_status: STATUSES.map((value, index) => ({ value, label: value, enabled: 1, sort_order: index })),
      badge: BADGES.map((value, index) => ({ value, label: value || "无标签", enabled: 1, sort_order: index })),
      sale_status: SALE_STATUSES.map((value, index) => ({ value, label: value || "自动判断", enabled: 1, sort_order: index })),
      tipo_status: ["待开模", "已开模"].map((value, index) => ({ value, label: value, enabled: 1, sort_order: index })),
      country: [
        { value: "MX", label: "墨西哥 MX", enabled: 1, sort_order: 0 },
        { value: "CN", label: "中国 CN", enabled: 1, sort_order: 1 },
        { value: "KR", label: "韩国 KR", enabled: 1, sort_order: 2 },
        { value: "GLOBAL", label: "全球参考 GLOBAL", enabled: 1, sort_order: 3 },
      ],
      price_currency: ["MXN", "CNY", "KRW", "USD"].map((value, index) => ({ value, label: value, enabled: 1, sort_order: index })),
      price_bucket: [
        { value: "all", label: "全部", enabled: 1, sort_order: 0 },
        { value: "priced", label: "有价格", enabled: 1, sort_order: 1 },
        { value: "unpriced", label: "无价格/未识别", enabled: 1, sort_order: 2 },
      ],
      manual_model_type: [
        { value: "candidates", label: "候选机型", enabled: 1, sort_order: 0 },
        { value: "phones", label: "全部机型", enabled: 1, sort_order: 1 },
      ],
    };
    const $ = (selector) => document.querySelector(selector);
    const state = { page: "candidates", selected: new Set(), editingTipoId: null, editingFieldId: null, rowTipos: {}, tipoPicker: { table: "", id: null, values: [] }, trash: [], staticOptionsLoaded: Boolean(INITIAL_DATA), advancedFilterOpen: false, data: INITIAL_DATA || { summary: {}, phones: [], candidates: [], today: { date: "", phones: [], candidates: [] }, newToday: { date: "", previous_date: "", phones: [], candidates: [] }, rules: [], tipoOptions: [], fieldOptions: { brand: [] }, news: { status: "ok", date: "", fallback_used: false, fallback_limit: 3, items: [] } } };

    function readOverrides() {
      try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); }
      catch { return {}; }
    }

    function writeOverrides(overrides) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides));
    }

    function rowKey(table, id) {
      return `${table}:${id}`;
    }

    function rowStatus(table, row) {
      if (API_MODE) return row.sampling_status || "未开模";
      return readOverrides()[rowKey(table, row.id)] || row.sampling_status || "未开模";
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[char]));
    }

    let toastTimer = null;
    function showToast(message, type = "success") {
      const toast = $("#toast");
      if (!toast) {
        if (type === "error") console.error(message);
        return;
      }
      toast.textContent = message;
      toast.className = `toast ${type || "success"}`;
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        toast.className = "toast hidden";
      }, 2600);
    }

    function qs(params) {
      const query = new URLSearchParams();
      for (const [key, value] of Object.entries(params)) {
        if (value) query.set(key, value);
      }
      return query.toString();
    }

    function exportCurrent() {
      const f = filters();
      if (!API_MODE) {
        downloadRows(visibleRows(), `${state.page}.csv`);
        return;
      }
      if (state.page === "today" || state.page === "new-today") {
        downloadRows(visibleRows(), state.page === "new-today" ? "new_today.csv" : "today_collected.csv");
        return;
      }
      const url = state.page === "candidates"
        ? `/export/candidates.csv?${qs({
            brand: f.brand,
            status: f.status,
            source_country: f.country === "MX" ? "" : f.country,
            price_currency: f.price_currency,
            price_min: f.price_min,
            price_max: f.price_max,
            price_bucket: f.price_bucket
          })}`
        : `/export/phones.csv?${qs(f)}`;
      window.location.href = url;
    }

    function csvHeaders() {
      return ["brand", "country", "source_country", "missing_country", "model", "price", "image_url", "source_name", "release_date", "launch_date", "badge", "sale_status", "source_url", "reason", "sampling_status"];
    }

    function downloadRows(rows, filename) {
      const headers = csvHeaders();
      const csv = [headers.join(",")].concat(rows.map((row) => headers.map((key) => {
        const table = (state.page === "today" || state.page === "new-today") ? (row._table || "phones") : state.page;
        const value = key === "sampling_status" ? rowStatus(table, row) : row[key];
        return `"${String(value ?? "").replace(/"/g, '""')}"`;
      }).join(","))).join("\n");
      const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    }

    function selectedRows() {
      const rows = visibleRows();
      return rows.filter((row) => {
        const table = (state.page === "today" || state.page === "new-today") ? (row._table || "phones") : state.page;
        return state.selected.has(rowKey(table, row.id));
      });
    }

    function filters() {
      return {
        country: $("#country").value,
        brand: $("#brand").value,
        status: $("#status").value,
        badge: $("#badge") ? $("#badge").value : "",
        model_query: $("#model-query").value.trim(),
        price_currency: $("#price-currency").value,
        price_min: $("#price-min").value.trim(),
        price_max: $("#price-max").value.trim(),
        price_bucket: $("#price-bucket").value
      };
    }

    function applyModelSearch() {
      state.selected.clear();
      loadCurrentListOnly().catch(console.error);
    }

    async function getJson(url) {
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }

    async function postJson(url, payload) {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {})
      });
      const result = await res.json();
      if (!res.ok || result.ok === false) throw new Error(result.error || "操作失败");
      return result;
    }

    function newsQuery() {
      const category = $("#news-category")?.value || "ithome_phone_today";
      if (category === "ithome_phone_today") {
        return { source_type: "ithome_phone_today", date: "today" };
      }
      return { brand: category, source_type: "ithome_brand_search", date: "today" };
    }

    function toggleAdvancedFilter(show) {
      const panel = $("#advanced-filter-panel");
      if (!panel) return;
      state.advancedFilterOpen = typeof show === "boolean" ? show : panel.classList.contains("hidden");
      const configMode = state.page === "rules" || state.page === "fields" || state.page === "tipo";
      const newsMode = state.page === "news";
      panel.classList.toggle("hidden", configMode || newsMode || !state.advancedFilterOpen);
    }

    function updateSelectionToolbar() {
      const count = state.selected.size;
      const hasSelection = count > 0;
      const selectButton = $("#select-visible");
      if ($("#selected-count")) $("#selected-count").textContent = `已选择 ${count} 项`;
      if (selectButton) selectButton.textContent = hasSelection ? "取消全选" : "全选";
      [
        "#bulk-dingtalk-apply",
        "#bulk-delete",
        "#selected-count",
        "#export-selected",
        "#bulk-status",
        "#bulk-apply",
      ].forEach((selector) => {
        document.querySelector(selector)?.classList.toggle("hidden", !hasSelection);
      });
    }

    function currentListEndpoint(page, f) {
      if (page === "candidates") {
        return `/api/candidates?${qs({
          brand: f.brand,
          status: f.status,
          source_country: f.country === "MX" ? "" : f.country,
          model_query: f.model_query,
          price_currency: f.price_currency,
          price_min: f.price_min,
          price_max: f.price_max,
          price_bucket: f.price_bucket
        })}`;
      }
      if (page === "phones") return `/api/phones?${qs(f)}`;
      if (page === "today") return `/api/today?${qs(f)}`;
      if (page === "new-today") return `/api/new-today?${qs(f)}`;
      return "";
    }

    async function loadStaticOptionsOnce() {
      if (!API_MODE || state.staticOptionsLoaded) return;
      const fieldNames = FIELD_NAMES.join(",");
      const [rules, tipoOptions, fieldOptions] = await Promise.all([
        getJson("/api/custom-series"),
        getJson("/api/tipo-options"),
        getJson(`/api/field-options?field_names=${encodeURIComponent(fieldNames)}`)
      ]);
      state.data = { ...state.data, rules, tipoOptions, fieldOptions: mergeFieldOptions(fieldOptions) };
      state.staticOptionsLoaded = true;
      refreshManagedSelects();
    }

    async function reloadStaticOptions() {
      state.staticOptionsLoaded = false;
      await loadStaticOptionsOnce();
      applyFilters();
    }

    async function loadNewsOnly() {
      if (!API_MODE) {
        renderNews();
        updateMetrics();
        return;
      }
      const news = await getJson(`/api/news?${qs(newsQuery())}`);
      state.data = { ...state.data, news };
      renderNews();
      updateMetrics();
    }

    async function refreshNews() {
      if (!API_MODE) {
        showToast("静态页面不能刷新新闻，请打开服务版页面", "error");
        return;
      }
      const button = $("#news-refresh");
      const oldText = button?.textContent || "刷新";
      if (button) {
        button.disabled = true;
        button.textContent = "刷新中";
      }
      try {
        const result = await postJson("/api/news/refresh", {});
        const counts = result.counts || {};
        showToast(`新闻采集完成：写入 ${counts.inserted || 0} 条`, "success");
        await loadNewsOnly();
      } catch (error) {
        showToast(`新闻刷新失败：${error.message || error}`, "error");
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = oldText;
        }
      }
    }

    // Filters now reload only the visible page, so brand switches do not wait
    // for unrelated candidates/phones/today/news/config requests.
    async function loadCurrentListOnly() {
      if (!API_MODE) {
        applyFilters();
        return;
      }
      await loadStaticOptionsOnce();
      const page = state.page;
      if (page === "news") {
        await loadNewsOnly();
        return;
      }
      if (page === "rules" || page === "fields") {
        applyFilters();
        return;
      }
      if (page === "tipo") {
        applyFilters();
        return;
      }
      const url = currentListEndpoint(page, filters());
      if (!url) {
        applyFilters();
        return;
      }
      const payload = await getJson(url);
      if (page === "candidates") state.data = { ...state.data, candidates: payload.items || payload };
      if (page === "phones") state.data = { ...state.data, phones: payload.items || payload };
      if (page === "today") state.data = { ...state.data, today: payload };
      if (page === "new-today") state.data = { ...state.data, newToday: payload };
      applyFilters();
    }

    async function reloadAfterRowMutation() {
      await loadCurrentListOnly();
    }

    async function loadData() {
      if (!API_MODE) {
        applyFilters();
        return;
      }
      const f = filters();
      const [summary, candidates, phones, today, newToday, news] = await Promise.all([
        getJson("/api/summary"),
        getJson(`/api/candidates?${qs({
          brand: f.brand,
          status: f.status,
          source_country: f.country === "MX" ? "" : f.country,
          model_query: f.model_query,
          price_currency: f.price_currency,
          price_min: f.price_min,
          price_max: f.price_max,
          price_bucket: f.price_bucket
        })}`),
        getJson(`/api/phones?${qs(f)}`),
        getJson(`/api/today?${qs(f)}`),
        getJson(`/api/new-today?${qs(f)}`),
        state.page === "news"
          ? getJson(`/api/news?${qs(newsQuery())}`)
          : Promise.resolve(state.data.news || { status: "ok", date: "", fallback_used: false, fallback_limit: 3, items: [] })
      ]);
      const fieldNames = FIELD_NAMES.join(",");
      const [rules, tipoOptions, fieldOptions] = await Promise.all([
        getJson("/api/custom-series"),
        getJson("/api/tipo-options"),
        getJson(`/api/field-options?field_names=${encodeURIComponent(fieldNames)}`)
      ]);
      state.data = { summary, candidates, phones, today, newToday, news, rules, tipoOptions, fieldOptions: mergeFieldOptions(fieldOptions) };
      state.staticOptionsLoaded = true;
      refreshManagedSelects();
      applyFilters();
    }

    async function saveStatus(table, ids, status) {
      if (!ids.length) return;
      if (API_MODE) {
        const res = await fetch("/api/status/bulk", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: table, ids, status })
        });
        if (!res.ok) throw new Error(await res.text());
        await reloadAfterRowMutation();
        return;
      }
      const overrides = readOverrides();
      for (const id of ids) overrides[rowKey(table, id)] = status;
      writeOverrides(overrides);
      applyFilters();
    }

    async function saveLabels(table, ids, badge, saleStatus) {
      if (!ids.length) return;
      if (API_MODE) {
        const res = await fetch("/api/labels/bulk", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: table, ids, badge, sale_status: saleStatus })
        });
        if (!res.ok) throw new Error(await res.text());
        await reloadAfterRowMutation();
        return;
      }
      for (const row of visibleRows()) {
        if (!ids.includes(Number(row.id))) continue;
        row.badge = badge || "";
        row.sale_status = saleStatus || row.sale_status;
      }
      applyFilters();
    }

    const TIPO_STATUS_DONE = "已开模";

    function rowTipoRecords(row) {
      return Array.isArray(row?.molding_tipos) ? row.molding_tipos : [];
    }

    function tipoRecordMap(row) {
      return new Map(
        rowTipoRecords(row)
          .filter((record) => record && record.tipo_name)
          .map((record) => [record.tipo_name, record])
      );
    }

    function tipoStatusBadge(record) {
      if (!record) return "";
      if (record.status === TIPO_STATUS_DONE) {
        return `<span class="tipo-status-badge done">已开模</span>`;
      }
      return "";
    }

    function mergeTipoSelections(localValues, records) {
      const merged = new Set(localValues || []);
      for (const record of records) {
        if (record.tipo_name && record.status === TIPO_STATUS_DONE) {
          merged.add(record.tipo_name);
        }
      }
      return [...merged];
    }

    function findRowByKey(table, id) {
      const targetId = Number(id);
      const sources = [
        ...(state.data.phones || []).map((row) => ({ ...row, _table: "phones" })),
        ...(state.data.candidates || []).map((row) => ({ ...row, _table: "candidates" })),
        ...(state.data.today?.phones || []).map((row) => ({ ...row, _table: row._table || "phones" })),
        ...(state.data.today?.candidates || []).map((row) => ({ ...row, _table: row._table || "candidates" })),
        ...(state.data.newToday?.phones || []).map((row) => ({ ...row, _table: row._table || "phones" })),
        ...(state.data.newToday?.candidates || []).map((row) => ({ ...row, _table: row._table || "candidates" })),
      ];
      return sources.find((row) => (row._table || table) === table && Number(row.id) === targetId) || null;
    }

    function selectedTipoValues(table, id) {
      if (!table || id === undefined || id === null) return [];
      const key = rowKey(table, id);
      const row = findRowByKey(table, id);
      const existing = tipoRecordMap(row);
      return (state.rowTipos[key] || []).filter((name) => {
        const record = existing.get(name);
        return record?.status !== TIPO_STATUS_DONE;
      });
    }

    function tipoSelect(table, id) {
      const key = rowKey(table, id);
      const selected = state.rowTipos[key] || [];
      return `
        <span class="tipo-summary" data-key="${escapeHtml(key)}">${escapeHtml(selected.length ? selected.join(", ") : "未选Tipo")}</span>
        <button class="small-button open-row-tipo" data-table="${table}" data-id="${id}" type="button">选择Tipo</button>
      `;
    }

    function openTipoPicker(table, id) {
      const key = rowKey(table, id);
      const row = findRowByKey(table, id);
      const records = rowTipoRecords(row);
      const recordMap = tipoRecordMap(row);
      const selected = mergeTipoSelections(state.rowTipos[key] || [], records);
      const options = (state.data.tipoOptions || []).filter((option) => Number(option.enabled) === 1);
      state.rowTipos[key] = selected;
      state.tipoPicker = { table, id: Number(id), values: [...selected] };
      $("#tipo-picker-model").textContent = row ? [row.brand, row.model || row.normalized_model].filter(Boolean).join(" ") : "";
      $("#tipo-picker-options").innerHTML = options.length ? options.map((option) => {
        const record = recordMap.get(option.name);
        const isDone = record?.status === TIPO_STATUS_DONE;
        const checked = selected.includes(option.name) || isDone;
        const locked = isDone;
        const title = isDone ? "该 Tipo 已标记为已开模" : "";
        return `
          <label class="tipo-option ${locked ? "tipo-option-locked" : ""} ${isDone ? "tipo-option-done" : ""}" title="${escapeHtml(title)}">
            <input
              type="checkbox"
              class="tipo-picker-check"
              value="${escapeHtml(option.name)}"
              ${checked ? "checked" : ""}
              ${locked ? "disabled" : ""}
            >
            <span class="tipo-option-name">${escapeHtml(option.name)}</span>
            ${tipoStatusBadge(record)}
          </label>
        `;
      }).join("") : `<span class="note">暂无可用 Tipo</span>`;
      $("#tipo-picker-modal").classList.remove("hidden");
    }

    function closeTipoPicker() {
      $("#tipo-picker-modal").classList.add("hidden");
      state.tipoPicker = { table: "", id: null, values: [] };
    }

    function confirmTipoPicker() {
      const { table, id } = state.tipoPicker;
      if (!table || id === null) {
        closeTipoPicker();
        return;
      }
      const key = rowKey(table, id);
      const values = [...document.querySelectorAll(".tipo-picker-check:checked")].map((input) => input.value);
      const row = findRowByKey(table, id);
      state.rowTipos[key] = mergeTipoSelections(values, rowTipoRecords(row));
      const summary = document.querySelector(`.tipo-summary[data-key="${CSS.escape(key)}"]`);
      if (summary) summary.textContent = state.rowTipos[key].length ? state.rowTipos[key].join(", ") : "未选Tipo";
      closeTipoPicker();
    }

    function renderTipoOptions() {
      const options = state.data.tipoOptions || [];
      const list = $("#tipo-list");
      const admin = $("#tipo-admin-list");
      if (!options.length) {
        list.innerHTML = `<span class="note">No Tipo options</span>`;
        admin.innerHTML = "";
        return;
      }
      list.innerHTML = `<span class="note">在每个手机型号卡片里的 Tipo 下拉框选择；这里仅管理选项。</span>`;
      admin.innerHTML = options.map((option) => `
        <span class="tipo-chip">
          <span>${escapeHtml(option.name)}</span>
          <button class="small-button edit-tipo" data-id="${option.id}" data-name="${escapeHtml(option.name)}" type="button">修改</button>
          <button class="small-button danger delete-tipo" data-id="${option.id}" type="button">删除</button>
        </span>
      `).join("");
    }

    async function saveTipoOption() {
      const name = $("#tipo-name").value.trim();
      if (!name) {
        alert("Please enter a Tipo value");
        return;
      }
      const res = await fetch("/api/tipo-options", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: state.editingTipoId, name, enabled: true })
      });
      if (!res.ok) throw new Error(await res.text());
      state.editingTipoId = null;
      $("#tipo-name").value = "";
      await reloadStaticOptions();
    }

    async function deleteTipoOption(id) {
      if (!confirm("Delete this Tipo option?")) return;
      const res = await fetch("/api/tipo-options/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id })
      });
      if (!res.ok) throw new Error(await res.text());
      await reloadStaticOptions();
    }

    async function syncDingTalkOne(table, id, button) {
      if (!API_MODE) {
        alert("静态页面不能送审，请打开服务版页面");
        return;
      }
      const tipoValues = selectedTipoValues(table, id);
      if (!tipoValues.length) {
        alert("没有新的 Tipo 需要送审，已开模的 Tipo 无需重复提交");
        return;
      }
      if (!confirm("确认将这个型号送入开模审批表？")) return;
      const oldText = button ? button.textContent : "";
      if (button) {
        button.disabled = true;
        button.textContent = "送审中";
      }
      try {
        const res = await fetch("/api/dingtalk/sync-one", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: table, id, tipo_values: tipoValues })
        });
        const result = await res.json();
        if (!res.ok || !result.ok) throw new Error(result.error || JSON.stringify(result));
        alert(formatDingTalkResult(result));
        await loadCurrentListOnly();
      } catch (error) {
        console.error(error);
        alert(`送审失败：${error.message || error}`);
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = oldText;
        }
      }
    }

    async function syncDingTalkSelected() {
      if (!API_MODE) {
        alert("静态页面不能送审，请打开服务版页面");
        return;
      }
      const table = state.page;
      const items = (table === "today" || table === "new-today")
        ? selectedRows().map((row) => ({ type: row._table || "phones", id: Number(row.id) }))
        : [...state.selected]
          .filter((key) => key.startsWith(`${table}:`))
          .map((key) => ({ type: table, id: Number(key.split(":")[1]) }));
      if (!items.length) {
        alert("请先勾选要送审的型号");
        return;
      }
      const itemsWithNewTipos = items
        .map((item) => ({
          ...item,
          tipo_values: selectedTipoValues(item.type, item.id)
        }))
        .filter((item) => item.tipo_values.length);
      if (!itemsWithNewTipos.length) {
        alert("选中型号没有新的 Tipo 需要送审，已开模的 Tipo 无需重复提交");
        return;
      }
      if (!confirm(`确认送审 ${itemsWithNewTipos.length} 个型号？系统会一个型号创建一张审批表。`)) return;
      const button = $("#bulk-dingtalk-apply");
      const oldText = button.textContent;
      button.disabled = true;
      button.textContent = "送审中";
      try {
        const res = await fetch("/api/dingtalk/sync-selected", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            items: itemsWithNewTipos
          })
        });
        const result = await res.json();
        if (!res.ok) throw new Error(result.error || JSON.stringify(result));
        alert(formatDingTalkResult(result));
        await loadCurrentListOnly();
      } catch (error) {
        console.error(error);
        alert(`批量送审失败：${error.message || error}`);
      } finally {
        button.disabled = false;
        button.textContent = oldText;
      }
    }

    function formatDingTalkResult(result) {
      const rows = result.results || [result];
      const okRows = rows.filter((row) => row.ok);
      const failedRows = rows.filter((row) => !row.ok);
      const lines = [`送审完成：成功 ${result.synced ?? okRows.length}，失败 ${result.failed ?? failedRows.length}`];
      for (const row of rows) {
        const model = row.model || row.source_id || "";
        const tipo = row.tipo ? ` + ${row.tipo}` : "";
        if (row.ok) {
          lines.push(`成功：${model}${tipo}${row.process_instance_id ? `，审批ID：${row.process_instance_id}` : ""}`);
        } else {
          lines.push(`失败：${model}${tipo}，原因：${row.error || "未知错误"}`);
        }
      }
      return lines.join("\n");
    }

    async function addRule() {
      const brand = $("#rule-brand").value;
      const series = $("#rule-series").value.trim();
      if (!series) {
        alert("请填写系列名");
        return;
      }
      const res = await fetch("/api/custom-series", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand, series_name: series, enabled: true })
      });
      if (!res.ok) throw new Error(await res.text());
      $("#rule-series").value = "";
      await reloadStaticOptions();
    }

    async function toggleRule(id, enabled) {
      const res = await fetch("/api/custom-series/enabled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, enabled })
      });
      if (!res.ok) throw new Error(await res.text());
      await reloadStaticOptions();
    }

    function statusPill(status) {
      const cls = status === "部分开模" ? "pill warn" : "pill";
      return `<span class="${cls}">${escapeHtml(status)}</span>`;
    }

    function imgCell(row) {
      if (row.image_url) {
        return `<img class="thumb" src="${escapeHtml(row.image_url)}" alt="${escapeHtml(row.model)}">`;
      }
      return `<div class="thumb empty-thumb">无图</div>`;
    }

    function mergeFieldOptions(options = {}) {
      const merged = {};
      for (const fieldName of FIELD_NAMES) {
        const rows = Array.isArray(options[fieldName]) ? options[fieldName] : [];
        merged[fieldName] = rows.length ? rows : DEFAULT_FIELD_OPTIONS[fieldName];
      }
      return merged;
    }

    function managedOptions(fieldName, enabledOnly = true) {
      const options = state.data.fieldOptions?.[fieldName] || DEFAULT_FIELD_OPTIONS[fieldName] || [];
      return enabledOnly ? options.filter((item) => Number(item.enabled) === 1) : options;
    }

    function managedOptionsHtml(fieldName, current = "", { emptyLabel = "", includeEmpty = false } = {}) {
      const rows = includeEmpty ? [`<option value="">${escapeHtml(emptyLabel)}</option>`] : [];
      for (const option of managedOptions(fieldName, true)) {
        if (includeEmpty && String(option.value) === "") continue;
        const selected = String(option.value) === String(current || "") ? " selected" : "";
        rows.push(`<option value="${escapeHtml(option.value)}"${selected}>${escapeHtml(option.label || option.value)}</option>`);
      }
      return rows.join("");
    }

    function statusOptions(current) {
      return managedOptionsHtml("sampling_status", current, { includeEmpty: false });
    }

    function badgeOptions(current) {
      return managedOptionsHtml("badge", current || "", { includeEmpty: false });
    }

    function saleOptions(current) {
      return managedOptionsHtml("sale_status", current || "", { includeEmpty: false });
    }

    function refreshSelect(selector, fieldName, current, emptyLabel = "", includeEmpty = false) {
      const el = typeof selector === "string" ? document.querySelector(selector) : selector;
      if (!el) return;
      const value = current ?? el.value;
      el.innerHTML = managedOptionsHtml(fieldName, value, { emptyLabel, includeEmpty });
      el.value = value || "";
    }

    function refreshManagedSelects() {
      refreshSelect("#country", "country", undefined, "全部", true);
      refreshSelect("#brand", "brand", undefined, "全部", true);
      refreshSelect("#status", "sampling_status", undefined, "全部", true);
      refreshSelect("#badge", "badge", undefined, "全部", true);
      refreshSelect("#price-currency", "price_currency", undefined, "全部", true);
      refreshSelect("#price-bucket", "price_bucket", undefined, "", false);
      refreshSelect("#bulk-status", "sampling_status");
      refreshSelect("#rule-brand", "brand");
      refreshSelect('select[name="type"]', "manual_model_type");
      refreshSelect('select[name="brand"]', "brand", undefined, "请选择", true);
      refreshSelect('select[name="source_country"]', "country");
      refreshSelect('select[name="missing_country"]', "country", "MX");
      refreshSelect('select[name="badge"]', "badge");
      refreshSelect('select[name="sale_status"]', "sale_status");
      refreshSelect('select[name="sampling_status"]', "sampling_status");
    }

    function currentFieldName() {
      return $("#field-name")?.value || "brand";
    }

    function renderFields() {
      const fieldName = currentFieldName();
      const label = FIELD_LABELS[fieldName] || fieldName;
      const options = managedOptions(fieldName, false);
      const target = $("#field-list");
      if (!target) return;
      if (!options.length) {
        target.className = "empty";
        target.textContent = "暂无字段选项";
        return;
      }
      target.className = "grid";
      target.innerHTML = options.map((option) => `
        <article class="card">
          <div></div>
          <div class="thumb empty-thumb">${escapeHtml(option.value)}</div>
          <div>
            <div class="model">${escapeHtml(option.label || option.value)}</div>
            <div class="meta">
              <span class="pill">${escapeHtml(label)}</span>
              <span class="${Number(option.enabled) === 1 ? "pill" : "pill ignore"}">${Number(option.enabled) === 1 ? "启用" : "停用"}</span>
            </div>
            <div class="actions">
              <button class="small-button edit-field" data-id="${option.id}" data-value="${escapeHtml(option.value)}" data-label="${escapeHtml(option.label || "")}" type="button">修改</button>
              <button class="small-button toggle-field" data-id="${option.id}" data-enabled="${Number(option.enabled) === 1 ? "0" : "1"}" type="button">${Number(option.enabled) === 1 ? "停用" : "启用"}</button>
              <button class="small-button danger delete-field" data-id="${option.id}" type="button">删除</button>
            </div>
          </div>
        </article>
      `).join("");
    }

    async function saveFieldOption() {
      const value = $("#field-value").value.trim();
      const label = $("#field-label").value.trim();
      if (!value) {
        showToast("请输入字段值", "error");
        return;
      }
      try {
        const res = await fetch("/api/field-options", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: state.editingFieldId,
            field_name: currentFieldName(),
            value,
            label: label || value,
            enabled: true
          })
        });
        const result = await res.json();
        if (!res.ok || !result.ok) throw new Error(result.error || "保存字段失败");
        state.editingFieldId = null;
        $("#field-value").value = "";
        $("#field-label").value = "";
        await reloadStaticOptions();
        renderFields();
        showToast("字段已保存", "success");
      } catch (error) {
        showToast("保存字段失败：" + (error.message || "未知错误"), "error");
        console.error(error);
      }
    }

    async function toggleFieldOption(id, enabled) {
      try {
        const res = await fetch("/api/field-options/enabled", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: Number(id), enabled: Boolean(enabled) })
        });
        const result = await res.json();
        if (!res.ok || !result.ok) throw new Error(result.error || "操作失败");
        await reloadStaticOptions();
        renderFields();
        showToast(`已${enabled ? "启用" : "停用"}`, "success");
      } catch (error) {
        showToast("操作失败：" + (error.message || "未知错误"), "error");
        console.error(error);
      }
    }

    async function deleteFieldOption(id) {
      if (!confirm("确认删除该字典项？历史业务数据不会删除。")) return;
      try {
        const res = await fetch("/api/field-options/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: Number(id) })
        });
        const result = await res.json();
        if (!res.ok || !result.ok) throw new Error(result.error || "删除字段失败");
        await reloadStaticOptions();
        renderFields();
        showToast("字段已删除", "success");
      } catch (error) {
        showToast("删除字段失败：" + (error.message || "未知错误"), "error");
        console.error(error);
      }
    }

    function parsePriceForFilter(price) {
      const text = String(price || "").trim();
      if (!text) return { currency: "", amount: null };
      const upper = text.toUpperCase();
      let currency = "";
      if (upper.includes("US$") || /\bUSD\b/.test(upper)) currency = "USD";
      else if (upper.includes("MXN") || /\bMX\$/.test(upper) || text.includes("$")) currency = "MXN";
      else if (upper.includes("CNY") || upper.includes("RMB") || text.includes("¥") || text.includes("￥") || text.includes("元")) currency = "CNY";
      else if (upper.includes("KRW") || text.includes("₩") || text.includes("원")) currency = "KRW";
      if (!currency) return { currency: "", amount: null };
      const match = text.match(/\d[\d,.\s]*/);
      if (!match) return { currency, amount: null };
      const amount = Number(match[0].replace(/[\s,]/g, ""));
      return Number.isFinite(amount) ? { currency, amount } : { currency, amount: null };
    }

    function modelMatches(row, query) {
      const text = String(query || "").trim().toLowerCase();
      if (!text) return true;
      const compact = text.replace(/[\s-]+/g, "");
      const model = String(row.model || "").toLowerCase();
      const normalized = String(row.normalized_model || "").toLowerCase().replace(/[\s-]+/g, "");
      return model.includes(text) || normalized.includes(compact);
    }

    function priceMatches(row, f) {
      const bucket = f.price_bucket || "all";
      if (bucket === "all" && !f.price_currency && !f.price_min && !f.price_max) return true;
      const parsed = parsePriceForFilter(row.price);
      const hasPrice = Boolean(parsed.currency && parsed.amount !== null);
      if (bucket === "unpriced") return !hasPrice;
      if (bucket === "priced" && !hasPrice) return false;
      if (f.price_currency && parsed.currency !== f.price_currency) return false;
      if (parsed.amount === null) return false;
      const min = f.price_min ? Number(f.price_min) : null;
      const max = f.price_max ? Number(f.price_max) : null;
      if (min !== null && parsed.amount < min) return false;
      if (max !== null && parsed.amount > max) return false;
      return true;
    }

    function card(row, table) {
      const status = rowStatus(table, row);
      const country = row.country || row.source_country || "";
      const reason = row.reason ? `<span class="pill warn">${escapeHtml(row.reason)}</span>` : "";
      const badge = row.badge ? `<span class="pill warn">${escapeHtml(row.badge)}</span>` : "";
      const sale = row.sale_status && row.sale_status !== "已售" ? `<span class="pill unreleased">${escapeHtml(row.sale_status)}</span>` : `<span class="pill">已售</span>`;
      const price = row.price ? `<span class="pill">起步价：${escapeHtml(row.price)}</span>` : "";
      const sourceName = row.source_name ? `<span class="pill">${escapeHtml(row.source_name)}</span>` : "";
      const dates = (row.release_date || row.launch_date)
        ? `<div class="dates">
              ${row.release_date ? `<span>发布时间：${escapeHtml(row.release_date)}</span>` : ""}
              ${row.launch_date ? `<span>上市日期：${escapeHtml(row.launch_date)}</span>` : ""}
            </div>`
        : "";
      const key = rowKey(table, row.id);
      const checked = state.selected.has(key) ? "checked" : "";
      return `
        <article class="card" data-key="${escapeHtml(key)}">
          <label class="pick" aria-label="选择 ${escapeHtml(row.model)}">
            <input type="checkbox" class="row-check" data-table="${table}" data-id="${row.id}" ${checked}>
          </label>
          ${imgCell(row)}
          <div>
            <div class="model">${escapeHtml(row.model)}</div>
            <div class="meta">
              <span class="pill">${escapeHtml(row.brand)}</span>
              <span class="pill">${escapeHtml(country)}</span>
              ${statusPill(status)}
              ${badge}
              ${sale}
              ${price}
              ${sourceName}
              ${reason}
            </div>
            ${dates}
            ${(() => {
              const tiposs = row.molding_tipos || [];
              if (!tiposs.length) return "";
              const parts = tiposs.map(t => `${escapeHtml(t.tipo_name)}（${escapeHtml(t.status)}）`);
              return `<div class="molding-tipos" style="font-size:12px; color:var(--muted); margin:4px 0">开模类型：${parts.join("；")}</div>`;
            })()}
            <div class="actions">
              <a href="${escapeHtml(row.source_url)}" target="_blank" rel="noopener">发布链接</a>
              <select class="row-status" data-table="${table}" data-id="${row.id}">
                ${statusOptions(status)}
              </select>
              <select class="row-badge row-status" data-table="${table}" data-id="${row.id}">
                ${badgeOptions(row.badge || "")}
              </select>
              <select class="row-sale row-status" data-table="${table}" data-id="${row.id}">
                ${saleOptions(row.sale_status || "")}
              </select>
              ${tipoSelect(table, row.id)}
              ${(() => {
                const tips = row.molding_tipos || [];
                const pendingTips = tips.filter(t => t.status === "待开模");
                if (!pendingTips.length) return "";
                return pendingTips.map(t => `
                  <button class="small-button mark-tipo-done" data-table="${table}" data-id="${row.id}"
                    data-brand="${escapeHtml(row.brand)}" data-model="${escapeHtml(row.normalized_model)}"
                    data-tipo="${escapeHtml(t.tipo_name)}" type="button"
                    style="margin-top:4px">标记「${escapeHtml(t.tipo_name)}」已开模</button>
                `).join("");
              })()}
              <button class="small-button save-row" data-table="${table}" data-id="${row.id}" type="button">修改</button>
              <button class="small-button sync-dingtalk-row" data-table="${table}" data-id="${row.id}" type="button">确认送审</button>
            </div>
          </div>
        </article>
      `;
    }

    function newsDate(item) {
      const published = item.published_at ? String(item.published_at).slice(0, 10) : "";
      return published || item.seen_date || item.last_collected_at || item.first_collected_at || "";
    }

    function renderNewsSection(targetSelector, items) {
      const target = $(targetSelector);
      if (!target) return;
      if (!items.length) {
        target.innerHTML = `<div class="empty">该分类暂无新闻</div>`;
        return;
      }
      target.innerHTML = items.map((item) => `
        <article class="news-item">
          <a class="news-title" href="${escapeHtml(item.url)}" target="_blank" rel="noopener">
            ${escapeHtml(item.title)}
          </a>
          <div class="meta">
            ${item.brand ? `<span class="pill">${escapeHtml(item.brand)}</span>` : ""}
            ${item.source_name ? `<span class="pill">${escapeHtml(item.source_name)}</span>` : ""}
            ${newsDate(item) ? `<span class="pill">${escapeHtml(newsDate(item))}</span>` : ""}
          </div>
        </article>
      `).join("");
    }

    function renderNews() {
      const news = state.data.news || { items: [] };
      const items = Array.isArray(news.items) ? news.items : [];
      const category = $("#news-category")?.value || "ithome_phone_today";
      const showPhone = category === "ithome_phone_today";
      document.querySelector('[data-news-section="ithome_phone_today"]')?.classList.toggle("hidden", !showPhone);
      document.querySelector('[data-news-section="ithome_brand_search"]')?.classList.toggle("hidden", showPhone);
      const status = $("#news-status");
      if (status) {
        if (news.status && news.status !== "ok") {
          status.className = "empty news-error";
          status.textContent = news.error || "新闻加载失败";
        } else if (news.empty_today) {
          status.className = "empty";
          status.textContent = news.empty_message || "今日暂无相关新闻";
        } else if (news.mode === "recent_retained") {
          status.className = "news-status-note";
          const retentionDays = news.retention_days || 7;
          status.textContent = news.fallback_note && news.fallback_message
            ? `${news.fallback_message}。当前展示最近 ${retentionDays} 天已采集新闻，按时间倒序`
            : `当前展示最近 ${retentionDays} 天已采集新闻，按时间倒序`;
        } else if (news.crawl_failed) {
          status.className = "empty news-error";
          status.textContent = `当日爬取失败：${news.crawl_error || "品牌 tag 页无数据，已使用手机分区关键词结果"}`;
        } else if (news.fallback_used) {
          status.className = "empty";
          status.textContent = showPhone
            ? `该分类本次采集窗口暂无新闻，已展示最近 ${news.fallback_limit || 3} 条新闻`
            : `该分类本次采集窗口暂无新闻，已展示最近 ${news.fallback_limit || 3} 条品牌新闻`;
        } else {
          status.className = "news-status-note";
          status.textContent = news.window_start && news.window_end
            ? `本次采集：${news.window_start} 至 ${news.window_end}`
            : (news.date ? `当天获取：${news.date}` : "当天获取");
        }
      }
      renderNewsSection("#news-ithome-brand", showPhone ? [] : items);
      renderNewsSection("#news-ithome-phone", showPhone ? items : []);
    }

    function visibleRows() {
      const f = filters();
      const table = state.page;
      if (table === "news") return [];
      const rows = table === "today"
        ? [...(state.data.today?.phones || []), ...(state.data.today?.candidates || [])]
        : table === "new-today"
          ? [...(state.data.newToday?.phones || []), ...(state.data.newToday?.candidates || [])]
          : (table === "candidates" ? state.data.candidates : state.data.phones);
      if (API_MODE) return rows;
      return rows.filter((row) => {
        const rowTable = (table === "today" || table === "new-today") ? (row._table || "phones") : table;
        const status = rowStatus(rowTable, row);
        const countryOk = rowTable === "phones"
          ? (!f.country || row.country === f.country)
          : (!f.country || f.country === "MX" || row.source_country === f.country);
        return countryOk &&
          (!f.brand || row.brand === f.brand) &&
          (!f.status || status === f.status) &&
          (!f.badge || row.badge === f.badge) &&
          modelMatches(row, f.model_query) &&
          priceMatches(row, f);
      });
    }

    function applyFilters() {
      const table = state.page;
      const rows = visibleRows();
      const list = $("#list");
      const rulesPanel = $("#rules-panel");
      const fieldsPanel = $("#fields-panel");
      const tipoPanel = $("#tipo-admin-panel");
      const newsPanel = $("#news-panel");
      const newsMode = table === "news";
      const configMode = table === "rules" || table === "fields" || table === "tipo";
      const listMode = !newsMode && !configMode;
      $("#global-toolbar")?.classList.toggle("hidden", configMode);
      $("#advanced-filter-panel")?.classList.toggle("hidden", configMode || newsMode || !state.advancedFilterOpen);
      document.querySelector(".quick-filter-group")?.classList.toggle("hidden", newsMode);
      $(".search-slot")?.classList.toggle("hidden", newsMode);
      document.querySelectorAll("#country, #model-query, #status, #badge, #price-currency, #price-min, #price-max, #price-bucket").forEach((el) => {
        const label = el.closest("label");
        if (label) label.classList.toggle("hidden", newsMode);
      });
      $("#brand")?.closest("label")?.classList.toggle("hidden", newsMode);
      $("#news-filter-actions")?.classList.toggle("hidden", !newsMode);
      $("#global-batchbar")?.classList.toggle("hidden", !listMode);
      $("#title-primary-actions")?.classList.toggle("hidden", !listMode);
      rulesPanel.classList.toggle("hidden", table !== "rules");
      fieldsPanel.classList.toggle("hidden", table !== "fields");
      tipoPanel.classList.toggle("hidden", table !== "tipo");
      newsPanel.classList.toggle("hidden", table !== "news");
      list.classList.toggle("hidden", table === "rules" || table === "fields" || table === "tipo" || table === "news");
      $("#page-title").textContent = table === "today"
        ? `\u5f53\u65e5\u6293\u53d6${state.data.today?.date ? "\uff08" + state.data.today.date + "\uff09" : ""}`
        : table === "new-today"
          ? `\u4eca\u65e5\u4e0a\u65b0${state.data.newToday?.date ? "\uff08" + state.data.newToday.date + (state.data.newToday?.previous_date ? " \u5bf9\u6bd4 " + state.data.newToday.previous_date : "") + "\uff09" : ""}`
          : (table === "rules" ? "\u81ea\u5b9a\u4e49\u7cfb\u5217\u8bc6\u522b\u89c4\u5219" : (table === "fields" ? "\u5b57\u6bb5\u7ba1\u7406" : (table === "tipo" ? "TIPO\u7c7b\u578b\u7ba1\u7406" : (table === "news" ? "\u65b0\u95fb\u677f\u5757" : (table === "candidates" ? "\u58a8\u897f\u54e5\u672a\u4e0a\u65b0\u5019\u9009" : "\u5168\u90e8\u6536\u96c6\u5230\u7684\u673a\u578b")))));
      if (table === "rules") {
        renderRules();
        updateMetrics();
        return;
      }
      if (table === "fields") {
        renderFields();
        updateMetrics();
        return;
      }
      if (table === "tipo") {
        renderTipoOptions();
        updateMetrics();
        return;
      }
      if (table === "news") {
        renderNews();
        updateMetrics();
        return;
      }
      if (!rows.length) {
        list.className = "empty";
        list.textContent = "暂无数据";
      } else {
        list.className = "grid";
        list.innerHTML = rows.map((row) => card(row, (table === "today" || table === "new-today") ? (row._table || "phones") : table)).join("");
      }
      updateMetrics();
      renderTipoOptions();
      updateSelectionToolbar();
    }

    function renderRules() {
      const rules = state.data.rules || [];
      const target = $("#rules-list");
      if (!rules.length) {
        target.className = "empty";
        target.textContent = "暂无自定义系列";
        return;
      }
      target.className = "grid";
      target.innerHTML = rules.map((rule) => `
        <article class="card">
          <div></div>
          <div class="thumb empty-thumb">${escapeHtml(rule.brand)}</div>
          <div>
            <div class="model">${escapeHtml(rule.series_name)}</div>
            <div class="meta">
              <span class="pill">${escapeHtml(rule.brand)}</span>
              <span class="${rule.enabled ? "pill" : "pill ignore"}">${rule.enabled ? "启用" : "停用"}</span>
            </div>
            <div class="actions">
              <button class="small-button toggle-rule" data-id="${rule.id}" data-enabled="${rule.enabled ? "0" : "1"}" type="button">
                ${rule.enabled ? "停用" : "启用"}
              </button>
            </div>
          </div>
        </article>
      `).join("");
    }

    function updateMetrics() {
      const phones = state.data.phones || [];
      const candidates = state.data.candidates || [];
      const candidateStatuses = candidates.map((row) => rowStatus("candidates", row));
      $("#m-candidates").textContent = candidates.length;
      $("#m-unreviewed").textContent = candidateStatuses.filter((status) => status === "未开模").length;
      $("#m-pending").textContent = candidateStatuses.filter((status) => status === "部分开模").length;
      $("#m-phones").textContent = phones.length;
    }

    function pageHasData(page) {
      if (page === "candidates") return Array.isArray(state.data.candidates);
      if (page === "phones") return Array.isArray(state.data.phones);
      if (page === "today") return Boolean(state.data.today && (Array.isArray(state.data.today.phones) || Array.isArray(state.data.today.candidates)));
      if (page === "new-today") return Boolean(state.data.newToday && (Array.isArray(state.data.newToday.phones) || Array.isArray(state.data.newToday.candidates)));
      if (page === "rules") return Array.isArray(state.data.rules);
      if (page === "fields") return Boolean(state.data.fieldOptions);
      if (page === "tipo") return Array.isArray(state.data.tipoOptions);
      if (page === "news") return Boolean(state.data.news && Array.isArray(state.data.news.items));
      return false;
    }

    function switchPage(page) {
      state.page = page;
      state.selected.clear();
      document.querySelectorAll(".tab").forEach((tab) => {
        tab.classList.toggle("active", tab.dataset.page === page);
      });
      if (pageHasData(page)) {
        applyFilters();
        return;
      }
      if (page === "news") {
        loadNewsOnly().catch(console.error);
        return;
      }
      loadCurrentListOnly().catch(console.error);
    }

    function openManualModel() {
      const modal = $("#manual-model-modal");
      const form = $("#manual-model-form");
      form.reset();
      if ($("#brand").value) form.elements.brand.value = $("#brand").value;
      if ($("#country").value && $("#country").value !== "MX") {
        form.elements.source_country.value = $("#country").value;
      }
      modal.classList.remove("hidden");
    }

    function closeManualModel() {
      $("#manual-model-modal").classList.add("hidden");
    }

    async function saveManualModel(event) {
      event.preventDefault();
      if (!API_MODE) {
        alert("静态页面不能保存手动型号，请打开服务版页面");
        return;
      }
      const form = event.currentTarget;
      const payload = Object.fromEntries(new FormData(form).entries());
      const button = form.querySelector("button[type='submit']");
      const oldText = button.textContent;
      button.disabled = true;
      button.textContent = "保存中";
      try {
        const res = await fetch("/api/manual-model", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const result = await res.json();
        if (!res.ok || !result.ok) throw new Error(result.error || result.message || "保存失败");
        closeManualModel();
        switchPage(payload.type === "phones" ? "phones" : "candidates");
        await loadCurrentListOnly();
        alert(result.message || "已保存手动添加型号");
      } catch (error) {
        console.error(error);
        alert(`保存失败：${error.message || error}`);
      } finally {
        button.disabled = false;
        button.textContent = oldText;
      }
    }

    function selectedModelItems() {
      const table = state.page;
      return (table === "today" || table === "new-today")
        ? selectedRows().map((row) => ({ type: row._table || "phones", id: Number(row.id) }))
        : [...state.selected]
          .filter((key) => key.startsWith(`${table}:`))
          .map((key) => ({ type: table, id: Number(key.split(":")[1]) }));
    }

    async function trashSelectedModels() {
      if (!API_MODE) {
        showToast("静态页面不能删除型号，请打开服务版页面", "error");
        return;
      }
      const items = selectedModelItems();
      if (!items.length) {
        showToast("请先选择要删除的型号", "error");
        return;
      }
      if (!confirm(`确认将 ${items.length} 个型号放入回收站？7 天后将彻底删除。`)) return;
      const result = await postJson("/api/models/trash", { items, reason: "manual_bulk_delete" });
      state.selected.clear();
      showToast(`已放入回收站：${result.updated} 个型号`, "success");
      await loadCurrentListOnly();
    }

    function daysUntil(dateText) {
      if (!dateText) return "";
      const target = new Date(dateText);
      if (Number.isNaN(target.getTime())) return "";
      return Math.max(0, Math.ceil((target.getTime() - Date.now()) / 86400000));
    }

    function renderTrashList() {
      const list = $("#trash-list");
      const items = state.trash || [];
      if (!items.length) {
        list.className = "empty";
        list.textContent = "回收站暂无型号";
        return;
      }
      list.className = "trash-list";
      list.innerHTML = items.map((item) => `
        <div class="trash-row">
          <div>
            <div class="model">${escapeHtml(item.model || item.normalized_model)}</div>
            <div class="meta">
              <span class="pill">${escapeHtml(item.brand)}</span>
              <span class="pill">${escapeHtml(item.source_country || "")}</span>
            </div>
          </div>
          <span class="pill">${item.type === "phones" ? "全部机型" : "候选机型"}</span>
          <span>${escapeHtml((item.deleted_at || "").slice(0, 10))}</span>
          <span>${daysUntil(item.purge_after)} 天后清理</span>
          <div class="trash-actions">
            <button class="small-button restore-trash" data-table="${item.type}" data-id="${item.id}" type="button">恢复</button>
            <button class="small-button danger purge-trash" data-table="${item.type}" data-id="${item.id}" type="button">彻底删除</button>
          </div>
        </div>
      `).join("");
    }

    async function openTrash() {
      if (!API_MODE) {
        showToast("静态页面不能查看回收站，请打开服务版页面", "error");
        return;
      }
      $("#trash-modal").classList.remove("hidden");
      await postJson("/api/models/trash/cleanup", {});
      const result = await getJson("/api/models/trash");
      state.trash = result.items || [];
      renderTrashList();
    }

    function closeTrash() {
      $("#trash-modal").classList.add("hidden");
    }

    async function restoreTrashItem(table, id) {
      await postJson("/api/models/restore", { items: [{ type: table, id: Number(id) }] });
      showToast("型号已恢复", "success");
      await openTrash();
      await loadCurrentListOnly();
    }

    async function purgeTrashItem(table, id) {
      if (!confirm("确认彻底删除这个型号？此操作不能恢复。")) return;
      await postJson("/api/models/purge", { items: [{ type: table, id: Number(id) }] });
      showToast("型号已彻底删除", "success");
      await openTrash();
      await loadCurrentListOnly();
    }

    async function cleanupTrash() {
      const result = await postJson("/api/models/trash/cleanup", {});
      showToast(`已清理过期型号：${result.purged} 个`, "success");
      const payload = await getJson("/api/models/trash");
      state.trash = payload.items || [];
      renderTrashList();
      await loadCurrentListOnly();
    }

    document.addEventListener("change", (event) => {
      if (event.target.matches(".row-check")) {
        const key = rowKey(event.target.dataset.table, event.target.dataset.id);
        if (event.target.checked) state.selected.add(key);
        else state.selected.delete(key);
        updateSelectionToolbar();
      } else if (event.target.matches("#field-name")) {
        state.editingFieldId = null;
        $("#field-value").value = "";
        $("#field-label").value = "";
        renderFields();
      } else if (event.target.matches("#news-category")) {
        state.selected.clear();
        loadNewsOnly().catch(console.error);
      } else if (event.target.matches("#country, #brand, #status, #badge, #price-currency, #price-min, #price-max, #price-bucket")) {
        state.selected.clear();
        loadCurrentListOnly().catch(console.error);
      }
    });

    document.addEventListener("input", (event) => {
      if (event.target.matches("#price-min, #price-max")) {
        state.selected.clear();
        loadCurrentListOnly().catch(console.error);
      }
    });

    function setManageMenuOpen(open) {
      $("#manage-menu")?.classList.toggle("hidden", !open);
      $("#manage-menu-toggle")?.setAttribute("aria-expanded", open ? "true" : "false");
    }

    function closeManageMenu() {
      setManageMenuOpen(false);
    }

    document.addEventListener("click", (event) => {
      const clickedInManageMenu = event.target.closest?.(".nav-menu");
      if (event.target.matches("#manage-menu-toggle")) {
        event.stopPropagation();
        setManageMenuOpen($("#manage-menu")?.classList.contains("hidden"));
      } else if (event.target.matches(".tab")) {
        closeManageMenu();
        switchPage(event.target.dataset.page);
      } else if (event.target.matches('.manage-menu-item[data-action="tipo"]')) {
        closeManageMenu();
        switchPage("tipo");
      } else if (event.target.matches(".save-row")) {
        const table = event.target.dataset.table;
        const id = Number(event.target.dataset.id);
        const select = document.querySelector(`.row-status[data-table="${table}"][data-id="${id}"]`);
        const badgeSelect = document.querySelector(`.row-badge[data-table="${table}"][data-id="${id}"]`);
        const saleSelect = document.querySelector(`.row-sale[data-table="${table}"][data-id="${id}"]`);
        Promise.all([
          saveStatus(table, [id], select.value),
          saveLabels(table, [id], badgeSelect.value, saleSelect.value)
        ]).catch(console.error);
      } else if (event.target.matches(".sync-dingtalk-row")) {
        syncDingTalkOne(event.target.dataset.table, Number(event.target.dataset.id), event.target).catch(console.error);
      } else if (event.target.matches(".toggle-rule")) {
        toggleRule(Number(event.target.dataset.id), event.target.dataset.enabled === "1").catch(console.error);
      } else if (event.target.matches(".edit-tipo")) {
        state.editingTipoId = Number(event.target.dataset.id);
        $("#tipo-name").value = event.target.dataset.name || "";
      } else if (event.target.matches(".delete-tipo")) {
        deleteTipoOption(Number(event.target.dataset.id)).catch(console.error);
      } else if (event.target.matches(".edit-field")) {
        state.editingFieldId = Number(event.target.dataset.id);
        $("#field-value").value = event.target.dataset.value || "";
        $("#field-label").value = event.target.dataset.label || "";
      } else if (event.target.matches(".toggle-field")) {
        toggleFieldOption(Number(event.target.dataset.id), event.target.dataset.enabled === "1").catch(console.error);
      } else if (event.target.matches(".delete-field")) {
        deleteFieldOption(Number(event.target.dataset.id)).catch(console.error);
      } else if (event.target.matches(".restore-trash")) {
        restoreTrashItem(event.target.dataset.table, event.target.dataset.id).catch(console.error);
      } else if (event.target.matches(".purge-trash")) {
        purgeTrashItem(event.target.dataset.table, event.target.dataset.id).catch(console.error);
      } else if (event.target.matches(".open-row-tipo")) {
        openTipoPicker(event.target.dataset.table, event.target.dataset.id);
      } else if (event.target.matches(".mark-tipo-done")) {
        if (!API_MODE) {
          showToast("静态页面不支持此操作，请打开服务版页面", "error");
          return;
        }
        const button = event.target;
        const oldText = button.textContent;
        button.disabled = true;
        button.textContent = "标记中";
        const table = button.dataset.table;
        fetch("/api/tipo-status", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: table,
            id: Number(button.dataset.id),
            brand: button.dataset.brand,
            normalized_model: button.dataset.model,
            tipo_name: button.dataset.tipo,
            status: "已开模",
          }),
        }).then(res => res.json()).then(result => {
          if (!result.ok) throw new Error(result.error || "操作失败");
          showToast(`「${button.dataset.tipo}」已标记为已开模，型号状态更新为「${result.aggregate_status}」`, "success");
          reloadAfterRowMutation().catch(console.error);
        }).catch(error => {
          showToast("标记失败：" + (error.message || "未知错误"), "error");
          console.error(error);
        }).finally(() => {
          button.disabled = false;
          button.textContent = oldText;
        });
      }
      if (!clickedInManageMenu) closeManageMenu();
    });

    document.addEventListener("change", (event) => {
      if (event.target.matches(".tipo-check")) {
        if (event.target.checked) state.selectedTipos.add(event.target.value);
        else state.selectedTipos.delete(event.target.value);
      }
    });

    $("#select-visible").addEventListener("click", () => {
      const table = state.page;
      const rows = visibleRows();
      const allSelected = rows.length > 0 && rows.every((row) => {
        const rowTable = (table === "today" || table === "new-today") ? (row._table || "phones") : table;
        return state.selected.has(rowKey(rowTable, row.id));
      });
      if (allSelected || state.selected.size > 0) {
        state.selected.clear();
      } else {
        for (const row of rows) {
          const rowTable = (table === "today" || table === "new-today") ? (row._table || "phones") : table;
          state.selected.add(rowKey(rowTable, row.id));
        }
      }
      applyFilters();
      updateSelectionToolbar();
    });

    $("#export-selected").addEventListener("click", () => {
      const rows = selectedRows();
      if (!rows.length) {
        alert("请先勾选要导出的机型");
        return;
      }
      downloadRows(rows, `${state.page}_selected.csv`);
    });

    $("#bulk-apply").addEventListener("click", () => {
      const table = state.page;
      const selected = (table === "today" || table === "new-today")
        ? selectedRows().map((row) => ({ table: row._table || "phones", id: Number(row.id) }))
        : [...state.selected]
          .filter((key) => key.startsWith(`${table}:`))
          .map((key) => ({ table, id: Number(key.split(":")[1]) }));
      const byTable = selected.reduce((groups, item) => {
        (groups[item.table] ||= []).push(item.id);
        return groups;
      }, {});
      Promise.all(Object.entries(byTable).map(([targetTable, ids]) =>
        saveStatus(targetTable, ids, $("#bulk-status").value)
      )).catch(console.error);
      state.selected.clear();
      updateSelectionToolbar();
    });

    $("#bulk-dingtalk-apply").addEventListener("click", () => syncDingTalkSelected().catch(console.error));
    $("#bulk-delete").addEventListener("click", () => trashSelectedModels().catch((error) => {
      console.error(error);
      showToast(`删除失败：${error.message || error}`, "error");
    }));
    $("#toggle-advanced-filter").addEventListener("click", () => toggleAdvancedFilter());

    $("#refresh").addEventListener("click", () => loadData().catch(console.error));
    $("#news-refresh").addEventListener("click", () => refreshNews().catch(console.error));
    $("#add-rule").addEventListener("click", () => addRule().catch(console.error));
    $("#tipo-save").addEventListener("click", () => saveTipoOption().catch(console.error));
    $("#field-save").addEventListener("click", () => saveFieldOption().catch(console.error));
    $("#field-clear").addEventListener("click", () => {
      state.editingFieldId = null;
      $("#field-value").value = "";
      $("#field-label").value = "";
    });
    $("#tipo-clear").addEventListener("click", () => {
      state.editingTipoId = null;
      $("#tipo-name").value = "";
    });
    $("#export-current").addEventListener("click", exportCurrent);
    $("#model-search-apply").addEventListener("click", applyModelSearch);
    $("#model-query").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        applyModelSearch();
      }
    });
    $("#open-manual-model-nav").addEventListener("click", openManualModel);
    $("#open-trash").addEventListener("click", () => openTrash().catch((error) => {
      console.error(error);
      showToast(`打开回收站失败：${error.message || error}`, "error");
    }));
    $("#close-trash").addEventListener("click", closeTrash);
    $("#trash-cleanup").addEventListener("click", () => cleanupTrash().catch((error) => {
      console.error(error);
      showToast(`清理失败：${error.message || error}`, "error");
    }));
    $("#close-manual-model").addEventListener("click", closeManualModel);
    $("#manual-model-form").addEventListener("submit", saveManualModel);
    $("#manual-model-modal").addEventListener("click", (event) => {
      if (event.target.id === "manual-model-modal") closeManualModel();
    });
    $("#trash-modal").addEventListener("click", (event) => {
      if (event.target.id === "trash-modal") closeTrash();
    });
    $("#tipo-picker-cancel").addEventListener("click", closeTipoPicker);
    $("#tipo-picker-confirm").addEventListener("click", confirmTipoPicker);
    $("#tipo-picker-modal").addEventListener("click", (event) => {
      if (event.target.id === "tipo-picker-modal") closeTipoPicker();
    });
    $("#reset").addEventListener("click", () => {
      $("#country").value = "";
      $("#brand").value = "";
      $("#news-category").value = "ithome_phone_today";
      $("#status").value = "";
      if ($("#badge")) $("#badge").value = "";
      $("#price-currency").value = "";
      $("#price-min").value = "";
      $("#price-max").value = "";
      $("#price-bucket").value = "all";
      $("#model-query").value = "";
      state.selected.clear();
      loadData().catch(console.error);
    });

    $("#mode-note").textContent = API_MODE
      ? "服务版：修改会保存到数据库"
      : "静态版：修改保存在当前浏览器";
    loadData().catch((error) => {
      console.error(error);
      $("#list").className = "empty";
      $("#list").textContent = "加载失败";
    });
  </script>
</body>
</html>"""
