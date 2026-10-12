package com.yuewei.plm.module.pilot;
import com.fasterxml.jackson.databind.ObjectMapper;import com.yuewei.plm.common.exception.*;import com.yuewei.plm.common.security.*;import com.yuewei.plm.module.auth.service.TokenSessionService;
import java.util.*;import org.junit.jupiter.api.*;import org.springframework.jdbc.core.JdbcTemplate;import org.springframework.test.web.servlet.*;import org.springframework.test.web.servlet.setup.MockMvcBuilders;import org.springframework.web.bind.annotation.*;
import static org.assertj.core.api.Assertions.*;import static org.mockito.Mockito.*;import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class PilotSecurityTest {
 JdbcTemplate jdbc;ObjectMapper json=new ObjectMapper().findAndRegisterModules();PilotAccessService access;MockMvc mvc;String role;List<String> permissions;boolean allObjects,pilot,active;
 @BeforeEach void start(){jdbc=mock(JdbcTemplate.class);role="supplier";permissions=PilotAccessService.ROLE_PERMISSIONS.get(role);allObjects=false;pilot=true;active=true;
  when(jdbc.queryForList(anyString(),eq(7L))).thenAnswer(i->{String sql=i.getArgument(0);if(sql.contains("from sys_user"))return active?List.of(Map.of("user_id",7L,"username","real-supplier","display_name","真实供应商","all_permissions",false)):List.of();return pilot?List.of(Map.of("role_code",role,"permissions",json.writeValueAsString(permissions),"all_objects",allObjects)):List.of();});
  when(jdbc.queryForObject(anyString(),eq(Long.class),anyLong())).thenAnswer(i->((Number)i.getArgument(2)).longValue()==1L?1L:0L);
  access=new PilotAccessService(jdbc,json);CurrentUserContext.set(new CurrentUser(7L,"forged-admin","冒用",true));
  mvc=MockMvcBuilders.standaloneSetup(new Fixture()).addInterceptors(new PilotSecurityInterceptor(access)).setControllerAdvice(new GlobalExceptionHandler(),new PilotMoneyResponseAdvice(access,json),new PilotMoneyRequestAdvice(access,json)).build();
 }
 @AfterEach void clear(){CurrentUserContext.clear();}
 @RestController static class Fixture{
  @RequestMapping("/api/v1/**") Map<String,Object> any(){return Map.of("safe","visible","amount",999,"nested",Map.of("projectName","A","unitCost",8,"phonePrice",12));}
  @PostMapping("/api/v1/boms/{id}/items") Map<String,Object> bomItem(@RequestBody com.yuewei.plm.module.bom.dto.ProductBomItemDTO dto){return Map.of("itemName",Objects.toString(dto.getItemName(),""));}
  @PostMapping("/api/v1/collaboration-plans/items/{id}/patch") Map<String,Object> patch(@RequestBody Map<String,Object> dto){return dto;}
 }
 @Test void identityComesFromLiveAccountNotClaimedRoleAndDisabledSessionsFail(){assertThat(access.actor().username()).isEqualTo("real-supplier");assertThat(access.actor().allPermissions()).isFalse();active=false;assertThatThrownBy(access::actor).isInstanceOf(BusinessException.class).hasMessageContaining("失效");}
 @Test void supplierCannotEscapeThroughOldCollectionsOrUnassignedDownloads()throws Exception{
  mvc.perform(get("/api/v1/molds")).andExpect(status().isForbidden());
  mvc.perform(get("/api/v1/file-center/attachments")).andExpect(status().isForbidden());
  mvc.perform(get("/api/v1/attachments/2/download")).andExpect(status().isForbidden());
  mvc.perform(get("/api/v1/attachments/1/download")).andExpect(status().isOk()).andExpect(jsonPath("$.amount").doesNotExist());
 }
 @Test void mexicoCannotWriteBomOrFileEvenWithAssignedObjects()throws Exception{role="mexico";permissions=PilotAccessService.ROLE_PERMISSIONS.get(role);mvc.perform(post("/api/v1/boms/1/publish")).andExpect(status().isForbidden());mvc.perform(post("/api/v1/attachments/1/versions")).andExpect(status().isForbidden());mvc.perform(get("/api/v1/pilot/tasks")).andExpect(status().isOk());}
 @Test void allObjectDomesticGrantsDoNotBypassCustomPublishPermission()throws Exception{role="domestic";allObjects=true;permissions=List.of("product:view","project:view","file:read","bom:write","documents:write");mvc.perform(post("/api/v1/boms/1/publish")).andExpect(status().isForbidden());mvc.perform(post("/api/v1/attachments/1/release")).andExpect(status().isForbidden());mvc.perform(post("/api/v1/attachments/1/versions")).andExpect(status().isOk());}
 @Test void financialActionsRemainIndependentAndLegacyUsersDoNotInheritMoney()throws Exception{role="finance";allObjects=true;permissions=List.of("finance:confirm");mvc.perform(get("/api/v1/development/budgets")).andExpect(status().isForbidden());mvc.perform(post("/api/v1/development/budgets/1/confirm")).andExpect(status().isOk());mvc.perform(get("/api/v1/development/export")).andExpect(status().isForbidden());pilot=false;mvc.perform(get("/api/v1/projects/1/cost-summary")).andExpect(status().isForbidden());mvc.perform(get("/api/v1/collaboration-plans")).andExpect(status().isOk());}
 @Test void assignedDomesticAccountsCannotUseUnscopedLegacyCollections()throws Exception{role="domestic";permissions=List.of("project:view","product:view");mvc.perform(get("/api/v1/projects")).andExpect(status().isForbidden());mvc.perform(get("/api/v1/projects/1")).andExpect(status().isOk());mvc.perform(get("/api/v1/projects/2")).andExpect(status().isForbidden());mvc.perform(get("/api/v1/boms/1")).andExpect(status().isOk());mvc.perform(get("/api/v1/boms/2")).andExpect(status().isForbidden());verify(jdbc).queryForObject(contains("from plm_product_bom"),eq(Long.class),eq(1L));}
 @Test void oldBomDtoAndUnchangedMoneyPatchesCannotBypassIndependentFinanceWrite()throws Exception{
  role="domestic";permissions=List.of("product:view","bom:write","collaboration:view");
  mvc.perform(post("/api/v1/boms/1/items").contentType("application/json").content("{\"itemName\":\"PC\",\"unitCost\":99}")).andExpect(status().isForbidden());
  mvc.perform(post("/api/v1/boms/1/items").contentType("application/json").content("{\"itemName\":\"PC\",\"unitCost\":0}")).andExpect(status().isForbidden());
  mvc.perform(post("/api/v1/boms/1/costs/recalculate").contentType("application/json").content("[]")).andExpect(status().isForbidden());
  mvc.perform(post("/api/v1/collaboration-plans/items/1/patch").contentType("application/json").content("{\"changes\":[{\"field\":\"unitCost\",\"before\":8,\"after\":8}]}")).andExpect(status().isForbidden());
  mvc.perform(post("/api/v1/boms/1/items").contentType("application/json").content("{\"itemName\":\"PC\",\"quantity\":2,\"unitCost\":null}")).andExpect(status().isOk());
  mvc.perform(post("/api/v1/collaboration-plans/items/1/patch").contentType("application/json").content("{\"phonePrice\":1999,\"priceCurrency\":\"MXN\",\"changes\":[{\"field\":\"phonePrice\",\"after\":1999}]}")).andExpect(status().isOk()).andExpect(jsonPath("$.phonePrice").value(1999)).andExpect(jsonPath("$.priceCurrency").value("MXN"));
  pilot=false;mvc.perform(post("/api/v1/boms/1/items").contentType("application/json").content("{\"itemName\":\"PC\",\"unitCost\":99}")).andExpect(status().isForbidden());
 }
 @Test void scopeSqlRejectsUntrustedIdentifiersAndFileAuthorizationDoesNotInherit(){assertThat(access.visibleSqlClause("file","a.attachment_id")).contains("entity_type='file'").doesNotContain("plm_collaboration_item_project");assertThat(access.visibleSqlClause("mold","ms.mold_set_id")).contains("entity_type='item'");assertThatThrownBy(()->access.visibleSqlClause("mold","id);drop table sys_user")).isInstanceOf(IllegalArgumentException.class);}
 @Test void legacyNestedMoneyIsRemovedWithoutHidingOperationalFields(){var node=json.createObjectNode();node.put("styleName","A");node.put("phonePrice",1999);node.put("priceCurrency","MXN");node.putObject("detail").put("unitCost",99).put("amount",8).put("status","making");PilotMoneyResponseAdvice.redact(node);assertThat(node.path("detail").has("unitCost")).isFalse();assertThat(node.path("detail").has("amount")).isFalse();assertThat(node.path("detail").path("status").asText()).isEqualTo("making");assertThat(node.path("phonePrice").asInt()).isEqualTo(1999);assertThat(node.path("priceCurrency").asText()).isEqualTo("MXN");}
 @Test void ssoMissingConfigurationAndUnmappedUsersNeverCreateSessions(){var tokens=mock(TokenSessionService.class);var sso=new PilotDingTalkSsoService(jdbc,json,tokens,access);assertThatThrownBy(()->sso.login("temporary-code")).isInstanceOf(BusinessException.class).hasMessageContaining("尚未配置");when(jdbc.queryForList(anyString(),eq("unmapped"))).thenReturn(List.of());assertThatThrownBy(()->sso.mappedSession("unmapped")).isInstanceOf(BusinessException.class).hasMessageContaining("未关联");verifyNoInteractions(tokens);}
}
