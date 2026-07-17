# 通用智能客服框架

一个可直接运行、便于二次开发的开源智能客服工作台。添加兼容 OpenAI Chat Completions 的 API Key，再上传业务资料，即可获得带知识库检索、人工接管和运行追踪的客服助手。

> 本项目采用描述性名称，不隶属于任何模型厂商或客服软件品牌。OpenAI、OpenRouter 等名称仅用于说明兼容接口。

## 已实现

- OpenRouter / OpenAI / 其他 OpenAI 兼容中转 API
- 后台录入 API 地址、Key、模型、客服名称和客服规则
- API Key 由本机后端加密保存，前端不会读回明文
- TXT、Markdown、CSV、PDF、DOCX 知识库文件
- 无额外向量 API 成本的中英文 BM25 检索
- 有界 Agent 编排：输入防护、确定性路由、知识检索工具、受控人工转接
- 服务端多轮会话记忆、知识来源提示、回答反馈
- 运行追踪、耗时/检索指标、人工接管队列
- 桌面端和移动端自适应工作台
- SQLite 本地存储，无需另装数据库

## 一分钟启动

需要 Python 3.11 或更高版本。

```powershell
git clone https://github.com/zhaoyeyu/general-ai-customer-service.git
cd general-ai-customer-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

启动后有两个独立页面：

- 客户聊天页：<http://127.0.0.1:8000>
- 管理后台：<http://127.0.0.1:8000/admin>

进入管理后台的“服务配置”：

1. API 地址保留 `https://openrouter.ai/api/v1`。
2. 填入你的 OpenRouter API Key。
3. 模型 ID 可以手动填写；留空时点击连接检测会从可用列表中自动选择推荐模型。
4. 点击“保存并检测连接”，页面会先保存配置，再验证 Key 并加载模型。
5. 到“知识库”上传业务资料，然后开始对话。

也可以通过环境变量提供 Key：

```powershell
$env:OPENROUTER_API_KEY="在当前终端中设置，不要写入源码"
python run.py
```

## 数据与安全

运行数据位于 `data/`：

- `customer_service.db`：设置、文档切片和加密后的 API Key
- `.master.key`：本机解密密钥

`data/` 和 `.env*` 已被 `.gitignore` 排除。聊天消息、运行追踪、用户反馈和人工接管工单会写入本机数据库；API Key 不会进入这些记录。部署到公网前仍应增加管理员登录、HTTPS、访问限流、数据保留策略和文件安全扫描。

仓库不包含 API Key、运行数据库、会话记录或服务日志。请不要把 `data/`、`.env` 或日志文件提交到公开仓库。

## API

| 方法 | 地址 | 用途 |
|---|---|---|
| `GET` | `/api/health` | 健康与配置状态 |
| `GET/PUT` | `/api/settings` | 读取/更新公开设置 |
| `POST` | `/api/settings/test` | 验证模型服务连接 |
| `GET/POST` | `/api/knowledge` | 列出/上传知识文件 |
| `DELETE` | `/api/knowledge/{id}` | 删除知识文件 |
| `POST` | `/api/chat` | 有界 Agent 客服对话 |
| `POST` | `/api/feedback` | 对单次回答提交反馈 |
| `GET` | `/api/admin/metrics` | 运行指标 |
| `GET` | `/api/admin/traces` | 最近运行追踪 |
| `GET` | `/api/admin/handoffs` | 人工接管队列 |
| `PATCH` | `/api/admin/handoffs/{id}` | 更新人工工单状态 |

接口文档：<http://127.0.0.1:8000/docs>

Chat 请求示例：

```json
{
  "conversation_id": "首轮可省略，后续传回响应中的 ID",
  "messages": [
    { "role": "user", "content": "退款需要多久？" }
  ]
}
```

## 测试

```powershell
python -m pip install -r requirements-dev.txt
pytest -q
```

## 生产部署前

当前架构决策、运行流程和扩展边界见 [Agent 架构说明](docs/AGENT_ARCHITECTURE_ZH.md)。当前版本适合作为本地工作台或二次开发底座。如果需要开放给真实客户，还应增加：

- 管理员登录与访客会话隔离
- HTTPS、反向代理、速率限制和用量上限
- 更完整的敏感信息分类、工单系统对接与数据保留/删除策略
- PostgreSQL/Redis、多实例部署和备份策略

本机测试、局域网、临时公网演示和云服务器的选择见 [DEPLOYMENT_GUIDE_ZH.md](DEPLOYMENT_GUIDE_ZH.md)。

## 许可证

代码采用 [MIT License](LICENSE)。项目名称为通用描述，不主张与任何第三方品牌存在关联。
