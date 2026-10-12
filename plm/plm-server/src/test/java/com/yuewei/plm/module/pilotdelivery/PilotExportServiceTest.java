package com.yuewei.plm.module.pilotdelivery;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.infrastructure.storage.StorageClient;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.pilot.PilotAccessService;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.ZipInputStream;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class PilotExportServiceTest {
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    static class Exporter extends PilotExportService {
        List<Map<String,Object>> attachments=List.of();final List<String> queries=new ArrayList<>();boolean lineage;
        Exporter(ObjectMapper json,PilotTrialService trials,PilotAccessService access,StorageClient storage,OperationLogService logs){super(mock(JdbcTemplate.class),json,trials,access,storage,logs);}
        @Override List<Map<String,Object>> records(String sql,Object...args){
            queries.add(sql);if(sql.contains("from plm_attachment"))return attachments;
            if(sql.startsWith("select * from plm_product where"))return lineage?List.of(Map.of("product_id",1,"workflow_template_id",5),Map.of("product_id",2,"workflow_template_id",5)):List.of(Map.of("product_id",1),Map.of("product_id",2));
            if(!lineage)return new ArrayList<>();
            if(sql.startsWith("select p.product_id"))return sql.endsWith("(false)")?List.of():List.of(Map.of("product_id",3));
            if(sql.startsWith("select product_id,parent_product_id"))return List.of(Map.of("product_id",3,"product_code","SRC","product_name","只读来源平台"));
            if(sql.startsWith("select * from plm_product_bom where"))return sql.contains("product_id in")?List.of(Map.of("product_bom_id",10,"product_id",2,"source_product_bom_id",12)):List.of(Map.of("product_bom_id",12,"product_id",3,"version_no","SOURCE-V1"));
            if(sql.startsWith("select * from plm_product_bom_route where"))return sql.contains("product_id in")?List.of(Map.of("product_bom_route_id",100,"product_bom_id",10,"product_id",2,"process_id",20,"source_product_bom_route_id",200)):List.of(Map.of("product_bom_route_id",200,"product_bom_id",12,"product_id",3,"process_id",30));
            if(sql.startsWith("select * from plm_process where product_id"))return List.of(Map.of("process_id",20,"product_id",2,"process_type","routing"));
            if(sql.startsWith("select * from plm_process where process_id")){var result=new ArrayList<Map<String,Object>>();for(Object id:args)result.add(((Number)id).longValue()==21?Map.of("process_id",21,"product_id",2,"parent_process_id",20,"operation_master_process_id",40):Map.of("process_id",30,"product_id",3,"process_type","routing"));return result;}
if(sql.startsWith("select * from plm_process where parent_process_id"))return List.of(Map.of("process_id",21,"product_id",2,"parent_process_id",20,"operation_master_process_id",40,"process_name","注塑"),Map.of("process_id",31,"product_id",3,"parent_process_id",30),Map.of("process_id",40,"process_type","operation_master","status","confirmed"));
            if(sql.startsWith("select * from plm_workflow_template_node"))return List.of(Map.of("workflow_node_id",6,"workflow_template_id",5,"node_name","工程确认"));
            if(sql.startsWith("select * from plm_workflow_template where"))return List.of(Map.of("workflow_template_id",5,"template_name","真实流程版本"));
            if(sql.startsWith("select product_id,workflow_template_id"))return List.of(Map.of("product_id",2,"workflow_template_id",5,"current_step_no",1));
            if(sql.startsWith("select * from plm_process_production_operation_selection"))return List.of(Map.of("product_id",2,"process_id",20,"operation_process_id",21));
            if(sql.startsWith("select * from plm_operation_log"))return List.of(Map.of("log_id",7,"business_type","PRODUCT","business_id","2","action","TIMELINE_CONFIRM","operator_user_id",9));
            if(sql.startsWith("select user_id,username"))return List.of(Map.of("user_id",9,"username","engineer","display_name","工程账号","department_name","研发","status","active","deleted_flag",0));
            return new ArrayList<>();
        }
    }
    private PilotTrialService trial(){var trials=mock(PilotTrialService.class);var data=new LinkedHashMap<String,Object>();data.put("platform_ids",List.of(1L));data.put("project_ids",List.of(2L));when(trials.raw(3)).thenReturn(data);when(trials.projectIds(any())).thenReturn(List.of(1L,2L));return trials;}
    private Map<String,byte[]> zip(byte[] bytes)throws Exception{var entries=new LinkedHashMap<String,byte[]>();try(var in=new ZipInputStream(new ByteArrayInputStream(bytes),StandardCharsets.UTF_8)){java.util.zip.ZipEntry entry;while((entry=in.getNextEntry())!=null)entries.put(entry.getName(),in.readAllBytes());}return entries;}
    @Test void packageIncludesOriginalBinaryAndChecksummedRelationshipDatasets()throws Exception {
byte[] binary=new byte[]{0,1,2,3,(byte)255,0,7};String checksum=HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(binary));var access=mock(PilotAccessService.class);when(access.actorId()).thenReturn(9L);when(access.visibleSqlClause("product","p.product_id")).thenReturn("true");var storage=mock(StorageClient.class);when(storage.exists("source/key")).thenReturn(true);when(storage.loadAsResource("source/key")).thenReturn(new ByteArrayResource(binary));var service=new Exporter(json,trial(),access,storage,mock(OperationLogService.class));service.lineage=true;service.attachments=List.of(Map.of("attachment_id",11L,"storage_key","source/key","original_file_name","drawing.step","checksum",checksum));var entries=zip(service.export(3,null));assertThat(entries.get("files/11/drawing.step")).isEqualTo(binary);var manifest=json.readTree(entries.get("manifest.json"));assertThat(manifest.path("format").asText()).isEqualTo("deeplink-plm-pilot-v1");for(var file:manifest.path("files")){byte[] raw=entries.get(file.path("path").asText());assertThat(raw).isNotNull();assertThat(HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(raw))).isEqualTo(file.path("sha256").asText());}assertThat(json.readTree(entries.get("data/products.json")).size()).isEqualTo(2);verify(access).requireFile(11L);verify(access).requireFinanceExport();verify(access).requireProduct(1L);verify(access).requireProduct(2L);assertThat(json.readTree(entries.get("data/referenced_boms.json")).get(0).path("product_bom_id").asLong()).isEqualTo(12L);assertThat(json.readTree(entries.get("data/referenced_products.json")).get(0).path("product_id").asLong()).isEqualTo(3L);assertThat(json.readTree(entries.get("data/referenced_processes.json")).findValues("process_id")).anySatisfy(p->assertThat(p.asLong()).isEqualTo(21L));assertThat(json.readTree(entries.get("data/workflow_nodes.json")).get(0).path("node_name").asText()).isEqualTo("工程确认");assertThat(json.readTree(entries.get("data/workflow_history.json")).size()).isPositive();var account=json.readTree(entries.get("data/accounts.json")).get(0);assertThat(account.path("display_name").asText()).isEqualTo("工程账号");assertThat(account.has("password_hash")).isFalse();assertThat(account.has("dingtalk_user_id")).isFalse();assertThat(new String(entries.get("README.txt"),StandardCharsets.UTF_8)).contains("不是 PostgreSQL 全库恢复备份");assertThat(manifest.path("scope").path("selectedProjectIds").size()).isEqualTo(2);assertThat(service.queries.size()).isLessThan(70);
    }
    @Test void missingOrChangedOriginalFileRejectsTheWholePackage() {
var storage=mock(StorageClient.class);var logs=mock(OperationLogService.class);var service=new Exporter(json,trial(),mock(PilotAccessService.class),storage,logs);service.attachments=List.of(Map.of("attachment_id",11L,"storage_key","key","original_file_name","drawing.pdf","checksum","wrong"));assertThatThrownBy(()->service.export(3,null)).hasMessageContaining("缺失");when(storage.exists("key")).thenReturn(true);when(storage.loadAsResource("key")).thenReturn(new ByteArrayResource(new byte[]{1,2}));assertThatThrownBy(()->service.export(3,null)).hasMessageContaining("校验不符");verifyNoInteractions(logs);service.attachments=List.of(Map.of("attachment_id",11L,"family_id",999L,"storage_key","key","original_file_name","drawing.pdf"));assertThatThrownBy(()->service.export(3,null)).hasMessageContaining("族根").hasMessageContaining("已删除");service.attachments=List.of(Map.of("attachment_id",11L,"derived_pdf_attachment_id",999L,"storage_key","key","original_file_name","drawing.pdf"));assertThatThrownBy(()->service.export(3,null)).hasMessageContaining("PDF").hasMessageContaining("授权范围");verifyNoInteractions(logs);
    }
    @Test void permissionIsCheckedBeforeReadingOrLoadingBinaryFiles() {
        var access=mock(PilotAccessService.class);doThrow(new BusinessException(40103,"无导出权限")).when(access).requireFinanceExport();var storage=mock(StorageClient.class);var trials=trial();var service=new Exporter(json,trials,access,storage,mock(OperationLogService.class));assertThatThrownBy(()->service.export(3,null)).hasMessageContaining("权限");verifyNoInteractions(storage);verify(trials,never()).raw(anyLong());doNothing().when(access).requireFinanceExport();when(access.visibleSqlClause("product","p.product_id")).thenReturn("false");service.lineage=true;assertThatThrownBy(()->service.export(3,null)).hasMessageContaining("未授权");verifyNoInteractions(storage);
    }
    @Test void zipNamesCannotEscapeThePackageRoot(){assertThat(PilotExportService.safeName("../../private/file\n.step")).doesNotContain("..").doesNotContain("/").doesNotContain("\n");}
}
