# 信息累积下的信心预测：分层 LLM 硅样本 + 贝叶斯扩展的点时安全面板模拟

## Abstract

We forecast US consumer confidence for a single target month (2026-06) as a *point-in-time-safe information-accrual panel*: a fixed pool of 12 demographically distinct SocioVerse agents is re-surveyed at three as-of cutoffs (06-13, 06-20, 07-01), each time conditioning only on news published up to that cutoff. At every step a stratified core of 6 agents answers the five Michigan-style sentiment questions via a real LLM (gpt-4o-mini, structured JSON), and the remaining agents are inferred through hierarchical Bayesian small-area expansion — 18 simulation-layer LLM calls in total. The corrected headline score traces 129.8 → 139.8 → 123.2, an inverted V that tracks the information environment (combined_score 0.056 → 0.090 → 0.068) rather than drifting with time: news volume accrues monotonically (4 → 5 → 10 items) while net news sentiment peaks on 06-20 and is then diluted by mixed coverage. Component scores reproduce the classic Present-Situation vs Expectations split reported by the Conference Board for June — current-finance falling (133 → 108) while 12-month business expectations climb (133 → 175) — on a fully synthetic panel. We argue information accrual is a defensible longitudinal axis for survey simulation when future months are unobservable, and discuss scale-calibration limits of silicon samples.

## 1 引言

消费者信心指数每月只发布一次，但支撑它的信息环境每天都在变化。对模拟预测而言这提出一个方法问题：在不编造未来数据的前提下，固定人群的"纵向"轴应当是什么？本文的回答是**同一目标月内的信息累积**：把 2026-06 的预测按三个 as-of 截止日切片，每步只允许智能体看到发布日 ≤ 截止日的新闻——一个点时安全（point-in-time-safe）的信息集序列。

预测层采用"分层硅样本 + 贝叶斯扩展"的两段式：6 个按 age×income×education×location 分层的核心样本由真实 LLM 直接作答五个密歇根式调查问题，其余 6 人经分层贝叶斯小域模型从核心后验扩展。全程仅 18 次模拟层 LLM 调用，即覆盖全体人群的信心分布。

## 2 相关工作

**LLM 硅样本。** Argyle 等提出并验证了"算法保真"：条件在真实人口属性上的语言模型可作为特定亚人群的有效代理 [argyle2023out]。本研究的核心样本层正是该范式的预测型应用。营销学对硅样本的系统审视 [sarstedt2024using] 表明其结果随领域与提示差异显著、须以人类基准校准——这直接塑造了本文对读数的立场：看方向与分项结构，不看绝对点位。

**文本情绪与信心指数。** O'Connor 等证明社媒文本情绪率与消费者信心调查显著相关 [oconnor2010from]；大规模社媒情绪的心理测量学建模进一步刻画了事件冲击下的情绪响应 [bollen2021modeling]。新闻文本的情绪标注比评论更复杂——目标多元且立场混杂 [alexandra2013sentiment]，这解释了本模型信息层用相关度加权净情绪的设计。宏观上，"新闻冲击"文献表明预期性信息可以先于基本面驱动波动 [beaudry2006stock]——信息累积改变信心，正是该传统的微观机制化。

## 3 方法

**人群 P。** 12 个 agent 恰好覆盖 12 个互异人口格（age×income×education×location）。core_ratio 上调至 0.5（声明的假设：默认 0.10 在 12 人池会塌缩为单人核心），得到 6 人分层核心。

**环境 E。** 信息层为点时安全新闻集（news.jsonl，覆盖 2026-06-12 → 07-01，逐步纳入 4 → 5 → 10 条），`InformationEnvironmentBuilder` 按相关度加权求净情绪 news_score，与（本窗口为空的）指标分合成 combined_score 作为核心样本的信息冲击输入。

**决策 B。** 每核心样本每步一次 gpt-4o-mini 结构化 JSON 预测（五个问题各给 positive/neutral/negative），非核心 agent 由分层贝叶斯小域扩展（多项式后验传播）。头条分经 `PreviousMonthCorrector` 施加 +1.5 的上月残差回归修正。

**指标。** raw/corrected 头条分、五个分项分、combined/news_score、news_count；面板逐步落 DuckDB。

## 4 结果

![修正前后头条分与信息环境的两联轨迹](figures/forecast_trajectory.png)

**预测跟随信息而非时间。** corrected_score 走出 129.8 → 139.8 → 123.2 的倒 V，与 combined_score（0.056 → 0.090 → 0.068）几乎同形。同一目标月按 as-of 切片，能直接读出"信息何时最乐观"。

**信息量与信息情绪解耦。** news_count 单调累积（4 → 5 → 10），但 news_score 在 06-20 达 0.20 后回落至 0.15：06-26 之后新增的多为中性/混杂标题，稀释了早期"油价回落"利好——"新闻更多"不等于"情绪更好"。

![信息累积与净情绪的背离](figures/info_accrual.png)

**分项分化复现实证结构。** 前瞻性商业预期单调爬升（business_12m：133 → 158 → 175），当期财务与耐用品购买先升后大幅回落（current_finance：133 → 108；durable_buying 在 116.7 ↔ 75.0 间摆动）。这与 grounding 记录的 Conference Board 6 月实证同构：Present Situation −3.0 而 Expectations +3.0——完全合成的人群复现了同向的"当期弱/远期强"分裂。

![五个分项的分化](figures/component_scores.png)

**两段式按设计工作。** 每步 6 核心 LLM 预测 + 6 贝叶斯扩展，population_size 与 core_size 全程恒定；核心多数回答 neutral，头条波动主要由个别样本在 positive/negative 间的翻转驱动。

## 5 讨论

**信息累积是可辩护的纵向轴。** ConsumerSim 原生是单步月度预测；把纵向轴设为同月内 as-of 推进，既不编造未来月份数据，又让固定面板真正"动"起来——这为数据受限下的纵向模拟提供了一个通用范式。

**量纲须作风格化解读。** 本模拟头条分落在 ~120–140，而同月真实 Conference Board CCI 为 91.2、UMich ICS 仅 44.8：绝对水平明显偏高（声明的假设 a-index-scale-mapping）。可迁移的信号是方向与结构——倒 V 的时序形状与"当期弱/远期强"的分项分裂均与实证吻合，这与硅样本文献"校准后方可读点位"的结论一致 [sarstedt2024using]。

**小样本抖动。** n=12 的展示规模下单个核心样本的翻转被放大；扩池到 500（core_ratio 0.1 → ~50 核心）是抑制头条分方差的直接下一步。其余方向：接入 as-of 之前的真实宏观指标校准量纲、关掉利好新闻的反事实、以及 2026-07 的跨月扩展验证（真实 UMich 已回升至 54.4）。

## 6 结论

分层 LLM 硅样本 + 贝叶斯扩展 + 点时安全信息集的组合，用 18 次 LLM 调用产出了方向与结构均可与实证对话的信心预测轨迹。方法上，本文示范了"同月信息累积"作为纵向轴的可辩护性；证据上，倒 V 头条与当期/远期分裂在完全合成的面板上得到复现——信息环境（而非时间本身）是信心变化的驱动。

## References

- [argyle2023out] Argyle, L., Busby, E., Fulda, N., Gubler, J., Rytting, C., & Wingate, D. (2023). Out of one, many: Using language models to simulate human samples. *Political Analysis*.
- [sarstedt2024using] Sarstedt, M., et al. (2024). Using large language models to generate silicon samples in consumer and marketing research. *Psychology & Marketing*.
- [oconnor2010from] O'Connor, B., Balasubramanyan, R., Routledge, B., & Smith, N. (2010). From tweets to polls: Linking text sentiment to public opinion time series. *ICWSM*.
- [bollen2021modeling] Lansdall-Welfare, T., et al. (2021). Modeling public mood and emotion: Twitter sentiment and socio-economic phenomena. *(journal per OpenAlex record)*.
- [alexandra2013sentiment] Balahur, A., et al. (2013). Sentiment analysis in the news. *(per OpenAlex record)*.
- [beaudry2006stock] Beaudry, P., & Portier, F. (2006). Stock prices, news, and economic fluctuations. *American Economic Review*.
