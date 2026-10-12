package com.yuewei.plm.module.code.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.module.code.repository.CodeItemRepository;
import java.io.ByteArrayOutputStream;
import java.util.List;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class CodeItemImportServiceTest {
    private CodeItemRepository repository;
    private CodeItemImportService service;

    @BeforeEach
    void setUp() {
        repository = mock(CodeItemRepository.class);
        service = new CodeItemImportService(repository);
    }

    @Test
    void previewsBusinessHeaderAndPreservesLeadingZero() throws Exception {
        when(repository.selectList(any(Wrapper.class))).thenReturn(List.of());

        var result = service.preview("colors.xlsx", workbook(
            new String[] {"01", "Morado", "Enabled", "2026-06-18"},
            new String[] {"02", "Negro", "Enabled", "2026-06-18"}));

        assertThat(result.getCreateCount()).isEqualTo(2);
        assertThat(result.getRows()).extracting("codeValue").containsExactly("01", "02");
        assertThat(result.getRows()).extracting("status").containsOnly("enabled");
    }

    @Test
    void commitTokenCanOnlyBeUsedOnce() throws Exception {
        when(repository.selectList(any(Wrapper.class))).thenReturn(List.of());
        var preview = service.preview("colors.xlsx", workbook(
            new String[] {"01", "Morado", "Enabled", "2026-06-18"}));

        var committed = service.commit(preview.getImportToken());

        assertThat(committed.getCommittedCount()).isEqualTo(1);
        assertThatThrownBy(() -> service.commit(preview.getImportToken()))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("不存在、已过期或已提交");
    }

    @Test
    void previewsChineseWorkbookAndMapsEnabledStatus() throws Exception {
        when(repository.selectList(any(Wrapper.class))).thenReturn(List.of());

        var result = service.preview("颜色编码.xlsx", workbook(
            "颜色编码",
            new String[] {"63", "Navy", "启用", "2026-08-04"},
            new String[] {"64", "Light Pink", "启用", "2026-08-04"}));

        assertThat(result.getCreateCount()).isEqualTo(2);
        assertThat(result.getRows()).extracting("codeValue").containsExactly("63", "64");
        assertThat(result.getRows()).extracting("codeNameZh").containsExactly("Navy", "Light Pink");
        assertThat(result.getRows()).extracting("status").containsOnly("enabled");
    }

    private byte[] workbook(String[]... values) throws Exception {
        return workbook("Códigos de color", values);
    }

    private byte[] workbook(String sheetName, String[]... values) throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet(sheetName);
            for (int index = 0; index < 5; index++) sheet.createRow(index);
            var header = sheet.createRow(5);
            if ("颜色编码".equals(sheetName)) {
                header.createCell(0).setCellValue("颜色编码");
                header.createCell(1).setCellValue("颜色名称");
                header.createCell(2).setCellValue("状态");
                header.createCell(3).setCellValue("更新时间");
            } else {
                header.createCell(0).setCellValue("Código color");
                header.createCell(1).setCellValue("Nombre color");
                header.createCell(2).setCellValue("Estado");
                header.createCell(3).setCellValue("Actualizado");
            }
            for (int rowIndex = 0; rowIndex < values.length; rowIndex++) {
                var row = sheet.createRow(rowIndex + 6);
                for (int column = 0; column < values[rowIndex].length; column++) {
                    row.createCell(column).setCellValue(values[rowIndex][column]);
                }
            }
            workbook.write(output);
            return output.toByteArray();
        }
    }
}
