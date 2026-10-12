package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.*;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.DefaultTransactionDefinition;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static com.yuewei.plm.module.collaboration.CollaborationTypes.*;

/** Opt-in against the local snapshot only. Every business/account fixture is rolled back. */
@EnabledIfEnvironmentVariable(named="PLM_COLLAB_TEST_DB_URL",matches="jdbc:postgresql://127\\.0\\.0\\.1:15432/plm_data_management\\?currentSchema=plm")
class CollaborationLocalIntegrationTest {
    JdbcTemplate jdbc;DataSourceTransactionManager tx;TransactionStatus scope;
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules().disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    CollaborationRepository repository;CollaborationService service;CollaborationImportService imports;CurrentUser admin;

    @BeforeEach void beginLocalRollbackScope() {
        var source=new DriverManagerDataSource(System.getenv("PLM_COLLAB_TEST_DB_URL"),"postgres",System.getenv("PLM_COLLAB_TEST_DB_PASSWORD"));
        jdbc=new JdbcTemplate(source);tx=new DataSourceTransactionManager(source);scope=tx.getTransaction(new DefaultTransactionDefinition());
        repository=new CollaborationRepository(jdbc,json);service=new CollaborationService(jdbc,json,repository,tx,mock(OperationLogService.class));
        imports=new CollaborationImportService(jdbc,json,service,repository,tx);
        var user=jdbc.queryForList("select user_id,username,display_name from sys_user where deleted_flag=0 and status='active' and all_permissions=true order by user_id limit 1").get(0);
        admin=new CurrentUser(((Number)user.get("user_id")).longValue(),user.get("username").toString(),user.get("display_name").toString(),true);CurrentUserContext.set(admin);
    }
    @AfterEach void rollbackAllFixtures() {if(scope!=null&&!scope.isCompleted()) tx.rollback(scope);CurrentUserContext.clear();}
    long item() {return ((Number)service.createItem(new CreateItem(null,"IT款式-"+UUID.randomUUID(),"HONOR","Honor Test",null,"原备注 OK 5400"),null).get("itemId")).longValue();}
    RowPatch patch(String entity,long id,String field,Object before,Object after,String reason) {return new RowPatch(entity,id,List.of(new CellChange(field,json.valueToTree(before),json.valueToTree(after),reason)));}
    RowResult save(RowPatch... rows) {return service.save(new BatchSave(List.of(rows)),null).get(0);}
    long mold(long item) {return ((Number)service.createMoldSet(item,new CreateMoldSet(null,null,null),null).get("moldSetId")).longValue();}
    RowPatch moldPatch(long id,Map<String,Object> values) {
        var before=service.mold(id);return new RowPatch("mold_set",id,values.entrySet().stream().map(e->new CellChange(e.getKey(),json.valueToTree(before.get(e.getKey())),json.valueToTree(e.getValue()),null)).toList());
    }
    long ordinary(String group) {
        Long id=jdbc.queryForObject("select max(user_id)+100 from sys_user",Long.class);
        jdbc.update("insert into sys_user(user_id,user_code,user_name,login_name,username,display_name,status,all_permissions) values(?,?,?,?,?,?,'active',false)",id,"it-"+id,"台账权限测试","it-"+id,"mold-it-"+id,"台账权限测试");
        jdbc.update("insert into plm_collaboration_assignment(field_group,user_id) values(?,?)",group,id);
        CurrentUserContext.set(new CurrentUser(id,"forged-admin","forged",true));return id;
    }
    @Test void moldCopyReusesOriginalCodesButNotDatesLocationAcceptanceOrProduction() {
        Query q=new Query();var existing=service.page(q).getContent().stream().filter(r->r.get("productLineId")!=null).findFirst().orElseThrow();
        long itemId=((Number)existing.get("itemId")).longValue(),original=mold(itemId);
        String oldCode="0000-MOLD-"+UUID.randomUUID().toString().substring(0,8);
        Long codeId=jdbc.queryForObject("insert into plm_product_mold_code(product_id,mold_code,mold_name) values(?,?,'历史模具') returning product_mold_code_id",Long.class,existing.get("productLineId"),oldCode);
        assertThat(save(moldPatch(original,Map.of("pcMoldCodeId",codeId,"tpuMoldCodeId",codeId,"openedDate","2026-08-01","manufacturerName","工程制模厂","ownerUserId",admin.userId(),"pcCurrentLocation","mexico_factory","pcFactoryArrivalDate","2026-08-15","pcAcceptanceDate","2026-08-16","pcAcceptanceStatus","passed"))).status()).isEqualTo("saved");
        var copy=service.copyMold(original,new CreateMoldSet("重新开模",null,null),null);
        assertThat(copy).containsEntry("sourceMoldSetId",original).containsEntry("setNo",2).containsEntry("pcMoldCode",oldCode).containsEntry("tpuMoldCode",oldCode)
            .containsEntry("openedDate",null).containsEntry("pcCurrentLocation",null).containsEntry("pcFactoryArrivalDate",null).containsEntry("pcAcceptanceDate",null).containsEntry("pcAcceptanceStatus","pending").containsEntry("manufacturerName",null).containsEntry("ownerUserId",null);
        assertThat(copy.get("assetNumber")).isNotEqualTo(service.mold(original).get("assetNumber"));
        assertThat(copy.get("pcAssetNumber")).isEqualTo(copy.get("assetNumber")+"-PC");
        assertThat(jdbc.queryForObject("select count(*) from plm_product_mold_code where mold_code=?",Long.class,oldCode)).isEqualTo(1L);
        assertThat(service.item(itemId).get("finishedTotal")).isEqualTo(existing.get("finishedTotal"));
    }
    @Test void moldPhysicalIdentityAndSourceCannotBeEditedAndCrossArchiveCopyIsRejected() {
        long firstItem=item(),first=mold(firstItem),secondItem=item();
        for(String immutable:List.of("assetNumber","pcAssetNumber","setNo","sourceMoldSetId","itemId")) assertThat(save(patch("mold_set",first,immutable,null,"hacked",null)).status()).isEqualTo("invalid");
        assertThatThrownBy(()->service.createMoldSet(secondItem,new CreateMoldSet(null,null,null,first),null)).isInstanceOf(BusinessException.class).hasMessageContaining("同一");
        assertThat(service.mold(first).get("setNo")).isEqualTo(1);
    }
    @Test void moldReceiptAndAcceptanceRemainIndependentFromCountryArrivalAndLocations() {
        long id=item(),set=mold(id);
        assertThat(save(moldPatch(set,Map.of("actualMexicoArrivalDate","2026-08-01","pcCurrentLocation","mexico_transit","tpuCurrentLocation","in_transit"))).status()).isEqualTo("saved");
        assertThat(service.mold(set)).containsEntry("status","mexico_arrived").containsEntry("pcFactoryArrivalDate",null).containsEntry("tpuFactoryArrivalDate",null);
        assertThat(save(moldPatch(set,Map.of("pcCurrentLocation","mexico_factory"))).row()).containsEntry("status","partially_arrived").containsEntry("pcFactoryArrivalDate",null);
        assertThat(save(moldPatch(set,Map.of("pcFactoryArrivalDate","2026-08-03","pcCurrentLocation","mexico_factory"))).row()).containsEntry("status","partially_arrived");
        assertThat(save(moldPatch(set,Map.of("tpuFactoryArrivalDate","2026-08-04","tpuCurrentLocation","mexico_factory"))).row()).containsEntry("status","awaiting_acceptance");
        assertThat(save(moldPatch(set,Map.of("pcAcceptanceStatus","passed","pcAcceptanceDate","2026-08-04"))).row()).containsEntry("status","partially_accepted");
        assertThat(save(moldPatch(set,Map.of("tpuAcceptanceStatus","failed","tpuAcceptanceIssues","尺寸不合格"))).row()).containsEntry("status","acceptance_failed");
        assertThat(save(moldPatch(set,Map.of("tpuAcceptanceStatus","passed","tpuAcceptanceDate","2026-08-05","tpuAcceptanceIssues","返修后确认通过"))).row()).containsEntry("status","delivered");
        Query q=new Query();q.setItemId(id);q.setView("delivery");assertThat(service.page(q).getContent()).extracting(r->r.get("status")).containsExactly("delivered");
        assertThat(service.moldHistory(set,1,100).getContent()).anySatisfy(h->assertThat(h).containsEntry("fieldName","tpuAcceptanceIssues").containsEntry("actorName",admin.username()));
    }
    @Test void moldAcceptanceValidatesFinalRowAtomicallyRegardlessOfFieldOrder() {
        long set=mold(item());
        assertThat(save(patch("mold_set",set,"pcAcceptanceStatus","pending","passed",null)).message()).contains("到厂日期");
        assertThat(save(patch("mold_set",set,"pcAcceptanceStatus","pending","failed",null)).message()).contains("问题说明");
        LinkedHashMap<String,Object> values=new LinkedHashMap<>();values.put("pcAcceptanceStatus","passed");values.put("pcAcceptanceDate","2026-08-02");values.put("pcFactoryArrivalDate","2026-08-03");
        assertThat(save(moldPatch(set,values)).message()).contains("不能早于");
        values.put("pcAcceptanceDate","2026-08-03");assertThat(save(moldPatch(set,values)).status()).isEqualTo("saved");
        assertThat(service.mold(set).get("status")).isEqualTo("partially_accepted");
    }
    @Test void moldDifferentPartFieldsMergeWhileSameFieldConflictDoesNotSaveTheRow() {
        long first=mold(item()),second=mold(item());
        assertThat(save(patch("mold_set",first,"pcCurrentLocation",null,"china_maker",null)).status()).isEqualTo("saved");
        assertThat(save(patch("mold_set",first,"tpuCurrentLocation",null,"china_dispatch",null)).status()).isEqualTo("saved");
        var conflicting=new RowPatch("mold_set",first,List.of(new CellChange("pcCurrentLocation",json.nullNode(),json.valueToTree("in_transit"),null),new CellChange("manufacturerName",json.nullNode(),json.valueToTree("不能部分保存"),null)));
        var results=service.save(new BatchSave(List.of(conflicting,patch("mold_set",second,"manufacturerName",null,"正常保存",null))),null);
        assertThat(results).extracting(RowResult::status).containsExactly("conflict","saved");
        assertThat(service.mold(first)).containsEntry("manufacturerName",null).containsEntry("pcCurrentLocation","china_maker").containsEntry("tpuCurrentLocation","china_dispatch");
    }
    @Test void moldOrdinaryAccountFieldGroupsAreEnforcedAndServerActorIsAudited() {
        long set=mold(item());long logistics=ordinary("logistics");
        assertThat(save(patch("mold_set",set,"pcCurrentLocation",null,"in_transit",null)).status()).isEqualTo("saved");
        assertThat(save(patch("mold_set",set,"actualMexicoArrivalDate",null,"2026-08-04",null)).status()).isEqualTo("saved");
        assertThat(save(patch("mold_set",set,"pcFactoryArrivalDate",null,"2026-08-05",null)).status()).isEqualTo("forbidden");
        assertThat(save(patch("mold_set",set,"manufacturerName",null,"越权",null)).status()).isEqualTo("forbidden");
        assertThat(service.moldHistory(set,1,100).getContent()).anySatisfy(h->assertThat(h).containsEntry("fieldName","pcCurrentLocation").containsEntry("actorName","mold-it-"+logistics));
        CurrentUserContext.set(admin);ordinary("mexico");
        assertThat(save(patch("mold_set",set,"pcFactoryArrivalDate",null,"2026-08-05",null)).status()).isEqualTo("saved");
        assertThat(save(patch("mold_set",set,"pcCurrentLocation","in_transit","mexico_factory",null)).status()).isEqualTo("forbidden");
        assertThat(service.moldOptions()).containsEntry("administrator",false);
    }
    @Test void moldHttpEndpointsRejectUnauthorizedCreationAndMixedEntityOrOversizedRequests() throws Exception {
        long set=mold(item());ordinary("logistics");
        var mvc=org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(new MoldController(service)).setControllerAdvice(new com.yuewei.plm.common.exception.GlobalExceptionHandler()).build();
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post("/api/v1/molds").contentType("application/json").content("{\"itemId\":"+service.mold(set).get("itemId")+",\"actorId\":1,\"allPermissions\":true}")).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isForbidden());
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/api/v1/molds").param("size","101")).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isBadRequest());
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post("/api/v1/molds/batch-save").contentType("application/json").content(json.writeValueAsString(new BatchSave(List.of(patch("item",((Number)service.mold(set).get("itemId")).longValue(),"brand",null,"fake",null)))))).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isBadRequest());
        CurrentUserContext.clear();mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/api/v1/molds")).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isUnauthorized());
    }
    @Test void moldInventoryLinksRequireExplicitOriginalCodeAndReasonAndNeverUseQuantity() {
        long itemId=item(),set=mold(itemId);var source=jdbc.queryForList("select inventory_id,inventory_code from plm_inventory where deleted_flag=0 and inventory_type='tooling' limit 1").get(0);
        long inventory=((Number)source.get("inventory_id")).longValue();String code=source.get("inventory_code").toString();
        assertThat(save(patch("mold_set",set,"pcInventoryId",null,inventory,"确认资料")).status()).isEqualTo("invalid");
        save(patch("mold_set",set,"pcOriginalMoldCode",null,code,null));
        assertThat(save(patch("mold_set",set,"pcInventoryId",null,inventory,null)).message()).contains("人工核对");
        assertThat(save(patch("mold_set",set,"pcInventoryId",null,inventory,"人工确认此资料引用；不使用库存数量")).status()).isEqualTo("saved");
        assertThat(service.mold(set)).containsEntry("pcOriginalMoldCode",code).containsEntry("pcInventoryId",inventory);
        assertThat(service.item(itemId)).containsEntry("moldSetCount",1L).containsEntry("finishedTotal",null);
        assertThat(service.moldHistory(set,1,100).getContent()).anySatisfy(h->assertThat(h).containsEntry("fieldName","pcInventoryId").containsEntry("reason","人工确认此资料引用；不使用库存数量"));
    }
    @Test void moldPageFiltersPhysicalNumberProductLineLocationAndStatusWithServerPaging() {
        long id=item(),first=mold(id),second=mold(id),unknown=mold(id),sameDay=mold(id);
        assertThat(save(moldPatch(first,Map.of("pcCurrentLocation","china_maker","openedDate","2026-07-01"))).status()).isEqualTo("saved");
        assertThat(save(moldPatch(second,Map.of("openedDate","2026-10-01"))).status()).isEqualTo("saved");
        assertThat(save(moldPatch(sameDay,Map.of("openedDate","2026-10-01"))).status()).isEqualTo("saved");
        // An old mold edited most recently must not outrank newer opening dates.
        jdbc.update("update plm_collaboration_mold_set set updated_at=case when mold_set_id=? then timestamp '2026-10-12 23:59:59' else timestamp '2026-10-01 00:00:00' end where item_id=?",first,id);
        Query q=new Query();q.setItemId(id);q.setLocation("china_maker");assertThat(service.moldPage(q).getContent()).extracting(r->r.get("moldSetId")).containsExactly(first);
        q.setLocation("unknown");assertThat(service.moldPage(q).getTotalElements()).isEqualTo(4);q.setLocation(null);q.setKeyword(service.mold(second).get("assetNumber").toString());
        assertThat(service.moldPage(q).getContent()).extracting(r->r.get("moldSetId")).containsExactly(second);
        q.setKeyword(null);q.setSize(2);q.setPage(1);
        var newest=service.moldPage(q);assertThat(newest.getContent()).extracting(r->r.get("moldSetId")).containsExactly(sameDay,second);
        assertThat(newest.getTotalElements()).isEqualTo(4);assertThat(newest.getTotalPages()).isEqualTo(2);
        q.setPage(2);assertThat(service.moldPage(q).getContent()).extracting(r->r.get("moldSetId")).containsExactly(first,unknown);
        q.setStatus("delivered");assertThat(service.moldPage(q).getTotalElements()).isZero();
    }
    @Test void moldDeliveryTemplateExportsStablePartIdsOriginalStringsAndTypedDates() throws Exception {
        long id=item(),set=mold(id);save(moldPatch(set,Map.of("pcOriginalMoldCode","000001-PC","tpuOriginalMoldCode","000001-TPU","openedDate","2026-08-01","pcFactoryArrivalDate","2026-08-15")));
        Query q=new Query();q.setItemId(id);byte[] bytes=imports.template("delivery",q,false);
        try(var wb=WorkbookFactory.create(new java.io.ByteArrayInputStream(bytes))) {
            var sheet=wb.getSheetAt(0);Map<String,Integer> headers=new HashMap<>();for(Cell c:sheet.getRow(0)) headers.put(CollaborationImportService.header(c.getStringCellValue()),c.getColumnIndex());
            assertThat(headers).containsKeys("moldSetId","assetNumber","pcAssetNumber","tpuAssetNumber","pcOriginalMoldCode","pcFactoryArrivalDate","tpuAcceptanceStatus");
            assertThat(sheet.getRow(1).getCell(headers.get("pcOriginalMoldCode")).getStringCellValue()).isEqualTo("000001-PC");
            assertThat(DateUtil.isCellDateFormatted(sheet.getRow(1).getCell(headers.get("openedDate")))).isTrue();
        }
        var preview=imports.preview("delivery",new MockMultipartFile("file","mold-template.xlsx",null,bytes));var r=rows(preview).get(0);
        assertThat(r.issues()).isEmpty();assertThat(r.values().get("pcFactoryArrivalDate").asText()).isEqualTo("2026-08-15");
        var decision=decision(r,id,"核对导出模板");assertThat(imports.commit(preview.get("importToken").toString(),new ImportCommit(List.of(decision)),null)).containsEntry("saved",1);
        assertThat(imports.commit(preview.get("importToken").toString(),new ImportCommit(List.of(decision)),null)).containsEntry("saved",0);
        assertThat(service.item(id).get("moldSetCount")).isEqualTo(1L);
    }
    @Test void moldImportCanCopyAnExplicitSourceAndWarnsOnWrongImmutablePartNumbers() throws Exception {
        long id=item(),set=mold(id);save(patch("mold_set",set,"pcOriginalMoldCode",null,"000001-PC",null));var item=service.item(id);
        var file=workbook("模具交付",new String[]{"协作档案ID","产品款式","兼容手机型号","模具套ID","实物编号","新增模具套","PC 实际到厂日期"},new Object[]{id,item.get("styleName"),item.get("compatibleModels"),set,"MS-wrong","是",null});
        var preview=imports.preview("delivery",file);var r=rows(preview).get(0);assertThat(r.issues()).anyMatch(s->s.contains("实物编号"));
        assertThat(imports.commit(preview.get("importToken").toString(),new ImportCommit(List.of(decision(r,id,"重新确认来源套 ID；错误手写编号不采用"))),null)).containsEntry("saved",1);
        Query q=new Query();q.setItemId(id);assertThat(service.moldPage(q).getContent()).anySatisfy(copy->assertThat(copy).containsEntry("sourceMoldSetId",set).containsEntry("pcMoldCode","000001-PC").containsEntry("pcFactoryArrivalDate",null));
    }
    @SuppressWarnings("unchecked") List<CollaborationImportService.PreviewRow> rows(Map<String,Object> preview) {return (List<CollaborationImportService.PreviewRow>)preview.get("rows");}
    ImportDecision decision(CollaborationImportService.PreviewRow row,Long target,String reason) {
        return new ImportDecision(row.rowNo(),row.sheetName(),false,target,row.moldSetId(),row.productLineId(),row.styleName(),row.brand(),row.compatibleModels(),row.newMoldSet(),row.values(),row.before(),reason);
    }
    MockMultipartFile workbook(String sheetName,String[] headers,Object[]...data) throws Exception {
        try(var wb=new XSSFWorkbook();var out=new ByteArrayOutputStream()) {
            Sheet sheet=wb.createSheet(sheetName);Row header=sheet.createRow(0);
            for(int c=0;c<headers.length;c++) header.createCell(c).setCellValue(headers[c]);
            for(int r=0;r<data.length;r++) {Row row=sheet.createRow(r+1);for(int c=0;c<data[r].length;c++) {Object v=data[r][c];if(v==null) continue;Cell cell=row.createCell(c);if(v instanceof Number n) cell.setCellValue(n.doubleValue());else cell.setCellValue(v.toString());}}
            wb.write(out);return new MockMultipartFile("file","test.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",out.toByteArray());
        }
    }

    @Test void multipleColorProjectsAndCopiedSetsDoNotDuplicateProduction() {
        Query historic=new Query();historic.setSize(100);
        assertThat(service.page(historic).getContent()).anySatisfy(row->assertThat(((Number)row.get("projectCount")).longValue()).isGreaterThan(1));
        long id=item();long first=mold(id),second=mold(id);
        assertThat(first).isNotEqualTo(second);assertThat(repository.row("mold_set",second).get("setNo")).isEqualTo(2);
        assertThat(jdbc.queryForObject("select count(*) from plm_collaboration_mold_part where mold_set_id in (?,?)",Long.class,first,second)).isEqualTo(4L);
        assertThat(save(patch("item",id,"pcTotal",null,0,null)).status()).isEqualTo("saved");
        assertThat(save(patch("item",id,"tpuTotal",null,12,null)).status()).isEqualTo("saved");
        assertThat(repository.row("item",id)).containsEntry("pcTotal",0L).containsEntry("tpuTotal",12L).containsEntry("finishedTotal",null);
        Query q=new Query();q.setView("production");q.setItemId(id);assertThat(service.page(q).getContent()).hasSize(1);
        q.setView("delivery");assertThat(service.page(q).getContent()).hasSize(2);
    }
    @Test void differentFieldsMergeButSameFieldConflictsAndOtherRowsStillSave() {
        long first=item(),second=item();
        assertThat(save(patch("item",first,"brand","HONOR","HUAWEI",null)).status()).isEqualTo("saved");
        assertThat(save(patch("item",first,"salesPlatform",null,"Telcel",null)).status()).isEqualTo("saved");
        RowPatch conflicting=new RowPatch("item",first,List.of(new CellChange("brand",json.valueToTree("HONOR"),json.valueToTree("Samsung"),null),new CellChange("referenceUrl",json.nullNode(),json.valueToTree("https://example.com"),null)));
        List<RowResult> results=service.save(new BatchSave(List.of(conflicting,patch("item",second,"pcTotal",null,100,null))),null);
        assertThat(results).extracting(RowResult::status).containsExactly("conflict","saved");
        assertThat(results.get(0).conflicts().get(0)).containsEntry("current","HUAWEI").containsEntry("attempted","Samsung");
        assertThat(repository.row("item",first)).containsEntry("referenceUrl",null).containsEntry("salesPlatform","Telcel");
        assertThat(repository.row("item",second).get("pcTotal")).isEqualTo(100L);
    }
    @Test void ordinaryPermissionsComeFromDatabaseNotForgedClientAdministrator() {
        long id=item();Long userId=jdbc.queryForObject("select max(user_id)+100 from sys_user",Long.class);
        jdbc.update("insert into sys_user(user_id,user_code,user_name,login_name,username,display_name,status,all_permissions) values(?,?,?,?,?,?,'active',false)",userId,"it-"+userId,"权限测试","it-"+userId,"it-user-"+userId,"权限测试");
        jdbc.update("insert into plm_collaboration_assignment(field_group,user_id) values('engineering',?)",userId);
        CurrentUserContext.set(new CurrentUser(userId,"forged","forged",true));
        assertThat(service.options().get("writableGroups")).isEqualTo(Set.of("engineering"));
        assertThat(service.options().get("administrator")).isEqualTo(false);
        assertThat(save(patch("item",id,"pcTotal",null,99,null)).status()).isEqualTo("forbidden");
        assertThatThrownBy(()->service.assignments()).isInstanceOf(BusinessException.class);
        long mold=mold(id);assertThat(save(patch("mold_set",mold,"openedDate",null,"2026-08-01",null)).status()).isEqualTo("saved");
        assertThat(service.history(id,1,20).getContent()).anySatisfy(row->{assertThat(row.get("fieldName")).isEqualTo("openedDate");assertThat(row.get("actorName")).isEqualTo("it-user-"+userId);assertThat(row.get("actorId")).isEqualTo(userId);});
    }
    @Test void decreasingOrClearingSavedCumulativeCountsNeedsAuditedReason() {
        long id=item();save(patch("item",id,"pcTotal",null,100,null));
        assertThat(save(patch("item",id,"pcTotal",100,90,null)).status()).isEqualTo("invalid");
        assertThat(save(patch("item",id,"pcTotal",100,null,"更正原记录，待重新核对")).status()).isEqualTo("saved");
        assertThat(repository.row("item",id).get("pcTotal")).isNull();
        assertThat(service.history(id,1,20).getContent()).anySatisfy(row->{assertThat(row.get("fieldName")).isEqualTo("pcTotal");assertThat(row.get("before")).isEqualTo(100);assertThat(row.get("after")).isNull();assertThat(row.get("reason")).isEqualTo("更正原记录，待重新核对");});
    }
    @Test void aConflictTakesPrecedenceOverAQuantityReductionError() {
        long id=item();save(patch("item",id,"pcTotal",null,100,null));
        assertThat(save(patch("item",id,"pcTotal",90,95,null)).status()).isEqualTo("conflict");
    }
    @Test void arrivalSuggestionNeedsExplicitConfirmationAndPlanChangesDoNotOverwriteIt() {
        long id=item(),set=mold(id);
        save(patch("mold_set",set,"plannedMoldDeliveryDate",null,"2026-08-01",null));
        assertThat(repository.row("mold_set",set)).containsEntry("suggestedFactoryArrivalDate","2026-08-08").containsEntry("plannedFactoryArrivalDate",null);
        save(patch("mold_set",set,"plannedFactoryArrivalDate",null,"2026-08-15",null));
        assertThat(repository.row("mold_set",set)).containsEntry("arrivalConfirmedBasisDate","2026-08-01").containsEntry("arrivalNeedsReview",false);
        save(patch("mold_set",set,"plannedMoldDeliveryDate","2026-08-01","2026-08-03",null));
        assertThat(repository.row("mold_set",set)).containsEntry("plannedFactoryArrivalDate","2026-08-15").containsEntry("arrivalNeedsReview",true);
        save(patch("mold_set",set,"plannedFactoryArrivalDate","2026-08-15","2026-08-15",null));
        assertThat(repository.row("mold_set",set)).containsEntry("arrivalConfirmedBasisDate","2026-08-03").containsEntry("arrivalNeedsReview",false);
        save(patch("mold_set",set,"actualMexicoArrivalDate",null,"2026-08-10",null));
        assertThat(repository.row("mold_set",set).get("status")).isEqualTo("mexico_arrived");
    }
    @Test void anomalousDatesAreRejectedUntilHumanReviewIsRecorded() {
        long id=item(),set=mold(id);save(patch("mold_set",set,"openedDate",null,"2026-08-21",null));
        assertThat(save(patch("mold_set",set,"actualShipDate",null,"2026-08-01",null)).status()).isEqualTo("invalid");
        assertThat(save(patch("mold_set",set,"actualShipDate",null,"2026-08-01","历史表日期已核对，保留异常并继续追查")).status()).isEqualTo("saved");
    }
    @Test void repeatedExactFileImportIsIdempotentAndKeepsUnknownDifferentFromZero() throws Exception {
        long id=item();Map<String,Object> item=repository.row("item",id);
        var file=workbook("累计产量",new String[]{"协作档案ID","产品款式","兼容手机型号","PC 半成品累计","TPU 半成品累计","成品累计","产量备注"},new Object[]{id,item.get("styleName"),item.get("compatibleModels"),0,12,null,"OK 5400"});
        Map<String,Object> preview=imports.preview("production",file);var row=rows(preview).get(0);
        assertThat(row.issues()).isEmpty();assertThat(row.values().get("finishedTotal").isNull()).isTrue();
        var dto=new ImportCommit(List.of(decision(row,id,"已核对累计产量")));
        assertThat(imports.commit(preview.get("importToken").toString(),dto,null)).containsEntry("saved",1);
        assertThat(imports.commit(preview.get("importToken").toString(),dto,null)).containsEntry("saved",0).containsEntry("skipped",1);
        assertThat(rows(imports.preview("production",file)).get(0).alreadyImported()).isTrue();
        assertThat(repository.row("item",id)).containsEntry("finishedTotal",null).containsEntry("pcTotal",0L).containsEntry("productionNotes","OK 5400");
    }
    @Test void deliveryCopiesPreserveOldSetAndOnlyCommitAfterMappingConfirmation() throws Exception {
        long id=item();long original=mold(id);
        var file=workbook("模具交付",new String[]{"协作档案ID","款式","型号","新增模具套","开模日期","备注"},new Object[]{id,"IT复制款式","Honor Test（重新开模，复制模具）","是","2026-08-21","OK 5400"});
        Map<String,Object> preview=imports.preview("delivery",file);var row=rows(preview).get(0);
        assertThat(row.issues()).anyMatch(s->s.contains("复制或重新开模"));
        assertThatThrownBy(()->imports.commit(preview.get("importToken").toString(),new ImportCommit(List.of(decision(row,id,""))),null)).isInstanceOf(BusinessException.class);
        assertThat(imports.commit(preview.get("importToken").toString(),new ImportCommit(List.of(decision(row,id,"确认复制模具，日期与原备注逐项核对"))),null)).containsEntry("saved",1);
        assertThat(repository.row("mold_set",original)).containsEntry("openedDate",null);
        assertThat(jdbc.queryForObject("select count(*) from plm_collaboration_mold_set where item_id=?",Long.class,id)).isEqualTo(2L);
        assertThat(repository.row("item",id).get("finishedTotal")).isNull();
    }
    @Test void missingCurrencyAndContradictoryBrandAreExplicitPreviewWarnings() throws Exception {
        var file=workbook("市场",new String[]{"产品款式","品牌","兼容手机型号","手机价格","备注"},new Object[]{"新候选","Xiaomi","OPPO A5",1999,"OK 5400"});
        var row=rows(imports.preview("market",file)).get(0);
        assertThat(row.values().get("priceCurrency").asText()).isEqualTo("UNKNOWN");
        assertThat(row.issues()).anyMatch(s->s.contains("品牌与型号")).anyMatch(s->s.contains("币种待确认"));
        assertThat(row.values()).doesNotContainKeys("pcTotal","tpuTotal","finishedTotal");
    }
    @Test void exportedCurrentPageCarriesStableIdsAndRoundTripsThroughPreview() throws Exception {
        long id=item(),set=mold(id);Query q=new Query();q.setItemId(id);
        byte[] template=imports.template("delivery",q,false);
        try(Workbook wb=WorkbookFactory.create(new java.io.ByteArrayInputStream(template))) {
            assertThat(wb.getSheetAt(0).getLastRowNum()).isEqualTo(1);
            assertThat(wb.getSheetAt(0).getRow(1).getCell(0).getStringCellValue()).isEqualTo(Long.toString(id));
            assertThat(wb.getSheetAt(0).getRow(1).getCell(4).getStringCellValue()).isEqualTo(Long.toString(set));
        }
        var preview=imports.preview("delivery",new MockMultipartFile("file","export.xlsx",null,template));
        assertThat(rows(preview).get(0).issues()).isEmpty();assertThat(rows(preview).get(0).moldSetId()).isEqualTo(set);
    }
    @Test void importOriginalValuesRejectLaterChangesWithoutOverwritingOtherFields() throws Exception {
        long id=item();var item=repository.row("item",id);
        var file=workbook("市场",new String[]{"协作档案ID","产品款式","兼容手机型号","品牌"},new Object[]{id,item.get("styleName"),item.get("compatibleModels"),"HONOR"});
        var preview=imports.preview("market",file);var row=rows(preview).get(0);
        save(patch("item",id,"brand","HONOR","HUAWEI",null));
        assertThatThrownBy(()->imports.commit(preview.get("importToken").toString(),new ImportCommit(List.of(decision(row,id,"已核对"))),null)).isInstanceOf(BusinessException.class).hasMessageContaining("已被他人修改");
        assertThat(repository.row("item",id).get("brand")).isEqualTo("HUAWEI");
    }
    @Test void brandInitialisationFillsOnlyExplicitEmptyBrandsAndAuditsTheRealAccount() {
        String style="IT-brand-"+UUID.randomUUID();
        var apple=service.createItem(new CreateItem(null,style,null,"Apple iPhone 18 Pro Max",null,null),null);
        assertThat(apple.get("brand")).isEqualTo("Apple");
        var samsung=service.createItem(new CreateItem(null,style,"Samsung","Samsung Galaxy A37 5G",null,null),null);
        long appleId=((Number)apple.get("itemId")).longValue(),samsungId=((Number)samsung.get("itemId")).longValue();
        jdbc.update("update plm_collaboration_item set brand=null where item_id=?",appleId);
        jdbc.update("update plm_collaboration_item set brand='待人工核对' where item_id=?",samsungId);
        assertThat(((Number)service.initialiseExplicitBrands(null).get("updated")).longValue()).isGreaterThanOrEqualTo(1);
        assertThat(repository.row("item",appleId).get("brand")).isEqualTo("Apple");
        assertThat(repository.row("item",samsungId).get("brand")).isEqualTo("待人工核对");
        assertThat(service.history(appleId,1,20).getContent()).anySatisfy(h->{assertThat(h.get("fieldName")).isEqualTo("brand");assertThat(h.get("actorName")).isEqualTo(admin.username());assertThat(h.get("reason").toString()).contains("明确品牌");});
    }
    @Test void projectAssociationReplacementRequiresOriginalIdsWhileAppendPreservesExistingColors() {
        Query q=new Query();var existing=service.page(q).getContent().stream().filter(r->((Number)r.get("projectCount")).longValue()>1).findFirst().orElseThrow();
        long id=((Number)existing.get("itemId")).longValue();
        @SuppressWarnings("unchecked") var projects=(List<Map<String,Object>>)existing.get("projects");
        List<Long> ids=projects.stream().map(p->((Number)p.get("projectId")).longValue()).toList();
        assertThatThrownBy(()->service.linkProjects(id,new LinkProjects(List.of(ids.get(0)),true,List.of(),false),null)).isInstanceOf(BusinessException.class).hasMessageContaining("已被其他人修改");
        assertThat(service.linkProjects(id,new LinkProjects(List.of(ids.get(0)),true,null,true),null).get("projectCount")).isEqualTo((long)ids.size());
        assertThat(service.linkProjects(id,new LinkProjects(List.of(ids.get(0)),true,ids,false),null).get("projectCount")).isEqualTo(1L);
    }
    @Test void globalAssignmentsOnlyUseActiveRealAccountsAndRejectStaleConfiguration() {
        var settings=service.assignments();
        @SuppressWarnings("unchecked") var before=(Map<String,List<Long>>)settings.get("groups");
        Map<String,List<Long>> after=new LinkedHashMap<>(before);after.put("production",List.of(admin.userId()));
        assertThat(service.accounts()).allSatisfy(account->assertThat(account).doesNotContainKeys("passwordHash","password_hash","token"));
        assertThat(service.saveAssignments(new Assignments(after,before),null).get("groups")).isEqualTo(after);
        assertThatThrownBy(()->service.saveAssignments(new Assignments(before,before),null)).isInstanceOf(BusinessException.class).hasMessageContaining("已被其他管理员修改");
    }
    @Test @EnabledIfEnvironmentVariable(named="PLM_COLLAB_SOURCE_XLSX",matches=".+")
    void actualCustomerWorkbookIsReadOnlyAndAllOriginalRowsRemainTraceable() throws Exception {
        long before=jdbc.queryForObject("select count(*) from plm_collaboration_mold_set",Long.class);
        byte[] bytes=Files.readAllBytes(Path.of(System.getenv("PLM_COLLAB_SOURCE_XLSX")));
        var preview=imports.preview("delivery",new MockMultipartFile("file","customer-delivery.xlsx",null,bytes));
        assertThat(preview.get("total")).isEqualTo(42);
        var rows=rows(preview);assertThat(rows).extracting(CollaborationImportService.PreviewRow::rowNo).contains(3,44);
        assertThat(rows).anySatisfy(row->assertThat(row.issues()).anyMatch(s->s.contains("品牌与型号")));
        assertThat(rows).anySatisfy(row->assertThat(row.issues()).anyMatch(s->s.contains("早于")));
        assertThat(rows).anySatisfy(row->assertThat(row.issues()).anyMatch(s->s.contains("公式建议")));
        assertThat(rows).allSatisfy(row->assertThat(row.values()).doesNotContainKeys("pcTotal","tpuTotal","finishedTotal"));
        assertThat(jdbc.queryForObject("select count(*) from plm_collaboration_mold_set",Long.class)).isEqualTo(before);
    }
    MoldScheduleService schedules() {return new MoldScheduleService(jdbc,json,service,repository,new com.yuewei.plm.module.pilot.PilotAccessService(jdbc,json),tx);}
    MoldScheduleTypes.ConfirmPlan planBaseline(long id,String reason) {var current=repository.row("mold_set",id);Map<String,JsonNode> before=new LinkedHashMap<>();MoldScheduleTypes.PLAN_KEYS.forEach(k->before.put(k,json.valueToTree(current.get(k))));return new MoldScheduleTypes.ConfirmPlan(before,reason);}
    @Test void scheduleSharesOneDateAuthorityAndKeepsImmutablePlansSeparateFromForecasts() {
        long set=mold(item());var schedules=schedules();
        assertThat(save(moldPatch(set,Map.of("openedDate","2026-09-28","manufacturingDays",14,"holidayDays",5,"extraDays",1,"plannedMoldDeliveryDate","2026-10-18","plannedFactoryArrivalDate","2026-10-25","plannedAcceptanceDate","2026-10-26","plannedProductionDate","2026-10-29"))).status()).isEqualTo("saved");
        assertThat(schedules.confirmPlan(set,planBaseline(set,"首次负责人确认"))).containsEntry("planVersion",1).containsEntry("baselineNeedsReview",false);
        assertThat(save(patch("mold_set",set,"plannedMoldDeliveryDate","2026-10-18","2026-10-19","供应商延后一天")).status()).isEqualTo("saved");
        assertThat(schedules.detail(set)).containsEntry("baselineNeedsReview",true);
        schedules.confirmPlan(set,planBaseline(set,"调整版本"));
        assertThat(jdbc.queryForObject("select plan_snapshot->>'plannedMoldDeliveryDate' from plm_mold_schedule_plan where mold_set_id=? and version_no=1",String.class,set)).isEqualTo("2026-10-18");
        assertThat(schedules.save(new BatchSave(List.of(patch("mold_set",set,"forecastFactoryDate",null,"2026-11-01",null))),null).get(0).status()).isEqualTo("saved");
        assertThat(service.mold(set)).containsEntry("plannedFactoryArrivalDate","2026-10-25").containsEntry("forecastFactoryDate","2026-11-01");
        assertThat(jdbc.queryForObject("select count(*) from plm_mold_schedule_plan where mold_set_id=?",Long.class,set)).isEqualTo(2L);
    }
    @Test void scheduleRemindersPersistAndDeduplicateWithoutExternalDelivery() {
        long set=mold(item());save(moldPatch(set,Map.of("ownerUserId",admin.userId(),"logisticsOwnerUserId",admin.userId(),"manufacturingDays",12,"plannedMoldDeliveryDate","2020-01-01")));
        var schedules=schedules();CurrentUserContext.clear();var first=schedules.enqueueAutomaticReminders();assertThat(((Number)first.get("created")).intValue()).isGreaterThanOrEqualTo(2);assertThat(first).containsEntry("externalSent",0).containsEntry("externalEnabled",false);
        assertThat(jdbc.queryForList("select distinct created_by from plm_mold_schedule_reminder where mold_set_id=?",String.class,set)).containsExactly("system");CurrentUserContext.set(admin);
        var second=schedules.enqueueReminders();assertThat(second.get("created")).isEqualTo(0);
        assertThat(jdbc.queryForObject("select count(*) from plm_mold_schedule_reminder where mold_set_id=?",Long.class,set)).isEqualTo(2L);
        MoldScheduleTypes.Query q=new MoldScheduleTypes.Query();q.setMoldSetId(set);q.setOverdueOnly(true);q.setSize(1);q.setPage(2);var tasks=schedules.tasks(q);assertThat(tasks.getContent()).hasSize(1);assertThat(tasks.getTotalElements()).isEqualTo(2);assertThat(tasks.getTotalPages()).isEqualTo(2);
    }
    @Test void scheduleSignedDatesAndMexicoTasksRemainAfterCountryArrivalWithoutPublishingBom() {
        long set=mold(item());var schedules=schedules();
        assertThat(save(moldPatch(set,Map.of("actualMexicoArrivalDate","2026-10-20","pcSignedDate","2026-10-21","tpuSignedDate","2026-10-22"))).status()).isEqualTo("saved");
        assertThat(schedules.detail(set)).containsEntry("marketEligible",false).containsEntry("pcFactoryArrivalDate",null).containsEntry("pcSignedDate","2026-10-21");
        assertThat(save(patch("mold_set",set,"marketReadyDate",null,"2026-10-22",null)).status()).isEqualTo("invalid");
        for(String p:List.of("pc","tpu")) assertThat(save(moldPatch(set,Map.of(p+"FactoryArrivalDate","2026-10-22",p+"AcceptanceDate","2026-10-23",p+"AcceptanceStatus","passed"))).status()).isEqualTo("saved");
        long boms=jdbc.queryForObject("select count(*) from plm_product_bom where status='released'",Long.class);
        assertThat(save(patch("mold_set",set,"marketReadyDate",null,"2026-10-23",null)).status()).isEqualTo("saved");
        assertThat(schedules.detail(set)).containsEntry("marketEligible",true).containsEntry("scheduleStatus","market_ready");
        assertThat(jdbc.queryForObject("select count(*) from plm_product_bom where status='released'",Long.class)).isEqualTo(boms);
    }
    @Test void scheduleImportReusesPreviewConflictAndIdempotencyAndRequiresExplicitCompatibility() throws Exception {
        long id=item(),set=mold(id);var i=service.item(id);long before=jdbc.queryForObject("select count(*) from plm_collaboration_mold_set",Long.class);
        var file=workbook("排程",new String[]{"协作档案ID","模具套ID","款式","型号","开模日期","模具制作天数","法定假期天数（人工确认）"},new Object[]{id,set,i.get("styleName"),"Note 17 PRO / PRO MAX","2026-09-28",14,5});
        var preview=imports.preview("schedule",file);var source=rows(preview).get(0);
        assertThat(source.issues()).anyMatch(s->s.contains("合写手机型号"));assertThat(source.newMoldSet()).isFalse();
        var decision=new ImportDecision(source.rowNo(),source.sheetName(),false,id,set,null,i.get("styleName").toString(),"",i.get("compatibleModels").toString(),false,source.values(),source.before(),"人工核对组合兼容型号",false);
        assertThatThrownBy(()->imports.commit(preview.get("importToken").toString(),new ImportCommit(List.of(decision)),null)).hasMessageContaining("明确确认");
        var confirmed=new ImportDecision(source.rowNo(),source.sheetName(),false,id,set,null,i.get("styleName").toString(),"",i.get("compatibleModels").toString(),false,source.values(),source.before(),"人工核对组合兼容型号",true);
        assertThat(imports.commit(preview.get("importToken").toString(),new ImportCommit(List.of(confirmed)),null)).containsEntry("saved",1);
        assertThat(imports.commit(preview.get("importToken").toString(),new ImportCommit(List.of(confirmed)),null)).containsEntry("saved",0);
        assertThat(jdbc.queryForObject("select count(*) from plm_collaboration_mold_set",Long.class)).isEqualTo(before);
    }
    @Test @EnabledIfEnvironmentVariable(named="PLM_SCHEDULE_SOURCE_XLSX",matches=".+")
    void actualSeventeenRowScheduleWorkbookOnlyPreviewsWithOriginalLineNumbers() throws Exception {
        long sets=jdbc.queryForObject("select count(*) from plm_collaboration_mold_set",Long.class),items=jdbc.queryForObject("select count(*) from plm_collaboration_item",Long.class);
        byte[] bytes=Files.readAllBytes(Path.of(System.getenv("PLM_SCHEDULE_SOURCE_XLSX")));var preview=imports.preview("schedule",new MockMultipartFile("file","产品开模时间管控.xlsx",null,bytes));var rows=rows(preview);
        assertThat(preview.get("total")).isEqualTo(17);assertThat(rows).extracting(CollaborationImportService.PreviewRow::rowNo).containsExactlyElementsOf(java.util.stream.IntStream.rangeClosed(3,19).boxed().toList());
        assertThat(rows).allSatisfy(r->{assertThat(r.newMoldSet()).isFalse();assertThat(r.values()).doesNotContainKeys("pcTotal","tpuTotal","finishedTotal");});
        assertThat(rows).anySatisfy(r->assertThat(r.issues()).anyMatch(s->s.contains("合写手机型号")));
        assertThat(jdbc.queryForObject("select count(*) from plm_collaboration_mold_set",Long.class)).isEqualTo(sets);assertThat(jdbc.queryForObject("select count(*) from plm_collaboration_item",Long.class)).isEqualTo(items);
    }
}
