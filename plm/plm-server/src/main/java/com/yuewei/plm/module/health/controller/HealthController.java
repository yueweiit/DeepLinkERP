package com.yuewei.plm.module.health.controller;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import com.yuewei.plm.module.health.dto.ValidationProbeDTO;
import com.yuewei.plm.module.health.vo.HealthVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.sql.Connection;
import java.time.OffsetDateTime;
import javax.sql.DataSource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/health")
public class HealthController {

    private final DataSource dataSource;
    private final Environment environment;
    private final String applicationName;

    public HealthController(
            DataSource dataSource,
            Environment environment,
            @Value("${spring.application.name:plm-server}") String applicationName) {
        this.dataSource = dataSource;
        this.environment = environment;
        this.applicationName = applicationName;
    }

    @GetMapping
    public ResponseVO<HealthVO> health(HttpServletRequest request) {
        HealthVO vo = new HealthVO("UP", applicationName, activeProfiles(), "UNKNOWN", OffsetDateTime.now());
        return ResponseVO.success(vo, RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @GetMapping("/db")
    public ResponseVO<HealthVO> database(HttpServletRequest request) {
        String databaseStatus = databaseStatus();
        String status = "UP".equals(databaseStatus) ? "UP" : "DOWN";
        HealthVO vo = new HealthVO(status, applicationName, activeProfiles(), databaseStatus, OffsetDateTime.now());
        return ResponseVO.success(vo, RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    @PostMapping("/validation-probe")
    public ResponseVO<String> validationProbe(@Valid @RequestBody ValidationProbeDTO dto, HttpServletRequest request) {
        return ResponseVO.success(dto.getName(), RequestIdUtil.getRequestId(request), OffsetDateTime.now());
    }

    private String activeProfiles() {
        String[] profiles = environment.getActiveProfiles();
        return profiles.length == 0 ? "default" : String.join(",", profiles);
    }

    private String databaseStatus() {
        try (Connection connection = dataSource.getConnection()) {
            return connection.isValid(2) ? "UP" : "DOWN";
        } catch (Exception ex) {
            return "DOWN";
        }
    }
}
