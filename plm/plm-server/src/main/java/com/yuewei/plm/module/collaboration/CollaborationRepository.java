package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.vo.PageVO;
import java.sql.*;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
@RequiredArgsConstructor
public class CollaborationRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private static final String PROJECT_JOIN="""
        left join (select item_id,count(*) as project_count,
            jsonb_agg(jsonb_build_object('projectId',p.product_id,'productCode',p.product_code,
                'productName',p.product_name,'color',p.color,'status',p.status) order by p.product_id) as projects
          from plm_collaboration_item_project ip join plm_product p on p.product_id=ip.project_id and p.deleted_flag=0
          group by item_id) links on links.item_id=i.item_id
        left join plm_product line on line.product_id=i.product_line_id and line.deleted_flag=0
        """;
    private static final String PART_JOIN="""
        left join plm_collaboration_mold_part pc on pc.mold_set_id=s.mold_set_id and pc.part_type='PC'
        left join plm_collaboration_mold_part tpu on tpu.mold_set_id=s.mold_set_id and tpu.part_type='TPU'
        left join plm_product_mold_code pcm on pcm.product_mold_code_id=pc.product_mold_code_id and pcm.deleted_flag=0
        left join plm_product_mold_code tpum on tpum.product_mold_code_id=tpu.product_mold_code_id and tpum.deleted_flag=0
        left join plm_inventory pci on pci.inventory_id=pc.inventory_id and pci.deleted_flag=0
        left join plm_inventory tpui on tpui.inventory_id=tpu.inventory_id and tpui.deleted_flag=0
        left join sys_user owner on owner.user_id=s.owner_user_id
        """;
    static String statusSql(String view) {
        return switch(view) {
            case "delivery" -> "case when s.actual_mexico_arrival_date is not null then 'mexico_arrived' when s.actual_ship_date is not null then 'shipped' when pc.status='ready' and tpu.status='ready' then 'ready' when s.opened_date is not null or pc.status<>'pending' or tpu.status<>'pending' then 'making' else 'pending' end";
            case "production" -> "case when i.pc_total is not null or i.tpu_total is not null or i.finished_total is not null then 'recorded' else 'missing' end";
            default -> "case when coalesce(links.project_count,0)>0 then 'linked' else 'candidate' end";
        };
    }
    static String moldStatusSql() {
        return "case when pc.acceptance_status='failed' or tpu.acceptance_status='failed' then 'acceptance_failed' "+
            "when pc.acceptance_status='passed' and tpu.acceptance_status='passed' and pc.factory_arrival_date is not null and tpu.factory_arrival_date is not null then 'delivered' "+
            "when pc.acceptance_status='passed' or tpu.acceptance_status='passed' then 'partially_accepted' "+
            "when (pc.factory_arrival_date is not null or pc.current_location='mexico_factory') and (tpu.factory_arrival_date is not null or tpu.current_location='mexico_factory') then 'awaiting_acceptance' "+
            "when pc.factory_arrival_date is not null or tpu.factory_arrival_date is not null or pc.current_location='mexico_factory' or tpu.current_location='mexico_factory' then 'partially_arrived' else "+statusSql("delivery")+" end";
    }
    public static String assetSql() {return "('MS-'||lpad(s.mold_set_id::text,greatest(6,length(s.mold_set_id::text)),'0'))";}
    private static String from(String view) {
        return " from plm_collaboration_item i "+("delivery".equals(view)
            ?"join plm_collaboration_mold_set s on s.item_id=i.item_id and s.deleted_flag=0 "+PART_JOIN:"")+PROJECT_JOIN;
    }
    private static String select(String view) {
        return select(view,view.equals("delivery"));
    }
    private static String select(String view,boolean ledger) {
        String extra="delivery".equals(view)?"""
            ,s.mold_set_id,s.set_no,s.set_name,s.opened_date,s.planned_mold_delivery_date,s.actual_ship_date,
             s.planned_factory_arrival_date,s.actual_mexico_arrival_date,s.arrival_confirmed_basis_date,s.notes,
             pc.status as pc_status,tpu.status as tpu_status,
             pc.product_mold_code_id as pc_mold_code_id,tpu.product_mold_code_id as tpu_mold_code_id,
             pcm.mold_code as pc_catalog_mold_code,tpum.mold_code as tpu_catalog_mold_code,
             coalesce(pcm.mold_code,pc.original_mold_code) as pc_mold_code,coalesce(tpum.mold_code,tpu.original_mold_code) as tpu_mold_code,
             pc.original_mold_code as pc_original_mold_code,tpu.original_mold_code as tpu_original_mold_code,
             pc.inventory_id as pc_inventory_id,tpu.inventory_id as tpu_inventory_id,
             pci.inventory_code as pc_inventory_code,pci.inventory_name as pc_inventory_name,
             tpui.inventory_code as tpu_inventory_code,tpui.inventory_name as tpu_inventory_name,
             s.source_mold_set_id,s.manufacturer_name,s.owner_user_id,owner.display_name as owner_name,
             pc.current_location as pc_current_location,tpu.current_location as tpu_current_location,
             pc.location_detail as pc_location_detail,tpu.location_detail as tpu_location_detail,
             pc.factory_arrival_date as pc_factory_arrival_date,tpu.factory_arrival_date as tpu_factory_arrival_date,
             pc.acceptance_status as pc_acceptance_status,tpu.acceptance_status as tpu_acceptance_status,
             pc.acceptance_date as pc_acceptance_date,tpu.acceptance_date as tpu_acceptance_date,
             pc.acceptance_issues as pc_acceptance_issues,tpu.acceptance_issues as tpu_acceptance_issues,
             s.updated_at as updated_at,
             s.plan_start_date,s.manufacturing_days,s.holiday_days,s.extra_days,
             s.forecast_delivery_date,s.forecast_factory_date,s.forecast_acceptance_date,s.forecast_production_date,
             s.planned_acceptance_date,s.planned_production_date,s.actual_port_arrival_date,
             s.pc_signed_date,s.tpu_signed_date,s.actual_supplier_trial_date,s.actual_trial_date,s.actual_production_date,s.market_ready_date,
             s.logistics_owner_user_id,s.mexico_owner_user_id,s.production_owner_user_id,s.schedule_notes,
             (s.planned_mold_delivery_date+7) as suggested_factory_arrival_date,
             (s.planned_factory_arrival_date is not null and s.arrival_confirmed_basis_date is distinct from s.planned_mold_delivery_date) as arrival_needs_review
            """+","+assetSql()+" as asset_number,"+assetSql()+"||'-PC' as pc_asset_number,"+assetSql()+"||'-TPU' as tpu_asset_number,"+moldStatusSql()+" as delivery_status":",i.notes,i.updated_at";
        return """
            select i.item_id,i.product_line_id,i.style_name,i.brand,i.compatible_models,i.phone_model_code,
              i.phone_price,i.price_currency,i.sales_platform,i.reference_url,i.pc_total,i.tpu_total,i.finished_total,
              i.production_notes,line.product_name as product_line_name,coalesce(links.project_count,0) as project_count,
              coalesce(links.projects,'[]'::jsonb)::text as projects_json,
              (select count(*) from plm_collaboration_mold_set ms where ms.item_id=i.item_id and ms.deleted_flag=0) as mold_set_count,
            """+(ledger?moldStatusSql():statusSql(view))+" as status"+extra;
    }
    public PageVO<Map<String,Object>> page(CollaborationTypes.Query q,Set<String> writableGroups) {
        return page(q,writableGroups,"true");
    }
    public PageVO<Map<String,Object>> page(CollaborationTypes.Query q,Set<String> writableGroups,String scope) {
        String view=q.getView(); StringBuilder where=new StringBuilder(" where i.deleted_flag=0");
        where.append(" and (").append(scope).append(")");
        List<Object> args=new ArrayList<>();
        if(q.getItemId()!=null) {where.append(" and i.item_id=?");args.add(q.getItemId());}
        if("delivery".equals(view)&&q.getMoldSetId()!=null) {where.append(" and s.mold_set_id=?");args.add(q.getMoldSetId());}
        if(q.getProductLineId()!=null) {where.append(" and i.product_line_id=?");args.add(q.getProductLineId());}
        if(q.getKeyword()!=null&&!q.getKeyword().isBlank()) {
            where.append(" and (concat_ws(' ',i.style_name,i.brand,i.compatible_models,i.phone_model_code,i.sales_platform) ilike ?");
            String pattern="%"+q.getKeyword().trim().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%";
            args.add(pattern);
            if("delivery".equals(view)) {where.append(" or concat_ws(' ',s.set_name,"+assetSql()+",pcm.mold_code,tpum.mold_code,pc.original_mold_code,tpu.original_mold_code,s.manufacturer_name,owner.display_name) ilike ?");args.add(pattern);}
            where.append(")");
        }
        if(q.getStatus()!=null&&!q.getStatus().isBlank()) {where.append(" and (").append(q.isSchedule()?"case when s.market_ready_date is not null then 'market_ready' else "+moldStatusSql()+" end":q.isMoldLedger()?moldStatusSql():statusSql(view)).append(")=?");args.add(q.getStatus());}
        if("delivery".equals(view)&&q.getLocation()!=null&&!q.getLocation().isBlank()) {
            if(q.getLocation().equals("unknown")) where.append(" and (pc.current_location is null or tpu.current_location is null)");
            else {where.append(" and (pc.current_location=? or tpu.current_location=?)");args.add(q.getLocation());args.add(q.getLocation());}
        }
        if(q.isMineOnly()) where.append(" and (").append(q.isSchedule()?MoldScheduleService.missingSql(writableGroups):missingSql(view,writableGroups)).append(")");
        if(q.isSchedule()&&q.isOverdueOnly()) where.append(" and (").append(MoldScheduleService.overdueSql()).append(")");
        Long count=jdbc.queryForObject("select count(*)"+from(view)+where,Long.class,args.toArray());
        long total=count==null?0:count;
        args.add(q.getSize());args.add((long)(q.getPage()-1)*q.getSize());
        String sort="delivery".equals(view)?"s.opened_date desc nulls last,s.mold_set_id desc":"i.updated_at desc,i.item_id desc";
        List<Map<String,Object>> rows=jdbc.query(select(view,q.isMoldLedger())+from(view)+where+" order by "+sort+" limit ? offset ?",this::map,args.toArray());
        return new PageVO<>(rows,q.getPage(),q.getSize(),total,(total+q.getSize()-1)/q.getSize());
    }
    static String missingSql(String view,Set<String> groups) {
        List<String> missing=new ArrayList<>();
        if(view.equals("market")&&groups.contains("market")) missing.add("i.brand is null or i.reference_url is null");
        if(view.equals("production")&&groups.contains("production")) missing.add("i.pc_total is null or i.tpu_total is null or i.finished_total is null");
        if(view.equals("delivery")) {
            if(groups.contains("engineering")) missing.add("s.opened_date is null or s.planned_mold_delivery_date is null or s.manufacturer_name is null or s.owner_user_id is null or coalesce(pcm.mold_code,pc.original_mold_code) is null or coalesce(tpum.mold_code,tpu.original_mold_code) is null");
            if(groups.contains("logistics")) missing.add("s.planned_mold_delivery_date is not null and (s.planned_factory_arrival_date is null or s.arrival_confirmed_basis_date is distinct from s.planned_mold_delivery_date or (pc.status='ready' and tpu.status='ready' and s.actual_ship_date is null))");
            if(groups.contains("logistics")) missing.add("pc.current_location is null or tpu.current_location is null or (s.actual_ship_date is not null and s.actual_mexico_arrival_date is null)");
            if(groups.contains("mexico")) missing.add("(s.actual_ship_date is not null or s.actual_mexico_arrival_date is not null or pc.factory_arrival_date is not null or tpu.factory_arrival_date is not null or pc.current_location='mexico_factory' or tpu.current_location='mexico_factory') and (pc.factory_arrival_date is null or tpu.factory_arrival_date is null or pc.acceptance_status<>'passed' or tpu.acceptance_status<>'passed')");
        }
        return missing.isEmpty()?"false":String.join(" or ",missing.stream().map(s->"("+s+")").toList());
    }
    public Map<String,Object> row(String entity,long id) {
        String view="mold_set".equals(entity)?"delivery":"market";
        List<Map<String,Object>> rows=jdbc.query(select(view)+from(view)+" where i.deleted_flag=0 and "+
            (view.equals("delivery")?"s.mold_set_id":"i.item_id")+"=?",this::map,id);
        if(rows.isEmpty()) throw new com.yuewei.plm.common.exception.BusinessException(40401,"协作记录不存在");
        return rows.get(0);
    }
    /** Import previews share two bulk snapshots rather than querying once per spreadsheet row. */
    public List<Map<String,Object>> previewRows(String entity) {
        return previewRows(entity,"true");
    }
    public List<Map<String,Object>> previewRows(String entity,String scope) {
        String view="mold_set".equals(entity)?"delivery":"market";
        return jdbc.query(select(view)+from(view)+" where i.deleted_flag=0 and ("+scope+")",this::map);
    }
    public List<Map<String,Object>> productLines() {
        return jdbc.query("select product_id as product_line_id,product_name,product_code,status from plm_product where deleted_flag=0 and product_type='product_line' order by product_name",this::map);
    }
    public List<Map<String,Object>> users() {
        return jdbc.query("select user_id,username,display_name,department_name,all_permissions from sys_user where deleted_flag=0 and status='active' order by user_id",this::map);
    }
    public List<Map<String,Object>> projectOptions(Long productLineId,String keyword) {
        List<Object> args=new ArrayList<>();String where="where p.deleted_flag=0 and p.product_type='model_variant'";
        if(productLineId!=null) {where+=" and p.parent_product_id=?";args.add(productLineId);}
        if(keyword!=null&&!keyword.isBlank()) {where+=" and concat_ws(' ',p.product_code,p.product_name,p.model,p.phone_model_code) ilike ?";args.add("%"+keyword.trim().replace("%","\\%").replace("_","\\_")+"%");}
        return jdbc.query("select p.product_id as project_id,p.parent_product_id as product_line_id,p.product_code,p.product_name,p.model,p.phone_model_code,p.color,p.status,ip.item_id as linked_item_id from plm_product p left join plm_collaboration_item_project ip on ip.project_id=p.product_id "+where+" order by p.product_id desc limit 100",this::map,args.toArray());
    }
    public List<Map<String,Object>> moldCodes(Long itemId,String keyword) {
        List<Object> args=new ArrayList<>();String where="where mc.deleted_flag=0";
        if(itemId!=null) {where+=" and (exists(select 1 from plm_collaboration_item_project ip where ip.item_id=? and ip.project_id=mc.product_id) or mc.product_id=(select product_line_id from plm_collaboration_item where item_id=?))";args.add(itemId);args.add(itemId);}
        if(keyword!=null&&!keyword.isBlank()) {where+=" and concat_ws(' ',mc.mold_code,mc.mold_name) ilike ?";args.add("%"+keyword.trim().replace("%","\\%").replace("_","\\_")+"%");}
        return jdbc.query("select mc.product_mold_code_id as mold_code_id,mc.product_id,mc.mold_code,mc.mold_name,mc.key_code from plm_product_mold_code mc "+where+" order by mc.mold_code limit 100",this::map,args.toArray());
    }
    public List<Map<String,Object>> moldInventoryOptions(String keyword) {
        if(keyword==null||keyword.trim().length()<2) return List.of();
        String pattern="%"+keyword.trim().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%";
        return jdbc.query("select inventory_id,inventory_code,inventory_name,inventory_type,specification from plm_inventory where deleted_flag=0 and concat_ws(' ',inventory_code,inventory_name,specification) ilike ? order by inventory_code limit 100",this::map,pattern);
    }
    public PageVO<Map<String,Object>> moldHistory(long id,int page,int size) {
        row("mold_set",id);
        Long total=jdbc.queryForObject("select count(*) from plm_collaboration_history where entity_type='mold_set' and entity_id=?",Long.class,id);
        List<Map<String,Object>> rows=jdbc.query("select history_id,entity_type,entity_id,field_name,before_value::text as before_json,after_value::text as after_json,reason,actor_name,changed_at from plm_collaboration_history where entity_type='mold_set' and entity_id=? order by history_id desc limit ? offset ?",this::map,id,size,(long)(page-1)*size);
        return new PageVO<>(rows,page,size,total==null?0:total,(total==null?0:total+size-1)/size);
    }
    public Map<String,Object> references(long itemId) {
        Map<String,Object> item=row("item",itemId);
        List<Map<String,Object>> express=jdbc.query("""
            select e.mold_transfer_express_id,e.project_id,e.timeline_node_key,e.tracking_no,e.shipped_at,e.latest_status_text
            from plm_project_mold_transfer_express e join plm_collaboration_item_project ip on ip.project_id=e.project_id
            where ip.item_id=? and e.deleted_flag=0 and e.status='active' order by e.mold_transfer_express_id desc
            """,this::map,itemId);
        return Map.of("item",item,"expressRecords",express);
    }
    public PageVO<Map<String,Object>> history(long itemId,int page,int size) {
        row("item",itemId);
        Long total=jdbc.queryForObject("select count(*) from plm_collaboration_history where item_id=?",Long.class,itemId);
        List<Map<String,Object>> rows=jdbc.query("select history_id,entity_type,entity_id,field_name,before_value::text as before_json,after_value::text as after_json,reason,actor_id,actor_name,changed_at from plm_collaboration_history where item_id=? order by history_id desc limit ? offset ?",this::map,itemId,size,(long)(page-1)*size);
        return new PageVO<>(rows,page,size,total==null?0:total,(total==null?0:total+size-1)/size);
    }
    private Map<String,Object> map(ResultSet rs,int row) throws SQLException {
        Map<String,Object> values=new LinkedHashMap<>();ResultSetMetaData meta=rs.getMetaData();
        for(int n=1;n<=meta.getColumnCount();n++) {
            String key=camel(meta.getColumnLabel(n));Object value=rs.getObject(n);
            if(value instanceof java.sql.Date date) value=date.toLocalDate().toString();
            else if(value instanceof Timestamp time) value=time.toInstant().toString();
            if(key.endsWith("Json")) {
                key=key.substring(0,key.length()-4);
                try {value=value==null?null:json.readValue(value.toString(),new TypeReference<Object>(){});}
                catch(Exception e) {throw new SQLException("Invalid collaboration JSON",e);}
            }
            values.put(key,value);
        }
        return values;
    }
    public static String camel(String snake) {
        StringBuilder text=new StringBuilder();boolean upper=false;
        for(char c:snake.toCharArray()) {if(c=='_') upper=true;else {text.append(upper?Character.toUpperCase(c):c);upper=false;}}
        return text.toString();
    }
}
