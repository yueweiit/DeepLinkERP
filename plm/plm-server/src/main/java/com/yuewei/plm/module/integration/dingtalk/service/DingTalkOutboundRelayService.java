package com.yuewei.plm.module.integration.dingtalk.service;

import com.yuewei.plm.module.integration.dingtalk.dto.DingTalkOutboundRelayDTO;
import com.yuewei.plm.module.integration.dingtalk.vo.DingTalkOutboundRelayResultVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class DingTalkOutboundRelayService {
    private static final String STATUS_SUCCESS = "success";
    private static final String STATUS_FAILED = "failed";

    private final DingTalkOfficialApprovalClient officialApprovalClient;

    public DingTalkOutboundRelayResultVO handle(DingTalkOutboundRelayDTO dto) {
        String action = normalize(dto == null ? null : dto.getAction());
        if (!StringUtils.hasText(action)) {
            return failed(null, dto, "DINGTALK_ACTION_REQUIRED", "action is required");
        }
        return switch (action) {
            case "workflow-task-lookup" -> lookupWorkflowTask(dto);
            case "agree" -> agree(dto);
            case "cc" -> cc(dto);
            default -> failed(action, dto, "DINGTALK_ACTION_UNSUPPORTED", "unsupported dingtalk outbound action");
        };
    }

    private DingTalkOutboundRelayResultVO lookupWorkflowTask(DingTalkOutboundRelayDTO dto) {
        String approvalInstanceId = approvalInstanceId(dto);
        if (!StringUtils.hasText(approvalInstanceId)) {
            return failed(
                "workflow-task-lookup",
                dto,
                "DINGTALK_APPROVAL_INSTANCE_REQUIRED",
                "approvalInstanceId is required"
            );
        }
        if (StringUtils.hasText(dto.getTaskId())) {
            return success("workflow-task-lookup", dto, dto.getTaskId(), "taskId provided by request");
        }
        try {
            DingTalkOfficialApprovalClient.TaskLookupResult lookup = officialApprovalClient.lookupRunningTaskId(
                approvalInstanceId,
                dto.getActionerUserId()
            );
            String message = lookup.fallback()
                ? "taskId found by fallback running task"
                : "taskId found by actioner user";
            return success("workflow-task-lookup", dto, lookup.taskId(), message);
        } catch (DingTalkOfficialApprovalException ex) {
            return failed("workflow-task-lookup", dto, ex.getErrorCode(), ex.getMessage());
        } catch (Exception ex) {
            return failed("workflow-task-lookup", dto, "DINGTALK_TASK_LOOKUP_FAILED", ex.getMessage());
        }
    }

    private DingTalkOutboundRelayResultVO agree(DingTalkOutboundRelayDTO dto) {
        String approvalInstanceId = approvalInstanceId(dto);
        if (!StringUtils.hasText(approvalInstanceId)) {
            return failed("agree", dto, "DINGTALK_APPROVAL_INSTANCE_REQUIRED", "approvalInstanceId is required");
        }
        if (!StringUtils.hasText(dto.getActionerUserId())) {
            return failed("agree", dto, "DINGTALK_ACTIONER_USER_ID_REQUIRED", "actionerUserId is required");
        }
        String taskId = dto.getTaskId();
        boolean fallback = false;
        try {
            if (!StringUtils.hasText(taskId)) {
                DingTalkOfficialApprovalClient.TaskLookupResult lookup = officialApprovalClient.lookupRunningTaskId(
                    approvalInstanceId,
                    dto.getActionerUserId()
                );
                taskId = lookup.taskId();
                fallback = lookup.fallback();
            }
            DingTalkOfficialApprovalClient.OfficialAgreeResult agree = officialApprovalClient.agreeTask(
                approvalInstanceId,
                taskId,
                dto.getActionerUserId(),
                dto.getRemark()
            );
            String message = fallback
                ? "DingTalk approval task agreed by fallback running task"
                : "DingTalk approval task agreed";
            return success("agree", dto, agree.taskId(), message);
        } catch (DingTalkOfficialApprovalException ex) {
            return failed("agree", dto, ex.getErrorCode(), ex.getMessage()).toBuilder().taskId(taskId).build();
        } catch (Exception ex) {
            return failed("agree", dto, "DINGTALK_AGREE_FAILED", ex.getMessage()).toBuilder().taskId(taskId).build();
        }
    }

    private DingTalkOutboundRelayResultVO cc(DingTalkOutboundRelayDTO dto) {
        if (dto.getReceiverUserIds() == null || dto.getReceiverUserIds().isEmpty()) {
            return failed("cc", dto, "DINGTALK_CC_RECEIVER_REQUIRED", "receiverUserIds is required");
        }
        return failed(
            "cc",
            dto,
            "DINGTALK_CC_NOT_IMPLEMENTED",
            "PLM relay endpoint accepted cc request, but official DingTalk message API is not connected yet"
        );
    }

    private DingTalkOutboundRelayResultVO success(String action, DingTalkOutboundRelayDTO dto, String taskId, String message) {
        return base(action, dto)
            .status(STATUS_SUCCESS)
            .externalStatus(STATUS_SUCCESS)
            .taskId(taskId)
            .message(message)
            .build();
    }

    private DingTalkOutboundRelayResultVO failed(String action, DingTalkOutboundRelayDTO dto, String errorCode, String message) {
        return base(action, dto)
            .status(STATUS_FAILED)
            .externalStatus(STATUS_FAILED)
            .errorCode(errorCode)
            .message(message)
            .build();
    }

    private DingTalkOutboundRelayResultVO.DingTalkOutboundRelayResultVOBuilder base(String action, DingTalkOutboundRelayDTO dto) {
        return DingTalkOutboundRelayResultVO.builder()
            .action(action)
            .approvalInstanceId(approvalInstanceId(dto))
            .processInstanceId(dto == null ? null : dto.getProcessInstanceId())
            .taskId(dto == null ? null : dto.getTaskId());
    }

    private String approvalInstanceId(DingTalkOutboundRelayDTO dto) {
        if (dto == null) {
            return null;
        }
        if (StringUtils.hasText(dto.getApprovalInstanceId())) {
            return dto.getApprovalInstanceId();
        }
        if (StringUtils.hasText(dto.getProcessInstanceId())) {
            return dto.getProcessInstanceId();
        }
        return dto.getSourceApprovalInstanceId();
    }

    private String normalize(String value) {
        return StringUtils.hasText(value) ? value.trim().toLowerCase() : null;
    }
}
