"""Quote UI forwards its current edit lease, including batch-list actions."""

import json
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("operation", ["manual", "confirm"])
@pytest.mark.parametrize("in_detail", [True, False])
def test_quote_write_requests_use_and_release_the_correct_edit_context(operation, in_detail):
    source = Path(__file__).resolve().parents[1] / "page/overseas_cost_workbench/parts/65-manual-documents.js"
    script = r"""
const fs=require('fs');
const Harness=Function(`return class Harness {${fs.readFileSync(SOURCE,'utf8')}}`)();
const calls=[]; const h=new Harness();
const batch={name:'B',current_version:'V'};
h.detailState=IN_DETAIL ? {batchName:'B',editToken:'DETAIL',expectedModified:'DETAIL-M'} : {batchName:'OTHER'};
h.ensureEditSession=async()=>{calls.push(['ensure']);return true};
h.escape=String;h.formatMoney=String;h.isPositive=(v)=>Number(v)>0;
h.readManualQuoteValue=(dialog,key)=>key==='amount'?'100':'';
const button={prop(){return this},text(){return this}};
const dialog={$wrapper:{find(){return button}},hide(){}};
global.frappe={confirm:(message,yes)=>yes(),msgprint:()=>{},show_alert:()=>{}};
h.call=async(method,args)=>{calls.push([method,args]);
 if(method.endsWith('.acquire'))return {ok:true,edit_token:'ACQUIRED',modified:'ACQUIRED-M'};
 if(method.endsWith('.release'))return {ok:true};
 return {ok:false,message:'EXPECTED STOP AFTER REQUEST'};};
(async()=>{
 try{if(OPERATION==='manual')await h.saveManualLogisticsQuote(batch,dialog);
 else await h.confirmLogisticsQuoteCandidate(batch,{amount:100,currency:'RMB'},0,dialog)}catch(e){
  if(e.message!=='EXPECTED STOP AFTER REQUEST')throw e;
 }
 console.log(JSON.stringify(calls));
})().catch(e=>{console.error(e);process.exit(1)});
""".replace("SOURCE", json.dumps(str(source))).replace("IN_DETAIL", json.dumps(in_detail)).replace("OPERATION", json.dumps(operation))
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True)
    calls = json.loads(result.stdout)
    request = next(call for call in calls if ".import_api." in call[0])
    assert request[1]["edit_token"] == ("DETAIL" if in_detail else "ACQUIRED")
    assert request[1]["expected_modified"] == ("DETAIL-M" if in_detail else "ACQUIRED-M")
    if in_detail:
        assert calls[0] == ["ensure"]
    else:
        assert calls[-1][0].endswith(".release") and calls[-1][1]["edit_token"] == "ACQUIRED"
