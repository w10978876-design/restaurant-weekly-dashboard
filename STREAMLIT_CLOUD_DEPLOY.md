# Streamlit Cloud 部署说明（方案 A）

适用于当前仅有 **GitHub + Streamlit Cloud** 的团队。

---

## 1. 准备

1. 将仓库推送到 GitHub（包含最新 `app.py`）
2. 确认 `requirements.txt` 已包含依赖（本项目已具备）

---

## 2. 在 Streamlit Cloud 创建应用

1. 登录 Streamlit Cloud
2. New app -> 选择该 GitHub 仓库
3. Main file path 填写：`app.py`
4. Deploy

---

## 3. 可选：开启团队共享持久化（推荐）

默认情况下，Streamlit Cloud 容器文件系统可能重启后丢失临时写入。  
为保证“行动计划可团队共享且不丢失”，建议配置 GitHub 回写。

在 Streamlit App 的 **Secrets** 中配置：

```toml
GITHUB_TOKEN = "你的 token"
GITHUB_REPO_OWNER = "你的 GitHub 用户名或组织名"
GITHUB_REPO_NAME = "仓库名"
GITHUB_BRANCH = "main"
```

说明：

- 配置后，行动计划会写回 `data/warehouse/action_plans.json`（提交到仓库分支）
- 所有同事访问同一线上地址时能看到同一份计划

---

## 4. 使用方式

- “重建最新数据”按钮：触发重新生成 `ui_payload.json`
- “保存行动计划”按钮：保存当前门店+周的三条行动

---

## 5. 注意事项

- 若未配置 GitHub Secrets，行动计划只写容器本地文件，重启后可能丢失
- 线上数据更新后，建议在 GitHub 保留 `data/warehouse/*.json` 快照，便于审计回溯
