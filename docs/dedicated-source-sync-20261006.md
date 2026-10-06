# 专用来源同步

只执行既有 `operating_expenses.scheduled_sync` 和 `purchase_source_service.scheduled_sync`。宿主机 user timer 每个整点、15、30、45 分触发；两项任务串行、各自一个容器进程，单项总预算 300 秒。运营支出逐页提交缓存与游标，未完成页失败回滚；采购沿用既有 300 秒 Redis 锁及整个扫描的单事务。两项既有启用开关和手动同步保持原用途。

System Settings.enable_scheduler 必须保持 0；不能开启其余自动任务。执行前用 Frappe 原生无缓存读取重新合并 common/site 配置，检查维护模式、scheduler_disabled 和无缓存全局开关，运营支出每页重新检查；无效配置安全拒绝且不输出配置内容。两条固定原生 RQ job 任一 QUEUED/STARTED 均拒绝执行或 metadata 安装，不改变 RQ 状态。只允许两项固定方法，内部 runner 和日志安装函数均不提供 HTTP 白名单接口。业务分类、China/2026 范围、流程代码、原生订单/付款/凭证操作没有新增规则。

## 安装与启动

正常 image overlay 发布完成后，单独暂存 `deploy/production/dedicated_source_sync.py` 与 `systemd` 下的两份模板。使用既有 `yuewei` 用户；不需要 sudo。提供已经核验的完整 branding SHA、backend image ID 和安装后 runner 的 SHA-256：

```sh
python3 deploy/production/dedicated_source_sync.py install --revision <SHA> --image-id <sha256:IMAGE> --runner-sha256 <RUNNER_SHA256>
```

默认只为**原有两条** Scheduled Job Type 打开 create_log、保存原始值的持久证据、暂存 user units，timer 保持停止。写 create_log 前必须确认两条原生 job 均空闲，启动 timer 前再次核查。缺少、重复、脚本化、stopped 或 cron 不符的 job 会拒绝安装，不做 broad migration/sync_jobs。先采集部署所需的 `before-timer.json`，再用同样参数加 `--start-timer`；该命令不会手动执行任务，随后由日历的下个时点触发。`Persistent=false` 不补跑停机错过的轮次。

配置、原始 create_log 证据和当前运行记录存于 `/home/yuewei/.local/state/deeplinkerp-source-sync`；启动器独立保存于 `.local/share/deeplinkerp-source-sync/launcher.py`，不依赖临时发布目录。重复安装保留首次原始 create_log 证据。

## 故障与回滚

原生 Scheduled Job Log 记录 Start、Complete、Failed，creation/modified 及 last_execution 保留原生语义。runner 检查实际终态，Failed 的 details/debug 在保存前去除来源内容。运营支出错误提示单独提交，只写 last_error，避免覆盖手动同步刚更新的游标。

容器内 SIGALRM/SIGTERM 中断实际 Python 子进程；宿主机另有 30 秒清理宽限。超时先验证私有 PID marker 中的 PID 启动时间，再终止实际容器进程，必要时 SIGKILL 使未提交事务随数据库连接关闭回滚，随后修复对应唯一日志。终止或日志恢复无法确认时保留运行记录、停止后续任务；下一次启动先恢复它。不会只杀 docker 客户端后假报完成。

```sh
python3 deploy/production/dedicated_source_sync.py rollback
```

回滚先停用 timer 并停止 service，再取得互斥锁、核对已安装 image/revision/checksum、恢复证据中两项 create_log。来源缓存、付款证据、游标、原生日志均不删除。回滚 timer/日志应在回滚应用镜像之前进行。

## 后续 ERP 发布

发布前必须先暂停该 user timer、停止 service；发布脚本和启动器复用 `/tmp/deeplinkerp-erp-release.lock`，同步另有自身运行锁，防止发布切换与同步重叠。只有定时 run 抢锁失败可返回 Skipped/exit 0；install/rollback 抢锁失败返回 Failed/非 0，控制动作不可误认成功。新镜像切换后按新 image ID、branding revision 和 runner checksum 重新 staged install，验收后显式启用 timer。旧 identity 会拒绝执行，不能直接重启旧配置绕过核验。

## 验证与范围

CI 增加宿主机 focused unittest；原有 app pytest 自动包含两个新测试文件。真实隔离站点验证命令：

```sh
docker exec --workdir /home/frappe/frappe-bench dlp-operating-expenses-qa-backend-1 /home/frappe/frappe-bench/env/bin/python /workspace/deploy/local/test_expense_source_scheduler_native_qa.py -v
```

该 helper 限定既有合成 QA 站点，外部来源用合成读取替换；验证真实原生日志、超时、分页提交/失败回滚/恢复、仅两项 metadata、原生单据和主数据数量不变。只恢复其自身设置、删除其准确命名的合成缓存/日志，不操作生产。

本轮不增加业务 API、模型、并行规则引擎或自动清理任务。原生日志以及私有 PID marker 的长期保留/清理政策仍属未处理技术债；现有原生日志清理也随全局 scheduler 停用。采购未新增分页 checkpoint，失败仍按既有单事务回滚并重试。
