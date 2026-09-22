"""Local, strict parser for CMB text receipts. No OCR or network service."""

import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

PARSER_VERSION = "cmb-text-v1"
TITLE = re.compile(r"[出入]\s*账\s*回\s*单")


class ReceiptParseError(ValueError):
	pass


def money(value):
	try:
		amount = Decimal(str(value).replace(",", "").strip())
	except InvalidOperation as exc:
		raise ReceiptParseError("金额无法识别") from exc
	if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
		raise ReceiptParseError("金额必须是有效的非负数，最多两位小数")
	return amount


def parse_receipt_text(text):
	"""Parse one receipt; reject missing/ambiguous financial identity fields."""
	text = text.replace("：", ":").replace("（", "(").replace("）", ")")

	def field(label, required=False):
		matches = re.findall(r"(?:^|\s)" + re.escape(label) + r":\s*([^\n]*?)(?=\s+[^\s:]+:|\n|$)", text)
		value = matches[0].strip() if len(matches) == 1 else ""
		if required and not value:
			raise ReceiptParseError(f"缺少或重复的字段：{label}")
		return value

	title = TITLE.search(text)
	if not title or len(TITLE.findall(text)) != 1:
		raise ReceiptParseError("未找到独立的出账/入账回单标题")
	direction = "支出" if title.group().startswith("出") else "收入"
	d = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", field("交易日期", True))
	if not d:
		raise ReceiptParseError("交易日期格式不支持")
	try:
		posting_date = date(*map(int, d.groups())).isoformat()
	except ValueError as exc:
		raise ReceiptParseError("交易日期无效") from exc
	amount_text = field("交易金额(小写)", True)
	m = re.fullmatch(r"(CNY|￥|¥)\s*((?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2})", amount_text)
	if not m:
		raise ReceiptParseError("第一期仅支持明确标注的人民币金额")
	amount = money(m[2])
	if amount <= 0:
		raise ReceiptParseError("交易金额必须大于零")
	flow = field("交易流水", True)
	if not re.fullmatch(r"[A-Za-z0-9-]{5,140}", flow):
		raise ReceiptParseError("交易流水号无效")
	receipt_number = field("回单编号", True).split()[0]
	business_type = field("业务类型", True)
	payer_account, payee_account = field("付款账号"), field("收款账号")
	payer, payee = field("付款人"), field("收款人")
	own_account = payer_account if direction == "支出" else payee_account
	if not re.fullmatch(r"\d{8,32}", own_account):
		raise ReceiptParseError("本方账号缺失、被掩码或格式不支持")
	fees, taxes = [], []
	for line in text.splitlines():
		tax = re.fullmatch(r"(.+?)\s+(\d{8})--(\d{8})\s+[￥¥]?([\d,]+\.\d{2})", line.strip())
		if tax:
			taxes.append(
				{"item": tax[1], "period_from": tax[2], "period_to": tax[3], "amount": str(money(tax[4]))}
			)
		fee = re.fullmatch(r"(.+?)\s+(\d+)\s+([\d,]+\.\d{2})", line.strip())
		if fee and "收费项目" in text:
			fees.append({"item": fee[1], "count": int(fee[2]), "amount": str(money(fee[3]))})
	if "税(费)种名称" in text and not taxes:
		raise ReceiptParseError("税费明细无法完整识别")
	if "收费项目" in text and not fees:
		raise ReceiptParseError("收费明细无法完整识别")
	for details in (fees, taxes):
		if details and sum(money(item["amount"]) for item in details) != amount:
			raise ReceiptParseError("回单明细合计与交易金额不一致")
	return {
		"posting_date": posting_date,
		"direction": direction,
		"currency": "CNY",
		"amount": str(amount),
		"transaction_id": flow,
		"receipt_number": receipt_number,
		"business_type": business_type,
		"business_number": field("业务编号"),
		"summary": field("交易摘要", True),
		"business_reference": field("业务参考号") or field("参考号"),
		"postscript": field("附言"),
		"taxpayer_id": field("纳税人识别号"),
		"taxpayer_name": field("纳税人全称"),
		"own_account": own_account,
		"own_name": payer if direction == "支出" else payee,
		"counterparty": payee if direction == "支出" else payer,
		"counterparty_account": payee_account if direction == "支出" else payer_account,
		"payer": payer,
		"payer_account": payer_account,
		"payer_bank": field("付款开户行"),
		"payee": payee,
		"payee_account": payee_account,
		"payee_bank": field("收款开户行"),
		"fee_period": field("收费时段"),
		"tax_number": field("税票号码"),
		"fee_details": fees,
		"tax_details": taxes,
		"raw_text": text,
	}


def parse_cmb_receipts(content):
	import pdfplumber

	if not content.startswith(b"%PDF-") or len(content) > 20 * 1024 * 1024:
		raise ReceiptParseError("请上传不超过 20 MB 的 PDF 回单")
	rows, errors = [], []
	try:
		with pdfplumber.open(io.BytesIO(content)) as pdf:
			if not 1 <= len(pdf.pages) <= 100:
				raise ReceiptParseError("单次支持 1—100 页回单")
			for page_number, page in enumerate(pdf.pages, 1):
				headings = page.search(TITLE)
				if not headings:
					errors.append(
						{
							"page": page_number,
							"message": "未识别到文字版回单；扫描件、非回单页面或其他版式暂不支持",
						}
					)
					continue
				for index, heading in enumerate(headings):
					if len(rows) >= 300:
						raise ReceiptParseError("单次最多支持 300 张回单")
					bottom = headings[index + 1]["top"] if index + 1 < len(headings) else page.height
					bbox = (
						0,
						max(0, heading["top"] - 2),
						page.width,
						bottom - 2 if index + 1 < len(headings) else bottom,
					)
					try:
						row = parse_receipt_text(page.crop(bbox).extract_text() or "")
						row.update(page=page_number, position=index + 1, bbox=list(bbox))
						rows.append(row)
					except ReceiptParseError as exc:
						errors.append({"page": page_number, "position": index + 1, "message": str(exc)})
	except ReceiptParseError:
		raise
	except Exception as exc:
		raise ReceiptParseError("无法读取 PDF，请确认文件未加密、未损坏且包含文字层") from exc
	return {"rows": rows, "errors": errors, "parser_version": PARSER_VERSION}
