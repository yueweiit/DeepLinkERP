# 增量发布的代码回退

空运海运测算发布仅增加结构和页面，失败后的自动回退使用 `.github/scripts/manage_material_ai_release.sh rollback-code`。发布前的 `prepare` 仍保留旧镜像和数据库、文件备份；新模式不会读取备份包、恢复数据库、恢复文件、覆盖站点配置或执行旧版本迁移。已保存的测算记录、来源关联、DocType 和 Page 均保留。

代码回退依次检查本次发布的 `pre-material-ai-release-<release_id>` 镜像，暂停前台及后台任务，重建旧后端，以旧镜像中的 `install.ensure_workspace_sidebar()` 恢复侧栏，并用旧 `_set_workspace_content()` 恢复既有工作区快捷入口。基线 `d02f4dadea` 已包含这些函数。随后重建各服务，将旧后端的构建资源同步至前端，更新工作台 Page 的缓存版本并清除站点及网站缓存。恢复新增功能时重新部署通过验证的代码，不需要重建测算数据。

需人工执行已批准的代码回退时，使用与 `prepare` 相同的发布标识：

```bash
bash .github/scripts/manage_material_ai_release.sh rollback-code \
  /home/yuewei/ERPNext-Docker/frappe_docker deeplinkerp.com <release_id>
```

执行后确认各服务正常、登录页可访问、工作区恢复旧入口，并通过只读数据库检查确认 `Overseas Air Sea Comparison` 记录数未减少。已打开的 Desk 页面需刷新。旧代码暂不提供新增测算功能，但保存的数据留在现有数据库中。

原 `rollback` 模式保持原行为：恢复发布前数据库、文件和站点配置。这会覆盖备份之后的数据，仅用于另外审查和批准的完整恢复，不用于本次增量发布的失败处理。`rollback-code` 也不适用于删除列、破坏性数据转换或其他不兼容迁移；此类发布需单独设计恢复方案。

本地验证运行 `python3 -m pytest -q overseas_costing/tests/test_additive_release_rollback.py overseas_costing/tests/test_deploy_workflow.py` 和 `bash -n .github/scripts/manage_material_ai_release.sh`。回归测试用临时的 Docker 替身执行脚本、检查命令顺序与禁止数据库恢复，不连接生产，也不执行实际回退。
