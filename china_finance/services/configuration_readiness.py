import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from china_finance.services.disclosure import get_policy_coverage
from china_finance.services.financial_statement import get_template
from china_finance.setup.china_coa_profile import get_china_coa_master_data_readiness, get_profile_status


ALLOWED_ROLES = ("System Manager", "Accounts Manager", "China Finance Manager", "China Finance Auditor")
STATEMENT_TYPES = ("Balance Sheet", "Profit and Loss", "Cash Flow", "Changes in Equity")


def _route(route_type, name, filters=None):
	return {"type": route_type, "name": name, "filters": filters or {}}


def _item(code, label, passed, details, route, count=0, severity="Blocking"):
	return {
		"code": code,
		"label": label,
		"passed": bool(passed),
		"details": details,
		"route": route,
		"count": int(count or 0),
		"severity": severity,
	}


def _active_count(doctype, company, as_of_date, extra_filters=None):
	filters = {"company": company, "enabled": 1, "effective_from": ["<=", as_of_date]}
	filters.update(extra_filters or {})
	return sum(
		1
		for row in frappe.get_all(doctype, filters=filters, fields=["effective_to"])
		if not row.effective_to or getdate(row.effective_to) >= as_of_date
	)


def _required_scope_types(settings):
	return [
		scope_type
		for fieldname, scope_type in (
			("require_customer_reconciliation", "Customer"),
			("require_supplier_reconciliation", "Supplier"),
			("require_bank_reconciliation", "Bank"),
		)
		if settings.get(fieldname)
	]


def build_configuration_readiness(company, as_of_date=None):
	as_of_date = getdate(as_of_date or nowdate())
	settings = frappe.get_cached_doc("China Finance Settings", company)
	coa_status = get_profile_status(company)
	master_data = get_china_coa_master_data_readiness(company)

	settings_errors = []
	role_separation_warning = False
	if not settings.enforce_role_separation:
		role_separation_warning = True
	if not settings.profit_loss_account:
		settings_errors.append(_("未配置本年利润科目"))
	if not settings.retained_earnings_account:
		settings_errors.append(_("未配置利润分配科目"))
	if not settings.reconciliation_tolerance or settings.reconciliation_tolerance <= 0:
		settings_errors.append(_("对账金额容差无效"))

	active_scopes = {
		row.scope_type
		for row in frappe.get_all(
			"China Reconciliation Scope",
			filters={"company": company, "enabled": 1, "effective_from": ["<=", as_of_date]},
			fields=["scope_type", "effective_to"],
		)
		if not row.effective_to or getdate(row.effective_to) >= as_of_date
	}
	missing_scopes = [scope_type for scope_type in _required_scope_types(settings) if scope_type not in active_scopes]

	output_mappings = _active_count("China Tax Account Mapping", company, as_of_date, {"direction": "Output"})
	input_mappings = _active_count("China Tax Account Mapping", company, as_of_date, {"direction": "Input"})
	required_tax_directions = ["Output"] + (["Input"] if settings.taxpayer_type == "一般纳税人" else [])
	missing_tax_directions = [
		direction
		for direction, count in (("Output", output_mappings), ("Input", input_mappings))
		if direction in required_tax_directions and not count
	]
	tax_direction_labels = {"Output": _("销项"), "Input": _("进项")}

	templates = []
	missing_templates = []
	for statement_type in STATEMENT_TYPES:
		try:
			templates.append(get_template(company, statement_type, as_of_date).name)
		except frappe.ValidationError:
			missing_templates.append(statement_type)
	unreviewed_mappings = frappe.db.count(
		"China Financial Statement Mapping",
		{"company": company, "template": ["in", templates], "reviewed": 0},
	) if templates else 0
	reviewed_templates = {
		row.template
		for row in frappe.get_all(
			"China Financial Statement Mapping",
			filters={"company": company, "template": ["in", templates], "reviewed": 1},
			fields=["template"],
		)
	}
	missing_mapping_templates = [template for template in templates if template not in reviewed_templates]
	policy_coverage = get_policy_coverage(company, as_of_date)
	notes_count = frappe.db.count("China Financial Statement Notes", {"company": company, "docstatus": 1})

	sections = [
		{
			"key": "foundation",
			"label": _("基础设置"),
			"items": [
				_item(
					"CHINA_COA_PROFILE", _("中国科目模板"),
					(not coa_status.get("supported")) or coa_status.get("status") == "Ready",
					_("旧科目表公司保持原有配置") if not coa_status.get("supported") else
					("；".join([*coa_status.get("errors", []), *coa_status.get("warnings", [])]) or _("科目模板与默认科目完整")),
					_route("form", "China Finance Settings", {"name": settings.name}),
					len(coa_status.get("errors", [])) + len(coa_status.get("warnings", [])),
					severity="Info" if not coa_status.get("supported") else "Blocking",
				),
				_item(
					"SETTINGS", _("中国财务设置"), not settings_errors,
					"；".join(
						[*settings_errors, *([_("未启用职责分离")] if role_separation_warning else [])]
					) if settings_errors or role_separation_warning else _("关键设置已完成"),
					_route("form", "China Finance Settings", {"name": settings.name}),
					len(settings_errors) + int(role_separation_warning),
					severity="Blocking" if settings_errors else ("Warning" if role_separation_warning else "Blocking"),
				),
				_item(
					"RECONCILIATION_SCOPE", _("对账范围"), not missing_scopes,
					_('缺少：{0}').format("、".join(missing_scopes)) if missing_scopes else _("必需范围已配置"),
					_route("doctype", "China Reconciliation Scope", {"company": company}), len(missing_scopes),
				),
			],
		},
		{
			"key": "business_rules",
			"label": _("业务规则"),
			"items": [
				_item(
					"INVOICE_CONTROL", _("开票控制规则"), True,
					_("当前有效规则 {0} 条；未配置时按单据人工决定").format(_active_count("China Invoice Control Rule", company, as_of_date)),
					_route("doctype", "China Invoice Control Rule", {"company": company}), severity="Info",
				),
				_item(
					"SALES_SETTLEMENT", _("销售结算规则"), True,
					_("当前有效规则 {0} 条；未配置客户沿用直接确认应收").format(_active_count("China Sales Settlement Rule", company, as_of_date)),
					_route("doctype", "China Sales Settlement Rule", {"company": company}), severity="Info",
				),
				_item(
					"PURCHASE_RECONCILIATION", _("采购应付对账规则"), True,
					_("当前有效规则 {0} 条；未配置供应商沿用直接策略").format(_active_count("China Purchase Reconciliation Rule", company, as_of_date)),
					_route("doctype", "China Purchase Reconciliation Rule", {"company": company}), severity="Info",
				),
			],
		},
		{
			"key": "master_data",
			"label": _("主数据与业务默认科目"),
			"items": master_data["items"],
		},
		{
			"key": "tax_reporting",
			"label": _("税务与报表"),
			"items": [
				_item(
					"TAX_ACCOUNT_MAPPING", _("税务科目映射"), not missing_tax_directions,
					_('缺少 {0} 税务科目映射').format("、".join(tax_direction_labels[item] for item in missing_tax_directions)) if missing_tax_directions else _("进销项税务科目已配置"),
					_route("doctype", "China Tax Account Mapping", {"company": company}), len(missing_tax_directions),
				),
				_item(
					"STATEMENT_TEMPLATE", _("财务报表模板"), not missing_templates,
					_('缺少：{0}').format("、".join(missing_templates)) if missing_templates else _("四类现行模板可用"),
					_route("doctype", "China Financial Statement Template", {}), len(missing_templates),
				),
				_item(
					"STATEMENT_MAPPING", _("财务报表科目映射"), not missing_mapping_templates and not unreviewed_mappings,
					_('未复核 {0} 条，缺少已复核映射模板 {1} 个').format(unreviewed_mappings, len(missing_mapping_templates)),
					_route("doctype", "China Financial Statement Mapping", {"company": company}), unreviewed_mappings + len(missing_mapping_templates),
				),
			],
		},
		{
			"key": "audit",
			"label": _("审计准备"),
			"items": [
				_item(
					"ACCOUNTING_POLICY", _("中国会计政策"), policy_coverage["passed"], policy_coverage["details"],
					_route("doctype", "China Accounting Policy", {"company": company}), len(policy_coverage["missing"]),
				),
				_item(
					"STATEMENT_NOTES", _("财务报表附注"), True,
					_("已提交附注 {0} 份；年结时按结账期间校验").format(notes_count),
					_route("doctype", "China Financial Statement Notes", {"company": company}), notes_count, severity="Info",
				),
			],
		},
	]
	items = [item for section in sections for item in section["items"]]
	return {
		"company": company,
		"as_of_date": str(as_of_date),
		"status": "Ready" if not any(
			not item["passed"] and item["severity"] == "Blocking" for item in items
		) else "Needs Attention",
		"passed_count": sum(1 for item in items if item["passed"]),
		"pending_count": sum(1 for item in items if not item["passed"]),
		"sections": sections,
	}


@frappe.whitelist()
def get_configuration_readiness(company, as_of_date=None):
	frappe.only_for(ALLOWED_ROLES)
	company_doc = frappe.get_doc("Company", company)
	if not company_doc.has_permission("read"):
		frappe.throw(_("无权访问公司 {0}").format(company), frappe.PermissionError)
	if not frappe.db.exists("China Finance Settings", {"company": company, "enabled": 1}):
		frappe.throw(_("公司 {0} 尚未启用中国财务").format(company))
	return build_configuration_readiness(company, as_of_date)
