package com.yuewei.plm.module.code.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.never;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.code.dto.CodeItemSaveDTO;
import com.yuewei.plm.module.code.dto.CodeItemQueryDTO;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.repository.CodeItemRepository;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class CodeItemServiceTest {
    private CodeItemRepository repository;
    private CodeItemService service;

    @BeforeEach
    void setUp() {
        repository = mock(CodeItemRepository.class);
        service = new CodeItemService(repository);
    }

    @Test
    void createPreservesLeadingZero() {
        when(repository.selectCount(any(Wrapper.class))).thenReturn(0L);
        CodeItemSaveDTO dto = new CodeItemSaveDTO();
        dto.setCodeType("color");
        dto.setCodeValue("02");
        dto.setCodeName("Negro");
        dto.setSortOrder(2);

        var created = service.create(dto);

        assertThat(created.getCodeValue()).isEqualTo("02");
        verify(repository).insert(any(CodeItem.class));
    }

    @Test
    void pageAllowsStatusToBeOmitted() {
        when(repository.selectPage(any(Page.class), any(Wrapper.class))).thenReturn(new Page<>());
        CodeItemQueryDTO query = new CodeItemQueryDTO();

        var result = service.page(query);

        assertThat(result.getContent()).isEmpty();
    }

    @Test
    void createRejectsDuplicateWithinType() {
        when(repository.selectCount(any(Wrapper.class))).thenReturn(1L);
        CodeItemSaveDTO dto = new CodeItemSaveDTO();
        dto.setCodeType("color");
        dto.setCodeValue("02");
        dto.setCodeName("Negro");
        dto.setSortOrder(2);

        assertThatThrownBy(() -> service.create(dto))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("编码已存在");
    }

    @Test
    void changeStatusKeepsItemQueryable() {
        CodeItem item = new CodeItem();
        item.setCodeItemId(2L);
        item.setCodeType("color");
        item.setCodeValue("02");
        item.setCodeName("Negro");
        item.setStatus("enabled");
        item.setSortOrder(2);
        item.setDeletedFlag(0);
        when(repository.selectById(2L)).thenReturn(item);

        var disabled = service.changeStatus(2L, "disabled");

        assertThat(disabled.getStatus()).isEqualTo("disabled");
        assertThat(item.getDeletedFlag()).isZero();
        verify(repository).updateById(item);
    }

    @Test
    void phoneCodeIsFourDigitStringAndNameIsTrimmed() {
        CodeItemSaveDTO dto = phone("0001", "  Apple iPhone 16  ");
        var result = service.create(dto);
        assertThat(result.getCodeType()).isEqualTo("phone_model");
        assertThat(result.getCodeValue()).isEqualTo("0001");
        assertThat(result.getCodeName()).isEqualTo("Apple iPhone 16");
    }

    @Test
    void phoneRejectsInvalidLengthsAndNonDigits() {
        for (String value : new String[]{"1", "001", "00001", "00a1", "０００１"})
            assertThatThrownBy(() -> service.create(phone(value, "Model")))
                .isInstanceOf(BusinessException.class).hasMessageContaining("四位数字");
        verify(repository, never()).insert(any(CodeItem.class));
    }

    @Test
    void phoneNameIsUniqueEvenWhenCodeIsDifferentOrRecordIsDisabled() {
        when(repository.selectCount(any(Wrapper.class))).thenReturn(1L);
        assertThatThrownBy(() -> service.create(phone("0001", " apple IPHONE 16 ")))
            .isInstanceOf(BusinessException.class).hasMessageContaining("手机型号名称已存在");
    }

    @Test
    void phoneCodeAndTypeAreImmutableButNameCanBeEdited() {
        CodeItem item = new CodeItem();
        item.setCodeItemId(12L); item.setCodeType("phone_model"); item.setCodeValue("0001");
        item.setCodeName("Before"); item.setDeletedFlag(0); item.setStatus("disabled");
        when(repository.selectById(12L)).thenReturn(item);
        assertThatThrownBy(() -> service.update(12L, phone("0002", "After"))).hasMessageContaining("不可修改");
        var updated = service.update(12L, phone("0001", " After "));
        assertThat(updated.getCodeValue()).isEqualTo("0001");
        assertThat(updated.getCodeName()).isEqualTo("After");
        assertThat(updated.getStatus()).isEqualTo("disabled");
    }

    @Test
    void databaseUniquenessRaceIsReportedAsBusinessConflict() {
        org.mockito.Mockito.doThrow(new org.springframework.dao.DuplicateKeyException("duplicate"))
            .when(repository).insert(any(CodeItem.class));
        assertThatThrownBy(() -> service.create(phone("0001", "Model")))
            .isInstanceOf(BusinessException.class).hasMessageContaining("手机型号编码或名称已存在");
    }

    @Test
    void phoneCodesCannotBeUsedAsColors() {
        CodeItem item = new CodeItem(); item.setCodeType("phone_model"); item.setCodeValue("0001"); item.setDeletedFlag(0);
        when(repository.selectById(12L)).thenReturn(item);
        assertThatThrownBy(() -> service.requireEnabledColor(12L, "0001")).hasMessageContaining("颜色编码不存在");
    }

    private CodeItemSaveDTO phone(String value, String name) {
        CodeItemSaveDTO dto = new CodeItemSaveDTO();
        dto.setCodeType("phone_model"); dto.setCodeValue(value); dto.setCodeName(name); dto.setSortOrder(0);
        return dto;
    }
}
