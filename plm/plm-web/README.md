# PLM Web

基于 `D:\Yuewei\资料\PLM\docs` 文档整理出的 PLM 前端原型，技术栈遵循文档约束：

- Vue 3
- Vite
- Element Plus
- Pinia
- Vue Router

## 当前实现

- 工作台
- 产品主数据列表与详情
- 机型库、样品开发、BOM、图纸文件、工艺路线、模具治具、成本报价、工程变更、质量合规、ERP 导入等模块化看板
- 审批中心
- 权限配置与超管审计视图

当前以前端高保真 mock 数据驱动，方便后续逐步接入 `/api/v1` 后端接口。

## 本地运行

如果本机未安装 Node，可直接使用 Docker Desktop：

```powershell
docker run --rm -it -v ${PWD}/plm-web:/app -w /app node:20-alpine npm install
docker run --rm -it -p 5173:5173 -v ${PWD}/plm-web:/app -w /app node:20-alpine npm run dev
```

启动后访问：

- `http://localhost:5173`
