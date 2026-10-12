package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.vo.PageVO;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.regex.Pattern;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import static com.yuewei.plm.module.collaboration.MoldCodeSourceTypes.*;

@Service
@RequiredArgsConstructor
public class MoldCodeSourceService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final CollaborationService collaboration;
    private static final Pattern CODE=Pattern.compile("^M([A-Z]{2})(10|20)([0-9]{4})$",Pattern.CASE_INSENSITIVE);

    public record Identity(String styleCode,String phoneCode,String part) {}
    public static Identity identity(String code) {
        var match=CODE.matcher(code);
        return match.matches()?new Identity(match.group(1).toUpperCase(Locale.ROOT),match.group(3),match.group(2).equals("20")?"PC":"TPU"):new Identity(null,null,null);
    }

    /** Preview storage is deliberately separate from physical sets and inventory. */
    @Transactional
    public Map<String,Object> previewErp(ErpPreview dto) {
        CurrentUser actor=collaboration.actor();
        if(!actor.allPermissions()) throw new BusinessException(40103,"仅管理员可载入 ERP 来源核对资料");
        var duplicates=new HashSet<String>();
        for(var row:dto.rows()) if(!duplicates.add(row.itemCode())) throw CollaborationFields.invalid("同一快照包含重复原编码："+row.itemCode());
        lock("erp-preview:"+dto.snapshotId());
        var payload=encode(dto);
        var prior=event("erp","mold_code_preview",dto.snapshotId());
        if(!prior.isEmpty()) {
            if(!payload.equals(prior.get(0).get("source_payload_json"))) throw CollaborationFields.invalid("相同快照 ID 的内容不一致");
            return Map.of("status","duplicate","created",0,"physicalSetsCreated",0,"conflicts",List.of());
        }
        int created=0;List<String> conflicts=new ArrayList<>();
        // Serialize overlapping snapshots, but never overwrite an earlier source baseline.
        lock("erp-code-catalog");
        for(var row:dto.rows()) {
            String fingerprint=codeFingerprint(row);
            var existing=jdbc.queryForList("select payload_fingerprint from plm_mold_code_source where source_system='erp' and mold_code=?",row.itemCode());
            if(!existing.isEmpty()) {if(!fingerprint.equals(existing.get(0).get("payload_fingerprint"))) conflicts.add(row.itemCode());continue;}
            insert("erp",dto.snapshotId(),null,null,row,fingerprint,actor.username());created++;
        }
        record("erp","mold_code_preview",dto.snapshotId(),"preview",payload,actor.username());
        return Map.of("status","preview_saved","created",created,"physicalSetsCreated",0,"conflicts",conflicts);
    }

    /** Uses the authenticated service account; incoming actor names are not audit identities. */
    @Transactional
    public Map<String,Object> receive(DingTalkCodeEvent dto) {
        CurrentUser actor=collaboration.actor();collaboration.requireGroup(actor,"engineering");
        if(dto.approvalStatus()!=null&&!dto.approvalStatus().equals("approved")) throw CollaborationFields.invalid("未通过的审批不能同步模具编码");
        if(dto.approvalStatus()!=null&&(dto.approvalInstanceId()==null||dto.approvalInstanceId().isBlank())) throw CollaborationFields.invalid("声明审批通过时必须携带真实审批实例 ID");
        lock("dingtalk-code-catalog");
        String payload=encode(dto);
        var prior=event("dingtalk","mold_code_catalog",dto.eventId());
        if(!prior.isEmpty()) {
            if(!payload.equals(prior.get(0).get("source_payload_json"))) throw new BusinessException(40901,"同一同步事件的内容已变化，请核对原事件");
            return result("duplicate",dto);
        }
        var row=dto.item();String fingerprint=codeFingerprint(row);
        var existing=jdbc.queryForList("select payload_fingerprint from plm_mold_code_source where source_system='dingtalk' and mold_code=?",row.itemCode());
        if(!existing.isEmpty()&&!fingerprint.equals(existing.get(0).get("payload_fingerprint"))) throw new BusinessException(40901,"已有同编码的名称或规格不同，请人工核对，未覆盖原资料");
        if(existing.isEmpty()) insert("dingtalk",dto.eventId(),dto.approvalInstanceId(),dto.approvalStatus(),row,fingerprint,actor.username());
        record("dingtalk","mold_code_catalog",dto.eventId(),dto.approvalStatus()==null?"code_received":"approved",payload,actor.username());
        return result(existing.isEmpty()?"created":"linked_existing",dto);
    }

    private Map<String,Object> result(String status,DingTalkCodeEvent dto) {
        return Map.of("status",status,"eventId",dto.eventId(),"moldCode",dto.item().itemCode(),"physicalSetsCreated",0,
            "approvalTrace",dto.approvalInstanceId()==null||dto.approvalInstanceId().isBlank()?"not_provided":"provided");
    }
    private void insert(String source,String event,String approvalId,String approvalStatus,SourceItem row,String fingerprint,String actor) {
        var identity=identity(row.itemCode());
        jdbc.update("""
            insert into plm_mold_code_source(source_system,mold_code,mold_name,item_group,specifications,original_alias,
                source_disabled,source_modified_at,product_specific_code,phone_model_code,part_type,approval_instance_id,
                approval_status,payload_fingerprint,source_event_id,created_by)
            values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,source,row.itemCode(),row.itemName(),row.itemGroup(),row.specifications(),row.originalAlias(),Boolean.TRUE.equals(row.disabled()),row.modified(),
            identity.styleCode(),identity.phoneCode(),identity.part(),approvalId,approvalStatus,fingerprint,event,actor);
    }
    private String codeFingerprint(SourceItem row) {
        // Source timestamps are not identity: ERP may touch them without changing the catalog.
        return sha256(encode(Arrays.asList(row.itemCode(),row.itemName(),row.itemGroup(),row.specifications(),row.originalAlias(),Boolean.TRUE.equals(row.disabled()))));
    }
    static String sha256(String value) {try {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));} catch(Exception e) {throw new IllegalStateException(e);}}
    private String encode(Object value) {try {return json.writeValueAsString(value);} catch(JsonProcessingException e) {throw CollaborationFields.invalid("来源字段无法序列化");}}
    private void lock(String key) {jdbc.queryForList("select pg_advisory_xact_lock(hashtextextended(?,0))",key);}
    private List<Map<String,Object>> event(String source,String type,String key) {return jdbc.queryForList("select source_payload_json from plm_integration_record where source_system=? and integration_type=? and external_instance_id=? and deleted_flag=0",source,type,key);}
    private void record(String source,String type,String key,String external,String payload,String actor) {
        jdbc.update("insert into plm_integration_record(source_system,integration_type,external_instance_id,external_status,source_payload_json,processing_status,created_by,updated_by) values(?,?,?,?,?,'succeeded',?,?)",source,type,key,external,payload,actor,actor);
    }

    private static final String CATALOG="""
        with archives as materialized (
            select upper(btrim(p.product_specific_code)) as style_code,btrim(i.phone_model_code) as phone_code,
                count(*) as archive_count,min(i.item_id) as item_id,min(i.style_name) as style_name,min(i.compatible_models) as compatible_models
            from plm_collaboration_item i join plm_product p on p.product_id=i.product_line_id and p.deleted_flag=0
            where i.deleted_flag=0 and i.phone_model_code is not null group by 1,2
        ), pairs as materialized (
            select source_system,product_specific_code,phone_model_code,
                count(*) filter(where part_type='PC' and not source_disabled) as pc_count,
                count(*) filter(where part_type='TPU' and not source_disabled) as tpu_count,
                count(distinct lower(btrim(regexp_replace(mold_name,'\\s+',' ','g')))) filter(where not source_disabled) as name_count
            from plm_mold_code_source where part_type is not null group by 1,2,3
        ), source_names as materialized (
            select lower(mold_code) as code_key,count(distinct lower(btrim(regexp_replace(mold_name,'\\s+',' ','g')))) as source_name_count
            from plm_mold_code_source group by 1
        ), catalog as (
            select s.*,coalesce(a.archive_count,0) as archive_count,
                case when a.archive_count=1 then a.item_id end as item_id,a.style_name,a.compatible_models,
                coalesce(p.pc_count,0) as pc_count,coalesce(p.tpu_count,0) as tpu_count,coalesce(p.name_count,0) as name_count,n.source_name_count
            from plm_mold_code_source s left join archives a on a.style_code=s.product_specific_code and a.phone_code=s.phone_model_code
            left join pairs p on p.source_system=s.source_system and p.product_specific_code=s.product_specific_code and p.phone_model_code=s.phone_model_code
            left join source_names n on n.code_key=lower(s.mold_code)
        )
        """;
    public PageVO<Map<String,Object>> page(Query q) {
        collaboration.actor();List<Object> args=new ArrayList<>();List<String> where=new ArrayList<>();
        if(q.getSource()!=null) {where.add("source_system=?");args.add(q.getSource());}
        if(q.getKeyword()!=null&&!q.getKeyword().isBlank()) {where.add("concat_ws(' ',mold_code,mold_name,item_group,specifications,original_alias,style_name,compatible_models) ilike ?");args.add("%"+q.getKeyword().trim()+"%");}
        if(q.getPart()!=null) {where.add(q.getPart().equals("nonstandard")?"part_type is null":"part_type=?");if(!q.getPart().equals("nonstandard")) args.add(q.getPart());}
        if(q.getReview()!=null) where.add(switch(q.getReview()) {
            case "matched" -> "archive_count=1";case "unmatched" -> "archive_count<>1";
            case "incomplete" -> "part_type is not null and (pc_count<>1 or tpu_count<>1)";
            case "name_conflict" -> "part_type is not null and name_count>1";case "source_conflict" -> "source_name_count>1";case "disabled" -> "source_disabled";
            default -> "part_type is null";
        });
        String clause=where.isEmpty()?"":" where "+String.join(" and ",where);
        Long total=jdbc.queryForObject(CATALOG+"select count(*) from catalog"+clause,Long.class,args.toArray());
        args.add(q.getSize());args.add(((long)q.getPage()-1)*q.getSize());
        var rows=jdbc.queryForList(CATALOG+"select * from catalog"+clause+" order by source_system,mold_code limit ? offset ?",args.toArray()).stream().map(this::view).toList();
        return new PageVO<>(rows,q.getPage(),q.getSize(),total==null?0:total,total==null?0:(total+q.getSize()-1)/q.getSize());
    }
    private Map<String,Object> view(Map<String,Object> row) {
        var result=new LinkedHashMap<String,Object>();
        Map.ofEntries(Map.entry("source_code_id","sourceCodeId"),Map.entry("source_system","sourceSystem"),Map.entry("mold_code","moldCode"),Map.entry("mold_name","moldName"),
            Map.entry("item_group","itemGroup"),Map.entry("specifications","specifications"),Map.entry("original_alias","originalAlias"),Map.entry("source_disabled","disabled"),
            Map.entry("source_modified_at","sourceModifiedAt"),Map.entry("product_specific_code","styleCode"),Map.entry("phone_model_code","phoneModelCode"),Map.entry("part_type","partType"),
            Map.entry("approval_instance_id","approvalInstanceId"),Map.entry("approval_status","approvalStatus"),Map.entry("created_by","receivedBy"),Map.entry("created_at","receivedAt"),
            Map.entry("archive_count","archiveCount"),Map.entry("item_id","itemId"),Map.entry("style_name","styleName"),Map.entry("compatible_models","compatibleModels"),
            Map.entry("pc_count","pcCount"),Map.entry("tpu_count","tpuCount"),Map.entry("name_count","nameCount"),Map.entry("source_name_count","sourceNameCount")).forEach((column,key)->result.put(key,row.get(column)));
        return result;
    }
    public Map<String,Object> summary() {
        collaboration.actor();return jdbc.queryForMap(CATALOG+"""
            select count(*) as total,count(*) filter(where source_system='erp') as erp,
                count(*) filter(where source_system='dingtalk') as dingtalk,count(*) filter(where part_type is null) as nonstandard,
                count(*) filter(where part_type='PC' and pc_count=1 and tpu_count=1) as paired,
                count(*) filter(where part_type='PC' and pc_count=1 and tpu_count=1 and name_count>1) as name_conflicts,
                count(distinct lower(mold_code)) filter(where source_name_count>1) as source_conflicts
            from catalog
            """);
    }
}
