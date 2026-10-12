package com.yuewei.plm.module.integration.dingtalk.config;

import java.util.ArrayList;
import java.util.List;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "plm.integrations.dingtalk")
public class DingTalkIntegrationProperties {
    private boolean enabled = true;
    private String corpId;
    private String appKey;
    private String appSecret;
    private String agentId;
    private String productLineProcessCode = "PROC-88C58F86-D55A-4A04-BA6E-CB71071F0468";
    private String modelVariantProcessCode = "PROC-BD65F530-F66F-46B9-8F72-0567DD68F60C";
    private String shipMoldProcessCode;
    private String outboundEndpoint;
    private String callbackToken;
    private String autoApproverUserId;
    private List<String> productLineCcUserIds = new ArrayList<>();
}
