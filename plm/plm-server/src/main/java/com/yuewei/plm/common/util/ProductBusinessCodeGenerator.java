package com.yuewei.plm.common.util;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

@Component
public class ProductBusinessCodeGenerator {
    public static final String MOLD_PREFIX = "M";
    public static final String PRODUCT_STATE_PREFIX = "N";
    public static final String DEFAULT_FINAL_OPERATION_CODE = "4030";
    private static final Pattern MOLD_CODE_PATTERN = Pattern.compile("(?i)(?<![A-Z0-9_-])[A-Z]{3}\\d{2,}(?![A-Z0-9_-])");

    public String generateMoldCode(String productSpecificCode, String materialCode, String phoneModelCode) {
        String product = requiredCode(productSpecificCode, "产品特定编码不能为空");
        String material = requiredCode(materialCode, "材质编码不能为空");
        String phone = requiredCode(phoneModelCode, "手机型号编码不能为空");
        return MOLD_PREFIX + product + material + phone;
    }

    public String generateProductStateCode(String productSpecificCode, String operationCode,
                                           String phoneModelCode, String colorCode) {
        String product = requiredCode(productSpecificCode, "产品特定编码不能为空");
        String operation = requiredCode(operationCode, "工序编码不能为空");
        String phone = requiredCode(phoneModelCode, "手机型号编码不能为空");
        String color = requiredCode(colorCode, "颜色编码不能为空");
        return PRODUCT_STATE_PREFIX + product + operation + phone + color;
    }

    public String generateProductLineCode(String productSpecificCode, String operationCode) {
        String product = requiredCode(productSpecificCode, "产品特定编码不能为空");
        String operation = requiredCode(operationCode, "工序编码不能为空");
        return PRODUCT_STATE_PREFIX + product + operation;
    }

    public ProductStateCodeParts parseProductStateCode(String productStateCode) {
        String code = requiredCode(productStateCode, "产品状态编码不能为空");
        if (!code.startsWith(PRODUCT_STATE_PREFIX)) {
            throw validation("产品状态编码必须以 N 开头");
        }
        String body = code.substring(PRODUCT_STATE_PREFIX.length());
        if (body.length() < 12) {
            throw validation("产品状态编码长度不正确: " + code);
        }
        String colorCode = body.substring(body.length() - 2);
        String phoneModelCode = body.substring(body.length() - 6, body.length() - 2);
        String operationCode = body.substring(body.length() - 10, body.length() - 6);
        String productSpecificCode = body.substring(0, body.length() - 10);
        if (!StringUtils.hasText(productSpecificCode)) {
            throw validation("产品状态编码缺少产品特定编码: " + code);
        }
        String expected = generateProductStateCode(productSpecificCode, operationCode, phoneModelCode, colorCode);
        if (!Objects.equals(expected, code)) {
            throw validation("产品状态编码与系统规则不一致: " + code);
        }
        return new ProductStateCodeParts(
            code,
            productSpecificCode,
            operationCode,
            phoneModelCode,
            colorCode,
            DEFAULT_FINAL_OPERATION_CODE.equals(operationCode),
            expected
        );
    }

    public boolean isFinishedProductCode(String code) {
        String normalized = requiredCode(code, "工序编码不能为空");
        if (normalized.startsWith(PRODUCT_STATE_PREFIX)) {
            return parseProductStateCode(normalized).finishedProduct();
        }
        return DEFAULT_FINAL_OPERATION_CODE.equals(normalized);
    }

    public List<String> splitCodes(String value) {
        if (!StringUtils.hasText(value)) {
            return List.of();
        }
        Set<String> codes = new LinkedHashSet<>();
        value = value
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\r", "\n")
            .replace("\\t", "\t");
        Matcher matcher = MOLD_CODE_PATTERN.matcher(value);
        while (matcher.find()) {
            String code = normalizeCode(matcher.group());
            if (StringUtils.hasText(code)) {
                codes.add(code);
            }
        }
        return new ArrayList<>(codes);
    }

    public MoldCodeParts parseMoldCode(String moldCode, String expectedProductSpecificCode,
                                       List<String> expectedMaterialCodes, String expectedPhoneModelCode) {
        String code = requiredCode(moldCode, "模具编码不能为空");
        if (code.length() < 3) {
            throw validation("模具编码长度不足，无法提取产品本身特征编码: " + code);
        }

        String productSpecificCode = normalizeCode(code.substring(1, 3));
        if (StringUtils.hasText(expectedProductSpecificCode)
            && !Objects.equals(productSpecificCode, normalizeCode(expectedProductSpecificCode))) {
            throw validation("模具编码产品特定编码与钉钉字段不一致: " + code);
        }
        String phoneModelCode = resolvePhoneModelCode(code, expectedPhoneModelCode);
        String materialCode = resolveMaterialCode(code, phoneModelCode, expectedMaterialCodes);
        return new MoldCodeParts(code, productSpecificCode, materialCode, phoneModelCode, code);
    }

    private String resolvePhoneModelCode(String code, String expectedPhoneModelCode) {
        if (StringUtils.hasText(expectedPhoneModelCode)) {
            String expected = normalizeCode(expectedPhoneModelCode);
            if (!code.endsWith(expected)) {
                throw validation("模具编码手机型号编码与钉钉字段不一致: " + code);
            }
            return expected;
        }
        if (code.length() > 5) {
            return code.substring(5);
        }
        return null;
    }

    private String resolveMaterialCode(String code, String phoneModelCode, List<String> expectedMaterialCodes) {
        String afterProductSpecificCode = code.substring(3);
        String materialSegment = StringUtils.hasText(phoneModelCode) && afterProductSpecificCode.endsWith(phoneModelCode)
            ? afterProductSpecificCode.substring(0, afterProductSpecificCode.length() - phoneModelCode.length())
            : afterProductSpecificCode;
        List<String> materials = expectedMaterialCodes == null ? List.of() : expectedMaterialCodes.stream()
            .map(this::normalizeCode)
            .filter(StringUtils::hasText)
            .distinct()
            .sorted((left, right) -> Integer.compare(right.length(), left.length()))
            .toList();
        for (String material : materials) {
            if (materialSegment.startsWith(material)) {
                return material;
            }
        }
        if (!materials.isEmpty()) {
            throw validation("模具编码材质编码不在钉钉传入材质范围内: " + code);
        }
        if (materialSegment.length() >= 2) {
            return materialSegment.substring(0, 2);
        }
        return null;
    }

    private String requiredCode(String value, String message) {
        String normalized = normalizeCode(value);
        if (!StringUtils.hasText(normalized)) {
            throw validation(message);
        }
        if (!normalized.matches("[A-Z0-9_-]+")) {
            throw validation(message.replace("不能为空", "格式错误"));
        }
        return normalized;
    }

    private String normalizeCode(String value) {
        return StringUtils.hasText(value) ? value.trim().toUpperCase(Locale.ROOT) : null;
    }

    private BusinessException validation(String message) {
        return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, message);
    }

    public record MoldCodeParts(String moldCode, String productSpecificCode, String materialCode,
                                String phoneModelCode, String expectedMoldCode) {}

    public record ProductStateCodeParts(String productStateCode, String productSpecificCode, String operationCode,
                                        String phoneModelCode, String colorCode, boolean finishedProduct,
                                        String expectedProductStateCode) {}
}
