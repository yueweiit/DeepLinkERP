"""Dedicated synthetic site: real native docs, with only external source reads stubbed."""
import json
import unittest
from copy import deepcopy
from datetime import datetime,timezone
from unittest.mock import patch

import frappe
from deeplinkerp_branding.services import purchase_source_service as service
from deeplinkerp_branding.services import purchase_source_contract as contract
from deeplinkerp_branding.services import unified_purchase_service as listing


def fixture(instance="QA-PUR-SOURCE-1", business="QA-DT-PUR-1", *, region="中国China", beneficiary_company=None, project=None, currency="人民币RMB",
            item_code="QA-JOINT-PO-ITEM", purchasing_company=None, supplier=None, rate=None, schedule_date=None, raw=False):
    row={"corp_id":"QA-CORP","process_instance_id":instance,"business_id":business,
         "process_code":contract.PROCESS_CODES[0],"status":"COMPLETED","result":"agree",
         "create_time":datetime(2026,1,1,tzinfo=timezone.utc),"updated_at":datetime(2026,1,1,tzinfo=timezone.utc),
         "originator_user_name":"QA applicant","form_component_values":[
            {"name":"执行地区Región de ejecución","value":region},
            {"name":"币种Moneda","value":currency},
            {"name":"金额importe","value":"100"},
            {"name":"收款人beneficiario","value":"QA Operating Supplier"},
            {"name":"需求明细Desglose de los gastos","componentType":"TableField","value":json.dumps([[
                {"name":"物品编码Código","value":item_code},
                {"name":"物品名称Nombre del artículo","value":"QA synthetic item"},
                {"name":"数量Cantidad","value":"2"},
                {"name":"单位Unidad","value":"Nos"},
                {"name":"总金额Monto Total","value":"100"},
            ]])}]}
    if rate is not None:
        table = json.loads(row["form_component_values"][-1]["value"])
        table[0].append({"name":"单价Precio", "value":rate})
        row["form_component_values"][-1]["value"] = json.dumps(table)
    for name,value in (("归属子公司Subsidiaria",beneficiary_company),("项目Proyecto",project),
                       ("采购公司",purchasing_company),("供应商",supplier),("交付日期",schedule_date)):
        if value is not None:
            row["form_component_values"].append({"name":name,"value":value})
    if raw:
        return row
    source=service._normalize(row)
    proof={"source_id":"QA-cashier-1","source_type":"purchase","corp_id":"QA-CORP","process_instance_id":instance,
           "currency":source["currency"],"paid_amount":"0","payment_evidence_status":"recorded","payments":[],"attachments":[]}
    return source,contract.payment_evidence(source,[proof])


def seed():
    if frappe.local.site!="operating-expenses-qa.localhost" or frappe.conf.db_host!="db":
        raise RuntimeError("Isolated synthetic QA site only")
    from deeplinkerp_branding.purchase_source_install import after_migrate
    after_migrate(); frappe.set_user("Administrator")
    source,evidence=fixture()
    name=service._cache_source(source,evidence,"QA Operating China")
    return name


class NativePurchaseSourcesQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name=seed()
        frappe.db.commit()  # Dedicated cache fixture only, no orders or accounting data.

    def setUp(self):
        frappe.set_user("Administrator")
        self.source,self.evidence=fixture()
        self.before={dt:frappe.db.count(dt) for dt in ("Purchase Receipt","Purchase Invoice","Payment Entry","GL Entry","Stock Entry","Stock Ledger Entry","Purchase Order")}

    def tearDown(self):
        frappe.db.rollback(); frappe.set_user("Administrator")

    def test_native_draft_and_idempotency_without_receipt_payment_or_gl(self):
        with patch.object(service,"_fresh_source",return_value=(self.source,self.evidence)):
            result=service.create_purchase_order_from_source(self.name,service._version(self.source,self.evidence),"QA Operating China","QA Operating Supplier","CNY","2026-10-08",
                [{"item_code":"QA-JOINT-PO-ITEM","qty":2,"uom":"Nos","rate":50}])
            po=frappe.get_doc("Purchase Order",result["name"])
            self.assertEqual(po.docstatus,0); self.assertEqual(po.grand_total,100)
            self.assertEqual(po.items[0].qty,2); self.assertEqual(po.items[0].rate,50)
            self.assertEqual(po.custom_oa_purchase_expense,self.name)
            again=service.create_purchase_order_from_source(self.name,"old","QA Operating China","QA Operating Supplier","CNY","2026-10-08",[])
            self.assertEqual(again,result)
            for dt in ("Purchase Receipt","Purchase Invoice","Payment Entry","GL Entry","Stock Entry","Stock Ledger Entry"):
                self.assertEqual(frappe.db.count(dt),self.before[dt])
            self.assertEqual(frappe.db.count("Purchase Order"),self.before["Purchase Order"]+1)
            payload=listing.get_unified_purchase_list(filters={"search":"QA-DT-PUR-1"})
            self.assertEqual(payload["total_count"],1)
            self.assertEqual(payload["rows"][0]["row_type"],"purchase_order")
            self.assertEqual(payload["rows"][0]["cashier_paid_amount"],"0")

    def test_zero_missing_quantities_and_stale_approval_fail_closed(self):
        for patch_source,items in (({},[{"item_code":"QA-JOINT-PO-ITEM","uom":"Nos","rate":50}]),
                                  ({"eligible":False},[{"item_code":"QA-JOINT-PO-ITEM","qty":2,"uom":"Nos","rate":50}]),
                                  ({"version":"changed"},[{"item_code":"QA-JOINT-PO-ITEM","qty":2,"uom":"Nos","rate":50}])):
            source={**self.source,**patch_source}
            with patch.object(service,"_fresh_source",return_value=(source,self.evidence)),self.assertRaises(frappe.ValidationError):
                service.create_purchase_order_from_source(self.name,service._version(self.source,self.evidence),"QA Operating China","QA Operating Supplier","CNY","2026-10-08",items)
        self.assertEqual(frappe.db.count("Purchase Order"),self.before["Purchase Order"])

    def test_private_json_is_not_native_readable_by_purchase_role(self):
        user="qa-purchase-source-reader@example.test"
        if not frappe.db.exists("User",user):
            frappe.get_doc({"doctype":"User","email":user,"first_name":"QA Purchase source","send_welcome_email":0,"roles":[{"role":"Purchase User"}]}).insert()
        frappe.set_user(user)
        from frappe.model import get_permitted_fields
        fields=set(get_permitted_fields(service.DOCTYPE,permission_type="read"))
        self.assertNotIn(service.SOURCE_FIELD,fields); self.assertNotIn(service.EVIDENCE_FIELD,fields)
        self.assertNotIn(service.RECONCILIATION_FIELD,fields)

    def test_source_update_retains_manual_header_and_child_values(self):
        long_source, long_evidence = fixture("QA-PUR-LONG-PAYEE", "QA-DT-LONG-PAYEE")
        long_source["payee"] = "QA bank information " + "完整原文" * 100
        long_source["originator_user_name"] = "QA " + "长申请人" * 100
        long_source["version"] = contract.digest(long_source)
        long_name = service._cache_source(long_source, long_evidence, "QA Operating China")
        long_doc = frappe.get_doc(service.DOCTYPE, long_name)
        self.assertIsNone(long_doc.payee)
        self.assertIsNone(long_doc.creator)
        self.assertEqual(json.loads(long_doc.get(service.SOURCE_FIELD))["payee"], long_source["payee"])
        self.assertEqual(json.loads(long_doc.get(service.SOURCE_FIELD))["originator_user_name"], long_source["originator_user_name"])
        self.assertEqual(service._cache_source(long_source, long_evidence), long_name)
        for dt, before in self.before.items():
            self.assertEqual(frappe.db.count(dt), before)
        frappe.db.set_value(service.DOCTYPE,self.name,{"currency":"USD","description":"manual text",
            "target_company":"QA Operating China",service.CONFIRMED_FIELD:1,service.BENEFICIARY_FIELD:"QA Operating Mexico"})
        source={**self.source,"requested_amount":"200"}; source["version"]=contract.digest(source)
        service._cache_source(source,self.evidence,"QA Operating Mexico")
        doc=frappe.get_doc(service.DOCTYPE,self.name)
        self.assertEqual(doc.currency,"USD"); self.assertEqual(doc.description,"manual text")
        self.assertEqual(doc.target_company,"QA Operating China")
        self.assertEqual(doc.get(service.BENEFICIARY_FIELD),"QA Operating Mexico")
        self.assertEqual(doc.get(service.CONFIRMED_FIELD),1)
        row=listing.get_unified_purchase_list(filters={"search":"QA-DT-PUR-1"})["rows"][0]
        self.assertEqual(row["oa_currency"],"CNY")
        self.assertEqual(row["requested_amount"],"200")

    def test_duplicate_business_numbers_keep_distinct_exact_source_names(self):
        second,evidence=fixture("QA-PUR-SOURCE-2","QA-DT-PUR-1")
        name=service._cache_source(second,evidence,"QA Operating China")
        self.assertNotEqual(name,self.name)
        doc=frappe.get_doc(service.DOCTYPE,name)
        self.assertEqual(json.loads(doc.get(service.SOURCE_FIELD))["business_id"],"QA-DT-PUR-1")
        self.assertEqual(doc.oa_code,doc.name)

    def test_native_save_protects_import_and_confirmation_before_any_source_json(self):
        def manual(name):
            return frappe.get_doc({"doctype":service.DOCTYPE,"oa_code":name,"apply_date":"2026-10-07",
                "target_company":"QA Operating China","description":"manual","backfill_imported":0,
                service.CONFIRMED_FIELD:0})
        guarded=(("backfill_imported",1),(service.CONFIRMED_FIELD,1),
                 (service.CONFIRMED_BY_FIELD,"Administrator"),(service.CONFIRMED_ON_FIELD,"2026-10-07 10:00:00"))
        for index,(field,value) in enumerate(guarded):
            name=f"QA-PUR-MANUAL-PRESET-{index}"
            doc=manual(name); doc.set(field,value)
            with self.subTest(new=True,field=field),self.assertRaises(frappe.PermissionError):
                doc.insert(set_name=name)
            self.assertFalse(frappe.db.exists(service.DOCTYPE,name))
        doc=manual("QA-PUR-MANUAL-NO-SOURCE").insert(set_name="QA-PUR-MANUAL-NO-SOURCE")
        self.assertFalse(doc.get(service.SOURCE_FIELD))
        doc.target_company="QA Operating Mexico"; doc.description="regular manual edit"; doc.save()
        self.assertEqual(frappe.db.get_value(service.DOCTYPE,doc.name,"description"),"regular manual edit")
        for field,value in guarded:
            changed=frappe.get_doc(service.DOCTYPE,doc.name); changed.set(field,value)
            with self.subTest(new=False,field=field),self.assertRaises(frappe.PermissionError):
                changed.save()
        imported=frappe.get_doc(service.DOCTYPE,self.name); imported.backfill_imported=0
        with self.assertRaises(frappe.PermissionError): imported.save()
        for dt,before in self.before.items(): self.assertEqual(frappe.db.count(dt),before)

    def test_native_inactive_or_unassigned_project_is_evidence_only_and_explicit_choice_fails(self):
        for suffix,active,company in (("INACTIVE","No","QA Operating China"),("UNASSIGNED","Yes",None)):
            project=frappe.get_doc({"doctype":"Project","project_name":f"QA Invalid source project {suffix}",
                "company":"QA Operating China","is_active":active}).insert()
            if not company:
                frappe.db.set_value("Project",project.name,"company",None)
            source,evidence=fixture(f"QA-PUR-PROJECT-{suffix}",f"QA-DT-PROJECT-{suffix}",project=project.project_name)
            name=service._cache_source(source,evidence,"QA Operating China")
            detail=service.get_purchase_source_detail(name)
            self.assertEqual(detail["project_status"],"incompatible")
            self.assertIsNone(detail["project_candidate"])
            self.assertEqual(detail["source"]["project"],project.project_name)
            self.assertTrue(any("启用" in message for message in detail["role_warnings"]))
            before=frappe.db.count("Purchase Order")
            with patch.object(service,"_fresh_source",return_value=(source,evidence)):
                with self.subTest(explicit=True,project=suffix),self.assertRaises(frappe.ValidationError):
                    service.create_purchase_order_from_source(name,service._version(source,evidence),"QA Operating China",
                        "QA Operating Supplier","CNY","2026-10-08",[{"item_code":"QA-JOINT-PO-ITEM","qty":2,"uom":"Nos","rate":50}],
                        project=project.name)
                self.assertEqual(frappe.db.count("Purchase Order"),before)
                result=service.create_purchase_order_from_source(name,service._version(source,evidence),"QA Operating China",
                    "QA Operating Supplier","CNY","2026-10-08",[{"item_code":"QA-JOINT-PO-ITEM","qty":2,"uom":"Nos","rate":50}])
            order=frappe.get_doc("Purchase Order",result["name"])
            self.assertFalse(order.project)
            self.assertEqual(order.docstatus,0)
            self.assertFalse(frappe.get_doc(service.DOCTYPE,name).get(service.PROJECT_FIELD))
        for dt in self.before:
            if dt!="Purchase Order": self.assertEqual(frappe.db.count(dt),self.before[dt])

    def test_mexico_factory_source_cache_and_domestic_purchase_order_have_separate_roles(self):
        project=frappe.get_doc({"doctype":"Project","project_name":"QA Mexico source molds","company":"QA Operating Mexico","is_active":"Yes"}).insert()
        source,evidence=fixture("QA-PUR-MX-EXTERNAL","QA-DT-MX-EXTERNAL",region="墨西哥Mexico",
            beneficiary_company="QA Operating Mexico",project=project.project_name)
        name=service._cache_source(source,evidence,"QA Operating China")
        doc=frappe.get_doc(service.DOCTYPE,name)
        self.assertTrue(source["eligible"])
        self.assertFalse(doc.target_company)
        self.assertEqual(doc.get(service.PROPOSAL_FIELD),"QA Operating China")
        self.assertFalse(doc.get(service.CONFIRMED_FIELD))
        for dt,before in self.before.items(): self.assertEqual(frappe.db.count(dt),before)
        with patch.object(service,"_fresh_source",return_value=(source,evidence)):
            result=service.create_purchase_order_from_source(name,service._version(source,evidence),"QA Operating China",
                "QA Operating Supplier","CNY","2026-10-08",[{"item_code":"QA-JOINT-PO-ITEM","qty":2,"uom":"Nos","rate":50}])
        order=frappe.get_doc("Purchase Order",result["name"])
        self.assertEqual(order.company,"QA Operating China")
        self.assertFalse(order.project)
        self.assertEqual(order.docstatus,0)
        doc=frappe.get_doc(service.DOCTYPE,name)
        self.assertEqual(doc.get(service.BENEFICIARY_FIELD),"QA Operating Mexico")
        self.assertEqual(doc.target_company,"QA Operating China")
        self.assertEqual(doc.get(service.CONFIRMED_FIELD),1)
        self.assertEqual(doc.get(service.CONFIRMED_BY_FIELD),"Administrator")
        changed={**source,"beneficiary_company":"QA Operating China","project":"new raw project"}
        changed["version"]=contract.digest(changed)
        service._cache_source(changed,evidence,"QA Operating Mexico")
        refreshed=frappe.get_doc(service.DOCTYPE,name)
        self.assertEqual(refreshed.get(service.BENEFICIARY_FIELD),"QA Operating Mexico")
        self.assertEqual(refreshed.target_company,"QA Operating China")
        self.assertTrue(refreshed.source_stale)
        self.assertEqual(json.loads(refreshed.get(service.SOURCE_FIELD))["project"],"new raw project")
        for dt in self.before:
            if dt!="Purchase Order": self.assertEqual(frappe.db.count(dt),self.before[dt])

    def test_mexico_internal_molds_use_an_explicit_mexico_buyer_and_its_existing_project(self):
        project=frappe.get_doc({"doctype":"Project","project_name":"QA Mexico internal molds","company":"QA Operating Mexico","is_active":"Yes"}).insert()
        currency=frappe.db.get_value("Company","QA Operating Mexico","default_currency")
        source,evidence=fixture("QA-PUR-MX-INTERNAL","QA-DT-MX-INTERNAL",region="墨西哥México",
            beneficiary_company="QA Operating Mexico",project=project.project_name,currency=currency)
        name=service._cache_source(source,evidence,"QA Operating China")
        with patch.object(service,"_fresh_source",return_value=(source,evidence)):
            result=service.create_purchase_order_from_source(name,service._version(source,evidence),"QA Operating Mexico",
                "QA Operating Supplier",currency,"2026-10-08",[{"item_code":"QA-JOINT-PO-ITEM","qty":2,"uom":"Nos","rate":50}],
                beneficiary_company="QA Operating Mexico",project=project.name)
        order=frappe.get_doc("Purchase Order",result["name"])
        self.assertEqual(order.company,"QA Operating Mexico")
        self.assertEqual(order.project,project.name)
        self.assertEqual(order.docstatus,0)
        doc=frappe.get_doc(service.DOCTYPE,name)
        self.assertEqual(doc.target_company,"QA Operating Mexico")
        self.assertEqual(doc.get(service.BENEFICIARY_FIELD),"QA Operating Mexico")
        self.assertEqual(doc.get(service.PROJECT_FIELD),project.name)
        for dt in self.before:
            if dt!="Purchase Order": self.assertEqual(frappe.db.count(dt),self.before[dt])


if __name__=="__main__": unittest.main()
