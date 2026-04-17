# 云托管部署指南（团队可共享）

本项目推荐使用 **Docker 部署 + 持久化磁盘**，确保：

- 历史周数据（`weekly_metrics.json`）不丢失
- 每周行动计划（`action_plans.json`）不丢失

---

## 1. 关键持久化文件

请确保以下目录在云平台挂载为持久化磁盘（Persistent Disk / Volume）：

- `data/warehouse/`

其中核心文件：

- `data/warehouse/weekly_metrics.json`
- `data/warehouse/action_plans.json`
- `data/warehouse/ui_payload.json`

> 如果不挂持久化盘，容器重启后这些文件可能回到镜像初始状态。

---

## 2. 本地先验证容器

```bash
docker build -t weekly-dashboard:latest .
docker run --rm -p 3010:3010 weekly-dashboard:latest
```

打开：

- `http://localhost:3010`
- 健康检查：`http://localhost:3010/api/health`

---

## 3. 推荐平台：Render（示例）

### 3.1 创建服务

1. 将仓库推送到 GitHub
2. 在 Render 新建 **Web Service**
3. 选择 **Docker** 部署（自动识别 `Dockerfile`）

### 3.2 持久化盘

在 Render 给该服务添加 Persistent Disk，挂载到：

- `/app/data/warehouse`

### 3.3 环境变量

- `PORT`：Render 会自动注入（服务内已兼容）
- 无其他强制变量

### 3.4 发布后验证

1. 打开 `/api/health`
2. 打开前端首页
3. 在页面保存一条行动计划
4. 重启服务，确认行动计划仍在（验证持久化生效）

---

## 4. 每周更新操作（线上）

### 方式 A：调用刷新接口（推荐）

```bash
POST /api/refresh-excel
```

作用：触发 `python3 -m core.dashboard_builder` 重新生成 `ui_payload.json`。

### 方式 B：进入容器手工运行

```bash
PYTHONPATH=. python3 scripts/weekly_update.py
```

作用：自动备份 + 更新 + 校验，适合周更发布窗口。

---

## 5. 团队协作建议

- 统一使用线上地址访问（避免每人本地环境差异）
- 每周数据更新人固定 1-2 位，执行后在群里回传：
  - 更新时间
  - 影响门店
  - 校验结果截图（周数、计划条数）

---

## 6. 上线前检查清单

- [ ] `data/warehouse` 已挂载持久化磁盘
- [ ] `/api/health` 正常
- [ ] 能读取并展示最新周
- [ ] 行动计划可保存且重启后仍在
- [ ] `/api/refresh-excel` 可正常触发重建

