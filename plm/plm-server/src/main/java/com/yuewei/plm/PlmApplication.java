package com.yuewei.plm;

import com.yuewei.plm.common.config.AppProperties;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(AppProperties.class)
@MapperScan({"com.yuewei.plm.repository", "com.yuewei.plm.module.**.repository"})
public class PlmApplication {

    public static void main(String[] args) {
        SpringApplication.run(PlmApplication.class, args);
    }
}
