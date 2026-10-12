package com.yuewei.plm.module.process.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.process.dto.ProcessOperationMasterSaveDTO;
import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.module.process.repository.ProcessRepository;
import com.yuewei.plm.module.process.vo.ProcessOperationMasterVO;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

class ProcessOperationMasterServiceImplTest {

    @Test
    void createOperationMasterStoresProcessMetadataAndReturnsDraftMaster() {
        ProcessRepository processRepository = mock(ProcessRepository.class);
        AtomicLong idSequence = new AtomicLong(900L);
        List<ProcessEntity> inserted = new ArrayList<>();
        when(processRepository.insert(Mockito.any(ProcessEntity.class))).thenAnswer(invocation -> {
            ProcessEntity entity = invocation.getArgument(0);
            entity.setProcessId(idSequence.getAndIncrement());
            inserted.add(entity);
            return 1;
        });
        when(processRepository.selectById(900L)).thenAnswer(invocation -> inserted.get(0));
        ProcessOperationMasterServiceImpl service = new ProcessOperationMasterServiceImpl(
            processRepository,
            mock(OperationLogService.class),
            new ObjectMapper()
        );

        ProcessOperationMasterVO result = service.create(saveDTO());

        assertThat(result.getProcessId()).isEqualTo(900L);
        assertThat(result.getProcessCode()).isEqualTo("PROC_TEST_PRESS");
        assertThat(result.getProcessName()).isEqualTo("Test pressing");
        assertThat(result.getProcessCategory()).isEqualTo("assembly");
        assertThat(result.getOperationType()).isEqualTo("process");
        assertThat(result.getDefaultStandardTimeMins()).isEqualByComparingTo("8.50");
        assertThat(result.getDefaultQualityRequirement()).isEqualTo("No offset");
        assertThat(result.getStatus()).isEqualTo("draft");
        assertThat(inserted.get(0).getProductId()).isNull();
        assertThat(inserted.get(0).getProcessType()).isEqualTo("operation_master");
        assertThat(inserted.get(0).getProcessParamJson()).contains("assembly", "process", "defaultProcessParamJson");
    }

    @Test
    void listOperationMastersReadsOnlyOperationMasterRows() {
        ProcessRepository processRepository = mock(ProcessRepository.class);
        ProcessEntity master = new ProcessEntity();
        master.setProcessId(900L);
        master.setProcessCode("PROC_INJECTION");
        master.setProcessName("Injection molding");
        master.setProcessType("operation_master");
        master.setStatus("confirmed");
        master.setStandardTimeMins(new BigDecimal("12"));
        master.setQualityRequirement("No burrs");
        master.setProcessParamJson("{\"processCategory\":\"forming\",\"operationType\":\"process\"}");
        master.setDeletedFlag(0);
        when(processRepository.selectList(Mockito.<Wrapper<ProcessEntity>>any())).thenReturn(List.of(master));
        ProcessOperationMasterServiceImpl service = new ProcessOperationMasterServiceImpl(
            processRepository,
            mock(OperationLogService.class),
            new ObjectMapper()
        );

        List<ProcessOperationMasterVO> result = service.list(null, null, null, "confirmed");

        assertThat(result).hasSize(1);
        assertThat(result.get(0).getProcessCode()).isEqualTo("PROC_INJECTION");
        assertThat(result.get(0).getProcessCategory()).isEqualTo("forming");
        assertThat(result.get(0).getOperationType()).isEqualTo("process");
    }

    private ProcessOperationMasterSaveDTO saveDTO() {
        ProcessOperationMasterSaveDTO dto = new ProcessOperationMasterSaveDTO();
        dto.setProcessCode("PROC_TEST_PRESS");
        dto.setProcessName("Test pressing");
        dto.setProcessCategory("assembly");
        dto.setOperationType("process");
        dto.setDefaultStandardTimeMins(new BigDecimal("8.50"));
        dto.setDefaultQualityRequirement("No offset");
        dto.setDefaultProcessParamJson("{\"pressure\":30}");
        dto.setNeedWorkstation(true);
        dto.setWorkstationType("station");
        dto.setRemark("for frontend direct test");
        return dto;
    }
}
