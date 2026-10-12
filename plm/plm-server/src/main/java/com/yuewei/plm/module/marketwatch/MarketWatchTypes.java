package com.yuewei.plm.module.marketwatch;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.util.List;

public final class MarketWatchTypes {
    private MarketWatchTypes() {}

    public record UpdateItem(
        @Size(max = 32) String status,
        @Size(max = 64) String badge,
        @Size(max = 64) String saleStatus
    ) {}

    public record BulkUpdate(
        @NotBlank @Pattern(regexp = "phone|candidate") String kind,
        @NotEmpty @Size(max = 500) List<@Positive Long> ids,
        @Size(max = 32) String status,
        @Size(max = 64) String badge,
        @Size(max = 64) String saleStatus
    ) {}

    public record Promote(
        @NotBlank @Pattern(regexp = "phone|candidate") String sourceKind,
        @Positive long sourceId,
        @NotBlank @Pattern(regexp = "create|link") String mode,
        @Positive Long itemId,
        @Positive Long productLineId,
        @Size(max = 255) String styleName,
        @Size(max = 512) String compatibleModels,
        @Size(max = 20) String phoneModelCode,
        @Size(max = 4000) String notes
    ) {}
}
