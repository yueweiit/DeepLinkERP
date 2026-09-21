from __future__ import annotations

from pathlib import Path
import importlib
import json
import subprocess
import sys
from types import ModuleType


PARTS = Path(__file__).resolve().parents[1] / "page" / "overseas_cost_workbench" / "parts"


def _request_result(script: str) -> dict:
    source = PARTS / "20-data-filters.js"
    completed = subprocess.run(
        [
            "node",
            "-e",
            (
                "const fs=require('fs');"
                f"const source=fs.readFileSync({json.dumps(str(source))},'utf8').split('  async loadBatches(')[0];"
                "const Harness=Function(`return class RequestHarness {${source}}`)();"
                "global.window={location:{reload:()=>{global.reloads+=1}},setTimeout:(fn)=>{global.scheduled=fn;return 7},clearTimeout:()=>{},addEventListener:()=>{},removeEventListener:()=>{}};"
                "global.document={visibilityState:'visible',addEventListener:()=>{},removeEventListener:()=>{}};"
                "global.reloads=0;global.frappe={csrf_token:'csrf',dom:{freeze:()=>{},unfreeze:()=>{}},ui:{Dialog:class{show(){}}}};"
                f"(async()=>{{const workspace=new Harness();workspace.initialReleaseId='release-1';{script}}})().catch((error)=>{{console.error(error);process.exit(1)}});"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_release_id_prefers_site_configuration(monkeypatch) -> None:
    from overseas_costing.services import workbench_release_service

    monkeypatch.setattr(
        workbench_release_service,
        "frappe",
        type("Frappe", (), {"conf": {"overseas_costing_release_id": "4100c42c32"}})(),
    )

    assert workbench_release_service.get_release_id() == "4100c42c32"


def test_release_id_falls_back_to_stable_workbench_asset_digest(monkeypatch, tmp_path: Path) -> None:
    from overseas_costing.services import workbench_release_service

    (tmp_path / "overseas_cost_workbench.js").write_text("one", encoding="utf-8")
    (tmp_path / "overseas_cost_workbench.css").write_text("two", encoding="utf-8")
    monkeypatch.setattr(
        workbench_release_service,
        "frappe",
        type("Frappe", (), {"conf": {}})(),
    )
    monkeypatch.setattr(workbench_release_service, "WORKBENCH_ASSET_DIR", tmp_path)

    first = workbench_release_service.get_release_id()
    second = workbench_release_service.get_release_id()

    assert first == second
    assert first.startswith("assets-")
    assert len(first) == len("assets-") + 16


def test_release_api_requires_workbench_access_and_returns_marker(monkeypatch) -> None:
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda: (lambda function: function)
    fake_frappe.session = type("Session", (), {"user": "Administrator"})()
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.workbench", None)
    workbench = importlib.import_module("overseas_costing.api.workbench")

    calls = []
    monkeypatch.setattr(workbench, "require_overseas_cost_access", lambda: calls.append("access"))
    monkeypatch.setattr(workbench.workbench_release_service, "get_release_id", lambda: "release-1")

    assert workbench.get_workbench_release() == {"ok": True, "release_id": "release-1"}
    assert calls == ["access"]


def test_read_request_retries_once_only_after_same_release_is_confirmed() -> None:
    result = _request_result(
        """
let reads=0,checks=0;
workspace.requestJson=async(url)=>{
  if(url.includes('get_workbench_release')){checks+=1;return {message:{ok:true,release_id:'release-1'}}}
  reads+=1;if(reads===1){const error=new Error('Bad Gateway');error.status=503;throw error}
  return {message:{ok:true,value:42}};
};
const value=await workspace.call('overseas_costing.api.batch.get_batch_list',{});
console.log(JSON.stringify({reads,checks,value,blocked:!!workspace.releaseBlocked}));
"""
    )
    assert result == {"reads": 2, "checks": 1, "value": {"ok": True, "value": 42}, "blocked": False}


def test_write_request_is_never_replayed_after_transient_failure() -> None:
    result = _request_result(
        """
let writes=0,checks=0;
workspace.requestJson=async(url)=>{
  if(url.includes('get_workbench_release')){checks+=1;return {message:{ok:true,release_id:'release-1'}}}
  writes+=1;const error=new Error('Bad Gateway');error.status=503;throw error;
};
let caught;try{await workspace.call('overseas_costing.api.calculate.recalculate_batch',{})}catch(error){caught=error.message}
console.log(JSON.stringify({writes,checks,caught}));
"""
    )
    assert result == {"writes": 1, "checks": 1, "caught": "Bad Gateway"}


def test_file_upload_uses_same_release_gate_and_is_never_replayed() -> None:
    result = _request_result(
        """
let uploads=0,checks=0;
workspace.requestJson=async(url)=>{
  if(url.includes('get_workbench_release')){checks+=1;throw Object.assign(new Error('Unavailable'),{status:503})}
  uploads+=1;throw Object.assign(new Error('Bad Gateway'),{status:502});
};
let handled=false;try{await workspace.uploadFileRequest({})}catch(error){handled=error.workbenchReleaseHandled===true}
console.log(JSON.stringify({uploads,checks,handled,blocked:workspace.releaseBlocked}));
"""
    )
    assert result == {"uploads": 1, "checks": 1, "handled": True, "blocked": True}


def test_same_release_recovery_unblocks_before_hiding_update_dialog() -> None:
    result = _request_result(
        """
let blockedWhenHidden=null;
workspace.releaseUpdating=true;workspace.releaseBlocked=true;
workspace.hideWorkbenchReleaseDialog=()=>{blockedWhenHidden=workspace.releaseBlocked};
workspace.requestJson=async()=>({message:{ok:true,release_id:'release-1'}});
const state=await workspace.checkWorkbenchRelease();
console.log(JSON.stringify({state,blockedWhenHidden,blocked:workspace.releaseBlocked,updating:workspace.releaseUpdating}));
"""
    )
    assert result == {
        "state": {"changed": False, "releaseId": "release-1"},
        "blockedWhenHidden": False,
        "blocked": False,
        "updating": False,
    }


def test_changed_release_blocks_old_page_and_deduplicates_update_dialog() -> None:
    result = _request_result(
        """
let checks=0,dialogs=0;
workspace.showWorkbenchReleaseDialog=()=>{dialogs+=1};
workspace.requestJson=async(url)=>{checks+=1;return {message:{ok:true,release_id:'release-2'}}};
await Promise.all([workspace.checkWorkbenchRelease(),workspace.checkWorkbenchRelease(),workspace.checkWorkbenchRelease()]);
let blocked;try{await workspace.call('overseas_costing.api.batch.get_batch_list',{})}catch(error){blocked=error.workbenchReleaseBlocked===true}
console.log(JSON.stringify({checks,dialogs,blocked,releaseBlocked:workspace.releaseBlocked}));
"""
    )
    assert result == {"checks": 1, "dialogs": 1, "blocked": True, "releaseBlocked": True}


def test_request_layer_owns_calls_uploads_usage_and_settlement_without_frappe_transport() -> None:
    data = (PARTS / "20-data-filters.js").read_text(encoding="utf-8")
    upload = (PARTS / "50-import-category.js").read_text(encoding="utf-8")
    settlement = (PARTS / "85-settlement.js").read_text(encoding="utf-8")
    shell = (PARTS / "10-shell.js").read_text(encoding="utf-8")

    assert "frappe.call" not in data + upload + settlement
    assert "this.uploadFileRequest(formData)" in upload
    assert "return this.call(`overseas_costing.api.logistics_settlement.${action}`" in settlement
    assert "initializeWorkbenchRelease" in shell


def test_page_show_resumes_release_monitor_after_page_hide_cleanup() -> None:
    data = (PARTS / "20-data-filters.js").read_text(encoding="utf-8")
    bootstrap = (PARTS / "00-bootstrap.js").read_text(encoding="utf-8")
    shell = (PARTS / "10-shell.js").read_text(encoding="utf-8")

    assert "startWorkbenchReleaseMonitor" in data
    assert "resumeWorkbenchReleaseMonitor" in data
    assert "workbench.resumeWorkbenchReleaseMonitor()" in bootstrap
    assert 'window.removeEventListener("focus", this._releaseFocusHandler)' in shell
