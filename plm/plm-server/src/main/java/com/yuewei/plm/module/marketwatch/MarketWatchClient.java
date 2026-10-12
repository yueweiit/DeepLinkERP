package com.yuewei.plm.module.marketwatch;

import com.yuewei.plm.common.config.AppProperties;
import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import java.net.URI;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.Getter;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.util.UriComponentsBuilder;

@Component
public class MarketWatchClient {
    private static final ParameterizedTypeReference<Map<String,Object>> MAP = new ParameterizedTypeReference<>() {};
    private final AppProperties.PhoneWatch properties;
    private final RestClient rest;

    public MarketWatchClient(AppProperties appProperties) {
        this.properties = appProperties.getPhoneWatch();
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofMillis(properties.getConnectTimeoutMs()));
        factory.setReadTimeout(Duration.ofMillis(properties.getReadTimeoutMs()));
        this.rest = RestClient.builder().requestFactory(factory).build();
    }

    public boolean enabled() { return properties.isEnabled(); }

    public Map<String,Object> health() { return get("/internal/v1/health", null); }
    public Map<String,Object> summary() { return get("/internal/v1/summary", null); }
    public Map<String,Object> items(MultiValueMap<String,String> query) { return get("/internal/v1/items", query); }
    public Map<String,Object> detail(String kind,long id) { return get("/internal/v1/items/"+kind+"/"+id, null); }

    public Map<String,Object> update(String kind,long id,Object body) {
        return exchange(HttpMethod.PATCH, "/internal/v1/items/"+kind+"/"+id, null, body, MAP);
    }

    public Map<String,Object> bulk(Object body) {
        return exchange(HttpMethod.POST, "/internal/v1/items/bulk", null, body, MAP);
    }

    public CsvFile export(MultiValueMap<String,String> query) {
        try {
            ResponseEntity<byte[]> response = request(HttpMethod.GET, "/internal/v1/export.csv", query)
                .retrieve().toEntity(byte[].class);
            String disposition = response.getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION);
            String filename = disposition == null ? "phone-watch.csv" : disposition.replaceFirst(".*filename=\"?([^\"]+)\"?.*", "$1");
            return new CsvFile(response.getBody() == null ? new byte[0] : response.getBody(), filename);
        } catch (RestClientException ex) {
            throw upstream(ex);
        }
    }

    private Map<String,Object> get(String path,MultiValueMap<String,String> query) {
        return exchange(HttpMethod.GET, path, query, null, MAP);
    }

    private <T> T exchange(HttpMethod method,String path,MultiValueMap<String,String> query,Object body,ParameterizedTypeReference<T> type) {
        try {
            RestClient.RequestBodySpec request = request(method,path,query);
            if (body != null) request.body(body);
            T value = request.retrieve().body(type);
            if (value == null) throw new RestClientException("empty response");
            return value;
        } catch (HttpClientErrorException.NotFound ex) {
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND,"监控记录不存在");
        } catch (RestClientException ex) {
            throw upstream(ex);
        }
    }

    private RestClient.RequestBodySpec request(HttpMethod method,String path,MultiValueMap<String,String> query) {
        UriComponentsBuilder builder = UriComponentsBuilder.fromUriString(properties.getBaseUrl()).path(path);
        if (query != null) builder.queryParams(query);
        URI uri = builder.build().encode().toUri();
        return rest.method(method).uri(uri)
            .header(HttpHeaders.AUTHORIZATION,"Bearer "+properties.getToken())
            .accept(MediaType.APPLICATION_JSON);
    }

    private BusinessException upstream(Exception ignored) {
        return new BusinessException(ErrorCodeConstants.UPSTREAM_UNAVAILABLE,"手机新品监控服务暂时不可用，请稍后重试");
    }

    public record CsvFile(byte[] bytes,String filename) {}
}
