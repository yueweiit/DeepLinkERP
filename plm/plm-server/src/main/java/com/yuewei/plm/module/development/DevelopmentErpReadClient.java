package com.yuewei.plm.module.development;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.infrastructure.http.SafeHttpTransport;
import java.net.*;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import static com.yuewei.plm.module.development.DevelopmentTypes.*;
import static com.yuewei.plm.module.development.DevelopmentFinanceMath.invalid;

/** Configured server-only GET contract, not a guessed ERPNext financial API or a write client. */
@Component
public class DevelopmentErpReadClient {
    private final String endpoint,token;
    private final ObjectMapper json;
    private final HttpClient client;
    private static final int MAX_BYTES=2*1024*1024;
    public DevelopmentErpReadClient(@Value("${PLM_PILOT_ERP_EXPENSES_URL:}") String endpoint,@Value("${PLM_PILOT_ERP_EXPENSES_TOKEN:}") String token,ObjectMapper json) {
        this.endpoint=endpoint;this.token=token;this.json=json;
        this.client=SafeHttpTransport.client();
    }
    public boolean configured(){return endpoint!=null&&!endpoint.isBlank()&&token!=null&&!token.isBlank();}
    public List<ErpLine> read() {
        if(!configured())throw invalid("ERP费用只读接口未配置");URI uri;
        try {uri=SafeHttpTransport.endpoint(endpoint);}catch(IllegalArgumentException e){throw invalid("ERP费用地址仅支持HTTPS或本机回环，不允许凭据URL或重定向");}
        try {var request=HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(15)).header("Authorization","Bearer "+token).header("Accept","application/json").GET().build();
            var response=client.send(request,SafeHttpTransport.boundedBody(MAX_BYTES));
            if(response.statusCode()!=200)throw new BusinessException(50301,"ERP费用只读请求失败，未写入任何费用");
            var root=json.readTree(response.body());var rows=root.get("rows");if(rows==null||!rows.isArray()||rows.isEmpty()||rows.size()>2000)throw invalid("ERP响应须为rows数组，1至2000条已过账明细");
            List<ErpLine> output=new ArrayList<>();for(var row:rows){for(String field:List.of("voucherId","lineId","description","currency","postedAmount","docstatus"))if(!row.hasNonNull(field))throw invalid("ERP明细缺少稳定ID、原币或过账状态，未进行金额猜测");var line=json.treeToValue(row,ErpLine.class);if(line.docstatus()!=1||line.voucherId().isBlank()||line.voucherId().length()>128||line.lineId().isBlank()||line.lineId().length()>128||line.description().isBlank()||line.description().length()>128||!Set.of("CNY","MXN","USD","EUR").contains(line.currency()))throw invalid("ERP明细契约校验失败，未将未过账记录视为实际费用");output.add(line);}return output;
        }catch(BusinessException e){throw e;}catch(InterruptedException e){Thread.currentThread().interrupt();throw new BusinessException(50301,"ERP费用只读请求中断");}catch(Exception e){throw new BusinessException(50301,"ERP费用只读连接或响应校验失败，未写入费用");}
    }
}
