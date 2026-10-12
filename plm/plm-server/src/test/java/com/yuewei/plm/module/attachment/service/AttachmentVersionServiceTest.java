package com.yuewei.plm.module.attachment.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.security.CurrentUser;
import com.yuewei.plm.module.attachment.entity.Attachment;
import com.yuewei.plm.module.attachment.repository.AttachmentRepository;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.pilot.PilotAccessService;
import java.time.LocalDateTime;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AttachmentVersionServiceTest {
    final AttachmentService storage=mock(AttachmentService.class);
    final AttachmentRepository files=mock(AttachmentRepository.class);
    final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    final PilotAccessService access=mock(PilotAccessService.class);
    final OperationLogService logs=mock(OperationLogService.class);
    final AttachmentVersionService service=new AttachmentVersionService(storage,files,jdbc,access,logs,new ObjectMapper().findAndRegisterModules());
    Attachment file(long id,String ext){var a=new Attachment();a.setAttachmentId(id);a.setOwnerObjectId(10L);a.setOwnerObjectType("Product");a.setFileExt(ext);a.setVersionNo("V1");a.setDeletedFlag(0);a.setStatus("draft");a.setCreatedAt(LocalDateTime.now());when(files.selectById(id)).thenReturn(a);return a;}
    void actor(){when(access.actor()).thenReturn(new CurrentUser(3L,"engineer","真实工程账号",false));when(access.actorId()).thenReturn(3L);}
    @Test void publicationRetainsImmutableVersionAndRealPublisherWithoutCopyingBinary() {
        actor();var a=file(1,"pdf");var dto=new AttachmentVersionService.Publication("完成核对",null,null,null);
        assertThat(service.publish(1,dto,null).getReleasedBy()).isEqualTo("engineer");
        assertThat(a.getReleasedByUserId()).isEqualTo(3L);assertThat(a.getFamilyId()).isEqualTo(1L);
        assertThat(service.publish(1,dto,null).getReleasedAt()).isEqualTo(a.getReleasedAt());
        assertThatThrownBy(()->service.publish(1,new AttachmentVersionService.Publication("覆盖历史",null,null,null),null)).isInstanceOf(BusinessException.class).hasMessageContaining("固定");
        verify(files,times(1)).updateById(a);verify(logs,times(1)).logSuccess(any());verifyNoInteractions(storage);
        verify(jdbc,times(3)).queryForList(contains("for update"),eq(1L));
    }
    @Test void cadRequiresAnExplicitPdfAndRejectsAnotherProjectsDerivative() {
        actor();file(1,"step");var pdf=file(2,"pdf");
        assertThatThrownBy(()->service.publish(1,new AttachmentVersionService.Publication("确认",null,null,null),null)).hasMessageContaining("PDF");
        pdf.setOwnerObjectId(20L);
        assertThatThrownBy(()->service.publish(1,new AttachmentVersionService.Publication("确认",null,null,2L),null)).hasMessageContaining("同项目");
        verify(files,never()).updateById(any(Attachment.class));
        pdf.setOwnerObjectId(10L);assertThat(service.publish(1,new AttachmentVersionService.Publication("确认",null,null,2L),null).getDerivedPdfAttachmentId()).isEqualTo(2L);
    }
    @Test void authorizationAndAssociationValidationRunBeforePublication() {
        file(1,"pdf");doThrow(new BusinessException(40103,"无发布权限")).when(access).requirePermission("documents:publish");
        assertThatThrownBy(()->service.publish(1,new AttachmentVersionService.Publication("确认",null,null,null),null)).hasMessageContaining("权限");verifyNoInteractions(jdbc,logs);verify(files,never()).selectById(anyLong());
        doNothing().when(access).requirePermission("documents:publish");
        when(jdbc.queryForObject(anyString(),eq(Boolean.class),any(),any(),any())).thenReturn(false);
        assertThatThrownBy(()->service.publish(1,new AttachmentVersionService.Publication("确认",99L,null,null),null)).hasMessageContaining("不一致");verify(files,never()).updateById(any(Attachment.class));
    }
    @Test void versionHistoryUsesOneScopedBatchAndDuplicateVersionNeverUploads() {
        var a=file(1,"pdf");when(access.visibleSqlClause("file","a.attachment_id")).thenReturn("false");
        when(jdbc.queryForList(anyString(),eq(Long.class),eq(1L),eq(1L))).thenReturn(List.of(1L,2L));
        var b=file(2,"pdf");when(files.selectBatchIds(List.of(1L,2L))).thenReturn(List.of(a,b));
        assertThat(service.versions(1)).hasSize(2);verify(files).selectBatchIds(List.of(1L,2L));
        when(jdbc.queryForObject(anyString(),eq(Boolean.class),eq("V1"),eq(1L),eq(1L))).thenReturn(true);
        assertThatThrownBy(()->service.upload(1,null,"V1","更正",null)).hasMessageContaining("重复");verifyNoInteractions(storage);
    }
}
