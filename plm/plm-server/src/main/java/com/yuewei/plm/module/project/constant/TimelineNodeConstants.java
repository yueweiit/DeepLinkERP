package com.yuewei.plm.module.project.constant;

import java.util.List;

public final class TimelineNodeConstants {

    public static final String PRODUCT_TYPE_PRODUCT_LINE = "product_line";
    public static final String PRODUCT_TYPE_MODEL_VARIANT = "model_variant";
    public static final String PRODUCT_TYPE_SKU = "sku";

    public static final String NODE_STATUS_COMPLETED = "completed";
    public static final String NODE_STATUS_CURRENT = "current";
    public static final String NODE_STATUS_PENDING = "pending";

    public static final String PRODUCT_TYPE_NAME_PRODUCT_LINE = "新产品线";
    public static final String PRODUCT_TYPE_NAME_MODEL_VARIANT = "新型号线";
    public static final String PRODUCT_TYPE_NAME_SKU = "SKU";

    public static final List<TimelineNodeDefinition> PRODUCT_LINE_NODES = List.of(
        step(1, "PRODUCT_LINE_INIT_CREATE", "产品立项", "PRODUCT_LINE_INIT_CONFIRM", "立项确认", "立项阶段", "other"),
        step(2, "PRODUCT_LINE_INIT_APPROVE", "确认立项", "PRODUCT_LINE_INIT_CONFIRM", "立项确认", "立项阶段", null),
        step(3, "PRODUCT_LINE_DESIGN_DRAWING", "画图查看", "PRODUCT_LINE_DESIGN_CONFIRM", "设计确认", "设计验证阶段", "drawing"),
        step(4, "PRODUCT_LINE_DESIGN_SUPPLIER_CONFIRM", "供应商确认外观图纸", "PRODUCT_LINE_DESIGN_CONFIRM", "设计确认", "设计验证阶段", "drawing"),
        step(5, "PRODUCT_LINE_MOLD_APPLY", "申请开模", "PRODUCT_LINE_MOLD_TRIAL", "开模试模", "开模阶段", null),
        step(6, "PRODUCT_LINE_MOLD_MAKE", "制作模具", "PRODUCT_LINE_MOLD_TRIAL", "开模试模", "开模阶段", "other"),
        step(7, "PRODUCT_LINE_MOLD_TEST", "测试模具", "PRODUCT_LINE_MOLD_TRIAL", "开模试模", "开模阶段", "testing"),
        step(8, "PRODUCT_LINE_SAMPLE_SIGN", "签样确认", "PRODUCT_LINE_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "customer_confirm"),
        step(9, "PRODUCT_LINE_PROCESS_PLAN", "加工艺", "PRODUCT_LINE_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "sop"),
        step(10, "PRODUCT_LINE_PROCESS_CONFIRM", "敲定工序", "PRODUCT_LINE_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "sop"),
        step(11, "PRODUCT_LINE_COMPONENT_CONFIRM", "确认组件", "PRODUCT_LINE_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", null),
        step(12, "PRODUCT_LINE_COMPONENT_FINISH_CONFIRM", "确认组件成品", "PRODUCT_LINE_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", null),
        step(13, "PRODUCT_LINE_FINAL_APPEARANCE_SAMPLE", "最终外观确认样", "PRODUCT_LINE_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "customer_confirm"),
        step(14, "PRODUCT_LINE_RED_SAMPLE_TEST", "红样测试", "PRODUCT_LINE_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "testing"),
        step(15, "PRODUCT_LINE_PRODUCTION_DOCS", "整理生产资料", "PRODUCT_LINE_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "sop"),
        step(16, "PRODUCT_LINE_YELLOW_SAMPLE", "黄样", "PRODUCT_LINE_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "testing"),
        step(17, "PRODUCT_LINE_SMALL_BATCH_TEST", "小批量测试", "PRODUCT_LINE_SMALL_BATCH_MX", "小批与 MX 验证", "市场验证阶段", "testing"),
        step(18, "PRODUCT_LINE_MOLD_TRANSFER", "运模", "PRODUCT_LINE_SMALL_BATCH_MX", "小批与 MX 验证", "市场验证阶段", null),
        step(19, "PRODUCT_LINE_MX_ACCEPTANCE", "MX 验收", "PRODUCT_LINE_SMALL_BATCH_MX", "小批与 MX 验证", "市场验证阶段", "testing"),
        step(20, "PRODUCT_LINE_TEST_VERIFY", "测试验证", "PRODUCT_LINE_SMALL_BATCH_MX", "小批与 MX 验证", "市场验证阶段", "testing"),
        step(21, "PRODUCT_LINE_MX_MARKET_TEST", "MX 小批量测试", "PRODUCT_LINE_SMALL_BATCH_MX", "小批与 MX 验证", "市场验证阶段", "testing"),
        step(22, "PRODUCT_LINE_PRODUCTION_DECISION_STEP", "投产决策", "PRODUCT_LINE_PRODUCTION_DECISION", "投产决策", "投产发布阶段", null)
    );

    public static final List<TimelineNodeDefinition> MODEL_VARIANT_NODES = List.of(
        step(1, "MODEL_VARIANT_INIT_CREATE", "产品立项", "MODEL_VARIANT_INIT_CONFIRM", "立项确认", "立项阶段", "other"),
        step(2, "MODEL_VARIANT_INIT_APPROVE", "确认立项", "MODEL_VARIANT_INIT_CONFIRM", "立项确认", "立项阶段", null),
        step(3, "MODEL_VARIANT_DESIGN_DRAWING", "画图查看", "MODEL_VARIANT_DESIGN_CONFIRM", "设计确认", "设计验证阶段", "drawing"),
        step(4, "MODEL_VARIANT_DESIGN_SUPPLIER_CONFIRM", "供应商确认外观图纸", "MODEL_VARIANT_DESIGN_CONFIRM", "设计确认", "设计验证阶段", "drawing"),
        step(5, "MODEL_VARIANT_MOLD_APPLY", "申请开模", "MODEL_VARIANT_MOLD_TRIAL", "开模试模", "开模阶段", null),
        step(6, "MODEL_VARIANT_MOLD_MAKE", "制作模具", "MODEL_VARIANT_MOLD_TRIAL", "开模试模", "开模阶段", "other"),
        step(7, "MODEL_VARIANT_MOLD_TEST", "测试模具", "MODEL_VARIANT_MOLD_TRIAL", "开模试模", "开模阶段", "testing"),
        step(8, "MODEL_VARIANT_SAMPLE_SIGN", "签样确认", "MODEL_VARIANT_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "customer_confirm"),
        step(9, "MODEL_VARIANT_PROCESS_PLAN", "加工艺", "MODEL_VARIANT_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "sop"),
        step(10, "MODEL_VARIANT_PROCESS_CONFIRM", "敲定工序", "MODEL_VARIANT_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "sop"),
        step(11, "MODEL_VARIANT_COMPONENT_CONFIRM", "确认组件", "MODEL_VARIANT_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", null),
        step(12, "MODEL_VARIANT_COMPONENT_FINISH_CONFIRM", "确认组件成品", "MODEL_VARIANT_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", null),
        step(13, "MODEL_VARIANT_FINAL_APPEARANCE_SAMPLE", "最终外观确认样", "MODEL_VARIANT_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "customer_confirm"),
        step(14, "MODEL_VARIANT_RED_SAMPLE_TEST", "红样测试", "MODEL_VARIANT_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "testing"),
        step(15, "MODEL_VARIANT_PRODUCTION_DOCS", "整理生产资料", "MODEL_VARIANT_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "sop"),
        step(16, "MODEL_VARIANT_YELLOW_SAMPLE", "黄样", "MODEL_VARIANT_SAMPLE_PROCESS", "样品与工艺", "样品/工艺定型阶段", "testing"),
        step(17, "MODEL_VARIANT_SMALL_BATCH_TEST", "小批量测试", "MODEL_VARIANT_SMALL_BATCH_MX", "小批与 MX 验证", "市场验证阶段", "testing"),
        step(18, "MODEL_VARIANT_MOLD_TRANSFER", "运模", "MODEL_VARIANT_SMALL_BATCH_MX", "小批与 MX 验证", "市场验证阶段", null)
    );

    private TimelineNodeConstants() {
    }

    private static TimelineNodeDefinition step(
        Integer stepNo,
        String nodeCode,
        String nodeName,
        String stageCode,
        String stageName,
        String phaseName,
        String requiredFileCategory
    ) {
        return new TimelineNodeDefinition(
            stepNo,
            nodeCode,
            nodeName,
            stageCode,
            stageName,
            phaseName,
            requiredFileCategory,
            requiredFileCategory != null && !requiredFileCategory.isBlank(),
            null,
            null,
            null,
            false,
            true
        );
    }

    public record TimelineNodeDefinition(
        Integer stepNo,
        String nodeCode,
        String nodeName,
        String stageCode,
        String stageName,
        String phaseName,
        String requiredFileCategory,
        Boolean requiredAttachment,
        String uploadPrompt,
        String confirmPrompt,
        String emptyFileMessage,
        Boolean gateFlag,
        Boolean enabledFlag
    ) {
        public TimelineNodeDefinition(Integer stepNo, String nodeCode, String nodeName) {
            this(stepNo, nodeCode, nodeName, nodeCode, nodeName, "", null, false, null, null, null, false, true);
        }
    }
}
