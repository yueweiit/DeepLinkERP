package com.yuewei.plm.module.pilot;
import com.fasterxml.jackson.databind.ObjectMapper;import com.yuewei.plm.common.exception.BusinessException;import com.yuewei.plm.common.security.*;import com.yuewei.plm.module.auth.service.TokenSessionService;import com.yuewei.plm.module.operationlog.service.OperationLogCreateCommand;import com.yuewei.plm.module.operationlog.service.OperationLogService;
import java.util.*;import org.junit.jupiter.api.*;import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;import org.springframework.jdbc.core.JdbcTemplate;import org.springframework.jdbc.datasource.*;import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;import org.springframework.transaction.*;import org.springframework.transaction.support.DefaultTransactionDefinition;import org.springframework.transaction.support.TransactionTemplate;
import static org.assertj.core.api.Assertions.*;import static org.mockito.Mockito.*;

/** Local opt-in only; every account, grant, mold and attachment fixture rolls back. */
@EnabledIfEnvironmentVariable(named="PLM_COLLAB_TEST_DB_URL",matches="jdbc:postgresql://127\\.0\\.0\\.1:15432/plm_data_management\\?currentSchema=plm")
class PilotAccessLocalIntegrationTest {
 JdbcTemplate jdbc;DataSourceTransactionManager tx;TransactionStatus scope;PilotAccessService access;PilotUserService users;CurrentUser admin;ObjectMapper json=new ObjectMapper().findAndRegisterModules();BCryptPasswordEncoder encoder=new BCryptPasswordEncoder();
 @BeforeEach void begin(){var data=new DriverManagerDataSource(System.getenv("PLM_COLLAB_TEST_DB_URL"),"postgres",System.getenv("PLM_COLLAB_TEST_DB_PASSWORD"));jdbc=new JdbcTemplate(data);tx=new DataSourceTransactionManager(data);scope=tx.getTransaction(new DefaultTransactionDefinition());access=new PilotAccessService(jdbc,json);users=new PilotUserService(jdbc,json,access,encoder,mock(OperationLogService.class));var a=jdbc.queryForList("select user_id,username,display_name from sys_user where all_permissions=true and status='active' and deleted_flag=0 order by user_id limit 1").get(0);admin=new CurrentUser(((Number)a.get("user_id")).longValue(),a.get("username").toString(),a.get("display_name").toString(),true);CurrentUserContext.set(admin);}
 @AfterEach void rollback(){CurrentUserContext.clear();if(scope!=null&&!scope.isCompleted())tx.rollback(scope);}
 String username(){return "pilot-test-"+UUID.randomUUID();}
 PilotUserService.UserInput input(String username,String role,List<PilotUserService.Scope> grants,Long version,String status){return new PilotUserService.UserInput(username,"测试账号","回滚测试",role,status,false,"ding-"+username,null,null,grants,"test-only-password-123",version);}
 long create(String role,List<PilotUserService.Scope> grants){var result=users.save(null,input(username(),role,grants,null,"active"),null);return ((Number)result.get("userId")).longValue();}
 void as(long id){CurrentUserContext.set(new CurrentUser(id,"forged-admin","冒用",true));}
 long item(){return jdbc.queryForObject("select item_id from plm_collaboration_item where product_line_id is not null and deleted_flag=0 order by item_id limit 1",Long.class);}
 long mold(long item,int n){return jdbc.queryForObject("insert into plm_collaboration_mold_set(item_id,set_no,set_name,created_by,updated_by) values(?,?,?,'test','test') returning mold_set_id",Long.class,item,n,"测试套"+n);}
 @Test void realAccountPersistsOnlyPasswordHashAndServerRole(){long id=create("supplier",List.of());String hash=jdbc.queryForObject("select password_hash from sys_user where user_id=?",String.class,id);assertThat(hash).isNotEqualTo("test-only-password-123");assertThat(encoder.matches("test-only-password-123",hash)).isTrue();as(id);assertThat(access.actor().allPermissions()).isFalse();assertThat(access.hasPermission("task:ship")).isTrue();assertThatThrownBy(access::requireFinanceRead).isInstanceOf(BusinessException.class);assertThatThrownBy(users::users).isInstanceOf(BusinessException.class);}
 @Test void requiredAuditStorageFailureRollsBackRealAccountGrantsAndResponsibilities(){
  String login=username();long[] createdId={0};long item=item();var logs=mock(OperationLogService.class);
  when(logs.logRequired(any(OperationLogCreateCommand.class),any(CurrentUser.class))).thenAnswer(call->{
   OperationLogCreateCommand command=call.getArgument(0);CurrentUser actor=call.getArgument(1);createdId[0]=Long.parseLong(command.getBusinessId());
   assertThat(actor.userId()).isEqualTo(admin.userId());
   assertThat(jdbc.queryForObject("select count(*) from sys_user where user_id=? and username=?",Long.class,createdId[0],login)).isEqualTo(1L);
   assertThat(jdbc.queryForObject("select count(*) from plm_pilot_account where user_id=? and role_code='supplier'",Long.class,createdId[0])).isEqualTo(1L);
   assertThat(jdbc.queryForList("select field_group from plm_collaboration_assignment where user_id=? order by field_group",String.class,createdId[0])).containsExactly("engineering","logistics");
   assertThat(jdbc.queryForObject("select count(*) from plm_pilot_scope where user_id=? and entity_type='item' and entity_id=?",Long.class,createdId[0],item)).isEqualTo(1L);
   throw new IllegalStateException("test-required-audit-storage-failure");
  });
  var service=new PilotUserService(jdbc,json,access,encoder,logs);var saveTx=new TransactionTemplate(tx);
  saveTx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
  assertThatThrownBy(()->saveTx.execute(status->{assertThat(status.isNewTransaction()).isTrue();return service.save(null,input(login,"supplier",List.of(new PilotUserService.Scope("item",item)),null,"active"),null);}))
   .isInstanceOf(IllegalStateException.class).hasMessage("test-required-audit-storage-failure");
  assertThat(createdId[0]).isPositive();verify(logs).logRequired(any(OperationLogCreateCommand.class),any(CurrentUser.class));
  assertThat(jdbc.queryForObject("select count(*) from sys_user where username=?",Long.class,login)).isZero();
  assertThat(jdbc.queryForObject("select count(*) from plm_pilot_account where user_id=?",Long.class,createdId[0])).isZero();
  assertThat(jdbc.queryForObject("select count(*) from plm_collaboration_assignment where user_id=?",Long.class,createdId[0])).isZero();
  assertThat(jdbc.queryForObject("select count(*) from plm_pilot_scope where user_id=?",Long.class,createdId[0])).isZero();
  assertThat(scope.isCompleted()).isFalse();
 }
 @Test void exactMoldGrantDoesNotAuthorizeSiblingSetsOrFiles(){long item=item(),a=mold(item,800001),b=mold(item,800002);long id=create("supplier",List.of(new PilotUserService.Scope("mold",a)));as(id);access.requireMold(a);access.requireItem(item);assertThatThrownBy(()->access.requireMold(b)).isInstanceOf(BusinessException.class);long file=jdbc.queryForObject("insert into plm_attachment(owner_object_type,owner_object_id,file_category,file_name,original_file_name,file_size,storage_key,created_by,updated_by) select 'Product',product_line_id,'drawing','test.pdf','test.pdf',0,'test-only','rollback-test','rollback-test' from plm_collaboration_item where item_id=? returning attachment_id",Long.class,item);assertThatThrownBy(()->access.requireFile(file)).isInstanceOf(BusinessException.class);}
 @Test void ProductScopeExpandsToItsMoldsButNotUnrelatedFiles(){long item=item(),mold=mold(item,800001),product=jdbc.queryForObject("select product_line_id from plm_collaboration_item where item_id=?",Long.class,item);long id=create("supplier",List.of(new PilotUserService.Scope("product",product)));as(id);access.requireProduct(product);access.requireItem(item);access.requireMold(mold);assertThat(access.visibleSqlClause("file","a.attachment_id")).contains("entity_type='file'");}
 @Test void staleGrantEditAndAccountDisableInvalidateExistingIdentity(){String login=username();long id=((Number)users.save(null,input(login,"mexico",List.of(),null,"active"),null).get("userId")).longValue();users.save(id,input(login,"mexico",List.of(),1L,"inactive"),null);assertThatThrownBy(()->users.save(id,input(login,"mexico",List.of(),1L,"active"),null)).isInstanceOf(BusinessException.class).hasMessageContaining("已变更");as(id);assertThatThrownBy(access::actor).isInstanceOf(BusinessException.class).hasMessageContaining("停用");}
 @Test @SuppressWarnings("unchecked") void responsibilityEditorInvalidatesOnlyChangedAccountDrafts(){
  String login=username();long changed=((Number)users.save(null,input(login,"supplier",List.of(),null,"active"),null).get("userId")).longValue(),unchanged=create("supplier",List.of());
  var logs=mock(OperationLogService.class);var collaboration=new com.yuewei.plm.module.collaboration.CollaborationService(jdbc,json,new com.yuewei.plm.module.collaboration.CollaborationRepository(jdbc,json),tx,logs);
  Map<String,List<Long>> before=(Map<String,List<Long>>)collaboration.assignments().get("groups"),next=new LinkedHashMap<>(before);
  next.put("engineering",before.get("engineering").stream().filter(id->id!=changed).toList());
  collaboration.saveAssignments(new com.yuewei.plm.module.collaboration.CollaborationTypes.Assignments(next,before),null);
  assertThat(jdbc.queryForObject("select version_no from plm_pilot_account where user_id=?",Long.class,changed)).isEqualTo(2L);
  assertThat(jdbc.queryForObject("select version_no from plm_pilot_account where user_id=?",Long.class,unchanged)).isEqualTo(1L);
  assertThat(jdbc.queryForList("select field_group from plm_collaboration_assignment where user_id=?",String.class,changed)).containsExactly("logistics");
  assertThatThrownBy(()->users.save(changed,input(login,"supplier",List.of(),1L,"active"),null)).isInstanceOf(BusinessException.class).hasMessageContaining("已变更");
  collaboration.saveAssignments(new com.yuewei.plm.module.collaboration.CollaborationTypes.Assignments(next,next),null);
  assertThat(jdbc.queryForObject("select version_no from plm_pilot_account where user_id=?",Long.class,changed)).isEqualTo(2L);
  verify(logs,times(2)).logSuccess(argThat(command->command.getAction().equals("COLLABORATION_ASSIGNMENTS")));
 }
 @Test void externalRoleCannotRequestAllObjectsOrOtherFieldGroups(){long before=jdbc.queryForObject("select count(*) from sys_user",Long.class);var bad=new PilotUserService.UserInput(username(),"测试","回滚测试","supplier","active",true,null,null,List.of("mexico"),List.of(),"test-only-password-123",null);assertThatThrownBy(()->users.save(null,bad,null)).isInstanceOf(BusinessException.class);assertThat(jdbc.queryForObject("select count(*) from sys_user",Long.class)).isEqualTo(before);}
 @Test void mappedDingTalkIdentityUsesExistingSessionAndInactiveMappingIsRejected(){long id=create("mexico",List.of());String uid=jdbc.queryForObject("select dingtalk_user_id from plm_pilot_account where user_id=?",String.class,id);var tokens=mock(TokenSessionService.class);when(tokens.createSession(any())).thenReturn("test-session");var sso=new PilotDingTalkSsoService(jdbc,json,tokens,access);assertThat(sso.mappedSession(uid).getUser().getUserId()).isEqualTo(id);assertThat(sso.mappedSession(uid).getUser().getPermissions()).contains("task:arrival").doesNotContain("finance:read");jdbc.update("update sys_user set status='inactive' where user_id=?",id);assertThatThrownBy(()->sso.mappedSession(uid)).isInstanceOf(BusinessException.class).hasMessageContaining("未关联");}
}
