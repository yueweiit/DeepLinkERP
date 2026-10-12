package com.yuewei.plm.module.development;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import lombok.RequiredArgsConstructor;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.multipart.MultipartFile;
import static com.yuewei.plm.module.development.DevelopmentTypes.*;
import static com.yuewei.plm.module.development.DevelopmentFinanceMath.*;

/** Reuses XLSX preview/explicit mapping and the unified save path; never changes source workbooks. */
@Service @RequiredArgsConstructor
public class DevelopmentFinanceImportService {
    private final DevelopmentFinanceService finance;
    private final DevelopmentErpReadClient erpRead;
    private record Session(long userId,Instant expires,String hash,List<Map<String,Object>> rows,List<ErpLine> erp) {}
    private final Map<String,Session> sessions=new ConcurrentHashMap<>();
    private static final LinkedHashMap<String,String> HEADERS=new LinkedHashMap<>();
    static {
        HEADERS.put("预算ID","budgetId");HEADERS.put("产品平台ID","productLineId");HEADERS.put("协作档案ID","itemId");HEADERS.put("模具套ID","moldSetId");HEADERS.put("父预算ID","parentBudgetId");
        HEADERS.put("款式","budgetName");HEADERS.put("预算名称","budgetName");HEADERS.put("原币","currencyCode");HEADERS.put("预算类型","budgetKind");HEADERS.put("测算方式","calculationMode");
        HEADERS.put("手工预算","budgetAmount");HEADERS.put("模具成本","moldCost");HEADERS.put("模具重量","moldWeight");HEADERS.put("运输单价","transportRate");HEADERS.put("燃油单价","fuelRate");
        HEADERS.put("清关成本","customsCost");HEADERS.put("产品单价","salePrice");HEADERS.put("单个产品生产成本","unitProductionCost");HEADERS.put("备注","notes");
    }
    private static String header(String value){String s=value.replaceAll("\\s","");if(s.startsWith("快递运输成本"))return "transportFormula";if(s.startsWith("燃油附加费"))return "fuelFormula";return HEADERS.get(s);}
    private String hash(byte[] bytes){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}catch(Exception e){throw new IllegalStateException(e);}}
    private Map<String,Object> session(List<Map<String,Object>> rows,List<ErpLine> erp,String hash){sessions.entrySet().removeIf(e->e.getValue().expires.isBefore(Instant.now()));if(sessions.size()>100)throw invalid("预览任务过多，请稍后再试");String token=UUID.randomUUID().toString();sessions.put(token,new Session(finance.access().actorId(),Instant.now().plusSeconds(1800),hash,rows,erp));return Map.of("token",token,"rows",rows,"total",rows.size(),"fileHash",hash,"note","预览不写正式预算/费用，必须逐行确认核算对象；不按金额匹配");}
    private Session get(String token,boolean erp){Session s=sessions.get(token);if(s==null||s.userId!=finance.access().actorId()||s.expires.isBefore(Instant.now())||(erp?s.erp==null:s.erp!=null))throw invalid("预览已过期或不属于当前账号，请重新上传");return s;}
    public Map<String,Object> previewBudget(MultipartFile file) {
        finance.access().requireFinanceRead();if(file.isEmpty()||file.getSize()>20*1024*1024||!Objects.toString(file.getOriginalFilename(),"").toLowerCase(Locale.ROOT).endsWith(".xlsx"))throw invalid("请选择不超过20MB的XLSX文件");
        try {byte[] bytes=file.getBytes();List<Map<String,Object>> rows=new ArrayList<>();DataFormatter formatter=new DataFormatter(Locale.ROOT);
            try(Workbook workbook=WorkbookFactory.create(new java.io.ByteArrayInputStream(bytes))) {
                FormulaEvaluator evaluator=workbook.getCreationHelper().createFormulaEvaluator();
                for(Sheet sheet:workbook) {
                    Map<Integer,String> columns=new LinkedHashMap<>();int headerRow=-1;
                    for(int n=0;n<=Math.min(sheet.getLastRowNum(),10);n++){Row r=sheet.getRow(n);if(r==null)continue;Map<Integer,String> candidate=new LinkedHashMap<>();for(Cell c:r){String key=header(formatter.formatCellValue(c));if(key!=null)candidate.put(c.getColumnIndex(),key);}if(candidate.containsValue("budgetName")&&(candidate.containsValue("moldCost")||candidate.containsValue("budgetAmount"))){columns=candidate;headerRow=n;break;}}
                    if(headerRow<0)continue;
                    for(int n=headerRow+1;n<=sheet.getLastRowNum();n++){Row r=sheet.getRow(n);if(r==null)continue;Map<String,String> raw=new LinkedHashMap<>(),formulas=new LinkedHashMap<>();
                        for(var col:columns.entrySet()){Cell c=r.getCell(col.getKey());raw.put(col.getValue(),c==null?"":formatter.formatCellValue(c,evaluator));if(c!=null&&c.getCellType()==CellType.FORMULA)formulas.put(col.getValue(),c.getCellFormula());}
                        if(raw.values().stream().allMatch(String::isBlank))continue;if(rows.size()>=2000)throw invalid("一次最多预览2000行");
                        List<String> issues=new ArrayList<>();Map<String,JsonNode> values=new LinkedHashMap<>();String mode=raw.getOrDefault("calculationMode",raw.containsKey("moldCost")?"mold_formula":"manual"),currency=raw.getOrDefault("currencyCode","CNY").trim().toUpperCase(Locale.ROOT);
                        values.put("calculationMode",finance.json().valueToTree(mode));values.put("budgetName",finance.json().valueToTree(raw.get("budgetName")));
                        for(String key:List.of("budgetAmount","moldCost","moldWeight","customsCost","salePrice","unitProductionCost","notes"))if(raw.containsKey(key)){String v=raw.get(key);try{Cell c=null;for(var column:columns.entrySet())if(column.getValue().equals(key))c=r.getCell(column.getKey());JsonNode parsed;if(key.equals("notes"))parsed=finance.json().valueToTree(v.isBlank()?null:v);else if(c!=null&&c.getCellType()==CellType.NUMERIC)parsed=finance.json().valueToTree(BigDecimal.valueOf(c.getNumericCellValue()));else if(c!=null&&c.getCellType()==CellType.FORMULA){CellValue evaluated=evaluator.evaluate(c);if(evaluated==null||evaluated.getCellType()!=CellType.NUMERIC)throw invalid("公式结果不是数字");parsed=finance.json().valueToTree(BigDecimal.valueOf(evaluated.getNumberValue()));}else parsed=finance.json().valueToTree(v.isBlank()?null:new BigDecimal(v.replace(",","")));values.put(key,parsed);}catch(Exception e){issues.add(key+"不是有效数字，请修正");values.put(key,finance.json().valueToTree(v));}}
                        String kind=raw.getOrDefault("budgetKind","platform");Long budget=id(raw.get("budgetId"),issues),product=id(raw.get("productLineId"),issues),item=id(raw.get("itemId"),issues),mold=id(raw.get("moldSetId"),issues),parent=id(raw.get("parentBudgetId"),issues);
                        Map<String,Object> existing=budget==null?null:finance.detail("budget",budget);Map<String,JsonNode> before=new LinkedHashMap<>();if(existing!=null){for(String key:values.keySet())before.put(key,finance.json().valueToTree(existing.get(key)));product=(Long)existing.get("productLineId");item=(Long)existing.get("itemId");mold=(Long)existing.get("moldSetId");parent=(Long)existing.get("parentBudgetId");currency=existing.get("currencyCode").toString();kind=existing.get("budgetKind").toString();}
                        else issues.add("原表款式不是手机型号/实物套；请选择唯一产品平台或明确档案，不按名称/金额自动建模具");
                        if(mode.equals("mold_formula")){values.put("transportRate",importRate(raw,"transportRate",currency,TRANSPORT_RATE,existing,issues));values.put("fuelRate",importRate(raw,"fuelRate",currency,FUEL_RATE,existing,issues));
                            if(existing!=null)for(String key:List.of("transportRate","fuelRate"))before.put(key,finance.json().valueToTree(existing.get(key)));
                            if(raw.containsKey("transportFormula")||raw.containsKey("fuelFormula"))issues.add("原表表头71/33.2与公式不同；按用户确认运输74.68、燃油33.18 CNY/KG核对，不采用表头旧值");}
                        if(!Set.of("platform","mold").contains(kind)||!Set.of("CNY","MXN","USD","EUR").contains(currency))issues.add("预算类型/币种须人工核对");
                        var data=new LinkedHashMap<String,Object>();data.put("sheetName",sheet.getSheetName());data.put("rowNo",n+1);data.put("name",raw.get("budgetName"));data.put("kind",kind);data.put("currency",currency);data.put("budgetId",budget);data.put("productLineId",product);data.put("itemId",item);data.put("moldSetId",mold);data.put("parentBudgetId",parent);data.put("raw",raw);data.put("formulas",formulas);data.put("values",values);data.put("before",before);data.put("issues",issues);
                        var math=new LinkedHashMap<String,Object>();values.forEach((k,v)->math.put(k,v.isNull()?null:v.asText()));math.put("budgetKind",kind);try{calculate(math);}catch(NumberFormatException e){issues.add("无效金额导致暂不能测算，请修正数值");}data.put("calculatedTotal",math.get("calculatedTotal"));data.put("breakEvenQuantity",math.get("breakEvenQuantity"));rows.add(data);
                    }
                }
            }
            if(rows.isEmpty())throw invalid("未找到预算数据行，请使用预算模板或原模具成本预算表");return session(rows,null,hash(bytes));
        }catch(com.yuewei.plm.common.exception.BusinessException e){throw e;}catch(Exception e){throw invalid("无法读取预算XLSX，请检查表头、公式和数字格式");}
    }
    private JsonNode importRate(Map<String,String> raw,String key,String currency,BigDecimal cnyDefault,Map<String,Object> existing,List<String> issues){
        if(!raw.containsKey(key))return finance.json().valueToTree(existing!=null?existing.get(key):"CNY".equals(currency)?cnyDefault:null);
        String value=raw.get(key);if(value.isBlank())return finance.json().nullNode();
        try{return finance.json().valueToTree(new BigDecimal(value.replace(",","")));}catch(NumberFormatException e){issues.add(key+"不是有效数字，请修正");return finance.json().valueToTree(value);}
    }
    private Long id(String value,List<String> issues){if(value==null||value.isBlank())return null;try{return new BigDecimal(value).longValueExact();}catch(Exception e){issues.add("核算对象ID无效");return null;}}
    public Map<String,Object> commitBudget(ImportCommit dto,HttpServletRequest request) {
        finance.access().requireFinanceWrite();Session s=get(dto.token(),false);
        return new TransactionTemplate(finance.transactionManager()).execute(tx->{finance.jdbc().queryForList("select pg_advisory_xact_lock(hashtextextended(?,0))","development-budget:"+s.hash);int saved=0,skipped=0;Set<String> seen=new HashSet<>();
            for(var d:dto.rows()){String key=d.sheetName()+":"+d.rowNo();if(!seen.add(key))throw invalid("同一来源行不能重复提交");var original=s.rows.stream().filter(r->r.get("sheetName").equals(d.sheetName())&&same(r.get("rowNo"),d.rowNo())).findFirst().orElseThrow(()->invalid("预览行不存在"));
                if(d.skip()||finance.jdbc().queryForObject("select count(*) from plm_development_finance_import where file_hash=? and import_kind='budget' and source_sheet=? and source_row=?",Long.class,s.hash,d.sheetName(),d.rowNo())>0){skipped++;continue;}
                if(d.reason()==null||d.reason().isBlank())throw invalid("第"+d.rowNo()+"行须填写核对和映射说明");long target;boolean created=d.budgetId()==null;
                String kind=d.kind()==null?original.get("kind").toString():d.kind();if(!Set.of("platform","mold").contains(kind))throw invalid("第"+d.rowNo()+"行须明确选择平台或模具预算层级");
                if(created){var row=finance.createBudget(new CreateBudget(kind,d.name(),d.productLineId(),d.itemId(),d.moldSetId(),d.parentBudgetId(),original.get("currency").toString()),request);target=((Number)row.get("budgetId")).longValue();}else target=d.budgetId();
                var current=finance.detail("budget",target);if(!created&&d.kind()!=null&&!d.kind().equals(current.get("budgetKind")))throw invalid("已有预算层级固定，不能通过导入改变平台/模具归属");
                List<Change> changes=new ArrayList<>();for(var e:d.values().entrySet()){if(!created&&!d.before().containsKey(e.getKey()))throw invalid("更新已有预算须携带预览原值，不覆盖后续修改");changes.add(new Change(e.getKey(),created?finance.json().valueToTree(current.get(e.getKey())):d.before().get(e.getKey()),e.getValue()));}
                if(!changes.isEmpty()){var result=finance.save("budget",new Batch(List.of(new Patch(target,changes,d.reason()))),request).get(0);if(!result.status().equals("saved"))throw invalid("第"+d.rowNo()+"行："+result.message());}
                finance.jdbc().update("insert into plm_development_finance_import(file_hash,import_kind,source_sheet,source_row,entity_id,created_by) values(?,'budget',?,?,?,?)",s.hash,d.sheetName(),d.rowNo(),target,finance.access().actor().username());saved++;
            }return Map.of("saved",saved,"skipped",skipped,"duplicate",saved==0);});
    }
    public Map<String,Object> previewErp(ErpPreview dto) {
        finance.access().requireFinanceRead();Set<String> seen=new HashSet<>();List<Map<String,Object>> rows=new ArrayList<>();int n=0;
        for(var line:dto.rows()){if(!seen.add(line.voucherId()+"\u0000"+line.lineId()))throw invalid("ERP单据明细ID重复，不能按金额去重");if(line.docstatus()!=1)throw invalid("只接受ERP已过账明细");amount(finance.json().valueToTree(line.postedAmount()),2,true);
            var row=new LinkedHashMap<String,Object>();row.put("rowNo",++n);row.put("voucherId",line.voucherId());row.put("lineId",line.lineId());row.put("description",line.description());row.put("currency",line.currency());row.put("postedAmount",line.postedAmount());row.put("reversalOf",line.reversalOf());row.put("issues",List.of("只读ERP来源预览；必须按单据明细ID及资料确认归属，不按金额或颜色自动匹配"));rows.add(row);}
        return session(rows,dto.rows(),hash(finance.encode(dto.rows()).getBytes(java.nio.charset.StandardCharsets.UTF_8)));
    }
    public Map<String,Object> refreshErp(){finance.access().requireFinanceRead();if(!erpRead.configured())return Map.of("status","not_configured","message","ERP只读费用接口尚未配置；没有调用外部服务器，也未写入正式费用");var result=new LinkedHashMap<>(previewErp(new ErpPreview(erpRead.read())));result.put("status","preview_ready");return result;}
    public Map<String,Object> commitErp(ErpCommit dto,HttpServletRequest request) {
        finance.access().requireFinanceWrite();finance.access().requireFinanceConfirm();Session s=get(dto.token(),true);
        return new TransactionTemplate(finance.transactionManager()).execute(tx->{int saved=0,skipped=0;Set<Integer> seen=new HashSet<>();
            for(var d:dto.rows()){if(!seen.add(d.rowNo())||d.rowNo()>s.erp.size())throw invalid("ERP预览行不存在或重复");if(d.skip()){skipped++;continue;}var line=s.erp.get(d.rowNo()-1);String fingerprint=hash(finance.encode(line).getBytes(java.nio.charset.StandardCharsets.UTF_8));
                finance.jdbc().queryForList("select pg_advisory_xact_lock(hashtextextended(?,0))","erp-posting:"+line.voucherId()+":"+line.lineId());
                var existing=finance.jdbc().queryForList("select project_cost_item_id,erp_fingerprint from plm_project_cost_item where source_system='erp' and erp_voucher_id=? and erp_line_id=?",line.voucherId(),line.lineId());
                if(!existing.isEmpty()){if(!fingerprint.equals(existing.get(0).get("erp_fingerprint")))throw invalid("ERP已存在同单据明细不同内容，未覆盖；请核对冲销及新明细ID");skipped++;continue;}
                var actor=finance.access().actor();var created=finance.createExpense(new CreateExpense(line.description(),d.productLineId(),d.itemId(),d.moldSetId(),d.budgetId(),line.currency()),request);long id=((Number)created.get("expenseId")).longValue();
                finance.jdbc().update("update plm_project_cost_item set source_system='erp',erp_voucher_id=?,erp_line_id=?,erp_posted_amount=?,erp_posted_at=?,erp_reversal_of=?,erp_fingerprint=?,status='confirmed',confirmed_at=current_timestamp,confirmed_by=? where project_cost_item_id=?",line.voucherId(),line.lineId(),line.postedAmount(),line.postedAt(),line.reversalOf(),fingerprint,actor.username(),id);
                finance.history("expense",id,null,"__erp_posted",null,finance.detail("expense",id),d.mappingReason(),actor);saved++;
            }return Map.of("saved",saved,"skipped",skipped,"duplicate",saved==0);});
    }
    public byte[] exportBudgets(Query query) {
        finance.access().requireFinanceExport();try(Workbook workbook=new XSSFWorkbook();ByteArrayOutputStream output=new ByteArrayOutputStream()){Sheet sheet=workbook.createSheet("预算模板");List<Map.Entry<String,String>> columns=HEADERS.entrySet().stream().filter(e->!e.getKey().equals("款式")).toList();Row header=sheet.createRow(0);for(int n=0;n<columns.size();n++){header.createCell(n).setCellValue(columns.get(n).getKey());sheet.setColumnWidth(n,20*256);}int target=1,page=1;query.setSize(100);while(true){query.setPage(page++);var result=finance.page("budget",query);for(var row:result.getContent()){Row out=sheet.createRow(target++);for(int n=0;n<columns.size();n++){Object v=row.get(columns.get(n).getValue());if(v instanceof BigDecimal number)out.createCell(n).setCellValue(number.doubleValue());else if(v!=null)out.createCell(n).setCellValue(v.toString());}}if(page>result.getTotalPages())break;}workbook.write(output);return output.toByteArray();}catch(Exception e){throw invalid("预算导出失败");}
    }
}
