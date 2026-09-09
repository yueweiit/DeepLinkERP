import frappe
from frappe.utils import add_days, getdate

TEMPLATE_VERSION = "3.0"
MAPPING_RULE_VERSION = "1.6"
TEMPLATE_EFFECTIVE_FROM = "2026-01-01"

# Depreciation and amortisation cannot be translated into a direct-method cash
# flow line from their account number alone. A cash leg involving either must
# be classified and confirmed by the accountant.
NON_CASH_FLOW_SUGGESTION_PREFIXES = ("1231", "1471", "1602", "1702", "510102", "510105")


def requires_manual_cash_flow_assignment(account_number):
	return str(account_number or "").startswith(NON_CASH_FLOW_SUGGESTION_PREFIXES)


def is_strictly_excluded_from_statement(account_number, statement_type):
	return statement_type == "Profit and Loss" and str(account_number or "") == "6901"


def get_seed_version(accounting_standard):
	return TEMPLATE_VERSION


def row(code, label, row_type="Mapped Accounts", formula=None, direction="Debit Positive", indent=0, bold=0):
	return (code, label, row_type, formula, direction, indent, bold)


ENTERPRISE_ROWS = {
	"Balance Sheet": [
		row("CURRENT_ASSETS_HEADING", "流动资产", "Heading", bold=1),
		row("CASH", "货币资金", indent=1),
		row("TRADING_FINANCIAL_ASSETS", "交易性金融资产", indent=1),
		row("DERIVATIVE_FINANCIAL_ASSETS", "衍生金融资产", indent=1),
		row("NOTES_RECEIVABLE", "应收票据", indent=1),
		row("ACCOUNTS_RECEIVABLE", "应收账款", indent=1),
		row("RECEIVABLE_FINANCING", "应收款项融资", indent=1),
		row("PREPAYMENTS", "预付款项", indent=1),
		row("OTHER_RECEIVABLES", "其他应收款", indent=1),
		row("INVENTORIES", "存货", indent=1),
		row("CONTRACT_ASSETS", "合同资产", indent=1),
		row("HELD_FOR_SALE_ASSETS", "持有待售资产", indent=1),
		row("CURRENT_ASSETS_DUE_WITHIN_ONE_YEAR", "一年内到期的非流动资产", indent=1),
		row("OTHER_CURRENT_ASSETS", "其他流动资产", indent=1),
		row("CURRENT_ASSETS", "流动资产合计", "Formula", "CASH + TRADING_FINANCIAL_ASSETS + DERIVATIVE_FINANCIAL_ASSETS + NOTES_RECEIVABLE + ACCOUNTS_RECEIVABLE + RECEIVABLE_FINANCING + PREPAYMENTS + OTHER_RECEIVABLES + INVENTORIES + CONTRACT_ASSETS + HELD_FOR_SALE_ASSETS + CURRENT_ASSETS_DUE_WITHIN_ONE_YEAR + OTHER_CURRENT_ASSETS", bold=1),
		row("NONCURRENT_ASSETS_HEADING", "非流动资产", "Heading", bold=1),
		row("DEBT_INVESTMENTS", "债权投资", indent=1),
		row("OTHER_DEBT_INVESTMENTS", "其他债权投资", indent=1),
		row("LONG_TERM_RECEIVABLES", "长期应收款", indent=1),
		row("LONG_TERM_EQUITY_INVESTMENTS", "长期股权投资", indent=1),
		row("OTHER_EQUITY_INSTRUMENTS", "其他权益工具投资", indent=1),
		row("OTHER_NONCURRENT_FINANCIAL_ASSETS", "其他非流动金融资产", indent=1),
		row("INVESTMENT_PROPERTY", "投资性房地产", indent=1),
		row("FIXED_ASSETS", "固定资产", indent=1),
		row("CONSTRUCTION_IN_PROGRESS", "在建工程", indent=1),
		row("RIGHT_OF_USE_ASSETS", "使用权资产", indent=1),
		row("INTANGIBLE_ASSETS", "无形资产", indent=1),
		row("DEVELOPMENT_EXPENDITURE", "开发支出", indent=1),
		row("GOODWILL", "商誉", indent=1),
		row("LONG_TERM_DEFERRED_EXPENSES", "长期待摊费用", indent=1),
		row("DEFERRED_TAX_ASSETS", "递延所得税资产", indent=1),
		row("OTHER_NONCURRENT_ASSETS", "其他非流动资产", indent=1),
		row("NONCURRENT_ASSETS", "非流动资产合计", "Formula", "DEBT_INVESTMENTS + OTHER_DEBT_INVESTMENTS + LONG_TERM_RECEIVABLES + LONG_TERM_EQUITY_INVESTMENTS + OTHER_EQUITY_INSTRUMENTS + OTHER_NONCURRENT_FINANCIAL_ASSETS + INVESTMENT_PROPERTY + FIXED_ASSETS + CONSTRUCTION_IN_PROGRESS + RIGHT_OF_USE_ASSETS + INTANGIBLE_ASSETS + DEVELOPMENT_EXPENDITURE + GOODWILL + LONG_TERM_DEFERRED_EXPENSES + DEFERRED_TAX_ASSETS + OTHER_NONCURRENT_ASSETS", bold=1),
		row("TOTAL_ASSETS", "资产总计", "Formula", "CURRENT_ASSETS + NONCURRENT_ASSETS", bold=1),
		row("CURRENT_LIABILITIES_HEADING", "流动负债", "Heading", direction="Credit Positive", bold=1),
		row("SHORT_TERM_BORROWINGS", "短期借款", direction="Credit Positive", indent=1),
		row("TRADING_FINANCIAL_LIABILITIES", "交易性金融负债", direction="Credit Positive", indent=1),
		row("DERIVATIVE_FINANCIAL_LIABILITIES", "衍生金融负债", direction="Credit Positive", indent=1),
		row("NOTES_PAYABLE", "应付票据", direction="Credit Positive", indent=1),
		row("ACCOUNTS_PAYABLE", "应付账款", direction="Credit Positive", indent=1),
		row("ADVANCES_FROM_CUSTOMERS", "预收款项", direction="Credit Positive", indent=1),
		row("CONTRACT_LIABILITIES", "合同负债", direction="Credit Positive", indent=1),
		row("EMPLOYEE_BENEFITS_PAYABLE", "应付职工薪酬", direction="Credit Positive", indent=1),
		row("TAXES_PAYABLE", "应交税费", direction="Credit Positive", indent=1),
		row("OTHER_PAYABLES", "其他应付款", direction="Credit Positive", indent=1),
		row("HELD_FOR_SALE_LIABILITIES", "持有待售负债", direction="Credit Positive", indent=1),
		row("NONCURRENT_LIABILITIES_DUE_WITHIN_ONE_YEAR", "一年内到期的非流动负债", direction="Credit Positive", indent=1),
		row("OTHER_CURRENT_LIABILITIES", "其他流动负债", direction="Credit Positive", indent=1),
		row("CURRENT_LIABILITIES", "流动负债合计", "Formula", "SHORT_TERM_BORROWINGS + TRADING_FINANCIAL_LIABILITIES + DERIVATIVE_FINANCIAL_LIABILITIES + NOTES_PAYABLE + ACCOUNTS_PAYABLE + ADVANCES_FROM_CUSTOMERS + CONTRACT_LIABILITIES + EMPLOYEE_BENEFITS_PAYABLE + TAXES_PAYABLE + OTHER_PAYABLES + HELD_FOR_SALE_LIABILITIES + NONCURRENT_LIABILITIES_DUE_WITHIN_ONE_YEAR + OTHER_CURRENT_LIABILITIES", "Credit Positive", bold=1),
		row("NONCURRENT_LIABILITIES_HEADING", "非流动负债", "Heading", direction="Credit Positive", bold=1),
		row("LONG_TERM_BORROWINGS", "长期借款", direction="Credit Positive", indent=1),
		row("BONDS_PAYABLE", "应付债券", direction="Credit Positive", indent=1),
		row("LEASE_LIABILITIES", "租赁负债", direction="Credit Positive", indent=1),
		row("LONG_TERM_PAYABLES", "长期应付款", direction="Credit Positive", indent=1),
		row("LONG_TERM_EMPLOYEE_BENEFITS", "长期应付职工薪酬", direction="Credit Positive", indent=1),
		row("PROVISIONS", "预计负债", direction="Credit Positive", indent=1),
		row("DEFERRED_INCOME", "递延收益", direction="Credit Positive", indent=1),
		row("DEFERRED_TAX_LIABILITIES", "递延所得税负债", direction="Credit Positive", indent=1),
		row("OTHER_NONCURRENT_LIABILITIES", "其他非流动负债", direction="Credit Positive", indent=1),
		row("NONCURRENT_LIABILITIES", "非流动负债合计", "Formula", "LONG_TERM_BORROWINGS + BONDS_PAYABLE + LEASE_LIABILITIES + LONG_TERM_PAYABLES + LONG_TERM_EMPLOYEE_BENEFITS + PROVISIONS + DEFERRED_INCOME + DEFERRED_TAX_LIABILITIES + OTHER_NONCURRENT_LIABILITIES", "Credit Positive", bold=1),
		row("TOTAL_LIABILITIES", "负债合计", "Formula", "CURRENT_LIABILITIES + NONCURRENT_LIABILITIES", "Credit Positive", bold=1),
		row("EQUITY_HEADING", "所有者权益", "Heading", direction="Credit Positive", bold=1),
		row("PAID_IN_CAPITAL", "实收资本（或股本）", direction="Credit Positive", indent=1),
		row("PREFERRED_SHARES", "其他权益工具", direction="Credit Positive", indent=1),
		row("CAPITAL_RESERVE", "资本公积", direction="Credit Positive", indent=1),
		row("TREASURY_SHARES", "减：库存股", direction="Debit Positive", indent=1),
		row("OTHER_COMPREHENSIVE_INCOME", "其他综合收益", direction="Credit Positive", indent=1),
		row("SPECIAL_RESERVE", "专项储备", direction="Credit Positive", indent=1),
		row("SURPLUS_RESERVE", "盈余公积", direction="Credit Positive", indent=1),
		row("RETAINED_EARNINGS", "未分配利润", direction="Credit Positive", indent=1),
		row("OWNERS_EQUITY", "所有者权益合计", "Formula", "PAID_IN_CAPITAL + PREFERRED_SHARES + CAPITAL_RESERVE - TREASURY_SHARES + OTHER_COMPREHENSIVE_INCOME + SPECIAL_RESERVE + SURPLUS_RESERVE + RETAINED_EARNINGS", "Credit Positive", bold=1),
		row("TOTAL_LIABILITIES_EQUITY", "负债和所有者权益总计", "Formula", "TOTAL_LIABILITIES + OWNERS_EQUITY", "Credit Positive", bold=1),
	],
	"Profit and Loss": [
		row("OPERATING_REVENUE", "一、营业收入", direction="Credit Positive", bold=1),
		row("OPERATING_COST", "减：营业成本", indent=1),
		row("TAX_SURCHARGES", "税金及附加", indent=1),
		row("SELLING_EXPENSES", "销售费用", indent=1),
		row("ADMIN_EXPENSES", "管理费用", indent=1),
		row("RD_EXPENSES", "研发费用", indent=1),
		row("FINANCE_EXPENSES", "财务费用", indent=1),
		row("OTHER_INCOME", "加：其他收益", direction="Credit Positive", indent=1),
		row("INVESTMENT_INCOME", "投资收益", direction="Credit Positive", indent=1),
		row("FAIR_VALUE_CHANGES", "公允价值变动收益", direction="Credit Positive", indent=1),
		row("CREDIT_IMPAIRMENT_LOSSES", "信用减值损失", direction="Credit Positive", indent=1),
		row("ASSET_IMPAIRMENT_LOSSES", "资产减值损失", direction="Credit Positive", indent=1),
		row("ASSET_DISPOSAL_INCOME", "资产处置收益", direction="Credit Positive", indent=1),
		row("OPERATING_PROFIT", "二、营业利润", "Formula", "OPERATING_REVENUE - OPERATING_COST - TAX_SURCHARGES - SELLING_EXPENSES - ADMIN_EXPENSES - RD_EXPENSES - FINANCE_EXPENSES + OTHER_INCOME + INVESTMENT_INCOME + FAIR_VALUE_CHANGES + CREDIT_IMPAIRMENT_LOSSES + ASSET_IMPAIRMENT_LOSSES + ASSET_DISPOSAL_INCOME", "Credit Positive", bold=1),
		row("NONOPERATING_INCOME", "加：营业外收入", direction="Credit Positive", indent=1),
		row("NONOPERATING_EXPENSE", "减：营业外支出", indent=1),
		row("TOTAL_PROFIT", "三、利润总额", "Formula", "OPERATING_PROFIT + NONOPERATING_INCOME - NONOPERATING_EXPENSE", "Credit Positive", bold=1),
		row("INCOME_TAX", "减：所得税费用", indent=1),
		row("NET_PROFIT", "四、净利润", "Formula", "TOTAL_PROFIT - INCOME_TAX", "Credit Positive", bold=1),
		row("OCI_NOT_RECLASSIFIABLE", "（一）不能重分类进损益的其他综合收益", "Formula", "OCI_DEFINED_BENEFIT + OCI_EQUITY_METHOD_NONRECLASS + OCI_EQUITY_INVESTMENT_FAIR_VALUE + OCI_OWN_CREDIT_RISK", "Credit Positive", bold=1),
		row("OCI_DEFINED_BENEFIT", "1.重新计量设定受益计划变动额", direction="Credit Positive", indent=1),
		row("OCI_EQUITY_METHOD_NONRECLASS", "2.权益法下不能转损益的其他综合收益", direction="Credit Positive", indent=1),
		row("OCI_EQUITY_INVESTMENT_FAIR_VALUE", "3.其他权益工具投资公允价值变动", direction="Credit Positive", indent=1),
		row("OCI_OWN_CREDIT_RISK", "4.企业自身信用风险公允价值变动", direction="Credit Positive", indent=1),
		row("OCI_RECLASSIFIABLE", "（二）将重分类进损益的其他综合收益", "Formula", "OCI_EQUITY_METHOD_RECLASS + OCI_DEBT_INVESTMENT_FAIR_VALUE + OCI_FINANCIAL_RECLASS + OCI_CREDIT_IMPAIRMENT + OCI_CASH_FLOW_HEDGE + OCI_FOREIGN_CURRENCY", "Credit Positive", bold=1),
		row("OCI_EQUITY_METHOD_RECLASS", "1.权益法下可转损益的其他综合收益", direction="Credit Positive", indent=1),
		row("OCI_DEBT_INVESTMENT_FAIR_VALUE", "2.其他债权投资公允价值变动", direction="Credit Positive", indent=1),
		row("OCI_FINANCIAL_RECLASS", "3.金融资产重分类计入其他综合收益的金额", direction="Credit Positive", indent=1),
		row("OCI_CREDIT_IMPAIRMENT", "4.其他债权投资信用减值准备", direction="Credit Positive", indent=1),
		row("OCI_CASH_FLOW_HEDGE", "5.现金流量套期储备", direction="Credit Positive", indent=1),
		row("OCI_FOREIGN_CURRENCY", "6.外币财务报表折算差额", direction="Credit Positive", indent=1),
		row("OTHER_COMPREHENSIVE_INCOME_PL", "五、其他综合收益的税后净额", "Formula", "OCI_NOT_RECLASSIFIABLE + OCI_RECLASSIFIABLE", "Credit Positive", bold=1),
		row("COMPREHENSIVE_INCOME", "六、综合收益总额", "Formula", "NET_PROFIT + OTHER_COMPREHENSIVE_INCOME_PL", "Credit Positive", bold=1),
	],
}


SMALL_ENTERPRISE_ROWS = {
	"Balance Sheet": [
		row("CURRENT_ASSETS_HEADING", "流动资产", "Heading", bold=1),
		row("CASH", "货币资金", indent=1), row("SHORT_TERM_INVESTMENTS", "短期投资", indent=1),
		row("NOTES_RECEIVABLE", "应收票据", indent=1), row("ACCOUNTS_RECEIVABLE", "应收账款", indent=1),
		row("PREPAYMENTS", "预付账款", indent=1), row("DIVIDENDS_RECEIVABLE", "应收股利", indent=1),
		row("INTEREST_RECEIVABLE", "应收利息", indent=1), row("OTHER_RECEIVABLES", "其他应收款", indent=1),
		row("INVENTORIES", "存货", "Formula", "RAW_MATERIALS + WORK_IN_PROGRESS + FINISHED_GOODS + TURNOVER_MATERIALS - INVENTORY_PROVISION", indent=1), row("RAW_MATERIALS", "其中：原材料", indent=2),
		row("WORK_IN_PROGRESS", "在产品", indent=2), row("FINISHED_GOODS", "库存商品", indent=2),
		row("TURNOVER_MATERIALS", "周转材料", indent=2), row("INVENTORY_PROVISION", "减：存货跌价准备", direction="Credit Positive", indent=2), row("OTHER_CURRENT_ASSETS", "其他流动资产", indent=1),
		row("CURRENT_ASSETS", "流动资产合计", "Formula", "CASH + SHORT_TERM_INVESTMENTS + NOTES_RECEIVABLE + ACCOUNTS_RECEIVABLE + PREPAYMENTS + DIVIDENDS_RECEIVABLE + INTEREST_RECEIVABLE + OTHER_RECEIVABLES + INVENTORIES + OTHER_CURRENT_ASSETS", bold=1),
		row("NONCURRENT_ASSETS_HEADING", "非流动资产", "Heading", bold=1),
		row("LONG_TERM_BOND_INVESTMENTS", "长期债券投资", indent=1), row("LONG_TERM_EQUITY_INVESTMENTS", "长期股权投资", indent=1),
		# Group the statutory fixed-asset rows under one display-only parent.  The
		# heading has no statutory line number and does not affect the formula.
		row("FIXED_ASSETS_HEADING", "固定资产", "Heading", indent=1, bold=1),
		row("FIXED_ASSETS", "固定资产原价", indent=2), row("ACCUMULATED_DEPRECIATION", "减：累计折旧", direction="Credit Positive", indent=2),
		row("FIXED_ASSETS_NET", "固定资产账面价值", "Formula", "FIXED_ASSETS - ACCUMULATED_DEPRECIATION", indent=2),
		row("CONSTRUCTION_IN_PROGRESS", "在建工程", indent=1), row("ENGINEERING_MATERIALS", "工程物资", indent=1),
		row("FIXED_ASSET_DISPOSAL", "固定资产清理", indent=1), row("BIOLOGICAL_ASSETS", "生产性生物资产", indent=1),
		row("INTANGIBLE_ASSETS", "无形资产", indent=1), row("DEVELOPMENT_EXPENDITURE", "开发支出", indent=1),
		row("LONG_TERM_DEFERRED_EXPENSES", "长期待摊费用", indent=1), row("OTHER_NONCURRENT_ASSETS", "其他非流动资产", indent=1),
		row("NONCURRENT_ASSETS", "非流动资产合计", "Formula", "LONG_TERM_BOND_INVESTMENTS + LONG_TERM_EQUITY_INVESTMENTS + FIXED_ASSETS_NET + CONSTRUCTION_IN_PROGRESS + ENGINEERING_MATERIALS + FIXED_ASSET_DISPOSAL + BIOLOGICAL_ASSETS + INTANGIBLE_ASSETS + DEVELOPMENT_EXPENDITURE + LONG_TERM_DEFERRED_EXPENSES + OTHER_NONCURRENT_ASSETS", bold=1),
		row("TOTAL_ASSETS", "资产合计", "Formula", "CURRENT_ASSETS + NONCURRENT_ASSETS", bold=1),
		row("CURRENT_LIABILITIES_HEADING", "流动负债", "Heading", direction="Credit Positive", bold=1),
		row("SHORT_TERM_BORROWINGS", "短期借款", direction="Credit Positive", indent=1), row("NOTES_PAYABLE", "应付票据", direction="Credit Positive", indent=1),
		row("ACCOUNTS_PAYABLE", "应付账款", direction="Credit Positive", indent=1), row("ADVANCES_FROM_CUSTOMERS", "预收账款", direction="Credit Positive", indent=1),
		row("EMPLOYEE_BENEFITS_PAYABLE", "应付职工薪酬", direction="Credit Positive", indent=1), row("TAXES_PAYABLE", "应交税费", direction="Credit Positive", indent=1),
		row("INTEREST_PAYABLE", "应付利息", direction="Credit Positive", indent=1), row("PROFIT_PAYABLE", "应付利润", direction="Credit Positive", indent=1),
		row("OTHER_PAYABLES", "其他应付款", direction="Credit Positive", indent=1), row("OTHER_CURRENT_LIABILITIES", "其他流动负债", direction="Credit Positive", indent=1),
		row("CURRENT_LIABILITIES", "流动负债合计", "Formula", "SHORT_TERM_BORROWINGS + NOTES_PAYABLE + ACCOUNTS_PAYABLE + ADVANCES_FROM_CUSTOMERS + EMPLOYEE_BENEFITS_PAYABLE + TAXES_PAYABLE + INTEREST_PAYABLE + PROFIT_PAYABLE + OTHER_PAYABLES + OTHER_CURRENT_LIABILITIES", "Credit Positive", bold=1),
		row("NONCURRENT_LIABILITIES_HEADING", "非流动负债", "Heading", direction="Credit Positive", bold=1),
		row("LONG_TERM_BORROWINGS", "长期借款", direction="Credit Positive", indent=1), row("LONG_TERM_PAYABLES", "长期应付款", direction="Credit Positive", indent=1),
		row("DEFERRED_INCOME", "递延收益", direction="Credit Positive", indent=1), row("OTHER_NONCURRENT_LIABILITIES", "其他非流动负债", direction="Credit Positive", indent=1),
		row("NONCURRENT_LIABILITIES", "非流动负债合计", "Formula", "LONG_TERM_BORROWINGS + LONG_TERM_PAYABLES + DEFERRED_INCOME + OTHER_NONCURRENT_LIABILITIES", "Credit Positive", bold=1),
		row("TOTAL_LIABILITIES", "负债合计", "Formula", "CURRENT_LIABILITIES + NONCURRENT_LIABILITIES", "Credit Positive", bold=1),
		row("OWNERS_EQUITY_HEADING", "所有者权益（或股东权益）", "Heading", direction="Credit Positive", bold=1),
		row("PAID_IN_CAPITAL", "实收资本（或股本）", direction="Credit Positive", indent=1), row("CAPITAL_RESERVE", "资本公积", direction="Credit Positive", indent=1),
		row("SURPLUS_RESERVE", "盈余公积", direction="Credit Positive", indent=1), row("RETAINED_EARNINGS", "未分配利润", direction="Credit Positive", indent=1),
		row("OWNERS_EQUITY", "所有者权益（或股东权益）合计", "Formula", "PAID_IN_CAPITAL + CAPITAL_RESERVE + SURPLUS_RESERVE + RETAINED_EARNINGS", "Credit Positive", indent=1, bold=1),
		row("TOTAL_LIABILITIES_EQUITY", "负债和所有者权益合计", "Formula", "TOTAL_LIABILITIES + OWNERS_EQUITY", "Credit Positive", bold=1),
	],
	"Profit and Loss": [
		row("OPERATING_REVENUE", "一、营业收入", direction="Credit Positive", bold=1), row("OPERATING_COST", "减：营业成本", indent=1),
		row("TAX_SURCHARGES", "税金及附加", indent=1), row("CONSUMPTION_TAX", "其中：消费税", indent=2),
		row("BUSINESS_TAX", "营业税", indent=2), row("URBAN_MAINTENANCE_TAX", "城市维护建设税", indent=2),
		row("RESOURCE_TAX", "资源税", indent=2), row("LAND_VALUE_ADDED_TAX", "土地增值税", indent=2),
		row("LOCAL_PROPERTY_TAXES", "城镇土地使用税、房产税、车船税、印花税", indent=2),
		row("EDUCATION_SURCHARGES", "教育费附加、矿产资源补偿费、排污费", indent=2),
		row("SELLING_EXPENSES", "销售费用", indent=1), row("PRODUCT_REPAIR_EXPENSES", "其中：商品维修费", indent=2),
		row("ADVERTISING_EXPENSES", "广告费和业务宣传费", indent=2),
		row("ADMIN_EXPENSES", "管理费用", indent=1), row("STARTUP_EXPENSES", "其中：开办费", indent=2),
		row("ENTERTAINMENT_EXPENSES", "业务招待费", indent=2), row("RESEARCH_EXPENSES", "其中：研究费用", indent=2),
		row("FINANCE_EXPENSES", "财务费用", indent=1), row("INTEREST_EXPENSES", "其中：利息费用（收入以“-”号填列）", indent=2),
		row("INVESTMENT_INCOME", "加：投资收益", direction="Credit Positive", indent=1),
		row("OPERATING_PROFIT", "二、营业利润", "Formula", "OPERATING_REVENUE - OPERATING_COST - TAX_SURCHARGES - SELLING_EXPENSES - ADMIN_EXPENSES - FINANCE_EXPENSES + INVESTMENT_INCOME", "Credit Positive", bold=1),
		row("NONOPERATING_INCOME", "加：营业外收入", direction="Credit Positive", indent=1), row("GOVERNMENT_GRANTS", "其中：政府补助", direction="Credit Positive", indent=2),
		row("NONOPERATING_EXPENSE", "减：营业外支出", indent=1), row("BAD_DEBT_LOSSES", "其中：坏账损失", indent=2),
		row("LONG_TERM_BOND_LOSSES", "无法收回的长期债券投资损失", indent=2), row("LONG_TERM_EQUITY_LOSSES", "无法收回的长期股权投资损失", indent=2),
		row("NATURAL_DISASTER_LOSSES", "自然灾害等不可抗力因素造成的损失", indent=2),
		row("TAX_LATE_PAYMENT_PENALTIES", "税收滞纳金", indent=2),
		row("TOTAL_PROFIT", "三、利润总额", "Formula", "OPERATING_PROFIT + NONOPERATING_INCOME - NONOPERATING_EXPENSE", "Credit Positive", bold=1),
		row("INCOME_TAX", "减：所得税费用", indent=1), row("NET_PROFIT", "四、净利润", "Formula", "TOTAL_PROFIT - INCOME_TAX", "Credit Positive", bold=1),
	],
}


CASH_FLOW_ROWS = [
	row("OPERATING_RECEIPTS_HEADING", "一、经营活动产生的现金流量", "Heading", bold=1),
	row("CASH_RECEIVED_SALES", "销售商品、提供劳务收到的现金", indent=1),
	row("TAX_REFUNDS", "收到的税费返还", indent=1), row("OTHER_OPERATING_RECEIPTS", "收到其他与经营活动有关的现金", indent=1),
	row("OPERATING_CASH_RECEIPTS", "经营活动现金流入小计", "Formula", "CASH_RECEIVED_SALES + TAX_REFUNDS + OTHER_OPERATING_RECEIPTS", bold=1),
	row("CASH_PAID_SUPPLIERS", "购买商品、接受劳务支付的现金", indent=1), row("CASH_PAID_EMPLOYEES", "支付给职工以及为职工支付的现金", indent=1),
	row("CASH_PAID_TAXES", "支付的各项税费", indent=1), row("OTHER_OPERATING_PAYMENTS", "支付其他与经营活动有关的现金", indent=1),
	row("OPERATING_CASH_PAYMENTS", "经营活动现金流出小计", "Formula", "CASH_PAID_SUPPLIERS + CASH_PAID_EMPLOYEES + CASH_PAID_TAXES + OTHER_OPERATING_PAYMENTS", bold=1),
	row("OPERATING_CASH_FLOW", "经营活动产生的现金流量净额", "Formula", "OPERATING_CASH_RECEIPTS - OPERATING_CASH_PAYMENTS", bold=1),
	row("INVESTING_RECEIPTS_HEADING", "二、投资活动产生的现金流量", "Heading", bold=1),
	row("CASH_RECEIVED_INVESTMENT_RECOVERY", "收回投资收到的现金", indent=1), row("CASH_RECEIVED_INVESTMENT_INCOME", "取得投资收益收到的现金", indent=1),
	row("CASH_RECEIVED_ASSET_DISPOSAL", "处置固定资产、无形资产和其他长期资产收回的现金净额", indent=1),
	row("CASH_RECEIVED_SUBSIDIARY_DISPOSAL", "处置子公司及其他营业单位收到的现金净额", indent=1),
	row("OTHER_INVESTING_RECEIPTS", "收到其他与投资活动有关的现金", indent=1),
	row("INVESTING_CASH_RECEIPTS", "投资活动现金流入小计", "Formula", "CASH_RECEIVED_INVESTMENT_RECOVERY + CASH_RECEIVED_INVESTMENT_INCOME + CASH_RECEIVED_ASSET_DISPOSAL + CASH_RECEIVED_SUBSIDIARY_DISPOSAL + OTHER_INVESTING_RECEIPTS", bold=1),
	row("CASH_PAID_LONG_TERM_ASSETS", "购建固定资产、无形资产和其他长期资产支付的现金", indent=1), row("CASH_PAID_INVESTMENTS", "投资支付的现金", indent=1),
	row("CASH_PAID_SUBSIDIARY_ACQUISITION", "取得子公司及其他营业单位支付的现金净额", indent=1), row("OTHER_INVESTING_PAYMENTS", "支付其他与投资活动有关的现金", indent=1),
	row("INVESTING_CASH_PAYMENTS", "投资活动现金流出小计", "Formula", "CASH_PAID_LONG_TERM_ASSETS + CASH_PAID_INVESTMENTS + CASH_PAID_SUBSIDIARY_ACQUISITION + OTHER_INVESTING_PAYMENTS", bold=1),
	row("INVESTING_CASH_FLOW", "投资活动产生的现金流量净额", "Formula", "INVESTING_CASH_RECEIPTS - INVESTING_CASH_PAYMENTS", bold=1),
	row("FINANCING_RECEIPTS_HEADING", "三、筹资活动产生的现金流量", "Heading", bold=1),
	row("CASH_RECEIVED_INVESTMENT", "吸收投资收到的现金", indent=1), row("CASH_RECEIVED_BORROWINGS", "取得借款收到的现金", indent=1),
	row("OTHER_FINANCING_RECEIPTS", "收到其他与筹资活动有关的现金", indent=1),
	row("FINANCING_CASH_RECEIPTS", "筹资活动现金流入小计", "Formula", "CASH_RECEIVED_INVESTMENT + CASH_RECEIVED_BORROWINGS + OTHER_FINANCING_RECEIPTS", bold=1),
	row("CASH_PAID_DEBT_REPAYMENT", "偿还债务支付的现金", indent=1), row("CASH_PAID_DIVIDENDS_INTEREST", "分配股利、利润或偿付利息支付的现金", indent=1),
	row("OTHER_FINANCING_PAYMENTS", "支付其他与筹资活动有关的现金", indent=1),
	row("FINANCING_CASH_PAYMENTS", "筹资活动现金流出小计", "Formula", "CASH_PAID_DEBT_REPAYMENT + CASH_PAID_DIVIDENDS_INTEREST + OTHER_FINANCING_PAYMENTS", bold=1),
	row("FINANCING_CASH_FLOW", "筹资活动产生的现金流量净额", "Formula", "FINANCING_CASH_RECEIPTS - FINANCING_CASH_PAYMENTS", bold=1),
	row("FX_EFFECT", "四、汇率变动对现金及现金等价物的影响"),
	row("NET_CASH_INCREASE", "五、现金及现金等价物净增加额", "Formula", "OPERATING_CASH_FLOW + INVESTING_CASH_FLOW + FINANCING_CASH_FLOW + FX_EFFECT", bold=1),
	row("OPENING_CASH", "加：期初现金及现金等价物余额", bold=1), row("CLOSING_CASH", "六、期末现金及现金等价物余额", bold=1),
	row("CASH_RECONCILIATION_DIFFERENCE", "现金流量勾稽差额（应为零）", "Formula", "CLOSING_CASH - OPENING_CASH - NET_CASH_INCREASE", bold=1),
]


ENTERPRISE_EQUITY_ROWS = [
	row("OPENING_EQUITY", "一、上年年末所有者权益余额", direction="Credit Positive", bold=1),
	row("POLICY_CHANGE", "加：会计政策变更", direction="Credit Positive", indent=1), row("ERROR_CORRECTION", "前期差错更正", direction="Credit Positive", indent=1),
	row("CURRENT_OPENING_EQUITY", "二、本年年初所有者权益余额", "Formula", "OPENING_EQUITY + POLICY_CHANGE + ERROR_CORRECTION", "Credit Positive", bold=1),
	row("NET_PROFIT", "净利润", direction="Credit Positive", indent=1), row("OTHER_COMPREHENSIVE", "其他综合收益", direction="Credit Positive", indent=1),
	row("OWNER_CONTRIBUTIONS", "所有者投入资本", direction="Credit Positive", indent=1), row("SHARE_BASED_PAYMENTS", "股份支付计入所有者权益的金额", direction="Credit Positive", indent=1),
	row("PROFIT_DISTRIBUTION", "利润分配", direction="Debit Positive", indent=1), row("SURPLUS_RESERVE_TRANSFER", "提取盈余公积", direction="Debit Positive", indent=1),
	row("DISTRIBUTIONS", "对所有者的分配", direction="Debit Positive", indent=1), row("INTERNAL_EQUITY_TRANSFER", "所有者权益内部结转", direction="Credit Positive", indent=1),
	row("SPECIAL_RESERVE_CHANGE", "专项储备变动", direction="Credit Positive", indent=1), row("OTHER_CHANGES", "其他", direction="Credit Positive", indent=1),
	row("CURRENT_EQUITY_CHANGE", "三、本年增减变动金额", "Formula", "NET_PROFIT + OTHER_COMPREHENSIVE + OWNER_CONTRIBUTIONS + SHARE_BASED_PAYMENTS - PROFIT_DISTRIBUTION - SURPLUS_RESERVE_TRANSFER - DISTRIBUTIONS + INTERNAL_EQUITY_TRANSFER + SPECIAL_RESERVE_CHANGE + OTHER_CHANGES", "Credit Positive", bold=1),
	row("CLOSING_EQUITY", "四、本年年末所有者权益余额", "Formula", "CURRENT_OPENING_EQUITY + CURRENT_EQUITY_CHANGE", "Credit Positive", bold=1),
]


SMALL_EQUITY_ROWS = [
	row("OPENING_EQUITY", "年初所有者权益余额", direction="Credit Positive", bold=1),
	row("NET_PROFIT", "本年净利润", direction="Credit Positive", indent=1), row("OWNER_CONTRIBUTIONS", "所有者投入资本", direction="Credit Positive", indent=1),
	row("DISTRIBUTIONS", "向所有者分配利润", direction="Debit Positive", indent=1), row("OTHER_CHANGES", "其他权益变动", direction="Credit Positive", indent=1),
	row("CLOSING_EQUITY", "年末所有者权益余额", "Formula", "OPENING_EQUITY + NET_PROFIT + OWNER_CONTRIBUTIONS - DISTRIBUTIONS + OTHER_CHANGES", "Credit Positive", bold=1),
]


STATEMENT_ROWS = {
	"企业会计准则": {**ENTERPRISE_ROWS, "Cash Flow": CASH_FLOW_ROWS, "Changes in Equity": ENTERPRISE_EQUITY_ROWS},
	"小企业会计准则": {**SMALL_ENTERPRISE_ROWS, "Cash Flow": CASH_FLOW_ROWS, "Changes in Equity": SMALL_EQUITY_ROWS},
}

STATEMENT_TYPE_LABELS = {
	"Balance Sheet": "资产负债表",
	"Profit and Loss": "利润表",
	"Cash Flow": "现金流量表",
	"Changes in Equity": "所有者权益变动表",
}


def get_template_title(accounting_standard, statement_type, version):
	return f"{accounting_standard} - {STATEMENT_TYPE_LABELS[statement_type]}（{version}）"


def localize_seeded_template_titles():
	"""Translate only titles that were generated by earlier app versions."""
	for template in frappe.get_all(
		"China Financial Statement Template",
		filters={"accounting_standard": ["in", list(STATEMENT_ROWS)]},
		fields=["name", "title", "accounting_standard", "statement_type", "version"],
	):
		legacy_title = f"{template.accounting_standard} - {template.statement_type}"
		if template.title == legacy_title and template.statement_type in STATEMENT_TYPE_LABELS:
			frappe.db.set_value(
				"China Financial Statement Template",
				template.name,
				"title",
				get_template_title(template.accounting_standard, template.statement_type, template.version),
				update_modified=False,
			)


def seed_statement_templates():
	if not frappe.db.exists("DocType", "China Financial Statement Template"):
		return
	localize_seeded_template_titles()
	for standard, statements in STATEMENT_ROWS.items():
		version = get_seed_version(standard)
		for statement_type, rows in statements.items():
			retire_previous_template_versions(standard, statement_type)
			template_key = f"{standard}|{statement_type}|{version}"
			if frappe.db.exists("China Financial Statement Template", template_key):
				continue
			frappe.get_doc(
				{
					"doctype": "China Financial Statement Template", "template_key": template_key,
					"title": get_template_title(standard, statement_type, version), "accounting_standard": standard,
					"statement_type": statement_type, "version": version,
					"effective_from": TEMPLATE_EFFECTIVE_FROM, "is_active": 1,
					"rows": build_seed_rows(rows),
				}
			).insert(ignore_permissions=True)


def build_seed_rows(rows):
	line_number = 0
	result = []
	for code, label, row_type, formula, direction, indent, bold in rows:
		if row_type != "Heading":
			line_number += 1
		result.append({
			"row_code": code, "statutory_line_number": str(line_number) if row_type != "Heading" else None,
			"label": label, "row_type": row_type, "formula": formula,
			"balance_direction": direction, "is_child": int(bool(indent)), "indent": indent,
			"bold": bold, "show_zero": 1,
		})
	return result


def refresh_enterprise_v3_templates():
	"""Finish the registered 3.0 definition before it has produced an immutable snapshot."""
	for statement_type, rows in STATEMENT_ROWS["企业会计准则"].items():
		name = frappe.db.get_value(
			"China Financial Statement Template",
			{"accounting_standard": "企业会计准则", "statement_type": statement_type, "version": "3.0"}, "name",
		)
		if not name or frappe.db.exists("China Report Snapshot", {"template": name}):
			continue
		doc = frappe.get_doc("China Financial Statement Template", name)
		doc.set("rows", build_seed_rows(rows))
		doc.flags.ignore_permissions = True
		doc.save()


def refresh_small_enterprise_v3_templates():
	"""Align small-enterprise v3 rows to the statutory order without losing custom rows."""
	old_fixed_asset_formula = (
		"LONG_TERM_BOND_INVESTMENTS + LONG_TERM_EQUITY_INVESTMENTS + FIXED_ASSETS "
		"- ACCUMULATED_DEPRECIATION + CONSTRUCTION_IN_PROGRESS + INTANGIBLE_ASSETS "
		"+ DEVELOPMENT_EXPENDITURE + LONG_TERM_DEFERRED_EXPENSES + OTHER_NONCURRENT_ASSETS"
	)
	new_fixed_asset_formula = (
		"LONG_TERM_BOND_INVESTMENTS + LONG_TERM_EQUITY_INVESTMENTS + FIXED_ASSETS_NET "
		"+ CONSTRUCTION_IN_PROGRESS + ENGINEERING_MATERIALS + FIXED_ASSET_DISPOSAL "
		"+ BIOLOGICAL_ASSETS + INTANGIBLE_ASSETS + DEVELOPMENT_EXPENDITURE "
		"+ LONG_TERM_DEFERRED_EXPENSES + OTHER_NONCURRENT_ASSETS"
	)
	new_inventory_formula = "RAW_MATERIALS + WORK_IN_PROGRESS + FINISHED_GOODS + TURNOVER_MATERIALS - INVENTORY_PROVISION"
	for statement_type, rows in STATEMENT_ROWS["小企业会计准则"].items():
		name = frappe.db.get_value(
			"China Financial Statement Template",
			{"accounting_standard": "小企业会计准则", "statement_type": statement_type, "version": "3.0"}, "name",
		)
		if not name or frappe.db.exists("China Report Snapshot", {"template": name}):
			continue
		doc = frappe.get_doc("China Financial Statement Template", name)
		seed_rows = build_seed_rows(rows)
		existing = {row.row_code: row for row in doc.rows}
		ordered_rows = []
		changed = False
		for row_data in seed_rows:
			row = existing.get(row_data["row_code"])
			if row:
				if any(row.get(field) != value for field, value in row_data.items() if field not in {"name", "parent", "parentfield", "parenttype"}):
					# Only synchronize structural metadata; user-entered labels/formulas remain intact.
					for field in ("statutory_line_number", "row_type", "is_child", "indent", "bold", "show_zero", "label", "formula", "balance_direction"):
						if row.get(field) != row_data[field]:
							row.set(field, row_data[field])
							changed = True
				ordered_rows.append(row)
			else:
				ordered_rows.append(frappe._dict(row_data))
				changed = True
		custom_rows = [row for row in doc.rows if row.row_code not in {item["row_code"] for item in seed_rows}]
		if custom_rows:
			ordered_rows.extend(custom_rows)
		if [row.row_code for row in doc.rows] != [row.row_code if hasattr(row, "row_code") else row["row_code"] for row in ordered_rows]:
			changed = True
		if statement_type == "Balance Sheet":
			for row in ordered_rows:
				if row.row_code == "NONCURRENT_ASSETS" and row.formula == old_fixed_asset_formula:
					row.formula = new_fixed_asset_formula
					changed = True
				if row.row_code == "INVENTORIES" and row.formula != new_inventory_formula:
					row.formula = new_inventory_formula
					changed = True
		if changed:
			# Rebuild the child table through Frappe's API so newly added child rows
			# receive parent metadata and are persisted correctly.
			doc.set("rows", [])
			for row in ordered_rows:
				as_dict = getattr(row, "as_dict", None)
				values = as_dict() if callable(as_dict) else dict(row)
				for field in ("name", "parent", "parentfield", "parenttype", "idx"):
					values.pop(field, None)
				doc.append("rows", values)
			doc.flags.ignore_permissions = True
			doc.save()


def retire_previous_template_versions(accounting_standard, statement_type):
	"""Keep prior versions queryable for history but close their validity period."""
	cutoff = add_days(getdate(TEMPLATE_EFFECTIVE_FROM), -1)
	for template in frappe.get_all(
		"China Financial Statement Template",
		filters={"accounting_standard": accounting_standard, "statement_type": statement_type, "version": ["!=", TEMPLATE_VERSION]},
		fields=["name", "effective_to"],
	):
		if not template.effective_to or getdate(template.effective_to) >= getdate(TEMPLATE_EFFECTIVE_FROM):
			frappe.db.set_value(
				"China Financial Statement Template", template.name, "effective_to", cutoff, update_modified=False
			)


def ensure_company_mappings():
	if not frappe.db.exists("DocType", "China Finance Settings"):
		return 0
	created = 0
	for settings in frappe.get_all(
		"China Finance Settings", filters={"enabled": 1},
		fields=["company", "accounting_standard", "activation_date", "statutory_reporting_activation_date"]
	):
		effective_from = settings.statutory_reporting_activation_date or settings.activation_date or TEMPLATE_EFFECTIVE_FROM
		created += create_automatic_mappings(settings.company, settings.accounting_standard, effective_from)
		sync_unreviewed_automatic_mappings(settings.company, settings.accounting_standard)
	return created


def sync_unreviewed_automatic_mappings(company, accounting_standard):
	"""Keep suggestions current without changing reviewed or manual accounting decisions."""
	updated = 0
	accounts = {
		row.name: row for row in frappe.get_all(
			"Account", filters={"company": company, "is_group": 0, "disabled": 0},
			fields=["name", "account_name", "account_number", "parent_account", "root_type", "account_type"],
		)
	}
	accounts_by_name = _get_company_account_index(company)
	for statement_type in ("Balance Sheet", "Profit and Loss", "Cash Flow", "Changes in Equity"):
		template = frappe.db.get_value(
			"China Financial Statement Template",
			{"accounting_standard": accounting_standard, "statement_type": statement_type, "version": get_seed_version(accounting_standard)},
			"name",
		)
		if not template:
			continue
		valid_rows = {
			row.row_code: row.row_type for row in frappe.get_cached_doc("China Financial Statement Template", template).rows
		}
		for mapping in frappe.get_all(
			"China Financial Statement Mapping",
			filters={"company": company, "template": template, "mapping_source": "Automatic", "reviewed": 0},
			fields=["name", "account", "row_code", "supplementary_row_code", "cash_inflow_row_code", "cash_outflow_row_code", "account_number_snapshot", "mapping_basis", "mapping_rule_version"],
		):
			account = accounts.get(mapping.account)
			if account and (
				(statement_type == "Cash Flow" and requires_manual_cash_flow_assignment(account.account_number))
				or is_strictly_excluded_from_statement(account.account_number, statement_type)
			):
				frappe.delete_doc("China Financial Statement Mapping", mapping.name, ignore_permissions=True)
				updated += 1
				continue
			classification, _basis = classify_company_account(company, account, statement_type, accounts_by_name) if account else (None, None)
			classification = refine_classification_for_template(account, statement_type, valid_rows, classification)
			if not classification:
				continue
			if isinstance(classification, tuple):
				row_code, inflow_code, outflow_code = classification
			else:
				row_code, inflow_code, outflow_code = classification, None, None
			if valid_rows.get(row_code) != "Mapped Accounts":
				continue
			values = {
				"row_code": row_code,
				"supplementary_row_code": get_supplementary_row_code(account, statement_type, valid_rows, row_code),
				"account_number_snapshot": account.account_number,
				"mapping_basis": _basis or "Accounting Standard Downgrade",
				"mapping_rule_version": MAPPING_RULE_VERSION,
			}
			if statement_type == "Cash Flow":
				values.update(cash_inflow_row_code=inflow_code, cash_outflow_row_code=outflow_code)
			if any(mapping.get(field) != value for field, value in values.items()):
				frappe.db.set_value("China Financial Statement Mapping", mapping.name, values, update_modified=False)
				updated += 1
	return updated


def sync_statement_row_hierarchy():
	"""Migrate existing template indentation to the editable parent/child control."""
	updated = 0
	for row in frappe.get_all(
		"China Financial Statement Row", fields=["name", "indent", "is_child"], order_by="parent, idx"
	):
		is_child = int(bool(row.indent))
		if int(bool(row.is_child)) != is_child:
			frappe.db.set_value("China Financial Statement Row", row.name, "is_child", is_child, update_modified=False)
			updated += 1
	return updated


def create_automatic_mappings(company, accounting_standard, effective_from):
	created = 0
	accounts = frappe.get_all(
		"Account", filters={"company": company, "is_group": 0, "disabled": 0},
		fields=["name", "account_name", "account_number", "parent_account", "root_type", "account_type"],
	)
	accounts_by_name = _get_company_account_index(company)
	for statement_type in ("Balance Sheet", "Profit and Loss", "Cash Flow", "Changes in Equity"):
		template = frappe.db.get_value(
			"China Financial Statement Template",
			{"accounting_standard": accounting_standard, "statement_type": statement_type, "version": get_seed_version(accounting_standard)}, "name",
		)
		if not template:
			continue
		valid_rows = {row.row_code: row.row_type for row in frappe.get_cached_doc("China Financial Statement Template", template).rows}
		valid_codes = set(valid_rows)
		for account in accounts:
			if (statement_type == "Cash Flow" and requires_manual_cash_flow_assignment(account.account_number)) or is_strictly_excluded_from_statement(account.account_number, statement_type):
				continue
			classification, basis = classify_company_account(company, account, statement_type, accounts_by_name)
			classification = refine_classification_for_template(account, statement_type, valid_codes, classification)
			if not classification:
				continue
			if isinstance(classification, tuple):
				row_code, inflow_code, outflow_code = classification
			else:
				row_code, inflow_code, outflow_code = classification, None, None
			if row_code not in valid_codes and basis != "Account Number" and basis != "Parent Inheritance":
				row_code, inflow_code, outflow_code = fallback_classification(
					account, statement_type, valid_codes, inflow_code, outflow_code
				)
			if not row_code or valid_rows.get(row_code) != "Mapped Accounts":
				continue
			basis = basis or "Accounting Standard Downgrade"
			effective_date = getdate(effective_from)
			mapping_key = f"{company}|{template}|{account.name}|{effective_date}"
			if frappe.db.exists("China Financial Statement Mapping", {"mapping_key": mapping_key}):
				continue
			effective_to = _available_mapping_end(company, template, account.name, effective_date)
			if effective_to is False:
				continue
			frappe.get_doc(
				{
					"doctype": "China Financial Statement Mapping", "mapping_key": mapping_key,
					"company": company, "template": template, "row_code": row_code, "account": account.name,
					"supplementary_row_code": get_supplementary_row_code(account, statement_type, valid_rows, row_code),
					"cash_inflow_row_code": inflow_code, "cash_outflow_row_code": outflow_code,
					"sign_multiplier": "1", "effective_from": effective_date, "effective_to": effective_to,
					"mapping_source": "Automatic", "reviewed": 0,
					"account_number_snapshot": account.account_number,
					"mapping_basis": basis,
				"mapping_rule_version": MAPPING_RULE_VERSION,
				}
			).insert(ignore_permissions=True)
			created += 1
	return created


def _available_mapping_end(company, template, account, effective_from):
	"""Return a non-overlapping end date, or False when already covered."""
	start = getdate(effective_from)
	rows = frappe.get_all(
		"China Financial Statement Mapping",
		filters={"company": company, "template": template, "account": account},
		fields=["effective_from", "effective_to"],
		order_by="effective_from asc",
	)
	for row in rows:
		row_start = getdate(row.effective_from)
		row_end = getdate(row.effective_to) if row.effective_to else None
		if row_start <= start and (not row_end or row_end >= start):
			return False
		if row_start > start:
			return add_days(row_start, -1)
	return None


def seed_cash_equivalent_scope():
	"""Create review-required suggestions; never silently approve statutory cash scope."""
	if not frappe.db.exists("DocType", "China Cash Equivalent Scope"):
		return 0
	created = 0
	for settings in frappe.get_all(
		"China Finance Settings", filters={"enabled": 1}, fields=["company", "activation_date"]
	):
		from china_finance.setup.china_coa_profile import ensure_cash_scope, is_profile_company
		if is_profile_company(settings.company):
			created += ensure_cash_scope(settings.company, settings.activation_date)
			continue
		for account in frappe.get_all(
			"Account",
			filters={"company": settings.company, "is_group": 0, "disabled": 0, "account_type": ["in", ["Cash", "Bank"]]},
			fields=["name", "account_type"],
		):
			key = f"{settings.company}|{account.name}|{settings.activation_date}"
			if frappe.db.exists("China Cash Equivalent Scope", {"scope_key": key}):
				continue
			frappe.get_doc({
				"doctype": "China Cash Equivalent Scope", "scope_key": key,
				"company": settings.company, "account": account.name,
				"classification": "库存现金" if account.account_type == "Cash" else "随时可用存款",
				"included": 1, "effective_from": settings.activation_date,
				"policy_basis": "按 ERPNext 科目类型自动建议，须由财务人员复核可随时支用性及受限情况。",
				"reviewed": 0,
			}).insert(ignore_permissions=True)
			created += 1
	return created


def sync_automatic_cash_flow_mappings(company, accounting_standard):
	"""Refresh only unreviewed automatic cash-flow mappings after classification improvements."""
	template = frappe.db.get_value(
		"China Financial Statement Template",
		{"accounting_standard": accounting_standard, "statement_type": "Cash Flow", "version": TEMPLATE_VERSION},
		"name",
	)
	if not template:
		return 0
	accounts = {
		row.name: row
		for row in frappe.get_all(
			"Account", filters={"company": company, "is_group": 0, "disabled": 0},
			fields=["name", "account_name", "account_number", "parent_account", "root_type", "account_type"],
		)
	}
	accounts_by_name = _get_company_account_index(company)
	updated = 0
	for mapping in frappe.get_all(
		"China Financial Statement Mapping",
		filters={"company": company, "template": template, "mapping_source": "Automatic", "reviewed": 0},
		fields=["name", "account", "row_code", "cash_inflow_row_code", "cash_outflow_row_code", "mapping_rule_version"],
	):
		account = accounts.get(mapping.account)
		if not account:
			continue
		if requires_manual_cash_flow_assignment(account.account_number):
			frappe.delete_doc("China Financial Statement Mapping", mapping.name, ignore_permissions=True)
			updated += 1
			continue
		classification, _basis = classify_company_account(company, account, "Cash Flow", accounts_by_name)
		if not classification:
			continue
		row_code, inflow_code, outflow_code = classification
		values = {
			"row_code": row_code,
			"cash_inflow_row_code": inflow_code,
			"cash_outflow_row_code": outflow_code,
			"mapping_rule_version": MAPPING_RULE_VERSION,
		}
		if any(mapping.get(fieldname) != value for fieldname, value in values.items()):
			frappe.db.set_value("China Financial Statement Mapping", mapping.name, values, update_modified=False)
			updated += 1
	return updated


def classify_company_account(company, account, statement_type, accounts_by_name=None):
	"""Use the numbered China profile first; preserve legacy classification for all other charts."""
	if not account:
		return None, None
	from china_finance.setup.china_coa_profile import get_profile_account_numbers, is_profile_company

	if not is_profile_company(company):
		return classify_account(account, statement_type), "Attribute Fallback"
	if (statement_type == "Cash Flow" and requires_manual_cash_flow_assignment(account.account_number)) or is_strictly_excluded_from_statement(account.account_number, statement_type):
		return None, None
	classification = classify_account_number(str(account.account_number or ""), statement_type, account)
	if classification:
		return classification, "Account Number"
	accounts_by_name = accounts_by_name or {}
	parent = accounts_by_name.get(account.parent_account)
	visited = set()
	while parent and parent.name not in visited:
		visited.add(parent.name)
		classification = classify_account_number(str(parent.account_number or ""), statement_type, parent)
		if classification:
			return classification, "Parent Inheritance"
		parent = accounts_by_name.get(parent.parent_account)
	if str(account.account_number or "") in get_profile_account_numbers():
		return _classify_known_profile_fallback(account, statement_type), "Account Number"
	return None, None


def _get_company_account_index(company):
	return {
		row.name: row for row in frappe.get_all(
			"Account", filters={"company": company, "disabled": 0},
			fields=["name", "account_name", "account_number", "parent_account", "root_type", "account_type", "is_group"],
		)
	}


def _classify_known_profile_fallback(account, statement_type):
	"""Classify only known template numbers; unknown company additions remain pending."""
	if statement_type == "Cash Flow":
		if account.account_type in {"Cash", "Bank"}:
			return None
		if account.root_type == "Equity":
			return ("OTHER_FINANCING_RECEIPTS", "OTHER_FINANCING_RECEIPTS", "OTHER_FINANCING_PAYMENTS")
		return ("OTHER_OPERATING_RECEIPTS", "OTHER_OPERATING_RECEIPTS", "OTHER_OPERATING_PAYMENTS")
	if statement_type == "Changes in Equity" and account.root_type == "Equity":
		return "OTHER_CHANGES"
	return None


def refine_classification_for_template(account, statement_type, valid_rows, classification):
	"""Use small-enterprise statutory detail rows when the selected template has them."""
	if not account:
		return classification
	number = str(account.account_number or "")
	name = account.account_name or account.name or ""
	if statement_type == "Balance Sheet":
		# The small-enterprise form does not expose several enterprise-chart
		# headings.  Put their leaf accounts into the closest statutory line so
		# they are not silently omitted from the balance sheet.  This branch is
		# deliberately gated by FIXED_ASSETS_NET, which only exists in the small
		# enterprise template.
		if "FIXED_ASSETS_NET" in valid_rows:
			small_special = (
				(("1321", "1407"), "FINISHED_GOODS"),
				(("1501", "1502"), "LONG_TERM_BOND_INVESTMENTS"),
				(("1503", "1521", "1531", "1532", "1711", "1811", "3101", "3201", "3202"), "OTHER_NONCURRENT_ASSETS"),
				(("2101",), "OTHER_CURRENT_LIABILITIES"),
				(("2314",), "OTHER_PAYABLES"),
				(("2401",), "DEFERRED_INCOME"),
				(("2502", "2801", "2901"), "OTHER_NONCURRENT_LIABILITIES"),
			)
			for prefixes, row_code in small_special:
				if number.startswith(prefixes) and row_code in valid_rows:
					return row_code
			# In this chart 1622 is used for accumulated depreciation of
			# productive biological assets, not for right-of-use assets.
			if number.startswith("1622") and "生产性生物资产" in name and "BIOLOGICAL_ASSETS" in valid_rows:
				return "BIOLOGICAL_ASSETS"
		if not classification:
			return classification
		# Small-enterprise templates intentionally collapse several enterprise
		# presentation lines.  Keep this downgrade explicit and auditable.
		if "SHORT_TERM_INVESTMENTS" in valid_rows and number.startswith("1101"):
			return "SHORT_TERM_INVESTMENTS"
		if (
			"ADVANCES_FROM_CUSTOMERS" in valid_rows
			and "CONTRACT_LIABILITIES" not in valid_rows
			and number.startswith("2204")
		):
			return "ADVANCES_FROM_CUSTOMERS"
		if (
			"OTHER_NONCURRENT_ASSETS" in valid_rows
			and "RIGHT_OF_USE_ASSETS" not in valid_rows
			and number.startswith("1622")
		):
			return "OTHER_NONCURRENT_ASSETS"
		if "LONG_TERM_PAYABLES" in valid_rows and number.startswith(("2703", "2802")):
			return "LONG_TERM_PAYABLES"
		detailed = {
			"1131": "DIVIDENDS_RECEIVABLE", "1132": "INTEREST_RECEIVABLE",
			"1501": "LONG_TERM_BOND_INVESTMENTS", "1502": "LONG_TERM_BOND_INVESTMENTS",
			"1511": "LONG_TERM_EQUITY_INVESTMENTS", "1512": "LONG_TERM_EQUITY_INVESTMENTS",
			"1471": "INVENTORY_PROVISION", "1602": "ACCUMULATED_DEPRECIATION", "160201": "ACCUMULATED_DEPRECIATION", "160202": "ACCUMULATED_DEPRECIATION", "160203": "ACCUMULATED_DEPRECIATION", "1605": "ENGINEERING_MATERIALS",
			"1606": "FIXED_ASSET_DISPOSAL", "1621": "BIOLOGICAL_ASSETS",
			"2231": "INTEREST_PAYABLE", "2232": "PROFIT_PAYABLE",
		}
		row_code = detailed.get(number)
		if not row_code:
			if number.startswith(("1401", "1402", "1403", "1404")) or "原材料" in name:
				row_code = "RAW_MATERIALS"
			elif number.startswith(("5001", "5101", "5201")) or "生产成本" in name or "在产品" in name:
				row_code = "WORK_IN_PROGRESS"
			elif number in {"1405", "1406", "1408"} or any(word in name for word in ("库存商品", "产成品", "委托加工物资")):
				row_code = "FINISHED_GOODS"
			elif number.startswith("1411") or "周转材料" in name or "低值易耗品" in name:
				row_code = "TURNOVER_MATERIALS"
		if row_code and row_code in valid_rows:
			return row_code
	if statement_type == "Profit and Loss":
		row_code = None
		if (
			number.startswith("6101")
			and "INVESTMENT_INCOME" in valid_rows
			and "FAIR_VALUE_CHANGES" not in valid_rows
		):
			row_code = "INVESTMENT_INCOME"
		elif (
			number.startswith(("6115", "6117", "6201", "6301"))
			and "NONOPERATING_INCOME" in valid_rows
			and "OTHER_INCOME" not in valid_rows
			and "ASSET_DISPOSAL_INCOME" not in valid_rows
		):
			row_code = "NONOPERATING_INCOME"
		elif (
			number.startswith(("6701", "6702"))
			and "NONOPERATING_EXPENSE" in valid_rows
			and "ASSET_IMPAIRMENT_LOSSES" not in valid_rows
		):
			row_code = "NONOPERATING_EXPENSE"
		if number.startswith("6403"):
			if "消费税" in name:
				row_code = "CONSUMPTION_TAX"
			elif "营业税" in name:
				row_code = "BUSINESS_TAX"
			elif "城市维护" in name:
				row_code = "URBAN_MAINTENANCE_TAX"
			elif "资源税" in name:
				row_code = "RESOURCE_TAX"
			elif "土地增值税" in name:
				row_code = "LAND_VALUE_ADDED_TAX"
			elif any(word in name for word in ("土地使用税", "房产税", "车船税", "印花税")):
				row_code = "LOCAL_PROPERTY_TAXES"
			elif any(word in name for word in ("教育费附加", "矿产资源补偿", "排污费")):
				row_code = "EDUCATION_SURCHARGES"
		if number.startswith("6601"):
			if "维修" in name:
				row_code = "PRODUCT_REPAIR_EXPENSES"
			elif any(word in name for word in ("广告", "业务宣传")):
				row_code = "ADVERTISING_EXPENSES"
		if number.startswith("6602") and "开办" in name:
			row_code = "STARTUP_EXPENSES"
		if number.startswith("6602") and "招待" in name:
			row_code = "ENTERTAINMENT_EXPENSES"
		if number.startswith(("660206", "530101")) or any(word in name for word in ("研发", "研究")):
			row_code = "ADMIN_EXPENSES"
		if number.startswith("6603") and any(word in name for word in ("利息", "Interest")):
			row_code = "INTEREST_EXPENSES"
		if number.startswith("6301") and "政府补助" in name:
			row_code = "GOVERNMENT_GRANTS"
		if number.startswith("6711"):
			if "坏账" in name:
				row_code = "BAD_DEBT_LOSSES"
			elif "长期债券" in name:
				row_code = "LONG_TERM_BOND_LOSSES"
			elif "长期股权" in name:
				row_code = "LONG_TERM_EQUITY_LOSSES"
			elif "自然灾害" in name or "不可抗力" in name:
				row_code = "NATURAL_DISASTER_LOSSES"
			elif "滞纳金" in name:
				row_code = "TAX_LATE_PAYMENT_PENALTIES"
		if row_code and row_code in valid_rows:
			return row_code
	if statement_type == "Changes in Equity" and "CLOSING_EQUITY" in valid_rows:
		# The small-enterprise equity form has no separate rows for OCI or the
		# detailed profit-distribution subaccounts.  Preserve their movements in
		# the available equity-change lines; direct owner distributions remain a
		# separate line.
		if number.startswith("4003") and "OTHER_CHANGES" in valid_rows:
			return "OTHER_CHANGES"
		if number.startswith("4104"):
			if number.startswith(("410404", "410410")) and "DISTRIBUTIONS" in valid_rows:
				return "DISTRIBUTIONS"
			if "OTHER_CHANGES" in valid_rows:
				return "OTHER_CHANGES"
	return classification


def get_supplementary_row_code(account, statement_type, valid_rows, row_code):
	"""Return a disclosure-only detail row without duplicating the statement total.

	Small-enterprise research expenditure is included in management expenses, while
	the statutory form also requires an 'of which: research expenses' disclosure.
	The primary mapping remains ADMIN_EXPENSES and this field is rendered outside
	the parent formula.
	"""
	if statement_type != "Profit and Loss" or "RESEARCH_EXPENSES" not in valid_rows:
		return None
	number = str(account.account_number or "")
	name = account.account_name or account.name or ""
	if row_code == "ADMIN_EXPENSES" and (number.startswith(("660206", "530101")) or any(word in name for word in ("研发", "研究"))):
		return "RESEARCH_EXPENSES"
	if row_code == "NONOPERATING_INCOME" and number.startswith("6201") and "GOVERNMENT_GRANTS" in valid_rows:
		return "GOVERNMENT_GRANTS"
	return None


def classify_account_number(number, statement_type, account=None):
	if not number:
		return None
	if statement_type == "Balance Sheet":
		return _classify_balance_sheet_number(number)
	if statement_type == "Profit and Loss":
		return _classify_profit_loss_number(number)
	if statement_type == "Changes in Equity":
		if number == "4001": return "OWNER_CONTRIBUTIONS"
		if number.startswith("4002"): return "OWNER_CONTRIBUTIONS"
		if number.startswith("4003"): return "OTHER_COMPREHENSIVE"
		if number == "4103": return "NET_PROFIT"
		if number.startswith("410402"): return "SURPLUS_RESERVE_TRANSFER"
		if number.startswith("410403"): return "DISTRIBUTIONS"
		if number.startswith("4104"): return "PROFIT_DISTRIBUTION"
		if number.startswith("6901"): return "ERROR_CORRECTION"
		if number.startswith(("4101", "4201", "999901")): return "OTHER_CHANGES"
		return None
	if statement_type == "Cash Flow":
		if account and account.account_type in {"Cash", "Bank"}: return None
		if number.startswith(("6001", "6051", "1122", "1123", "1121", "2203", "2204")):
			return ("CASH_RECEIVED_SALES", "CASH_RECEIVED_SALES", "OTHER_OPERATING_PAYMENTS")
		if number.startswith("1101"):
			return ("CASH_PAID_INVESTMENTS", "CASH_RECEIVED_INVESTMENT_RECOVERY", "CASH_PAID_INVESTMENTS")
		if number.startswith("6115"):
			return ("CASH_RECEIVED_ASSET_DISPOSAL", "CASH_RECEIVED_ASSET_DISPOSAL", "OTHER_INVESTING_PAYMENTS")
		if number.startswith(("4001", "4002")):
			return ("CASH_RECEIVED_INVESTMENT", "CASH_RECEIVED_INVESTMENT", "OTHER_FINANCING_PAYMENTS")
		if number.startswith(("500101", "500104", "510103", "510104", "5201")):
			return ("CASH_PAID_SUPPLIERS", "OTHER_OPERATING_RECEIPTS", "CASH_PAID_SUPPLIERS")
		if number.startswith(("500102", "510101")):
			return ("CASH_PAID_EMPLOYEES", "OTHER_OPERATING_RECEIPTS", "CASH_PAID_EMPLOYEES")
		if number.startswith(("500103", "510199")):
			return ("OTHER_OPERATING_PAYMENTS", "OTHER_OPERATING_RECEIPTS", "OTHER_OPERATING_PAYMENTS")
		if number == "5101":
			return ("OTHER_OPERATING_PAYMENTS", "OTHER_OPERATING_RECEIPTS", "OTHER_OPERATING_PAYMENTS")
		if number.startswith(("510102", "510105")):
			return None
		if number.startswith(("140", "141", "2201", "2202", "2205", "2206")):
			return ("CASH_PAID_SUPPLIERS", "OTHER_OPERATING_RECEIPTS", "CASH_PAID_SUPPLIERS")
		if number.startswith(("2211",)):
			return ("CASH_PAID_EMPLOYEES", "OTHER_OPERATING_RECEIPTS", "CASH_PAID_EMPLOYEES")
		if number.startswith(("222", "6403", "6801")):
			return ("CASH_PAID_TAXES", "TAX_REFUNDS", "CASH_PAID_TAXES")
		if number.startswith(("150", "151", "152")):
			return ("CASH_PAID_INVESTMENTS", "CASH_RECEIVED_INVESTMENT_RECOVERY", "CASH_PAID_INVESTMENTS")
		if number.startswith(("160", "170", "180", "530102")):
			return ("CASH_PAID_LONG_TERM_ASSETS", "CASH_RECEIVED_ASSET_DISPOSAL", "CASH_PAID_LONG_TERM_ASSETS")
		if number.startswith(("2001", "2501", "2502", "2701")):
			return ("CASH_RECEIVED_BORROWINGS", "CASH_RECEIVED_BORROWINGS", "CASH_PAID_DEBT_REPAYMENT")
		if number.startswith(("2231", "2232", "410403", "660301")):
			return ("CASH_PAID_DIVIDENDS_INTEREST", "OTHER_FINANCING_RECEIPTS", "CASH_PAID_DIVIDENDS_INTEREST")
		if number.startswith(("6111", "1131", "1132")):
			return ("CASH_RECEIVED_INVESTMENT_INCOME", "CASH_RECEIVED_INVESTMENT_INCOME", "OTHER_INVESTING_PAYMENTS")
		if number.startswith("6301"):
			return ("OTHER_OPERATING_RECEIPTS", "OTHER_OPERATING_RECEIPTS", "OTHER_OPERATING_PAYMENTS")
		if number.startswith(("660", "670", "6711", "1221", "2241")):
			return ("OTHER_OPERATING_PAYMENTS", "OTHER_OPERATING_RECEIPTS", "OTHER_OPERATING_PAYMENTS")
	return None


def _classify_balance_sheet_number(number):
	if number.startswith(("1001", "1002", "1012")): return "CASH"
	if number.startswith("1101"): return "TRADING_FINANCIAL_ASSETS"
	if number.startswith("1121"): return "NOTES_RECEIVABLE"
	if number.startswith(("1122", "1231")): return "ACCOUNTS_RECEIVABLE"
	if number.startswith("1123"): return "PREPAYMENTS"
	if number.startswith(("1131", "1132", "1221")): return "OTHER_RECEIVABLES"
	if number.startswith(("140", "141", "1471", "500", "510", "5201")): return "INVENTORIES"
	if number.startswith("1125"): return "RECEIVABLE_FINANCING"
	if number.startswith(("1501", "1502")): return "DEBT_INVESTMENTS"
	if number.startswith("1503"): return "OTHER_DEBT_INVESTMENTS"
	if number.startswith(("1511", "1512")): return "LONG_TERM_EQUITY_INVESTMENTS"
	if number.startswith("1521"): return "INVESTMENT_PROPERTY"
	if number.startswith("1531"): return "LONG_TERM_RECEIVABLES"
	if number.startswith(("1601", "1603", "1606")): return "FIXED_ASSETS"
	if number.startswith("1602"): return "ACCUMULATED_DEPRECIATION"
	if number.startswith("1621"): return "BIOLOGICAL_ASSETS"
	if number.startswith("1622"): return "RIGHT_OF_USE_ASSETS"
	if number.startswith(("1604", "1605")): return "CONSTRUCTION_IN_PROGRESS"
	if number.startswith(("1701", "1702", "1703")): return "INTANGIBLE_ASSETS"
	if number.startswith("530102"): return "DEVELOPMENT_EXPENDITURE"
	if number.startswith("1711"): return "GOODWILL"
	if number.startswith("1801"): return "LONG_TERM_DEFERRED_EXPENSES"
	if number.startswith("1811"): return "DEFERRED_TAX_ASSETS"
	if number.startswith("1901"): return "OTHER_CURRENT_ASSETS"
	if number.startswith("2001"): return "SHORT_TERM_BORROWINGS"
	if number.startswith("2101"): return "TRADING_FINANCIAL_LIABILITIES"
	if number.startswith("2201"): return "NOTES_PAYABLE"
	if number.startswith(("2202", "2205", "2206")): return "ACCOUNTS_PAYABLE"
	if number.startswith("2203"): return "ADVANCES_FROM_CUSTOMERS"
	if number.startswith("2204"): return "CONTRACT_LIABILITIES"
	if number.startswith("2211"): return "EMPLOYEE_BENEFITS_PAYABLE"
	if number.startswith("222"): return "TAXES_PAYABLE"
	if number.startswith(("2231", "2232", "2241")): return "OTHER_PAYABLES"
	if number.startswith("2301"): return "DEFERRED_INCOME"
	if number.startswith("2501"): return "LONG_TERM_BORROWINGS"
	if number.startswith("2502"): return "BONDS_PAYABLE"
	if number.startswith(("2701", "2702")): return "LONG_TERM_PAYABLES"
	if number.startswith(("2703", "2802")): return "LEASE_LIABILITIES"
	if number.startswith("2801"): return "PROVISIONS"
	if number.startswith(("2711",)): return "OTHER_NONCURRENT_LIABILITIES"
	if number.startswith("2901"): return "DEFERRED_TAX_LIABILITIES"
	if number.startswith("4001"): return "PAID_IN_CAPITAL"
	if number.startswith("4002"): return "CAPITAL_RESERVE"
	if number.startswith(("4005", "4401")): return "OTHER_EQUITY_INSTRUMENTS"
	if number.startswith("4003"): return "OTHER_COMPREHENSIVE_INCOME"
	if number.startswith("4101"): return "SURPLUS_RESERVE"
	if number.startswith("4102"): return "SPECIAL_RESERVE"
	if number.startswith(("4103", "4104", "999901")): return "RETAINED_EARNINGS"
	if number.startswith("4201"): return "TREASURY_SHARES"
	return None


def _classify_profit_loss_number(number):
	if number.startswith(("6001", "6051")): return "OPERATING_REVENUE"
	if number.startswith("6101"): return "FAIR_VALUE_CHANGES"
	if number.startswith("6111"): return "INVESTMENT_INCOME"
	if number.startswith("6115"): return "ASSET_DISPOSAL_INCOME"
	if number.startswith("6117"): return "OTHER_INCOME"
	if number.startswith("6301"): return "NONOPERATING_INCOME"
	if number.startswith(("6401", "6402", "640199")): return "OPERATING_COST"
	if number.startswith("6403"): return "TAX_SURCHARGES"
	if number.startswith("6601"): return "SELLING_EXPENSES"
	if number.startswith("660206") or number.startswith("530101"): return "RD_EXPENSES"
	if number.startswith("6602"): return "ADMIN_EXPENSES"
	if number.startswith("6603"): return "FINANCE_EXPENSES"
	if number.startswith("6701"): return "ASSET_IMPAIRMENT_LOSSES"
	if number.startswith("6702"): return "CREDIT_IMPAIRMENT_LOSSES"
	if number.startswith("6711"): return "NONOPERATING_EXPENSE"
	if number.startswith("6801"): return "INCOME_TAX"
	return None


def fallback_classification(account, statement_type, valid_codes, inflow_code=None, outflow_code=None):
	if statement_type == "Profit and Loss":
		return ("OPERATING_REVENUE" if account.root_type == "Income" else "ADMIN_EXPENSES"), None, None
	if statement_type == "Balance Sheet":
		if account.root_type == "Asset":
			return ("OTHER_NONCURRENT_ASSETS" if "OTHER_NONCURRENT_ASSETS" in valid_codes else "OTHER_CURRENT_ASSETS"), None, None
		if account.root_type == "Liability":
			return ("OTHER_NONCURRENT_LIABILITIES" if "OTHER_NONCURRENT_LIABILITIES" in valid_codes else "OTHER_CURRENT_LIABILITIES"), None, None
		if account.root_type == "Equity":
			return "RETAINED_EARNINGS", None, None
	if statement_type == "Changes in Equity":
		return "OTHER_CHANGES", None, None
	if statement_type == "Cash Flow":
		return "OTHER_OPERATING_RECEIPTS", inflow_code or "OTHER_OPERATING_RECEIPTS", outflow_code or "OTHER_OPERATING_PAYMENTS"
	return None, None, None


def classify_account(account, statement_type):
	name = account.account_name or account.name
	if statement_type == "Cash Flow":
		if account.account_type in {"Cash", "Bank"}:
			return None
		if account.root_type == "Income":
			if any(word in name for word in ("投资收益", "Interest Income", "应收股利", "应收利息")):
				return ("CASH_RECEIVED_INVESTMENT_INCOME", "CASH_RECEIVED_INVESTMENT_INCOME", "OTHER_INVESTING_PAYMENTS")
			return ("CASH_RECEIVED_SALES", "CASH_RECEIVED_SALES", "OTHER_OPERATING_PAYMENTS")
		if account.root_type == "Expense":
			if any(word in name for word in ("所得税", "Tax Expense")):
				return ("CASH_PAID_TAXES", "TAX_REFUNDS", "CASH_PAID_TAXES")
			if any(word in name for word in ("利息", "Interest Expense")):
				return ("CASH_PAID_DIVIDENDS_INTEREST", "OTHER_FINANCING_RECEIPTS", "CASH_PAID_DIVIDENDS_INTEREST")
			if any(word in name for word in ("职工薪酬", "工资", "薪资", "社保", "公积金")):
				return ("CASH_PAID_EMPLOYEES", "OTHER_OPERATING_RECEIPTS", "CASH_PAID_EMPLOYEES")
			return ("OTHER_OPERATING_PAYMENTS", "OTHER_OPERATING_RECEIPTS", "OTHER_OPERATING_PAYMENTS")
		if account.account_type == "Receivable" or "应收" in name or "合同资产" in name:
			return ("CASH_RECEIVED_SALES", "CASH_RECEIVED_SALES", "OTHER_OPERATING_PAYMENTS")
		if account.account_type in {"Payable", "Stock"} or any(word in name for word in ("应付账款", "存货", "原材料", "库存商品")):
			return ("CASH_PAID_SUPPLIERS", "OTHER_OPERATING_RECEIPTS", "CASH_PAID_SUPPLIERS")
		if account.account_type in {"Fixed Asset", "Capital Work in Progress", "Intangible Asset"} or any(word in name for word in ("固定资产", "在建工程", "无形资产")):
			return ("CASH_PAID_LONG_TERM_ASSETS", "CASH_RECEIVED_ASSET_DISPOSAL", "CASH_PAID_LONG_TERM_ASSETS")
		if account.root_type == "Equity":
			return ("CASH_RECEIVED_INVESTMENT", "CASH_RECEIVED_INVESTMENT", "CASH_PAID_DIVIDENDS_INTEREST")
		if any(word in name for word in ("借款", "借贷", "贷款", "应付债券", "租赁负债")):
			return ("CASH_RECEIVED_BORROWINGS", "CASH_RECEIVED_BORROWINGS", "CASH_PAID_DEBT_REPAYMENT")
		if account.account_type == "Tax" or "应交税" in name or "所得税" in name:
			return ("CASH_PAID_TAXES", "TAX_REFUNDS", "CASH_PAID_TAXES")
		if any(word in name for word in ("职工薪酬", "工资", "薪资", "社保", "公积金")):
			return ("CASH_PAID_EMPLOYEES", "OTHER_OPERATING_RECEIPTS", "CASH_PAID_EMPLOYEES")
		if any(word in name for word in ("投资收益", "应收股利", "应收利息")):
			return ("CASH_RECEIVED_INVESTMENT_INCOME", "CASH_RECEIVED_INVESTMENT_INCOME", "OTHER_INVESTING_PAYMENTS")
		if "投资" in name:
			return ("CASH_PAID_INVESTMENTS", "CASH_RECEIVED_INVESTMENT_RECOVERY", "CASH_PAID_INVESTMENTS")
		return ("OTHER_OPERATING_RECEIPTS", "OTHER_OPERATING_RECEIPTS", "OTHER_OPERATING_PAYMENTS")
	if statement_type == "Changes in Equity":
		if account.root_type == "Income" or account.root_type == "Expense" or "本年利润" in name:
			return "NET_PROFIT"
		if account.root_type != "Equity":
			return None
		if any(word in name for word in ("实收资本", "股本")):
			return "OWNER_CONTRIBUTIONS"
		if "其他综合收益" in name:
			return "OTHER_COMPREHENSIVE"
		if "专项储备" in name:
			return "SPECIAL_RESERVE_CHANGE"
		if any(word in name for word in ("利润分配", "应付股利")):
			return "DISTRIBUTIONS"
		return "OTHER_CHANGES"
	if statement_type == "Balance Sheet":
		return classify_balance_sheet_account(account, name)
	return classify_profit_loss_account(account, name)


def classify_balance_sheet_account(account, name):
	rules = (
		("CASH", ("现金", "库存现金", "银行存款", "货币资金")), ("NOTES_RECEIVABLE", ("应收票据",)),
		("ACCOUNTS_RECEIVABLE", ("应收账款",)), ("PREPAYMENTS", ("预付",)),
		("OTHER_RECEIVABLES", ("其他应收",)), ("INVENTORIES", ("存货", "原材料", "库存商品", "在产品", "委托加工")),
		("CONTRACT_ASSETS", ("合同资产",)), ("LONG_TERM_EQUITY_INVESTMENTS", ("长期股权投资",)),
		("FIXED_ASSETS", ("固定资产",)), ("CONSTRUCTION_IN_PROGRESS", ("在建工程",)),
		("RIGHT_OF_USE_ASSETS", ("使用权资产",)), ("INTANGIBLE_ASSETS", ("无形资产",)),
		("DEVELOPMENT_EXPENDITURE", ("开发支出",)), ("DEFERRED_TAX_ASSETS", ("递延所得税资产",)),
		("SHORT_TERM_BORROWINGS", ("短期借款",)), ("NOTES_PAYABLE", ("应付票据",)),
		("ACCOUNTS_PAYABLE", ("应付账款",)), ("ADVANCES_FROM_CUSTOMERS", ("预收",)),
		("CONTRACT_LIABILITIES", ("合同负债",)), ("LONG_TERM_EMPLOYEE_BENEFITS", ("长期应付职工薪酬",)),
		("EMPLOYEE_BENEFITS_PAYABLE", ("应付职工薪酬",)),
		("TAXES_PAYABLE", ("应交税",)), ("OTHER_PAYABLES", ("其他应付",)),
		("LONG_TERM_BORROWINGS", ("长期借款",)), ("LEASE_LIABILITIES", ("租赁负债",)),
		("DEFERRED_INCOME", ("递延收益",)), ("DEFERRED_TAX_LIABILITIES", ("递延所得税负债",)),
		("PAID_IN_CAPITAL", ("实收资本", "股本")), ("CAPITAL_RESERVE", ("资本公积",)),
		("SURPLUS_RESERVE", ("盈余公积",)), ("RETAINED_EARNINGS", ("未分配利润", "本年利润")),
	)
	for code, words in rules:
		if any(word in name for word in words):
			return code
	if account.root_type == "Asset":
		return "OTHER_NONCURRENT_ASSETS" if account.account_type in {"Fixed Asset", "Capital Work in Progress", "Intangible Asset", "Accumulated Depreciation"} or "长期" in name else "OTHER_CURRENT_ASSETS"
	if account.root_type == "Liability":
		return "OTHER_NONCURRENT_LIABILITIES" if "长期" in name or "非流动" in name else "OTHER_CURRENT_LIABILITIES"
	if account.root_type == "Equity":
		return "RETAINED_EARNINGS"
	return None


def classify_profit_loss_account(account, name):
	if str(getattr(account, "account_number", "") or "") == "6901":
		return None
	if "其他综合收益" in name:
		return "OCI_EQUITY_METHOD_RECLASS" if "权益法" in name else "OCI_FOREIGN_CURRENCY" if "外币" in name else "OCI_EQUITY_INVESTMENT_FAIR_VALUE"
	if account.root_type == "Income":
		for code, words in (
			("NONOPERATING_INCOME", ("营业外",)), ("INVESTMENT_INCOME", ("投资收益",)),
			("FAIR_VALUE_CHANGES", ("公允价值",)), ("ASSET_DISPOSAL_INCOME", ("资产处置",)),
			("OTHER_INCOME", ("其他收益", "政府补助", "补贴")),
		):
			if any(word in name for word in words):
				return code
		return "OPERATING_REVENUE"
	if account.root_type != "Expense":
		return None
	for code, words in (
		("INCOME_TAX", ("所得税",)), ("NONOPERATING_EXPENSE", ("营业外",)),
		("CREDIT_IMPAIRMENT_LOSSES", ("信用减值", "坏账")), ("ASSET_IMPAIRMENT_LOSSES", ("资产减值", "存货跌价")),
		("RD_EXPENSES", ("研发",)), ("SELLING_EXPENSES", ("销售费用",)),
		("ADMIN_EXPENSES", ("管理费用",)), ("FINANCE_EXPENSES", ("财务费用", "利息费用")),
		("TAX_SURCHARGES", ("税金及附加",)),
	):
		if any(word in name for word in words):
			return code
	if account.account_type in {"Cost of Goods Sold", "Stock Adjustment"} or "成本" in name:
		return "OPERATING_COST"
	return "ADMIN_EXPENSES"
