#!/usr/bin/env bash
set -euo pipefail

compose_root="${1:?compose root is required}"
site_name="${2:?site name is required}"
compose_file="$compose_root/compose.custom.yaml"

cd "$compose_root"

echo "Backing up site before route_revision cleanup..."
docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
  bench --site "$site_name" backup --with-files

echo "Inspecting and normalizing legacy route_revision..."
docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
  bench --site "$site_name" mariadb --batch --skip-column-names <<'SQL'
SET @has_route_revision := (
  SELECT COUNT(*) > 0
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'tabOverseas Cost Item'
    AND column_name = 'route_revision'
);

SELECT table_name, column_name, column_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = DATABASE()
  AND table_name = 'tabOverseas Cost Item'
  AND column_name = 'route_revision';

SET @sql := IF(
  @has_route_revision,
  'SELECT COUNT(*) AS total_rows,
          SUM(
            CASE
              WHEN `route_revision` IS NULL
               OR (
                 TRIM(CAST(`route_revision` AS CHAR)) = ''''
                 OR TRIM(CAST(`route_revision` AS CHAR)) NOT REGEXP ''^[0-9]+$''
                 OR CHAR_LENGTH(TRIM(CAST(`route_revision` AS CHAR))) > 10
                 OR (
                   CHAR_LENGTH(TRIM(CAST(`route_revision` AS CHAR))) = 10
                   AND TRIM(CAST(`route_revision` AS CHAR)) > ''2147483647''
                 )
               )
              THEN 1 ELSE 0
            END
          ) AS invalid_rows
   FROM `tabOverseas Cost Item`',
  'SELECT 0 AS total_rows, 0 AS invalid_rows'
);
PREPARE route_revision_counts FROM @sql;
EXECUTE route_revision_counts;
DEALLOCATE PREPARE route_revision_counts;

SET @sql := IF(
  @has_route_revision,
  'ALTER TABLE `tabOverseas Cost Item`
   ALTER COLUMN `route_revision` SET DEFAULT 0',
  'SELECT 1'
);
PREPARE route_revision_default FROM @sql;
EXECUTE route_revision_default;
DEALLOCATE PREPARE route_revision_default;

SET @route_revision_safe_updates := @@SQL_SAFE_UPDATES;
SET SQL_SAFE_UPDATES = 0;
SET @sql := IF(
  @has_route_revision,
  'UPDATE `tabOverseas Cost Item`
   SET `route_revision` = 0
   WHERE `route_revision` IS NULL
     OR (
       TRIM(CAST(`route_revision` AS CHAR)) = ''''
       OR TRIM(CAST(`route_revision` AS CHAR)) NOT REGEXP ''^[0-9]+$''
       OR CHAR_LENGTH(TRIM(CAST(`route_revision` AS CHAR))) > 10
       OR (
         CHAR_LENGTH(TRIM(CAST(`route_revision` AS CHAR))) = 10
         AND TRIM(CAST(`route_revision` AS CHAR)) > ''2147483647''
       )
     )',
  'SELECT 1'
);
PREPARE route_revision_values FROM @sql;
EXECUTE route_revision_values;
DEALLOCATE PREPARE route_revision_values;
SET SQL_SAFE_UPDATES = @route_revision_safe_updates;

SELECT 'route_revision cleanup complete' AS status;
SQL
