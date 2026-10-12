package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.List;
import java.util.Map;
import java.math.BigDecimal;
import lombok.Data;

public final class CollaborationTypes {
    private CollaborationTypes() {}
    @Data
    public static class Query {
        @Pattern(regexp="market|delivery|production") private String view="market";
        @Min(1) @Max(1000000) private int page=1;
        @Min(1) @Max(100) private int size=50;
        @Size(max=128) private String keyword;
        private Long productLineId;
        @Size(max=32) private String status;
        private boolean mineOnly;
        private Long itemId;
        @Positive private Long moldSetId;
        @Pattern(regexp="unknown|china_maker|china_dispatch|in_transit|mexico_transit|mexico_factory|other") private String location;
        private boolean moldLedger;
        private boolean schedule;
        private boolean overdueOnly;
    }
    public record CellChange(@NotBlank String field, JsonNode before, JsonNode after,
                             @Size(max=2000) String reason) {}
    public record RowPatch(@NotBlank @Pattern(regexp="item|mold_set") String entityType, @Positive long id,
                           @NotEmpty @Size(max=30) List<@Valid CellChange> changes) {}
    public record BatchSave(@NotEmpty @Size(max=100) List<@Valid RowPatch> rows) {}
    public record RowResult(String entityType, long id, String status, String message,
                            List<Map<String,Object>> conflicts, Map<String,Object> row) {}
    public record CreateItem(Long productLineId, @NotBlank @Size(max=255) String styleName,
                             @Size(max=128) String brand, @NotBlank @Size(max=512) String compatibleModels,
                             @Size(max=20) String phoneModelCode, @PositiveOrZero BigDecimal phonePrice,
                             @Size(max=12) String priceCurrency, @Size(max=512) String salesPlatform,
                             @Size(max=4000) String referenceUrl, @Size(max=4000) String notes) {
        public CreateItem(Long productLineId,String styleName,String brand,String compatibleModels,String phoneModelCode,String notes) {
            this(productLineId,styleName,brand,compatibleModels,phoneModelCode,null,null,null,null,notes);
        }
    }
    public record CreateMoldSet(@Size(max=255) String setName, Long pcMoldCodeId, Long tpuMoldCodeId,
                                @Positive Long sourceMoldSetId) {
        public CreateMoldSet(String setName,Long pcMoldCodeId,Long tpuMoldCodeId) {this(setName,pcMoldCodeId,tpuMoldCodeId,null);}
    }
    public record CreateMold(@Positive long itemId, @Size(max=255) String setName) {}
    public record LinkProjects(@NotNull @Size(max=300) List<@Positive Long> projectIds, boolean confirmCompatibility,
                               @Size(max=300) List<@Positive Long> beforeProjectIds, boolean append) {}
    public record Assignments(@NotNull Map<String,List<Long>> groups, @NotNull Map<String,List<Long>> before) {}
    public record ImportDecision(@Positive int rowNo, @NotBlank @Size(max=128) String sheetName, boolean skip, Long itemId, Long moldSetId, Long productLineId,
                                 String styleName, String brand, String compatibleModels, boolean newMoldSet,
                                 @NotNull Map<String,JsonNode> values, @NotNull Map<String,JsonNode> before,
                                 @Size(max=2000) String reviewReason, boolean confirmCompatibility) {
        public ImportDecision(int rowNo,String sheetName,boolean skip,Long itemId,Long moldSetId,Long productLineId,String styleName,String brand,String compatibleModels,boolean newMoldSet,Map<String,JsonNode> values,Map<String,JsonNode> before,String reviewReason) {
            this(rowNo,sheetName,skip,itemId,moldSetId,productLineId,styleName,brand,compatibleModels,newMoldSet,values,before,reviewReason,false);
        }
    }
    public record ImportCommit(@NotEmpty @Size(max=2000) List<@Valid ImportDecision> rows) {}
}
