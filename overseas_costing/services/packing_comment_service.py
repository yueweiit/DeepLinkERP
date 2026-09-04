"""从钉钉审批评论提取可人工确认的装箱信息。"""

from __future__ import annotations

import hashlib
import re


PACKING_KEYWORDS = ("装箱", "装柜", "发货", "发出", "寄出", "重量", "毛重", "规格", "尺寸", "dhl", "packing")
QUANTITY_UNITS = r"PCS|pcs|Pcs|件|个|套|箱|包|袋|支|台|卷|托"
NUMBER = r"(?<![\d,.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d,.])"


def build_comment_source_id(instance_id: str, operation_time: str, user_id: str, remark: str) -> str:
    raw = "|".join(str(value or "").strip() for value in (instance_id, operation_time, user_id, remark))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _number(value: str) -> float:
    return float(str(value).replace(",", ""))


def _compact_number(value: float) -> float:
    return round(value, 6)


def _clean_product_name(value: str) -> str:
    text = re.sub(r"^[+＋,，:：;；\s]+|[+＋,，:：;；\s]+$", "", str(value or ""))
    text = re.sub(r"(?:过去|过去了|发货|发出|寄出|到仓|左右|合计)$", "", text)
    return text.strip()


def _quantity(value: str, multiplier: str | None = None) -> float:
    quantity = _number(value)
    if str(multiplier or "").strip() == "万":
        quantity *= 10_000
    return _compact_number(quantity)


def parse_packing_comment(remark: str) -> dict:
    text = str(remark or "").strip()
    rows: list[dict] = []
    seen: set[tuple[str, str, float]] = set()

    weight_match = re.search(rf"(?:重量|毛重|重)\s*[：:=]?\s*({NUMBER})\s*(?:kg|公斤|千克)\b", text, re.I)
    gross_weight = _number(weight_match.group(1)) if weight_match else None

    dimension_match = re.search(
        rf"(?:规格|尺寸)?\s*[：:=]?\s*({NUMBER})\s*[xX×*]\s*({NUMBER})\s*[xX×*]\s*({NUMBER})\s*(mm|cm|厘米|毫米|m|米)?",
        text,
        re.I,
    )
    dimensions = None
    volume_m3 = None
    if dimension_match:
        dimensions = [_number(dimension_match.group(index)) for index in (1, 2, 3)]
        unit = str(dimension_match.group(4) or "cm").lower()
        divisor = 1_000_000
        if unit in {"mm", "毫米"}:
            dimensions = [value / 10 for value in dimensions]
        elif unit in {"m", "米"}:
            dimensions = [value * 100 for value in dimensions]
        volume_m3 = _compact_number(dimensions[0] * dimensions[1] * dimensions[2] / divisor)

    material_pattern = re.compile(
        rf"\b([A-Z][A-Z0-9_-]*\d[A-Z0-9_-]*)\b[^\n,，;；]{{0,30}}?({NUMBER})\s*({QUANTITY_UNITS})\b",
        re.I,
    )
    for match in material_pattern.finditer(text):
        row = {
            "material_code": match.group(1).upper(),
            "actual_shipped_qty": _number(match.group(2)),
            "unit": match.group(3).upper() if match.group(3).lower() == "pcs" else match.group(3),
        }
        key = (row["material_code"], "", row["actual_shipped_qty"])
        if key not in seen:
            seen.add(key)
            rows.append(row)

    # 历史评论常把多个物料紧凑写成“品名10万套+品名22000个”。
    # 只在数量单位后面是分隔符或发货类结尾词时接受匹配，避免把
    # “亮甲2.0包装袋”中的 2.0 误当成“2 包”。
    product_first_pattern = re.compile(
        rf"^\s*(?P<name>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9._\-\s]{{0,40}})"
        rf"(?P<quantity>{NUMBER})\s*(?P<multiplier>万)?\s*(?P<unit>{QUANTITY_UNITS})"
        rf"(?=\s*(?:$|发货|发出|寄出|过去|到仓|请知悉))",
        re.I,
    )
    for segment in re.split(r"[+＋,，;；\n]+", text):
        match = product_first_pattern.search(segment)
        if not match:
            continue
        product_name = _clean_product_name(match.group("name"))
        if not product_name or not re.search(r"[\u4e00-\u9fff]", product_name):
            continue
        quantity = _quantity(match.group("quantity"), match.group("multiplier"))
        unit = match.group("unit").upper() if match.group("unit").lower() == "pcs" else match.group("unit")
        key = ("", product_name, quantity)
        if key not in seen:
            seen.add(key)
            rows.append({"product_name": product_name, "actual_shipped_qty": quantity, "unit": unit})

    chinese_pattern = re.compile(rf"({NUMBER})\s*({QUANTITY_UNITS})\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_-]{{0,20}})", re.I)
    for match in chinese_pattern.finditer(text):
        product_name = _clean_product_name(match.group(3))
        if not product_name:
            continue
        quantity = _number(match.group(1))
        unit = match.group(2).upper() if match.group(2).lower() == "pcs" else match.group(2)
        if unit == "包" and product_name.startswith("装"):
            continue
        key = ("", product_name, quantity)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"product_name": product_name, "actual_shipped_qty": quantity, "unit": unit})

    if rows:
        if gross_weight is not None:
            rows[0]["gross_weight_kg"] = gross_weight
        if volume_m3 is not None:
            rows[0]["volume_m3"] = volume_m3

    normalized = text.lower()
    keyword_hits = [keyword for keyword in PACKING_KEYWORDS if keyword in normalized]
    is_candidate = bool(rows or ((gross_weight is not None or dimensions) and keyword_hits))
    confidence = min(1.0, 0.35 * bool(rows) + 0.25 * bool(gross_weight) + 0.2 * bool(dimensions) + 0.1 * min(len(keyword_hits), 2))
    return {
        "is_candidate": is_candidate,
        "confidence": round(confidence, 2),
        "gross_weight_kg": gross_weight,
        "dimensions_cm": dimensions,
        "volume_m3": volume_m3,
        "rows": rows,
        "keyword_hits": keyword_hits,
        "source_text": text,
    }
