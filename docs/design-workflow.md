# v0.4 联动与证据工作流

## 显式预算链

旧原型保留单一 `downstream_efficiency` 计算。只有明确选择输入面的下游起点并启用 `downstream_chain`，才关联原型效率；启用链要求单一后段效率为1，避免重复计入损失。

链结构为 `{schema_version:1, stages:[...]}`。每段包含 `id,name,from_plane,to_plane,efficiencies:{R,G,B},basis:"optical_only",status,reference`，可选 `parameter_key`。段与段的接收面必须连续，首段从预算的 `receiving_plane` 开始，末段到 `屏幕`。状态为 `assumed`、`specified` 或 `measured`；状态和来源由使用者核对，程序不替其认证。

允许关联的参数为 `collimator_transmission,flyeye_transmission,prism_transmission,imager_efficiency,lens_transmission`。有关联时，计算必须传入当前完整 `parameters`，以当前值替换保存的效率快照；参数修改会随同一版本事务重算配色。链只含光学损失，收集角和时序不作为下游段。创建模板不证明输入面或效率定义正确，须核对起止面及所含损失。

令输入面各组 CW 通量为 `C_i`，各段效率乘积为 `E_i`，目标白点各组Y比例为 `f_i`。时序模式在屏幕计算：

`screen_white_lm = available_deg / Σ[f_i/(C_i·E_i/360)]`

`angle_i = 360·screen_white_lm·f_i/(C_i·E_i)`

同时点亮模式为 `screen_white_lm=min(C_i·E_i/f_i)`，各组调光比例独立限制在0–1。`output` 仍为输入面平均XYZ，`screen_output` 为屏幕XYZ；白点偏差以屏幕为准。组内谱形保持不变是该模型的假设，谱形或偏振随通道变化时须更细的模型。近轴光扇达屏比例不参与效率计算。

## 当前计算与来源

案例对照是预览，不替换当前计算；点击应用案例才改变本地编辑输入。当前结果显示原型ID、版本和未保存状态。来源指纹可区分案例原样、改过案例、基线已变化或本机缺少案例，展示字段差异。来源SHA引用既有核读证据，并非每次计算重新核对原始文件。缺少私人案例时不静默用合成案例冒充。

## 本地检索与 AI 草案

`GET /api/evidence?q=...&limit=8` 返回本地索引中的有限片段、位置和核读范围，不执行原文件。片段ID绑定内容版本。网页默认不选择；内置AI只获得最多8项明确选中的片段，以及当前设计和面板对话。资料内容只作为证据，不能授权执行命令。未选案例的历史基线值不加入模型工具计算输出。本地结果仍可展示完整来源对照。

`POST /api/design/preview` 接受 `project_id,version,scene?,parameter_updates?,color_budget?,note?`，返回校验后的草案、计算和字段差异，不写入数据库。`POST /api/design/chain-template` 接受 `parameters,receiving_plane,start_stage`，生成未保存的链。

网页内置聊天调用 `POST /api/ai/chat` 时使用 `preview:true,evidence_ids:[...]`。修改先在内存校验，返回 `proposal_id,draft,differences`；点击应用调用 `/api/ai/apply`，携带 `project_id,version,proposal_id`。草案30分钟失效、仅使用一次、重启后失效。版本冲突不会覆盖新版本；差异截断时网页禁止应用。旧API省略 `preview` 或设为false，仍保留原有校验后自动提交合同。

内置聊天没有服务端密钥时显示未配置，不模拟成功。Codex通过MCP操作无需工作台自己的密钥。本次回归使用模拟模型响应，不代表线上认证或模型调用已验证。

## 草稿与迁移

浏览器编辑草稿写入本机 `localStorage`，重新打开时提供恢复或放弃，恢复保留旧版本以触发正常冲突检查。它不是数据库备份，私人输入不应通过共享浏览器环境传播。收到明确的CSRF令牌拒绝时刷新令牌并重试一次；不自动重试超时或结果不明的写入。

原型JSON包含链、配色来源和光路；使用者自填名称、备注和参数须在公开前检查。v0.4没有SQLite结构迁移。旧客户端不能正确计算新链，应更新；没有链的原型仍按旧公式计算。

MCP共27个工具，新增 `optics_search_evidence`、`optics_preview_design` 和 `optics_create_chain_template` 均只读。`optics_calculate_color_budget` 新增可选 `parameters`；关联链要求当前参数。工具列表有缓存时重新连接服务。写入仍使用现有 `optics_apply_design` 及当前版本。
