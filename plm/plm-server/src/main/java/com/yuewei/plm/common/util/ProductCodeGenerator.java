package com.yuewei.plm.common.util;

import java.util.Locale;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.stereotype.Component;

@Component
public class ProductCodeGenerator {

    private final AtomicInteger sequence = new AtomicInteger(1);

    public String generate(String productName) {
        String shortCode = productName == null || productName.isBlank()
            ? "PLM"
            : productName.replaceAll("[^A-Za-z0-9\\u4e00-\\u9fa5]", "")
                .toUpperCase(Locale.ROOT);
        String prefix = shortCode.length() > 6 ? shortCode.substring(0, 6) : shortCode;
        return "PRD-" + prefix + "-" + String.format("%04d", sequence.getAndIncrement());
    }
}
