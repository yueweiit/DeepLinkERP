package com.yuewei.plm.module.project.service.impl;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.operationlog.service.OperationLogService;
import com.yuewei.plm.module.project.constant.TimelineNodeConstants;
import com.yuewei.plm.module.project.dto.MoldTransferExpressSaveDTO;
import com.yuewei.plm.module.project.entity.ProjectMoldTransferExpress;
import com.yuewei.plm.module.project.repository.ProjectMoldTransferExpressRepository;
import com.yuewei.plm.module.project.service.TimelineDefinitionProvider;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDateTime;
import org.junit.jupiter.api.Test;

class MoldTransferExpressServiceImplTest {

    @Test
    void saveCreatesMoldTransferTrackingNoForMoldTransferNode() {
        ProductRepository productRepository = mock(ProductRepository.class);
        ProjectMoldTransferExpressRepository repository = mock(ProjectMoldTransferExpressRepository.class);
        LocalDateTime shippedAt = LocalDateTime.of(2026, 8, 10, 9, 30);
        when(productRepository.selectById(10L)).thenReturn(product(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE));
        when(repository.selectOne(any())).thenReturn(null);
        when(repository.insert(any(ProjectMoldTransferExpress.class))).thenAnswer(invocation -> {
            ProjectMoldTransferExpress entity = invocation.getArgument(0);
            entity.setMoldTransferExpressId(100L);
            return 1;
        });
        MoldTransferExpressServiceImpl service = service(productRepository, repository);
        MoldTransferExpressSaveDTO dto = new MoldTransferExpressSaveDTO();
        dto.setTrackingNo("JD014600006969760000");
        dto.setShippedAt(shippedAt);

        var result = service.save(10L, "PRODUCT_LINE_MOLD_TRANSFER", dto, null);

        assertThat(result.getMoldTransferExpressId()).isEqualTo(100L);
        assertThat(result.getTrackingNo()).isEqualTo("JD014600006969760000");
        assertThat(result.getShippedAt()).isEqualTo(shippedAt);
        verify(repository).insert(any(ProjectMoldTransferExpress.class));
    }

    @Test
    void saveRejectsNonMoldTransferNode() {
        ProductRepository productRepository = mock(ProductRepository.class);
        when(productRepository.selectById(10L)).thenReturn(product(TimelineNodeConstants.PRODUCT_TYPE_PRODUCT_LINE));
        MoldTransferExpressServiceImpl service = service(
            productRepository,
            mock(ProjectMoldTransferExpressRepository.class)
        );
        MoldTransferExpressSaveDTO dto = new MoldTransferExpressSaveDTO();
        dto.setTrackingNo("JD014600006969760000");

        assertThatThrownBy(() -> service.save(10L, "PRODUCT_LINE_INIT_CREATE", dto, null))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ErrorCodeConstants.VALIDATION_ERROR);
    }

    private MoldTransferExpressServiceImpl service(ProductRepository productRepository,
                                                   ProjectMoldTransferExpressRepository repository) {
        return new MoldTransferExpressServiceImpl(
            productRepository,
            new TimelineDefinitionProvider(),
            repository,
            mock(OperationLogService.class)
        );
    }

    private Product product(String productType) {
        Product product = new Product();
        product.setProductId(10L);
        product.setProductCode("PRD-CD30-0001");
        product.setProductName("超队 3.0");
        product.setProductType(productType);
        product.setDeletedFlag(0);
        return product;
    }

}
