package com.yuewei.plm.common.vo;

import java.util.List;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class PageVO<T> {
    private List<T> content;
    private long page;
    private long size;
    private long totalElements;
    private long totalPages;
}
