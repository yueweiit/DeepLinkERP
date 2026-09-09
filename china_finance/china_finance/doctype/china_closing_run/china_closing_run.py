import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime

from china_finance.services.closing import create_report_snapshots, run_closing_checks


class ChinaClosingRun(Document):
	def validate(self):
		self._remove_empty_check_rows()
		if self.from_date > self.to_date:
			frappe.throw(_("起始日期不能晚于截止日期"))
		if self.period_closing_voucher:
			company, period_start_date, period_end_date, docstatus = frappe.db.get_value(
				"Period Closing Voucher", self.period_closing_voucher,
				["company", "period_start_date", "period_end_date", "docstatus"],
			)
			if (
				company != self.company
				or getdate(period_start_date) != getdate(self.from_date)
				or getdate(period_end_date) != getdate(self.to_date)
				or docstatus == 2
			):
				frappe.throw(_("损益结转凭证必须与结账运行单的公司和起止日期一致，且不能是已取消状态"))

	def _remove_empty_check_rows(self):
		"""Discard UI-created blank rows before Frappe validates child mandatory fields."""
		populated_rows = [
			row for row in self.get("checks") or []
			if any(row.get(fieldname) for fieldname in ("check_code", "description", "severity", "details"))
		]
		if len(populated_rows) != len(self.get("checks") or []):
			self.set("checks", populated_rows)

	def before_submit(self):
		if self.period_closing_voucher and frappe.db.get_value(
			"Period Closing Voucher", self.period_closing_voucher, "docstatus"
		) != 1:
			frappe.throw(_("请先提交损益结转凭证，再提交结账运行单"))
		checks = run_closing_checks(
			self.company, self.from_date, self.to_date, self.period_closing_voucher, self.closing_type
		)
		self.set("checks", checks)
		failed = [row["description"] for row in checks if row["severity"] == "Blocking" and not row["passed"]]
		if failed:
			frappe.throw(_("以下结账检查未通过：{0}").format("；".join(failed)))
		self.previous_frozen_date = frappe.db.get_value("Company", self.company, "accounts_frozen_till_date")
		self.status = "Closed"
		self.closed_by = frappe.session.user
		self.closed_on = now_datetime()

	def on_submit(self):
		create_report_snapshots(self)
		settings = frappe.get_cached_doc("China Finance Settings", self.company)
		if settings.freeze_on_close:
			frappe.db.set_value("Company", self.company, "accounts_frozen_till_date", self.to_date)
