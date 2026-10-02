"""Shared native-control browse behavior; Node isolates only the DOM/network boundary."""

import ast
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "overseas_costing/tests/frontend/selection_dropdown_harness.js"


def run_js(body, *, late_classes=False):
    source = f"""process.env.SELECTION_CLASSES_LATE={json.dumps('1' if late_classes else '')};
const h=require({json.dumps(str(HARNESS))});
const {{assert,makeControl,requests,reply,flush,load,frappe,inputEvent,document,clock}}=h;
(async()=>{{{body}}})().catch(e=>{{console.error(e);process.exit(1)}});"""
    result = subprocess.run(["node", "-e", source], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["Link", "DynamicLink", "Autocomplete", "MultiSelect"])
@pytest.mark.parametrize("value", ["ALPHA", ""])
def test_click_browses_without_changing_the_input_or_model(kind, value):
    run_js(f"""const c=makeControl({json.dumps(kind)},{{value:{json.dumps(value)},query:true}});
c.$input.trigger('click');
assert.equal(requests.length,1,'one click must issue a native browse query');
assert.equal(requests[0].args.txt,'');
assert.equal(c.$input.val(),{json.dumps(value)});assert.equal(c.changed,0);
assert.deepEqual(c.input.writes,[]);await reply(0);assert(c.awesomplete.opened);
assert.equal(c.nativeSelections,0);""")


@pytest.mark.parametrize("kind", ["Link", "DynamicLink", "Autocomplete", "MultiSelect"])
def test_empty_native_focus_then_click_does_not_duplicate_query(kind):
    run_js(f"""const c=makeControl('{kind}',{{value:'',query:true}});
c.$input.trigger('focus');c.$input.trigger('click');assert.equal(requests.length,1);
await reply(0);assert(c.awesomplete.opened);assert.equal(c.changed,0);""")


@pytest.mark.parametrize("kind", ["Link", "DynamicLink"])
def test_browse_retains_native_arguments_and_context_separated_cache(kind):
    run_js(f"""const c=makeControl('{kind}',{{value:'ALPHA',query:true}});
c.$input._created_new_doc=true;c.$input.trigger('click');
assert.deepEqual(requests[0].args,{{txt:'',doctype:'Warehouse',ignore_user_permissions:1,
reference_doctype:'Stock Entry',page_length:37,link_fieldname:'warehouse',query:'custom.allowed',
filters:{{company:'A',is_group:0,item:'SKU'}}}});
await reply(0,[{{value:'A-WH'}}]);c.awesomplete.close();c.doc.company='B';
c.$input.trigger('click');assert(!c.awesomplete.visible.some(x=>x.value==='A-WH'));
assert.equal(requests[1].args.filters.company,'B');await reply(1,[{{value:'B-WH'}}]);
assert.deepEqual(c.awesomplete.visible.map(x=>x.value),['B-WH']);""")


def test_dynamic_link_queries_the_current_target_doctype():
    run_js("""const c=makeControl('DynamicLink',{value:'ALPHA',query:true});
c.df.options='target_field';c.doc.target='Customer';c.$input.trigger('click');
assert.equal(requests[0].args.doctype,'Customer');c.doc.target='Supplier';
c.$input.trigger('click');assert.equal(requests[1].args.doctype,'Supplier');
await reply(0,[{value:'OLD-CUSTOMER'}]);assert(!c.awesomplete.visible.length);
await reply(1,[{value:'SUPPLIER'}]);assert.equal(c.awesomplete.visible[0].value,'SUPPLIER');""")


@pytest.mark.parametrize("kind", ["Link", "DynamicLink", "Autocomplete", "MultiSelect"])
def test_typing_restores_native_search_and_selection(kind):
    run_js(f"""const c=makeControl('{kind}',{{value:'ALPHA',query:true}});
c.$input.trigger('click');await reply(0);inputEvent(c,'BE');
assert.equal(requests[1].args.txt,'BE');await reply(1,[{{label:'BETA',value:'BETA'}}]);
assert(c.awesomplete.select('BETA',{{keyCode:13}}));
assert.equal(c.nativeSelections,1);assert.equal(c.changed,1);
assert.equal(c.$input.val(),'{"BETA, " if kind == "MultiSelect" else "BETA"}');""")


@pytest.mark.parametrize("kind", ["Link", "Autocomplete"])
def test_repeated_click_install_and_recreated_input_have_one_handler(kind):
    run_js(f"""load();load();const c=makeControl('{kind}',{{value:'ALPHA',query:true}});
c.$input.trigger('click');c.$input.trigger('click');assert.equal(requests.length,1);
await reply(0);c.$input.trigger('click');assert.equal(requests.length,1);
const old=c.input;c.make_input();c.$input.val('ALPHA');c.input.writes=[];
c.$input.trigger('click');assert.equal(requests.length,2);
old.dispatch('click');assert.equal(requests.length,2);await reply(1);assert(c.awesomplete.opened);""")


@pytest.mark.parametrize("kind", ["Link", "DynamicLink", "Autocomplete", "MultiSelect"])
@pytest.mark.parametrize("restriction", ["read_only", "disabled", "status", "domReadonly", "domDisabled"])
def test_noneditable_controls_do_not_browse(kind, restriction):
    run_js(f"""const c=makeControl('{kind}',{{value:'ALPHA',query:true}});
const restriction='{restriction}';if(restriction==='status')c.disp_status='Read';
else if(restriction==='domReadonly')c.input.readOnly=true;
else if(restriction==='domDisabled')c.input.disabled=true;else c.df[restriction]=1;
c.$input.trigger('click');assert.equal(requests.length,0);assert.equal(c.$input.val(),'ALPHA');""")


@pytest.mark.parametrize("kind", ["Link", "Autocomplete"])
@pytest.mark.parametrize("change", ["input", "close", "reopen", "context", "recreate", "blur", "readonly"])
def test_late_reply_cannot_display_after_the_request_is_obsolete(kind, change):
    run_js(f"""const c=makeControl('{kind}',{{value:'ALPHA',query:true}});c.$input.trigger('click');
const change='{change}';if(change==='input')inputEvent(c,'NEW');
if(change==='close'||change==='reopen')c.awesomplete.close();
if(change==='reopen')c.$input.trigger('click');
if(change==='context')c.doc.company='B';if(change==='recreate')c.make_input();
if(change==='blur')c.$input.trigger('blur');if(change==='readonly')c.df.read_only=1;
await reply(0,[{{value:'STALE'}}]);
assert(!c.awesomplete.visible.some(x=>x.value==='STALE'),'obsolete reply was displayed');
assert.notEqual(c._data?.[0]?.value,'STALE');""")


def test_async_filter_description_rechecks_validity_at_final_assignment():
    run_js("""const c=makeControl('Link',{value:'ALPHA',query:true});let release;
c.get_filter_description=()=>new Promise(r=>release=r);c.$input.trigger('click');
const pending=reply(0,[{value:'STALE'}]);await flush();inputEvent(c,'NEW');release('Company A');
await pending;assert(!c.awesomplete.visible.some(x=>x.value==='STALE'));
assert.equal(c.hrefUpdates,0);""")


@pytest.mark.parametrize("kind,remote", [("Link", True), ("Autocomplete", True), ("Autocomplete", False)])
@pytest.mark.parametrize("interaction", ["focus", "click"])
def test_dependency_change_clears_displayed_options_before_native_focus_or_click(kind, remote, interaction):
    run_js(f"""const c=makeControl('{kind}',{{value:'ALPHA',query:{str(remote).lower()}}});
if(!{str(remote).lower()})c.get_data=()=>[{{value:c.doc.company+'-WH'}}];
c.$input.trigger('click');if({str(remote).lower()})await reply(0,[{{value:'A-WH'}}]);
assert(c.awesomplete.visible.some(x=>x.value==='A-WH'));c.doc.company='B';
c.input.dispatch('{interaction}');
assert(!c.awesomplete.visible.some(x=>x.value==='A-WH'),'native focus reopened obsolete options');
assert.equal(c.$input.val(),'ALPHA');""")


@pytest.mark.parametrize("kind", ["Autocomplete", "MultiSelect"])
def test_local_browse_preserves_options_filter_and_multiselect_replace(kind):
    run_js(f"""const c=makeControl('{kind}',{{value:'ALPHA, ',query:false}});
const replace=c.awesomplete.replace;c.$input.trigger('click');
assert.equal(c.awesomplete.replace,replace);assert.equal(requests.length,0);
assert.deepEqual(c.awesomplete.visible.map(x=>x.value),{json.dumps(['BETA'] if kind == 'MultiSelect' else ['ALPHA', 'BETA'])});
assert.equal(c.$input.val(),'ALPHA, ');assert(c.awesomplete.select('BETA'));
assert.equal(c.$input.val(),'{"ALPHA, BETA, " if kind == "MultiSelect" else "BETA"}');
inputEvent(c,'AL');assert.deepEqual(c.awesomplete.visible.map(x=>x.value),['ALPHA']);""")


def test_autocomplete_query_function_keeps_raw_call_and_native_parameter_handling():
    run_js("""const c=makeControl('Autocomplete',{value:'ALPHA'});let calls=[];
c.get_query=function(doc,doctype,name){'use strict';calls.push({self:this,doc,doctype,name});
return {query:'custom.options',params:{company:doc.company,limit:8}}};
c.$input.trigger('click');assert(calls.every(x=>x.self===undefined));
assert(calls.every(x=>x.doc===c.doc&&x.doctype==='Stock Entry'&&x.name==='ROW'));
assert.deepEqual(requests[0].args,{txt:'',query:'custom.options',company:'A',limit:8});
await reply(0);assert(c.awesomplete.opened);""")


@pytest.mark.parametrize("kind", ["Link", "Autocomplete"])
def test_failed_browse_can_retry_without_changing_value(kind):
    run_js(f"""const c=makeControl('{kind}',{{value:'ALPHA',query:true}});
c.$input.trigger('click');requests[0].failed=true;clock.expire();c.$input.trigger('click');
assert.equal(requests.length,2);await reply(1);assert(c.awesomplete.opened);
assert.equal(c.$input.val(),'ALPHA');assert.equal(c.changed,0);""")


@pytest.mark.parametrize("kind", ["Link", "Autocomplete"])
def test_pending_browse_timeout_does_not_discard_native_typed_search(kind):
    run_js(f"""const c=makeControl('{kind}',{{value:'ALPHA',query:true}});
inputEvent(c,'BE');clock.expire();await reply(0,[{{value:'BETA_REMOTE'}}]);
assert.deepEqual(c.awesomplete.visible.map(x=>x.value),['BETA_REMOTE']);""")


@pytest.mark.parametrize("value", ["ALPHA", ""])
def test_link_browse_keyboard_requires_explicit_choice_and_tab_keeps_value(value):
    run_js(f"""const c=makeControl('Link',{{value:{json.dumps(value)},query:true}});
c.$input.trigger('click');await reply(0);assert.equal(c.awesomplete.tabSelect,false);
assert.equal(c.awesomplete.index,-1);c.input.dispatch('keydown',{{key:'Tab',keyCode:9}});
assert.equal(c.$input.val(),{json.dumps(value)});assert.equal(c.changed,0);
c.input.dispatch('keydown',{{key:'ArrowDown',keyCode:40}});
assert(c.awesomplete.select('BETA',{{keyCode:13}}));assert.equal(c.changed,1);
assert.equal(c.$input.val(),'BETA');assert.equal(c.awesomplete.tabSelect,true);""")


def test_delayed_classes_are_installed_once_and_other_selector_classes_untouched():
    run_js("""const select=frappe.ui.form.ControlSelect.prototype.make_input;
const multi=frappe.ui.form.ControlMultiSelectList.prototype.make_input;
frappe.ui.form.ControlLink=h.NativeLink;frappe.ui.form.ControlAutocomplete=h.NativeAutocomplete;
document.dispatch('app_ready');load();const c=makeControl('Link',{value:'ALPHA',query:true});
c.$input.trigger('click');assert.equal(requests.length,1);
assert.equal(frappe.ui.form.ControlSelect.prototype.make_input,select);
assert.equal(frappe.ui.form.ControlMultiSelectList.prototype.make_input,multi);""", late_classes=True)


def test_selection_bundle_is_registered_in_global_desk_assets():
    tree = ast.parse((ROOT / "overseas_costing/hooks.py").read_text())
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "app_include_js"
                              for target in node.targets))
    assets = ast.literal_eval(assignment.value)
    assert "selection_dropdown.bundle.js" in ([assets] if isinstance(assets, str) else assets)
