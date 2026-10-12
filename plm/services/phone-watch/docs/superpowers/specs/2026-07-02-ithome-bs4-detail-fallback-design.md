# IT之家 BS4 主抓、详情页校验与 Playwright 兜底设计

## 背景

当前新闻板块的 IT之家品牌搜索已经做了两层改造：

- 搜索请求节流：每个品牌关键词随机延迟 `8~20` 秒，每 3 个请求额外冷却 `30~60` 秒。
- Playwright 真实浏览态兜底：当搜索页返回异常短页或登录/拦截页时，尝试从首页进入搜索。

现场验证显示，Playwright 兜底路径已执行，但多个关键词仍返回 `html_len≈2821/2842`、`text_len=9` 的异常短页，说明常规无头浏览器并不能稳定绕过 IT之家搜索页异常。因此下一步要降低 Playwright 使用频率，把主路径收敛为更轻、更可控的 BS4 静态解析，并用详情页请求提高准确率。

## 目标

采用方案 A：

1. BS4 静态请求搜索页作为主抓路径。
2. 搜索页只负责发现候选新闻链接、列表标题和列表时间。
3. 对搜索结果中的每个新闻详情链接单独请求。
4. 详情页用于确认链接有效，并补强标题、发布时间等字段。
5. 只有搜索页本身异常、拦截或结构不可解析时，才使用 Playwright 兜底搜索页。

## 非目标

- 不改数据库 schema。
- 不改 UI。
- 不把每个详情页都改成 Playwright 请求。
- 不用空结果掩盖搜索页异常、详情页失败或外部依赖异常。
- 不移除已有 IT之家搜索节流。

## 推荐架构

### 主流程

IT之家品牌搜索采集按以下顺序执行：

1. 构造搜索页 URL：`https://www.ithome.com/search/{keyword}.html`。
2. 按已有节流策略等待。
3. 用静态请求获取搜索页 HTML。
4. 用 BS4 解析 `#list .fl ul.bl li`，得到候选新闻：
   - `title`
   - `url`
   - 列表页 `state` 时间文本
   - 从列表页推导的 `seen_date` / `published_at`
5. 如果搜索页是异常页或拦截页：
   - 执行 Playwright 搜索页兜底。
   - 兜底返回 HTML 后仍走同一套 BS4 候选解析。
6. 对候选新闻链接逐个请求详情页。
7. 详情页请求成功后补强候选行。
8. 对补强后的行做去重、采集窗口过滤和 DB upsert。

### 详情页补强规则

每个搜索结果链接单独请求文章详情页，静态请求优先。

详情页成功的判断：

- URL 仍是 `www.ithome.com` 或 `mobile.ithome.com` 的新闻正文 URL。
- HTML 不是异常短页。
- 能解析到正文标题或至少页面 `<title>`。

补强字段优先级：

- `title`：详情页正文标题优先，其次搜索列表标题。
- `published_at`：详情页发布时间优先，其次搜索列表 `state` 推导时间。
- `url`：使用 canonical 后的详情页 URL。
- `seen_date`：优先从 `published_at` 的日期推导；无法推导时使用列表页 `seen_date`。

详情页失败处理：

- 单个详情页请求失败，不让整个搜索源失败。
- 记录 `detail_errors += 1`，并输出 `[WARN] news detail failed: ...`。
- 如果列表页已有足够信息，可以保留该候选行；如果详情页显示异常且列表页字段不足，则跳过该候选。

### Playwright 兜底边界

Playwright 只用于搜索页兜底：

- 搜索页 HTML 被 `is_ithome_blocked_or_error()` 判定为异常。
- 搜索页无法解析出任何候选新闻。
- 当前源允许 fallback。

Playwright 兜底不用于每个详情页的常规请求。详情页如果静态请求失败，只记录详情失败，避免请求量和拦截风险继续放大。

## 组件设计

### `IthomeSearchCandidate`

新增轻量数据结构，表示从搜索页解析出来的候选新闻。

字段：

- `title: str`
- `url: str`
- `state_text: str`
- `seen_date: str | None`
- `published_at: str | None`

### 搜索页解析函数

新增或调整函数：

```python
def parse_ithome_search_candidates(
    html: str,
    base_url: str,
    *,
    seen_date: str | None = None,
    window_end: str | None = None,
) -> list[IthomeSearchCandidate]:
    ...
```

职责：

- 只解析搜索页候选。
- 使用 BS4 作为主解析器。
- 保留现有正则解析作为无 BS4 环境的后备。
- 不直接生成 DB row，避免把“发现候选”和“详情补强”混在一起。

### 详情页解析函数

新增函数：

```python
def enrich_ithome_candidate_from_detail(
    candidate: IthomeSearchCandidate,
    detail_html: str,
    *,
    source: NewsSource,
    seen_date: str,
    collected_at: str,
    window_end: str | None = None,
) -> dict[str, Any] | None:
    ...
```

职责：

- 从详情页解析标题和发布时间。
- 生成最终 `make_news_row()` 行。
- 如果详情页不可用但候选信息足够，生成候选降级行。
- 如果详情页和候选信息都不足，返回 `None`。

### 详情页请求函数

在采集主流程中注入详情页 fetcher，便于单元测试：

```python
detail_fetcher: Fetcher | None = None
detail_sleeper: Callable[[float], None] = time.sleep
detail_random_uniform: Callable[[float, float], float] = random.uniform
```

默认使用现有 `fetch_html()`。每篇详情请求间增加轻量延迟：

- `1.5~4` 秒。
- 只对详情页链接生效。
- 单元测试注入 no-op sleeper。

## 统计与日志

保留已有统计：

- `sources`
- `fetched`
- `parsed`
- `inserted`
- `errors`
- `rendered`
- `render_errors`
- `fallbacks`

新增统计：

- `detail_fetched`
- `detail_errors`

日志建议：

- 搜索页异常：沿用 `[WARN] news source blocked or abnormal after fallback: ...`
- 详情页失败：`[WARN] news detail failed: {source_name} {detail_url} ({ExceptionType}: {message})`
- 详情页异常短页：`[WARN] news detail abnormal: {source_name} {detail_url}`

## 错误语义

- 搜索页请求失败：计入 `errors`。
- 搜索页异常且 Playwright 兜底仍异常：计入 `errors`。
- 详情页请求失败：计入 `detail_errors`，不计入源级 `errors`。
- 搜索页成功但无候选：返回空结果，不伪装成错误。
- 详情页失败但列表页候选足够：保留候选降级行，并计入 `detail_errors`。

## 测试策略

新增单元测试覆盖：

1. BS4 从搜索页解析候选新闻，不直接生成最终 row。
2. 详情页成功时，用详情页标题和发布时间补强。
3. 详情页请求失败时，保留列表页候选行并增加 `detail_errors`。
4. 搜索页异常时才调用 Playwright 兜底。
5. Playwright 兜底返回正常搜索 HTML 后，仍逐个请求详情页。
6. 详情页延迟可注入，测试中不真实 sleep。

回归验证：

- `py -m unittest tests.test_news_crawler -v`
- `py -m unittest tests.test_cli_collect_news -v`
- 真实采集临时库：
  - `py -m phone_watch collect-news --db .codex_tmp\news_bs4_detail_live.sqlite --timeout 20`

## 验收标准

- 单测全部通过。
- 真实采集日志中主路径应以静态搜索页和详情页请求为主。
- Playwright 只在搜索页异常时出现。
- `detail_errors` 能区分详情页失败，不再混入源级 `errors`。
- 采集结果中新闻标题、URL、发布时间比单纯搜索页解析更可靠。
