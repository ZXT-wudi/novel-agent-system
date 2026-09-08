# Checklist

- [x] `LlmProvider` 模型表字段完整（provider_type/name/base_url/api_key/chat_model/embedding_model/is_active/created_at）并可持久化
- [x] `ProviderCreate` / `ProviderUpdate` / `ProviderResponse` schema 齐全，`ProviderResponse` 中 `api_key` 脱敏（仅末 4 位）
- [x] `GET /api/llm-providers` 列表端点返回脱敏 key 的供应商列表
- [x] `POST` / `PUT` / `DELETE` 供应商端点可用
- [x] `POST /api/llm-providers/{id}/activate` 能设激活（其余取消）并即时 `reconfigure` 客户端
- [x] `GET /api/llm-providers/active` 返回当前激活供应商
- [x] `SiliconFlowClient` 具备 `reconfigure` 方法，`chat`/`chat_stream`/`embed`/`generate_image` 使用动态配置
- [x] 模块函数 `reconfigure_llm_client(db)` 能从 DB 载入激活供应商，无激活则回退 `.env`
- [x] `main.py` startup 在 `init_db` 后调用载入激活供应商
- [x] `:root` 配色变量为温暖纸张浅色，全站无 `#1a1a2e`/`#16213e`/`#6c63ff` 冷蓝黑残留
- [x] 左侧图标活动栏存在且可切换 写作台/大纲/知识库/设置 四个视图
- [x] `switchView` 正确切换视图显隐并高亮当前图标，默认进入写作台
- [x] 顶部栏精简为 品牌 + 小说选择器 + 新建小说 + 激活模型指示
- [x] 全文大纲/章节大纲（含展开全屏）位于「大纲」视图（全屏遮罩已移至 body 层，跨视图可用）
- [x] 偏好/世界观/知识库管理/知识图谱位于「知识库」视图
- [x] 章节内容/编辑/AI 重写/写作控制/章节选择器位于「写作台」视图
- [x] 设置视图含供应商列表（脱敏 key）+ 新增/编辑/激活/删除
- [x] 厂商预设含 SiliconFlow/OpenAI/DeepSeek/智谱/自定义，选中自动填默认 base_url 与推荐模型
- [x] 设置视图显示「当前激活模型」提示，切换后即时刷新
- [x] 切换激活供应商后，后续大纲生成使用新模型（activate→reconfigure_llm_client→更新 self.model/self.base_url，chat 读取之；静态链路已确认）
- [x] 四视图切换与原有交互（生成/确认/展开/导入/图谱/写作/重写/审查）全部正常（元素与处理器齐全；运行时点击因本机 PowerShell 执行策略限制未实跑，静态已逐一确认引用解析）

> 备注：本机 PowerShell 执行策略禁止运行脚本，导致 `python -m py_compile` / 启动 uvicorn 均无法在工具内执行（PSSecurityException，与历史一致）。所有检查项均通过静态源码核对 + grep 确认通过；如需运行时实测，请在用户终端手动执行 `python -m uvicorn app.main:app --port 8011`。
