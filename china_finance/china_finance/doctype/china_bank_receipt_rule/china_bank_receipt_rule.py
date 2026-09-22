import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from china_finance.services.bank_receipt_social import SOCIAL_ITEMS


class ChinaBankReceiptRule(Document):
	def validate(self):
		if self.rule_type != "社保分摊" and not self.business_type and not self.keyword:
			frappe.throw("业务类型和关键词至少填写一项")
		if (
			self.effective_from
			and self.effective_to
			and getdate(self.effective_from) > getdate(self.effective_to)
		):
			frappe.throw("交易日期起不能晚于交易日期止")
		account = frappe.get_doc("Account", self.account)
		if (
			account.company != self.company
			or account.is_group
			or account.disabled
			or account.account_currency != "CNY"
		):
			frappe.throw("请选择本公司启用的明细科目")
		if self.rule_type == "社保分摊":
			if self.direction != "支出" or account.root_type != "Expense":
				frappe.throw("社保分摊须为支出，公司承担科目须为费用科目")
			personal = frappe.get_doc("Account", self.personal_account)
			if (
				personal.company != self.company
				or personal.is_group
				or personal.disabled
				or personal.account_currency != "CNY"
				or personal.root_type != "Asset"
				or personal.account_type in ("Bank", "Cash", "Receivable", "Payable")
			):
				frappe.throw(
					"个人承担请选择本公司人民币其他应收款明细科目；需要逐人往来核算时请手工制证后关联"
				)
			if not self.accrual_account:
				frappe.throw("请设置社保计提及支付使用的应付科目")
			accrual = frappe.get_doc("Account", self.accrual_account)
			if (
				accrual.company != self.company
				or accrual.is_group
				or accrual.disabled
				or accrual.account_currency != "CNY"
				or accrual.root_type != "Liability"
				or accrual.account_type in ("Bank", "Cash", "Receivable", "Payable")
			):
				frappe.throw(
					"社保计提请选择本公司启用的人民币负债明细科目；需要往来单位的科目请手工制证后关联"
				)
			for field in SOCIAL_ITEMS.values():
				if self.get(field) is None or not 0 <= self.get(field) <= 100:
					frappe.throw("请填写 0 至 100 之间的公司承担百分比")
