package com.yuewei.plm.module.process.service;

import com.yuewei.plm.module.process.vo.ProcessRouteTemplateVO;
import java.util.List;

public interface ProcessRouteTemplateService {

    List<ProcessRouteTemplateVO> listTemplates(String productCode, Boolean onlyDefault);

    ProcessRouteTemplateVO getPublishedTemplate(String routeTemplateCode, String versionNo);
}
