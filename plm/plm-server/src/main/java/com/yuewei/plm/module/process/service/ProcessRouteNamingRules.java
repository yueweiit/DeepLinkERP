package com.yuewei.plm.module.process.service;

import com.yuewei.plm.module.process.entity.ProcessEntity;
import com.yuewei.plm.repository.entity.Product;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.springframework.util.StringUtils;

public final class ProcessRouteNamingRules {

    private static final String PRODUCT_TYPE_MODEL_VARIANT = "model_variant";
    private static final String LINE_CODE_PLACEHOLDER = "0000";
    private static final Pattern END_FOUR_DIGIT_GROUP = Pattern.compile("(\\d{4})\\D*$");

    private ProcessRouteNamingRules() {
    }

    public static String routeName(String baseName, Product product) {
        String normalizedName = StringUtils.hasText(baseName) ? baseName.trim() : "工艺路线";
        if (!isModelVariant(product) || !StringUtils.hasText(product.getModel())) {
            return normalizedName;
        }
        String model = product.getModel().trim();
        return normalizedName.contains(model) ? normalizedName : normalizedName + " - " + model;
    }

    public static String manualRouteCode(Product product, String routeTemplateCode, String versionNo) {
        String routeToken = sanitize(StringUtils.hasText(routeTemplateCode) ? routeTemplateCode : "CUSTOM", "CUSTOM");
        String version = sanitize(versionNo, "V1");
        if (!isModelVariant(product)) {
            String productCode = sanitize(product.getProductCode(), "P" + product.getProductId());
            return productCode + "-" + routeToken + "-" + version;
        }
        String phoneModelCode = phoneModelCode(product);
        return modelVariantProductPrefix(product, phoneModelCode) + "-" + phoneModelCode + "-"
            + LINE_CODE_PLACEHOLDER + "-" + routeToken + "-" + version;
    }

    public static String inheritedRouteCode(Product targetProduct, ProcessEntity sourceRoute) {
        String sourceProcessId = sourceRoute.getProcessId() == null ? "0" : String.valueOf(sourceRoute.getProcessId());
        String version = sanitize(sourceRoute.getVersionNo(), "V1");
        if (!isModelVariant(targetProduct)) {
            String productCode = sanitize(targetProduct.getProductCode(), "P" + targetProduct.getProductId());
            return productCode + "-INH-R" + sourceProcessId + "-" + version;
        }
        String phoneModelCode = phoneModelCode(targetProduct);
        return modelVariantProductPrefix(targetProduct, phoneModelCode) + "-" + phoneModelCode + "-" + LINE_CODE_PLACEHOLDER
            + "-INH-R" + sourceProcessId + "-" + version;
    }

    private static boolean isModelVariant(Product product) {
        return product != null && PRODUCT_TYPE_MODEL_VARIANT.equals(product.getProductType());
    }

    private static String phoneModelCode(Product product) {
        String fromProductCode = endingFourDigitGroup(product.getProductCode());
        if (StringUtils.hasText(fromProductCode)) {
            return fromProductCode;
        }
        String digits = digits(product.getModel());
        if (!StringUtils.hasText(digits)) {
            return LINE_CODE_PLACEHOLDER;
        }
        if (digits.length() > 4) {
            return digits.substring(digits.length() - 4);
        }
        return "0".repeat(4 - digits.length()) + digits;
    }

    private static String modelVariantProductPrefix(Product product, String phoneModelCode) {
        String productCode = sanitize(product.getProductCode(), "P" + product.getProductId());
        String suffix = "-" + phoneModelCode;
        if (productCode.endsWith(suffix) && productCode.length() > suffix.length()) {
            return productCode.substring(0, productCode.length() - suffix.length());
        }
        return productCode;
    }

    private static String endingFourDigitGroup(String value) {
        if (!StringUtils.hasText(value)) {
            return null;
        }
        Matcher matcher = END_FOUR_DIGIT_GROUP.matcher(value.trim());
        return matcher.find() ? matcher.group(1) : null;
    }

    private static String digits(String value) {
        return StringUtils.hasText(value) ? value.replaceAll("\\D", "") : null;
    }

    private static String sanitize(String value, String fallback) {
        String raw = StringUtils.hasText(value) ? value : fallback;
        String cleaned = raw.trim().toUpperCase()
            .replaceAll("[^A-Z0-9_-]", "-")
            .replaceAll("-{2,}", "-")
            .replaceAll("^-|-$", "");
        return StringUtils.hasText(cleaned) ? cleaned : fallback;
    }
}
