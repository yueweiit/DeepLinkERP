/* DOM/network boundary for the production Frappe control contract inspected 2026-10-03.
 * Search methods below retain native callback ordering, including the awaited Link
 * filter description. This harness is not browser acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const requests = [];
const timers = new Map();
let timerId = 0;
let now = 0;
const schedule=(fn,delay=0)=>{timers.set(++timerId,{fn,due:now+delay});return timerId;};
const clock = {
    tick(ms) {const end=now+ms;let next;
        while((next=[...timers].filter(([,item])=>item.due<=end).sort((a,b)=>a[1].due-b[1].due)[0])){
            timers.delete(next[0]);now=next[1].due;next[1].fn();}
        now=end;},
    expire() {const latest=Math.max(now,...[...timers.values()].map(item=>item.due));this.tick(latest-now);}
};
function debounce(fn,delay){let timer;const handler=(...args)=>{handler.cancel();timer=schedule(()=>fn(...args),delay);};
    handler.cancel=()=>{timers.delete(timer);timer=undefined;};return handler;}
class Input {
    constructor(value='') { this.value=value;this.writes=[];this.listeners={};this.focused=true;this.isConnected=true; }
    addEventListener(type,fn,capture=false) { (this.listeners[type] ||= []).push({fn,capture}); }
    dispatch(type,patch={}) {
        const event={type,target:this,key:undefined,keyCode:undefined,defaultPrevented:false,
            preventDefault(){this.defaultPrevented=true},...patch};
        for(const capture of [true,false]) for(const listener of [...(this.listeners[type]||[])])
            if(Boolean(listener.capture)===capture)listener.fn(event);
        return event;
    }
}
function jq(input) {
    const wrapper={0:input,length:1,cache:{},get:()=>input,
        val(value) { if(arguments.length){input.value=value;input.writes.push(value);return this}return input.value; },
        is:selector=>selector===':focus'?input.focused:false,
        prop:name=>input[name],
        on(events,fn) { events.split(' ').forEach(event=>input.addEventListener(event.split('.')[0],fn));return this; },
        trigger(type,patch) { if(type==='blur')input.focused=false;if(type==='focus')input.focused=true;
            return input.dispatch(type,patch); }};
    return wrapper;
}
const document=new Input();document.readyState='complete';
const $=obj=>obj===document?jq(document):obj;
$.isPlainObject=obj=>obj!=null&&typeof obj==='object'&&!Array.isArray(obj);
$.each=(obj,fn)=>Object.entries(obj).forEach(([key,value])=>fn(key,value));
class Awesome {
    constructor(control,multi=false) {
        this.control=control;this.input=control.input;this.tabSelect=!multi;this.autoFirst=true;
        this.index=-1;this.visible=[];this._list=[];this.opened=false;
        this.filter=function(item,term) { return !item.hidden&&(item.label||item.value).includes(term); };
        this.replace=function(item) {this.input.value=item.label||item.value;};
        if(multi)this.replace=function(item){const before=this.input.value.match(/^.+,\s*|/)[0];this.input.value=before+(item.label||item.value)+', ';};
        // Awesomplete owns an earlier input listener than Frappe's query listener.
        this.input.addEventListener('input',()=>this.evaluate());
        this.input.addEventListener('focus',()=>this.evaluate());
    }
    set list(items) {this._list=Array.from(items,item=>typeof item==='string'?{value:item,label:item}:item);this.evaluate();}
    get list(){return this._list;}
    evaluate(){this.visible=Array.from(this._list).filter(item=>this.filter.call(this,item,this.input.value));
        this.index=this.autoFirst&&this.visible.length?0:-1;
        if(this.visible.length)this.open();else this.close({reason:'nomatches'});}
    open(){if(this.visible.length)this.opened=true;}
    close(options={}){if(!this.opened)return;this.opened=false;this.input.dispatch('awesomplete-close',options);}
    get_item(value){return this._list.find(item=>item.value===value);}
    select(value,originalEvent){const item=this.get_item(value);
        const event=this.input.dispatch('awesomplete-select',{text:item,originalEvent:{text:item,originalEvent}});
        if(event.defaultPrevented)return false;
        this.replace(item);this.close();this.input.dispatch('awesomplete-selectcomplete',{text:item,originalEvent:{text:item}});return true;}
}
class Base {
    constructor(options) {
        this.doc={company:'A',item:'SKU'};this.frm={doc:this.doc};this.doctype='Stock Entry';this.docname='ROW';
        this.df={fieldname:'warehouse',options:'Warehouse',ignore_user_permissions:1,only_select:1,...options.df};
        this.disp_status='Write';this.changed=0;this.nativeSelections=0;this.hrefUpdates=0;
        this.initial=options.value||'';this.modelValue=this.last_value=options.modelValue??this.initial;
        if(options.standalone){delete this.doc;delete this.frm;delete this.doctype;delete this.docname;
            delete this.modelValue;delete this.last_value;}
        this.query=Boolean(options.query);this.make_input();
    }
    make_input(){this.input=new Input(this.initial);this.$input=jq(this.input);this.awesomplete=new Awesome(this,this.df.fieldtype==='MultiSelect');}
    parse_validate_and_set_in_model(value){
        if(!this.frm&&!this.doc){this.changed++;this.nativeSelections++;return this.validate_and_set_in_model(value);}
        const result=this.validate?this.validate(value):value;
        this.changed++;this.nativeSelections++;this.selectedValue=this.modelValue=this.last_value=result;}
    // Native BaseControl/Data standalone lifecycle: set_input remembers the
    // previous value in last_value, not the newly initialized control value.
    set_value(value){return this.validate_and_set_in_model(value);}
    validate_and_set_in_model(value){if(this.inside_change_event||this.get_model_value()===value)return Promise.resolve();
        this.inside_change_event=true;const validated=this.validate(value);
        return Promise.resolve(validated).then(value=>{this.inside_change_event=false;return this.set_model_value(value);});}
    set_model_value(value){if(this.frm){this.modelValue=this.last_value=value;return Promise.resolve();}
        if(this.doc)this.doc[this.df.fieldname]=value;this.set_input(value);return Promise.resolve();}
    set_input(value){this.last_value=this.value;this.value=value;this.set_formatted_input(value);}
    set_formatted_input(value){this.$input.val(value==null?'':value);}
    get_input_value(){return this.$input.val();}
    get_label_value(){return this.$input.val();}
    get_translated(value){return value;}
    get_options(){return this.df.options;}
    get_reference_doctype(){return this.doctype;}
    get_model_value(){return this.doc?this.modelValue:undefined;}
}
class NativeLink extends Base {
    make_input(){super.make_input();this.awesomplete.filter=()=>true;
        this.$input.on('focus',()=>{if(!this.$input.val())this.on_input();});
        this._debounced_input_handler=debounce(this.on_input.bind(this),500);
        this.$input.on('input',this._debounced_input_handler);
        this.$input.on('awesomplete-select',e=>{const o=e.originalEvent,item=this.awesomplete.get_item(o.text.value);
            const event=o.originalEvent;
            if(event&&[9,13].includes(event.keyCode)){const input=this.get_label_value().toLowerCase();
                if(!input&&event.keyCode===9){e.preventDefault();this.awesomplete.close();return false;}
                else if(input&&!this.input_matches_item(input,item)){e.preventDefault();event.preventDefault?.();return false;}}
            if(item.value==='filter_description__link_option'){e.preventDefault();return false;}
            if(item.action){item.value='';item.label='';item.action.apply(this);}
            this.parse_validate_and_set_in_model(item.value,null,item.label);});}
    input_matches_item(input,item){return input&&((item.label||item.value).toLowerCase().includes(input)||(item.description||'').toLowerCase().includes(input));}
    get_search_args(txt){const args={txt,doctype:this.get_options(),ignore_user_permissions:this.df.ignore_user_permissions,
        reference_doctype:this.get_reference_doctype(),page_length:37,link_fieldname:this.df.fieldname};
        this.set_custom_query(args);return args;}
    set_custom_query(args){if(this.query){args.query='custom.allowed';args.filters={company:this.doc.company,is_group:0,item:this.doc.item};}}
    are_filters_large(filters){return [false,JSON.stringify(filters)];}
    merge_duplicates(results){return results.filter((item,index)=>results.findIndex(other=>other.value===item.value)===index);}
    async get_filter_description(){return null;}
    toggle_href(){this.hrefUpdates++;}
    new_doc(){} open_advanced_search(){}
    // Native Link.on_input receiver/callback contract, including native cache and async await.
    on_input(e) {
        const term=e?e.target.value:this.$input.val();const args=this.get_search_args(term);if(!args)return;
        const doctype=args.doctype;const cache=this.$input.cache;if(!cache[doctype])cache[doctype]={};
        if(cache[doctype][term]!=null)this.awesomplete.list=cache[doctype][term];
        const filters=args.filters;let use_get=!term&&!this.$input._created_new_doc;
        if(use_get){const [large,filters_str]=this.are_filters_large(filters);use_get=!large;args.filters=filters_str;}
        frappe.call({type:use_get?'GET':'POST',method:'frappe.desk.search.search_link',no_spinner:true,cache:use_get,args,
            callback:async r=>{
                if(!window.Cypress&&!this.$input.is(':focus'))return;
                r.message=this.merge_duplicates(r.message);
                const description=this.df.filter_description?this.df.filter_description:filters?await this.get_filter_description(filters):null;
                if(description)r.message.push({html:description,value:'filter_description__link_option',action:()=>{}});
                if(!this.df.only_select){if(frappe.model.can_create(doctype))r.message.push({label:'Create',value:'create_new__link_option',action:this.new_doc});
                    const custom=frappe.ui.form.ControlLink.link_options&&frappe.ui.form.ControlLink.link_options(this);
                    if(custom)r.message=r.message.concat(custom);
                    if(locals&&locals.DocType)r.message.push({label:'Advanced Search',value:'advanced_search__link_option',action:this.open_advanced_search});}
                cache[doctype][term]=r.message;this.awesomplete.list=cache[doctype][term];this.toggle_href(doctype);
                r.message.forEach(item=>frappe.utils.add_link_title(doctype,item.value,item.label));
            }});
    }
}
class NativeAutocomplete extends Base {
    constructor(options){super(options);if(this.query)this.get_query={query:'custom.options',params:{company:'A'}};}
    make_input(){super.make_input();this.awesomplete.tabSelect=false;
        this.$input.on('input',e=>{if(this.get_query||this.df.get_query)this.execute_query_if_exists(e.target.value);else this.awesomplete.list=this.get_data();});
        this.$input.on('focus',()=>{if(!this.$input.val()){this.$input.val('');this.$input.trigger('input');}});
        this.$input.on('blur',()=>{if(this.selected){this.selected=false;return;}
            const value=this.get_input_value();if(value!==this.last_value)this.parse_validate_and_set_in_model(value);});
        this.$input.on('awesomplete-selectcomplete',()=>{this.$input.trigger('change');});
        this.$input.on('change',()=>this.parse_validate_and_set_in_model(this.get_input_value()));
        this.set_data([{value:'ALPHA'},{value:'BETA'},{value:'HIDDEN',hidden:true}]);}
    get_data(){return this._data||[];}
    get_input_value(){const label=this.$input.val(),item=this._data?.find(item=>item.label===label);return item?item.value:label;}
    parse_options(data){if(typeof data==='string')data=data[0]==='['?JSON.parse(data):data.split('\n');
        if(typeof data[0]==='string')data=data.map(value=>({label:value,value}));
        return data.map(item=>({...item,label:String(item.label??''),value:String(item.value??'')}));}
    set_data(data){data=this.parse_options(data);if(this.awesomplete)this.awesomplete.list=data;this._data=data;}
    validate(value){if(this.df.ignore_validation)return value||'';
        const values=this.awesomplete._list.map(item=>item.value);return !values.length||values.includes(value)?value:'';}
    execute_query_if_exists(term) {
        const args={txt:term};let get_query=this.get_query||this.df.get_query;if(!get_query)return;
        const process=function(obj){if(obj.query)args.query=obj.query;if(obj.params)Object.assign(args,obj.params);
            if(obj.translate_values!==undefined)this.translate_values=obj.translate_values;};
        if($.isPlainObject(get_query))process(get_query);else if(typeof get_query==='string')args.query=get_query;
        else {const q=get_query((this.frm&&this.frm.doc)||this.doc,this.doctype,this.docname);
            if(typeof q==='string')args.query=q;else if($.isPlainObject(q))process(q);}
        if(args.query)frappe.call({method:args.query,args,callback:({message})=>{
            if(!this.$input.is(':focus'))return;this.set_data(message);}});
    }
}
class DynamicLink extends NativeLink {get_options(){return this.doc.target||'Warehouse';}}
class MultiSelect extends NativeAutocomplete {
    get_values(){return this.$input.val().split(/\s*,\s*/).filter(Boolean);}
    validate(value){if(this.df.ignore_validation)return value||'';
        const values=this.awesomplete._list.map(item=>item.value);if(!values.length)return value;
        return value.replace(/,\s*$/,'').split(',').every(item=>values.includes(item))?value:'';}
}
const frappe={ui:{form:{ControlLink:NativeLink,ControlDynamicLink:DynamicLink,ControlAutocomplete:NativeAutocomplete,
    ControlMultiSelect:MultiSelect,ControlSelect:class extends Base{},ControlMultiSelectList:class extends Base{}}},
    call:options=>requests.push(options),model:{can_create:()=>false},utils:{add_link_title(){},debounce},
    provide(){},boot:{sysdefaults:{link_field_results_limit:37}}};
const window={frappe,Cypress:false};const locals={};
const context={window,frappe,$,document,locals,console,Proxy,WeakMap,Map,Set,
    setTimeout:schedule,clearTimeout:id=>timers.delete(id)};
vm.createContext(context);
if(process.env.SELECTION_CLASSES_LATE){delete frappe.ui.form.ControlLink;delete frappe.ui.form.ControlAutocomplete;}
function load(){const asset=path.join(__dirname,'../../public/js/selection_dropdown.bundle.js');
    vm.runInContext(fs.existsSync(asset)?fs.readFileSync(asset,'utf8'):'',context);}
load();
function makeControl(kind,options={}) {const Class=frappe.ui.form['Control'+kind];
    return new Class({...options,df:{fieldtype:kind,...options.df}});}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function reply(index,message=[{value:'ALPHA'},{value:'BETA'}]) {await requests[index].callback({message});await flush();}
function inputEvent(control,value,{defer=false}={}){control.input.value=value;control.input.dispatch('input');if(!defer)clock.tick(500);}
module.exports={assert,makeControl,requests,reply,flush,load,frappe,inputEvent,document,clock,NativeLink,NativeAutocomplete};
