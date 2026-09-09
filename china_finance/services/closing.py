import frappe
from frappe import _
from frappe.utils import add_days, flt, get_first_day, get_last_day, getdate, now_datetime

from erpnext.accounts.utils import get_fiscal_year

from china_finance.services.financial_statement import (
	PROFIT_AND_LOSS_CLOSING_REMARK,
	get_template,
	snapshot_statement,
	validate_statement_links,
)
from china_finance.services.ledger_reconciliation import get_ar_ap_ledger_check
from china_finance.services.reconciliation_control import get_reconciliation_closing_checks
from china_finance.services.archive import create_archive_package
from china_finance.services.voucher import calculate_entries_hash, get_pending_cancellation_sync_issues
from china_finance.services.purchase_reconciliation import get_blocked_purchase_invoices
from china_finance.services.tax_reconciliation import get_input_tax_closing_checks, get_output_tax_closing_checks
from china_finance.services.disclosure import get_disclosure_closing_checks, get_notes_payload
from china_finance.services.sales_settlement import get_sales_settlement_closing_check
from china_finance.services.cash_flow_assignment import get_assignment_coverage
from china_finance.services.statutory_reporting import get_statutory_report_readiness_data
from china_finance.services.prior_period_error import get_prior_period_error_readiness
from china_finance.setup.china_coa_profile import (
	TEMPORARY_ACCOUNT_NUMBERS, get_china_coa_master_data_readiness,
	get_company_accounts_by_number, get_profile_status,
)
from china_finance.setup.templates import (
	classify_company_account, is_strictly_excluded_from_statement,
	refine_classification_for_template, requires_manual_cash_flow_assignment,
)


def run_closing_checks(company, from_date, to_date, period_closing_voucher=None, closing_type="Monthly"):
	checks = []
	settings = frappe.get_cached_doc("China Finance Settings", company)
	voucher_from_date = max(getdate(from_date), getdate(settings.activation_date))

	def add(code, description, passed, details="", severity="Blocking"):
		checks.append({"check_code": code, "description": description, "passed": int(bool(passed)), "details": details, "severity": severity})

	configuration_errors = []
	role_separation_warning = False
	if not settings.enforce_role_separation:
		role_separation_warning = True
	if not settings.profit_loss_account:
		configuration_errors.append(_("未配置本年利润科目"))
	if not settings.retained_earnings_account:
		configuration_errors.append(_("未配置利润分配科目"))
	if flt(settings.reconciliation_tolerance) <= 0:
		configuration_errors.append(_("对账金额容差必须大于零"))
	add(
		"CONFIGURATION_READINESS", _("中国财务关键配置完整"), not configuration_errors and not role_separation_warning,
		"；".join(
			[*configuration_errors, *([_("未启用制单、审核、记账职责分离")] if role_separation_warning else [])]
		),
		"Blocking" if configuration_errors else ("Warning" if role_separation_warning else "Blocking"),
	)
	prior_errors = get_prior_period_error_readiness(company, from_date, to_date)
	add(
		"PRIOR_PERIOD_ERROR_ADJUSTMENT", _("前期差错更正已审批并附依据"),
		prior_errors["passed"], prior_errors["details"],
	)
	coa_status = get_profile_status(company)
	if coa_status.get("supported"):
		coa_errors = coa_status.get("errors", [])
		coa_warnings = coa_status.get("warnings", [])
		add(
			"CHINA_COA_INTEGRITY", _("中国科目模板及公司默认科目完整"), not coa_errors,
			"；".join([*coa_errors, *coa_warnings]),
			"Blocking" if coa_errors else ("Warning" if coa_warnings else "Blocking"),
		)
		accounts, _duplicates = get_company_accounts_by_number(company)
		temporary_accounts = [accounts[number].name for number in TEMPORARY_ACCOUNT_NUMBERS if number in accounts]
		temporary_balances = []
		if temporary_accounts:
			temporary_balances = frappe.db.sql(
				"""SELECT account, COALESCE(SUM(debit-credit), 0) AS balance FROM `tabGL Entry`
				WHERE company=%(company)s AND posting_date<=%(to_date)s AND is_cancelled=0 AND account IN %(accounts)s
				GROUP BY account""",
				{"company": company, "to_date": to_date, "accounts": temporary_accounts},
				as_dict=True,
			)
		violations = [row for row in temporary_balances if abs(flt(row.balance)) > flt(settings.reconciliation_tolerance)]
		add(
			"CHINA_COA_TEMPORARY_BALANCE", _("临时及待处理科目期末余额为零"),
			not violations,
			"；".join(f"{row.account}: {row.balance}" for row in violations),
		)
		master_data = get_china_coa_master_data_readiness(company)
		blocking_items = [item for item in master_data["items"] if not item["passed"] and item["severity"] == "Blocking"]
		add(
			"CHINA_COA_MASTER_DATA", _("主数据与业务默认科目已就绪"), not blocking_items,
			"；".join(item["label"] + "：" + item["details"] for item in blocking_items),
		)

	required_scope_types = []
	for fieldname, scope_type in (
		("require_customer_reconciliation", "Customer"),
		("require_supplier_reconciliation", "Supplier"),
		("require_bank_reconciliation", "Bank"),
	):
		if settings.get(fieldname):
			required_scope_types.append(scope_type)
	active_scope_types = {
		row.scope_type for row in frappe.get_all(
			"China Reconciliation Scope",
			filters={"company": company, "enabled": 1, "effective_from": ["<=", to_date]},
			fields=["scope_type", "effective_to"],
		)
		if not row.effective_to or getdate(row.effective_to) >= getdate(from_date)
	}
	missing_scope_types = [scope_type for scope_type in required_scope_types if scope_type not in active_scope_types]
	add(
		"RECONCILIATION_SCOPE_CONFIGURATION", _("客户、供应商和银行对账范围已按设置配置"),
		not missing_scope_types,
		_("缺少对账范围：{0}").format(", ".join(missing_scope_types)) if missing_scope_types else "",
		"Blocking" if closing_type == "Year End" else "Warning",
	)

	trial = frappe.db.sql(
		"SELECT COALESCE(SUM(debit-credit), 0) FROM `tabGL Entry` WHERE company=%s AND posting_date<=%s AND is_cancelled=0",
		(company, to_date),
	)[0][0]
	add("TRIAL_BALANCE", _("总账借贷平衡"), abs(flt(trial)) <= 0.005, str(trial))

	missing = count_missing_vouchers(company, voucher_from_date, to_date)
	pending_cancellations = get_pending_cancellation_sync_issues(company, voucher_from_date, to_date)
	voucher_coverage_details = [_("缺少 {0} 张").format(missing)] if missing else []
	if pending_cancellations:
		voucher_coverage_details.append(_("待补齐冲销审计快照 {0} 张").format(len(pending_cancellations)))
	add(
		"VOUCHER_COVERAGE", _("总账来源与冲销均已生成审计快照"),
		missing == 0 and not pending_cancellations, "；".join(voucher_coverage_details),
	)

	hash_errors = count_voucher_hash_errors(company, voucher_from_date, to_date)
	add("VOUCHER_HASH", _("凭证快照与分录哈希一致"), hash_errors == 0, _("异常 {0} 张").format(hash_errors))

	current_templates = [
		get_template(company, statement_type, to_date).name
		for statement_type in ("Balance Sheet", "Profit and Loss", "Cash Flow", "Changes in Equity")
	]
	unreviewed = frappe.db.count(
		"China Financial Statement Mapping",
		{"company": company, "template": ["in", current_templates], "reviewed": 0},
	)
	add("MAPPING_REVIEW", _("财务报表科目映射已复核"), unreviewed == 0, _("未复核 {0} 条").format(unreviewed))

	missing_templates = []
	for statement_type in ("Balance Sheet", "Profit and Loss", "Cash Flow", "Changes in Equity"):
		template = get_template(company, statement_type, to_date).name
		if not template or not frappe.db.exists(
			"China Financial Statement Mapping", {"company": company, "template": template, "reviewed": 1}
		):
			missing_templates.append(statement_type)
	add(
		"MAPPING_COVERAGE",
		_("四类财务报表均已配置并复核科目映射"),
		not missing_templates,
		_("缺少：{0}").format(", ".join(missing_templates)) if missing_templates else "",
	)
	mapping_coverage = get_account_mapping_coverage(company, current_templates)
	add(
		"ACCOUNT_MAPPING_COMPLETENESS", _("适用会计科目均已纳入四类报表映射"),
		mapping_coverage["passed"], mapping_coverage["details"],
	)

	reconciliation_checks = get_reconciliation_closing_checks(company, from_date, to_date)
	add(
		"RECONCILIATION_COVERAGE", _("强制对账范围均已完成当期确认"),
		reconciliation_checks["coverage"]["passed"], reconciliation_checks["coverage"]["details"],
	)
	add(
		"RECONCILIATION_DIFFERENCE", _("强制对账差异均已闭环"),
		reconciliation_checks["differences"]["passed"], reconciliation_checks["differences"]["details"],
	)
	add(
		"RECONCILIATION_DRAFTS", _("非强制对账草稿已关注"), True,
		reconciliation_checks["drafts"]["details"], "Warning",
	)
	if reconciliation_checks["differences"]["timing_count"]:
		add(
			"RECONCILIATION_TIMING", _("已批准时间性差异持续跟踪"), True,
			reconciliation_checks["differences"]["details"], "Warning",
		)

	ledger_check = get_ar_ap_ledger_check(company, to_date)
	add(
		"AR_AP_LEDGER_MATCH", _("应收应付总账与付款台账一致"),
		ledger_check["passed"], ledger_check["details"],
	)

	statement_checks = validate_statement_links(company, from_date, to_date, settings.reconciliation_tolerance)
	add(
		"BALANCE_SHEET_EQUATION", _("资产总计等于负债和所有者权益总计"),
		statement_checks["balance_sheet"]["passed"], statement_checks["balance_sheet"]["details"],
	)
	add(
		"PROFIT_EQUITY_LINK", _("利润表净利润与所有者权益变动表衔接"),
		statement_checks["profit_equity"]["passed"], statement_checks["profit_equity"]["details"],
	)
	add(
		"CASH_FLOW_RECONCILIATION", _("现金流量表与现金及现金等价物变动衔接"),
		statement_checks["cash_flow"]["passed"], statement_checks["cash_flow"]["details"],
	)
	cash_assignment = get_assignment_coverage(company, from_date, to_date)
	add(
		"CASH_FLOW_ASSIGNMENT", _("启用日后现金流量项目均已确认指定"),
		cash_assignment["passed"], cash_assignment["details"],
	)

	disclosure_checks = get_disclosure_closing_checks(company, from_date, to_date, closing_type)
	add(
		"ACCOUNTING_POLICY_COVERAGE", _("核心会计政策已完整配置并生效"),
		disclosure_checks["policy"]["passed"], disclosure_checks["policy"]["details"],
		"Blocking" if closing_type == "Year End" else "Warning",
	)
	add(
		"FINANCIAL_STATEMENT_NOTES", _("财务报表附注已提交"),
		disclosure_checks["notes"]["passed"], disclosure_checks["notes"]["details"],
		disclosure_checks["notes"]["severity"],
	)
	statutory_readiness = get_statutory_report_readiness_data(company, from_date, to_date)
	add(
		"STATUTORY_REPORT_READINESS", _("中国会计准则四表一注正式输出就绪"),
		statutory_readiness["passed"],
		(_("阻断项 {0} 个") if closing_type == "Year End" else _("尚未完成项 {0} 个")).format(
			statutory_readiness["blocking_count"]
		),
		"Blocking" if closing_type == "Year End" else "Warning",
	)

	blocked_purchases = get_blocked_purchase_invoices(company, from_date, to_date)
	add(
		"PURCHASE_RECONCILIATION",
		_("受控采购已完成齐套校验"),
		not blocked_purchases,
		_("未齐套 {0} 张").format(len(blocked_purchases)),
	)

	sales_settlement = get_sales_settlement_closing_check(company, from_date, to_date)
	add(
		"SALES_SETTLEMENT_COVERAGE",
		_("对账结算销售出库已完成正式应收确认"),
		sales_settlement["passed"],
		sales_settlement["details"],
	)

	unallocated_tax = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabChina Tax Invoice` ti
		WHERE ti.company=%s AND ti.invoice_date BETWEEN %s AND %s AND ti.docstatus=1
		AND NOT EXISTS (SELECT 1 FROM `tabChina Tax Invoice Allocation` a WHERE a.parent=ti.name)
		""",
		(company, from_date, to_date),
	)[0][0]
	add("TAX_ALLOCATION", _("税务发票已完成业务分摊"), unallocated_tax == 0, _("未分摊 {0} 张").format(unallocated_tax), "Warning")

	output_tax_checks = get_output_tax_closing_checks(company, from_date, to_date)
	add(
		"OUTPUT_INVOICE_COVERAGE",
		_("必须开票的销售发票已完成票账闭环"),
		output_tax_checks["coverage"]["passed"],
		output_tax_checks["coverage"]["details"],
	)
	add(
		"OUTPUT_TAX_GL",
		_("销项税税票与总账发生额一致"),
		output_tax_checks["gl"]["passed"],
		output_tax_checks["gl"]["details"],
	)
	input_tax_checks = get_input_tax_closing_checks(company, from_date, to_date)
	add(
		"INPUT_TAX_ACCOUNTING",
		_("进项税票分摊与总账发生额一致"),
		input_tax_checks["accounting"]["passed"],
		input_tax_checks["accounting"]["details"],
	)
	add(
		"INPUT_TAX_PENDING",
		_("已勾选未抵扣进项税票已关注"),
		True,
		input_tax_checks["pending"]["details"],
		"Warning",
	)

	pcv_ok = bool(period_closing_voucher and frappe.db.get_value("Period Closing Voucher", period_closing_voucher, "docstatus") == 1)
	add("PERIOD_CLOSING", _("ERPNext 损益结转凭证已提交"), pcv_ok)
	return checks


def get_account_mapping_coverage(company, templates):
	template_types = dict(
		frappe.get_all(
			"China Financial Statement Template", filters={"name": ["in", templates]},
			fields=["name", "statement_type"], as_list=True,
		)
	)
	mapped = {
		(row.template, row.account)
		for row in frappe.get_all(
			"China Financial Statement Mapping", filters={"company": company, "template": ["in", templates]},
			fields=["template", "account"],
		)
	}
	accounts = frappe.get_all(
		"Account", filters={"company": company, "is_group": 0, "disabled": 0},
		fields=["name", "root_type", "account_type"],
	)
	missing = []
	for template, statement_type in template_types.items():
		valid_rows = {
			row.row_code: row.row_type
			for row in frappe.get_cached_doc("China Financial Statement Template", template).rows
		}
		accounts_by_name = {
			row.name: row for row in frappe.get_all(
				"Account", filters={"company": company, "disabled": 0},
				fields=["name", "account_name", "account_number", "parent_account", "root_type", "account_type", "is_group"],
			)
		}
		for account in accounts:
			if not is_account_applicable_to_statement(statement_type, account.root_type, account.account_type):
				continue
			if is_strictly_excluded_from_statement(account.account_number, statement_type):
				continue
			if statement_type == "Cash Flow" and requires_manual_cash_flow_assignment(account.account_number):
				continue
			classification, _basis = classify_company_account(company, account, statement_type, accounts_by_name)
			classification = refine_classification_for_template(account, statement_type, valid_rows, classification)
			row_code = classification[0] if isinstance(classification, tuple) else classification
			# An account with no applicable row in the selected statutory form is
			# intentionally outside that form, not a missing mapping.
			required = bool(row_code and valid_rows.get(row_code) == "Mapped Accounts")
			if required and (template, account.name) not in mapped:
				missing.append(f"{statement_type}:{account.name}")
	return {
		"passed": not missing, "missing": missing,
		"details": _("未映射科目 {0} 个：{1}").format(len(missing), "；".join(missing[:10])) if missing else _("适用科目均已映射"),
	}


def is_account_applicable_to_statement(statement_type, root_type, account_type=None):
	if statement_type == "Balance Sheet":
		return root_type in {"Asset", "Liability", "Equity"}
	if statement_type == "Profit and Loss":
		return root_type in {"Income", "Expense"}
	if statement_type == "Changes in Equity":
		return root_type == "Equity"
	if statement_type == "Cash Flow":
		return account_type not in {"Cash", "Bank"}
	return False


def count_missing_vouchers(company, from_date, to_date):
	return frappe.db.sql(
		"""
		SELECT COUNT(*) FROM (
			SELECT DISTINCT gle.voucher_type, gle.voucher_no
			FROM `tabGL Entry` gle
			LEFT JOIN `tabChina Accounting Voucher` cav
				ON cav.source_key=CONCAT('Posting|', gle.voucher_type, '|', gle.voucher_no) AND cav.docstatus=1
			WHERE gle.company=%s AND gle.posting_date BETWEEN %s AND %s AND gle.is_cancelled=0
			AND cav.name IS NULL
		) missing
		""",
		(company, from_date, to_date),
	)[0][0]


def get_pending_bank_vouchers(company, from_date, to_date):
	"""Return bank-generated Journal Entries that are still drafts.

	A Period Closing Voucher reads GL Entry. Bank transactions whose linked
	Journal Entries are still drafts are therefore not ready to be included in
	the monthly closing calculation.
	"""
	if not frappe.db.has_column("Bank Transaction", "custom_china_journal_entry"):
		return []
	return frappe.db.sql(
		"""
		SELECT bt.name, bt.date, bt.reference_number, bt.custom_china_journal_entry
		FROM `tabBank Transaction` bt
		LEFT JOIN `tabJournal Entry` je ON je.name=bt.custom_china_journal_entry
		WHERE bt.company=%s
			AND bt.date BETWEEN %s AND %s
			AND bt.docstatus=1
			AND bt.custom_china_journal_entry IS NOT NULL
			AND (je.name IS NULL OR je.docstatus!=1)
		ORDER BY bt.date, bt.reference_number
		""",
		(company, from_date, to_date),
		as_dict=True,
	)


def get_ordinary_profit_loss_closings(company, from_date, to_date):
	"""Find legacy ordinary Journal Entries used for period closing."""
	return frappe.get_all(
		"Journal Entry",
		filters={
			"company": company,
			"posting_date": ["between", [from_date, to_date]],
			"docstatus": ["!=", 2],
			"voucher_type": "Journal Entry",
		},
		or_filters=[
			["Journal Entry", "user_remark", "=", PROFIT_AND_LOSS_CLOSING_REMARK],
			["Journal Entry", "remark", "=", PROFIT_AND_LOSS_CLOSING_REMARK],
		],
		fields=["name", "posting_date", "docstatus"],
		order_by="posting_date, name",
	)


def count_voucher_hash_errors(company, from_date, to_date):
	errors = 0
	for name in frappe.get_all(
		"China Accounting Voucher",
		filters={"company": company, "posting_date": ["between", [from_date, to_date]], "docstatus": 1},
		pluck="name",
	):
		doc = frappe.get_doc("China Accounting Voucher", name)
		if calculate_entries_hash(doc.entries) != doc.source_hash:
			errors += 1
	return errors


def create_report_snapshots(closing_run):
	validation_results = validate_statement_links(
		closing_run.company, closing_run.from_date, closing_run.to_date,
		frappe.db.get_value("China Finance Settings", closing_run.company, "reconciliation_tolerance"),
	)
	notes_payload = get_notes_payload(closing_run.company, closing_run.from_date, closing_run.to_date)
	snapshots = [
		snapshot_statement(closing_run, statement_type, validation_results, notes_payload)
		for statement_type in ("Balance Sheet", "Profit and Loss", "Cash Flow", "Changes in Equity")
	]
	package = create_archive_package(
		closing_run.company,
		"China Closing Run",
		closing_run.name,
		closing_run=closing_run.name,
	)
	closing_run.db_set("archive_package", package["file_url"])
	return snapshots


@frappe.whitelist()
def create_period_closing_voucher(company, from_date, to_date, closing_type="Monthly", allow_first_period=False):
	"""Create the draft PCV for the next continuous closing period.

	ERPNext calculates the actual entries when the Period Closing Voucher is
	submitted. This endpoint only creates the reviewed draft and supplies the
	configured profit-and-loss closing account as the target account. An explicit
	``allow_first_period`` opt-in permits a complete monthly period to be used as
	the first period when no earlier closing voucher exists.
	"""
	frappe.only_for(("System Manager", "China Finance Manager"))

	if not company:
		frappe.throw(_("必须选择公司"))

	from_date = getdate(from_date)
	to_date = getdate(to_date)
	if not from_date or not to_date or from_date > to_date:
		frappe.throw(_("损益结转期间不正确"))
	if closing_type not in ("Monthly", "Year End"):
		frappe.throw(_("不支持的结账类型：{0}").format(closing_type))

	settings = frappe.get_cached_doc("China Finance Settings", company)
	if not settings.profit_loss_account:
		frappe.throw(_("请先在中国财务设置中配置本年利润科目"))

	fiscal_year_info = get_fiscal_year(to_date, company=company)
	fiscal_year, fiscal_year_start, fiscal_year_end = (
		fiscal_year_info[0], getdate(fiscal_year_info[1]), getdate(fiscal_year_info[2])
	)
	if to_date > fiscal_year_end:
		frappe.throw(_("结转截止日期不能晚于会计年度结束日 {0}").format(fiscal_year_end))

	previous_end_date = frappe.db.get_value(
		"Period Closing Voucher",
		{"company": company, "fiscal_year": fiscal_year, "docstatus": 1},
		"period_end_date",
		order_by="period_end_date desc",
	)
	required_start_date = add_days(getdate(previous_end_date), 1) if previous_end_date else fiscal_year_start
	first_period_override = bool(
		allow_first_period
		and not previous_end_date
		and closing_type == "Monthly"
		and from_date >= fiscal_year_start
	)
	if from_date != required_start_date and not first_period_override:
		frappe.throw(
			_("本期必须从 {0} 开始，不能跳过或重复结转期间").format(required_start_date),
			title=_("结转期间不连续"),
		)

	if closing_type == "Monthly":
		if from_date != get_first_day(from_date) or to_date != get_last_day(from_date):
			frappe.throw(_("月度结转期间必须是完整自然月"), title=_("月度结转期间不正确"))
	elif to_date != fiscal_year_end:
		frappe.throw(_("年度结转截止日期必须是会计年度结束日 {0}").format(fiscal_year_end))

	pending_bank_vouchers = get_pending_bank_vouchers(company, from_date, to_date)
	if pending_bank_vouchers:
		references = [row.reference_number or row.name for row in pending_bank_vouchers[:10]]
		frappe.throw(
			_("本期还有 {0} 张银行流水凭证未审核提交，请先处理：{1}").format(
				len(pending_bank_vouchers), "、".join(references)
			),
			title=_("银行凭证尚未完成"),
		)

	legacy_closings = get_ordinary_profit_loss_closings(company, from_date, to_date)
	if legacy_closings:
		frappe.throw(
			_("本期已有普通记账凭证作为损益结转：{0}。请先取消或确认旧结转，再生成月末结转凭证").format(
				"、".join(row.name for row in legacy_closings)
			),
			title=_("存在旧损益结转"),
		)

	existing = frappe.db.get_value(
		"Period Closing Voucher",
		{
			"company": company,
			"period_start_date": from_date,
			"period_end_date": to_date,
			"docstatus": ["!=", 2],
		},
		["name", "docstatus", "closing_account_head"],
		as_dict=True,
	)
	if existing:
		if existing.closing_account_head != settings.profit_loss_account:
			frappe.throw(
				_("该期间已有损益结转凭证 {0}，但结转科目不是当前设置的 {1}").format(
					existing.name, settings.profit_loss_account
				),
				title=_("结转科目不一致"),
			)
		return {
			"name": existing.name,
			"created": False,
			"docstatus": existing.docstatus,
			"message": _("该期间已经存在损益结转凭证 {0}").format(existing.name),
		}

	voucher = frappe.get_doc(
		{
			"doctype": "Period Closing Voucher",
			"transaction_date": to_date,
			"company": company,
			"fiscal_year": fiscal_year,
			"period_start_date": from_date,
			"period_end_date": to_date,
			"closing_account_head": settings.profit_loss_account,
			"remarks": _("{0}至{1}损益结转").format(from_date, to_date),
		}
	)
	voucher.insert()
	return {
		"name": voucher.name,
		"created": True,
		"docstatus": voucher.docstatus,
		"message": _("已生成损益结转凭证草稿 {0}，提交后系统将按实际损益科目生成分录").format(voucher.name),
	}


@frappe.whitelist()
def preview_closing_checks(company, from_date, to_date, period_closing_voucher=None, closing_type="Monthly"):
	frappe.only_for(("System Manager", "China Finance Manager"))
	return run_closing_checks(company, getdate(from_date), getdate(to_date), period_closing_voucher, closing_type)


@frappe.whitelist()
def reopen_closing(name, reason):
	frappe.only_for(("System Manager", "China Finance Manager"))
	if not reason:
		frappe.throw(_("重新开账必须填写原因"))
	doc = frappe.get_doc("China Closing Run", name)
	if doc.docstatus != 1 or doc.status != "Closed":
		frappe.throw(_("只有已结账运行单可以重新开账"))
	# A closing run freezes the company cumulatively through its end date. If a
	# user needs to reopen an earlier period, every later closed run must be
	# reopened first; otherwise its later snapshots and freeze boundary would
	# claim that the earlier period is still closed. Process the chain in
	# reverse chronological order, while leaving the Period Closing Vouchers
	# themselves submitted for an explicit, auditable cancellation step.
	runs = frappe.get_all(
		"China Closing Run",
		filters={
			"company": doc.company,
			"to_date": [">=", doc.to_date],
			"status": "Closed",
			"docstatus": 1,
		},
		fields=["name", "to_date", "period_closing_voucher"],
		order_by="to_date desc, creation desc",
		ignore_permissions=True,
	)
	if not any(run.name == doc.name for run in runs):
		frappe.throw(_("未找到需要重新开账的当前结账运行单"))

	reopened_on = now_datetime()
	for run in runs:
		frappe.db.set_value(
			"China Closing Run",
			run.name,
			{
				"status": "Reopened",
				"reopen_reason": reason,
				"reopened_by": frappe.session.user,
				"reopened_on": reopened_on,
			},
			update_modified=True,
		)

	frappe.db.set_value("Company", doc.company, "accounts_frozen_till_date", doc.previous_frozen_date)
	return {
		"name": doc.name,
		"status": "Reopened",
		"reopened_runs": runs,
		"period_closing_vouchers": [
			run.period_closing_voucher for run in runs if run.period_closing_voucher
		],
		"previous_frozen_date": doc.previous_frozen_date,
	}
