"""Competing synthetic payments with a pre-lock REPEATABLE-READ snapshot.

This test commits only its unique fixture on the dedicated QA site and removes
exactly that fixture in finally. It creates only an unposted native JE draft;
it never creates GL or Payment Entry.
"""
import copy
import json
import threading
import unittest
import uuid
from unittest.mock import patch

import frappe


class OperatingPaymentConcurrencyQA(unittest.TestCase):
    def test_existing_voucher_link_locks_native_editor_and_rechecks_its_old_event_snapshot(self):
        from frappe.model.document import Document
        from deeplinkerp_branding.services import operating_expenses as expenses
        if frappe.local.site != "operating-expenses-qa.localhost" or frappe.conf.db_host != "db":
            raise RuntimeError("Dedicated synthetic operating site only")
        frappe.set_user("Administrator")
        name = "qa-journal-link-race-" + uuid.uuid4().hex
        source = frappe.get_doc({**frappe.get_doc(expenses.SOURCE, "1001").as_dict(), "name": name, "source_id": name})
        raw = json.loads(source.source_json)
        raw.update(source_id=name, amount="100.00", version="qa-link-race-version")
        source.source_json = json.dumps(raw)
        mapping = {"company": source.company, "party_type": "Supplier", "party": "QA Operating Supplier", "payable_account": "Creditors - QOC", "payable_exchange_rate": "1", "posting_date": "2026-10-01", "actual_incurred": True, "recognition_mode": "existing", "existing_erp_coverage_confirmed": True, "no_existing_erp_coverage": False,
                   "expense_lines": [{"account": "Administrative Expenses - QOC", "source_amount": "100", "amount": "100", "exchange_rate": "1", "cost_center": frappe.db.get_value("Company", source.company, "cost_center")}], "payments": {}}
        snapshot_ready, event_inserted, editor_started = threading.Event(), threading.Event(), threading.Event()
        editor_finished = threading.Event()
        results, worker, journal, preview = [], None, None, None
        before = (frappe.db.count("GL Entry"), frappe.db.count("Payment Entry"))
        original = Document.run_method
        try:
            with expenses.managed_write():
                source.insert(ignore_permissions=True)
            with patch.object(expenses, "_fresh", side_effect=lambda doc, **kwargs: copy.deepcopy(raw)):
                expenses.save_mapping(name, mapping, raw["version"])
                preview = expenses.preview_voucher(name)
                journal = frappe.get_doc({"doctype": "Journal Entry", "company": source.company, "posting_date": preview["posting_date"], "accounts": preview["accounts"]}).insert()
                frappe.db.commit()
                def edit_from_old_snapshot():
                    try:
                        frappe.init(site="operating-expenses-qa.localhost", sites_path=".")
                        frappe.connect(); frappe.set_user("Administrator")
                        self.assertFalse(frappe.db.exists(expenses.EVENT, preview["event_key"]))
                        edit = frappe.get_doc("Journal Entry", journal.name)
                        snapshot_ready.set()
                        self.assertTrue(event_inserted.wait(10))
                        edit.posting_date = "2026-10-03"
                        editor_started.set()
                        edit.save()
                        frappe.db.commit(); results.append("accepted")
                    except frappe.ValidationError:
                        frappe.db.rollback(); results.append("rejected")
                    except frappe.QueryDeadlockError:
                        # MariaDB may reject a current read after this old
                        # snapshot with 1020. The isolated native POST aborts;
                        # a fresh user retry must still find the new association.
                        frappe.db.rollback()
                        try:
                            retry = frappe.get_doc("Journal Entry", journal.name)
                            retry.posting_date = "2026-10-03"
                            retry.save()
                            frappe.db.commit(); results.append("accepted")
                        except frappe.ValidationError:
                            frappe.db.rollback(); results.append("rejected")
                    except BaseException as error:
                        frappe.db.rollback(); results.append(error)
                    finally:
                        snapshot_ready.set(); editor_finished.set(); frappe.destroy()
                worker = threading.Thread(target=edit_from_old_snapshot, daemon=True)
                worker.start()
                self.assertTrue(snapshot_ready.wait(10))
                def paused(document, method, *args, **kwargs):
                    result = original(document, method, *args, **kwargs)
                    if document.doctype == expenses.EVENT and document.source == name and method == "after_insert":
                        event_inserted.set()
                        self.assertTrue(editor_started.wait(10))
                        self.assertFalse(editor_finished.wait(0.25), "Native editor must wait on the associated Journal Entry lock")
                    return result
                with patch.object(Document, "run_method", new=paused):
                    expenses.link_existing(name, journal.name, preview["fingerprint"])
                frappe.db.commit()
                worker.join(20)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results, ["rejected"], "Native editor must current-read the newly linked Event, not its old empty snapshot")
                self.assertEqual(str(frappe.db.get_value("Journal Entry", journal.name, "posting_date")), preview["posting_date"])
                self.assertEqual((frappe.db.count("GL Entry"), frappe.db.count("Payment Entry")), before)
        finally:
            frappe.db.rollback(); event_inserted.set()
            if worker:
                worker.join(20)
                if worker.is_alive():
                    raise RuntimeError("Retain exact QA fixture: native editor did not stop")
            with expenses.managed_write():
                if preview:
                    frappe.delete_doc(expenses.EVENT, preview["event_key"], ignore_permissions=True, ignore_missing=True)
                if journal:
                    if frappe.db.get_value("Journal Entry", journal.name, "docstatus") != 0:
                        raise RuntimeError("Never remove submitted QA journals")
                    frappe.delete_doc("Journal Entry", journal.name, ignore_permissions=True)
                frappe.delete_doc(expenses.MAPPING, name, ignore_permissions=True, ignore_missing=True)
                frappe.delete_doc(expenses.SOURCE, name, ignore_permissions=True, ignore_missing=True)
            frappe.db.commit()

    def test_waiting_registration_observes_committed_payment_not_its_old_snapshot(self):
        from deeplinkerp_branding.services import operating_expenses as expenses, operating_payment_service as service
        from deeplinkerp_branding.services.operating_expense_contract import digest, expense_facts
        if frappe.local.site != "operating-expenses-qa.localhost" or frappe.conf.db_host != "db":
            raise RuntimeError("Dedicated synthetic operating site only")
        frappe.set_user("Administrator")
        name="qa-payment-race-"+uuid.uuid4().hex
        source=frappe.get_doc({**frappe.get_doc(expenses.SOURCE,"1001").as_dict(),"name":name,"source_id":name})
        raw=json.loads(source.source_json)
        raw.update(source_id=name,amount="100.00",paid_amount="30.00",pending_amount="70.00",version="qa-race-version")
        raw["payments"]=[{"source_id":"qa-history","amount":"30.00","currency":"CNY","payment_date":"2026-10-02","evidence_status":"recorded"}]
        source.source_json=json.dumps(raw)
        bank=frappe.db.get_value("Account",{"company":source.company,"account_type":"Cash","is_group":0},"name")
        values={"amount":"50.00","bank_amount":"50.00","payment_date":"2026-10-07","bank_account":bank,"party_type":"Supplier","party":"QA Operating Supplier","bank_reference":"synthetic-race-no-transfer"}
        before_gl,before_pe=frappe.db.count("GL Entry"),frappe.db.count("Payment Entry")
        snapshot_ready=threading.Event()
        result=[]
        worker=None
        try:
            with expenses.managed_write():
                source.insert(ignore_permissions=True)
                frappe.get_doc({"doctype":service.TAKEOVER,"source":name,"company":source.company,"history_json":json.dumps(raw),"claim_token":"qa-race-token","history_fingerprint":digest(raw),"expense_fingerprint":digest(expense_facts(raw)),"claimed_by":"Administrator"}).insert(ignore_permissions=True)
            frappe.db.commit()
            expenses._source(name,write=True)
            def competing_registration():
                try:
                    frappe.init(site="operating-expenses-qa.localhost",sites_path=".")
                    frappe.connect()
                    frappe.set_user("Administrator")
                    # Establish a real snapshot before waiting on the source lock.
                    self.assertEqual(frappe.db.count(service.PAYMENT,{"source":name}),0)
                    snapshot_ready.set()
                    service.register_payment(name,values,raw["version"],"second-request")
                    frappe.db.commit()
                    result.append("accepted")
                except frappe.ValidationError:
                    frappe.db.rollback()
                    result.append("rejected")
                except BaseException as error:
                    frappe.db.rollback()
                    result.append(error)
                finally:
                    snapshot_ready.set()
                    frappe.destroy()
            with patch.object(expenses,"_fresh",side_effect=lambda doc,**kwargs:copy.deepcopy(raw)):
                worker=threading.Thread(target=competing_registration,daemon=True)
                worker.start()
                self.assertTrue(snapshot_ready.wait(10),"Contender did not establish its snapshot")
                service.register_payment(name,values,raw["version"],"first-request")
                frappe.db.commit()
                worker.join(20)
                self.assertFalse(worker.is_alive(),"Competing request remained blocked")
            self.assertEqual(result,["rejected"],"Both distinct payments must not consume the same pending balance")
            self.assertEqual(frappe.db.count(service.PAYMENT,{"source":name}),1)
            self.assertEqual(service.payment_detail(source)["balance"]["pending_amount"],"20.00")
            self.assertEqual((frappe.db.count("GL Entry"),frappe.db.count("Payment Entry")),(before_gl,before_pe))
        finally:
            frappe.db.rollback()
            if worker and worker.is_alive():
                worker.join(20)
            if worker and worker.is_alive():
                raise RuntimeError("Retain QA fixture: competing transaction did not stop")
            with expenses.managed_write():
                for row in frappe.get_all(service.PAYMENT,filters={"source":name},pluck="name"):
                    frappe.delete_doc(service.PAYMENT,row,ignore_permissions=True)
                frappe.delete_doc(service.TAKEOVER,name,ignore_permissions=True,ignore_missing=True)
                frappe.delete_doc(expenses.SOURCE,name,ignore_permissions=True,ignore_missing=True)
            frappe.db.commit()
