alter table plm_product
    add column if not exists mold_transfer_at timestamp,
    add column if not exists expected_arrival_at timestamp,
    add column if not exists actual_arrival_at timestamp;

comment on column plm_product.mold_transfer_at is 'Mold transfer confirmed time, written by server when the mold-transfer timeline node is confirmed';
comment on column plm_product.expected_arrival_at is 'Expected arrival time after mold transfer';
comment on column plm_product.actual_arrival_at is 'Actual arrival time after mold transfer';
