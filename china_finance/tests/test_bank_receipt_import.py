import copy
import hashlib
import io
import json
import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.utils.file_manager import save_file

from china_finance.services import bank_receipt_import as service
from china_finance.services.bank_receipt_parser import ReceiptParseError, parse_receipt_text
from china_finance.services.bank_receipt_social import social_suggestion


def social_data(data):
	return {
		**data,
		"amount": "11173.52",
		"fee_details": [],
		"business_type": "TIPS缴税出账",
		"summary": "社保缴费",
		"tax_details": [
			{"item": name, "amount": amount, "period_from": "20260701", "period_to": "20260731"}
			for name, amount in [
				("工伤保险费", "229.20"),
				("企业职工基本养老保险费", "9168.00"),
				("基本医疗保险费", "1394.32"),
				("失业保险费", "382.00"),
			]
		],
	}


def social_rule(**kwargs):
	return frappe._dict(
		name="test-rule",
		account="expense",
		personal_account="personal",
		accrual_account="accrual",
		injury_company_percent=100,
		pension_company_percent=66.67,
		medical_company_percent=86.30,
		unemployment_company_percent=80,
		**kwargs,
	)


def receipt_text(
	direction="出",
	amount="CNY3.52",
	flow="TEST-FLOW-001",
	business="企业银行收费",
	summary="收费",
	details="收费项目 笔数 金额\n网银支付手续费 1 3.52",
):
	return f"""{direction} 账 回 单
交易日期：2026年08月03日 业务类型：{business}
业务编号：BUSINESS-SHARED 交易流水：{flow}
付款账号：12345678901234 付款人：测试公司
付款开户行：招商银行测试支行
收款账号：98765432101234 收款人：测试收款人
收款开户行：招商银行
交易金额(小写)： {amount}
交易金额(大写)： 人民币金额
交易摘要：{summary}
{details}
经办： 复核： 授权： 回单编号：RECEIPT-001 2026/09/01 08:43:40
"""


class TestReceiptParser(unittest.TestCase):
	def test_user_social_percentages_round_each_item_and_balance(self):
		suggestion = social_suggestion(social_rule(), social_data(parse_receipt_text(receipt_text())))
		self.assertEqual(
			[r["company_amount"] for r in suggestion["breakdown"]], ["229.20", "6112.31", "1203.30", "305.60"]
		)
		self.assertEqual(
			[r["personal_amount"] for r in suggestion["breakdown"]], ["0.00", "3055.69", "191.02", "76.40"]
		)
		self.assertEqual([r["amount"] for r in suggestion["allocations"]], ["7850.41", "3323.11"])
		self.assertEqual(suggestion["social_period"], "2026-07")
		self.assertEqual(
			[r["summary"] for r in suggestion["journal_lines"]],
			["计提7月公司部分社保", "计提7月个人部分社保", "计提7月社保", "支付7月社保"],
		)
		self.assertEqual(suggestion["bank_summary"], "支付7月社保")

	def test_social_month_is_from_coverage_not_payment_or_print_date(self):
		data = social_data(parse_receipt_text(receipt_text()))
		data["posting_date"] = "2026-09-21"
		for row in data["tax_details"]:
			row.update(period_from="20260801", period_to="20260831")
		result = social_suggestion(social_rule(), data)
		self.assertEqual(result["social_period"], "2026-08")
		self.assertEqual(result["journal_lines"][0]["summary"], "计提8月公司部分社保")
		self.assertEqual(result["bank_summary"], "支付8月社保")
		data["posting_date"] = "2027-01-05"
		self.assertEqual(social_suggestion(social_rule(), data)["bank_summary"], "支付2026年8月社保")

	def test_social_ambiguous_or_invalid_coverage_cannot_generate(self):
		for dates in [
			("", ""),
			("20260230", "20260231"),
			("20260731", "20260701"),
			("20260701", "20260831"),
			("20260801", "20260831"),
		]:
			data = social_data(parse_receipt_text(receipt_text()))
			data["tax_details"][0].update(period_from=dates[0], period_to=dates[1])
			with self.subTest(dates=dates):
				result = social_suggestion(social_rule(), data)
				self.assertIsNone(result["account"])
				self.assertIn("所属时期", result["reason"])

	def test_social_missing_accrual_account_requires_rule_update(self):
		rule = social_rule()
		rule.accrual_account = None
		self.assertIn(
			"应付科目", social_suggestion(rule, social_data(parse_receipt_text(receipt_text())))["reason"]
		)

	def test_social_unknown_tax_item_requires_manual_classification(self):
		data = social_data(parse_receipt_text(receipt_text()))
		data["tax_details"][0]["item"] = "滞纳金"
		self.assertIsNone(social_suggestion(social_rule(), data)["account"])

	def test_payment_entry_bank_direction_and_transfer_boundary(self):
		bank = frappe._dict(company="test", account="bank")
		pe = frappe._dict(
			doctype="Payment Entry",
			company="test",
			docstatus=1,
			payment_type="Pay",
			paid_from="bank",
			paid_from_account_currency="CNY",
			paid_amount=123.45,
		)
		self.assertEqual(service.voucher_bank_amount(pe, bank), Decimal("-123.45"))
		pe.payment_type = "Internal Transfer"
		with self.assertRaises(frappe.ValidationError):
			service.voucher_bank_amount(pe, bank)

	def test_full_fields_and_fee_details(self):
		r = parse_receipt_text(receipt_text())
		self.assertEqual(r["posting_date"], "2026-08-03")
		self.assertEqual(r["amount"], "3.52")
		self.assertEqual(r["own_account"], "12345678901234")
		self.assertEqual(r["counterparty_account"], "98765432101234")
		self.assertEqual(r["fee_details"][0]["amount"], "3.52")
		self.assertEqual(r["receipt_number"], "RECEIPT-001")

	def test_incoming_uses_payee_as_own_account(self):
		r = parse_receipt_text(
			receipt_text(direction="入", amount="CNY10,000.00", business="汇入汇款", details="")
		)
		self.assertEqual(r["own_account"], "98765432101234")
		self.assertEqual(r["counterparty_account"], "12345678901234")
		self.assertEqual(r["direction"], "收入")

	def test_wage_fee_does_not_merge_by_business_number(self):
		wage = parse_receipt_text(
			receipt_text(
				amount="CNY13,430.74", flow="FLOW-WAGE", business="自助代发付款", summary="工资", details=""
			)
		)
		fee = parse_receipt_text(
			receipt_text(
				amount="CNY1.00",
				flow="FLOW-FEE",
				business="代发付费",
				summary="工资",
				details="收费项目 笔数 金额\n代发手续费 1 1.00",
			)
		)
		self.assertEqual(wage["business_number"], fee["business_number"])
		self.assertNotEqual(
			service.identity("bank", wage["transaction_id"]), service.identity("bank", fee["transaction_id"])
		)

	def test_tax_details_are_not_extra_transactions(self):
		r = parse_receipt_text(
			receipt_text(
				amount="￥655.20",
				business="TIPS缴税出账",
				details="税(费)种名称 所属时期 实缴金额\n个人所得税 20260701--20260731 ￥655.20",
			)
		)
		self.assertEqual(r["amount"], "655.20")
		self.assertEqual(r["posting_date"], "2026-08-03")
		self.assertEqual(r["tax_details"][0]["period_from"], "20260701")

	def test_rejects_missing_identity_wrong_totals_and_foreign_currency(self):
		for text in [
			receipt_text().replace("交易流水：TEST-FLOW-001", ""),
			receipt_text(amount="CNY9.99"),
			receipt_text(amount="USD3.52"),
			receipt_text(amount="CNY9,87.61"),
			receipt_text().replace("2026年08月03日", "2026年02月31日"),
		]:
			with self.subTest(text=text[:30]), self.assertRaises(ReceiptParseError):
				parse_receipt_text(text)

	def test_fee_suggestion_beats_wage_summary(self):
		data = parse_receipt_text(
			receipt_text(
				amount="CNY1.00",
				business="代发付费",
				summary="工资",
				details="收费项目 笔数 金额\n代发手续费 1 1.00",
			)
		)
		with (
			patch.object(frappe, "get_all", return_value=[]),
			patch.object(frappe.db, "get_value", return_value="fee") as get,
		):
			result = service.suggest_account("Test", data)
			self.assertEqual(result["account"], "fee")
			self.assertEqual(get.call_args.args[1]["account_number"], "660303")

	def test_ambiguous_reimbursement_does_not_inherit_old_office_rule(self):
		data = parse_receipt_text(receipt_text(business="支付", summary="报销", details=""))
		with patch.object(frappe, "get_all", return_value=[]):
			self.assertIsNone(service.suggest_account("Test", data)["account"])

	def test_conflicting_company_rules_are_not_arbitrarily_chosen(self):
		data = parse_receipt_text(receipt_text())
		rules = [
			frappe._dict(priority=10, business_type="企业银行收费", keyword="", account=a)
			for a in ("one", "two")
		]
		with patch.object(frappe, "get_all", return_value=rules):
			self.assertIn("冲突", service.suggest_account("Test", data)["reason"])


class TestReceiptIntegration(unittest.TestCase):
	"""Run on a configured CNY test company; every case rolls back all business writes."""

	def setUp(self):
		self.user = frappe.session.user
		frappe.set_user("Administrator")
		self.company = "YUEWEI CN悦为中国"
		if not frappe.db.exists("Company", self.company):
			self.skipTest("requires the local CNY test company")
		self.bank = frappe.get_doc("Bank Account", "招商银行 - 招商")
		self.account = frappe.db.get_value(
			"Account", {"company": self.company, "account_number": "660303"}, "name"
		)
		self.point = "receipt_test_" + frappe.generate_hash(length=8)
		frappe.db.savepoint(self.point)
		self.bank.bank_account_no = self.bank.bank_account_no or "12345678901234"
		frappe.db.set_value("Bank Account", self.bank.name, "bank_account_no", self.bank.bank_account_no)
		self.files = []
		self.data = parse_receipt_text(
			receipt_text(
				amount="CNY987.61",
				flow="TEST-" + frappe.generate_hash(length=15),
				details="收费项目 笔数 金额\n网银手续费 1 987.61",
			)
		)
		self.data.update(
			own_account=self.bank.bank_account_no,
			own_name=self.company,
			page=1,
			position=1,
			bbox=[0, 0, 100, 100],
		)

	def tearDown(self):
		if hasattr(self, "point"):
			frappe.db.rollback(save_point=self.point)
			for file in self.files:
				from pathlib import Path

				Path(file).unlink(missing_ok=True)
		frappe.set_user(self.user)

	def batch(self, mode="新业务制证", data=None):
		from pypdf import PdfWriter

		pdf = PdfWriter()
		pdf.add_blank_page(width=595, height=842)
		pdf.add_metadata({"/Subject": frappe.generate_hash()})
		buffer = io.BytesIO()
		pdf.write(buffer)
		content = buffer.getvalue().replace(b"\xe2\xe3\xcf\xd3", b"test")
		file = save_file("test-bank-receipt.pdf", content, None, None, is_private=1)
		self.files.append(file.get_full_path())
		doc = frappe.get_doc(
			{
				"doctype": service.IMPORT,
				"company": self.company,
				"bank_account": self.bank.name,
				"mode": mode,
				"source_file": file.file_url,
			}
		).insert()
		file.db_set({"attached_to_doctype": service.IMPORT, "attached_to_name": doc.name})
		with patch.object(
			service,
			"parse_cmb_receipts",
			return_value={"rows": [copy.deepcopy(data or self.data)], "errors": [], "parser_version": "test"},
		):
			service.parse_import(doc.name)
		return frappe.get_doc(service.IMPORT, doc.name)

	def process(self, batch, **kwargs):
		return service.process_receipt(
			batch.name, batch.rows[0].name, account=self.account, confirmed=1, **kwargs
		)

	def test_preview_creates_no_bank_or_accounting_entries(self):
		before = {
			dt: frappe.db.count(dt)
			for dt in ("Bank Transaction", "Journal Entry", "GL Entry", service.RECEIPT)
		}
		batch = self.batch()
		self.assertEqual(service.preview_import(batch.name)["rows"][0]["status"], "待处理")
		self.assertEqual(before, {dt: frappe.db.count(dt) for dt in before})

	def test_new_receipt_is_one_draft_and_retry_is_idempotent(self):
		batch = self.batch()
		result = self.process(batch, action="create")
		self.assertNotIn("error", result)
		self.assertEqual(frappe.db.get_value("Journal Entry", result["voucher_name"], "docstatus"), 0)
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": result["voucher_name"]}), 0)
		retry = self.process(batch, action="create")
		self.assertNotIn("error", retry, retry)
		self.assertTrue(retry["reused"])
		second = self.batch()
		self.assertEqual(second.rows[0].receipt, result["receipt"])
		self.assertEqual(second.status, "处理完成")

	def test_history_mode_cannot_create_a_new_voucher(self):
		batch = self.batch("历史补回单")
		before = frappe.db.count("Bank Transaction")
		result = self.process(batch, action="create")
		self.assertIn("历史补回单", result["error"])
		self.assertEqual(before, frappe.db.count("Bank Transaction"))
		self.assertEqual(frappe.get_doc(service.IMPORT, batch.name).rows[0].status, "处理失败")

	def test_failed_voucher_creation_rolls_back_bank_transaction(self):
		batch = self.batch()
		before = frappe.db.count("Bank Transaction")
		result = service.process_receipt(
			batch.name, batch.rows[0].name, "create", account=self.bank.account, confirmed=1
		)
		self.assertIn("error", result)
		self.assertEqual(before, frappe.db.count("Bank Transaction"))
		self.assertFalse(
			frappe.db.exists(service.RECEIPT, service.identity(self.bank.name, self.data["transaction_id"]))
		)

	def manual_voucher(self):
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": self.company,
				"posting_date": self.data["posting_date"],
				"voucher_type": "Journal Entry",
				"accounts": [
					{"account": self.bank.account, "credit_in_account_currency": 987.61},
					{
						"account": self.account,
						"debit_in_account_currency": 987.61,
						"cost_center": frappe.db.get_value("Company", self.company, "cost_center"),
					},
				],
			}
		).insert()
		return je

	def test_history_attachment_and_later_statement_do_not_create_second_voucher(self):
		je = self.manual_voucher()
		batch = self.batch("历史补回单")
		before = frappe.db.count("Journal Entry")
		result = self.process(batch, action="link", voucher_type="Journal Entry", voucher_name=je.name)
		self.assertNotIn("error", result)
		self.assertFalse(result["bank_transaction"])
		bt = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"company": self.company,
				"bank_account": self.bank.name,
				"date": self.data["posting_date"],
				"currency": "CNY",
				"reference_number": self.data["transaction_id"],
				"withdrawal": 987.61,
				"description": "手续费",
			}
		).insert()
		bt.submit()
		self.assertEqual(before, frappe.db.count("Journal Entry"))
		self.assertEqual(frappe.db.get_value(service.RECEIPT, result["receipt"], "bank_transaction"), bt.name)

	def test_candidates_prevent_automatic_duplicate_voucher(self):
		je = self.manual_voucher()
		batch = self.batch()
		self.assertTrue(
			any(r.get("name") == je.name for r in service.preview_import(batch.name)["rows"][0]["candidates"])
		)
		self.assertIn("疑似已有凭证", self.process(batch, action="create")["error"])

	def test_statement_first_receipt_reuses_bank_and_voucher(self):
		bt = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"company": self.company,
				"bank_account": self.bank.name,
				"date": self.data["posting_date"],
				"currency": "CNY",
				"reference_number": self.data["transaction_id"],
				"withdrawal": 987.61,
				"description": "手续费",
			}
		).insert()
		bt.submit()
		bt.reload()
		self.assertTrue(bt.custom_china_journal_entry)
		before = frappe.db.count("Journal Entry")
		batch = self.batch("历史补回单")
		result = self.process(
			batch, action="link", voucher_type="Journal Entry", voucher_name=bt.custom_china_journal_entry
		)
		self.assertNotIn("error", result)
		self.assertEqual(result["bank_transaction"], bt.name)
		self.assertEqual(before, frappe.db.count("Journal Entry"))

	def test_conflicting_same_reference_is_blocked(self):
		batch = self.batch()
		self.process(batch, action="create")
		changed = {**self.data, "amount": "1000.00"}
		second = self.batch(data=changed)
		self.assertEqual(second.status, "识别失败")

	def test_company_account_mismatch_and_source_change_block_processing(self):
		batch = self.batch()
		with self.assertRaises(frappe.ValidationError):
			service.validate_receipt_context(
				{**self.data, "own_account": "9999999999"}, self.bank, self.company
			)
		with patch.object(service, "_source", return_value=b"changed"):
			self.assertIn("原件内容已变化", self.process(batch, action="create")["error"])

	def test_cannot_forge_receipt_or_change_parsed_batch(self):
		batch = self.batch()
		batch.rows[0].amount = 1
		with self.assertRaises(frappe.ValidationError):
			batch.save()
		with self.assertRaises(frappe.PermissionError):
			service.protect_service_document()

	def test_posting_reconciles_and_clears_pending_receipts(self):
		from china_finance.services.voucher import _complete_voucher_workflow

		batch = self.batch()
		result = self.process(batch, action="create")
		self.assertNotIn("error", result)
		self.assertTrue(
			any(
				r.parent == batch.name
				for r in service.pending_receipts(self.company, "2026-08-01", "2026-08-31")
			)
		)
		_complete_voucher_workflow(frappe.get_doc("Journal Entry", result["voucher_name"]))
		receipt = frappe.get_doc(service.RECEIPT, result["receipt"])
		self.assertEqual(service.receipt_status(receipt), "已核销")
		self.assertFalse(
			any(
				r.parent == batch.name
				for r in service.pending_receipts(self.company, "2026-08-01", "2026-08-31")
			)
		)

	def test_user_without_permissions_cannot_process_or_read(self):
		batch = self.batch()
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			service.preview_import(batch.name)
		with self.assertRaises(frappe.PermissionError):
			self.process(batch, action="create")

	def test_same_pdf_attachments_keep_each_batch_accessible(self):
		first = self.batch()
		file = frappe.get_doc("File", {"file_url": first.source_file, "attached_to_name": first.name})
		# A duplicate upload creates a second File that shares the same physical blob.
		duplicate = frappe.get_doc(
			{
				"doctype": service.IMPORT,
				"company": self.company,
				"bank_account": self.bank.name,
				"source_file": first.source_file,
			}
		)
		duplicate.flags.ignore_mandatory = True
		duplicate.insert()
		file.create_attachment_copy(service.IMPORT, duplicate.name, "source_file")
		self.assertEqual(service._source(first), service._source(duplicate))
		with self.assertRaises(frappe.ValidationError):
			file.delete()

	def test_failed_parse_blocks_closing_until_abandoned(self):
		batch = self.batch(data={**self.data, "own_account": "99999999999999"})
		self.assertEqual(batch.status, "识别失败")
		self.assertTrue(
			any(
				r.parent == batch.name
				for r in service.pending_receipts(self.company, "2026-08-01", "2026-08-31")
			)
		)
		service.abandon_import(batch.name, "选错账户，重新导入")
		self.assertFalse(
			any(
				r.parent == batch.name
				for r in service.pending_receipts(self.company, "2026-08-01", "2026-08-31")
			)
		)

	def test_interest_receipt_preserves_negative_debit(self):
		data = {
			**self.data,
			"direction": "收入",
			"summary": "银行利息收入",
			"business_type": "汇入汇款",
			"fee_details": [],
		}
		batch = self.batch(data=data)
		account = frappe.db.get_value(
			"Account", {"company": self.company, "account_number": "660302"}, "name"
		)
		result = service.process_receipt(
			batch.name, batch.rows[0].name, "create", account=account, confirmed=1
		)
		self.assertNotIn("error", result)
		je = frappe.get_doc("Journal Entry", result["voucher_name"])
		line = next(a for a in je.accounts if a.account == account)
		self.assertEqual(line.debit_in_account_currency, -987.61)
		self.assertEqual(line.credit_in_account_currency, 0)

	def test_posted_history_voucher_is_unchanged_and_can_be_amended(self):
		from china_finance.services.voucher import _complete_voucher_workflow

		je = self.manual_voucher()
		_complete_voucher_workflow(je)
		je.reload()
		before = frappe.db.count("GL Entry", {"voucher_no": je.name})
		batch = self.batch("历史补回单")
		result = self.process(batch, action="link", voucher_type="Journal Entry", voucher_name=je.name)
		self.assertNotIn("error", result)
		self.assertEqual(result["status"], "已补回单")
		self.assertEqual(before, frappe.db.count("GL Entry", {"voucher_no": je.name}))
		je.cancel()
		self.assertEqual(
			frappe.db.get_value(service.RECEIPT, result["receipt"], "status"), "凭证已取消或缺失"
		)
		amended = frappe.copy_doc(je)
		amended.amended_from = je.name
		amended.docstatus = 0
		amended.insert()
		relinked = self.process(
			batch,
			action="link",
			voucher_type="Journal Entry",
			voucher_name=amended.name,
			notes="取消后修订，重新核对银行回单",
		)
		self.assertNotIn("error", relinked)
		self.assertEqual(relinked["status"], "凭证待记账")
		self.assertEqual(relinked["receipt"], result["receipt"])

	def test_later_statement_with_conflicting_amount_is_rejected(self):
		batch = self.batch()
		self.process(batch, action="create")
		with self.assertRaises(frappe.ValidationError):
			service.existing_transaction(self.bank.name, {**self.data, "amount": "987.62"})

	def test_statement_duplicate_filter_reuses_equal_receipt_and_rejects_conflict(self):
		from china_finance.overrides.bank_statement_import import (
			BankStatementImportLog,
			ChinaFinanceBankStatementImportLog,
		)

		batch = self.batch()
		self.process(batch, action="create")
		log = ChinaFinanceBankStatementImportLog(
			{"doctype": "Bank Statement Import Log", "bank_account": self.bank.name, "currency": "CNY"}
		)
		transaction = {
			"reference": self.data["transaction_id"],
			"date": self.data["posting_date"],
			"withdrawal": 987.61,
			"deposit": 0,
		}
		with patch.object(BankStatementImportLog, "get_final_transactions", return_value=[transaction]):
			self.assertEqual(log.get_final_transactions([]), [])
			transaction["withdrawal"] = 123
			with self.assertRaises(frappe.ValidationError):
				log.get_final_transactions([])

	def test_linked_draft_cannot_change_bank_amount(self):
		batch = self.batch()
		result = self.process(batch, action="create")
		je = frappe.get_doc("Journal Entry", result["voucher_name"])
		for account in je.accounts:
			if account.account == self.bank.account:
				account.credit_in_account_currency = 888.00
			else:
				account.debit_in_account_currency = 888.00
		with self.assertRaises(frappe.ValidationError):
			je.save()

	def test_social_five_lines_and_period_summaries_survive_posting_and_merge(self):
		from china_finance.services.voucher import _complete_voucher_workflow

		expense = frappe.get_doc("Account", self.account)
		asset_parent = frappe.db.get_value(
			"Account", {"company": self.company, "root_type": "Asset", "is_group": 1}, "name"
		)
		personal = frappe.get_doc(
			{
				"doctype": "Account",
				"company": self.company,
				"account_name": "回单测试个人社保-" + frappe.generate_hash(length=8),
				"parent_account": asset_parent,
				"account_currency": "CNY",
				"is_group": 0,
			}
		).insert()
		rule_data = social_rule(
			company=self.company,
			rule_type="社保分摊",
			direction="支出",
			priority=1,
			enabled=1,
			notes="测试用户确认的社保比例",
		)
		rule_data.pop("name")
		rule_data.update(
			doctype="China Bank Receipt Rule",
			account=expense.name,
			personal_account=personal.name,
			accrual_account=frappe.db.get_value(
				"Account", {"company": self.company, "account_number": "221101"}, "name"
			),
		)
		rule = frappe.get_doc(rule_data).insert()
		data = social_data(self.data)
		self.assertIsNone(service.suggest_account("_Test Company", data)["account"])
		batch = self.batch(data=data)
		self.assertEqual(service.preview_import(batch.name)["rows"][0]["suggestion"]["rule"], rule.name)
		self.assertIn("尚未计提", self.process(batch, action="create_social")["error"])
		self.assertIn(
			"规则已变化",
			self.process(batch, action="create_social", social_not_accrued=1, decision_hash="stale")["error"],
		)
		result = self.process(
			batch,
			action="create_social",
			social_not_accrued=1,
			decision_hash=service.suggest_account(self.company, data)["decision_hash"],
		)
		self.assertNotIn("error", result)
		je = frappe.get_doc("Journal Entry", result["voucher_name"])
		self.assertEqual(len(je.accounts), 5)
		self.assertEqual(str(je.posting_date), data["posting_date"])
		expected_summaries = [
			"计提7月公司部分社保",
			"计提7月个人部分社保",
			"计提7月社保",
			"支付7月社保",
			"支付7月社保",
		]
		self.assertEqual([a.user_remark for a in je.accounts], expected_summaries)
		self.assertEqual(
			[a.account for a in je.accounts],
			[expense.name, personal.name, rule.accrual_account, rule.accrual_account, self.bank.account],
		)
		self.assertEqual(je.accounts[2].credit_in_account_currency, 11173.52)
		self.assertEqual(je.accounts[3].debit_in_account_currency, 11173.52)
		lines = {r.account: r for r in je.accounts}
		self.assertEqual(lines[self.bank.account].credit_in_account_currency, 11173.52)
		self.assertEqual(lines[expense.name].debit_in_account_currency, 7850.41)
		self.assertEqual(lines[personal.name].debit_in_account_currency, 3323.11)
		from china_finance.services.bank_reconciliation import repair_draft_bank_journal_entry_summaries

		bt = frappe.get_doc("Bank Transaction", result["bank_transaction"])
		with patch.object(frappe, "get_all", return_value=[bt]), patch.object(frappe.db, "commit"):
			self.assertEqual(repair_draft_bank_journal_entry_summaries(self.company)["skipped"], 1)
		je.reload()
		self.assertEqual([a.user_remark for a in je.accounts], expected_summaries)
		original_get_single_value = frappe.get_single_value
		with patch.object(
			frappe,
			"get_single_value",
			side_effect=lambda dt, field, *a, **k: (
				1
				if (dt, field) == ("Accounts Settings", "merge_similar_account_heads")
				else original_get_single_value(dt, field, *a, **k)
			),
		):
			_complete_voucher_workflow(je)
		snapshot = frappe.get_doc(
			"China Accounting Voucher",
			{"source_doctype": "Journal Entry", "source_name": je.name, "source_event": "Posting"},
		)
		self.assertEqual(len(snapshot.entries), 5)
		self.assertEqual([r.account for r in snapshot.entries], [r.account for r in je.accounts])
		self.assertEqual(
			[(r.debit, r.credit) for r in snapshot.entries], [(r.debit, r.credit) for r in je.accounts]
		)
		from china_finance.china_finance.report.china_voucher_ledger.china_voucher_ledger import execute

		_, report = execute(
			{
				"company": self.company,
				"from_date": data["posting_date"],
				"to_date": data["posting_date"],
				"voucher_number": je.name,
			}
		)
		self.assertEqual([r["remarks"] for r in report], expected_summaries)
		self.assertEqual(service.receipt_status(frappe.get_doc(service.RECEIPT, result["receipt"])), "已核销")
		decision = json.loads(frappe.db.get_value(service.RECEIPT, result["receipt"], "raw_data"))[
			"accounting_decision"
		]
		self.assertEqual(decision["breakdown"][1]["company_percent"], "66.67")
		self.assertEqual(decision["social_period"], "2026-07")
		self.assertEqual([r["summary"] for r in decision["journal_lines"]], expected_summaries[:4])
