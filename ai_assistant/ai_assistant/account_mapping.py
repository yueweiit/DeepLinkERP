from __future__ import annotations

import re


ACCOUNT_CATALOG = {
    "1001": "库存现金",
    "1002": "银行存款",
    "1012": "其他货币资金",
    "1101": "交易性金融资产",
    "1121": "应收票据",
    "1122": "应收账款",
    "1123": "预付账款",
    "1131": "应收股利",
    "1132": "应收利息",
    "1221": "其他应收款",
    "1231": "坏账准备",
    "1321": "受托代销商品",
    "1401": "材料采购",
    "1402": "在途物资",
    "1403": "原材料",
    "1404": "材料成本差异",
    "1405": "库存商品",
    "1406": "发出商品",
    "1407": "商品进销差价",
    "1408": "委托加工物资",
    "1411": "周转材料",
    "1471": "存货跌价准备",
    "1501": "持有至到期投资",
    "1502": "持有至到期投资减值准备",
    "1503": "可供出售金融资产",
    "1511": "长期股权投资",
    "1512": "长期股权投资减值准备",
    "1521": "投资性房地产",
    "1531": "长期应收款",
    "1532": "未实现融资收益",
    "1601": "固定资产",
    "1602": "累计折旧",
    "1603": "固定资产减值准备",
    "1604": "在建工程",
    "1605": "工程物资",
    "1606": "固定资产清理",
    "1621": "生产性生物资产",
    "1622": "生产性生物资产累计折旧",
    "1701": "无形资产",
    "1702": "累计摊销",
    "1703": "无形资产减值准备",
    "1711": "商誉",
    "1801": "长期待摊费用",
    "1811": "递延所得税资产",
    "1901": "待处理财产损溢",
    "2001": "短期借款",
    "2101": "交易性金融负债",
    "2201": "应付票据",
    "2202": "应付账款",
    "2203": "预收账款",
    "2211": "应付职工薪酬",
    "2221": "应交税费",
    "2231": "应付股利",
    "2232": "应付利息",
    "2241": "其他应付款",
    "2314": "受托代销商品款",
    "2401": "递延收益",
    "2501": "长期借款",
    "2502": "应付债券",
    "2701": "长期应付款",
    "2702": "未确认融资费用",
    "2711": "专项应付款",
    "2801": "预计负债",
    "2901": "递延所得税负债",
    "3101": "衍生工具",
    "3201": "套期工具",
    "3202": "被套期项目",
    "4001": "实收资本",
    "4002": "资本公积",
    "4003": "其他综合收益",
    "4101": "盈余公积",
    "4103": "本年利润",
    "4104": "利润分配",
    "4201": "库存股",
    "5001": "生产成本",
    "5101": "制造费用",
    "5201": "劳务成本",
    "5301": "研发支出",
    "6001": "主营业务收入",
    "6051": "其他业务收入",
    "6101": "公允价值变动损益",
    "6111": "投资收益",
    "6201": "其他收益-政府补助",
    "6301": "营业外收入",
    "6401": "主营业务成本",
    "6402": "其他业务成本",
    "6403": "税金及附加",
    "6601": "销售费用",
    "6602": "管理费用",
    "6603": "财务费用",
    "6701": "资产减值损失",
    "6711": "营业外支出",
    "6801": "所得税",
    "6901": "以前年度损益调整",
}

EXPENSE_RULES = [
    {"priority": 100, "patterns": [r"代发工资手续费", r"跨行.*手续费", r"余额变动提醒手续费", r"手续费", r"收费明细", r"对公收费", r"扣费"], "account": "财务费用-手续费"},
    {"priority": 95, "patterns": [r"工资", r"薪资", r"薪酬", r"代发(?!.*手续费)"], "account": "应付职工薪酬-工资"},
    {"priority": 94, "patterns": [r"社保", r"社会保险", r"社保\d+"], "account": "应付职工薪酬-社保"},
    {"priority": 93, "patterns": [r"公积金", r"住房公积金"], "account": "应付职工薪酬-公积金"},
    {"priority": 90, "patterns": [r"国库", r"税收", r"增值税", r"所得税", r"印花税", r"附加税", r"公共缴费", r"扣税"], "account": "应交税费"},
    {"priority": 80, "patterns": [r"货款", r"采购", r"供应商", r"材料", r"商品"], "account": "应付账款"},
    {"priority": 72, "patterns": [r"物业", r"水电", r"电费"], "account": "管理费用-物业水电费"},
    {"priority": 71, "patterns": [r"房租", r"租金"], "account": "管理费用-租金"},
    {"priority": 70, "patterns": [r"招聘"], "account": "管理费用-招聘费"},
    {"priority": 65, "patterns": [r"运费", r"物流", r"运输"], "account": "管理费用-运输费"},
    {"priority": 60, "patterns": [r"快递", r"办公", r"耗材", r"用品", r"服务费", r"咨询费", r"技术服务"], "account": "管理费用-办公费"},
    {"priority": 55, "patterns": [r"报销", r"差旅", r"餐费", r"招待"], "account": "管理费用-办公费"},
    {"priority": 40, "patterns": [r"利息"], "account": "财务费用-利息"},
]

INCOME_RULES = [
    {"priority": 95, "patterns": [r"利息"], "account": "财务费用-利息收入"},
    {"priority": 90, "patterns": [r"销售", r"收入", r"货款", r"客户", r"回款", r"收款", r"转存"], "account": "主营业务收入"},
    {"priority": 80, "patterns": [r"营业外收入", r"补贴", r"赔款"], "account": "营业外收入"},
    {"priority": 70, "patterns": [r"投资", r"股东", r"实收资本"], "account": "实收资本"},
    {"priority": 60, "patterns": [r"退款", r"退回", r"返还"], "account": "其他应收款"},
]


ACCOUNT_ROOTS = {
    "库存现金": "asset",
    "银行存款": "asset",
    "其他货币资金": "asset",
    "交易性金融资产": "asset",
    "应收票据": "asset",
    "应收账款": "asset",
    "预付账款": "asset",
    "应收股利": "asset",
    "应收利息": "asset",
    "其他应收款": "asset",
    "坏账准备": "asset_credit",
    "受托代销商品": "asset",
    "材料采购": "asset",
    "在途物资": "asset",
    "原材料": "asset",
    "材料成本差异": "asset",
    "库存商品": "asset",
    "发出商品": "asset",
    "商品进销差价": "asset",
    "委托加工物资": "asset",
    "周转材料": "asset",
    "存货跌价准备": "asset_credit",
    "持有至到期投资": "asset",
    "持有至到期投资减值准备": "asset_credit",
    "可供出售金融资产": "asset",
    "长期股权投资": "asset",
    "长期股权投资减值准备": "asset_credit",
    "投资性房地产": "asset",
    "长期应收款": "asset",
    "未实现融资收益": "asset",
    "固定资产": "asset",
    "累计折旧": "asset_credit",
    "固定资产减值准备": "asset_credit",
    "在建工程": "asset",
    "工程物资": "asset",
    "固定资产清理": "asset",
    "生产性生物资产": "asset",
    "生产性生物资产累计折旧": "asset_credit",
    "无形资产": "asset",
    "累计摊销": "asset_credit",
    "无形资产减值准备": "asset_credit",
    "商誉": "asset",
    "长期待摊费用": "asset",
    "递延所得税资产": "asset",
    "待处理财产损溢": "asset",
    "短期借款": "liability",
    "交易性金融负债": "liability",
    "应付票据": "liability",
    "应付账款": "liability",
    "预收账款": "liability",
    "应付职工薪酬": "liability",
    "应交税费": "liability",
    "应付股利": "liability",
    "应付利息": "liability",
    "其他应付款": "liability",
    "受托代销商品款": "liability",
    "递延收益": "liability",
    "长期借款": "liability",
    "应付债券": "liability",
    "长期应付款": "liability",
    "未确认融资费用": "liability",
    "专项应付款": "liability",
    "预计负债": "liability",
    "递延所得税负债": "liability",
    "衍生工具": "equity",
    "套期工具": "equity",
    "被套期项目": "equity",
    "实收资本": "equity",
    "资本公积": "equity",
    "其他综合收益": "equity",
    "盈余公积": "equity",
    "本年利润": "equity",
    "利润分配": "equity",
    "库存股": "equity",
    "生产成本": "expense",
    "制造费用": "expense",
    "劳务成本": "expense",
    "研发支出": "expense",
    "主营业务收入": "income",
    "其他业务收入": "income",
    "公允价值变动损益": "income",
    "投资收益": "income",
    "其他收益-政府补助": "income",
    "营业外收入": "income",
    "主营业务成本": "expense",
    "其他业务成本": "expense",
    "税金及附加": "expense",
    "销售费用": "expense",
    "管理费用": "expense",
    "财务费用": "expense",
    "资产减值损失": "expense",
    "营业外支出": "expense",
    "所得税": "expense",
    "以前年度损益调整": "expense",
}


def normalize_text(*parts):
    return " ".join(str(part or "") for part in parts).strip()


def counterparty_suffix(counterparty):
    cleaned = re.sub(r"\s+", "", str(counterparty or ""))
    if not cleaned:
        return "待确认"
    return cleaned[:24]


def base_account(account):
    text = str(account or "")
    if text in ACCOUNT_ROOTS:
        return text
    return text.split("-", 1)[0]


def account_root_type(account):
    base = base_account(account)
    return ACCOUNT_ROOTS.get(base, "unknown")


def is_valid_account(account):
    if not account:
        return False
    return base_account(account) in ACCOUNT_ROOTS


def allowed_base_accounts():
    return sorted(ACCOUNT_ROOTS)


def _match_rule(compact, rules):
    ordered_rules = sorted(rules, key=lambda item: item.get("priority", 0), reverse=True)
    for rule in ordered_rules:
        for pattern in rule.get("patterns", []):
            if re.search(pattern, compact):
                return rule["account"], pattern
    return None, None


def map_transaction(summary=None, purpose=None, counterparty=None, direction="out"):
    text = normalize_text(summary, purpose, counterparty)
    compact = re.sub(r"\s+", "", text)

    if direction == "out":
        debit_account, pattern = _match_rule(compact, EXPENSE_RULES)
        if debit_account:
            return debit_account, "银行存款", f"规则匹配：{debit_account}（{pattern}）"
        if not str(counterparty or "").strip() and re.search(r"手续费|收费|扣费|服务费", compact):
            return "财务费用-手续费", "银行存款", "对方单位为空且摘要为收费类，按银行手续费归类"
        return "其他应收款-待确认", "银行存款", "未命中规则，按待确认支出处理，需人工复核"

    credit_account, pattern = _match_rule(compact, INCOME_RULES)
    if credit_account:
        return "银行存款", credit_account, f"规则匹配：{credit_account}（{pattern}）"
    if re.search(r"网转|转账|往来", compact):
        return "银行存款", "其他应付款-待确认", "转入往来款待确认，需人工复核"
    return "银行存款", "其他应付款-待确认", "未命中规则，按待确认收入处理，需人工复核"
