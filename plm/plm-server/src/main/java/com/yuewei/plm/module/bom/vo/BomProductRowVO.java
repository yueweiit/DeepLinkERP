package com.yuewei.plm.module.bom.vo;

import java.time.LocalDateTime;

public record BomProductRowVO(Long productId, String productCode, String productName,
                              long bomCount, LocalDateTime updatedAt) { }
