package com.yuewei.plm.module.bom.service.impl;

import com.yuewei.plm.common.constant.ErrorCodeConstants;
import com.yuewei.plm.common.exception.BusinessException;
import com.yuewei.plm.common.vo.PageVO;
import com.yuewei.plm.module.bom.dto.BomLedgerQueryDTO;
import com.yuewei.plm.module.bom.entity.ProductBom;
import com.yuewei.plm.module.bom.service.BomLedgerService;
import com.yuewei.plm.module.bom.vo.BomLedgerRowVO;
import com.yuewei.plm.module.bom.vo.BomProductRowVO;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class JdbcBomLedgerPageService {
    private final JdbcTemplate jdbc;
    private final BomLedgerService ledger;

    // The visibility predicate is identical to the existing formal ledger, including imported versions.
    private static final String CTE = """
        with recursive owners(root_id, product_id, path) as (
          select product_id, product_id, array[product_id] from plm_product
           where deleted_flag = 0 and product_type = 'product_line'
          union all
          select o.root_id, p.product_id, o.path || p.product_id
            from owners o join plm_product p on p.parent_product_id = o.product_id
           where p.deleted_flag = 0 and not (p.product_id = any(o.path))
        ), formal as (
          select b.* from plm_product_bom b
           where b.deleted_flag = 0 and b.bom_scope = 'formal' and b.status = 'released'
             and (b.source_type = 'import' or b.released_by = 'history-import' or exists (
               select 1 from plm_product_bom_route_formal_selection s
                where s.product_bom_id = b.product_bom_id and s.status = 'active' and s.deleted_flag = 0
             ))
        )
        """;

    public PageVO<BomProductRowVO> products(BomLedgerQueryDTO query) {
        List<Object> args = new ArrayList<>();
        String filter = "";
        if (StringUtils.hasText(query.getKeyword())) {
            filter = """
                and (p.product_code ilike ? or p.product_name ilike ? or exists (
                  select 1 from owners ox join plm_product child on child.product_id = ox.product_id
                    left join formal bf on bf.product_id = ox.product_id
                   where ox.root_id = p.product_id and (bf.bom_code ilike ? or child.model ilike ?)
                ))
                """;
            for (int i = 0; i < 4; i++) args.add(pattern(query.getKeyword()));
        }
        String summary = """
            , summary as (
              select p.product_id, p.product_code, p.product_name,
                     count(f.product_bom_id) as bom_count,
                     coalesce(max(f.updated_at), p.updated_at) as updated_at
                from plm_product p left join owners o on o.root_id = p.product_id
                  left join formal f on f.product_id = o.product_id
               where p.deleted_flag = 0 and p.product_type = 'product_line'
            """ + filter + " group by p.product_id, p.product_code, p.product_name, p.updated_at) ";
        Long total = jdbc.queryForObject(CTE + summary + "select count(*) from summary", Long.class, args.toArray());
        addPageArgs(query, args);
        List<BomProductRowVO> values = jdbc.query(CTE + summary
            + "select * from summary order by updated_at desc, product_id desc limit ? offset ?",
            (rs, row) -> new BomProductRowVO(rs.getLong("product_id"), rs.getString("product_code"),
                rs.getString("product_name"), rs.getLong("bom_count"), time(rs.getTimestamp("updated_at"))), args.toArray());
        return page(values, query, total);
    }

    public PageVO<BomLedgerRowVO> boms(Long productId, BomLedgerQueryDTO query) {
        Integer exists = jdbc.queryForObject("select count(*) from plm_product where product_id = ?"
            + " and deleted_flag = 0 and product_type = 'product_line'", Integer.class, productId);
        if (exists == null || exists == 0)
            throw new BusinessException(ErrorCodeConstants.RESOURCE_NOT_FOUND, "产品线不存在");
        List<Object> args = new ArrayList<>();
        args.add(productId);
        String from = " from formal b join owners o on o.product_id = b.product_id"
            + " join plm_product p on p.product_id = b.product_id where o.root_id = ?";
        if (StringUtils.hasText(query.getKeyword())) {
            from += " and (b.bom_code ilike ? or p.product_code ilike ? or p.product_name ilike ? or p.model ilike ?)";
            for (int i = 0; i < 4; i++) args.add(pattern(query.getKeyword()));
        }
        Long total = jdbc.queryForObject(CTE + "select count(*)" + from, Long.class, args.toArray());
        addPageArgs(query, args);
        List<ProductBom> values = jdbc.query(CTE + "select b.*" + from
            + " order by b.updated_at desc, b.product_bom_id desc limit ? offset ?", (rs, row) -> {
                ProductBom bom = new ProductBom();
                bom.setProductBomId(rs.getLong("product_bom_id"));
                bom.setProductId(rs.getLong("product_id"));
                bom.setBomCode(rs.getString("bom_code"));
                bom.setVersionNo(rs.getString("version_no"));
                bom.setStatus(rs.getString("status"));
                bom.setSourceType(rs.getString("source_type"));
                bom.setUpdatedAt(time(rs.getTimestamp("updated_at")));
                return bom;
            }, args.toArray());
        return page(ledger.describeFormal(values), query, total);
    }

    private static String pattern(String value) {
        return "%" + value.trim().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%";
    }
    private static void addPageArgs(BomLedgerQueryDTO query, List<Object> args) {
        args.add(query.getSize());
        args.add((query.getPage() - 1) * query.getSize());
    }
    private static java.time.LocalDateTime time(Timestamp value) {
        return value == null ? null : value.toLocalDateTime();
    }
    private static <T> PageVO<T> page(List<T> rows, BomLedgerQueryDTO query, Long count) {
        long total = count == null ? 0 : count;
        return new PageVO<>(rows, query.getPage(), query.getSize(), total, (total + query.getSize() - 1) / query.getSize());
    }
}
