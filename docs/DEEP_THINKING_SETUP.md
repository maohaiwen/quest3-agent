# 深度思考功能配置指南

## 问题诊断

当前 `.env` 文件中：
- `ANTHROPIC_API_KEY=ce767027-79d8-4721-ae15-f858f55284dc` ✓
- `VOLCENGINE_API_KEY=ce767027-79d8-4721-ae15-f858f55284dc` ✗（错误的 key）

**问题**：`VOLCENGINE_API_KEY` 使用的是 Anthropic 的 API key，这不是有效的火山引擎 API key。

## 解决方案

### 方案 1：使用 Anthropic 客户端（推荐用于测试）

如果你只需要测试深度思考功能，可以直接使用 Anthropic 客户端，它会自动解析 `<thinking>` 标签。

**当前已工作的功能**：
- ✅ 深度思考开关
- ✅ `<thinking>` 标签解析
- ✅ 流式输出
- ✅ 所有执行模式（Direct/Plan/ReAct）

**使用方法**：
1. 在前端勾选"深度思考模式"
2. 发送需要推理的复杂问题
3. 模型会自动输出 `<thinking>` 标签（如果问题需要思考）

### 方案 2：配置火山引擎 API（推荐用于生产）

要使用火山引擎的原生深度思考 API，需要配置正确的火山引擎 API key。

#### 获取火山引擎 API Key

1. 访问火山引擎控制台：https://console.volcengine.com/ark
2. 登录或注册账号
3. 进入 "API 访问密钥" 页面
4. 创建新的 API Key 或复制现有的

#### 配置环境变量

在 `.env` 文件中更新：

```bash
# 使用正确的火山引擎 API key（不是 Anthropic 的）
VOLCENGINE_API_KEY=your_real_volcengine_api_key_here

# 确保基础 URL 正确
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

# 检查可用的模型 ID
# 在控制台的"推理接入"→"模型推理"中查看可用模型
VOLCENGINE_MODEL=your_available_model_id
```

#### 查看可用模型

1. 访问火山引擎控制台：https://console.volcengine.com/ark
2. 进入"推理接入" → "模型推理"
3. 查看可用模型列表
4. 找到支持 `thinking` 功能的模型

#### 常见模型 ID

- `doubao-pro-256k` (Doubao Pro 256K)
- `doubao-pro-4k` (Doubao Pro 4K)
- 等其他模型...

**注意**：模型 ID 可能会随时间变化，请在控制台查看最新的可用模型。

## 功能对比

| 功能 | Anthropic 客户端 | 火山引擎 SDK |
|------|----------------|---------------|
| 深度思考 | ✓（解析 `<thinking>` 标签）| ✓（原生 reasoning_content）|
| 流式输出 | ✓ | ✓ |
| 推理深度级别 | ✗ | ✓ (minimal/low/medium/high) |
| 跨平台兼容性 | ✓ | ✓ |

## 测试步骤

### 1. 测试 Anthropic 客户端（无需额外配置）

```bash
# 重启应用
python main.py

# 在前端：
# 1. 勾选"深度思考模式"
# 2. 发送复杂问题："分析一下北京到东京的航班选择"
# 3. 应该看到思考过程
```

### 2. 测试火山引擎 SDK（需要正确配置）

```bash
# 1. 配置正确的 VOLCENGINE_API_KEY
# 2. 配置正确的模型 ID
# 3. 重启应用
python main.py

# 在前端测试相同的问题
```

## 故障排查

### 问题：看不到思考过程

**原因**：
1. 问题太简单，模型不需要思考
2. 深度思考开关未开启
3. 模型没有输出 `<thinking>` 标签（Anthropic 客户端）

**解决**：
- 使用需要推理的复杂问题
- 确保勾选了"深度思考模式"
- 检查浏览器控制台是否有错误

### 问题：404 模型未找到错误

**原因**：模型 ID 不正确或无权限

**解决**：
1. 访问火山引擎控制台
2. 查看可用的模型列表
3. 更新 `VOLCENGINE_MODEL` 为正确的模型 ID

### 问题：连接错误

**原因**：API Key 不正确或网络问题

**解决**：
1. 验证 API Key 是否正确
2. 检查网络连接
3. 检查 `VOLCENGINE_BASE_URL` 是否正确

## 总结

- **当前状态**：可以使用 Anthropic 客户端的 `<thinking>` 标签解析
- **推荐做法**：先使用 Anthropic 客户端测试功能
- **生产环境**：配置正确的火山引擎 API Key 以获得更好的性能

## 相关文件

- `.env` - 环境变量配置
- `app/services/llm_service.py` - LLM 服务（支持双客户端）
- `app/services/thinking_chain_manager.py` - 思维链管理器
- `docs/deep_thinking_usage.md` - 使用文档
