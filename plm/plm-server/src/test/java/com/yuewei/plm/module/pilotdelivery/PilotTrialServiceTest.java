package com.yuewei.plm.module.pilotdelivery;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.pilot.PilotAccessService;
import java.time.LocalDate;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class PilotTrialServiceTest {
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    static class Source extends JdbcTemplate {
        final Map<String,Object> trial=new LinkedHashMap<>();final List<String> mutations=new ArrayList<>();long mexicoUsers=2;List<Long> represented=List.of(1L,2L,3L,4L,5L,6L,7L);
        Source(){trial.put("trial_id",3L);trial.put("name","Four week pilot");trial.put("platform_ids","[1,2,3,4,5,6,7]");trial.put("new_platform_id",8L);trial.put("project_ids","[9,10,11,12,13,14,15]");trial.put("status","preparing");trial.put("revision",1);trial.put("baseline","{\"moldLeadDays\":0,\"bomPushMinutes\":10,\"fileLookupMinutes\":5,\"communicationMinutes\":20}");}
        @Override public <T>List<T> queryForList(String sql,Class<T> type,Object...args){return represented.stream().map(type::cast).toList();}
        @Override public List<Map<String,Object>> queryForList(String sql,Object...args){return sql.contains("platform_ids::text")?List.of(new LinkedHashMap<>(trial)):List.of();}
        @Override public <T>T queryForObject(String sql,Class<T> type){return queryForObject(sql,type,new Object[]{});}
        @Override public <T>T queryForObject(String sql,Class<T> type,Object...args){Object result=sql.contains("role_code='mexico'")?mexicoUsers:type==Boolean.class?true:sql.contains("parent_product_id")?1L:3L;return type.cast(result);}
        @Override public int update(String sql,Object...args){mutations.add(sql);if(sql.contains("set status='active'")){trial.put("status","active");trial.put("started_on",args[0]);trial.put("review_on",args[1]);}if(sql.contains("plm_pilot_trial_history"))mutations.add(Objects.toString(args[2]));return 1;}
    }
    private PilotDeliveryQueue configured(){var queue=mock(PilotDeliveryQueue.class);when(queue.enabled()).thenReturn(true);when(queue.configured("erp_bom")).thenReturn(true);when(queue.expenseConfigured()).thenReturn(true);when(queue.configured("dingtalk_reminder")).thenReturn(true);return queue;}
    @Test void sevenOldPlatformsAndOneNewPlatformCannotBeDuplicatedOrExpanded() {
        var service=new PilotTrialService(new Source(),json,mock(PilotAccessService.class),configured());assertThatThrownBy(()->service.save(null,new PilotTrialService.Save("Trial",List.of(1L,2L,3L,4L,5L,6L,7L,8L),9L,List.of(),Map.of(),null,""))).hasMessageContaining("七");assertThatThrownBy(()->service.save(null,new PilotTrialService.Save("Trial",List.of(1L),1L,List.of(),Map.of(),null,""))).hasMessageContaining("重复");
        var missing=new Source();missing.represented=List.of(1L);assertThatThrownBy(()->new PilotTrialService(missing,json,mock(PilotAccessService.class),configured()).start(3,new PilotTrialService.Start(LocalDate.of(2026,10,12),true,true,true))).hasMessageContaining("均须选择真实衍生项目");assertThat(missing.mutations).isEmpty();
    }
    @Test void actualMexicoAccessAndExternalConfigurationArePrerequisitesNotDemoFlags() {
        var source=new Source();var service=new PilotTrialService(source,json,mock(PilotAccessService.class),configured());assertThatThrownBy(()->service.start(3,new PilotTrialService.Start(LocalDate.of(2026,10,12),false,true,true))).hasMessageContaining("真实访问");assertThat(source.mutations).isEmpty();var disabled=new PilotTrialService(source,json,mock(PilotAccessService.class),mock(PilotDeliveryQueue.class));assertThatThrownBy(()->disabled.start(3,new PilotTrialService.Start(LocalDate.of(2026,10,12),true,true,true))).hasMessageContaining("尚未启用");assertThat(source.mutations).isEmpty();var incomplete=configured();when(incomplete.expenseConfigured()).thenReturn(false);var missingExpenses=new PilotTrialService(source,json,mock(PilotAccessService.class),incomplete);assertThatThrownBy(()->missingExpenses.start(3,new PilotTrialService.Start(LocalDate.of(2026,10,12),true,true,true))).hasMessageContaining("ERP费用只读");assertThat(source.mutations).isEmpty();
    }
    @Test void unknownBaselineCannotBeZeroAndValidZeroStartsFourWeeksWithAdministratorAttestation() {
        var source=new Source();source.trial.put("baseline","{}");var service=new PilotTrialService(source,json,mock(PilotAccessService.class),configured());assertThatThrownBy(()->service.start(3,new PilotTrialService.Start(LocalDate.of(2026,10,12),true,true,true))).hasMessageContaining("基准");source.trial.put("baseline","{\"moldLeadDays\":0,\"bomPushMinutes\":0,\"fileLookupMinutes\":0,\"communicationMinutes\":0}");var result=service.start(3,new PilotTrialService.Start(LocalDate.of(2026,10,12),true,true,true));assertThat(result).containsEntry("status","active").containsEntry("review_on",LocalDate.of(2026,11,8));assertThat(source.mutations).anyMatch(s->s.contains("administratorAttestation"));
    }
    @Test void onlyTwoOrThreeActiveMexicoUsersCanStartAndAStartedTrialCannotExpand() {
        var source=new Source();source.mexicoUsers=1;var service=new PilotTrialService(source,json,mock(PilotAccessService.class),configured());assertThatThrownBy(()->service.start(3,new PilotTrialService.Start(LocalDate.of(2026,10,12),true,true,true))).hasMessageContaining("2至3");source.trial.put("status","active");assertThatThrownBy(()->service.save(3L,new PilotTrialService.Save("Trial",List.of(1L,2L,3L,4L,5L,6L,7L),8L,List.of(9L),Map.of(),1,"expand"))).hasMessageContaining("不能扩大");
    }
    @Test void freeformFinancialDataCannotLeakThroughBaselineMetrics() {
        var service=new PilotTrialService(new Source(),json,mock(PilotAccessService.class),configured());assertThatThrownBy(()->service.save(null,new PilotTrialService.Save("Trial",List.of(),null,List.of(),Map.of("actualCost",1000),null,""))).hasMessageContaining("不接受自由金额");
    }
    @Test void reviewRequiresRealEvidenceAndWrittenExtensionNeverExceedsTwoWeeks() {
        var source=new Source();source.trial.put("status","active");source.trial.put("started_on",LocalDate.of(2026,10,12));
        var service=new PilotTrialService(source,json,mock(PilotAccessService.class),configured());
        assertThatThrownBy(()->service.review(3,new PilotTrialService.Review(LocalDate.of(2026,11,23),"双方书面延期",Map.of(),"active"))).hasMessageContaining("最多两周");
        assertThatThrownBy(()->service.review(3,new PilotTrialService.Review(LocalDate.of(2026,11,8),"完成评审",Map.of("notes"," "),"passed"))).hasMessageContaining("真实业务");
        Map<String,Object> observed=new LinkedHashMap<>();observed.put("notes","真实工单与会议记录编号，尚未完成链路如实记录");observed.put("businessCount",0);observed.put("fileLookupMinutes",null);
        service.review(3,new PilotTrialService.Review(LocalDate.of(2026,11,8),"双方评审依据",observed,"failed"));
        assertThat(source.mutations).anyMatch(s->s.contains("\"businessCount\":0")&&s.contains("\"fileLookupMinutes\":null"));
        assertThatThrownBy(()->service.review(3,new PilotTrialService.Review(LocalDate.of(2026,11,8),"评审",Map.of("notes","真实记录","actualCost",1000),"passed"))).hasMessageContaining("自由金额");
    }
}
