import ast
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_local_patch import prepare

FIXTURE = '''import threading
UNCHANGED_CONFIG = "do not print or modify configuration"
def push_to_erp(payload, label="未命名", force_method=None):
    return True
def task_mould_code_sync(item_code_raw, item_name_raw, notify_users):
    payload = {"item_code": item_code_raw, "item_name": item_name_raw, "custom_specifications": "PC"}
    if push_to_erp(payload, label="模具"):
        result = "existing ERP result"
def callback(data):
    if "itemCode" in data:
        threading.Thread(target=task_mould_code_sync, args=(data.get("itemCode"), data.get("itemName", "未命名开模物料"), "notify")).start()
    elif data.get("type") == "material":
        threading.Thread(target=task_mould_code_sync, args=(data.get("itemCode"), data.get("itemName", "未命名开模物料"), "notify")).start()
'''


class PatchTests(unittest.TestCase):
    def test_offline_patch_preserves_config_erp_sender_and_whitelisted_callback_context(self):
        candidate = prepare(FIXTURE)
        tree = ast.parse(candidate)
        self.assertIn('UNCHANGED_CONFIG = "do not print or modify configuration"', candidate)
        self.assertIn('def push_to_erp(payload, label="未命名", force_method=None):\n    return True', candidate)
        self.assertIn('dual_write_mold(payload, context=event_context)', candidate)
        tasks = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'Thread']
        self.assertEqual(len(tasks), 2)
        for call in tasks:
            self.assertIn("{'event_context': data}", ast.unparse(call))

    def test_repeat_or_unknown_service_shape_fails_closed(self):
        with self.assertRaises(ValueError):
            prepare(prepare(FIXTURE))
        with self.assertRaises(ValueError):
            prepare(FIXTURE.replace('notify_users):', 'notify_users, extra):'))
        with self.assertRaises(ValueError):
            prepare(FIXTURE.replace('label="模具"', 'label=item_code_raw'))

    def test_missing_label_keeps_original_sender_default(self):
        candidate = prepare(FIXTURE.replace(', label="模具"', ''))
        self.assertIn('configure_mold_sync(lambda payload: push_to_erp(payload))', candidate)


if __name__ == '__main__':
    unittest.main()
