package com.yuewei.plm.module.pilot;
import com.yuewei.plm.common.exception.BusinessException;import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.collaboration.CollaborationTypes.*;import com.yuewei.plm.module.collaboration.MoldScheduleService;
import jakarta.servlet.http.HttpServletRequest;import java.util.*;import lombok.RequiredArgsConstructor;import org.springframework.jdbc.core.JdbcTemplate;import org.springframework.stereotype.Service;

@Service @RequiredArgsConstructor
public class PilotMobileTaskService {
 private final JdbcTemplate jdbc;private final PilotAccessService access;private final MoldScheduleService schedules;
 public PageVO<Map<String,Object>> page(int page,int size,String keyword){access.requirePermission("pilot:tasks");String scope=access.visibleSqlClause("mold","s.mold_set_id");String from=" from plm_collaboration_mold_set s join plm_collaboration_item i on i.item_id=s.item_id left join plm_collaboration_mold_part pc on pc.mold_set_id=s.mold_set_id and pc.part_type='PC' left join plm_collaboration_mold_part tpu on tpu.mold_set_id=s.mold_set_id and tpu.part_type='TPU' where s.deleted_flag=0 and i.deleted_flag=0 and ("+scope+") and concat_ws(' ',i.style_name,i.compatible_models,s.set_name) ilike ?";String pattern="%"+Objects.toString(keyword,"").trim().replace("%","\\%").replace("_","\\_")+"%";
  long count=jdbc.queryForObject("select count(*)"+from,Long.class,pattern);
  String select="select s.mold_set_id \"moldSetId\",s.item_id \"itemId\","+com.yuewei.plm.module.collaboration.CollaborationRepository.assetSql()+" \"assetNumber\",s.set_name \"setName\",i.style_name \"styleName\",i.compatible_models \"compatibleModels\",s.planned_mold_delivery_date \"plannedMoldDeliveryDate\",s.actual_ship_date \"actualShipDate\",s.actual_supplier_trial_date \"actualSupplierTrialDate\",s.pc_signed_date \"pcSignedDate\",s.tpu_signed_date \"tpuSignedDate\",pc.status \"pcStatus\",tpu.status \"tpuStatus\",pc.current_location \"pcCurrentLocation\",tpu.current_location \"tpuCurrentLocation\",pc.factory_arrival_date \"pcFactoryArrivalDate\",tpu.factory_arrival_date \"tpuFactoryArrivalDate\",pc.acceptance_status \"pcAcceptanceStatus\",tpu.acceptance_status \"tpuAcceptanceStatus\",pc.acceptance_date \"pcAcceptanceDate\",tpu.acceptance_date \"tpuAcceptanceDate\",pc.acceptance_issues \"pcAcceptanceIssues\",tpu.acceptance_issues \"tpuAcceptanceIssues\"";
  return new PageVO<>(jdbc.queryForList(select+from+" order by s.updated_at desc,s.mold_set_id desc limit ? offset ?",pattern,size,(long)(page-1)*size),page,size,count,(count+size-1)/size);
 }
 public Object save(long id,String action,RowPatch patch,HttpServletRequest request){
  access.requirePermission("task:"+action);access.requireMold(id);
  if(!patch.entityType().equals("mold_set")||patch.id()!=id)throw new BusinessException(40103,"手机任务不能修改其他对象");
  return schedules.saveScopedTask(action,patch,request);
 }
 public List<Map<String,Object>> files(long moldId){access.requirePermission("file:read");access.requireMold(moldId);return jdbc.queryForList("select a.attachment_id \"attachmentId\",a.original_file_name \"fileName\",a.file_category \"fileCategory\",a.version_no \"versionNo\" from plm_attachment a where a.deleted_flag=0 and ("+access.visibleSqlClause("file","a.attachment_id")+") and (a.owner_object_id in(select ip.project_id from plm_collaboration_item_project ip join plm_collaboration_mold_set s on s.item_id=ip.item_id where s.mold_set_id=?) or a.owner_object_id=(select i.product_line_id from plm_collaboration_mold_set s join plm_collaboration_item i on i.item_id=s.item_id where s.mold_set_id=?)) and a.owner_object_type in('Product','Project','PRODUCT','PROJECT','product','project') order by a.attachment_id desc",moldId,moldId);}
}
