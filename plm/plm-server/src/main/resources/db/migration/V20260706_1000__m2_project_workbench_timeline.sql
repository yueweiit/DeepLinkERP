alter table plm_product
    add column if not exists current_step_no integer not null default 1;

comment on column plm_product.current_step_no is '当前项目时间轴节点序号，1-6；projectId 当前等同 product_id';

update plm_product
set current_step_no = 1
where current_step_no is null or current_step_no < 1 or current_step_no > 6;
