package com.yuewei.plm.module.development;

import com.yuewei.plm.common.util.RequestIdUtil;
import com.yuewei.plm.common.vo.ResponseVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import static com.yuewei.plm.module.development.DevelopmentTypes.*;

@RestController @Validated @RequiredArgsConstructor
public class DevelopmentFinanceController {
    private final DevelopmentFinanceService finance;
    private final DevelopmentFinanceImportService imports;
    private <T> ResponseVO<T> ok(T value,HttpServletRequest request){return ResponseVO.success(value,RequestIdUtil.getRequestId(request),OffsetDateTime.now());}
    @GetMapping("/api/v1/development-budgets") public ResponseVO<?> budgets(@Valid Query query,HttpServletRequest r){return ok(finance.page("budget",query),r);}
    @GetMapping("/api/v1/development-expenses") public ResponseVO<?> expenses(@Valid Query query,HttpServletRequest r){return ok(finance.page("expense",query),r);}
    @GetMapping("/api/v1/development-budgets/options") public ResponseVO<?> options(HttpServletRequest r){return ok(finance.options(),r);}
    @GetMapping("/api/v1/development-budgets/summary") public ResponseVO<?> budgetSummary(@Valid Query q,HttpServletRequest r){return ok(finance.summary("budget",q),r);}
    @GetMapping("/api/v1/development-expenses/summary") public ResponseVO<?> expenseSummary(@Valid Query q,HttpServletRequest r){return ok(finance.summary("expense",q),r);}
    @PostMapping("/api/v1/development-budgets") public ResponseVO<?> createBudget(@Valid @RequestBody CreateBudget dto,HttpServletRequest r){return ok(finance.createBudget(dto,r),r);}
    @PostMapping("/api/v1/development-expenses") public ResponseVO<?> createExpense(@Valid @RequestBody CreateExpense dto,HttpServletRequest r){return ok(finance.createExpense(dto,r),r);}
    @PostMapping("/api/v1/development-budgets/batch-save") public ResponseVO<?> saveBudgets(@Valid @RequestBody Batch dto,HttpServletRequest r){return ok(finance.save("budget",dto,r),r);}
    @PostMapping("/api/v1/development-expenses/batch-save") public ResponseVO<?> saveExpenses(@Valid @RequestBody Batch dto,HttpServletRequest r){return ok(finance.save("expense",dto,r),r);}
    @GetMapping("/api/v1/development-budgets/{id}/history") public ResponseVO<?> budgetHistory(@PathVariable @Positive long id,@RequestParam(defaultValue="1") @Min(1) int page,@RequestParam(defaultValue="20") @Min(1) @Max(100) int size,HttpServletRequest r){return ok(finance.history("budget",id,page,size),r);}
    @GetMapping("/api/v1/development-expenses/{id}/history") public ResponseVO<?> expenseHistory(@PathVariable @Positive long id,@RequestParam(defaultValue="1") @Min(1) int page,@RequestParam(defaultValue="20") @Min(1) @Max(100) int size,HttpServletRequest r){return ok(finance.history("expense",id,page,size),r);}
    @PostMapping("/api/v1/development-budgets/import-preview") public ResponseVO<?> preview(@RequestParam MultipartFile file,HttpServletRequest r){return ok(imports.previewBudget(file),r);}
    @PostMapping("/api/v1/development-budgets/import-commit") public ResponseVO<?> commit(@Valid @RequestBody ImportCommit dto,HttpServletRequest r){return ok(imports.commitBudget(dto,r),r);}
    @PostMapping("/api/v1/development-expenses/erp-preview") public ResponseVO<?> erpPreview(@Valid @RequestBody ErpPreview dto,HttpServletRequest r){return ok(imports.previewErp(dto),r);}
    @PostMapping("/api/v1/development-expenses/erp-refresh") public ResponseVO<?> erpRefresh(HttpServletRequest r){return ok(imports.refreshErp(),r);}
    @PostMapping("/api/v1/development-expenses/erp-commit") public ResponseVO<?> erpCommit(@Valid @RequestBody ErpCommit dto,HttpServletRequest r){return ok(imports.commitErp(dto,r),r);}
    @GetMapping("/api/v1/development-budgets/export") public org.springframework.http.ResponseEntity<byte[]> export(@Valid Query query){finance.access().requireFinanceExport();return org.springframework.http.ResponseEntity.ok().header("Content-Disposition","attachment; filename=development-budgets.xlsx").contentType(org.springframework.http.MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).body(imports.exportBudgets(query));}
}
