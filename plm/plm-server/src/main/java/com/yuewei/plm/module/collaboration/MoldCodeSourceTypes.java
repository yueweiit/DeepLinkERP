package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.annotation.JsonAlias;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.List;
import lombok.Data;

public final class MoldCodeSourceTypes {
    private MoldCodeSourceTypes() {}

    public record SourceItem(
        @NotBlank @Size(max=64) @JsonAlias("item_code") String itemCode,
        @NotBlank @Size(max=512) @JsonAlias("item_name") String itemName,
        @Size(max=255) @JsonAlias("item_group") String itemGroup,
        @Size(max=4000) @JsonAlias("custom_specifications") String specifications,
        @Size(max=512) @JsonAlias("custom_original_identifier_alias") String originalAlias,
        @JsonAlias("disabled") Boolean disabled,
        @Size(max=64) @JsonAlias("modified") String modified
    ) {}

    public record ErpPreview(
        @NotBlank @Pattern(regexp="[a-f0-9]{64}") String snapshotId,
        @NotEmpty @Size(max=5000) List<@Valid SourceItem> rows
    ) {}

    public record DingTalkCodeEvent(
        @NotBlank @Size(max=128) String eventId,
        @Size(max=128) String approvalInstanceId,
        @Pattern(regexp="approved") String approvalStatus,
        @NotNull @Valid SourceItem item
    ) {}

    @Data
    public static class Query {
        @Min(1) private int page=1;
        @Min(1) @Max(100) private int size=50;
        @Size(max=255) private String keyword;
        @Pattern(regexp="erp|dingtalk") private String source;
        @Pattern(regexp="PC|TPU|nonstandard") private String part;
        @Pattern(regexp="matched|unmatched|incomplete|name_conflict|source_conflict|disabled|nonstandard") private String review;
    }
}
