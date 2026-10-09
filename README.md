# Optics Workbench · 光学参数工作台

本地光学资料数据库、参数原型工作台与 MCP 服务。选择光源参数，关联准直透镜、复眼和棱镜候选，计算条件预算，保存版本，再通过 JSON 迁移到另一台电脑。

**公开仓库只包含代码、数据库结构和合成演示数据。** 个人工作文档、历史器件目录、模型、Skill 私人引用和实际数据库由使用者在本机配置，不随仓库发布。

## 开始使用

需要 Python 3.10 或更新版本。运行时只使用 Python 标准库，不需要 API Key。

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

1. 在参数工作台创建原型，依次填写光源、准直、复眼、棱镜和效率。
2. 点击计算，查看预算、适用条件和待验证项；输入变更会使旧结果失效。
3. 保存原型，保留计算和版本。多个窗口同时修改时，过期版本会提示重新加载。
4. 导出 JSON，在另一台工作台导入。**迁移文件会包含原型名称、备注和器件引用，公开分享前请检查。**

也可以在仓库目录直接运行 `python -m optics_workbench --config config.example.json`。`pip install .` 安装方式包含网页资源，可在仓库外运行命令 `optics-workbench`。

## 有什么

| 模块 | 当前能力 |
| --- | --- |
| 参数原型 | 光源 → 准直 → 复眼 → 棱镜 → 效率；输入、条件预算、保存与迁移 |
| 资料数据库 | SHA 去重记录、范围核读/未读状态、来源与核读说明、中文检索 |
| 器件参考库 | 三类候选器件，保留来源与历史参数；逐项选择是否采用建议 |
| 设计知识 | 本地蒸馏笔记与规则检索；原文作为纯文本展示 |
| 模型索引 | 检索模型元数据和位置；不启动或修改原生模型 |
| MCP / Skill | 15 个 stdio MCP 工具，便携插件 manifest 和通用调用 Skill |

示例数据是合成输入，不对应厂商产品或测量结果。UI 默认采用中文；Python API、MCP 及导出格式可独立使用。

## 计算边界

这是解析起算与方案记录工具。它不生成透镜处方，也不通过原生软件验收效率或均匀性。

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
