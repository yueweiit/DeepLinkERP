package com.yuewei.plm.module.code.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.code.dto.CodeItemQueryDTO;
import com.yuewei.plm.module.code.dto.CodeItemSaveDTO;
import com.yuewei.plm.module.code.entity.CodeItem;
import com.yuewei.plm.module.code.repository.CodeItemRepository;
import com.yuewei.plm.module.code.vo.CodeItemVO;
import java.time.LocalDateTime;
import java.util.Locale;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.dao.DuplicateKeyException;

@Service
@RequiredArgsConstructor
public class CodeItemService {
    private final CodeItemRepository repository;

    public PageVO<CodeItemVO> page(CodeItemQueryDTO query) {
        String normalizedStatus = StringUtils.hasText(query.getStatus()) ? normalizeStatus(query.getStatus()) : null;
        LambdaQueryWrapper<CodeItem> wrapper = new LambdaQueryWrapper<CodeItem>()
            .eq(CodeItem::getDeletedFlag, 0)
            .eq(StringUtils.hasText(query.getCodeType()), CodeItem::getCodeType, normalizeType(query.getCodeType()))
            .eq(normalizedStatus != null, CodeItem::getStatus, normalizedStatus)
            .and(StringUtils.hasText(query.getKeyword()), value -> value
                .like(CodeItem::getCodeValue, query.getKeyword().trim())
                .or().like(CodeItem::getCodeName, query.getKeyword().trim())
                .or().like(CodeItem::getCodeNameZh, query.getKeyword().trim()))
            .orderByAsc(CodeItem::getSortOrder, CodeItem::getCodeValue);
        IPage<CodeItem> result = repository.selectPage(new Page<>(query.getPage(), query.getSize()), wrapper);
        return PageVO.<CodeItemVO>builder()
            .content(result.getRecords().stream().map(this::toVO).toList())
            .page(result.getCurrent()).size(result.getSize())
            .totalElements(result.getTotal()).totalPages(result.getPages()).build();
    }

    @Transactional
    public CodeItemVO create(CodeItemSaveDTO dto) {
        String type = normalizeType(dto.getCodeType());
        String value = required(dto.getCodeValue(), "编码值");
        String name = required(dto.getCodeName(), "编码名称");
        if ("phone_model".equals(type)) {
            validatePhoneCode(value);
            ensurePhoneNameUnique(name, null);
        }
        ensureUnique(type, value, null);
        CodeItem item = new CodeItem();
        item.setCodeType(type);
        item.setCodeValue(value);
        item.setCodeName(name);
        item.setCodeNameZh(optional(dto.getCodeNameZh()));
        item.setStatus("enabled");
        item.setSortOrder(dto.getSortOrder());
        fillCreate(item);
        try { repository.insert(item); }
        catch (DuplicateKeyException exception) { throw duplicate(type); }
        return toVO(item);
    }

    @Transactional
    public CodeItemVO update(Long id, CodeItemSaveDTO dto) {
        CodeItem item = requireItem(id);
        String name = required(dto.getCodeName(), "编码名称");
        if ("phone_model".equals(item.getCodeType())) {
            if (!item.getCodeType().equals(normalizeType(dto.getCodeType()))
                || !item.getCodeValue().equals(required(dto.getCodeValue(), "编码值")))
                throw validation("手机型号编码创建后不可修改编码值或类型");
            ensurePhoneNameUnique(name, id);
        }
        item.setCodeName(name);
        item.setCodeNameZh(optional(dto.getCodeNameZh()));
        item.setSortOrder(dto.getSortOrder());
        touch(item);
        try { repository.updateById(item); }
        catch (DuplicateKeyException exception) { throw duplicate(item.getCodeType()); }
        return toVO(item);
    }

    @Transactional
    public CodeItemVO changeStatus(Long id, String status) {
        CodeItem item = requireItem(id);
        item.setStatus(normalizeStatus(status));
        touch(item);
        repository.updateById(item);
        return toVO(item);
    }

    public CodeItem requireEnabledColor(Long id, String codeValue) {
        CodeItem item = requireItem(id);
        if (!"color".equals(item.getCodeType()) || !item.getCodeValue().equals(codeValue)) {
            throw validation("颜色编码不存在或与选择值不一致");
        }
        if (!"enabled".equals(item.getStatus())) {
            throw validation("颜色编码已停用");
        }
        return item;
    }

    private void ensureUnique(String type, String value, Long excludedId) {
        long count = repository.selectCount(new LambdaQueryWrapper<CodeItem>()
            .eq(CodeItem::getCodeType, type).eq(CodeItem::getCodeValue, value)
            .eq(CodeItem::getDeletedFlag, 0)
            .ne(excludedId != null, CodeItem::getCodeItemId, excludedId));
        if (count > 0) throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT, "编码已存在");
    }

    private void validatePhoneCode(String value) {
        if (!value.matches("[0-9]{4}")) throw validation("手机型号编码必须为四位数字，保留前导零");
    }

    private void ensurePhoneNameUnique(String name, Long excludedId) {
        long count = repository.selectCount(new LambdaQueryWrapper<CodeItem>()
            .eq(CodeItem::getCodeType, "phone_model").eq(CodeItem::getDeletedFlag, 0)
            .apply("lower(btrim(code_name)) = lower({0})", name)
            .ne(excludedId != null, CodeItem::getCodeItemId, excludedId));
        if (count > 0) throw new BusinessException(ErrorCodeConstants.CODE_CONFLICT, "手机型号名称已存在（忽略大小写及首尾空格）");
    }

    private BusinessException duplicate(String type) {
        return new BusinessException(ErrorCodeConstants.CODE_CONFLICT,
            "phone_model".equals(type) ? "手机型号编码或名称已存在" : "编码已存在");
    }

    private CodeItem requireItem(Long id) {
        CodeItem item = repository.selectById(id);
        if (item == null || Integer.valueOf(1).equals(item.getDeletedFlag())) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "编码不存在");
        }
        return item;
    }

    private String normalizeType(String value) {
        return required(value, "编码类型").toLowerCase(Locale.ROOT);
    }

    private String normalizeStatus(String value) {
        String status = required(value, "状态").toLowerCase(Locale.ROOT);
        if (!"enabled".equals(status) && !"disabled".equals(status)) throw validation("编码状态无效");
        return status;
    }

    private String required(String value, String field) {
        if (!StringUtils.hasText(value)) throw validation(field + "不能为空");
        return value.trim();
    }

    private void fillCreate(CodeItem item) {
        LocalDateTime now = LocalDateTime.now();
        item.setCreatedAt(now); item.setCreatedBy("system");
        item.setUpdatedAt(now); item.setUpdatedBy("system"); item.setDeletedFlag(0);
    }

    private void touch(CodeItem item) {
        item.setUpdatedAt(LocalDateTime.now()); item.setUpdatedBy("system");
    }

    private CodeItemVO toVO(CodeItem item) {
        return CodeItemVO.builder().codeItemId(item.getCodeItemId()).codeType(item.getCodeType())
            .codeValue(item.getCodeValue()).codeName(item.getCodeName()).codeNameZh(item.getCodeNameZh())
            .status(item.getStatus())
            .sortOrder(item.getSortOrder()).updatedAt(item.getUpdatedAt()).build();
    }

    private String optional(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private BusinessException validation(String message) {
        return new BusinessException(ErrorCodeConstants.VALIDATION_ERROR, message);
    }
}
