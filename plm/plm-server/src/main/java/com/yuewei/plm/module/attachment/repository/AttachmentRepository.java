package com.yuewei.plm.module.attachment.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.yuewei.plm.module.attachment.entity.Attachment;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface AttachmentRepository extends BaseMapper<Attachment> {
}
