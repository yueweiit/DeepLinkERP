package com.yuewei.plm.module.product.mold.service;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.module.product.mold.vo.ProductMoldCodeVO;
import com.yuewei.plm.repository.ProductRepository;
import com.yuewei.plm.repository.entity.Product;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class ProductMoldCodeService {
    private final JdbcTemplate jdbcTemplate;
    private final ProductRepository productRepository;

    public Optional<Product> findByIncomingMoldCodes(Collection<String> incomingCodes) {
        List<String> codes = incomingCodes == null ? List.of() : incomingCodes.stream()
            .filter(StringUtils::hasText)
            .map(this::normalizeCode)
            .distinct()
            .toList();
        if (codes.isEmpty()) {
            return Optional.empty();
        }

        Set<Long> productIds = new LinkedHashSet<>();
        List<String> missingCodes = new ArrayList<>();
        for (String code : codes) {
            List<Long> matches = findProductIdsByCandidates(candidateCodes(code));
            if (matches.isEmpty()) {
                missingCodes.add(code);
            } else {
                productIds.addAll(matches);
            }
        }
        if (!productIds.isEmpty() && !missingCodes.isEmpty()) {
            throw validation("部分模具编码尚未建立产品关联: " + String.join(",", missingCodes));
        }
        if (productIds.size() > 1) {
            throw validation("多个模具编码关联了不同来源产品");
        }
        return productIds.stream()
            .findFirst()
            .map(productRepository::selectById)
            .filter(product -> product != null && (product.getDeletedFlag() == null || product.getDeletedFlag() == 0));
    }

    public List<ProductMoldCodeVO> listByProductId(Long productId) {
        if (productId == null) {
            return List.of();
        }
        return jdbcTemplate.query("""
            select pmc.product_mold_code_id, pmc.product_id, pmc.mold_code, pmc.mold_prefix,
                   pmc.product_code_prefix, pmc.product_specific_code, pmc.mold_name, pmc.key_code,
                   pmc.inventory_id, i.status as inventory_status, pmc.source_file, pmc.source_row_no,
                   pmc.status
              from plm_product_mold_code pmc
              left join plm_inventory i on i.inventory_id = pmc.inventory_id and i.deleted_flag = 0
             where pmc.product_id = ?
               and pmc.deleted_flag = 0
             order by pmc.mold_code
            """, (rs, rowNum) -> ProductMoldCodeVO.builder()
            .productMoldCodeId(rs.getLong("product_mold_code_id"))
            .productId(rs.getLong("product_id"))
            .moldCode(rs.getString("mold_code"))
            .moldPrefix(rs.getString("mold_prefix"))
            .productCodePrefix(rs.getString("product_code_prefix"))
            .productSpecificCode(rs.getString("product_specific_code"))
            .moldName(rs.getString("mold_name"))
            .keyCode(rs.getString("key_code"))
            .inventoryId(nullableLong(rs.getObject("inventory_id")))
            .inventoryStatus(rs.getString("inventory_status"))
            .sourceFile(rs.getString("source_file"))
            .sourceRowNo((Integer) rs.getObject("source_row_no"))
            .status(rs.getString("status"))
            .build(), productId);
    }

    public void upsert(Long productId, String moldCode, String moldName, String keyCode,
                       String status, String sourceFile, Integer sourceRowNo, String operator) {
        String normalizedCode = normalizeCode(moldCode);
        ProductBusinessCodeGenerator.MoldCodeParts parts =
            new ProductBusinessCodeGenerator().parseMoldCode(normalizedCode, null, List.of(), null);
        String moldPrefix = normalizedCode.substring(0, 3);
        String productCodePrefix = "N" + normalizedCode.substring(1, 3);
        Long inventoryId = findInventoryId(normalizedCode);
        LocalDateTime now = LocalDateTime.now();
        List<Long> existingIds = jdbcTemplate.query(
            "select product_mold_code_id from plm_product_mold_code where mold_code = ? order by product_mold_code_id limit 1",
            (rs, rowNum) -> rs.getLong("product_mold_code_id"),
            normalizedCode
        );
        if (!existingIds.isEmpty()) {
            jdbcTemplate.update("""
                update plm_product_mold_code
                   set product_id = ?, mold_prefix = ?, product_code_prefix = ?, product_specific_code = ?,
                       mold_name = ?, key_code = ?, inventory_id = ?, source_file = ?, source_row_no = ?,
                       status = ?, updated_at = ?, updated_by = ?, deleted_flag = 0
                 where product_mold_code_id = ?
                """,
                productId, moldPrefix, productCodePrefix, parts.productSpecificCode(), trimToNull(moldName),
                trimToNull(keyCode), inventoryId, sourceFile, sourceRowNo,
                StringUtils.hasText(status) ? status : "active", now, operator, existingIds.get(0)
            );
            return;
        }
        jdbcTemplate.update("""
            insert into plm_product_mold_code (
                product_id, mold_code, mold_prefix, product_code_prefix, product_specific_code,
                mold_name, key_code, inventory_id, source_file, source_row_no, status,
                created_at, created_by, updated_at, updated_by, deleted_flag
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            productId, normalizedCode, moldPrefix, productCodePrefix, parts.productSpecificCode(),
            trimToNull(moldName), trimToNull(keyCode), inventoryId, sourceFile, sourceRowNo,
            StringUtils.hasText(status) ? status : "active", now, operator, now, operator
        );
    }

    private List<Long> findProductIdsByCandidates(List<String> candidates) {
        if (candidates.isEmpty()) {
            return List.of();
        }
        String placeholders = String.join(",", candidates.stream().map(value -> "?").toList());
        return jdbcTemplate.query(
            "select distinct product_id from plm_product_mold_code where upper(mold_code) in (" + placeholders + ") and deleted_flag = 0 and status = 'active'",
            (rs, rowNum) -> rs.getLong("product_id"),
            candidates.toArray()
        );
    }

    private List<String> candidateCodes(String code) {
        Set<String> candidates = new LinkedHashSet<>();
        candidates.add(code);
        if (code.matches("[A-Z]{3}\\d{2,}") && code.length() > 5) {
            candidates.add(code.substring(0, 5));
        }
        return new ArrayList<>(candidates);
    }

    private Long findInventoryId(String moldCode) {
        List<Long> ids = jdbcTemplate.query(
            "select inventory_id from plm_inventory where upper(inventory_code) = ? and deleted_flag = 0 order by inventory_id limit 1",
            (rs, rowNum) -> rs.getLong("inventory_id"),
            moldCode
        );
        return ids.isEmpty() ? null : ids.get(0);
    }

    private Long nullableLong(Object value) {
        return value == null ? null : ((Number) value).longValue();
    }

    private String normalizeCode(String value) {
        return value == null ? "" : value.trim().toUpperCase(Locale.ROOT);
    }

    private String trimToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private BusinessException validation(String message) {
        return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, message);
    }
}
