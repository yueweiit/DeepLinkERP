-- Different historical snapshots created these optional fields with different null/default rules.
-- Preserve every historical value; only new explicitly unknown amounts/currencies must remain unknown.
alter table plm_product_bom_item
    alter column unit_cost_snapshot drop not null,
    alter column unit_cost_snapshot drop default,
    alter column line_cost_snapshot drop not null,
    alter column line_cost_snapshot drop default,
    alter column currency_code drop not null,
    alter column currency_code drop default;
