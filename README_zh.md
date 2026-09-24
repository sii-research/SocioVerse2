<!-- ───────────────────────── Challenge banner ─────────────────────────
     Files: assets/challenge-banner.svg (dark card) + assets/challenge-banner-light.svg.
     Both are self-contained (text outlined to paths, no fonts/scripts/external refs),
     so GitHub renders them through <img>. <picture> follows the viewer's GitHub theme.
     Remove this block (and the Challenge badge and News line) after the awards on 2026-11-08. -->
<p align="center">
  <a href="https://socioverse.fudan-disc.com/challenge/">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="assets/challenge-banner.svg">
      <source media="(prefers-color-scheme: light)" srcset="assets/challenge-banner-light.svg">
      <img alt="SocioVerse Challenge 2026: AI4SS Challenge for Human-AI Collaboration and Social Governance. Three research tracks, $21,050 in prizes and API support, final submission October 31, 2026." src="assets/challenge-banner.svg" width="100%">
    </picture>
  </a>
</p>

<h1 align="center">SocioVerse2</h1>

<p align="center">
  <b>让社会演化可见、可检验。</b><br>
  研究者与 AI 智能体共同构建纵向社会模拟：
  施加干预、开出反事实分支，并复现每一个版本。
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2609.24911"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2609.24911-b31b1b.svg"></a>
  <a href="https://socioverse.fudan-disc.com/"><img alt="Homepage" src="https://img.shields.io/badge/Homepage-socioverse.fudan--disc.com-e67e22.svg"></a>
  <a href="https://socioverse.fudan-disc.com/docs/zh/"><img alt="Docs" src="https://img.shields.io/badge/Docs-user%20manual-2563eb.svg"></a>
  <a href="https://socioverse.fudan-disc.com/challenge/"><img alt="Challenge 2026" src="https://img.shields.io/badge/Challenge%202026-open-f97316.svg"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/License-Apache%202.0-blue.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white">
  <!-- after the first PyPI upload:
  <a href="https://pypi.org/project/socioverse2/"><img alt="PyPI" src="https://img.shields.io/pypi/v/socioverse2.svg"></a> -->
</p>

<p align="center">
  <a href="https://socioverse.fudan-disc.com/">主页</a> ·
  <a href="https://socioverse.fudan-disc.com/docs/zh/">使用手册</a> ·
  <a href="https://arxiv.org/abs/2609.24911">技术报告</a> ·
  <a href="https://socioverse.fudan-disc.com/studies">在线工作台</a> ·
  <a href="https://socioverse.fudan-disc.com/challenge/">2026 挑战赛</a> ·
  <a href="README.md">English</a>
</p>

---

## 动态

- **2026-09-25** SocioVerse2 v0.2.0 开源：运行时、`/sv-*` 工作流 skills、本地研究仪表盘以及参考研究。11 个 ABM 基准研究和芝加哥研究运行在配套仓库 [SocioVerse-ABM](https://github.com/Lishi905/SocioVerse-ABM) 之上。
- **2026-09-21** 技术报告发布于 arXiv：[SocioVerse2: A Longitudinal Dynamic Social Simulation Framework under a Human-AI Co-evolutionary Paradigm](https://arxiv.org/abs/2609.24911)。
- **2026-09-15** [SocioVerse Challenge 2026](https://socioverse.fudan-disc.com/challenge/)（面向人机协同与社会治理的 AI4SS 挑战赛）开放报名。设三个赛道，$21,050 奖金与 API 支持。提案截止 2026-10-09，最终提交截止 2026-10-31（UTC+8 23:59）。成果将在 [LASS 2026 @ CIKM 2026](https://socioverse.fudan-disc.com/challenge/#about) 上交流。以本地开发方式参赛的队伍使用本仓库构建研究。
- **2025-04** 前作 [SocioVerse](https://arxiv.org/abs/2504.10157) 提出了基于千万级真实用户池的社会模拟世界模型。

## SocioVerse2 是什么

SocioVerse2 是一个纵向社会模拟框架。一组固定的 LLM 智能体带着持久 id，生活在一个不断变化的环境中，每一步为每个智能体记录一行面板数据。框架由两个循环和承载它们的一层基础设施组成。

- **纵向模拟循环。** 目标人群在一个以真实世界信号为依据、不断演化的环境中逐步模拟。干预（一个定时事件或一条信息广播）在选定的步骤触发；反事实**分支**会精确重放其父版本之前的步骤，因此处理组与对照组可以逐个智能体比较。
- **可控研究循环。** 研究本身是一个可编辑的状态：人群、环境、行为模型和运行设置。每一次修改都保存为新的**版本**或**分支**，不同设计与反事实之间是比较，而不是覆盖。
- **面向社会科学的智能体基础设施。** 可组合的工作流 skills 在研究者检查点的配合下，把一个问题推进到一份报告。可选的托管数据服务在构建阶段解析人（画像池）和事件（带时点保证的真实世界信号源）。依据账本（grounding ledger）、版本清单和事件表让每一项完成的研究都可审计。

结果是面板数据。任何智能体的轨迹和任何聚合指标都可以用普通 SQL 从 DuckDB 库中查询。

### 关键术语

- **人群（Population）**：一组带持久 id 的固定画像，是纵向追踪的主键。
- **环境（Environment）**：每个智能体在每一步观察到的内容，分两个维度（物理或信息、宏观或局部）。它随时间变化，来源是自身动态和干预。
- **行为模型（Behavior model）**：每个智能体对所观察内容施加的决策函数，可以是规则、LLM 或二者混合。
- **干预（Intervention）**：环境中的一个定时事件或一条广播。它在所属步骤、所有人观察之前触发，因此整轮决策基于同一状态。
- **分支（Branch）**：只从某一步 `t*` 起新增干预、保持人群、行为模型和运行设置不变的版本。`t*` 之前的步骤从父运行重放，不调用 LLM，因此分支与父版本构成处理组与对照组。
- **版本（Version）**：对已运行研究的其他任何修改。它从第 0 步开始运行。
- **复刻（Fork）**：以新 id 复制一个参考研究，再对副本进行编辑。

## 快速开始

### 1. 安装

```bash
git clone https://github.com/sii-research/SocioVerse2.git
cd SocioVerse2

conda create -n socioverse python=3.11 -y && conda activate socioverse   # 或：python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,viz]"

pytest -q    # 无需密钥；需要配套仓库、可选扩展（chicago、workbench）或真实 LLM 的测试会被跳过
```

### 2. 不用 API 密钥运行一个研究

```bash
python scripts/demo_offline.py
```

```text
Running opinion_diffusion_demo (a local copy of opinion_diffusion): 12 agents, 4 steps, llm_kind=scripted

step  mean_opinion  opinion_std  frac_above_0_5
   0         0.500        0.288            0.50
   1         0.500        0.282            0.50
   2         0.618        0.212            0.67
   3         0.707        0.160            0.83
   4         0.737        0.142            1.00
```

该脚本把随仓库提供的参考研究 [`studies/opinion_diffusion`](studies/opinion_diffusion/) 派生为一个本地研究 `studies/opinion_diffusion_demo/`（与你创建的所有研究一样被 gitignore），校验复制过来的产物后在其中运行。参考研究是一个从零构建的模板：环形网络上的 12 个智能体向意见相近的邻居靠拢，第 2 步开始一场媒体宣传（一个定时事件加一条广播）。决策模型以 `llm_kind: "scripted"`（确定性规则）运行，因此免费且可复现。运行结果写入演示研究的 `trajectory/`，也就是 `/sv-run` 写入的位置；渲染出的英文报告和图表位于它的 `reports/`。报告的“数据基础与参考来源”一节直接引自该研究的依据文件（`grounding/grounding.json`），保留该文件的原文语言，即中文。脚本从不写入参考研究，每次运行都会重新生成演示研究。参考研究随仓库提供的报告以中文撰写；加上 `--report-lang zh` 也可以把演示报告渲染成中文。

每次运行都是一个 DuckDB 库，可以用 SQL 查询：

```python
import duckdb
con = duckdb.connect("studies/opinion_diffusion_demo/trajectory/study.duckdb", read_only=True)
con.sql("SELECT step, state->>'opinion' AS opinion FROM panel WHERE agent_id = 'od-000' ORDER BY step").show()  # 单个智能体随时间变化
con.sql("SELECT * FROM metrics ORDER BY step").show()                                                          # 聚合轨迹
con.sql("SELECT step, note FROM events ORDER BY step").show()                                                  # 已触发的定时事件
```

### 3. 打开研究仪表盘

```bash
python dashboard/server/app.py --open        # http://127.0.0.1:8787（用 --port 更换端口）
```

演示会作为一个独立的研究 `opinion_diffusion_demo` 出现在参考研究 `opinion_diffusion` 旁边：它的数据表、曲线和报告都来自你刚才的运行，从参考研究复制来的阶段标记为派生。仪表盘是 `studies/` 的本地视图：阶段状态、环境与人群、DuckDB 数据表、运行中的实时指标曲线、版本对比，以及渲染了公式的报告和论文。它只依赖标准库；数据表需要启动它的解释器中装有 `duckdb`，上面的安装已经包含。`/sv-*` skills 会在研究开始时自动启动它。详见 [`dashboard/README.md`](dashboard/README.md)。

### 4. 用真实 LLM 运行同一个研究

```bash
pip install -e ".[llm]"
cp .env.example .env      # 设置 SV_LLM_API_KEY；SV_LLM_BASE_URL 与 SV_LLM_MODEL 可选
python scripts/demo_offline.py --llm openai
```

`SV_LLM_BASE_URL` 可指向任何兼容 OpenAI 的端点（未设置时为 OpenAI 官方 API），`SV_LLM_MODEL` 选择模型（未设置时使用该研究 `simulation.json` 中的设置）。`llm` 扩展包含 `httpx[socks]`，因此在 `ALL_PROXY` 中设置的 SOCKS 代理同样可用。脚本会先探测一次端点，然后发起 48 次简短调用（12 个智能体 × 4 步），并用这次运行替换演示研究原有的运行。无法解析的回复会回退到规则，并在输出中计数。随仓库提供的这次运行使用中文提示词（其 `simulation.json` 中为 `prompt_lang: "zh"`）；加上 `--prompt-lang en` 即改用英文提示词，基于该模板新建的研究也默认使用英文。

### 5. 用工作流 skills 构建你自己的研究

**你需要准备什么。** 一次 `/sv-*` 研究用到两套彼此独立的 LLM 连接，需要分别配置：

- **运行 skills 的编程智能体。** [Claude Code](https://claude.com/claude-code) 需要它自己的 Claude 登录（Claude 订阅）或 `ANTHROPIC_API_KEY`。`.env` 中的 `SV_LLM_*` 密钥不能驱动 Claude Code，它只用于模拟中的智能体。如果你只有 OpenAI 密钥，可以尝试用 [Codex CLI](https://github.com/openai/codex) 驱动同一套工作流（实验性：Codex 路径尚未做过完整的端到端测试）：它读取本仓库随附的 `AGENTS.md` 和 `.codex/skills/`，两者都由 Claude Code 一侧生成。在 Codex 中，在提示里点名要运行的阶段（例如 `Run sv-init: "How does a rumor spread ..."`），`AGENTS.md` 会让智能体读取该 skill 的 `SKILL.md` 并照做。
- **模拟本身的 LLM**，负责模拟智能体的决策：任何兼容 OpenAI 的服务商都可以，通过 `.env` 中的 `SV_LLM_API_KEY`、`SV_LLM_BASE_URL` 和 `SV_LLM_MODEL` 配置（见第 4 步）。没有它，从零构建的研究仍可在 scripted 模式下完整跑通；`/sv-run` 在花费真实 LLM 调用前会先询问。

在 Claude Code 中打开仓库目录，开启一个新会话，描述你的问题：

```
/sv-init "How does a rumor spread through a mid-sized online community
          when an official correction is broadcast on day 3?"
```

每个 skill 向 `studies/<id>/` 写入一个经过 schema 校验的产物，并在检查点停下等待你审阅：

| skill | 阶段 | 写入 |
|---|---|---|
| `/sv-init` | 为问题选路（复用已有研究、从零构建或包装你自己的模拟器）并确定范围 | `study.yaml`、`grounding/grounding.json` |
| `/sv-build-model` | 在核心接口上实现模型（仅从零构建的研究） | `model.py` |
| `/sv-build-environment` | 环境层、定时事件、信息广播 | `environment/environment.json` |
| `/sv-build-population` | 带持久 id 的固定人群 | `population/population.json`、`population/roster.jsonl` |
| `/sv-run` | 运行循环；在花费 LLM 调用前先询问 | `trajectory/study.duckdb`、`trajectory/metrics_history.json` |
| `/sv-report` | 图表与报告；`/sv-lit` 检索相关文献，`/sv-paper` 起草论文 | `reports/`、`literature/`、`paper/` |
| `/sv-iterate` | 以新版本或反事实分支的方式修改已有研究 | `versions.json`、`versions/vN/` |

`/sv-lit` 需要文献检索的 extra：`pip install -e ".[lit]"`。

> [!NOTE]
> `.claude/settings.json` 和 `.codex/hooks.json` 注册了会话 hooks，它们运行 `python3 dashboard/hooks/sv_emit.py`。这些 hooks 只切换仪表盘上“等待你操作”的提示条；仪表盘本身由 skills 启动。在启动智能体的环境中设置 `SV_DASH_DISABLE=1` 即可同时关闭两者。详见 [SECURITY.md](SECURITY.md)。

## 运行要求与密钥

| 项目 | 用于 | 没有它时 |
|---|---|---|
| Python 3.11+ | 全部功能 | |
| LLM API 密钥：在 `.env` 中设置 `SV_LLM_API_KEY`，使用其他兼容 OpenAI 的端点时再设 `SV_LLM_BASE_URL`；`pip install -e ".[llm]"`。ABM 研究的 LLM 模式改为从环境变量读取 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL` | LLM 决策层（`llm_kind: "openai"`）、ABM 研究的 LLM 行为函数、`consumer_confidence` | 测试、离线演示、从零模板的 `llm_kind: "scripted"` 运行、`germany_auto_market`、规则模式的 ABM 运行、芝加哥研究的空跑、仪表盘以及所有随仓库提供的报告 |
| Claude Code（它自己的 Claude 登录或 `ANTHROPIC_API_KEY`）或 Codex CLI（OpenAI 密钥）；`SV_LLM_*` 密钥不能驱动二者 | `/sv-*` 工作流 skills | 按快速开始的方式从 Python 运行研究 |
| 事件数据服务（可选）：`SV_EVENT_API_URL`、`SV_EVENT_API_KEY` | 构建阶段为环境提供带时点保证的真实世界事件和宏观序列 | 客户端先尝试本地缓存（`SV_EVENT_LOCAL_CACHE`），之后 skills 改用网络搜索，并把每个来源记入依据账本 |
| 用户池数据服务（可选）：`SV_USER_POOL_MCP_URL`、`SV_USER_POOL_MCP_KEY` | 构建阶段从真实平台用户池抽样画像 | skills 依据检索到的锚点或声明的假设合成画像，或加载你自己的画像文件 |

两项数据服务由 SocioVerse 团队托管，不属于本仓库。如需访问，请发邮件至 contact@socioverse.fudan-disc.com。把凭据写入 `.env`，然后运行 `python scripts/gen_mcp_json.py` 为编程智能体注册它们。没有这些服务不会导致任何功能失效，也不会静默伪造数据。[在线工作台](https://socioverse.fudan-disc.com/studies)已配置好这两项服务。

随仓库提供的从零构建研究在 `simulation.json` 中固定了模型（`decision_args.model`），`consumer_confidence` 固定在 `environment.json` 中（`prediction.model`），ABM 研究则固定在 SocioVerse-ABM 中该任务的 `config.yaml` 里（`behavior.llm_model`，可在 `abm_*` 研究的 `make_bundles` 中用 `config_overrides={"behavior": {"llm_model": ...}}` 覆盖）。若所用端点不提供该模型，请在上述位置修改；已经运行过的研究请通过 `/sv-iterate` 修改。`SV_LLM_MODEL` 由 `scripts/demo_offline.py`、芝加哥适配器以及 `simulation.json` 未指定模型的研究读取。

密钥只保存在已被 gitignore 的 `.env` 中，见 [`.env.example`](.env.example)。不用密钥运行时，在从零构建研究的 `simulation.json` 中使用 `llm_kind: "scripted"`，`chicago_schelling` 则使用 `DeterministicLLMClient`。详见 [LLM 客户端与空跑](https://socioverse.fudan-disc.com/docs/zh/guides/llm-clients/)。

安装 extras：

| extra | 增加 |
|---|---|
| `llm` | 用于真实 LLM 运行的 OpenAI 兼容客户端，支持 SOCKS 代理 |
| `viz` | 用于报告图表的 matplotlib |
| `workbench` | `llm` + `viz`，外加 textblob（`hisim_roe` 的情感打分器）和 openpyxl（`germany_auto_market` 的工作簿） |
| `lit` | `/sv-lit` 背后检索引擎的依赖 |
| `abm` | 11 个 `abm_*` 研究所需的 numpy 和 networkx |
| `chicago` | `chicago_schelling` 的地理与 Mesa 依赖，并包含 `abm` 的全部内容 |
| `dev` | pytest、build、twine |
| `all` | 以上全部 |

## 配套仓库

部分研究包装了位于独立仓库中的项目。把它克隆到本仓库旁边即可被自动发现，相应的测试也不再跳过。

```
workspace/
├── SocioVerse2/
├── SocioVerse-ABM/                               # 11 个 abm_* 研究与 chicago_schelling
└── ConsumerSim-Consumer-Confidence-Forecast/     # consumer_confidence
```

**[SocioVerse-ABM](https://github.com/Lishi905/SocioVerse-ABM)** 包含 11 个经典的基于智能体的模型（每个都有规则行为函数和 LLM 行为函数），以及芝加哥隔离模型及其人口普查数据。

```bash
cd ..                                                  # 包含 SocioVerse2 的目录
git clone https://github.com/Lishi905/SocioVerse-ABM.git
cd SocioVerse2
pip install -e ".[dev,chicago,workbench]"
pytest -q                                              # ABM 与芝加哥测试现在会运行
```

目录名必须恰好是 `SocioVerse-ABM`。芝加哥模型即使空跑也会构造 OpenAI 客户端；`chicago` 扩展为该客户端包含了 `httpx[socks]`，因此 `ALL_PROXY` 中的 SOCKS 代理同样可用。芝加哥数据有其自身的使用条款，其中包括一个仅限非商业用途的字段；见 SocioVerse-ABM 的数据声明。

**[ConsumerSim](https://github.com/RunRiotComeOn/ConsumerSim-Consumer-Confidence-Forecast)** 是 `consumer_confidence` 所包装的消费者信心预测管线：

```bash
cd ..
git clone https://github.com/RunRiotComeOn/ConsumerSim-Consumer-Confidence-Forecast.git
```

**[HiSim](https://github.com/xymou/HiSim)** 为可选项。`hisim_roe` 原生重新实现了它的混合模式，不依赖它也能运行；当本仓库旁边有 HiSim 检出、且准备好其 Roe v. Wade 用户数据（`data/user_data/roe`，按 HiSim README 的说明准备）时，会额外运行四个测试。

其他目录布局可在 shell 或 `.env` 中设置 `SV_ABM_ROOT`、`SV_CHICAGO_LEGACY`、`SV_CONSUMERSIM_ROOT` 或 `SV_HISIM_ROOT`；见 [`.env.example`](.env.example)。

## 仓库结构

```
socioverse/            运行时包（import socioverse）
  schemas/             每次交接的类型化契约（Pydantic）
  abc/                 研究需要实现的接口
  engine/              纵向循环、注册表、智能体记忆、消息总线
  env_layers/          信息广播与邻居信息流
  io/                  DuckDB 面板 / 指标 / 事件存储
  providers.py         文件与服务人群提供器
  external_events.py   事件服务客户端及其回退链
  validation.py        每个阶段边界上的严格校验
.claude/skills/        /sv-* 工作流 skills（另含两个第三方的写作与检索 skill）
.codex/, AGENTS.md     面向 Codex 的同一套接口（自动生成）
skills/                skills 调用的 Python 辅助模块（目录、依据、文献、论文）
dashboard/             本地研究仪表盘（服务端 + Web 界面）
resources/             可选服务的能力注册表
studies/               参考研究与模板，每个研究一个目录
scripts/               离线演示、MCP 注册、智能体接口同步、静态导出
tests/                 pytest 测试集
assets/                README 图片
```

可安装的包只有 `socioverse/`（分发名 `socioverse2`）。skills、仪表盘和研究都在本仓库的检出中使用。

## 参考研究

| 研究 | 展示内容 | 可离线运行？ | 需要 |
|---|---|---|---|
| [`opinion_diffusion`](studies/opinion_diffusion/) | 从零模板：有界信心意见动态、一个定时事件和一条广播、分支重放 | 可以，`llm_kind: "scripted"`（即快速开始中的演示） | `llm_kind: "openai"` 需要 LLM 密钥 |
| [`campus_dining_choice`](studies/campus_dining_choice/) | 从零模板：随食堂与外卖价格上涨，宿舍内多轮讨论（消息总线）与第一人称的 LLM 理由 | 可以，使用 `llm_kind: "scripted"` | 随仓库提供的 `llm_kind: "openai"` 需要 LLM 密钥 |
| [`germany_auto_market`](studies/germany_auto_market/) | 一份上传的工作簿同时为人群和环境提供依据：2024-01 至 2026-05 德国汽车品牌市场份额，以 KBA 注册数据评分 | 可以（随仓库提供 `llm_kind: "scripted"`） | `workbench` extra（读取 `.xlsx`） |
| [`hisim_roe`](studies/hisim_roe/) | 混合意见动态：少数 LLM 核心用户加上基于规则的普通人群，以观测到的 Twitter 情感（Roe v. Wade）评分 | 导入型参考：序列来自技术报告，不重新运行 | 查看无需任何依赖；`workbench` extra 提供其情感打分器 |
| [`consumer_confidence`](studies/consumer_confidence/) | 包装外部预测管线：同一个月内随信息累积变化的消费者信心 | 不可以 | 本仓库旁边的 ConsumerSim 与 LLM 密钥 |
| [`consumer_confidence_us_backtest`](studies/consumer_confidence_us_backtest/) | 回测模板：月度预测与事后公布的密歇根大学指数并列，附逐月误差和受访者面板 | 导入型参考：不重新运行；`build_from_source.py` 从固定版本的 ConsumerSim 公开数据逐字节重建（`--latest` 读取当前 CSV） | 重建需要网络访问 |
| [`chicago_schelling`](studies/chicago_schelling/) | 零改动包装一个已验证的遗留模拟器：基于 2010 年人口普查区的芝加哥隔离、一项交通干预和一条政策广播 | 用 `DeterministicLLMClient` 空跑 | SocioVerse-ABM、`chicago` extra；真实运行需要 LLM 密钥 |
| `abm_*`（11 个）：[`abm_axelrod`](studies/abm_axelrod/)、[`abm_boids`](studies/abm_boids/)、[`abm_civil_violence`](studies/abm_civil_violence/)、[`abm_hegselmann_krause`](studies/abm_hegselmann_krause/)、[`abm_lux_marchesi`](studies/abm_lux_marchesi/)、[`abm_minority_game`](studies/abm_minority_game/)、[`abm_nasch`](studies/abm_nasch/)、[`abm_schelling`](studies/abm_schelling/)、[`abm_sir`](studies/abm_sir/)、[`abm_social_force`](studies/abm_social_force/)、[`abm_sugarscape`](studies/abm_sugarscape/) | 经典的基于智能体的模型，其 LLM 行为函数与规则进行对照检验 | 可以，规则模式 | SocioVerse-ABM 与 `abm`（或 `chicago`）extra；LLM 模式需要 LLM 密钥 |

每个完整的研究目录都遵循同一布局（`study.yaml`、`environment/`、`population/`、`simulation/`、`grounding/`、`reports/`），这也是挑战赛的提交格式。`abm_*` 目录只是薄封装（`study.yaml` 和 `__init__.py`），其数据包由 [`studies/_abm_common`](studies/_abm_common/) 构建。`/sv-init` 读取同一份元数据：只有在研究所需条件齐备时才会复刻它，其他研究会连同配置所需的命令一起列出。

## 文档

- [使用手册](https://socioverse.fudan-disc.com/docs/zh/)（[English](https://socioverse.fudan-disc.com/docs/)）：安装、概念、指南、完整示例、API 参考。
- 指南：[从零构建研究](https://socioverse.fudan-disc.com/docs/zh/guides/build-a-study/) · [包装已有模拟器](https://socioverse.fudan-disc.com/docs/zh/guides/wrap-legacy-model/) · [版本与分支](https://socioverse.fudan-disc.com/docs/zh/guides/iterate-versions-branches/) · [运行仪表盘](https://socioverse.fudan-disc.com/docs/zh/guides/dashboard/) · [数据服务](https://socioverse.fudan-disc.com/docs/zh/guides/data-services/)
- [`CLAUDE.md`](CLAUDE.md) 是编程智能体阅读的工作指南；[`README-dev.md`](README-dev.md) 和 [`CLAUDE-dev.md`](CLAUDE-dev.md) 介绍如何扩展框架。
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md)

## 引用

如果你使用了 SocioVerse2，请引用技术报告：

```bibtex
@misc{zhang2026socioverse2,
  title         = {SocioVerse2: A Longitudinal Dynamic Social Simulation Framework under a Human-AI Co-evolutionary Paradigm},
  author        = {Xinnong Zhang and Jiayu Lin and Jia Wang and Yixu Huang and Xinyi Mou and Yingqian Wu and Jingcong Liang and Shijun Lei and Jianing Shi and Guanying Li and Siyuan Wang and Hanjia Lyu and Zhenfei Yin and Yunlu Yin and Siming Chen and Yulan He and Jiebo Luo and Xuanjing Huang and Liyin Jin and Baohua Zhou and Hanqi Yan and Zhongyu Wei},
  year          = {2026},
  eprint        = {2609.24911},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  url           = {https://arxiv.org/abs/2609.24911}
}
```

<details>
<summary>前作 SocioVerse（2025）</summary>

```bibtex
@misc{zhang2025socioverse,
  title         = {SocioVerse: A World Model for Social Simulation Powered by LLM Agents and A Pool of 10 Million Real-World Users},
  author        = {Xinnong Zhang and Jiayu Lin and Xinyi Mou and Shiyue Yang and Xiawei Liu and Libo Sun and Hanjia Lyu and Yihang Yang and Weihong Qi and Yue Chen and Guanying Li and Ling Yan and Yao Hu and Siming Chen and Yu Wang and Xuanjing Huang and Jiebo Luo and Shiping Tang and Libo Wu and Baohua Zhou and Zhongyu Wei},
  year          = {2025},
  eprint        = {2504.10157},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  url           = {https://arxiv.org/abs/2504.10157}
}
```

</details>

GitHub 上的 “Cite this repository” 按钮使用 [`CITATION.cff`](CITATION.cff)。

## 许可证

代码以 [Apache License 2.0](LICENSE) 发布。数据文件有其各自的条款，第三方组件保留各自的许可证；见 [`NOTICE`](NOTICE)。

## 致谢

除技术报告的作者外，我们还感谢：

- **Jia Wang**（[@JiaWANG-TJ](https://github.com/JiaWANG-TJ)）对工作流 skills、会话 hooks 和 Codex 支持的贡献。
- **[@RunRiotComeOn](https://github.com/RunRiotComeOn)** 提供 ConsumerSim、`consumer_confidence` 适配器，以及 `consumer_confidence_us_backtest` 所用的 ConsumerSim 公开数据。
- SocioVerse-ABM 中经典模型原始实现的贡献者：**Shijun Lei**（[@ShijunLei-cn](https://github.com/ShijunLei-cn)）、**Jianing Shi**（[@Brishian427](https://github.com/Brishian427)）、**Chenyu Li**（[@if111111111111111111111](https://github.com/if111111111111111111111)）和 **Jia Wang**（[@JiaWANG-TJ](https://github.com/JiaWANG-TJ)）。

本仓库包含以下第三方内容，并原样保留其许可证：

- [paper-search-pro](https://github.com/O0000-code/paper-search-pro)（Apache-2.0），`/sv-lit` 背后的检索引擎，位于 `.claude/skills/paper-search-pro/`。
- [Research-Paper-Writing-Skills](https://github.com/Master-cai/Research-Paper-Writing-Skills)（MIT），`/sv-paper` 背后的写作指导，位于 `.claude/skills/research-paper-writing/`。
- [KaTeX](https://katex.org) 0.18.7（MIT），用于仪表盘中的公式渲染，位于 `dashboard/web/v2/vendor/katex/`。
- 改编自 [HiSim](https://github.com/xymou/HiSim)（Apache-2.0；Mou et al., Findings of ACL 2024）的核心用户 prompt，位于 `studies/hisim_roe/model.py`。

问题与合作：contact@socioverse.fudan-disc.com。挑战赛相关问题：challenge26@socioverse.fudan-disc.com。
