"""Execute the real DingTalk approval detail renderers in Node."""

import json
import subprocess
from pathlib import Path


PARTS = Path(__file__).resolve().parents[1] / "page/overseas_cost_workbench/parts"
JS_PART = PARTS / "84-dingtalk-approval.js"
CSS_PART = PARTS / "46-dingtalk-approval.css"


def run_js(body: str) -> None:
    prelude = f"""
const fs=require('fs');
const assert=require('assert').strict;
const Workbench=new Function('return class {{'+fs.readFileSync({json.dumps(str(JS_PART))},'utf8')+'}}')();
const w=new Workbench();
w.escape=v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
w.formatDateTimeMinute=v=>String(v??'');
"""
    result = subprocess.run(
        ["node", "-e", prelude + "\n" + body],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_form_fields_render_semantic_table_long_values_and_collapsed_empty_fields() -> None:
    run_js(
        r"""
const html=w.renderDingtalkFormFields([
 {label:'项目 <script>bad()</script>',value:'超队 1.0',component_type:'TextField',display_kind:'scalar',is_empty:false},
 {label:'备注',value:'第一行\n第二行，内容较长，需要独占整行展示。',component_type:'TextareaField',display_kind:'scalar',is_empty:false},
 {label:'货物信息 Bienes',value:'THIS_TABLE_VALUE_MUST_NOT_RENDER_AS_LONG_TEXT',component_type:'TableField',display_kind:'table',is_empty:false,
  table:{columns:['物料编码 Código de material','数量 Cantidad'],rows:[['<MAT-1>','10'],['MAT-2','<img src=x onerror=bad()>']]}},
 {label:'空备注',value:'',component_type:'TextField',display_kind:'scalar',is_empty:true},
 {label:'空金额',value:'',component_type:'MoneyField',display_kind:'scalar',is_empty:true},
]);
assert(html.includes('class="ocw-dingtalk-form-grid"'));
assert(html.includes('class="ocw-dingtalk-field is-long"'));
assert(html.includes('<table class="ocw-dingtalk-goods-table">'));
assert(html.includes('<thead>')&&html.includes('<tbody>'));
assert(html.includes('<th scope="col" class="ocw-dingtalk-goods-code">物料编码 Código de material</th>'));
assert(html.includes('class="ocw-dingtalk-goods-code"'));
assert(html.includes('class="ocw-dingtalk-goods-cards"'));
assert(!html.includes('THIS_TABLE_VALUE_MUST_NOT_RENDER_AS_LONG_TEXT'));
assert(html.includes('<details class="ocw-dingtalk-empty-fields">'));
assert(html.includes('查看未填写字段（2）'));
assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;'));
assert(!html.includes('<img src=x'));assert(html.includes('&lt;img src=x onerror=bad()&gt;'));
"""
    )


def test_timeline_is_stably_newest_first_and_hides_raw_codes_outside_audit_details() -> None:
    run_js(
        r"""
const items=[
 {event_kind:'decision',display_label:'同意',operation_type:'EXECUTE_TASK_NORMAL',result:'AGREE',user_id:'USER-OLD',user_name:'旧审批人',operation_time:'2026-09-20T09:00:00+08:00',remark:'旧记录'},
 {event_kind:'comment',display_label:'评论',operation_type:'ADD_REMARK',result:'',user_id:'USER-A',user_name:'张三',operation_time:'2026-09-22T10:00:00+08:00',remark:'ignored raw remark',remark_segments:[{kind:'text',text:'<script>bad()</script> 请 '},{kind:'mention',text:'李四 <img src=x>'},{kind:'text',text:' 处理'}]},
 {event_kind:'decision',display_label:'拒绝',operation_type:'EXECUTE_TASK_NORMAL',result:'REFUSE',user_id:'USER-B',user_name:'王五',operation_time:'2026-09-22T10:00:00+08:00',remark:'信息不全'},
 {event_kind:'system',display_label:'其他流程记录',operation_type:'FUTURE_PRIVATE_CODE',result:'PRIVATE_RESULT',user_id:'USER-SYS',user_name:'系统',operation_time:'2026-09-23T10:00:00+08:00',remark:'未知系统事件'},
 {event_kind:'system',display_label:'发起审批',operation_type:'START_PROCESS_INSTANCE',result:'',user_id:'USER-START',user_name:'发起人',operation_time:'2026-09-19T10:00:00+08:00',remark:''},
];
const before=JSON.stringify(items);const html=w.renderDingtalkTimeline(items,false);
assert.equal(JSON.stringify(items),before,'renderer must not mutate the backend array');
assert(html.indexOf('张三')<html.indexOf('王五'));assert(html.indexOf('王五')<html.indexOf('旧审批人'));
assert(html.includes('<details class="ocw-dingtalk-system-records">'));
assert(!html.includes('<details class="ocw-dingtalk-system-records" open'));
assert(html.includes('展开 2 条系统记录'));assert(html.includes('其他流程记录'));
assert.equal((html.match(/>审计详情</g)||[]).length,5);
const main=html.replace(/<details class="ocw-dingtalk-timeline-audit">[\s\S]*?<\/details>/g,'');
for(const raw of ['EXECUTE_TASK_NORMAL','ADD_REMARK','FUTURE_PRIVATE_CODE','AGREE','REFUSE','PRIVATE_RESULT','USER-A','USER-B','USER-SYS'])assert(!main.includes(raw),raw);
assert(html.includes('EXECUTE_TASK_NORMAL'));assert(html.includes('USER-A'));
assert(html.includes('class="ocw-dingtalk-mention"'));
assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;'));
assert(!html.includes('<img src=x>'));assert(html.includes('李四 &lt;img src=x&gt;'));
assert(!html.includes('href='));
"""
    )


def test_attachments_keep_actions_escape_content_and_make_excluded_cards_read_only() -> None:
    run_js(
        r"""
const items=[
 {attachment_name:'ATT-1',process_instance_id:'PROC-PRIVATE',file_id:'FILE-PRIVATE',file_name:'装箱单 <bad>.png',preview_url:'/private/files/装箱 预览.png',file_url:'/private/files/packing.png',origin:'Form',archive_status:'archived',downloadable:true,previewable:true,packing_candidate:true},
 {attachment_name:'ATT-2',process_instance_id:'PROC-2',file_id:'FILE-2',file_name:'报价单.pdf',file_url:'',origin:'Form',archive_status:'pending',downloadable:false,previewable:false,packing_candidate:false},
 {attachment_name:'ATT-3',process_instance_id:'PROC-3',file_id:'FILE-3',file_name:'evil.png',file_url:'javascript:alert(1)',origin:'Comment',archive_status:'archived',downloadable:true,previewable:true,packing_candidate:false,comment_remark:'<script>run()</script>'},
];
const html=w.renderDingtalkAttachments(items,true);
assert(html.includes('class="ocw-dingtalk-attachment-card"'));
assert(html.includes('<img class="ocw-dingtalk-attachment-thumb" loading="lazy"'));
assert(html.includes('src="/private/files/装箱 预览.png"'));
assert(!html.includes('src="/private/files/packing.png"'),'应优先合法 preview_url');
assert.equal((html.match(/ocw-dingtalk-attachment-thumb/g)||[]).length,1);
assert(html.includes('class="ocw-dingtalk-file-icon"'));
for(const action of ['preview-dingtalk-attachment','download-dingtalk-attachment','use-dingtalk-packing-source'])assert(html.includes(`data-action="${action}"`),action);
assert(!html.includes('装箱单 <bad>.png'));assert(html.includes('装箱单 &lt;bad&gt;.png'));
assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;run()&lt;/script&gt;'));
assert(!html.includes('src="javascript:'));
for(const unsafe of [
 '//evil.example/image.png','javascript:alert(1)','data:image/png;base64,AAAA','https://evil.example/image.png',
 '\n/private/files/a.png','/files/../../api/method/logout','/private/files/%2e%2e/api','/files/%252e%252e/api'
]){
 assert.equal(w.dingtalkAttachmentPreviewUrl({preview_url:unsafe}),'',unsafe);
}
const excluded=w.renderDingtalkApprovalCard({excluded:true,title:'已排除',business_id:'B-1',form_fields:[],timeline:[],attachments:[items[0]]},'已排除审批',true);
assert(excluded.includes('preview-dingtalk-attachment'));assert(excluded.includes('download-dingtalk-attachment'));
assert(!excluded.includes('use-dingtalk-packing-source'));
"""
    )


def test_responsive_css_keeps_tables_scoped_and_switches_goods_to_cards() -> None:
    css = CSS_PART.read_text(encoding="utf-8")

    assert ".ocw-dingtalk-form-grid" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    assert ".ocw-dingtalk-table-scroll" in css and "overflow-x: auto" in css
    assert ".ocw-dingtalk-goods-table thead" in css and "position: sticky" in css
    assert ".ocw-dingtalk-goods-code" in css and "left: 0" in css
    tablet = css.split("@media (max-width: 768px)", 1)[1].split("@media (max-width: 700px)", 1)[0]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in tablet
    mobile = css.split("@media (max-width: 700px)", 1)[1]
    assert ".ocw-dingtalk-goods-table" in mobile and "display: none" in mobile
    assert ".ocw-dingtalk-goods-cards" in mobile and "display: grid" in mobile
    assert "grid-template-columns: 1fr" in mobile
