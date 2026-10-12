package com.yuewei.plm.module.integration.dingtalk;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkModelVariantReceiveDTO;
import com.yuewei.plm.module.integration.dingtalk.service.MoldCodeIntakeService;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;

class MoldCodeIntakeServiceTest {
    @Test
    void createsDraftToolingInventoryWhenMoldCodeDoesNotExist() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        when(jdbcTemplate.queryForObject(
            eq("select inventory_id from plm_inventory where inventory_code = ? and deleted_flag = 0"),
            eq(Long.class),
            eq("MFA101291")
        )).thenThrow(new EmptyResultDataAccessException(1));
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class),
            eq("MFA101291"), anyString(), eq(9L), eq("10/1291"), anyString(), anyString(), eq("tester"), eq("tester")))
            .thenReturn(88L);

        MoldCodeIntakeService service = new MoldCodeIntakeService(jdbcTemplate, new ProductBusinessCodeGenerator());
        List<?> matches = service.sync(receive(), parent(), project());

        assertThat(matches).hasSize(1);
        assertThat(matches.get(0)).hasFieldOrPropertyWithValue("moldCode", "MFA101291")
            .hasFieldOrPropertyWithValue("matchStatus", "created_draft")
            .hasFieldOrPropertyWithValue("inventoryId", 88L);
    }

    @Test
    void infersMoldCodePartsWhenOnlyMoldCodesAreProvided() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        when(jdbcTemplate.queryForObject(
            eq("select inventory_id from plm_inventory where inventory_code = ? and deleted_flag = 0"),
            eq(Long.class),
            eq("MFA101291")
        )).thenReturn(77L);
        when(jdbcTemplate.queryForObject(
            eq("select inventory_id from plm_inventory where inventory_code = ? and deleted_flag = 0"),
            eq(Long.class),
            eq("MFA201291")
        )).thenReturn(78L);

        MoldCodeIntakeService service = new MoldCodeIntakeService(jdbcTemplate, new ProductBusinessCodeGenerator());
        DingTalkModelVariantReceiveDTO dto = receive();
        dto.setProductSpecificCode(null);
        dto.setPhoneModelCode(null);
        dto.setMaterialCodes(null);
        dto.setMoldCodes("generated:MFA101291 / MFA201291");

        List<?> matches = service.sync(dto, parent(), project());

        assertThat(matches).hasSize(2);
        assertThat(dto.getProductSpecificCode()).isEqualTo("FA");
        assertThat(dto.getPhoneModelCode()).isEqualTo("1291");
        assertThat(dto.getMaterialCodes()).containsExactly("10", "20");
        assertThat(dto.getMoldCodes()).isEqualTo("MFA101291\nMFA201291");
    }

    @Test
    void keepsEmptyWhenSourceDoesNotProvideMoldCodes() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        MoldCodeIntakeService service = new MoldCodeIntakeService(jdbcTemplate, new ProductBusinessCodeGenerator());
        DingTalkModelVariantReceiveDTO dto = receive();
        dto.setMoldCodes(null);

        List<?> matches = service.sync(dto, parent(), project());

        assertThat(matches).isEmpty();
        verifyNoInteractions(jdbcTemplate);
    }

    private DingTalkModelVariantReceiveDTO receive() {
        DingTalkModelVariantReceiveDTO dto = new DingTalkModelVariantReceiveDTO();
        dto.setDingTalkApprovalNo("DT-001");
        dto.setProductSpecificCode("FA");
        dto.setPhoneModelCode("1291");
        dto.setMaterialCodes(List.of("10"));
        dto.setMoldCodes("MFA101291");
        dto.setCreatedBy("tester");
        return dto;
    }

    private Product parent() {
        Product value = new Product();
        value.setProductId(5L);
        value.setProductName("幻影");
        return value;
    }

    private Product project() {
        Product value = new Product();
        value.setProductId(9L);
        value.setModel("Xiaomi Redmi A7 Pro");
        return value;
    }
}
