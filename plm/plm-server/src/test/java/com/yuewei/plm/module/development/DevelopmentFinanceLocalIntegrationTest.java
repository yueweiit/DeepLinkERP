package com.yuewei.plm.module.development;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.pilot.PilotAccessService;
import com.yuewei.plm.module.project.dto.ProjectCostItemCreateDTO;
import com.yuewei.plm.module.project.dto.ProjectCostItemUpdateDTO;
import com.yuewei.plm.module.project.service.impl.ProjectCostServiceImpl;
import com.yuewei.plm.module.bom.service.BomLedgerService;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.DefaultTransactionDefinition;
import static com.yuewei.plm.module.development.DevelopmentTypes.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.mock;

/** Opt-in local snapshot only. Schema, all accounts and all business fixtures roll back. */
@EnabledIfEnvironmentVariable(named="PLM_COLLAB_TEST_DB_URL",matches="jdbc:postgresql://127\\.0\\.0\\.1:15432/plm_data_management\\?currentSchema=plm")
class DevelopmentFinanceLocalIntegrationTest {
    JdbcTemplate jdbc;DataSourceTransactionManager tx;TransactionStatus scope;PilotAccessService access;DevelopmentFinanceService service;DevelopmentFinanceImportService imports;long product,item;CurrentUser admin;
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    @BeforeEach void begin()throws Exception {
        var data=new DriverManagerDataSource(System.getenv("PLM_COLLAB_TEST_DB_URL"),"postgres",System.getenv("PLM_COLLAB_TEST_DB_PASSWORD"));jdbc=new JdbcTemplate(data);tx=new DataSourceTransactionManager(data);scope=tx.getTransaction(new DefaultTransactionDefinition());
        schema("plm_pilot_account","V20261012_1000__pilot_access.sql");schema("plm_development_budget","V20261012_1100__development_finance.sql");
        access=new PilotAccessService(jdbc,json);service=new DevelopmentFinanceService(jdbc,json,access,tx,mock(OperationLogService.class));imports=new DevelopmentFinanceImportService(service,mock(DevelopmentErpReadClient.class));
        var actor=jdbc.queryForList("select user_id,username,display_name from sys_user where deleted_flag=0 and status='active' and all_permissions=true order by user_id limit 1").get(0);admin=new CurrentUser(((Number)actor.get("user_id")).longValue(),actor.get("username").toString(),actor.get("display_name").toString(),true);CurrentUserContext.set(admin);
        product=jdbc.queryForObject("select product_id from plm_product p where product_type='product_line' and deleted_flag=0 and not exists(select 1 from plm_development_budget b where b.product_line_id=p.product_id and b.deleted_flag=0) order by product_id limit 1",Long.class);
        item=jdbc.queryForObject("insert into plm_collaboration_item(product_line_id,style_name,compatible_models,created_by,updated_by) values(?,'Finance Test','Apple Test Finance',?,?) returning item_id",Long.class,product,admin.username(),admin.username());
    }
    void schema(String table,String name)throws Exception{if(jdbc.queryForObject("select to_regclass(?)",String.class,"plm."+table)==null)try(var input=getClass().getResourceAsStream("/db/migration/"+name)){jdbc.execute(new String(Objects.requireNonNull(input).readAllBytes(),StandardCharsets.UTF_8));}}
    @AfterEach void rollback(){if(scope!=null&&!scope.isCompleted())tx.rollback(scope);CurrentUserContext.clear();}
    long budget(String kind,String currency){return ((Number)service.createBudget(new CreateBudget(kind,"Finance "+UUID.randomUUID(),product,kind.equals("mold")?item:null,null,null,currency),null).get("budgetId")).longValue();}
    long expense(String currency){return ((Number)service.createExpense(new CreateExpense("Test cost",product,item,null,null,currency),null).get("expenseId")).longValue();}
    Result patch(String entity,long id,Map<String,Object> values,String reason){var row=service.detail(entity,id);List<Change> changes=values.entrySet().stream().map(e->new Change(e.getKey(),json.valueToTree(row.get(e.getKey())),json.valueToTree(e.getValue()))).toList();return service.save(entity,new Batch(List.of(new Patch(id,changes,reason))),null).get(0);}
    @Test void nullableAmountsVersionsAndRealActorAreAudited() {
        long id=budget("mold","CNY");assertThat(service.detail("budget",id).get("moldCost")).isNull();assertThat(service.detail("budget",id).get("transportRate")).isEqualTo(new BigDecimal("74.6800"));
        assertThat(patch("budget",id,Map.of("moldCost",0),"").status()).isEqualTo("invalid");assertThat(patch("budget",id,Map.of("moldCost",0),"确认零值").status()).isEqualTo("saved");assertThat(service.detail("budget",id)).containsEntry("versionNo",2);assertThat(service.history("budget",id,1,20).getContent()).anySatisfy(r->assertThat(r).containsEntry("actorName",admin.username()).containsEntry("reason","确认零值"));
    }
    @Test void differentFieldsMergeSameFieldConflictRetainsOtherSuccessfulRows() {
        long a=budget("mold","CNY"),b=budget("platform","CNY");var before=service.detail("budget",a);patch("budget",a,Map.of("moldCost",100),"别人输入模具成本");
        var different=new Patch(a,List.of(new Change("customsCost",json.valueToTree(before.get("customsCost")),json.valueToTree(0))),"不同字段合并");assertThat(service.save("budget",new Batch(List.of(different)),null).get(0).status()).isEqualTo("saved");
        var stale=new Patch(a,List.of(new Change("moldCost",json.valueToTree(before.get("moldCost")),json.valueToTree(200))),"旧值冲突");var okay=new Patch(b,List.of(new Change("budgetAmount",json.nullNode(),json.valueToTree(500))),"平台计划");var results=service.save("budget",new Batch(List.of(stale,okay)),null);assertThat(results).extracting(Result::status).containsExactly("conflict","saved");assertThat(service.detail("budget",a).get("moldCost")).isEqualTo(new BigDecimal("100.00"));
    }
    @Test void parentBudgetsAndColorsAreNotAddedToChildTotalsOrCreatedTwice() {
        long parent=budget("platform","CNY");patch("budget",parent,Map.of("budgetAmount",10000),"平台计划");long child=((Number)service.createBudget(new CreateBudget("mold","Child",product,item,null,parent,"CNY"),null).get("budgetId")).longValue();patch("budget",child,Map.of("moldCost",1000,"moldWeight",0,"customsCost",0),"单档案测算");
        var q=new Query();q.setProductLineId(product);var groups=(List<Map<String,Object>>)service.summary("budget",q).get("currencyGroups");assertThat(groups).hasSize(2);assertThat(groups).anySatisfy(r->assertThat(r).containsEntry("budgetKind","platform").containsEntry("budgetTotal",new BigDecimal("10000.00"))).anySatisfy(r->assertThat(r).containsEntry("budgetKind","mold").containsEntry("budgetTotal",new BigDecimal("1000.00")));
        assertThatThrownBy(()->service.createBudget(new CreateBudget("mold","Same other color",product,item,null,parent,"CNY"),null)).hasMessageContaining("重复");
    }
    @Test void approvalDeclaredAndErpFactsAreIndependentAndCurrencyIsNotConverted() throws Exception {
        long cny=expense("CNY"),usd=expense("USD");assertThat(patch("expense",cny,Map.of("approvedAmount",50),"缺少审批").status()).isEqualTo("invalid");
        assertThat(patch("expense",cny,Map.of("requestedAmount",100,"approvedAmount",80,"approvalStatus","approved","approvalInstanceId","real-approved-id","declaredAmount",70,"state","confirmed"),"核对审批").status()).isEqualTo("saved");patch("expense",usd,Map.of("declaredAmount",5,"state","confirmed"),"美元原币");
        var q=new Query();q.setItemId(item);var groups=(List<Map<String,Object>>)service.summary("expense",q).get("currencyGroups");assertThat(groups).hasSize(2);assertThat(groups).anySatisfy(r->assertThat(r).containsEntry("currencyCode","CNY").containsEntry("erpPostedNet",null).containsEntry("approvedTotal",new BigDecimal("80.00")));assertThat(service.detail("expense",cny).get("erpPostedAmount")).isNull();
        long foreign=budget("mold","USD");assertThat(service.detail("budget",foreign)).containsEntry("transportRate",null).containsEntry("fuelRate",null);
        byte[] foreignTemplate;try(var workbook=new org.apache.poi.xssf.usermodel.XSSFWorkbook();var output=new java.io.ByteArrayOutputStream()){var sheet=workbook.createSheet("原币");var header=sheet.createRow(0);header.createCell(0).setCellValue("款式");header.createCell(1).setCellValue("模具成本");header.createCell(2).setCellValue("原币");var row=sheet.createRow(1);row.createCell(0).setCellValue("USD formula");row.createCell(1).setCellValue(100);row.createCell(2).setCellValue("USD");workbook.write(output);foreignTemplate=output.toByteArray();}
        var preview=imports.previewBudget(new MockMultipartFile("file","foreign.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",foreignTemplate));var first=((List<Map<String,Object>>)preview.get("rows")).get(0);var values=(Map<String,JsonNode>)first.get("values");assertThat(values.get("transportRate").isNull()).isTrue();assertThat(values.get("fuelRate").isNull()).isTrue();assertThat(first).containsEntry("currency","USD").containsEntry("calculatedTotal",null);
    }
    @Test void erpStableIdsIncludeNegativeReversalsAndNeverOverwritePostedAmounts() {
        String voucher="fixture-"+UUID.randomUUID();var lines=List.of(new ErpLine(voucher,"line-1","Actual paid","CNY",new BigDecimal("500"),"2026-10-12",null,1),new ErpLine(voucher,"reversal-1","Reversal","CNY",new BigDecimal("-100"),"2026-10-12",voucher+"/line-1",1));var preview=imports.previewErp(new ErpPreview(lines));String token=preview.get("token").toString();var decisions=List.of(new ErpDecision(1,false,product,item,null,null,"合同与档案核对"),new ErpDecision(2,false,product,item,null,null,"原单冲销核对"));
        assertThat(imports.commitErp(new ErpCommit(token,decisions),null)).containsEntry("saved",2);assertThat(imports.commitErp(new ErpCommit(token,decisions),null)).containsEntry("saved",0).containsEntry("skipped",2);
        var q=new Query();q.setItemId(item);assertThat((List<Map<String,Object>>)service.summary("expense",q).get("currencyGroups")).singleElement().satisfies(r->assertThat(r.get("erpPostedNet")).isEqualTo(new BigDecimal("400.00")));
        var row=service.page("expense",q).getContent().get(0);assertThat(patch("expense",((Number)row.get("expenseId")).longValue(),Map.of("declaredAmount",50),"不能改ERP原值").status()).isEqualTo("invalid");
    }
    @Test void oldProjectEndpointsDelegateToTheSameLedgerAndNoLongerAddBomUnitCosts() {
        var old=new ProjectCostServiceImpl(service,mock(BomLedgerService.class));var dto=new ProjectCostItemCreateDTO();dto.setCostCategory("mold");dto.setCostName("旧入口复用");dto.setAmount(new BigDecimal("12.5"));dto.setCurrencyCode("CNY");var created=old.createItem(product,dto,null);long id=created.getProjectCostItemId();
        var update=new ProjectCostItemUpdateDTO();update.setCostCategory("mold");update.setCostName("旧入口复用");update.setAmount(new BigDecimal("15"));assertThatThrownBy(()->old.updateItem(product,id,update,null)).hasMessageContaining("beforeUpdatedAt");assertThat(service.detail("expense",id).get("declaredAmount")).isEqualTo(new BigDecimal("12.500000"));
        update.setBeforeUpdatedAt(created.getUpdatedAt());var accepted=old.updateItem(product,id,update,null);assertThat(accepted.getAmount()).isEqualByComparingTo("15");
        patch("expense",id,Map.of("declaredAmount",20),"新入口更新，旧客户端不得覆盖");jdbc.update("update plm_project_cost_item set updated_at=updated_at+interval '1 microsecond' where project_cost_item_id=?",id);update.setBeforeUpdatedAt(accepted.getUpdatedAt());assertThatThrownBy(()->old.updateItem(product,id,update,null)).hasMessageContaining("已被修改");assertThat(service.detail("expense",id).get("declaredAmount")).isEqualTo(new BigDecimal("20.000000"));
        update.setBeforeUpdatedAt(old.listItems(product).get(0).getUpdatedAt());update.setAmount(new BigDecimal("22.5"));assertThat(old.updateItem(product,id,update,null).getAmount()).isEqualByComparingTo("22.5");old.confirmItem(product,id,null);
        assertThat(service.detail("expense",id)).containsEntry("productId",product).containsEntry("state","confirmed");assertThat(old.getSummary(product).getTotalCost()).isEqualByComparingTo("22.5");assertThat(old.getSummary(product).getRdCost()).isEqualByComparingTo("0");old.voidItem(product,id,null);assertThat(service.detail("expense",id)).containsEntry("state","void");
    }
    @Test void realFinancePermissionsAndObjectScopesRejectForgedAdministrator() {
        long id=jdbc.queryForObject("select max(user_id)+100 from sys_user",Long.class);jdbc.update("insert into sys_user(user_id,user_code,user_name,login_name,username,display_name,status,all_permissions) values(?,?,?,?,?,?,'active',false)",id,"finance-it-"+id,"财务权限测试","finance-it-"+id,"finance-real-"+id,"财务权限测试");jdbc.update("insert into plm_pilot_account(user_id,role_code,permissions,all_objects,created_by,updated_by) values(?,'domestic','[]'::jsonb,false,'test','test')",id);CurrentUserContext.set(new CurrentUser(id,"forged","forged",true));assertThatThrownBy(()->service.page("expense",new Query())).hasMessageContaining("finance:read");
        jdbc.update("update plm_pilot_account set role_code='finance',permissions='[\"finance:read\",\"finance:write\"]'::jsonb where user_id=?",id);assertThat(service.page("budget",new Query()).getContent()).isEmpty();assertThatThrownBy(()->service.createExpense(new CreateExpense("无对象授权",product,item,null,null,"CNY"),null)).hasMessageContaining("授权");
        jdbc.update("insert into plm_pilot_scope(user_id,entity_type,entity_id) values(?,'item',?)",id,item);jdbc.update("insert into plm_pilot_scope(user_id,entity_type,entity_id) values(?,'product',?)",id,product);long expense=expense("CNY");assertThat(patch("expense",expense,Map.of("state","confirmed"),"无确认权限").status()).isEqualTo("forbidden");
    }
    @Test void serverPaginationLimitsRenderedPageAndSearchHitsAcrossPages() {
        for(int n=0;n<55;n++)service.createExpense(new CreateExpense("Paging fixture "+n,product,item,null,null,"CNY"),null);var q=new Query();q.setItemId(item);assertThat(service.page("expense",q).getContent()).hasSize(50);q.setPage(2);assertThat(service.page("expense",q).getContent()).hasSize(5);q.setPage(1);q.setKeyword("fixture 3");assertThat(service.page("expense",q).getTotalElements()).isEqualTo(11);
    }
    @Test void embeddedProjectViewFiltersExistingExpensesWithoutGuessingSharedArchive() {
        long id=((Number)service.createExpense(new CreateExpense("嵌入旧项目",null,null,null,null,"CNY",product),null).get("expenseId")).longValue();expense("CNY");var q=new Query();q.setProductId(product);assertThat(service.page("expense",q).getContent()).singleElement().satisfies(r->assertThat(r).containsEntry("expenseId",id).containsEntry("itemId",null).containsEntry("productId",product));
        assertThat(patch("expense",id,Map.of("declaredAmount",20),"旧页与新页共用草稿").status()).isEqualTo("saved");assertThat(service.detail("expense",id).get("declaredAmount")).isEqualTo(new BigDecimal("20.000000"));
    }
    @Test void missingErpConfigurationDoesNotCallOrCreateExternalFinancialData(){long count=jdbc.queryForObject("select count(*) from plm_project_cost_item",Long.class);assertThat(imports.refreshErp()).containsEntry("status","not_configured");assertThat(jdbc.queryForObject("select count(*) from plm_project_cost_item",Long.class)).isEqualTo(count);}
    @Test void syntheticFileImportIsIdempotentAndUsesOriginalValuesForConflicts()throws Exception {
        long id=budget("platform","CNY");byte[] bytes;try(var workbook=new org.apache.poi.xssf.usermodel.XSSFWorkbook();var out=new java.io.ByteArrayOutputStream()){var sheet=workbook.createSheet("test");String[] headers={"预算ID","预算名称","手工预算","测算方式"};var top=sheet.createRow(0);for(int n=0;n<headers.length;n++)top.createCell(n).setCellValue(headers[n]);var row=sheet.createRow(1);row.createCell(0).setCellValue(id);row.createCell(1).setCellValue("合成测试预算");row.createCell(2).setCellValue(1000);row.createCell(3).setCellValue("manual");workbook.write(out);bytes=out.toByteArray();}
        var preview=imports.previewBudget(new MockMultipartFile("file","synthetic.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",bytes));var row=((List<Map<String,Object>>)preview.get("rows")).get(0);var decision=new ImportDecision("test",2,false,id,product,null,null,null,"合成测试预算",(Map<String,JsonNode>)row.get("values"),(Map<String,JsonNode>)row.get("before"),"仅回滚合成文件测试","platform");var commit=new ImportCommit(preview.get("token").toString(),List.of(decision));assertThat(imports.commitBudget(commit,null)).containsEntry("saved",1);assertThat(imports.commitBudget(commit,null)).containsEntry("saved",0).containsEntry("duplicate",true);
        byte[] scopeFile;try(var workbook=new org.apache.poi.xssf.usermodel.XSSFWorkbook(new java.io.ByteArrayInputStream(bytes));var out=new java.io.ByteArrayOutputStream()){var sheet=workbook.getSheetAt(0);sheet.getRow(0).getCell(0).setCellValue("预算类型");sheet.getRow(1).getCell(0).setCellValue("platform");workbook.write(out);scopeFile=out.toByteArray();}var mapped=imports.previewBudget(new MockMultipartFile("file","synthetic-scope.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",scopeFile));var mappedRow=((List<Map<String,Object>>)mapped.get("rows")).get(0);var explicit=new ImportDecision("test",2,false,null,product,item,null,id,"人工选择模具层级",(Map<String,JsonNode>)mappedRow.get("values"),Map.of(),"仅回滚：明确档案ID，不猜原款式名称","mold");assertThat(imports.commitBudget(new ImportCommit(mapped.get("token").toString(),List.of(explicit)),null)).containsEntry("saved",1);var q=new Query();q.setItemId(item);assertThat(service.page("budget",q).getContent()).singleElement().satisfies(r->assertThat(r).containsEntry("budgetKind","mold").containsEntry("parentBudgetId",id));
        byte[] changed;try(var workbook=new org.apache.poi.xssf.usermodel.XSSFWorkbook(new java.io.ByteArrayInputStream(bytes));var out=new java.io.ByteArrayOutputStream()){workbook.getSheetAt(0).getRow(1).getCell(2).setCellValue(2000);workbook.write(out);changed=out.toByteArray();}var second=imports.previewBudget(new MockMultipartFile("file","synthetic-v2.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",changed));var next=((List<Map<String,Object>>)second.get("rows")).get(0);patch("budget",id,Map.of("budgetAmount",3000),"预览后他人更新");var stale=new ImportDecision("test",2,false,id,product,null,null,null,"合成测试预算",(Map<String,JsonNode>)next.get("values"),(Map<String,JsonNode>)next.get("before"),"旧预览不能覆盖",null);assertThatThrownBy(()->imports.commitBudget(new ImportCommit(second.get("token").toString(),List.of(stale)),null)).hasMessageContaining("同字段");
        var forbiddenLayer=new ImportDecision("test",2,false,id,product,item,null,null,"不能修改已有层级",(Map<String,JsonNode>)next.get("values"),(Map<String,JsonNode>)next.get("before"),"仅回滚层级防错","mold");assertThatThrownBy(()->imports.commitBudget(new ImportCommit(second.get("token").toString(),List.of(forbiddenLayer)),null)).hasMessageContaining("层级固定");assertThat(service.detail("budget",id)).containsEntry("budgetKind","platform").containsEntry("budgetAmount",new BigDecimal("3000.00"));
    }
    @Test @EnabledIfEnvironmentVariable(named="PLM_FINANCE_SOURCE_XLSX",matches=".+")
    void originalFourRowsAreReadOnlyPreviewedWithCorrectRatesAndNoRealImport()throws Exception {
        var path=Path.of(System.getenv("PLM_FINANCE_SOURCE_XLSX"));byte[] source=Files.readAllBytes(path);long before=jdbc.queryForObject("select count(*) from plm_development_budget",Long.class);var preview=imports.previewBudget(new MockMultipartFile("file",path.getFileName().toString(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",source));
        assertThat(preview).containsEntry("total",4);var rows=(List<Map<String,Object>>)preview.get("rows");assertThat(rows).extracting(r->r.get("rowNo")).containsExactly(2,3,4,5);assertThat(rows.get(0)).containsEntry("kind","platform").containsEntry("productLineId",null).containsEntry("calculatedTotal",new BigDecimal("21702.30"));assertThat(((Map<String,JsonNode>)rows.get(0).get("values")).get("transportRate").decimalValue()).isEqualByComparingTo("74.68");assertThat(Files.readAllBytes(path)).isEqualTo(source);assertThat(jdbc.queryForObject("select count(*) from plm_development_budget",Long.class)).isEqualTo(before);
    }
}
