# Original Currency Price Range Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a long-term maintainable price filter with original-currency selection and min/max range inputs, without converting between currencies.

**Architecture:** Keep the existing `price TEXT` storage unchanged and introduce a small parsing helper that derives `currency` and numeric `amount` from the original price string at query time. API filtering happens in `phone_watch/db.py` and `phone_watch/webapp.py`; client filtering is mirrored in `phone_watch/ui.py` for static export mode.

**Tech Stack:** Python standard library, existing `http.server` web app, SQLite/PostgreSQL adapter layer, vanilla HTML/CSS/JavaScript in `phone_watch/ui.py`, pytest.

## Global Constraints

- Do not change production data schema for this feature.
- Do not add exchange-rate conversion.
- Currency filtering uses the original price text only.
- If a row price cannot be parsed as the selected currency, exclude it when currency/range filters are active.
- Empty currency means "all currencies"; empty min/max means unbounded side of the interval.
- Min and max are inclusive.
- Preserve current filters: country, brand, status, badge.
- Preserve API mode and static export mode behavior.
- Keep UI compact and consistent with the existing toolbar.

---

## Current State

The current system stores prices as text:

- `raw_items.raw_price`
- `phones.price`
- `candidates.price`
- source mirror tables such as `phones_mx.price`

The list API currently accepts only country, brand, status, source country, seen date, and badge style filters:

- `phone_watch/webapp.py`
  - `/api/phones`
  - `/api/candidates`
  - `/api/today`
  - `/api/new-today`
  - `/export/phones.csv`
  - `/export/candidates.csv`
- `phone_watch/db.py`
  - `list_phones(...)`
  - `list_candidates(...)`
  - `list_new_phones(...)`
  - `list_new_candidates(...)`
- `phone_watch/ui.py`
  - toolbar controls
  - `filters()`
  - `loadData()`
  - `visibleRows()`
  - `card(...)`

The UI currently shows the price as a pill:

```javascript
const price = row.price ? `<span class="pill">起步价：${escapeHtml(row.price)}</span>` : "";
```

## Target Behavior

Add three controls to the toolbar:

- Currency select: all / MXN / CNY / KRW / USD
- Minimum price input
- Maximum price input

Examples:

- Currency `MXN`, min `3000`, max `8000` shows rows whose original price text is Mexican peso-like and whose parsed number is between 3000 and 8000.
- Currency `CNY`, min `1000`, empty max shows rows whose original price text is Chinese yuan-like and whose parsed number is at least 1000.
- Empty currency, min `1000`, max `5000` shows rows from any recognized currency whose parsed number is between 1000 and 5000. This compares raw numeric values across currencies and should be treated as a convenience filter, not a financial comparison.

## Original Currency Rules

The feature intentionally does not convert values. It recognizes currency from price text:

| Currency | Recognized price text examples | Notes |
| --- | --- | --- |
| MXN | `MXN 4,999`, `$4,999`, `$ 4,999`, `4,999 MXN` | `$` defaults to MXN in this project because Mexico retail sources are the main `$` source. |
| CNY | `CNY 1999`, `¥1999`, `￥1999`, `RMB 1999`, `1999 元` | `¥` can also mean JPY, but this crawler does not target Japan. Treat as CNY. |
| KRW | `KRW 599000`, `₩599,000`, `599,000원` | Korean won values usually have no decimals. |
| USD | `USD 299`, `US$299` | Do not classify plain `$299` as USD. |

Ambiguous plain `$` remains MXN. This matches current business context: Mexico storefront pricing is the primary dollar-symbol source. If future sources add US storefronts, add a source-country hint to the parser rather than changing existing behavior silently.

---

### Task 1: Add Price Parsing Helper

**Files:**
- Modify: `phone_watch/db.py`
- Test: `tests/test_price_filtering.py`

**Interfaces:**
- Produces: `parse_price_for_filter(price: Any) -> tuple[str | None, float | None]`
- Consumes: existing Python standard library `re`

- [ ] **Step 1: Write failing parser tests**

Create `tests/test_price_filtering.py`:

```python
from phone_watch.db import parse_price_for_filter


def test_parse_mxn_plain_dollar():
    assert parse_price_for_filter("$4,999") == ("MXN", 4999.0)


def test_parse_mxn_explicit():
    assert parse_price_for_filter("MXN 12,499") == ("MXN", 12499.0)


def test_parse_cny_yuan_symbols():
    assert parse_price_for_filter("￥1,999") == ("CNY", 1999.0)
    assert parse_price_for_filter("1999 元") == ("CNY", 1999.0)


def test_parse_krw_symbols():
    assert parse_price_for_filter("₩599,000") == ("KRW", 599000.0)
    assert parse_price_for_filter("599,000원") == ("KRW", 599000.0)


def test_parse_usd_requires_us_marker():
    assert parse_price_for_filter("US$299") == ("USD", 299.0)
    assert parse_price_for_filter("USD 299.99") == ("USD", 299.99)


def test_unparseable_price_returns_none_pair():
    assert parse_price_for_filter("") == (None, None)
    assert parse_price_for_filter("Consultar precio") == (None, None)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
py -m pytest tests/test_price_filtering.py -v
```

Expected:

```text
ImportError or AttributeError because parse_price_for_filter does not exist
```

- [ ] **Step 3: Implement parser in `phone_watch/db.py`**

Add this near the existing constants and helper functions:

```python
PRICE_FILTER_CURRENCIES = {"MXN", "CNY", "KRW", "USD"}


def parse_price_for_filter(price: Any) -> tuple[str | None, float | None]:
    text = str(price or "").strip()
    if not text:
        return None, None

    upper = text.upper()
    currency: str | None = None
    if "US$" in upper or re.search(r"\bUSD\b", upper):
        currency = "USD"
    elif "MXN" in upper or re.search(r"\bMX\$", upper) or "$" in text:
        currency = "MXN"
    elif "CNY" in upper or "RMB" in upper or "¥" in text or "￥" in text or "元" in text:
        currency = "CNY"
    elif "KRW" in upper or "₩" in text or "원" in text:
        currency = "KRW"

    if currency is None:
        return None, None

    match = re.search(r"\d[\d,.\s]*", text)
    if not match:
        return currency, None

    raw_number = re.sub(r"[\s,]", "", match.group(0))
    try:
        amount = float(raw_number)
    except ValueError:
        return currency, None
    return currency, amount
```

- [ ] **Step 4: Run parser tests**

Run:

```powershell
py -m pytest tests/test_price_filtering.py -v
```

Expected:

```text
6 passed
```

---

### Task 2: Add Shared Price Filter Logic in DB Layer

**Files:**
- Modify: `phone_watch/db.py`
- Test: `tests/test_price_filtering.py`

**Interfaces:**
- Consumes: `parse_price_for_filter(price: Any) -> tuple[str | None, float | None]`
- Produces: `filter_rows_by_price(rows: list[Any], currency: str | None, min_price: float | None, max_price: float | None) -> list[Any]`

- [ ] **Step 1: Add failing helper tests**

Append to `tests/test_price_filtering.py`:

```python
from phone_watch.db import filter_rows_by_price


class Row(dict):
    def keys(self):
        return super().keys()


def test_filter_rows_by_original_currency_and_range():
    rows = [
        Row(id=1, price="$4,999"),
        Row(id=2, price="MXN 9,999"),
        Row(id=3, price="￥1,999"),
        Row(id=4, price="Consultar precio"),
    ]

    filtered = filter_rows_by_price(rows, "MXN", 4000, 8000)

    assert [row["id"] for row in filtered] == [1]


def test_filter_rows_without_currency_uses_recognized_amounts():
    rows = [
        Row(id=1, price="$4,999"),
        Row(id=2, price="￥1,999"),
        Row(id=3, price="Consultar precio"),
    ]

    filtered = filter_rows_by_price(rows, None, 2000, None)

    assert [row["id"] for row in filtered] == [1]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
py -m pytest tests/test_price_filtering.py -v
```

Expected:

```text
ImportError or AttributeError because filter_rows_by_price does not exist
```

- [ ] **Step 3: Implement shared filter helper**

Add below `parse_price_for_filter`:

```python
def filter_rows_by_price(
    rows: list[Any],
    currency: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
) -> list[Any]:
    selected_currency = str(currency or "").strip().upper() or None
    if selected_currency and selected_currency not in PRICE_FILTER_CURRENCIES:
        return []
    if selected_currency is None and min_price is None and max_price is None:
        return rows

    filtered: list[Any] = []
    for row in rows:
        row_currency, amount = parse_price_for_filter(row["price"] if "price" in row.keys() else "")
        if selected_currency and row_currency != selected_currency:
            continue
        if amount is None:
            continue
        if min_price is not None and amount < min_price:
            continue
        if max_price is not None and amount > max_price:
            continue
        filtered.append(row)
    return filtered
```

- [ ] **Step 4: Run helper tests**

Run:

```powershell
py -m pytest tests/test_price_filtering.py -v
```

Expected:

```text
8 passed
```

---

### Task 3: Wire Price Filters Into Existing List Queries

**Files:**
- Modify: `phone_watch/db.py`
- Test: `tests/test_price_filtering.py`

**Interfaces:**
- Consumes: `filter_rows_by_price(...)`
- Extends:
  - `list_phones(..., price_currency: str | None = None, price_min: float | None = None, price_max: float | None = None)`
  - `list_candidates(..., price_currency: str | None = None, price_min: float | None = None, price_max: float | None = None)`
  - `list_new_phones(..., price_currency: str | None = None, price_min: float | None = None, price_max: float | None = None)`
  - `list_new_candidates(..., price_currency: str | None = None, price_min: float | None = None, price_max: float | None = None)`

- [ ] **Step 1: Add integration-style tests using SQLite**

Append to `tests/test_price_filtering.py`:

```python
from phone_watch import db


def test_list_candidates_filters_price_range(tmp_path, monkeypatch):
    db_path = tmp_path / "phones.sqlite"
    monkeypatch.delenv("PHONE_WATCH_DB_BACKEND", raising=False)
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        db.upsert_candidate(conn, {
            "brand": "XIAOMI",
            "source_country": "CN",
            "missing_country": "MX",
            "model": "Redmi A",
            "normalized_model": "redmi a",
            "price": "￥1,999",
            "source_url": "https://example.com/a",
            "first_seen_at": "2026-06-26T00:00:00+00:00",
            "last_seen_at": "2026-06-26T00:00:00+00:00",
        })
        db.upsert_candidate(conn, {
            "brand": "XIAOMI",
            "source_country": "CN",
            "missing_country": "MX",
            "model": "Redmi B",
            "normalized_model": "redmi b",
            "price": "￥4,999",
            "source_url": "https://example.com/b",
            "first_seen_at": "2026-06-26T00:00:00+00:00",
            "last_seen_at": "2026-06-26T00:00:00+00:00",
        })

        rows = db.list_candidates(conn, price_currency="CNY", price_min=1000, price_max=3000)

    assert [row["model"] for row in rows] == ["Redmi A"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
py -m pytest tests/test_price_filtering.py -v
```

Expected:

```text
TypeError because list_candidates does not accept price_currency
```

- [ ] **Step 3: Extend `list_phones`**

Change the signature:

```python
def list_phones(
    conn: Any,
    country: str | None = None,
    brand: str | None = None,
    status: str | None = None,
    seen_date: str | None = None,
    badge: str | None = None,
    price_currency: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
) -> list[Any]:
```

Change the return block:

```python
    rows = conn.execute(
        f"""
        SELECT *
        FROM phones
        {where}
        ORDER BY last_seen_at DESC, brand, country, model
        """,
        params,
    ).fetchall()
    return filter_rows_by_price(rows, price_currency, price_min, price_max)
```

- [ ] **Step 4: Extend `list_candidates`**

Change the signature:

```python
def list_candidates(
    conn: Any,
    *,
    brand: str | None = None,
    status: str | None = None,
    source_country: str | None = None,
    seen_date: str | None = None,
    price_currency: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
) -> list[Any]:
```

Change the return block:

```python
    rows = conn.execute(
        f"""
        SELECT *
        FROM candidates
        {where}
        ORDER BY
            CASE sampling_status
                WHEN '待开模' THEN 0
                WHEN '未开模' THEN 1
                WHEN '已开模' THEN 2
                ELSE 3
            END,
            last_seen_at DESC,
            brand,
            model
        """,
        params,
    ).fetchall()
    return filter_rows_by_price(rows, price_currency, price_min, price_max)
```

Use the exact status strings already present in the file. If the local file shows mojibake because of console encoding, do not rewrite unrelated strings; only wrap the fetched rows before returning.

- [ ] **Step 5: Extend today's list helpers**

Add the same three optional parameters to `list_new_phones` and `list_new_candidates`, then wrap their fetched rows:

```python
rows = conn.execute(...).fetchall()
return filter_rows_by_price(rows, price_currency, price_min, price_max)
```

- [ ] **Step 6: Run tests**

Run:

```powershell
py -m pytest tests/test_price_filtering.py -v
```

Expected:

```text
9 passed
```

---

### Task 4: Parse Query Parameters in Web API

**Files:**
- Modify: `phone_watch/webapp.py`
- Test: `tests/test_price_filtering.py`

**Interfaces:**
- Consumes DB function parameters:
  - `price_currency`
  - `price_min`
  - `price_max`
- Produces API query parameters:
  - `price_currency`
  - `price_min`
  - `price_max`

- [ ] **Step 1: Add query parsing helper**

In `phone_watch/webapp.py`, add near the top-level helper functions:

```python
def parse_optional_float(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    return float(text)


def price_filter_args(query: dict[str, str]) -> dict[str, object]:
    return {
        "price_currency": query.get("price_currency") or None,
        "price_min": parse_optional_float(query.get("price_min")),
        "price_max": parse_optional_float(query.get("price_max")),
    }
```

- [ ] **Step 2: Pass filters to `/api/phones`**

Change:

```python
rows = db.list_phones(
    conn,
    country=query.get("country") or None,
    brand=query.get("brand") or None,
    status=query.get("status") or None,
    badge=query.get("badge") or None,
)
```

To:

```python
rows = db.list_phones(
    conn,
    country=query.get("country") or None,
    brand=query.get("brand") or None,
    status=query.get("status") or None,
    badge=query.get("badge") or None,
    **price_filter_args(query),
)
```

- [ ] **Step 3: Pass filters to `/api/candidates`**

Add `**price_filter_args(query)` to the `db.list_candidates(...)` call.

- [ ] **Step 4: Pass filters to `/api/today` and `/api/new-today`**

Add `**price_filter_args(query)` to each list call inside:

- `db.list_phones(...)`
- `db.list_candidates(...)`
- `db.list_new_phones(...)`
- `db.list_new_candidates(...)`

- [ ] **Step 5: Pass filters to CSV exports**

Add `**price_filter_args(query)` to:

- `/export/phones.csv`
- `/export/candidates.csv`

- [ ] **Step 6: Add invalid range handling**

Wrap list handling in the existing `try` block. If `parse_optional_float` raises `ValueError`, current exception handling will return HTTP 500. Replace that with an explicit 400 for invalid query values:

```python
        except ValueError as exc:
            self.send_json({"error": f"Invalid price filter: {exc}"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
```

- [ ] **Step 7: Run tests**

Run:

```powershell
py -m pytest tests/test_price_filtering.py -v
```

Expected:

```text
9 passed
```

---

### Task 5: Add Toolbar Controls and Client-Side Filtering

**Files:**
- Modify: `phone_watch/ui.py`
- Test: manual browser verification

**Interfaces:**
- Produces DOM controls:
  - `#price-currency`
  - `#price-min`
  - `#price-max`
- Extends `filters()` result with:
  - `price_currency`
  - `price_min`
  - `price_max`

- [ ] **Step 1: Add compact toolbar controls**

In the toolbar after badge filter, add:

```html
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
```

Use the file's existing text encoding style if the source file displays Chinese text as mojibake in the terminal. Do not rewrite surrounding Chinese text.

- [ ] **Step 2: Extend `filters()`**

Change `filters()` to include:

```javascript
price_currency: $("#price-currency").value,
price_min: $("#price-min").value.trim(),
price_max: $("#price-max").value.trim()
```

- [ ] **Step 3: Include query parameters in API mode**

Existing `loadData()` uses `qs(f)` for phones and passes selected keys for candidates/today. Add these three fields to each API call:

```javascript
price_currency: f.price_currency,
price_min: f.price_min,
price_max: f.price_max
```

- [ ] **Step 4: Add JS parser for static export mode**

Add JS helpers near other utility functions:

```javascript
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

function priceMatches(row, f) {
  if (!f.price_currency && !f.price_min && !f.price_max) return true;
  const parsed = parsePriceForFilter(row.price);
  if (f.price_currency && parsed.currency !== f.price_currency) return false;
  if (parsed.amount === null) return false;
  const min = f.price_min ? Number(f.price_min) : null;
  const max = f.price_max ? Number(f.price_max) : null;
  if (min !== null && parsed.amount < min) return false;
  if (max !== null && parsed.amount > max) return false;
  return true;
}
```

- [ ] **Step 5: Apply static-mode filtering in `visibleRows()`**

In the static export branch, add:

```javascript
priceMatches(row, f)
```

to the existing return condition.

- [ ] **Step 6: Trigger reload on price controls**

Change:

```javascript
event.target.matches("#country, #brand, #status, #badge")
```

To:

```javascript
event.target.matches("#country, #brand, #status, #badge, #price-currency, #price-min, #price-max")
```

Also add an `input` listener for numeric fields so typing updates after value changes:

```javascript
document.addEventListener("input", (event) => {
  if (event.target.matches("#price-min, #price-max")) {
    state.selected.clear();
    loadData().catch(console.error);
  }
});
```

- [ ] **Step 7: Reset controls**

In reset click handler, add:

```javascript
$("#price-currency").value = "";
$("#price-min").value = "";
$("#price-max").value = "";
```

---

### Task 6: Manual Verification

**Files:**
- No code files beyond Tasks 1-5

**Interfaces:**
- Verifies browser behavior and API behavior

- [ ] **Step 1: Run tests**

Run:

```powershell
py -m pytest -v
```

Expected:

```text
All tests pass
```

- [ ] **Step 2: Start service**

Run:

```powershell
Set-Location -LiteralPath 'C:\Users\JT\Desktop\备份\cst\phone_watch\python-sqlite-https-www-motorola-com'
py -m phone_watch serve --db data\phones.sqlite --port 8000
```

- [ ] **Step 3: Verify API filters**

Open these URLs:

```text
http://127.0.0.1:8000/api/candidates?price_currency=MXN&price_min=3000&price_max=8000
http://127.0.0.1:8000/api/phones?price_currency=CNY&price_min=1000
```

Expected:

- Response is JSON.
- Every returned row has a `price` matching the selected original currency.
- Parsed numeric amount is inside the requested interval.

- [ ] **Step 4: Verify UI filters**

Open:

```text
http://127.0.0.1:8000
```

Expected:

- Toolbar shows `货币`, `最低价`, `最高价`.
- Selecting `MXN` and entering a range refreshes current list.
- Existing filters still work together with price filters.
- Reset clears currency and price range.
- CSV export for current page respects the active price filters.

## Changed Code Summary

Expected implementation touches:

- `phone_watch/db.py`
  - Add original price parser.
  - Add reusable row filter.
  - Extend list functions with optional price parameters.
- `phone_watch/webapp.py`
  - Parse query params.
  - Pass filters into list functions.
  - Return clear bad-request errors for invalid numeric input.
- `phone_watch/ui.py`
  - Add controls.
  - Include filters in API queries.
  - Mirror filtering in static mode.
  - Reset and refresh behavior.
- `tests/test_price_filtering.py`
  - Parser tests.
  - Filter helper tests.
  - List integration test.

## Logic Summary

1. User selects currency and optional min/max.
2. Frontend sends `price_currency`, `price_min`, and `price_max`.
3. Backend loads rows using existing SQL filters.
4. Backend parses each row's original `price` text.
5. Backend excludes rows whose original currency does not match.
6. Backend excludes rows whose numeric price is outside the inclusive interval.
7. UI renders the filtered result without changing stored price text.

## Long-Term Maintenance Notes

- The parser is intentionally centralized in `db.py` so API filtering stays consistent across pages and exports.
- Static export mode has a mirrored JS parser because static HTML cannot call the Python backend.
- Do not silently reinterpret `$` as USD later. If US sources are added, pass source country into the parser and classify `$` by source.
- If price filtering becomes performance-heavy, add generated numeric columns later:
  - `price_currency TEXT`
  - `price_amount REAL`
  - migration backfill from existing `price`
  This is not required for the current UI scale.
- Keep exchange rates out of this feature. A future converted-price filter should be a separate feature with a timestamped rate source and explicit display copy.

## User-Facing Effect

After implementation, the user can narrow models by original selling currency and price range directly in the main toolbar. The result stays simple and predictable: `MXN` means records that already look like MXN in their captured price text, `CNY` means records that already look like CNY, and no conversion happens behind the scenes.

