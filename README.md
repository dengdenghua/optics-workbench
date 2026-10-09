# Optics Workbench · AI 光学工作台

本地光学资料数据库、可编辑光路工作台与 MCP 服务。选择光源、准直透镜、复眼和棱镜，查看 2D 近轴代表光线或可旋转的 3D 理想折转示意，计算有条件的能量预算，保存版本，再通过 JSON 迁移到另一台电脑。可在 Codex 中通过 MCP 下达设计指令，也可选用内置 OpenAI 聊天。

**公开仓库只包含代码、数据库结构和合成演示数据。** 个人工作文档、历史器件目录、模型、Skill 私人引用和实际数据库由使用者在本机配置，不随仓库发布。

**v0.4.0** 新增显式分段预算链、当前计算来源对照、本地证据片段选择、AI 草案差异预览及浏览器草稿恢复。详见 [联动与证据工作流](docs/design-workflow.md)。

## 配色与亮度

左侧 **配色与亮度** 可编辑最多24个光源的色坐标、lm/输出光学W/泵浦W、数量、工况修正和前段效率；先合并各RGB组的XYZ，再求目标白点的时序或同时调光。可用角度明确扣除消隐，已平均输入不会再次乘占空比。结果含白场lm、条件屏幕lm/lx/cd/m²、xy与u′v′基色图、P3/BT.709面积比与交集覆盖；缺少或矛盾的电热输入显示未确认。

配置本机 `skill_dir` 后，页面和MCP可读取已核读工作簿的本地证据JSON，展示原表缓存、同原角度独立复算、白点精确求解和单元格审计；原始Excel只读，不被执行或改写。没有个人证据时仅提供合成RGB演示。案例的屏幕面积/后段效率等占位条件须按新需求替换，历史输入不是通用器件规格。

配色预算随原型版本保存并随JSON迁移。默认与光路和标量预算分别计算；选择输入面后的分段链时，可显式关联当前原型效率参数，并在屏幕重新求解白点。光路的近轴光扇不提供效率。完整公式与边界见 [配色计算说明](docs/color-brightness.md)。

## 开始使用

需要 Python 3.10 或更新版本。运行时只使用 Python 标准库。可视化、计算和 MCP 不需要额外 API Key；内置聊天需要独立 OpenAI API 配置，见 [AI 入口说明](docs/ai.md)。

```sh
git clone https://github.com/dengdenghua/optics-workbench.git
cd optics-workbench
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m optics_workbench --config config.example.json
```

macOS / Linux：

```sh
.venv/bin/python -m pip install -e .
.venv/bin/python -m optics_workbench --config config.example.json
```

打开 **http://127.0.0.1:8788**。首次运行会在 `data/` 创建 SQLite 数据库和演示原型。端口占用时加 `--port 8789`。终端按 Ctrl+C 停止服务。

1. 创建原型，选择光学元件，编辑位置、孔径、焦距或复眼节距；切换 2D / 3D 查看代表光线。
2. 展开标量参数与能量预算，填写光源、准直、复眼、棱镜和效率。光路与标量预算分别编辑，互不自动覆盖。
3. 保存整个原型。页面每 2.5 秒同步 MCP / 其他窗口保存的版本；有本地修改时提示冲突并可另存副本。内置 AI 需先保存，再发送指令。
4. 导出 JSON，在另一台工作台导入。**迁移文件会包含原型名称、备注、器件引用和配色预算，公开分享前请检查。**

也可以在仓库目录直接运行 `python -m optics_workbench --config config.example.json`。`pip install .` 安装方式包含网页资源，可在仓库外运行命令 `optics-workbench`。

## 有什么

| 模块 | 当前能力 |
| --- | --- |
| 配色与亮度 | 多光源XYZ、目标白点、RGB时序/消隐、条件屏幕lm/lx/cd/m²、xy/u′v′色域图与原表核读对照 |
| 参数原型 | 光源 → 准直 → 复眼 → 棱镜 → 效率；输入、条件预算、保存与迁移 |
| 光路可视化 | 2D 展开近轴光扇、可旋转 3D 理想折转、元件编辑、孔径截光 |
| AI 入口 | Codex / MCP 与可选内置 OpenAI 聊天；验证后按版本原子保存 |
| 资料数据库 | SHA 去重记录、范围核读/未读状态、来源与核读说明、中文检索 |
| 器件参考库 | 三类候选器件，保留来源与历史参数；逐项选择是否采用建议 |
| 设计知识 | 本地蒸馏笔记与规则检索；原文作为纯文本展示 |
| 模型索引 | 检索模型元数据和位置；不启动或修改原生模型 |
| MCP / Skill | 24 个 stdio MCP 工具，便携插件 manifest 和通用调用 Skill |

示例数据是合成输入，不对应厂商产品或测量结果。UI 默认采用中文；Python API、MCP 及导出格式可独立使用。

## 计算边界

这是解析起算与方案记录工具。光路使用单子午面的近轴斜率、薄透镜与局部复眼单元；不生成真实透镜处方，也不通过原生软件验收效率或均匀性。3D 视图将展开光路作理想折转，未计算棱镜 Snell 折射、TIR、偏振或膜系。达屏光线条数没有能量权重，不能当作效率。

- 准直：空气中的分轴扩展量匹配，有限源在理想薄透镜焦面的角度与焦距估计。
- 复眼：近轴重叠成像，按中继与单元焦距比估计单元像覆盖；节距、有效口径、焦距分别输入。
- 棱镜：指定界面实数折射率和内部角区间的临界角裕量。等于指定裕量的边界不算通过。PBS 只保留手填通量效率，消光比待膜系和偏振验证。
- 通量：朗伯角收集或用户输入收集比例，乘以各级效率。覆盖/角度不满足时不会自动推断损失，所以输出始终是条件预算。

少量确定性光线、角度与位置映射可以作为准直优化的前期方法；有限光源、像差、渐晕、偏振、热与公差仍需相应的 LightTools/Zemax 模型或测量。当前版本不连接这两个软件。计算定义详见 [calculation-notes.md](docs/calculation-notes.md)。

## 接入自己的资料

复制 `config.example.json` 为 Git 忽略的 `config.local.json`，根据 [数据接口说明](docs/data-format.md) 设置可选项：

```json
{
  "data_dir": "./data",
  "coverage_file": "../my-private-data/coverage-by-sha256.json",
  "skill_dir": "../my-private-data/projection-optical-design",
  "snapshot_note": "说明清单快照时间及核读范围"
}
```

```sh
python -m optics_workbench --config config.local.json
```

同步读取覆盖清单和已蒸馏的 Skill 引用/目录，不会重新打开全部源文档。它更新检索索引，保留原型及版本。已含个人索引的数据库在缺少配置时拒绝被演示库覆盖。原文件是否后来变更仍需独立核验。

服务仅绑定 `127.0.0.1`；浏览器写操作需要当前会话令牌。数据库是未加密的本地 SQLite 文件。不要将本服务直接暴露到公网，也不要提交 `data/`、`config.local.json` 或自己的资料副本。

## MCP、插件与迁移

[MCP 接入说明](docs/mcp.md) 给出 Codex、通用 stdio 客户端与 `plugin/` 用法。先把本仓库安装到目标 Python 环境，再连接：

```sh
python -m optics_workbench.mcp_server --config config.local.json
```

网页与 MCP 使用相同配置，即读写同一数据库。复制代码或插件不会上传、同步或复制你的数据库。MCP 客户端获得的资料内容可能进入该客户端的模型上下文。

迁移另一台机器时：安装仓库和 MCP；自行拷贝所需私有资料/数据库；修改本机路径；或只导出和导入参数原型。原型导入会重新计算；另一台机器缺少的器件引用会解除关联并提示重新选择。宿主没有插件导入功能时，可直接使用 MCP 加独立 Skill。

## 验证与开发

```sh
python -m unittest discover -s tests -v
```

测试覆盖公式边界、零通量、无效输入、持久化、并发版本冲突、迁移重新计算、私人索引防覆盖、HTTP 本机请求保护，以及 MCP 协议与真实数据库流程。额外 SDK / schema 验证范围见 [MCP 文档](docs/mcp.md)。

源代码结构：`optics_workbench/` 为共用核心、SQLite 结构和服务；`web/` 为无 CDN 的前端；`plugin/` 为通用插件桥接；`examples/` 为合成演示；`tests/` 为可重复测试。未包含私人学习交付包。

MIT License。欢迎提交问题和改进；请使用合成示例复现问题，避免公开工作资料。
