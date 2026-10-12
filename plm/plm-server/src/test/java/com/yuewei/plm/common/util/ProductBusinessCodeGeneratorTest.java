package com.yuewei.plm.common.util;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.yuewei.plm.common.exception.BusinessException;
import java.util.List;
import org.junit.jupiter.api.Test;

class ProductBusinessCodeGeneratorTest {
    private final ProductBusinessCodeGenerator generator = new ProductBusinessCodeGenerator();

    @Test
    void generatesMoldAndProductStateCodes() {
        assertThat(generator.generateMoldCode("FA", "10", "1291")).isEqualTo("MFA101291");
        assertThat(generator.generateProductLineCode("FA", "4020")).isEqualTo("NFA4020");
        assertThat(generator.generateProductStateCode("FA", "4030", "1291", "01")).isEqualTo("NFA4030129101");
        assertThat(generator.isFinishedProductCode("4030")).isTrue();
    }

    @Test
    void parsesProductStateCodeAndDetectsFinishedProductByFinalOperation() {
        ProductBusinessCodeGenerator.ProductStateCodeParts parts = generator.parseProductStateCode("NFA4030129101");

        assertThat(parts.productSpecificCode()).isEqualTo("FA");
        assertThat(parts.operationCode()).isEqualTo("4030");
        assertThat(parts.phoneModelCode()).isEqualTo("1291");
        assertThat(parts.colorCode()).isEqualTo("01");
        assertThat(parts.finishedProduct()).isTrue();
        assertThat(generator.isFinishedProductCode("NFA4030129101")).isTrue();
        assertThat(generator.isFinishedProductCode("NFA1020129101")).isFalse();
    }

    @Test
    void parsesIncomingMoldCodeAgainstExpectedFields() {
        ProductBusinessCodeGenerator.MoldCodeParts parts = generator.parseMoldCode(
            "MFA101291",
            "FA",
            List.of("10", "20"),
            "1291"
        );

        assertThat(parts.productSpecificCode()).isEqualTo("FA");
        assertThat(parts.materialCode()).isEqualTo("10");
        assertThat(parts.phoneModelCode()).isEqualTo("1291");
        assertThat(parts.expectedMoldCode()).isEqualTo("MFA101291");
    }

    @Test
    void parsesShortMoldCodeBySecondAndThirdCharacters() {
        ProductBusinessCodeGenerator.MoldCodeParts mba = generator.parseMoldCode("MBA10", "BA", List.of("10"), null);
        ProductBusinessCodeGenerator.MoldCodeParts llt = generator.parseMoldCode("LLT10", "LT", List.of("10"), null);

        assertThat(mba.moldCode()).isEqualTo("MBA10");
        assertThat(mba.productSpecificCode()).isEqualTo("BA");
        assertThat(mba.materialCode()).isEqualTo("10");
        assertThat(mba.expectedMoldCode()).isEqualTo("MBA10");
        assertThat(llt.moldCode()).isEqualTo("LLT10");
        assertThat(llt.productSpecificCode()).isEqualTo("LT");
        assertThat(llt.materialCode()).isEqualTo("10");
    }

    @Test
    void splitsEscapedNewlineMoldCodesFromDingTalkConnector() {
        assertThat(generator.splitCodes("MFA101291\\nMFA201291\\nLLT10"))
            .containsExactly("MFA101291", "MFA201291", "LLT10");
    }

    @Test
    void extractsMoldCodesFromDingTalkFormattedText() {
        assertThat(generator.splitCodes("生成的编码：MBA10、LLT10 / MFA301291"))
            .containsExactly("MBA10", "LLT10", "MFA301291");
    }

    @Test
    void rejectsMoldCodeWhenPhoneModelCodeDoesNotMatch() {
        assertThatThrownBy(() -> generator.parseMoldCode("MFA101292", "FA", List.of("10"), "1291"))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("手机型号编码");
    }
}
