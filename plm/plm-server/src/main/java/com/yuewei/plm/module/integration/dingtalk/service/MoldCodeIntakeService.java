package com.yuewei.plm.module.integration.dingtalk.service;

import com.yuewei.plm.common.util.ProductBusinessCodeGenerator;
import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkModelVariantReceiveDTO;
import com.yuewei.plm.module.integration.dingtalk.vo.MoldCodeMatchVO;
import com.yuewei.plm.repository.entity.Product;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class MoldCodeIntakeService {
    private final JdbcTemplate jdbcTemplate;
    private final ProductBusinessCodeGenerator codeGenerator;

    public List<MoldCodeMatchVO> sync(DingTalkModelVariantReceiveDTO dto, Product parent, Product project) {
        List<String> materialCodes = normalizeMaterialCodes(dto);
        List<String> moldCodes = resolveMoldCodes(dto, materialCodes);
        if (moldCodes.isEmpty()) {
            return List.of();
        }
        List<ProductBusinessCodeGenerator.MoldCodeParts> partsList = moldCodes.stream()
            .map(moldCode -> codeGenerator.parseMoldCode(
                moldCode,
                dto.getProductSpecificCode(),
                materialCodes,
                dto.getPhoneModelCode()
            ))
            .toList();
        backfillMoldCodeParts(dto, partsList);
        List<MoldCodeMatchVO> matches = new ArrayList<>();
        for (ProductBusinessCodeGenerator.MoldCodeParts parts : partsList) {
            Optional<Long> existing = findInventoryId(parts.moldCode());
            if (existing.isPresent()) {
                matches.add(match(parts, "linked_existing", existing.get(), "已匹配系统已有模具资料"));
            } else {
                Long inventoryId = createToolingInventory(parts, dto, parent, project);
                matches.add(match(parts, "created_draft", inventoryId, "已按钉钉开模申请创建待开模模具资料"));
            }
        }
        return matches;
    }

    private void backfillMoldCodeParts(DingTalkModelVariantReceiveDTO dto,
                                       List<ProductBusinessCodeGenerator.MoldCodeParts> partsList) {
        if (partsList.isEmpty()) {
            return;
        }
        String productSpecificCode = partsList.get(0).productSpecificCode();
        String phoneModelCode = partsList.get(0).phoneModelCode();
        boolean consistent = partsList.stream().allMatch(parts ->
            productSpecificCode.equals(parts.productSpecificCode())
                && Objects.equals(phoneModelCode, parts.phoneModelCode())
        );
        if (!consistent) {
            throw new com.yuewei.plm.common.exception.BusinessException(
                com.yuewei.plm.common.constant.ErrorCodeConstants.VALIDATION_ERROR,
                "模具编码产品特定编码或手机型号编码不一致"
            );
        }
        dto.setProductSpecificCode(productSpecificCode);
        dto.setPhoneModelCode(phoneModelCode);
        dto.setMaterialCodes(partsList.stream()
            .map(ProductBusinessCodeGenerator.MoldCodeParts::materialCode)
            .distinct()
            .toList());
        dto.setMoldCodes(String.join("\n", partsList.stream()
            .map(ProductBusinessCodeGenerator.MoldCodeParts::moldCode)
            .distinct()
            .toList()));
    }

    private List<String> resolveMoldCodes(DingTalkModelVariantReceiveDTO dto, List<String> materialCodes) {
        List<String> incoming = codeGenerator.splitCodes(dto.getMoldCodes());
        if (!incoming.isEmpty()) {
            return incoming;
        }
        return List.of();
    }

    private List<String> normalizeMaterialCodes(DingTalkModelVariantReceiveDTO dto) {
        if (dto.getMaterialCodes() == null || dto.getMaterialCodes().isEmpty()) {
            return List.of();
        }
        return dto.getMaterialCodes().stream()
            .filter(StringUtils::hasText)
            .map(code -> code.trim().toUpperCase())
            .distinct()
            .toList();
    }

    private Optional<Long> findInventoryId(String moldCode) {
        try {
            Long id = jdbcTemplate.queryForObject(
                "select inventory_id from plm_inventory where inventory_code = ? and deleted_flag = 0",
                Long.class,
                moldCode
            );
            return Optional.ofNullable(id);
        } catch (EmptyResultDataAccessException ignored) {
            return Optional.empty();
        }
    }

    private Long createToolingInventory(ProductBusinessCodeGenerator.MoldCodeParts parts,
                                        DingTalkModelVariantReceiveDTO dto,
                                        Product parent,
                                        Product project) {
        String inventoryName = parent.getProductName() + " " + project.getModel() + " " + parts.materialCode() + " 模具";
        String description = "钉钉新型号开模申请自动创建；产品特定编码=" + parts.productSpecificCode()
            + "；材质编码=" + parts.materialCode() + "；手机型号编码=" + parts.phoneModelCode();
        String operator = StringUtils.hasText(dto.getCreatedBy()) ? dto.getCreatedBy() : "system";
        return jdbcTemplate.queryForObject(
            """
            insert into plm_inventory (
                inventory_code, inventory_name, inventory_type, product_id, specification, description,
                stock_uom, quantity, status, remark, created_by, updated_by, deleted_flag
            ) values (?, ?, 'tooling', ?, ?, ?, '套', 0, 'draft', ?, ?, ?, 0)
            returning inventory_id
            """,
            Long.class,
            parts.moldCode(),
            inventoryName,
            project.getProductId(),
            parts.materialCode() + "/" + (StringUtils.hasText(parts.phoneModelCode()) ? parts.phoneModelCode() : ""),
            description,
            "来源钉钉审批单：" + dto.getDingTalkApprovalNo(),
            operator,
            operator
        );
    }

    private MoldCodeMatchVO match(ProductBusinessCodeGenerator.MoldCodeParts parts, String status,
                                  Long inventoryId, String message) {
        return MoldCodeMatchVO.builder()
            .moldCode(parts.moldCode())
            .expectedMoldCode(parts.expectedMoldCode())
            .productSpecificCode(parts.productSpecificCode())
            .materialCode(parts.materialCode())
            .phoneModelCode(parts.phoneModelCode())
            .matchStatus(status)
            .inventoryId(inventoryId)
            .message(message)
            .build();
    }
}
