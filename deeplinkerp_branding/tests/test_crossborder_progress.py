"""Site-free native reader/API boundaries. Only persistence and native permissions are doubled."""
import copy
import importlib
import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from deeplinkerp_branding.services import purchase_order_progress as progress
from deeplinkerp_branding.services import purchase_payment_service as payment


LINK = "Purchase Fulfilment Link"
PO_FIELDS = {"company", "supplier", "currency", "grand_total", "items", "per_received", "status"}
ITEM_FIELDS = {"name", "idx", "item_code", "item_name", "description", "qty", "uom", "stock_uom",
               "conversion_factor", "rate", "amount", "received_qty"}
CHILDREN = {"Purchase Order": "Purchase Order Item", "Purchase Receipt": "Purchase Receipt Item",
            "Purchase Invoice": "Purchase Invoice Item", "Payment Entry": "Payment Entry Reference",
            "Sales Order": "Sales Order Item"}


class Rows(list):
    def __init__(self, rows, memory, dt):
        super().__init__(rows); self.memory = memory; self.dt = dt
    def __iter__(self):
        if self.dt == "Purchase Invoice":
            self.memory.invoice_iterations += len(self)
        return super().__iter__()


class NativeItem(frappe._dict):
    def as_dict(self):
        return dict(self)


class NativeDoc(SimpleNamespace):
    def __init__(self, memory, values):
        super().__init__(**values); self.memory = memory
        if "items" in values:
            self.items = Rows([NativeItem(row) for row in values["items"]], memory, self.doctype)
    def get(self, field, default=None):
        return getattr(self, field, default)
    def as_dict(self):
        return {key: value for key, value in vars(self).items() if key != "memory"}
    def mask_fields(self):
        pass
    def check_permission(self, permission):
        if (self.doctype, self.name, permission) in self.memory.denied:
            raise frappe.PermissionError("private native name must not leak: " + self.name)
    def has_permission(self, permission):
        return (self.doctype, self.name, permission) not in self.memory.denied
    def is_new(self):
        return (self.doctype, self.get("name")) not in self.memory.records
    def update(self, data):
        self.__dict__.update(data)
        return self
    def get_doc_before_save(self):
        row = self.memory.records.get((self.doctype, self.get("name")))
        return NativeDoc(self.memory, copy.deepcopy(row)) if row else None
    def insert(self, **kwargs):
        assert not kwargs.get("ignore_permissions"), "association APIs may not bypass native authorization"
        return self.save()
    def save(self, **kwargs):
        assert not kwargs.get("ignore_permissions")
        if self.doctype != LINK:
            raise AssertionError("No native business document writes are authorized in these APIs")
        api().validate_managed_link(self)
        self.name = self.get("name") or "LINK-" + str(len(self.memory.records))
        self.modified = str(self.memory.next_version)
        self.memory.next_version += 1
        self.memory.records[self.doctype, self.name] = copy.deepcopy(self.as_dict())
        return self


class NativeMemory:
    def __init__(self):
        self.records = {}; self.children = {}; self.denied = set(); self.hidden = {}; self.queries = []
        self.invoice_iterations = 0; self.next_version = 1; self.locks = []; self.installed_cost = False
        self.current_reads = []; self.events = []
        self.savepoints = {}; self.rollbacks = []
        self.db = Mock(get_values=self.get_values, get_value=self.get_value, exists=self.exists, sql=self.allocation_sql,
                       savepoint=self.savepoint, rollback=self.rollback, release_savepoint=self.release_savepoint)

    def savepoint(self, name):
        self.events.append(("savepoint", name))
        self.savepoints[name] = copy.deepcopy((self.records, self.children))
    def rollback(self, *, save_point=None):
        if save_point is None:
            raise AssertionError("optional logistics may not roll back the surrounding source-sync transaction")
        self.events.append(("rollback", save_point)); self.rollbacks.append(save_point)
        self.records, self.children = copy.deepcopy(self.savepoints[save_point])
    def release_savepoint(self, name):
        self.events.append(("release", name))
        del self.savepoints[name]

    def allocation_sql(self, query, values=None, **kwargs):
        self.current_reads.append((query, values))
        self.events.append(("allocations", tuple(values)))
        return [frappe._dict(copy.deepcopy(row)) for (dt, _), row in self.records.items()
                if dt == LINK and row.get("active") and (row["external_order"] == values[0] or
                    (len(values) > 1 and row.get("internal_order") == values[1]))]
    def add(self, dt, name, **values):
        data = {"doctype": dt, "name": name, "modified": "v1", "docstatus": 0, **values}
        self.records[dt, name] = data
        child_dt = CHILDREN.get(dt)
        field = "references" if dt == "Payment Entry" else "items"
        if child_dt:
            self.children[child_dt] = [row for row in self.children.get(child_dt, []) if row["parent"] != name]
        for index, row in enumerate(data.get(field, []), 1):
            child = {"parent": name, "parenttype": dt, "parentfield": field, "idx": index, **row}
            self.children.setdefault(child_dt, []).append(child)
        return data
    def po(self, name="EXT", company="BUYER", supplier="EXTERNAL", *, qty=10, currency="CNY", submitted=True):
        self.add("Company", company)
        self.add("Item", "M", is_stock_item=1, stock_uom="Nos")
        return self.add("Purchase Order", name, company=company, supplier=supplier, currency=currency,
            grand_total=qty * 10, docstatus=1 if submitted else 0, status="To Receive and Bill", per_received=0,
            items=[dict(name=name + "-I", item_code="M", item_name="Material", qty=qty, uom="Nos", stock_uom="Nos",
                        conversion_factor=1, rate=10, amount=qty * 10, received_qty=0)])
    def received(self, name, qty, percent):
        self.records["Purchase Order", name]["per_received"] = percent
        for row in self.records["Purchase Order", name]["items"]:
            row["received_qty"] = qty
        for row in self.children["Purchase Order Item"]:
            if row["parent"] == name:
                row["received_qty"] = qty
    def invoice(self, name="PI", po="EXT", *, total=100, outstanding=0, currency="CNY", docstatus=1, **changes):
        source = self.records["Purchase Order", po]
        return self.add("Purchase Invoice", name, company=source["company"], supplier=source["supplier"],
            currency=currency, party_account_currency=currency, grand_total=total, rounded_total=0,
            disable_rounded_total=1, base_grand_total=total, base_rounded_total=0, outstanding_amount=outstanding,
            is_return=0, docstatus=docstatus, items=[dict(purchase_order=po, purchase_receipt=None)], **changes)
    @staticmethod
    def matches(row, filters):
        for key, value in (filters or {}).items():
            if isinstance(value, (tuple, list)):
                if value[0] == "in" and row.get(key) not in value[1]: return False
                if value[0] == "!=" and row.get(key) == value[1]: return False
                if value[0] == "=" and row.get(key) != value[1]: return False
                if value[0] == "is" and (row.get(key) not in (None, "")) != (value[1] == "set"): return False
            elif row.get(key) != value:
                return False
        return True
    def rows(self, dt, filters=None, or_filters=None, **kwargs):
        self.queries.append((dt, filters))
        rows = self.children.get(dt, []) if dt in CHILDREN.values() else [row for (kind, _), row in self.records.items() if kind == dt]
        result = [frappe._dict(copy.deepcopy(row)) for row in rows if self.matches(row, filters) and (
            not or_filters or any(self.matches(row, {entry[-3]: [entry[-2], entry[-1]]}) for entry in or_filters))]
        if kwargs.get("pluck"):
            return list(dict.fromkeys(row[kwargs["pluck"]] for row in result))
        return result
    def get_values(self, dt, filters, fields, **kwargs):
        rows = self.rows(dt, filters)
        if fields != "*":
            fields = [fields] if isinstance(fields, str) else fields
            rows = [frappe._dict({field: row.get(field) for field in fields}) for row in rows]
        return rows if kwargs.get("as_dict") else [tuple(row.values()) for row in rows]
    def get_value(self, dt, name, field, **kwargs):
        row = self.records.get((dt, name), {}) if isinstance(name, str) else next(iter(self.rows(dt, name)), {})
        if isinstance(field, (list, tuple)):
            return frappe._dict({key: row.get(key) for key in field})
        return row.get(field)
    def exists(self, dt, name):
        if dt == "DocType":
            return name != "Overseas Cost Batch" or self.installed_cost
        return (dt, name) in self.records
    def get_doc(self, dt, name=None, **kwargs):
        if isinstance(dt, dict):
            return NativeDoc(self, dict(dt))
        if kwargs.get("for_update"):
            self.locks.append((dt, name))
            self.events.append(("lock", dt, name))
        row = self.records.get((dt, name))
        if row is None: raise frappe.DoesNotExistError(name)
        return NativeDoc(self, copy.deepcopy(row))
    def fields(self, dt, **kwargs):
        fields = set(PO_FIELDS | ITEM_FIELDS | payment.PI_FIELDS | {"name", "modified", "docstatus", "purchase_order",
            "purchase_receipt", "purchase_order_item", "po_detail", "is_return", "warehouse", "received_qty",
            "represents_company", "is_internal_supplier", "is_internal_customer", "disabled", "customer",
            "default_currency", "stock_qty", "posting_date", "is_group", "references",
            "reference_doctype", "reference_name", "allocated_amount"})
        fields.update(rowkey for (kind, _), row in self.records.items() if kind == dt for rowkey in row)
        return fields - self.hidden.get((dt, kwargs.get("permission_type", "read")), set())
    def meta(self, dt):
        child = CHILDREN.get(dt)
        tables = [frappe._dict(fieldname="references" if dt == "Payment Entry" else "items", options=child)] if child else []
        return SimpleNamespace(get_table_fields=lambda: tables, fields=[], get_permlevel_access=lambda **kwargs: [0],
                               has_field=lambda field: field in self.fields(dt))


def api():
    try:
        return importlib.import_module("deeplinkerp_branding.services.purchase_fulfilment_service")
    except ImportError:
        raise AssertionError("The approved managed association API is missing") from None


class CrossborderProgressTests(unittest.TestCase):
    def setUp(self):
        self.memory = NativeMemory()
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        def throw(message, exc=frappe.ValidationError, **kwargs): raise exc(message)
        for item in [patch.object(frappe, "db", self.memory.db), patch.object(frappe, "get_all", side_effect=self.memory.rows),
                     patch.object(frappe, "get_list", side_effect=self.memory.rows), patch.object(frappe, "get_doc", side_effect=self.memory.get_doc),
                     patch.object(frappe, "new_doc", side_effect=lambda dt: NativeDoc(self.memory, {"doctype": dt})),
                     patch.object(frappe, "get_meta", side_effect=self.memory.meta), patch.object(frappe, "throw", side_effect=throw),
                     patch.object(frappe, "has_permission", return_value=True), patch.object(frappe, "flags", frappe._dict()),
                     patch.object(frappe, "session", frappe._dict(user="buyer@example.test")),
                     patch.object(payment, "get_permitted_fields", side_effect=self.memory.fields),
                     patch.object(progress, "get_permitted_fields", side_effect=self.memory.fields),
                     patch("deeplinkerp_branding.services.purchase_fulfilment_service.get_permitted_fields", side_effect=self.memory.fields),
                     patch("frappe.permissions.get_user_permissions", return_value={}),
                     patch.object(frappe.utils, "now_datetime", return_value="2026-10-07 11:00:00")]:
            self.stack.enter_context(item)
        self.memory.po()

    def association(self, **changes):
        self.memory.po("INT", "FACTORY", "INTERNAL", qty=10, currency="MXN")
        self.memory.add("Supplier", "INTERNAL", is_internal_supplier=1, represents_company="BUYER", disabled=0)
        values = dict(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
            beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT", internal_item="INT-I",
            allocated_qty=10, expected_modified="v1", expected_internal_modified="v1")
        values.update(changes)
        return api().save_link(**values)

    def test_invoice_items_are_indexed_once_and_batch_queries_do_not_grow_per_order(self):
        for index in range(50):
            name = "PO" + str(index); self.memory.po(name); self.memory.invoice("PI" + str(index), name, outstanding=40)
        with patch.object(progress, "invoice_balance", wraps=payment.invoice_balance) as balance:
            result = progress.get_order_progress(["PO" + str(index) for index in range(50)])
        self.assertEqual(result["PO49"]["settled"], 60)
        self.assertEqual(balance.call_count, 50)
        self.assertLessEqual(self.memory.invoice_iterations, 100, "each PI.items must be traversed once, not once per PO")
        self.assertLessEqual(len(self.memory.queries), 20)

    def test_reconciled_po_advance_is_not_counted_twice_and_private_invoice_not_returned(self):
        self.memory.invoice(outstanding=60)
        self.memory.add("Payment Entry", "PE", company="BUYER", party="EXTERNAL", party_type="Supplier",
            payment_type="Pay", docstatus=1, paid_to_account_currency="CNY",
            references=[dict(reference_doctype="Purchase Invoice", reference_name="PI", allocated_amount=40)])
        self.memory.denied.add(("Purchase Invoice", "PI", "read"))
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(result["settled"], 40)
        self.assertNotIn("PI", json.dumps(result)); self.assertNotIn("PE", json.dumps(result))

    def test_external_paid_does_not_clear_internal_payable_and_changed_price_invalidates_confirmation(self):
        record = self.association()
        self.memory.invoice(outstanding=0)
        self.memory.invoice("INT-PI", "INT", currency="MXN", outstanding=80)
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(result["external"]["settled"], 100)
        self.assertEqual(result["internal"][0]["payable_outstanding"], 80)
        self.assertEqual(result["internal"][0]["currency"], "MXN")
        self.memory.records["Purchase Order", "INT"]["modified"] = "v2"
        for child in self.memory.children["Purchase Order Item"]:
            if child["parent"] == "INT": child["rate"] = 20
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertIsNone(result["internal"][0]["payable_outstanding"])
        self.assertEqual(result["internal"][0]["state"], "price_stale")

    def test_draft_quote_or_unconfirmed_price_never_becomes_internal_ap(self):
        record = self.association()
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertIsNone(result["internal"][0]["payable_outstanding"])
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(result["internal"][0]["state"], "awaiting_invoice")
        self.assertIsNone(result["internal"][0]["payable_outstanding"])

    def test_partial_internal_coverage_never_assigns_the_whole_invoice_balance(self):
        record = self.association(allocated_qty=4)
        self.memory.invoice("INT-PI", "INT", currency="MXN", outstanding=80)
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(result["internal"][0]["state"], "shared")
        self.assertIsNone(result["internal"][0]["payable_outstanding"])

    def test_requested_denied_po_fails_whole_call_and_denied_linked_company_has_no_signal(self):
        self.association()
        self.memory.denied.add(("Company", "FACTORY", "read"))
        result = progress.get_order_progress(["EXT"])["EXT"]
        text = json.dumps(result)
        self.assertNotIn("FACTORY", text); self.assertNotIn("INT", text)
        self.assertEqual(result["internal"][0]["state"], "restricted")
        self.memory.denied.add(("Purchase Order", "EXT", "read"))
        with self.assertRaises(frappe.PermissionError): progress.get_order_progress(["EXT"])

    def test_company_user_permissions_apply_even_to_source_authorized_summary(self):
        with patch("frappe.permissions.get_user_permissions", return_value={"Company": [frappe._dict(doc="OTHER")]}):
            with self.assertRaises(frappe.PermissionError): progress.get_order_progress(["EXT"])

    def test_hidden_native_item_fields_do_not_leak_internal_price_or_names(self):
        self.association()
        self.memory.hidden["Purchase Order Item", "read"] = {"rate"}
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertNotIn("FACTORY", json.dumps(result))
        self.assertEqual(result["internal"][0]["state"], "restricted")

    def test_detail_and_candidates_do_not_read_unrequired_hidden_receipt_quantity(self):
        record = self.association()
        self.memory.hidden["Purchase Order Item", "read"] = {"received_qty"}
        self.memory.records["Purchase Order", "INT"]["items"][0]["received_qty"] = 917

        class ProtectedItem(frappe._dict):
            def get(self, field, default=None):
                if field == "received_qty":
                    raise AssertionError("a hidden, unrequired PO Item field must not be read")
                return super().get(field, default)

        def authorized_doc(*args, **kwargs):
            doc = self.memory.get_doc(*args, **kwargs)
            if doc.doctype == "Purchase Order":
                doc.items = [ProtectedItem(item) for item in doc.items]
            return doc

        with patch.object(frappe, "get_doc", side_effect=authorized_doc):
            detail = api().get_link_detail(record["name"])
            candidates = api().get_link_candidates("EXT", "FACTORY")
        self.assertNotIn("received_qty", detail["native_internal"]["items"][0])
        self.assertNotIn("received_qty", candidates["purchase_orders"][0]["items"][0])
        self.assertNotIn("917", json.dumps((detail, candidates)))

    def test_cancelled_return_shared_or_cross_currency_never_invent_exact_external_balance(self):
        for change in ({"is_return": 1}, {"docstatus": 2}, {"currency": "USD", "party_account_currency": "USD"},
                       {"items": [dict(purchase_order="EXT"), dict(purchase_order="OTHER")]}):
            self.memory.invoice()
            self.memory.records["Purchase Invoice", "PI"].update(change)
            if "items" in change:
                self.memory.children["Purchase Invoice Item"] = [dict(parent="PI", parenttype="Purchase Invoice",
                    parentfield="items", idx=index, **item) for index, item in enumerate(change["items"], 1)]
            result = progress.get_order_progress(["EXT"])["EXT"]
            self.assertIsNone(result["settled"])
            self.assertFalse(result["settlement_exact"])

    def test_max100_and_duplicate_native_names_do_not_create_duplicate_reads(self):
        with self.assertRaises(frappe.ValidationError): progress.get_order_progress(["EXT"] * 101)
        result = progress.get_order_progress(["EXT", "EXT"])
        self.assertEqual(list(result), ["EXT"])
        self.assertEqual(sum(dt == "Purchase Order" for dt, _ in self.memory.queries), 1)

    def test_private_list_batch_exceeds100_without_rescanning_related_edges(self):
        batch = getattr(progress, "_get_order_progress_batch", None)
        self.assertTrue(callable(batch), "the unified list needs the shared private authorized batch core")
        for size in (500, 2500):
            with self.subTest(size=size):
                self.memory.records.clear(); self.memory.children.clear(); self.memory.queries.clear()
                for index in range(size):
                    name = "PO" + str(index); self.memory.po(name)
                    self.memory.invoice("PI" + str(index), name, outstanding=40)
                result = batch(["PO" + str(index) for index in range(size)])
                self.assertEqual(result["PO" + str(size - 1)]["external"]["order_unpaid"], 40)
                for doctype in ("Purchase Invoice Item", "Payment Entry Reference", "Purchase Receipt Item"):
                    self.assertEqual(sum(dt == doctype and "parent" not in (filters or {}) for dt, filters in self.memory.queries), 1,
                        "hydration may batch parents, but it must not rescan all edges per100")

    def test_private_list_batch_contains_single_denied_company_or_financial_row(self):
        batch = getattr(progress, "_get_order_progress_batch", None)
        self.assertTrue(callable(batch), "missing private restricted-row projection")
        self.memory.po("DENIED", "HIDDEN-COMPANY", qty=917)
        self.memory.denied.add(("Company", "HIDDEN-COMPANY", "read"))
        self.memory.invoice(outstanding=40)
        rows = batch(["EXT", "DENIED"])
        self.assertEqual(rows["EXT"]["order_unpaid"], 40)
        restricted = rows["DENIED"]
        self.assertEqual(restricted["state"], "restricted")
        self.assertTrue(restricted["review_required"])
        self.assertNotIn("HIDDEN-COMPANY", json.dumps(restricted)); self.assertNotIn("917", json.dumps(restricted))
        self.memory.denied.clear(); self.memory.hidden["Purchase Order", "read"] = {"grand_total"}
        rows = batch(["EXT", "DENIED"])
        self.assertTrue(all(row["state"] == "restricted" for row in rows.values()))
        with self.assertRaises(frappe.PermissionError):
            progress.get_order_progress(["EXT", "DENIED"])

    def test_private_list_batch_does_not_swallow_database_or_validation_errors(self):
        batch = getattr(progress, "_get_order_progress_batch", None)
        self.assertTrue(callable(batch))
        for error in (RuntimeError("database unavailable"), frappe.ValidationError("quota exceeded")):
            with self.subTest(error=error), patch.object(self.memory.db, "get_values", side_effect=error):
                with self.assertRaises(type(error)):
                    batch(["EXT"])

    def test_stock_updating_invoice_or_native_received_signal_without_pr_requires_review_not_zero(self):
        self.memory.invoice(update_stock=1)
        self.memory.records["Purchase Order", "EXT"]["per_received"] = 40
        self.memory.children["Purchase Order Item"][0]["received_qty"] = 4
        row = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(row["domestic_receipt"]["state"], "review")
        self.assertEqual(row["domestic_receipt"]["quantities"], [])
        self.assertIn("原生", "；".join(row["domestic_receipt"]["warnings"]))

    def test_factory_pending_uses_explicit_allocations_and_counts_same_native_item_receipt_once(self):
        first = self.association(allocated_qty=4)
        second = api().save_link(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
            beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT", internal_item="INT-I",
            allocated_qty=6, expected_modified="v1", expected_internal_modified="v1")
        self.memory.add("Purchase Receipt", "INT-PR", company="FACTORY", supplier="INTERNAL", docstatus=1,
            is_return=0, items=[dict(purchase_order="INT", purchase_order_item="INT-I", qty=4, stock_qty=4,
                uom="Nos", stock_uom="Nos")])
        self.memory.received("INT", 4, 40)
        row = progress.get_order_progress(["EXT"])["EXT"]
        factory = row.get("factory_receipt", {})
        self.assertEqual(factory.get("state"), "exact")
        self.assertEqual(len(factory["quantities"]), 1)
        self.assertEqual(factory["quantities"][0]["pending_stock_qty"], 6)
        self.assertEqual(factory["quantities"][0]["received_stock_qty"], 4)
        self.assertIn("factory_pending", row["progress_phases"])
        self.assertNotIn("internal_unsettled", row["progress_phases"], "unconfirmed prices are not internal AP")

    def test_no_factory_links_or_incomparable_stock_uom_remains_unknown_and_review(self):
        row = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(row.get("factory_receipt", {}).get("state"), "unknown")
        self.assertTrue(row.get("review_required"))
        record = self.association()
        self.memory.add("Purchase Receipt", "INT-PR", company="FACTORY", supplier="INTERNAL", docstatus=1,
            is_return=0, items=[dict(purchase_order="INT", purchase_order_item="INT-I", qty=4, stock_qty=4,
                uom="Kg", stock_uom="Kg")])
        row = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(row["factory_receipt"]["state"], "unknown")
        self.assertNotIn("factory_pending", row["progress_phases"])

    def test_factory_pending_requires_effective_submitted_native_source_and_target_orders(self):
        self.association()
        self.memory.add("Purchase Receipt", "FACTORY-PR", company="FACTORY", supplier="INTERNAL", docstatus=1,
            is_return=0, items=[dict(purchase_order="INT", purchase_order_item="INT-I", qty=4, stock_qty=4,
                uom="Nos", stock_uom="Nos")])
        self.memory.received("INT", 4, 40)
        active = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(active["factory_receipt"]["state"], "exact")
        self.assertEqual(active["factory_receipt"]["quantities"][0]["pending_stock_qty"], 6)
        for name in ("INT", "EXT"):
            for docstatus, status in ((0, "Draft"), (2, "Cancelled"), (1, "Closed"), (1, "On Hold")):
                with self.subTest(order=name, docstatus=docstatus, status=status):
                    order = self.memory.records["Purchase Order", name]
                    order.update(docstatus=docstatus, status=status)
                    try:
                        row = progress.get_order_progress(["EXT"])["EXT"]
                        self.assertEqual(row["factory_receipt"]["state"], "unknown")
                        self.assertEqual(row["factory_receipt"]["quantities"], [])
                        self.assertNotIn("factory_pending", row["progress_phases"])
                        self.assertTrue(row["review_required"])
                        self.assertIn("原生订单", "；".join(row["factory_receipt"]["warnings"]))
                    finally:
                        order.update(docstatus=1, status="To Receive and Bill")

    def test_batch_source_roles_match_exact_accessible_names_and_labels_once_and_keep_confirmed_separate(self):
        from deeplinkerp_branding.services import purchase_source_service as source_service
        batch = getattr(source_service, "_role_projections", None)
        self.assertTrue(callable(batch), "OA rows need one request-local Company/Project role projection")
        self.memory.add("Company", "FACTORY", company_name="Factory label")
        self.memory.add("Company", "PROPOSAL", company_name="Proposal")
        self.memory.add("Project", "PROJECT", project_name="Molds", company="BUYER", is_active="Yes")
        rows = [dict(name="OA" + str(index), target_company="PROPOSAL", backfill_imported=1,
            custom_purchase_company_confirmed=0) for index in range(500)]
        sources = {row["name"]: {"beneficiary_company": "Factory label", "project": "Molds"} for row in rows}
        permitted = {"target_company", "backfill_imported", source_service.CONFIRMED_FIELD, source_service.BENEFICIARY_FIELD,
            source_service.PROJECT_FIELD, source_service.PROPOSAL_FIELD, "purchase_order", "project"}
        with patch.object(source_service, "get_permitted_fields", side_effect=self.memory.fields), patch.object(frappe, "has_permission", return_value=True) as native_access:
            result = batch(rows, sources, permitted, {"PO": {"company": "BUYER"}})
        self.assertIsNone(result["OA0"]["purchasing_company"])
        self.assertFalse(result["OA0"]["company_confirmed"])
        self.assertEqual(result["OA0"]["buyer_company_proposal"], "PROPOSAL")
        self.assertIsNone(result["OA0"]["beneficiary_company"])
        self.assertEqual(result["OA0"]["beneficiary_company_candidate"], "FACTORY")
        self.assertEqual(result["OA0"]["project_status"], "incompatible", "a proposed buyer is not the native procurement company")
        self.assertLessEqual(native_access.call_count, 2, "doctype read authority is invariant across the500 source rows")
        self.assertLessEqual(sum(dt == "Project" and "name" not in (filters or {}) for dt, filters in self.memory.queries), 1)
        rows[0].update(purchase_order="PO", custom_purchase_beneficiary_company="FACTORY", custom_purchase_project="PROJECT")
        with patch.object(source_service, "get_permitted_fields", side_effect=self.memory.fields):
            linked = batch(rows[:1], sources, permitted, {"PO": {"company": "BUYER"}})["OA0"]
        self.assertEqual(linked["purchasing_company"], "BUYER")
        self.assertEqual(linked["project_candidate"], "PROJECT")
        self.assertEqual(linked["beneficiary_company"], "FACTORY")

    def test_batch_source_roles_respect_native_record_company_and_display_field_acl_and_ambiguity(self):
        from deeplinkerp_branding.services import purchase_source_service as source_service
        batch = getattr(source_service, "_role_projections", None)
        self.assertTrue(callable(batch))
        self.memory.add("Company", "FACTORY-A", company_name="Factory")
        self.memory.add("Company", "FACTORY-B", company_name="Factory")
        self.memory.add("Project", "PROJECT", project_name="Molds", company="BUYER", is_active="No")
        rows = [dict(name="OA", target_company="BUYER", custom_purchase_company_confirmed=1)]
        source = {"OA": {"beneficiary_company": "Factory", "project": "Molds"}}
        permitted = {"target_company", source_service.CONFIRMED_FIELD, source_service.BENEFICIARY_FIELD, source_service.PROJECT_FIELD}
        with patch.object(source_service, "get_permitted_fields", side_effect=self.memory.fields):
            role = batch(rows, source, permitted, {})["OA"]
        self.assertEqual(role["beneficiary_company_status"], "ambiguous")
        self.assertEqual(role["project_status"], "incompatible")
        self.memory.hidden["Company", "read"] = {"company_name"}
        self.memory.denied.add(("Company", "BUYER", "read"))
        with patch.object(source_service, "get_permitted_fields", side_effect=self.memory.fields):
            role = batch(rows, source, permitted, {})["OA"]
        self.assertIsNone(role["purchasing_company"])
        self.assertIsNone(role["beneficiary_company_candidate"])
        self.assertNotIn("FACTORY-A", json.dumps(role)); self.assertNotIn("FACTORY-B", json.dumps(role))

    def test_native_field_scope_is_obtained_once_per_doctype_for_all_progress_rows(self):
        record = self.association()
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        self.memory.invoice("INT-PI", "INT", currency="MXN", outstanding=80)
        calls = []
        def fields(dt, **kwargs):
            calls.append((dt, kwargs.get("parenttype")))
            return self.memory.fields(dt, **kwargs)
        with patch.object(payment, "get_permitted_fields", side_effect=fields), patch.object(progress, "get_permitted_fields", side_effect=fields):
            result = progress.get_order_progress(["EXT"], include_items=True)["EXT"]
            self.assertIn("warehouse", result["item_fields"])
            self.assertEqual(result["items"][0]["name"], self.memory.records["Purchase Order", "EXT"]["items"][0]["name"])
        for dt in ("Purchase Order", "Purchase Order Item", "Company", "Purchase Invoice", "Purchase Invoice Item"):
            self.assertEqual(sum(name == dt for name, _ in calls), 1, "field permission must be request-local, not per row or projection")

    def test_nonstock_item_or_denied_item_stock_flag_cannot_claim_factory_stock_pending(self):
        self.association()
        self.memory.records["Item", "M"]["is_stock_item"] = 0
        row = progress.get_order_progress(["EXT"])["EXT"]
        self.assertNotIn("factory_pending", row.get("progress_phases", []))
        self.assertNotEqual(row.get("factory_receipt", {}).get("state"), "exact")
        self.memory.records["Item", "M"]["is_stock_item"] = 1
        self.memory.hidden["Item", "read"] = {"is_stock_item"}
        row = progress.get_order_progress(["EXT"])["EXT"]
        self.assertNotIn("factory_pending", row.get("progress_phases", []))
        self.assertTrue(row.get("review_required"))

    def test_logistics_provenance_fixed_projection_keeps_author_time_source_but_not_arbitrary_snapshot_keys(self):
        link = {"name": "LINK", "beneficiary_company": "FACTORY", "cost_batch": "BATCH", "coverage": {"exact": True},
            "manual_nodes": [], "snapshot": {"state": "reported", "quantities": [{"qty": 2, "uom": "Nos", "destination": "FACTORY"}],
                "private": "PRIVATE", "timeline": [{"source_id": "COMMENT", "raw": {"user_name": "Author", "operation_time": "2026-10-07",
                    "remark": "已到货 FACTORY，2件", "bank_account": "SECRET"}}]}}
        row = progress._logistics_row(link, {})
        self.assertEqual(row.get("provenance"), [{"source_id": "COMMENT", "author": "Author", "time": "2026-10-07", "remark": "已到货 FACTORY，2件"}])
        self.assertNotIn("PRIVATE", json.dumps(row)); self.assertNotIn("SECRET", json.dumps(row))

    def test_internal_ap_paid_excludes_unallocated_po_advance_while_legacy_settled_remains_compatible(self):
        record = self.association()
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        self.memory.invoice("INT-PI", "INT", currency="MXN", total=100, outstanding=80)
        self.memory.add("Payment Entry", "INT-ADV", company="FACTORY", party="INTERNAL", party_type="Supplier",
            payment_type="Pay", docstatus=1, paid_to_account_currency="MXN",
            references=[dict(reference_doctype="Purchase Order", reference_name="INT", allocated_amount=7)])
        internal = progress.get_order_progress(["EXT"])["EXT"]["internal"][0]
        self.assertEqual(internal["settled"], 27)
        self.assertEqual(internal.get("payable_settled"), 20)
        self.assertEqual(internal["payable_outstanding"], 80)

    def test_real_unified_api_shares_role_and_progress_field_scope_and_denied_link_cannot_filter_count(self):
        from deeplinkerp_branding.services import unified_purchase_service as unified
        record = self.association()
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        self.memory.invoice("INT-PI", "INT", currency="MXN", outstanding=80)
        calls = []
        def fields(dt, **kwargs):
            calls.append(dt)
            return self.memory.fields(dt, **kwargs)
        with patch.object(unified, "get_permitted_fields", side_effect=fields), patch.object(unified, "get_workflow_name", return_value=""):
            result = unified.get_unified_purchase_list(filters={"beneficiary_company": "FACTORY", "progress_phase": "internal_unsettled"})
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["rows"][0]["role_context"]["beneficiary_companies"], ["FACTORY"])
        self.assertEqual(result["rows"][0]["order_progress"]["internal"][0]["payable_outstanding"], 80)
        self.assertEqual(calls.count("Purchase Order"), 1)
        self.assertEqual(calls.count("Company"), 1)
        self.memory.denied.add(("Company", "FACTORY", "read"))
        with patch.object(unified, "get_permitted_fields", side_effect=fields), patch.object(unified, "get_workflow_name", return_value=""):
            result = unified.get_unified_purchase_list(filters={"beneficiary_company": "FACTORY", "progress_phase": "internal_unsettled"})
        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["totals"]["orders"], [])

    def test_real_unified_company_denial_redacts_before_totals_filters_and_pagination_without_full_progress(self):
        from deeplinkerp_branding.services import unified_purchase_service as unified
        for index in range(149):
            self.memory.po("PO-" + str(index))
        self.memory.denied.add(("Company", "BUYER", "read"))
        with patch.object(unified, "get_permitted_fields", side_effect=self.memory.fields), patch.object(unified, "get_workflow_name", return_value=""), \
             patch.object(unified, "_load_order_progress", wraps=unified._load_order_progress) as batch:
            ordinary = unified.get_unified_purchase_list(start=100, page_length=1)
            review = unified.get_unified_purchase_list(start=100, page_length=1, filters={"review_only": True})
            company = unified.get_unified_purchase_list(filters={"company": "BUYER"})
        self.assertEqual(ordinary["rows"][0]["company"], None)
        self.assertEqual(ordinary["rows"][0]["grand_total"], None)
        self.assertEqual(ordinary["totals"]["orders"], [])
        self.assertEqual(ordinary["totals"], review["totals"])
        self.assertEqual(ordinary["total_count"], 150)
        self.assertEqual(company["total_count"], 0)
        self.assertNotIn("BUYER", json.dumps(ordinary))
        self.assertEqual(batch.call_count, 0, "denied Company rows need only an authority projection, not financial/receipt discovery")
        self.assertFalse(any(dt in ("Purchase Invoice Item", "Payment Entry Reference", "Purchase Receipt Item") for dt, _ in self.memory.queries))

    def test_real_unified_company_scope_is_batched_while_ordinary_progress_stays_on_page(self):
        from deeplinkerp_branding.services import unified_purchase_service as unified
        for index in range(149):
            self.memory.po("PO-" + str(index))
        self.memory.queries.clear()
        with patch.object(unified, "get_permitted_fields", side_effect=self.memory.fields), patch.object(unified, "get_workflow_name", return_value=""), \
             patch.object(unified, "_load_order_progress", wraps=unified._load_order_progress) as batch:
            result = unified.get_unified_purchase_list(start=100, page_length=1)
        self.assertEqual(result["totals"]["orders"], [{"currency": "CNY", "amount": 15000.0}])
        self.assertEqual(batch.call_count, 1)
        self.assertEqual(batch.call_args.args[0], [result["rows"][0]["name"]])
        self.assertEqual(sum(dt == "Company" for dt, _ in self.memory.queries), 1)
        for dt, filters in self.memory.queries:
            if dt in ("Purchase Receipt Item", "Purchase Invoice Item") and filters and "purchase_order" in filters:
                self.assertEqual(filters["purchase_order"][1], [result["rows"][0]["name"]])

    def test_real_unified_reversal_projection_selects_only_orders_with_pending_pointer(self):
        from deeplinkerp_branding.services import unified_purchase_service as unified
        from deeplinkerp_branding.services import purchase_reversal_progress as reversal
        pointer = "custom_purchase_reversal_operation"
        self.memory.records["Purchase Order", "EXT"][pointer] = "PENDING"
        self.memory.po("EMPTY")[pointer] = ""
        self.memory.po("UNBOUND")
        with patch.object(unified, "get_permitted_fields", side_effect=self.memory.fields), \
             patch.object(unified, "get_workflow_name", return_value=""), \
             patch.object(reversal, "projection", return_value={"stage": "waiting_inventory"}):
            result = unified.get_unified_purchase_list()
        rows = {row["name"]: row for row in result["rows"]}
        self.assertEqual(rows["EXT"]["reversal"], {"stage": "waiting_inventory"})
        self.assertIsNone(rows["EMPTY"]["reversal"])
        self.assertIsNone(rows["UNBOUND"]["reversal"])
        self.assertEqual(self.memory.locks, [("Purchase Order", "EXT")])

    def test_source_required_fields_restrict_before_quick_filters_totals_and_page_progress(self):
        from deeplinkerp_branding.services import unified_purchase_service as unified
        for field in sorted(PO_FIELDS):
            with self.subTest(field=field):
                self.memory.hidden["Purchase Order", "read"] = {field}
                self.memory.queries.clear()
                calls = []
                def fields(dt, **kwargs):
                    calls.append(dt)
                    return self.memory.fields(dt, **kwargs)
                with patch.object(unified, "get_permitted_fields", side_effect=fields), patch.object(unified, "get_workflow_name", return_value=""), \
                     patch.object(unified, "_load_order_progress", wraps=unified._load_order_progress) as batch:
                    ordinary = unified.get_unified_purchase_list()
                    review = unified.get_unified_purchase_list(filters={"review_only": True})
                    company = unified.get_unified_purchase_list(filters={"company": "BUYER"})
                self.assertEqual(ordinary["rows"][0]["order_progress"]["state"], "restricted")
                self.assertIsNone(ordinary["rows"][0]["company"])
                self.assertIsNone(ordinary["rows"][0]["grand_total"])
                self.assertEqual(ordinary["totals"]["orders"], [])
                self.assertEqual(ordinary["totals"], review["totals"])
                self.assertEqual(company["total_count"], 0)
                self.assertEqual(batch.call_count, 0)
                self.assertEqual(calls.count("Purchase Order"), 3, "one field scope per request, not per row/projection")
                self.assertFalse(any(dt in ("Purchase Invoice Item", "Payment Entry Reference", "Purchase Receipt Item") for dt, _ in self.memory.queries))

    def test_factory_partial_pr_proof_must_match_authorized_native_received_counter(self):
        self.association()
        self.memory.add("Purchase Receipt", "INT-PR", company="FACTORY", supplier="INTERNAL", docstatus=1,
            is_return=0, items=[dict(purchase_order="INT", purchase_order_item="INT-I", qty=4, stock_qty=4,
                uom="Nos", stock_uom="Nos")])
        self.memory.received("INT", 4, 40)
        exact = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(exact["factory_receipt"]["state"], "exact")
        self.assertEqual(exact["factory_receipt"]["quantities"][0]["pending_stock_qty"], 6)
        for received, percent, hidden in ((10, 100, set()), (None, 40, set()), (4, 40, {"received_qty"}), (4, 100, set())):
            with self.subTest(received=received, percent=percent, hidden=hidden):
                self.memory.received("INT", received, percent)
                self.memory.hidden["Purchase Order Item", "read"] = hidden
                row = progress.get_order_progress(["EXT"])["EXT"]
                self.assertEqual(row["factory_receipt"]["state"], "unknown")
                self.assertEqual(row["factory_receipt"]["quantities"], [])
                self.assertNotIn("factory_pending", row["progress_phases"])
                self.assertTrue(row["factory_receipt"]["warnings"])
                self.assertEqual(row["receipt_logistics"][0]["native_receipt"]["quantities"][0]["stock_qty"], 4,
                    "keep the original authorized PR proof without claiming complete factory receipt")

    def test_factory_receipt_counter_uses_native_stock_conversion_and_keeps_partial_or_returned_proof_unknown(self):
        self.memory.po("INT", "FACTORY", "INTERNAL", currency="MXN")
        for name in ("EXT", "INT"):
            self.memory.records["Purchase Order", name]["items"][0].update(uom="Box", conversion_factor=2)
        for item in self.memory.children["Purchase Order Item"]:
            item.update(uom="Box", conversion_factor=2)
        self.memory.add("Supplier", "INTERNAL", is_internal_supplier=1, represents_company="BUYER", disabled=0)
        record = api().save_link(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
            beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT", internal_item="INT-I",
            allocated_qty=10, expected_modified="v1", expected_internal_modified="v1")
        self.memory.add("Purchase Receipt", "INT-PR", company="FACTORY", supplier="INTERNAL", docstatus=1,
            is_return=0, items=[dict(purchase_order="INT", purchase_order_item="INT-I", qty=4, stock_qty=8,
                uom="Box", stock_uom="Nos")])
        self.memory.received("INT", 4, 40)
        row = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(row["factory_receipt"]["state"], "exact")
        self.assertEqual(row["factory_receipt"]["quantities"][0]["received_stock_qty"], 8)
        self.assertEqual(row["factory_receipt"]["quantities"][0]["pending_stock_qty"], 12)
        self.memory.records["Purchase Receipt", "INT-PR"]["is_return"] = 1
        row = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(row["factory_receipt"]["state"], "unknown")
        self.assertNotIn("factory_pending", row["progress_phases"])
        self.memory.records["Purchase Receipt", "INT-PR"]["is_return"] = 0
        link = self.memory.records[LINK, record["name"]]
        api().save_link(**{**{key: link.get(key) for key in ("external_order", "external_item", "purchasing_company", "beneficiary_company", "flow_kind", "internal_order", "internal_item")},
            "name": link["name"], "allocated_qty": 5, "expected_modified": "v1", "expected_internal_modified": "v1", "expected_link_modified": link["modified"]})
        row = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(row["factory_receipt"]["state"], "unknown")
        self.assertNotIn("factory_pending", row["progress_phases"])

    def test_company_denied_row_and_export_projection_do_not_retain_source_financial_warning_values(self):
        from deeplinkerp_branding.services import unified_purchase_service as unified
        self.memory.denied.add(("Company", "BUYER", "read"))
        self.memory.add("OA Purchase Request", "OA", purchase_order="EXT", target_company="BUYER",
            custom_purchase_source_id="source", custom_purchase_company_confirmed=1, oa_code="DT",
            currency="CNY", detail_total_amount=237, payment_amount=237, items_json="[]",
            custom_purchase_source_json=json.dumps({"version": "v1", "currency": "CNY", "detail_total_amount": "237",
                "issues": ["BUYER 原金额 237 待核对"]}))
        with patch.object(unified, "get_permitted_fields", side_effect=self.memory.fields), patch.object(unified, "get_workflow_name", return_value=""):
            result = unified.get_unified_purchase_list()
            data = unified._export_data(result["rows"], ["order_context", "external_payment"])
        self.assertEqual(result["totals"]["oa"], [])
        self.assertNotIn("BUYER", json.dumps(result))
        self.assertNotIn("237", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("BUYER", str(data))
        self.assertNotIn("237", str(data))

    def test_source_role_field_acl_blocks_hidden_confirmed_beneficiary_from_list_and_count(self):
        from deeplinkerp_branding.services import unified_purchase_service as unified
        from deeplinkerp_branding.services import purchase_source_service as source_service
        self.memory.add("Company", "FACTORY", company_name="Factory")
        self.memory.add("OA Purchase Request", "OA", target_company="BUYER", purchase_order="EXT", oa_code="DT-ORIGINAL",
            custom_purchase_source_id="source", custom_purchase_company_confirmed=1,
            custom_purchase_beneficiary_company="FACTORY", custom_purchase_source_json=json.dumps({"version": "v1", "beneficiary_company": "Factory", "project": "Raw"}))
        self.memory.hidden["OA Purchase Request", "read"] = {source_service.BENEFICIARY_FIELD}
        with patch.object(unified, "get_permitted_fields", side_effect=self.memory.fields), patch.object(unified, "get_workflow_name", return_value=""):
            result = unified.get_unified_purchase_list(filters={"beneficiary_company": "FACTORY"})
            unfiltered = unified.get_unified_purchase_list()
        self.assertEqual(result["total_count"], 0)
        self.assertNotIn("Factory", json.dumps(unfiltered)); self.assertNotIn("FACTORY", json.dumps(unfiltered))

    def test_forward_native_po_link_confirms_buyer_for_role_projection_without_rewriting_source_hint(self):
        from deeplinkerp_branding.services import unified_purchase_service as unified
        self.memory.add("Company", "PROPOSAL")
        self.memory.add("Project", "PROJECT", project_name="Molds", company="BUYER", is_active="Yes")
        self.memory.records["Purchase Order", "EXT"]["custom_oa_purchase_expense"] = "OA"
        self.memory.add("OA Purchase Request", "OA", target_company="PROPOSAL", purchase_order=None, oa_code="DT-ORIGINAL",
            backfill_imported=1, custom_purchase_source_id="source", custom_purchase_company_confirmed=0,
            custom_purchase_project=None, custom_purchase_source_json=json.dumps({"version": "v1", "project": "Molds"}))
        with patch.object(unified, "get_permitted_fields", side_effect=self.memory.fields), patch.object(unified, "get_workflow_name", return_value=""):
            row = unified.get_unified_purchase_list()["rows"][0]
        role = row["role_context"]
        self.assertEqual(role["purchasing_company"], "BUYER")
        self.assertEqual(role["project_candidate"], "PROJECT")
        self.assertNotIn("采购公司待确认", "；".join(role["role_warnings"]))
        self.assertEqual(self.memory.records["OA Purchase Request", "OA"]["target_company"], "PROPOSAL")

    def test_bulk_record_identity_dedup_does_not_sort_related_names(self):
        class NativeIdentity(str):
            comparisons = 0
            def __lt__(self, other):
                type(self).comparisons += 1
                return super().__lt__(other)
        names = [NativeIdentity("PO" + str((index * 37) % 100)) for index in range(100)]
        for name in names:
            self.memory.po(name)
        reader = payment._RecordReader()
        reader.preload("Purchase Order", names)
        self.assertEqual(len(reader.docs), 100)
        self.assertEqual(NativeIdentity.comparisons, 0, "linear identity hydration requires no ordering comparisons")

    def test_stale_native_version_and_native_master_mismatch_refuse_association(self):
        with self.assertRaisesRegex(frappe.ValidationError, "变化"):
            self.association(expected_modified="old")
        self.memory.add("Supplier", "INTERNAL", is_internal_supplier=0, represents_company="OTHER", disabled=0)
        # Use the public API directly to preserve the intentionally invalid master.
        with self.assertRaisesRegex(frappe.ValidationError, "内部供应商"):
            api().save_link(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
                beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT", internal_item="INT-I",
                allocated_qty=10, expected_modified="v1", expected_internal_modified="v1")
        self.assertFalse(any(kind == LINK for kind, _ in self.memory.records))

    def test_positive_quantity_that_underflows_or_exceeds_data_storage_never_reaches_audit_or_insert(self):
        service = api()
        original = copy.deepcopy(self.memory.records)
        for qty in ("1e-1000100", "1e-1000"):
            self.memory.records = copy.deepcopy(original)
            with self.subTest(qty=qty), patch.object(service, "_audit", wraps=service._audit) as audit, \
                 patch.object(service, "_save", wraps=service._save) as save:
                with self.assertRaises(frappe.ValidationError):
                    self.association(allocated_qty=qty)
                audit.assert_not_called(); save.assert_not_called()
                self.assertFalse(any(kind == LINK for kind, _ in self.memory.records))

    def test_save_link_reuses_each_locked_native_order_projection_once(self):
        self.memory.po("INT", "FACTORY", "INTERNAL", currency="MXN")
        self.memory.add("Supplier", "INTERNAL", is_internal_supplier=1, represents_company="BUYER", disabled=0)
        self.memory.add("Customer", "INTERNAL-CUSTOMER", is_internal_customer=1, represents_company="FACTORY", disabled=0)
        self.memory.add("Sales Order", "SO", company="BUYER", customer="INTERNAL-CUSTOMER", currency="MXN", grand_total=100,
            items=[dict(name="SO-I", item_code="M", qty=10, uom="Nos", stock_uom="Nos", conversion_factor=1, rate=10, amount=100)])
        service = api()
        with patch.object(service, "order_data", wraps=service.order_data) as project:
            saved = service.save_link(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
                beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT", internal_item="INT-I",
                allocated_qty=10, expected_modified="v1", expected_internal_modified="v1", seller_order="SO",
                seller_item="SO-I", expected_seller_modified="v1")
        self.assertEqual(saved["active"], 1)
        self.assertEqual([call.args[0].name for call in project.call_args_list], ["EXT", "INT"])
        self.memory.po("LOCAL", "FACTORY", "INTERNAL", currency="MXN")
        with patch.object(service, "order_data", wraps=service.order_data) as project:
            service.save_link(external_order="LOCAL", external_item="LOCAL-I", purchasing_company="FACTORY",
                beneficiary_company="FACTORY", flow_kind="internal_local", internal_order="LOCAL", internal_item="LOCAL-I",
                allocated_qty=10, expected_modified="v1", expected_internal_modified="v1")
        self.assertEqual([call.args[0].name for call in project.call_args_list], ["LOCAL"])

    def test_manual_quantity_underflow_never_changes_stored_nodes_or_registers_audit(self):
        record = self.association()
        original = copy.deepcopy(self.memory.records[LINK, record["name"]])
        service = api()
        with patch.object(service, "_audit", wraps=service._audit) as audit, \
             patch.object(service, "_save", wraps=service._save) as save:
            with self.assertRaises(frappe.ValidationError):
                service.set_manual_node(record["name"], record["modified"], "reported_arrival", "人工核对",
                                        qty="1e-1000100", uom="Nos")
        audit.assert_not_called(); save.assert_not_called()
        self.assertEqual(self.memory.records[LINK, record["name"]], original)

    def test_managed_association_writes_need_native_po_write_and_field_permission(self):
        self.memory.denied.add(("Purchase Order", "EXT", "write"))
        with self.assertRaises(frappe.PermissionError): self.association()
        self.memory.denied.clear(); self.memory.hidden["Purchase Order", "write"] = {"items"}
        with self.assertRaises(frappe.PermissionError): self.association()
        self.assertFalse(any(kind == LINK for kind, _ in self.memory.records))

    def test_rest_forgery_delete_and_rename_refused_and_json_is_private(self):
        service = api()
        forged = NativeDoc(self.memory, dict(doctype=LINK, name="FORGED", external_order="EXT", snapshot_json='{}'))
        for method in (service.validate_managed_link, service.protect_link_identity):
            with self.assertRaises(frappe.PermissionError): method(forged)
        from pathlib import Path
        definition = json.loads((Path(progress.__file__).parents[1] / "deeplinkerp_branding" / "doctype" /
            "purchase_fulfilment_link" / "purchase_fulfilment_link.json").read_text())
        self.assertFalse(definition["allow_rename"])
        for field in definition["fields"]:
            if field["fieldname"].endswith("_json"):
                self.assertEqual(field["permlevel"], 9)

    def test_manual_node_has_server_audit_and_refresh_preserves_it_when_cost_app_missing(self):
        record = self.association()
        updated = api().set_manual_node(record["name"], record["modified"], "reported_arrival", "工厂电话已核对", qty=4, uom="Nos")
        raw = self.memory.records[LINK, record["name"]]
        manual = json.loads(raw["manual_nodes_json"])
        self.assertEqual(manual[-1]["by"], "buyer@example.test")
        self.assertEqual(manual[-1]["on"], "2026-10-07 11:00:00")
        result = api().refresh_logistics(record["name"], updated["modified"])
        self.assertEqual(self.memory.records[LINK, record["name"]]["manual_nodes_json"], raw["manual_nodes_json"])
        self.assertTrue(result["warnings"])
        self.assertFalse(any(kind in ("Purchase Receipt", "Payment Entry", "GL Entry") for kind, _ in self.memory.records))

    def test_disable_keeps_audit_and_releases_quantity_without_deleting_link(self):
        record = self.association()
        result = api().disable_link(record["name"], record["modified"], "改为另一工厂")
        self.assertEqual(result["active"], 0)
        self.assertIn((LINK, record["name"]), self.memory.records)
        audit = json.loads(self.memory.records[LINK, record["name"]]["audit_json"])
        self.assertEqual(audit[-1]["action"], "disable")

    def test_whole_internal_invoice_balance_appears_once_for_multiple_native_item_links(self):
        record = self.association()
        for dt, name in (("Purchase Order", "EXT"), ("Purchase Order", "INT")):
            raw = self.memory.records[dt, name]
            raw["items"].append({**raw["items"][0], "name": name + "-J"})
            raw["grand_total"] = 200
            self.memory.add(dt, name, **{key: value for key, value in raw.items() if key not in ("doctype", "name")})
        second = api().save_link(external_order="EXT", external_item="EXT-J", purchasing_company="BUYER",
            beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT", internal_item="INT-J",
            allocated_qty=10, expected_modified="v1", expected_internal_modified="v1")
        for row in (record, second):
            api().confirm_native_price(row["name"], "v1", "v1", row["modified"])
        self.memory.invoice("INT-PI", "INT", currency="MXN", total=200, outstanding=120)
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(len(result["internal"]), 1)
        self.assertEqual(result["internal"][0]["payable_outstanding"], 120)
        self.assertEqual(len(result["internal"][0]["allocations"]), 2)

    def test_native_changed_source_quantity_or_missing_item_identity_requires_review(self):
        record = self.association()
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        for change in ({"qty": 3}, {"name": "REPLACED"}):
            child = self.memory.children["Purchase Order Item"][0]
            child.update(change)
            result = progress.get_order_progress(["EXT"])["EXT"]
            self.assertEqual(result["internal"][0]["state"], "source_stale")
            self.assertIsNone(result["internal"][0]["payable_outstanding"])

    def test_domestic_receipt_and_factory_native_receipt_remain_separate_from_logistics(self):
        self.association()
        for name, company, supplier, po, qty in (("PR-D", "BUYER", "EXTERNAL", "EXT", 10),
                                                  ("PR-M", "FACTORY", "INTERNAL", "INT", 4)):
            self.memory.add("Purchase Receipt", name, company=company, supplier=supplier, docstatus=1,
                is_return=0, items=[dict(purchase_order=po, qty=qty, stock_qty=qty, uom="Nos", stock_uom="Nos")])
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(result["domestic_receipt"]["quantities"][0]["qty"], 10)
        self.assertEqual(result["receipt_logistics"][0]["native_receipt"]["quantities"][0]["qty"], 4)
        self.assertEqual(result["receipt_logistics"][0]["reported_quantities"], [])

    def test_internal_local_factory_order_and_trade_custody_have_distinct_payment_roles(self):
        self.memory.po("LOCAL", "FACTORY", "INTERNAL", currency="MXN")
        self.memory.add("Company", "SELLER")
        self.memory.add("Supplier", "INTERNAL", is_internal_supplier=1, represents_company="SELLER", disabled=0)
        record = api().save_link(external_order="LOCAL", external_item="LOCAL-I", purchasing_company="FACTORY",
            beneficiary_company="FACTORY", flow_kind="internal_local", internal_order="LOCAL", internal_item="LOCAL-I",
            allocated_qty=10, expected_modified="v1", expected_internal_modified="v1")
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        self.memory.invoice("LOCAL-PI", "LOCAL", currency="MXN", outstanding=40)
        result = progress.get_order_progress(["LOCAL"])["LOCAL"]
        self.assertEqual(result["external"]["state"], "not_applicable")
        self.assertEqual(result["internal"][0]["payable_outstanding"], 40)
        self.memory.add("Company", "CUSTODY")
        self.memory.add("Warehouse", "WH", company="CUSTODY", is_group=0, disabled=0)
        api().save_link(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
            beneficiary_company="BUYER", flow_kind="trade_custody", allocated_qty=10, expected_modified="v1",
            custody_company="CUSTODY", custody_warehouse="WH")
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(result["internal"][0]["state"], "custody")
        self.assertIsNone(result["internal"][0]["payable_outstanding"])

    def test_link_cumulative_cap_and_shared_internal_source_are_native_item_checked(self):
        record = self.association(allocated_qty=4)
        with self.assertRaisesRegex(frappe.ValidationError, "累计"):
            api().save_link(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
                beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT", internal_item="INT-I",
                allocated_qty=7, expected_modified="v1", expected_internal_modified="v1")
        self.memory.po("EXT2", "BUYER", qty=6)
        second = api().save_link(external_order="EXT2", external_item="EXT2-I", purchasing_company="BUYER",
            beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT", internal_item="INT-I",
            allocated_qty=6, expected_modified="v1", expected_internal_modified="v1")
        for row, external in ((record, "EXT"), (second, "EXT2")):
            api().confirm_native_price(row["name"], "v1", "v1", row["modified"])
        self.memory.invoice("INT-PI", "INT", currency="MXN", outstanding=90)
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(result["internal"][0]["state"], "shared")
        self.assertIsNone(result["internal"][0]["payable_outstanding"])

    def test_allocation_caps_use_current_locked_rows_and_all_mutations_lock_parents_first(self):
        record = self.association()
        self.assertTrue(self.memory.current_reads, "allocation validation must use current locking reads")
        self.assertIn("for update", self.memory.current_reads[-1][0].lower())
        self.assertEqual(tuple(self.memory.current_reads[-1][1]), ("EXT", "INT"))
        self.memory.locks.clear()
        api().disable_link(record["name"], record["modified"], "核对另一订单")
        self.assertEqual([dt for dt, _ in self.memory.locks], ["Purchase Order", "Purchase Order", LINK])
        disabled = self.memory.records[LINK, record["name"]]
        self.memory.locks.clear()
        api().save_link(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
            beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT", internal_item="INT-I",
            allocated_qty=10, expected_modified="v1", expected_internal_modified="v1", name=record["name"],
            expected_link_modified=disabled["modified"])
        self.assertEqual([dt for dt, _ in self.memory.locks], ["Purchase Order", "Purchase Order", LINK])

    def test_payment_receipt_progress_and_remarks_do_not_invalidate_native_price_confirmation(self):
        record = self.association()
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        self.memory.invoice("INT-PI", "INT", currency="MXN", outstanding=80)
        self.memory.records["Purchase Order", "INT"].update(modified="v2", per_received=40, remarks="已收部分货")
        self.memory.records["Purchase Order", "EXT"].update(modified="v2", per_received=100, remarks="国内仓已收")
        result = progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(result["internal"][0]["state"], "payable")
        self.assertEqual(result["internal"][0]["payable_outstanding"], 80)

    def test_internal_balances_require_each_native_accounting_parent_and_child_field_permission(self):
        record = self.association()
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        self.memory.invoice("INT-PI", "INT", currency="MXN", outstanding=80)
        self.memory.add("Payment Entry", "INT-ADV", company="FACTORY", party="INTERNAL", party_type="Supplier",
            payment_type="Pay", docstatus=1, paid_to_account_currency="MXN",
            references=[dict(reference_doctype="Purchase Order", reference_name="INT", allocated_amount=7)])
        self.memory.invoice(outstanding=0)
        cases = (("Purchase Invoice", "INT-PI", None), ("Purchase Invoice", None, "outstanding_amount"),
                 ("Purchase Invoice Item", None, "purchase_order"), ("Payment Entry", "INT-ADV", None),
                 ("Payment Entry", None, "paid_to_account_currency"), ("Payment Entry Reference", None, "allocated_amount"))
        for dt, name, field in cases:
            with self.subTest(doctype=dt, name=name, field=field):
                self.memory.denied.clear(); self.memory.hidden.clear()
                if name:
                    self.memory.denied.add((dt, name, "read"))
                else:
                    self.memory.hidden[dt, "read"] = {field}
                result = progress.get_order_progress(["EXT"])["EXT"]
                internal = result["internal"][0]
                self.assertIsNone(internal["settled"])
                self.assertIsNone(internal["payable_outstanding"])
                self.assertTrue(internal["warnings"])
                self.assertNotIn("INT-PI", json.dumps(result)); self.assertNotIn("INT-ADV", json.dumps(result))
                self.assertEqual(result["external"]["settled"], 100, "the existing external authorized projection remains compatible")

    def test_internal_local_input_cannot_bypass_native_invoice_authorization(self):
        self.memory.po("LOCAL", "FACTORY", "INTERNAL", currency="MXN")
        self.memory.add("Company", "SELLER")
        self.memory.add("Supplier", "INTERNAL", is_internal_supplier=1, represents_company="SELLER", disabled=0)
        record = api().save_link(external_order="LOCAL", external_item="LOCAL-I", purchasing_company="FACTORY",
            beneficiary_company="FACTORY", flow_kind="internal_local", internal_order="LOCAL", internal_item="LOCAL-I",
            allocated_qty=10, expected_modified="v1", expected_internal_modified="v1")
        api().confirm_native_price(record["name"], "v1", "v1", record["modified"])
        self.memory.invoice("LOCAL-PI", "LOCAL", currency="MXN", outstanding=80)
        self.memory.denied.add(("Purchase Invoice", "LOCAL-PI", "read"))
        result = progress.get_order_progress(["LOCAL"])["LOCAL"]
        self.assertEqual(result["external"]["state"], "not_applicable")
        self.assertIsNone(result["internal"][0]["payable_outstanding"])
        self.assertIsNone(result["settled"])

    def test_receipt_item_projection_operations_grow_linearly_for_ten_and_twenty_links(self):
        operation_counts = []
        for size in (10, 20):
            with self.subTest(size=size):
                comparisons = [0]
                class NativeItemIdentity(str):
                    __hash__ = str.__hash__
                    def __eq__(identity, other):
                        comparisons[0] += 1
                        return str.__eq__(identity, other)
                    def __deepcopy__(identity, memo):
                        return identity
                self.memory.records.clear(); self.memory.children.clear()
                self.memory.po(qty=size)
                internal = self.memory.po("INT", "FACTORY", "INTERNAL", qty=size, currency="MXN")
                items = [{**internal["items"][0], "name": "INT-" + str(index), "qty": 1, "amount": 10}
                         for index in range(size)]
                self.memory.add("Purchase Order", "INT", **{key: value for key, value in internal.items()
                    if key not in ("doctype", "name", "items")}, items=items)
                self.memory.add("Supplier", "INTERNAL", is_internal_supplier=1, represents_company="BUYER", disabled=0)
                for item in items:
                    api().save_link(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
                        beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT",
                        internal_item=item["name"], allocated_qty=1, expected_modified="v1", expected_internal_modified="v1")
                self.memory.add("Purchase Receipt", "INT-PR", company="FACTORY", supplier="INTERNAL", docstatus=1,
                    is_return=0, items=[dict(purchase_order="INT", purchase_order_item=NativeItemIdentity(item["name"]),
                        qty=1, stock_qty=1, uom="Nos", stock_uom="Nos") for item in items])
                rows = progress.get_order_progress(["EXT"])["EXT"]["receipt_logistics"]
                operation_counts.append(comparisons[0])
                self.assertEqual(len(rows), size)
                for row, item in zip(rows, items):
                    quantities = row["native_receipt"]["quantities"]
                    self.assertEqual(len(quantities), 1)
                    self.assertEqual(str(quantities[0]["native_item"]), item["name"])
                    self.assertNotIn("_by_item", row["native_receipt"])
                self.assertLessEqual(operation_counts[-1], size * 3,
                    "native PR item identity must be indexed once, not compared for every link")
                self.memory.children["Purchase Receipt Item"][-1]["purchase_order_item"] = "UNKNOWN-ITEM"
                rows = progress.get_order_progress(["EXT"])["EXT"]["receipt_logistics"]
                self.assertEqual(rows[-1]["native_receipt"]["state"], "review")
                self.assertEqual(rows[-1]["native_receipt"]["quantities"], [])
                self.assertTrue(rows[-1]["native_receipt"]["warnings"])
        self.assertLessEqual(operation_counts[1], operation_counts[0] * 2 + 2)

    def test_every_link_mutation_uses_one_current_allocation_read_after_parents_and_link(self):
        record = self.association()
        actions = (lambda row: api().confirm_native_price(row["name"], "v1", "v1", row["modified"]),
                   lambda row: api().set_manual_node(row["name"], row["modified"], "review", "核对"),
                   lambda row: api().refresh_logistics(row["name"], row["modified"]),
                   lambda row: api().disable_link(row["name"], row["modified"], "停用"))
        for action in actions:
            with self.subTest(action=action):
                self.memory.events.clear(); self.memory.current_reads.clear()
                record = action(record)
                self.assertEqual(self.memory.events, [("lock", "Purchase Order", "EXT"),
                    ("lock", "Purchase Order", "INT"), ("lock", LINK, record["name"]), ("allocations", ("EXT", "INT"))])
                self.assertEqual(len(self.memory.current_reads), 1)
        disabled = self.memory.records[LINK, record["name"]]
        disabled["active"] = 1
        for item in self.memory.children["Purchase Order Item"]:
            if item["parent"] == "EXT": item["qty"] = 1
        self.memory.events.clear(); self.memory.current_reads.clear()
        result = api().disable_link(record["name"], record["modified"], "源数量减少仍可安全释放")
        self.assertEqual(result["active"], 0)
        self.assertEqual(len(self.memory.current_reads), 1)


if __name__ == "__main__":
    unittest.main()
