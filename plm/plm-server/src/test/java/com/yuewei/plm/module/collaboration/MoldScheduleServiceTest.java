package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.pilot.PilotAccessService;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static com.yuewei.plm.module.collaboration.CollaborationTypes.*;

class MoldScheduleServiceTest {
    ObjectMapper json=new ObjectMapper();JdbcTemplate jdbc=mock(JdbcTemplate.class);CollaborationService collaboration=mock(CollaborationService.class);CollaborationRepository repository=mock(CollaborationRepository.class);PilotAccessService access=mock(PilotAccessService.class);
    MoldScheduleService service=new MoldScheduleService(jdbc,json,collaboration,repository,access,mock(PlatformTransactionManager.class));
    @Test void pageRequiresDomesticReadAndPassesTrustedScopeToTheExistingPageEngine() {
        var actor=new CurrentUser(1L,"real","real",false);when(collaboration.actor()).thenReturn(actor);when(collaboration.groups(actor)).thenReturn(Set.of("engineering"));when(access.visibleSqlClause("mold","s.mold_set_id")).thenReturn("s.mold_set_id=7");when(repository.page(any(),eq(Set.of("engineering")),eq("s.mold_set_id=7"))).thenReturn(new PageVO<>(List.of(),1,50,0,0));
        assertThat(service.page(new MoldScheduleTypes.Query()).getContent()).isEmpty();verify(access).requireDomesticView();verify(access).requirePermission("schedule:read");verifyNoInteractions(jdbc);
    }
    @Test void externalAccountIsRejectedBeforeAnyFullLedgerRead() {
        doThrow(new BusinessException(40103,"仅手机任务")).when(access).requireDomesticView();assertThatThrownBy(()->service.page(new MoldScheduleTypes.Query())).hasMessageContaining("手机任务");verifyNoInteractions(repository,jdbc);
    }
    @Test void saveReusesTheSingleOriginalValueConflictAndAuditEngine() {
        var patch=new RowPatch("mold_set",7,List.of(new CellChange("forecastFactoryDate",json.nullNode(),json.valueToTree("2026-10-20"),"预测更新")));
        var dto=new BatchSave(List.of(patch));var result=new RowResult("mold_set",7,"conflict","原值冲突",List.of(),null);when(collaboration.save(dto,null)).thenReturn(List.of(result));assertThat(service.save(dto,null)).containsExactly(result);verify(access).requireMold(7);verify(collaboration).save(dto,null);verifyNoInteractions(jdbc);
    }
    @Test void mobileActionAllowlistRejectsWrongColumnsAndKeepsArrivalSeparateFromShipping() {
        var bad=new RowPatch("mold_set",7,List.of(new CellChange("plannedMoldDeliveryDate",json.nullNode(),json.valueToTree("2026-10-20"),null)));assertThatThrownBy(()->service.saveScopedTask("arrival",bad,null)).isInstanceOf(BusinessException.class).hasMessageContaining("未授权字段");verify(collaboration,never()).save(any(),any());
        var good=new RowPatch("mold_set",7,List.of(new CellChange("pcSignedDate",json.nullNode(),json.valueToTree("2026-10-20"),null)));when(collaboration.save(any(),any())).thenReturn(List.of(new RowResult("mold_set",7,"saved","saved",List.of(),null)));assertThat(service.saveScopedTask("arrival",good,null).status()).isEqualTo("saved");verify(access,times(2)).requirePermission("task:arrival");
    }
    @Test void trustedAutomaticReminderGenerationDoesNotFabricateALoginOrInvokeExternalDelivery() {
        when(jdbc.queryForObject(anyString(),eq(Long.class),any(Object[].class))).thenReturn(0L);
        assertThat(service.enqueueAutomaticReminders()).containsEntry("created",0).containsEntry("externalSent",0).containsEntry("externalEnabled",false);
        verifyNoInteractions(access,collaboration,repository);
    }
}
