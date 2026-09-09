import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from china_finance.services.archive import create_archive_record
from china_finance.services.purchase_reconciliation import (
	STATUS_BLOCKED,
	STATUS_WAIVED,
	apply_purchase_reconciliation_statuses,
)


class ChinaReconciliationStatement(Document):
	def validate(self):
		if self.from_date > self.to_date:
			frappe.throw(_("起始日期不能晚于截止日期"))
		if self.statement_type in ("Customer", "Supplier"):
			self.party_type = self.statement_type
			if not self.party:
				frappe.throw(_("客户或供应商对账必须选择往来单位"))
		elif not self.bank_account or not self.account:
			frappe.throw(_("银行对账必须选择银行账户及其会计科目"))
		if self.scope:
			scope = frappe.get_cached_doc("China Reconciliation Scope", self.scope)
			if scope.company != self.company or scope.scope_type != self.statement_type:
				frappe.throw(_("对账单与对账范围不一致"))
			self.confirmation_method = scope.confirmation_method
			duplicate = frappe.db.exists(
				"China Reconciliation Statement",
				{
					"scope": self.scope, "from_date": self.from_date, "to_date": self.to_date,
					"status": ["!=", "Superseded"], "name": ["!=", self.name or ""],
				},
			)
			if duplicate:
				frappe.throw(_("该对账范围和期间已存在有效对账单：{0}").format(duplicate))
		self.period_key = f"{self.from_date}|{self.to_date}"
		if self.statement_type == "Supplier":
			apply_purchase_reconciliation_statuses(self.lines)
			self.blocked_line_count = sum(row.reconciliation_status == STATUS_BLOCKED for row in self.lines)
			self.waived_line_count = sum(row.reconciliation_status == STATUS_WAIVED for row in self.lines)
			for row in self.lines:
				if row.reconciliation_status == STATUS_WAIVED:
					if not row.waiver_reason or not row.waived_by or not row.waived_on:
						frappe.throw(_("采购齐套豁免必须记录原因、豁免人和豁免时间"))
					if not set(("System Manager", "Accounts Manager", "China Finance Manager")) & set(frappe.get_roles()):
						frappe.throw(_("只有财务经理可以豁免采购齐套校验"))
		comparison_balance = self.calculated_bank_balance if self.statement_type == "Bank" else self.closing_balance
		self.difference = flt(self.counterparty_balance) - flt(comparison_balance)

	def before_submit(self):
		if self.statement_type == "Supplier" and self.blocked_line_count:
			blocked = [row.voucher_no for row in self.lines if row.reconciliation_status == STATUS_BLOCKED]
			frappe.throw(_("存在未齐套的采购发票，不能确认对账单：{0}").format("，".join(blocked)))
		if self.confirmation_method in ("External Confirmation", "Bank Statement") and not self.confirmation_file:
			frappe.throw(_("外部确认或银行对账必须上传确认附件"))
		if self.confirmation_method == "Internal Review":
			if not self.internal_review_reason:
				frappe.throw(_("内部复核必须填写原因"))
			if not set(("System Manager", "Accounts Manager", "China Finance Manager")) & set(frappe.get_roles()):
				frappe.throw(_("只有中国财务管理员可以确认内部复核"))
		if self.statement_type == "Bank" and not self.bank_snapshot_json:
			frappe.throw(_("银行对账必须先生成银行对账快照"))
		tolerance = flt(
			frappe.db.get_value("China Reconciliation Scope", self.scope, "amount_tolerance")
			if self.scope else frappe.db.get_value("China Finance Settings", self.company, "reconciliation_tolerance") or 0.01
		)
		if abs(flt(self.difference)) > tolerance:
			difference_total = frappe.db.sql(
				"SELECT COALESCE(SUM(amount), 0) FROM `tabChina Reconciliation Difference` WHERE statement=%s",
				(self.name,),
			)[0][0]
			if abs(flt(difference_total) - flt(self.difference)) > tolerance:
				frappe.throw(_("对账差异必须登记差异事项，且差异事项金额合计应等于对账差异"))
		self.status = "Confirmed"
		self.confirmed_by = frappe.session.user
		self.confirmed_on = now_datetime()

	def on_submit(self):
		if self.confirmation_file:
			create_archive_record(self.company, self.doctype, self.name, "Reconciliation", self.confirmation_file)
		if self.replaces:
			frappe.db.set_value("China Reconciliation Statement", self.replaces, "status", "Superseded", update_modified=False)
