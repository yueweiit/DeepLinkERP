package com.yuewei.plm.module.collaboration;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yuewei.plm.common.security.CurrentUser;
import jakarta.servlet.http.HttpServletRequest;
import java.io.ByteArrayOutputStream;
import java.security.MessageDigest;
import java.time.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import lombok.RequiredArgsConstructor;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.multipart.MultipartFile;
import static com.yuewei.plm.module.collaboration.CollaborationFields.*;
import static com.yuewei.plm.module.collaboration.CollaborationTypes.*;

@Service
@RequiredArgsConstructor
public class CollaborationImportService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final CollaborationService service;
    private final CollaborationRepository repository;
    private final org.springframework.transaction.PlatformTransactionManager transactionManager;
    private final Map<String,Session> sessions=new ConcurrentHashMap<>();
    record PreviewRow(int rowNo,String sheetName,Map<String,String> raw,Map<String,JsonNode> values,
                      Long itemId,Long moldSetId,Long productLineId,String styleName,String brand,String compatibleModels,
                      boolean newMoldSet,boolean alreadyImported,List<String> issues,Map<String,JsonNode> before) {}
    record Session(long userId,Instant expiresAt,String hash,String kind,String fileName,List<PreviewRow> rows) {}

    public Map<String,Object> preview(String kind,MultipartFile file) {
        return preview(kind,file,"true","true");
    }
    public Map<String,Object> preview(String kind,MultipartFile file,String itemScope,String moldScope) {
        CurrentUser actor=service.actor();checkKind(kind);
        if(file.isEmpty()||file.getSize()>20*1024*1024) throw invalid("请选择不超过 20MB 的 XLSX 文件");
        if(!Objects.toString(file.getOriginalFilename(),"").toLowerCase(Locale.ROOT).endsWith(".xlsx")) throw invalid("本页只支持 XLSX 文件");
        sessions.entrySet().removeIf(e->e.getValue().expiresAt.isBefore(Instant.now()));
        if(sessions.size()>100) throw invalid("预览任务过多，请稍后重试");
        try {
            byte[] bytes=file.getBytes();String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
            List<PreviewRow> rows;
            try(Workbook workbook=WorkbookFactory.create(new java.io.ByteArrayInputStream(bytes))) {rows=read(workbook,kind,hash,itemScope,moldScope);}
            if(rows.isEmpty()) throw invalid("未找到数据行，请检查表头和工作表");
            String token=UUID.randomUUID().toString();Session session=new Session(actor.userId(),Instant.now().plusSeconds(1800),hash,kind,file.getOriginalFilename(),rows);
            sessions.put(token,session);
            return Map.of("importToken",token,"kind",kind,"fileName",Objects.toString(file.getOriginalFilename(),""),"rows",rows,
                "total",rows.size(),"needsReview",rows.stream().filter(r->!r.issues.isEmpty()&&!r.alreadyImported).count());
        } catch(com.yuewei.plm.common.exception.BusinessException e) {throw e;}
        catch(Exception e) {throw invalid("无法读取 XLSX 文件，请检查文件格式或日期："+Objects.toString(e.getMessage(),"读取错误"));}
    }
    private List<PreviewRow> read(Workbook workbook,String kind,String hash,String itemScope,String moldScope) {
        List<Map<String,Object>> items=repository.previewRows("item",itemScope);
        List<Map<String,Object>> sets=repository.previewRows("mold_set",moldScope);
        List<Map<String,Object>> imported=jdbc.queryForList("select r.sheet_name,r.row_no,r.item_id,r.mold_set_id from plm_collaboration_import_row r join plm_collaboration_import_batch b on b.batch_id=r.batch_id where b.file_hash=? and b.import_kind=?",hash,kind);
        List<PreviewRow> out=new ArrayList<>();Set<String> seen=new HashSet<>();
        for(Sheet sheet:workbook) {
            int header=-1;Map<Integer,String> headers=new LinkedHashMap<>();
            for(int r=0;r<=Math.min(sheet.getLastRowNum(),10);r++) {
                Row row=sheet.getRow(r);if(row==null) continue;Map<Integer,String> candidate=new LinkedHashMap<>();
                for(Cell cell:row) {String key=header(text(cell));if(key!=null) candidate.put(cell.getColumnIndex(),key);}
                if(kind.equals("schedule")&&text(row.getCell(0)).equals("序号")&&text(row.getCell(3)).equals("模具制作时间")) {
                    candidate=new LinkedHashMap<>();String[] keys={"sequence","styleName","compatibleModels","manufacturingDays","openedDate","ownerUserId","holidayDays","extraDays","plannedMoldDeliveryDate","transportDays","plannedFactoryArrivalDate","logisticsOwnerUserId","plannedAcceptanceDate","mexicoOwnerUserId","plannedProductionDate","productionOwnerUserId"};
                    for(int c=0;c<keys.length;c++) candidate.put(c,keys[c]);
                }
                if(candidate.containsValue("itemId")||(candidate.containsValue("styleName")&&candidate.containsValue("compatibleModels"))) {header=r;headers=candidate;break;}
            }
            if(header<0) continue;
            for(int r=header+1;r<=sheet.getLastRowNum();r++) {
                Row row=sheet.getRow(r);if(row==null) continue;
                Map<String,String> raw=new LinkedHashMap<>();headers.forEach((column,key)->raw.put(key,text(row.getCell(column))));
                if(raw.values().stream().allMatch(String::isBlank)) continue;
                if(kind.equals("schedule")&&raw.containsKey("sequence")&&!raw.get("sequence").matches("[0-9]+")) continue;
                if(out.size()>=2000) throw invalid("一次最多预览 2000 行，请分批上传");
                List<String> issues=new ArrayList<>();Map<String,JsonNode> values=new LinkedHashMap<>();
                for(Field f:isMold(kind)?MOLD:ITEM) {
                    if(!raw.containsKey(f.key())||!included(kind,f)) continue;
                    String value=raw.get(f.key());
                    if(value.isBlank()&&(f.key().equals("setName")||List.of("part_status","acceptance").contains(f.kind()))) continue;
                    if(f.key().equals("notes")) value=joinNotes(raw);
                    if(f.kind().equals("date")) {
                        Integer column=headers.entrySet().stream().filter(e->e.getValue().equals(f.key())).map(Map.Entry::getKey).findFirst().orElse(null);
                        Cell cell=column==null?null:row.getCell(column);
                        value=dateText(cell,workbook);
                        if(f.key().equals("plannedFactoryArrivalDate")&&cell!=null&&cell.getCellType()==CellType.FORMULA)
                            issues.add("原表到厂日期为公式建议，须由负责人确认，不自动作为到厂承诺");
                        if(kind.equals("schedule")&&cell!=null&&cell.getCellType()==CellType.FORMULA&&!f.key().equals("plannedFactoryArrivalDate")) issues.add(f.label()+"为公式建议，须人工确认后采用");
                    }
                    try {Object normal=normalise(f,json.valueToTree(value));values.put(f.key(),json.valueToTree(normal));}
                    catch(RuntimeException e) {issues.add(f.label()+"："+e.getMessage());values.put(f.key(),json.valueToTree(value));}
                }
                if(kind.equals("delivery")&&raw.containsKey("observation")) values.put("notes",json.valueToTree(joinNotes(raw)));
                if(kind.equals("market")&&values.get("phonePrice")!=null&&!values.get("phonePrice").isNull()&&
                    (values.get("priceCurrency")==null||values.get("priceCurrency").isNull())) {
                    values.put("priceCurrency",json.valueToTree("UNKNOWN"));issues.add("价格币种待确认，不根据 $ 符号猜测币种");
                }
                String style=raw.getOrDefault("styleName","").trim(), model=raw.getOrDefault("compatibleModels","").trim(), brand=raw.getOrDefault("brand","").trim();
                if(kind.equals("schedule")) {
                    if(model.contains("/")||model.contains("＋")||model.contains("+")) issues.add("合写手机型号不代表已确认共模，须选择兼容型号档案并明确确认兼容关系");
                    if(raw.containsKey("transportDays")&&!raw.get("transportDays").isBlank()&&!raw.get("transportDays").equals("7")) issues.add("原表运输周期不是默认 7 天，需核对后手工确认到厂日期");
                    if(defaultCycleMismatch(style,values)) issues.add("制作周期与原表款式默认值不同，请核对款式及天数");
                }
                if(brand.isBlank()&&brandFromModel(model)!=null) {brand=brandFromModel(model);if(kind.equals("market")) values.put("brand",json.valueToTree(brand));}
                Long itemId=id(raw.get("itemId"),issues),setId=id(raw.get("moldSetId"),issues),lineId=id(raw.get("productLineId"),issues);
                boolean newSet=raw.getOrDefault("newMoldSet","").matches("(?i)true|1|是");
                if(itemId==null) {
                    List<Map<String,Object>> matches=items.stream().filter(i->style.equalsIgnoreCase(i.get("styleName").toString().trim())&&model.equalsIgnoreCase(i.get("compatibleModels").toString().trim())).toList();
                    if(matches.size()==1) itemId=((Number)matches.get(0).get("itemId")).longValue();
                    else issues.add(matches.isEmpty()?"未匹配现有档案，请确认款式映射或选择已有档案":"存在多个匹配档案，请人工选择");
                }
                Map<String,JsonNode> before=new LinkedHashMap<>();
                if(itemId!=null) {
                    try {
                        long targetId=itemId;
                        Map<String,Object> target=items.stream().filter(i->same(i.get("itemId"),targetId)).findFirst().orElseThrow();lineId=(Long)target.get("productLineId");
                        if(!style.isBlank()&&!style.equalsIgnoreCase(target.get("styleName").toString())) issues.add("原表款式与所选档案不同，请核对别名");
                        if(!model.isBlank()&&!model.equalsIgnoreCase(target.get("compatibleModels").toString())) issues.add("原表型号与所选档案不同，请确认兼容关系");
                        if(!isMold(kind)) values.keySet().forEach(k->before.put(k,json.valueToTree(target.get(k))));
                        if(isMold(kind)&&setId==null&&!newSet) {
                            long targetItemId=itemId;List<Map<String,Object>> matches=sets.stream().filter(s->((Number)s.get("itemId")).longValue()==targetItemId).toList();
                            if(matches.size()==1) setId=((Number)matches.get(0).get("moldSetId")).longValue();
                            else if(matches.size()>1) issues.add("该档案有多套模具，请选择本次对应的模具套");
                            else newSet=true;
                        }
                    } catch(RuntimeException e) {issues.add("档案 ID 无效，请重新选择");itemId=null;}
                }
                if(isMold(kind)&&setId!=null) {
                    try {long targetSetId=setId;Map<String,Object> set=sets.stream().filter(s->same(s.get("moldSetId"),targetSetId)).findFirst().orElseThrow();
                        if(itemId!=null&&!same(set.get("itemId"),itemId)) issues.add("模具套不属于所选档案");
                        for(String key:List.of("assetNumber","pcAssetNumber","tpuAssetNumber"))
                            if(raw.containsKey(key)&&!raw.get(key).isBlank()&&!same(raw.get(key),set.get(key))) issues.add("实物编号与模具套 ID 不一致，请人工重新确认映射（编号不能修改）");
                        values.keySet().forEach(k->before.put(k,json.valueToTree(set.get(k))));
                    } catch(RuntimeException e) {issues.add("模具套 ID 无效");}
                }
                if(model.matches(".*(复制|重新开模).*")) {issues.add("原表标记复制或重新开模，请确认兼容型号并新增独立模具套");newSet=true;setId=null;}
                if(brandConflict(brand,model)) issues.add("品牌与型号文字不一致，请确认后再导入");
                if(!seen.add(style.toLowerCase(Locale.ROOT)+"|"+model.toLowerCase(Locale.ROOT))) issues.add("文件内款式型号重复，请区分 PC/TPU 重复行与复制模具，累计数不能相加");
                if(isMold(kind)) {Map<String,Object> dates=new HashMap<>();values.forEach((k,v)->dates.put(k,v.isNull()?null:v.asText()));try {issues.addAll(dateWarnings(dates));}catch(RuntimeException ignored) {}}
                if(kind.equals("schedule")&&setId==null) {newSet=false;issues.add("排程导入不创建档案或实物套，请先建立或选择已人工确认的模具套");}
                int rowNo=r+1;String sheetName=sheet.getSheetName();
                Optional<Map<String,Object>> applied=imported.stream().filter(i->i.get("sheet_name").equals(sheetName)&&((Number)i.get("row_no")).intValue()==rowNo).findFirst();
                if(applied.isPresent()) {itemId=((Number)applied.get().get("item_id")).longValue();setId=(Long)applied.get().get("mold_set_id");}
                out.add(new PreviewRow(rowNo,sheetName,raw,values,itemId,setId,lineId,style,brand,model,newSet,applied.isPresent(),issues,before));
            }
        }
        return out;
    }
    public Map<String,Object> commit(String token,ImportCommit dto,HttpServletRequest request) {
        return commit(token,dto,request,null);
    }
    public Map<String,Object> commit(String token,ImportCommit dto,HttpServletRequest request,String expectedKind) {
        CurrentUser actor=service.actor();Session session=sessions.get(token);
        if(session==null||session.expiresAt.isBefore(Instant.now())||session.userId!=actor.userId()) throw invalid("预览已过期或不属于当前账号，请重新上传");
        if(expectedKind!=null&&!expectedKind.equals(session.kind)) throw invalid("预览类型与提交入口不一致，请重新上传");
        return new TransactionTemplate(transactionManager).execute(tx-> {
            jdbc.queryForObject("select pg_advisory_xact_lock(?)",(rs,n)->true,(long)(session.hash+session.kind).hashCode());
            Long batch=jdbc.queryForObject("insert into plm_collaboration_import_batch(file_hash,import_kind,file_name,imported_by) values(?,?,?,?) on conflict(file_hash,import_kind) do update set file_name=excluded.file_name returning batch_id",Long.class,session.hash,session.kind,session.fileName,actor.username());
            int saved=0,skipped=0;Set<String> seen=new HashSet<>();
            for(ImportDecision decision:dto.rows()) {
                if(!seen.add(decision.sheetName()+":"+decision.rowNo())) throw invalid("不能重复提交同一来源行");
                PreviewRow source=session.rows.stream().filter(r->r.rowNo==decision.rowNo()&&r.sheetName.equals(decision.sheetName())).findFirst().orElseThrow(()->invalid("来源行不存在"));
                if(decision.skip()) {skipped++;continue;}
                Long count=jdbc.queryForObject("select count(*) from plm_collaboration_import_row where batch_id=? and sheet_name=? and row_no=?",Long.class,batch,source.sheetName,source.rowNo);
                if(count!=null&&count>0) {skipped++;continue;}
                if(!source.issues.isEmpty()&&(decision.reviewReason()==null||decision.reviewReason().isBlank())) throw invalid("第 "+source.rowNo+" 行需要填写人工核对说明");
                if(session.kind.equals("schedule")) {
                    if(decision.itemId()==null||decision.moldSetId()==null||decision.newMoldSet()) throw invalid("排程只能更新已人工确认的档案及模具套，不自动建立实物");
                    if((source.compatibleModels.contains("/")||source.compatibleModels.contains("＋")||source.compatibleModels.contains("+"))&&!decision.confirmCompatibility()) throw invalid("第 "+source.rowNo+" 行须明确确认合写手机型号兼容关系");
                }
                Long itemId=decision.itemId();boolean created=false;
                if(itemId==null) {
                    Map<String,Object> row=service.createItem(new CreateItem(decision.productLineId(),decision.styleName(),decision.brand(),decision.compatibleModels(),null,null),request);
                    itemId=((Number)row.get("itemId")).longValue();created=true;
                } else repository.row("item",itemId);
                String entity=isMold(session.kind)?"mold_set":"item";long entityId=itemId;Long setId=null;boolean createdSet=false;
                if(entity.equals("mold_set")) {
                    if(decision.moldSetId()!=null&&!decision.newMoldSet()) {
                        Map<String,Object> set=repository.row("mold_set",decision.moldSetId());
                        if(!same(set.get("itemId"),itemId)) throw invalid("第 "+source.rowNo+" 行模具套与档案不一致");entityId=decision.moldSetId();
                    } else {
                        Map<String,Object> set=service.createMoldSet(itemId,new CreateMoldSet(null,null,null,decision.newMoldSet()?decision.moldSetId():null),request);
                        entityId=((Number)set.get("moldSetId")).longValue();createdSet=true;
                    }
                    setId=entityId;
                }
                Map<String,Object> current=repository.row(entity,entityId);List<CellChange> changes=new ArrayList<>();
                for(Map.Entry<String,JsonNode> entry:decision.values().entrySet()) {
                    Field f=field(entity,entry.getKey());if(!included(session.kind,f)) throw invalid("第 "+source.rowNo+" 行包含其他页签字段");
                    JsonNode before;
                    if(createdSet||created) before=json.valueToTree(current.get(f.key()));
                    else {
                        if(!decision.before().containsKey(f.key())) throw invalid("第 "+source.rowNo+" 行缺少原值，请重新选择目标或上传预览");
                        before=decision.before().get(f.key());
                    }
                    changes.add(new CellChange(f.key(),before,entry.getValue(),decision.reviewReason()));
                }
                if(!changes.isEmpty()) {
                    RowResult result=service.save(new BatchSave(List.of(new RowPatch(entity,entityId,changes))),request).get(0);
                    if(!result.status().equals("saved")) throw invalid("第 "+source.rowNo+" 行："+result.message());
                }
                jdbc.update("insert into plm_collaboration_import_row(batch_id,sheet_name,row_no,item_id,mold_set_id) values(?,?,?,?,?)",batch,source.sheetName,source.rowNo,itemId,setId);saved++;
            }
            return Map.of("batchId",batch,"saved",saved,"skipped",skipped,"duplicate",saved==0);
        });
    }
    public byte[] template(String kind) {
        return template(kind,new Query(),true);
    }
    public byte[] template(String kind,Query query,boolean blank) {
        return template(kind,query,blank,"true");
    }
    public byte[] template(String kind,Query query,boolean blank,String scope) {
        service.actor();checkKind(kind);
        query.setView(isMold(kind)?"delivery":kind);
        try(XSSFWorkbook wb=new XSSFWorkbook();ByteArrayOutputStream out=new ByteArrayOutputStream()) {
            Sheet sheet=wb.createSheet(kind.equals("schedule")?"开模时间管控":kind.equals("delivery")?"模具交付":kind.equals("production")?"累计产量":"市场资料");
            List<String> columns=new ArrayList<>(List.of("协作档案ID","产品款式","品牌","兼容手机型号"));
            if(isMold(kind)) {
                columns.addAll(List.of("模具套ID","实物编号","PC 实物编号","TPU 实物编号","新增模具套"));
                // Explicit part columns; never interpret inventory counts or notes as physical sets.
                for(Field f:MOLD) if(!List.of("pcMoldCodeId","tpuMoldCodeId","pcInventoryId","tpuInventoryId").contains(f.key())) columns.add(f.key().equals("ownerUserId")?"模具负责人ID":f.label());
            }
            else for(Field f:ITEM) if(included(kind,f)&&!List.of("styleName","brand","compatibleModels","productLineId").contains(f.key())) columns.add(f.label());
            Row row=sheet.createRow(0);CellStyle style=wb.createCellStyle();style.setFillForegroundColor(IndexedColors.DARK_BLUE.getIndex());style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
            Font font=wb.createFont();font.setBold(true);font.setColor(IndexedColors.WHITE.getIndex());style.setFont(font);
            CellStyle dateStyle=wb.createCellStyle();dateStyle.setDataFormat(wb.createDataFormat().getFormat("yyyy-mm-dd"));
            CellStyle textStyle=wb.createCellStyle();textStyle.setDataFormat(wb.createDataFormat().getFormat("@"));
            for(int c=0;c<columns.size();c++) {Cell cell=row.createCell(c);cell.setCellValue(columns.get(c));cell.setCellStyle(style);sheet.setColumnWidth(c,24*256);}
            if(!blank) {
                int n=1;
                for(Map<String,Object> record:repository.page(query,service.groups(service.actor()),scope).getContent()) {
                    Row exported=sheet.createRow(n++);
                    for(int c=0;c<columns.size();c++) {
                        String key=header(columns.get(c));Object value=key.equals("newMoldSet")?"否":record.get(key);
                        if(value==null) continue;
                        Cell cell=exported.createCell(c);
                        Field field=(isMold(kind)?MOLD:ITEM).stream().filter(f->f.key().equals(key)).findFirst().orElse(null);
                        if(field!=null&&field.kind().equals("date")) {cell.setCellValue(LocalDate.parse(value.toString()).atStartOfDay());cell.setCellStyle(dateStyle);}
                        else if(value instanceof Number number && !key.endsWith("Id")) cell.setCellValue(number.doubleValue());
                        else {cell.setCellValue(value.toString());cell.setCellStyle(textStyle);}
                    }
                }
            }
            sheet.createFreezePane(2,1);wb.write(out);return out.toByteArray();
        }catch(Exception e) {throw new IllegalStateException("无法生成协作模板",e);}
    }
    static boolean included(String kind,Field field) {
        return isMold(kind)||kind.equals("market")&&field.group().equals("market")||kind.equals("production")&&field.group().equals("production");
    }
    private static boolean isMold(String kind) {return Set.of("delivery","schedule").contains(kind);}
    private static boolean defaultCycleMismatch(String style,Map<String,JsonNode> values) {Integer days=MoldScheduleTypes.defaultDays(style);return days!=null&&values.containsKey("manufacturingDays")&&!values.get("manufacturingDays").isNull()&&values.get("manufacturingDays").asInt()!=days;}
    private static void checkKind(String kind) {if(!List.of("market","delivery","production","schedule").contains(kind)) throw invalid("未知导入页签");}
    static boolean brandConflict(String brand,String model) {
        String b=brand.trim().toLowerCase(Locale.ROOT),m=model.trim().toLowerCase(Locale.ROOT);
        if(b.isEmpty()||m.isEmpty()) return false;
        for(String prefix:List.of("oppo","xiaomi","honor","samsung","motorola","zte","apple","huawei","vivo","realme")) {
            if(m.startsWith(prefix)) return !b.equals(prefix)&&!(prefix.equals("apple")&&b.equals("iphone"));
        }
        return false;
    }
    private static String joinNotes(Map<String,String> raw) {
        String notes=raw.getOrDefault("notes","");String observation=raw.getOrDefault("observation","");
        return observation.isBlank()?notes:observation+(notes.isBlank()?"":"\n备注："+notes);
    }
    private static Long id(String text,List<String> issues) {
        if(text==null||text.isBlank()) return null;
        try {long id=new java.math.BigDecimal(text.trim()).longValueExact();if(id<1) throw new IllegalArgumentException();return id;}
        catch(RuntimeException e) {issues.add("ID 不是有效整数");return null;}
    }
    static String dateText(Cell cell,Workbook workbook) {
        if(cell==null) return "";
        CellType type=cell.getCellType()==CellType.FORMULA?cell.getCachedFormulaResultType():cell.getCellType();
        if(type==CellType.NUMERIC) {
            double serial=cell.getNumericCellValue();
            if(serial<=0||serial>100000) return text(cell);
            boolean use1904=workbook instanceof XSSFWorkbook x&&x.isDate1904();
            return DateUtil.getLocalDateTime(serial,use1904).toLocalDate().toString();
        }
        return text(cell);
    }
    private static String text(Cell cell) {
        if(cell==null) return "";
        if(cell.getCellType()==CellType.FORMULA) {
            return switch(cell.getCachedFormulaResultType()) {
                case NUMERIC -> DateUtil.isCellDateFormatted(cell)?DateUtil.getLocalDateTime(cell.getNumericCellValue()).toLocalDate().toString():java.math.BigDecimal.valueOf(cell.getNumericCellValue()).stripTrailingZeros().toPlainString();
                case STRING -> cell.getStringCellValue();default -> "";
            };
        }
        return new DataFormatter(Locale.ROOT).formatCellValue(cell).trim();
    }
    static String header(String text) {
        String clean=text.trim().replaceAll("\\s+","");
        // The supplied delivery workbook uses Chinese + Spanish in the same header cell.
        // Match only its explicit Chinese prefix; do not interpret spreadsheet contents as instructions.
        String chinesePrefix=clean.replaceFirst("[^\\p{IsHan}].*$","");
        if(!chinesePrefix.isBlank()&&!clean.endsWith("ID")) clean=chinesePrefix;
        for(Field f:ITEM) if(clean.equals(f.key())||clean.equals(f.label().replace(" ",""))) return f.key();
        for(Field f:MOLD) if(clean.equals(f.key())||clean.equals(f.label().replace(" ",""))) return f.key();
        return switch(clean) {
            case "协作档案ID","档案ID","itemId" -> "itemId";
            case "模具套ID","moldSetId" -> "moldSetId";
            case "实物编号","assetNumber" -> "assetNumber";
            case "PC实物编号","pcAssetNumber" -> "pcAssetNumber";
            case "TPU实物编号","tpuAssetNumber" -> "tpuAssetNumber";
            case "产品线ID","productLineId" -> "productLineId";
            case "模具负责人ID" -> "ownerUserId";
            case "新增模具套","newMoldSet" -> "newMoldSet";
            case "款式","产品类型","TipodeProducto" -> "styleName";
            case "型号","手机型号","Modelo型号" -> "compatibleModels";
            case "计划到达工厂日期","计划到工厂时间","计划到墨西哥工厂日期" -> "plannedFactoryArrivalDate";
            case "实际发模日期","发模日期" -> "actualShipDate";
            case "抵达墨西哥","实际抵达墨西哥日期" -> "actualMexicoArrivalDate";
            case "观察" -> "observation";
            case "备注","市场备注","模具备注" -> "notes";
            case "半成品PC累计","PC半成品累计" -> "pcTotal";
            case "半成品TPU累计","TPU半成品累计" -> "tpuTotal";
            default -> null;
        };
    }
}
