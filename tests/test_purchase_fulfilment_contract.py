"""Allocation and reported logistics are evidence, never accounting or stock writes."""
import importlib
import unittest


def module():
    try:
        return importlib.import_module("deeplinkerp_branding.services.purchase_fulfilment_contract")
    except ImportError:
        raise AssertionError("The approved fulfilment allocation/evidence contract is missing") from None


def order(name="EXT", company="BUYER", *, qty="10", factor="1", currency="CNY", item="EXT-I"):
    return {"name": name, "company": company, "supplier": "S", "currency": currency,
            "modified": "2026-10-07 10:00:00", "grand_total": "100", "docstatus": 0,
            "items": [{"name": item, "item_code": "MATERIAL", "qty": qty, "uom": "Nos",
                       "stock_uom": "Nos", "conversion_factor": factor, "rate": "10", "amount": "100"}]}


def link(**changes):
    return {"name": "LINK", "external_order": "EXT", "external_item": "EXT-I",
            "purchasing_company": "BUYER", "beneficiary_company": "FACTORY",
            "flow_kind": "external_internal", "internal_order": "INT", "internal_item": "INT-I",
            "allocated_qty": "4", "active": 1, **changes}


def context(**changes):
    return {"root_source_id": "source-1", "root_kind": "logistics", "corp_id": "corp",
            "instance_id": "instance", "source_snapshot": "snapshot", "fingerprint": "fingerprint",
            "available": True, "approved": True, "invalid": False, **changes}


def comment(text, *, source="comment-1", when="2026-10-07 10:00:00"):
    return {"source_id": source, "user_id": "author-1", "user_name": "Author",
            "operation_time": when, "remark": text, "operation_type": "comment"}


class AllocationContractTests(unittest.TestCase):
    def test_one_external_item_can_split_between_two_factories_without_mixing_currency(self):
        c = module()
        external = order()
        target = order("INT", "FACTORY", qty="4", currency="MXN", item="INT-I")
        first = c.validate_allocation(external, target, link(), [])
        target2 = order("INT2", "FACTORY2", qty="6", currency="USD", item="INT2-I")
        second = c.validate_allocation(external, target2, link(name="LINK2", internal_order="INT2",
            internal_item="INT2-I", beneficiary_company="FACTORY2", allocated_qty="6"), [first])
        self.assertEqual(first["allocated_stock_qty"], "4")
        self.assertEqual(second["allocated_stock_qty"], "6")
        self.assertEqual(first["allocated_uom"], "Nos")

    def test_conversion_uses_native_stock_factor_and_caps_both_items(self):
        c = module()
        external = order(qty="2", factor="10")
        external["items"][0]["uom"] = "Box"
        target = order("INT", "FACTORY", qty="15", item="INT-I")
        result = c.validate_allocation(external, target, link(allocated_qty="1"), [])
        self.assertEqual(result["allocated_stock_qty"], "10")
        with self.assertRaisesRegex(ValueError, "内部"):
            c.validate_allocation(external, target, link(allocated_qty="2"), [])

    def test_huge_finite_quantity_is_rejected_before_stock_factor_arithmetic(self):
        c = module()
        with self.assertRaisesRegex(ValueError, "外部"):
            c.validate_allocation(order(), order("INT", "FACTORY", item="INT-I"),
                                  link(allocated_qty="1e1000000"), [])

    def test_allocation_rejects_underflow_overflow_and_oversized_storage_as_business_validation(self):
        from decimal import DecimalException
        c = module()
        for qty, factor in (("1e-1000100", "1"), ("1e-1000", "1"), ("1e-139", "1"),
                            ("1", "1e-1000100"), ("1", "1e1000000")):
            with self.subTest(qty=qty, factor=factor):
                try:
                    with self.assertRaises(ValueError):
                        c.validate_allocation(order(factor=factor), order("INT", "FACTORY", item="INT-I"),
                                              link(allocated_qty=qty), [])
                except DecimalException as error:
                    self.fail("Decimal arithmetic must produce normal quantity validation: " + type(error).__name__)

    def test_oversized_fixed_point_allocation_is_rejected_before_formatting(self):
        from unittest.mock import patch
        c = module()
        with patch.object(c, "format", wraps=format, create=True) as formatter:
            with self.assertRaises(ValueError):
                c.validate_allocation(order(), order("INT", "FACTORY", item="INT-I"),
                                      link(allocated_qty="1e-999999"), [])
            formatter.assert_not_called()

    def test_allocation_storage_boundary_preserves_positive_decimals_and_global_context(self):
        from decimal import Decimal, getcontext
        c = module()
        original = getcontext().copy()
        for qty, factor, expected_qty, expected_stock in (("0.2500", "1.000", "0.25", "0.25"),
                ("2.50", "2", "2.5", "5"), ("1e-138", "1", "0." + "0" * 137 + "1", "0." + "0" * 137 + "1")):
            with self.subTest(qty=qty):
                result = c.validate_allocation(order(factor=factor), order("INT", "FACTORY", item="INT-I"),
                                              link(allocated_qty=qty), [])
                self.assertEqual(result["allocated_qty"], expected_qty)
                self.assertEqual(result["allocated_stock_qty"], expected_stock)
                self.assertGreater(Decimal(result["allocated_qty"]), 0)
                self.assertLessEqual(len(result["allocated_qty"]), 140)
                self.assertLessEqual(len(result["allocated_stock_qty"]), 140)
        # Numeric price/fingerprint canonicalization still accepts zero/negative;
        # the positive storage guard must stay scoped to allocation fields.
        self.assertEqual(c.numeric_text(0), "0")
        self.assertEqual(c.numeric_text("-2.500"), "-2.5")
        self.assertEqual(getcontext().prec, original.prec)
        self.assertEqual(getcontext().Emin, original.Emin)
        self.assertEqual(getcontext().Emax, original.Emax)
        self.assertEqual(getcontext().traps, original.traps)
        self.assertEqual(getcontext().flags, original.flags)

    def test_decimal_serializer_rejects_precision_failure_without_rejecting_zero_or_negative_prices(self):
        from decimal import Decimal, DecimalException
        c = module()
        for value in ("1e-1000100", "1e1000000"):
            with self.subTest(value=value):
                try:
                    with self.assertRaises(ValueError):
                        c.decimal_text(Decimal(value))
                except DecimalException as error:
                    self.fail("serializer precision failures must be normal validation: " + type(error).__name__)
        self.assertEqual(c.numeric_text(0), "0")
        self.assertEqual(c.numeric_text("-2.500"), "-2.5")

    def test_cumulative_allocations_include_other_external_orders_and_exclude_edited_link(self):
        c = module()
        external = order()
        target = order("INT", "FACTORY", qty="10", item="INT-I")
        existing = [link(name="OTHER", external_order="OTHER-EXT", external_item="OTHER-I",
                         allocated_qty="8", allocated_stock_qty="8")]
        with self.assertRaisesRegex(ValueError, "内部"):
            c.validate_allocation(external, target, link(), existing)
        result = c.validate_allocation(external, target, link(allocated_qty="10"),
                                       [link(allocated_qty="4", allocated_stock_qty="4")])
        self.assertEqual(result["allocated_stock_qty"], "10")

    def test_invalid_quantity_item_identity_and_stock_uom_never_guess_mapping(self):
        c = module()
        for qty in ("0", "-1", "NaN", "Infinity", "bad"):
            with self.subTest(qty=qty), self.assertRaises(ValueError):
                c.validate_allocation(order(), order("INT", "FACTORY", item="INT-I"),
                                      link(allocated_qty=qty), [])
        for field, value in (("name", "wrong"), ("item_code", "OTHER"), ("stock_uom", "Kg")):
            target = order("INT", "FACTORY", item="INT-I")
            target["items"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.validate_allocation(order(), target, link(), [])

    def test_internal_local_and_trade_custody_have_explicit_distinct_roles(self):
        c = module()
        native = order(company="FACTORY")
        local = link(flow_kind="internal_local", purchasing_company="FACTORY",
                     internal_order="EXT", internal_item="EXT-I")
        result = c.validate_allocation(native, native, local, [])
        self.assertEqual(result["flow_kind"], "internal_local")
        trade = link(flow_kind="trade_custody", internal_order=None, internal_item=None,
                     beneficiary_company="BUYER", custody_company="WAREHOUSE-OWNER", custody_warehouse="WH")
        result = c.validate_allocation(order(), None, trade, [])
        self.assertIsNone(result["internal_order"])
        with self.assertRaisesRegex(ValueError, "保管"):
            c.validate_allocation(order(), None, {**trade, "custody_warehouse": None}, [])

    def test_internal_whole_balance_requires_single_source_and_full_item_coverage(self):
        c = module()
        target = order("INT", "FACTORY", qty="10", item="INT-I")
        full = link(allocated_qty="10", allocated_stock_qty="10")
        self.assertTrue(c.internal_coverage([full], {"INT": target})["INT"]["exact"])
        for links in ([{**full, "allocated_stock_qty": "4"}],
                      [{**full, "allocated_stock_qty": "4"}, {**full, "name": "OTHER",
                        "external_order": "OTHER", "allocated_stock_qty": "6"}]):
            self.assertFalse(c.internal_coverage(links, {"INT": target})["INT"]["exact"])
        target["items"].append({**target["items"][0], "name": "INT-J"})
        self.assertFalse(c.internal_coverage([full], {"INT": target})["INT"]["exact"])

    def test_native_price_version_covers_prices_and_units_but_not_progress_modified(self):
        c = module()
        target = order("INT", "FACTORY", item="INT-I")
        original = c.price_version(target)
        self.assertEqual(original, c.price_version({**target, "modified": "progress later"}))
        self.assertNotEqual(original, c.price_version({**target, "currency": "USD"}))
        target["items"][0]["rate"] = "20"
        self.assertNotEqual(original, c.price_version(target))


class LogisticsContractTests(unittest.TestCase):
    def test_positive_is_reported_evidence_with_raw_author_time_not_native_receipt(self):
        c = module()
        raw = comment("10 Nos 已到 Factory A")
        snapshot = c.logistics_snapshot(context(), {"ok": True, "main_approval": {"timeline": [raw]}}, context())
        self.assertEqual(snapshot["state"], "reported")
        self.assertFalse(snapshot["erp_received"])
        self.assertFalse(snapshot["confirmed"])
        self.assertEqual(snapshot["timeline"][0]["raw"], raw)
        self.assertEqual(snapshot["quantities"], [{"qty": "10", "uom": "Nos", "destination": "Factory A"}])

    def test_raw_comment_quantity_serializer_failure_is_review_with_original_evidence(self):
        from decimal import Underflow, localcontext
        c = module()
        raw = comment("0.00001 Nos 已到 Factory A")
        # A small local arithmetic range exercises the same underflow boundary
        # without manufacturing a million-character upstream comment fixture.
        with localcontext() as current:
            current.prec = 3; current.Emin = -2; current.Emax = 2
            current.traps[Underflow] = False
            snapshot = c.logistics_snapshot(context(), {"ok": True, "main_approval": {"timeline": [raw]}}, context())
        self.assertEqual(snapshot["state"], "review")
        self.assertEqual(snapshot["quantities"], [])
        self.assertNotIn("quantity", snapshot["timeline"][0])
        self.assertEqual(snapshot["timeline"][0]["raw"], raw)

    def test_negative_future_question_partial_ambiguous_quantity_or_destination_need_review(self):
        c = module()
        texts = ("10 Nos 未到 Factory A", "预计 10 Nos 到达 Factory A", "10 Nos 已到 Factory A？",
                 "部分 10 Nos 已到 Factory A", "已到 Factory A", "10 Nos 已到", "已到货")
        for text in texts:
            with self.subTest(text=text):
                snapshot = c.logistics_snapshot(context(), {"ok": True, "main_approval": {
                    "timeline": [comment(text)]}}, context())
                self.assertEqual(snapshot["state"], "review")
                self.assertFalse(snapshot["confirmed"])

    def test_dedup_completed_comments_and_separate_units_without_summing(self):
        c = module()
        first = comment("10 Nos 已到 Factory A")
        second = comment("2 Kg 已到 Factory A", source="comment-2")
        snapshot = c.logistics_snapshot(context(), {"ok": True, "main_approval": {
            "timeline": [first, dict(first), second, dict(second)]}}, context())
        self.assertEqual(len(snapshot["timeline"]), 2)
        self.assertEqual(snapshot["quantities"], [{"qty": "10", "uom": "Nos", "destination": "Factory A"},
                                                  {"qty": "2", "uom": "Kg", "destination": "Factory A"}])

    def test_comment_dedup_hash_is_reused_as_identity_without_rehashing_unique_rows(self):
        from unittest.mock import patch
        c = module()
        first = comment("10 Nos 已到 Factory A")
        second = comment("2 Kg 已到 Factory A", source="comment-2")
        expected_ids = [c.digest(first), c.digest(second)]
        rows = [first, dict(first), second, dict(second)]
        with patch.object(c, "digest", wraps=c.digest) as digest:
            snapshot = c.logistics_snapshot(context(), {"ok": True, "main_approval": {"timeline": rows}}, context())
        self.assertEqual(digest.call_count, len(rows), "one hash per input row, including duplicate identity checks")
        self.assertEqual([row["id"] for row in snapshot["timeline"]], expected_ids)
        self.assertEqual([row["raw"] for row in snapshot["timeline"]], [first, second])
        self.assertEqual(snapshot["state"], "reported")

    def test_conflicting_comments_keep_raw_evidence_and_need_review(self):
        c = module()
        snapshot = c.logistics_snapshot(context(), {"ok": True, "main_approval": {
            "timeline": [comment("10 Nos 已到 Factory A"),
                         comment("10 Nos 未到 Factory A", source="comment-2")]}}, context())
        self.assertEqual(snapshot["state"], "review")
        self.assertEqual(len(snapshot["timeline"]), 2)

    def test_invalid_quantities_spanish_negation_and_positive_conflicts_require_review(self):
        c = module()
        negative_phrases = ("hadn't arrived at", "weren't received at", "couldn't have arrived at",
            "didn't say it arrived at", "don't confirm it arrived at", "isn't received at", "aren't received at",
            "wasn't received at", "can't have arrived at", "won't be received at", "wouldn't have arrived at",
            "hasn't arrived at", "haven't arrived at")
        english = tuple("10 Nos " + change(phrase).replace("'", quote) + " Factory A"
            for phrase in negative_phrases for quote in ("'", "’", "‘") for change in (str.lower, str.upper))
        shortage = ("10 Nos llegó Factory A, faltaron piezas", "10 Nos llegó Factory A, FALTABAN piezas",
            "10 Nos llegó Factory A, faltó material", "10 Nos 已到 Factory A，少了",
            "10 Nos 已到 Factory A，缺件", "10 Nos 已到 Factory A，数量不足", "10 Nos had not arrived at Factory A")
        for text in ("已到墨西哥，0 件", "1,000 件 已到 Factory A", "-10 件 已到 Factory A",
                     "no llegó a Factory A 100 piezas", "1.000 件 已到 Factory A",
                     "-10 件；2 Nos 已到 Factory A", "10 Nos never arrived at Factory A",
                     "10 Nos nunca llegó Factory A", "10 Nos 不曾到达 Factory A",
                     "10 Nos 已到 Factory A，但破损", "10 Nos haven't arrived at Factory A",
                     "10 Nos HASN’T arrived at Factory A", "10 Nos haven’t arrived at Factory A",
                     "10 Nos Ya llegó Factory A, faltan piezas", "1 234 件 已到 Factory A",
                     "1\u202f234 件 已到 Factory A") + english + shortage:
            with self.subTest(text=text):
                snapshot = c.logistics_snapshot(context(), {"ok": True, "main_approval": {
                    "timeline": [comment(text)]}}, context())
                self.assertEqual(snapshot["state"], "review")
                self.assertEqual(snapshot["quantities"], [])
                self.assertEqual(snapshot["timeline"][0]["raw"]["remark"], text)
        for text in ("8 Nos 已到 Factory A", "10 Nos 已到 Factory B"):
            snapshot = c.logistics_snapshot(context(), {"ok": True, "main_approval": {
                "timeline": [comment("10 Nos 已到 Factory A"), comment(text, source="other")]}}, context())
            self.assertEqual(snapshot["state"], "review")

    def test_quantity_scan_has_no_whitespace_start_and_keeps_grouped_number_whole(self):
        c = module()
        for size in (1000, 2000, 4000):
            with self.subTest(size=size):
                text = " " * size + "10 Nos"
                self.assertIsNone(c.QUANTITY.match(text), "a numeric scan cannot start at whitespace")
                matches = list(c.QUANTITY.finditer(text))
                self.assertEqual([row.start() for row in matches], [size])
        for text, token in (("1 234 件", "1 234"), ("1\u202f234 件", "1\u202f234")):
            with self.subTest(text=text):
                matches = list(c.QUANTITY.finditer(text))
                self.assertEqual([row[1] for row in matches], [token], "never accept the trailing 234 alone")
        for qty in ("10", "12.5", "0.25"):
            with self.subTest(qty=qty):
                snapshot = c.logistics_snapshot(context(), {"ok": True, "main_approval": {
                    "timeline": [comment(qty + " Nos 已到 Factory A")]}}, context())
                self.assertEqual(snapshot["state"], "reported")
                self.assertEqual(snapshot["quantities"][0]["qty"], qty)

    def test_unapproved_expense_root_and_changed_provenance_never_report_arrival(self):
        c = module()
        detail = {"ok": True, "main_approval": {"timeline": [comment("10 Nos 已到 Factory A")]}}
        for current in (context(approved=False), context(invalid=True), context(root_kind="expense"),
                        context(root_source_id="other"), context(fingerprint="new")):
            with self.subTest(current=current):
                snapshot = c.logistics_snapshot(current, detail, context())
                self.assertIn(snapshot["state"], ("review", "stale", "unavailable"))
                self.assertFalse(snapshot["confirmed"])
                self.assertEqual(snapshot["quantities"], [])
        self.assertNotIn("manual_nodes", c.logistics_snapshot(context(), detail, context()))

    def test_cached_evidence_requires_current_binding_and_snapshot_context_versions(self):
        c = module()
        validate = getattr(c, "validate_snapshot_context", None)
        self.assertTrue(callable(validate), "cached evidence needs one authoritative source-context validator")
        bound = context()
        snapshot = c.logistics_snapshot(bound, {"ok": True, "main_approval": {
            "timeline": [comment("10 Nos 已到 Factory A")]}}, bound)
        for changed in (context(source_snapshot="new"), context(cost_version="new"),
                        context(binding_revision=2), context(approved=False), context(root_source_id="new")):
            with self.subTest(changed=changed):
                checked = validate(snapshot, changed, bound)
                self.assertEqual(checked["state"], "stale")
                self.assertEqual(checked["quantities"], [])
                self.assertEqual(checked["timeline"][0]["raw"], comment("10 Nos 已到 Factory A"))
                already_rebound = validate(snapshot, changed, changed)
                self.assertEqual(already_rebound["state"], "stale")
        self.assertEqual(snapshot["state"], "reported", "validation must not mutate stored audit evidence")
        self.assertEqual(validate(snapshot, bound, bound)["state"], "reported")


if __name__ == "__main__":
    unittest.main()
