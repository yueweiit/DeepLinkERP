# 宿主基础设施归档（不在版本控制里的那三个文件）

这三个文件**不来自本仓库**，而是生产宿主机
`/home/yuewei/ERPNext-Docker/frappe_docker/` 下的本地改动。上级目录是上游
[`frappe/frappe_docker`](https://github.com/frappe/frappe_docker) 的克隆，
所以 `git status` 在宿主机上永远看不到它们 —— 它们不出现在任何版本控制里。

归档在这里是为了让"线上到底跑哪一版"有据可查。**归档是本仓库的一部分，宿主机不读它。**

| 文件 | 宿主绝对路径 | 作用 |
| --- | --- | --- |
| `compose.custom.yaml` | `/home/yuewei/ERPNext-Docker/frappe_docker/compose.custom.yaml` | 生产 compose：镜像 tag、端口、卷、service 定义 |
| `apps.json` | `/home/yuewei/ERPNext-Docker/frappe_docker/apps.json` | 钉死烘进镜像的 12 个 app 分支 |
| `upgrade_bench.sh` | `/home/yuewei/ERPNext-Docker/frappe_docker/upgrade_bench.sh` | 真正执行 `docker build --no-cache` + `compose up --force-recreate` 的脚本 |

## 为什么必须归档

1. **2026-09-27**：有人手工把 compose 的镜像行 pin 成
   `deeplinkerp-custom:v16.23.0-f33f7bc`（`china_finance` 分支的 HEAD 前缀）。
   后果是流水线**全部步骤绿、`release_id` 也前进，但容器重建后跑的还是旧代码**。
   因为那个 tag 只存在于宿主 compose 里，从仓库里完全看不出来。
2. `upgrade_bench.sh` 第 5 步会 `| tail -n +3 | xargs -r rm -f`，**只保留最近 2 份
   `compose.custom.yaml.bak.<日期>-<时分>`**。出事后可回看的现场很快就被自己的脚本删掉。

## ⚠️ 归档会过期，必须手工重同步

CI 不会自动更新这里的副本。宿主机上任何一个文件被改动，归档就会**静默失真** ——
而失真的归档比没有归档更危险（`release_id` 会说谎就是这么来的）。

改了宿主文件之后，重跑一次同步：

```bash
cd <repo>
OC_HOST=155.138.234.129 OC_USER=yuewei OC_PW=<本次口令> \
  python tmp/oc_ssh.py <<'SH'
cd /home/yuewei/ERPNext-Docker/frappe_docker
for f in apps.json compose.custom.yaml upgrade_bench.sh; do
  echo "===== $f"
  cat "$f"
done
SH
```

把输出按同名文件贴回本目录，并把 `MYSQL_ROOT_PASSWORD` 改回下面那个占位符。

## 脱敏

`compose.custom.yaml` 与宿主机副本**逐字节相同，只有一处例外**：

```yaml
MYSQL_ROOT_PASSWORD: "<redacted: only set on the production host>"
```

真实口令只留在宿主机上，本仓库是公开仓库，不放。**用这份归档恢复环境时记得把它改回去。**

## 恢复一台宿主机时注意

- `compose.custom.yaml` 的**镜像行必须是 `deeplinkerp-custom:v16.23.0-latest`**。
  宿主 `upgrade_bench.sh` 只打这一个 tag（代码版本由 `apps.json` 的**分支**决定，与 tag 无关），
  所以 compose pin 成别的 tag 就会出现"构建了新镜像，容器重建后仍跑老镜像"。
  部署脚本一律经 `.github/scripts/resolve_base_image.sh` 从 compose 读这个 tag，不许硬编码。
- `apps.json` 的 12 个分支共享同一个镜像：**我们的部署会把别人的最新提交一起带上线，
  别人重建也会覆盖我们的 `apps/overseas_costing`**。纯文档改动不要单独推上去触发重建。
- `upgrade_bench.sh` 里的 `IMAGE_LABEL="com.deeplinkerp.project=deeplinkerp"` 与第 13 步的
  `docker image prune -f --filter "label=$IMAGE_LABEL"` 配套：只回收本项目**悬空**镜像，
  不会碰到别的项目栈（同一台机器还跑着 `deeplink-mes-*`、`shop-crm-*`、`oem-crm-*`）。
