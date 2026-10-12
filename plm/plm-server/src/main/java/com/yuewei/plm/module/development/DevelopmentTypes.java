package com.yuewei.plm.module.development;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import lombok.Data;

public final class DevelopmentTypes {
    private DevelopmentTypes() {}
    @Data public static class Query {
        @Min(1) @Max(1000000) private int page=1;
        @Min(1) @Max(100) private int size=50;
        @Size(max=128) private String keyword;
        @Pattern(regexp="platform|mold") private String kind;
        @Pattern(regexp="draft|confirmed|void") private String state;
        @Positive private Long productLineId;
        @Positive private Long productId;
        @Positive private Long itemId;
        @Positive private Long budgetId;
        @Pattern(regexp="CNY|MXN|USD|EUR") private String currency;
    }
    public record Change(@NotBlank String field, JsonNode before, JsonNode after) {}
    public record Patch(@Positive long id,@NotEmpty @Size(max=25) List<@Valid Change> changes,@Size(max=2000) String reason) {}
    public record Batch(@NotEmpty @Size(max=100) List<@Valid Patch> rows) {}
    public record Result(long id,String status,String message,List<Map<String,Object>> conflicts,Map<String,Object> row) {}
    public record CreateBudget(@NotBlank @Pattern(regexp="platform|mold") String kind,
        @NotBlank @Size(max=255) String name, @Positive Long productLineId,@Positive Long itemId,
        @Positive Long moldSetId,@Positive Long parentBudgetId,@Pattern(regexp="CNY|MXN|USD|EUR") String currency) {}
    public record CreateExpense(@NotBlank @Size(max=128) String description,@Positive Long productLineId,
        @Positive Long itemId,@Positive Long moldSetId,@Positive Long budgetId,@Pattern(regexp="CNY|MXN|USD|EUR") String currency,@Positive Long productId) {
        public CreateExpense(String description,Long productLineId,Long itemId,Long moldSetId,Long budgetId,String currency){this(description,productLineId,itemId,moldSetId,budgetId,currency,null);}
    }
    public record ImportDecision(@NotBlank @Size(max=128) String sheetName,@Positive int rowNo,boolean skip,
        @Positive Long budgetId,@Positive Long productLineId,@Positive Long itemId,@Positive Long moldSetId,
        @Positive Long parentBudgetId,@NotBlank @Size(max=255) String name,
        @NotNull Map<String,JsonNode> values,@NotNull Map<String,JsonNode> before,@Size(max=2000) String reason,
        @Pattern(regexp="platform|mold") String kind) {}
    public record ImportCommit(@NotBlank String token,@NotEmpty @Size(max=2000) List<@Valid ImportDecision> rows) {}
    public record ErpLine(@NotBlank @Size(max=128) String voucherId,@NotBlank @Size(max=128) String lineId,
        @NotBlank @Size(max=128) String description,@NotBlank @Pattern(regexp="CNY|MXN|USD|EUR") String currency,
        @NotNull BigDecimal postedAmount,@Size(max=64) String postedAt,@Size(max=255) String reversalOf,
        @NotNull @Min(1) @Max(1) Integer docstatus) {}
    public record ErpPreview(@NotEmpty @Size(max=2000) List<@Valid ErpLine> rows) {}
    public record ErpDecision(@Positive int rowNo,boolean skip,@Positive Long productLineId,@Positive Long itemId,
        @Positive Long moldSetId,@Positive Long budgetId,@NotBlank @Size(max=2000) String mappingReason) {}
    public record ErpCommit(@NotBlank String token,@NotEmpty @Size(max=2000) List<@Valid ErpDecision> rows) {}
}
