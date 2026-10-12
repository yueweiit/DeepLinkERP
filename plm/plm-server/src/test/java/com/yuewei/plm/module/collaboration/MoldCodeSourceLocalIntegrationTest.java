package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.security.CurrentUserContext;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.DefaultTransactionDefinition;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static com.yuewei.plm.module.collaboration.MoldCodeSourceTypes.*;

/** Local-only opt-in; every source/account fixture is rolled back. */
@EnabledIfEnvironmentVariable(named="PLM_COLLAB_TEST_DB_URL",matches="jdbc:postgresql://127\\.0\\.0\\.1:15432/plm_data_management\\?currentSchema=plm")
class MoldCodeSourceLocalIntegrationTest {
    JdbcTemplate jdbc;DataSourceTransactionManager tx;TransactionStatus scope;CollaborationService collaboration;MoldCodeSourceService service;
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();CurrentUser admin;
    @BeforeEach void begin() {
        var data=new DriverManagerDataSource(System.getenv("PLM_COLLAB_TEST_DB_URL"),"postgres",System.getenv("PLM_COLLAB_TEST_DB_PASSWORD"));
        jdbc=new JdbcTemplate(data);tx=new DataSourceTransactionManager(data);scope=tx.getTransaction(new DefaultTransactionDefinition());
        collaboration=new CollaborationService(jdbc,json,new CollaborationRepository(jdbc,json),tx,mock(OperationLogService.class));service=new MoldCodeSourceService(jdbc,json,collaboration);
        var row=jdbc.queryForList("select user_id,username,display_name from sys_user where deleted_flag=0 and status='active' and all_permissions=true order by user_id limit 1").get(0);
        admin=new CurrentUser(((Number)row.get("user_id")).longValue(),row.get("username").toString(),row.get("display_name").toString(),true);CurrentUserContext.set(admin);
    }
    @AfterEach void rollback() {if(scope!=null&&!scope.isCompleted()) tx.rollback(scope);CurrentUserContext.clear();}
    SourceItem item(String code,String name) {return new SourceItem(code,name,"测试分类","PC",null,false,null);}
    String eventId() {return "test-"+UUID.randomUUID();}
    String snapshotId() {return MoldCodeSourceService.sha256(eventId());}
    long physicalCount() {return jdbc.queryForObject("select count(*) from plm_collaboration_mold_set",Long.class);}
    long inventoryCount() {return jdbc.queryForObject("select count(*) from plm_inventory",Long.class);}
    @Test void codeIdentityIsParsedWithoutRewritingLeadingZerosOrOriginalCase() {
        assertThat(MoldCodeSourceService.identity("mBA200007")).isEqualTo(new MoldCodeSourceService.Identity("BA","0007","PC"));
        assertThat(MoldCodeSourceService.identity("MBA100007").part()).isEqualTo("TPU");
        assertThat(MoldCodeSourceService.identity("MJ000921").part()).isNull();
    }
    @Test void receiveIsIdempotentAuditedAndNeverCreatesPhysicalSetsInventoryOrProjects() {
        String code="raw-"+eventId();long physical=physicalCount(),inventory=inventoryCount();
        var dto=new DingTalkCodeEvent(eventId(),null,null,item(code,"原名称\t"));
        assertThat(service.receive(dto)).containsEntry("status","created").containsEntry("approvalTrace","not_provided").containsEntry("physicalSetsCreated",0);
        assertThat(service.receive(dto)).containsEntry("status","duplicate");
        assertThat(service.receive(new DingTalkCodeEvent(eventId(),null,null,dto.item()))).containsEntry("status","linked_existing");
        var row=jdbc.queryForList("select * from plm_mold_code_source where source_system='dingtalk' and mold_code=?",code).get(0);
        assertThat(row).containsEntry("mold_name","原名称\t").containsEntry("created_by",admin.username());
        assertThat(physicalCount()).isEqualTo(physical);assertThat(inventoryCount()).isEqualTo(inventory);
        assertThat(jdbc.queryForObject("select count(*) from plm_integration_record where source_system='dingtalk' and integration_type='mold_code_catalog' and external_instance_id=? and created_by=?",Long.class,dto.eventId(),admin.username())).isEqualTo(1L);
    }
    @Test void reusedEventsAndSameCodeChangedNamesAreConflictsNotOverwrites() {
        var dto=new DingTalkCodeEvent(eventId(),null,null,item("raw-"+eventId(),"原名称"));service.receive(dto);
        assertThatThrownBy(()->service.receive(new DingTalkCodeEvent(dto.eventId(),null,null,item(dto.item().itemCode(),"改名")))).isInstanceOf(BusinessException.class).hasMessageContaining("事件");
        assertThatThrownBy(()->service.receive(new DingTalkCodeEvent(eventId(),null,null,item(dto.item().itemCode(),"改名")))).isInstanceOf(BusinessException.class).hasMessageContaining("人工核对");
        assertThat(jdbc.queryForObject("select mold_name from plm_mold_code_source where source_system='dingtalk' and mold_code=?",String.class,dto.item().itemCode())).isEqualTo("原名称");
    }
    @Test void approvalMetadataIsNotInventedAndRejectedApprovalIsNotReceived() {
        var row=item("raw-"+eventId(),"型号");
        assertThatThrownBy(()->service.receive(new DingTalkCodeEvent(eventId(),null,"approved",row))).hasMessageContaining("实例 ID");
        assertThatThrownBy(()->service.receive(new DingTalkCodeEvent(eventId(),"real-id","rejected",row))).hasMessageContaining("未通过");
        assertThat(service.receive(new DingTalkCodeEvent(eventId(),"real-id","approved",row))).containsEntry("approvalTrace","provided");
    }
    @Test void sourcePreviewIsRepeatableAndModifiedBaselinesAreNotOverwritten() {
        String code="raw-"+eventId();long physical=physicalCount();var dto=new ErpPreview(snapshotId(),List.of(item(code,"原名")));
        assertThat(service.previewErp(dto)).containsEntry("created",1).containsEntry("physicalSetsCreated",0);
        assertThat(service.previewErp(dto)).containsEntry("status","duplicate");
        assertThat(service.previewErp(new ErpPreview(snapshotId(),List.of(item(code,"新名"))))).containsEntry("created",0).containsEntry("conflicts",List.of(code));
        assertThatThrownBy(()->service.previewErp(new ErpPreview(dto.snapshotId(),List.of(item(code,"新名"))))).hasMessageContaining("快照 ID");
        assertThat(physicalCount()).isEqualTo(physical);
    }
    @Test void ordinaryEngineeringActorIsResolvedFromServerAndOtherGroupsCannotWrite() {
        Long id=jdbc.queryForObject("select max(user_id)+100 from sys_user",Long.class);
        jdbc.update("insert into sys_user(user_id,user_code,user_name,login_name,username,display_name,status,all_permissions) values(?,?,?,?,?,?,'active',false)",id,"source-it-"+id,"来源测试","source-it-"+id,"source-real-"+id,"来源测试");
        CurrentUserContext.set(new CurrentUser(id,"forged-admin","forged",true));
        var dto=new DingTalkCodeEvent(eventId(),null,null,item("raw-"+eventId(),"型号"));
        assertThatThrownBy(()->service.receive(dto)).hasMessageContaining("权限");
        jdbc.update("insert into plm_collaboration_assignment(field_group,user_id) values('engineering',?)",id);
        service.receive(dto);
        assertThat(jdbc.queryForObject("select created_by from plm_mold_code_source where source_system='dingtalk' and mold_code=?",String.class,dto.item().itemCode())).isEqualTo("source-real-"+id);
        assertThatThrownBy(()->service.previewErp(new ErpPreview(snapshotId(),List.of(dto.item())))).hasMessageContaining("管理员");
        jdbc.update("update sys_user set status='inactive' where user_id=?",id);
        assertThatThrownBy(()->service.receive(dto)).hasMessageContaining("失效");
    }
    @Test void crossSourceNameDisagreementIsVisibleButDoesNotOverwriteEitherOriginal() {
        String code="raw-"+eventId();service.previewErp(new ErpPreview(snapshotId(),List.of(item(code,"ERP 原名"))));
        service.receive(new DingTalkCodeEvent(eventId(),null,null,item(code,"钉钉新名")));
        Query q=new Query();q.setKeyword(code);q.setReview("source_conflict");
        var rows=service.page(q).getContent();assertThat(rows).hasSize(2);
        assertThat(rows).extracting(r->r.get("moldName")).containsExactlyInAnyOrder("ERP 原名","钉钉新名");
        assertThat(rows).allSatisfy(r->assertThat(r.get("sourceNameCount")).isEqualTo(2L));
    }
    @Test void pagingSearchAndPairWarningsUseSourcesNotPhysicalSetCounts() {
        service.previewErp(new ErpPreview(snapshotId(),List.of(item("MZZ209998","Apple Test PC"),item("MZZ109998","Apple Test TPU"),item("MZZ209997","Only PC"))));
        Query q=new Query();q.setSource("erp");q.setKeyword("MZZ");q.setSize(1);q.setPage(2);
        assertThat(service.page(q).getContent()).hasSize(1);assertThat(service.page(q).getTotalElements()).isEqualTo(3);
        q.setSize(50);q.setPage(1);q.setReview("name_conflict");assertThat(service.page(q).getContent()).hasSize(2);
        q.setReview("incomplete");assertThat(service.page(q).getContent()).hasSize(1);
        assertThat(service.page(q).getContent().get(0)).containsEntry("moldCode","MZZ209997").containsEntry("phoneModelCode","9997").containsEntry("itemId",null);
    }
    @Test void httpValidationAndAuthenticationDoNotAcceptForgedActorsOrUnapprovedStatus() throws Exception {
        var mvc=org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(new MoldCodeSourceController(service)).setControllerAdvice(new com.yuewei.plm.common.exception.GlobalExceptionHandler()).build();
        String payload="{\"eventId\":\"test\",\"approvalStatus\":\"rejected\",\"createdBy\":\"admin\",\"item\":{\"itemCode\":\"code\",\"itemName\":\"name\"}}";
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post("/api/v1/integrations/dingtalk/mold-codes").contentType("application/json").content(payload)).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isBadRequest());
        CurrentUserContext.clear();
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post("/api/v1/integrations/dingtalk/mold-codes").contentType("application/json").content("{\"eventId\":\"test\",\"item\":{\"itemCode\":\"code\",\"itemName\":\"name\"}}")).andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isUnauthorized());
    }
}
