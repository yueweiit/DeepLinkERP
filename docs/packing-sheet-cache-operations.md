# 装箱 Sheet 本地缓存运行手册

装箱目录和预览数据物化在本站点 MariaDB 的 `oc_ls_state`。远程 PostgreSQL/MinIO 仍是可信来源，本地缓存可重建，不是正式业务记录。

## 发布与首次预热

1. 确认站点时区为 `Asia/Shanghai`，并先完成常规 `migrate`，确保 `oc_ls_state` 已安装。
2. 在对外启用新前端资源前执行一次全量预热：

   ```bash
   bench --site <site> execute overseas_costing.services.packing_sheet_cache_service.refresh_catalog_cache
   ```

3. 确认返回值的 `failed` 为 `0`，并通过服务端目录接口核对已启用 Sheet 均为 `cache_status=ready`。
4. 再重启 web/worker/scheduler，清理站点缓存并发布生成后的工作台资源。

## 日常运行

- scheduler 每天北京时间 `08:00` 和 `18:00` 执行增量同步。
- 连续 24 小时没有成功同步时，目录与 Sheet 标记为过期，但仍保留最后成功版本供查看。
- 同步失败不会删除旧缓存；停用或移除的 Sheet 保留缓存并标记为不可用。
- 用户可在「获取装箱资料」中选中单个 Sheet 后手动刷新；远端刷新和本地物化都成功后，界面才会报告成功。

## 故障排查

- 先查目录返回的 `catalog_status`、`last_checked_at`、`last_success_at` 和 `sync_error`。
- 再查具体 Sheet 的 `cache_status`、`content_hash` 和 `sync_error`。
- 不要为修复缓存而删除已确认装箱快照、来源版本令牌或审计记录。
