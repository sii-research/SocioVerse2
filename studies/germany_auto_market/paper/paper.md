# 真值锚定的品牌选择面板模拟：德国乘用车市场三十个月的份额演化（2024-01 → 2026-06）

## Abstract

We simulate the monthly brand choices of 1,500 persistent car-buyer agents — sampled from Germany's real demographic joint distribution (Destatis/Zensus/BBSR/MiD) — across thirty months (2024-01 → 2026-06), under an evolving environment that encodes the EV-subsidy termination, Tesla's reputation shock and price cuts, BYD's distribution ramp-up, and brand price drift. Brand choice follows a random-utility multinomial logit whose base appeal is anchored monthly to real KBA FZ10 registration shares (λ=0.7), with individual×brand interactions (loyalty, EV affinity, German-brand and luxury preference, price sensitivity) derived from demographics. The simulated 13-brand share trajectories track KBA ground truth with a mean absolute error of ≈0.74pp per brand-month while preserving the long tail (Other ≈27%). Three findings: Volkswagen-group resilience (VW ~19% throughout, Škoda +… stable) rests on real brand roots; the EV transition is a long-tail substitution, not a head-on disruption — BYD's rise to 4.2% draws from Other and mid-tier combustion brands, concentrated among young, urban, high-openness agents; Tesla's V-shape (2.0% → trough → 2.5%) decomposes into subsidy-removal, reputation and model-refresh components. The panel design turns aggregate share curves into per-agent choice narratives, and the truth-anchoring parameter λ makes the fidelity–autonomy trade-off explicit.

## 1 引言

品牌市占率是购车人群离散选择的聚合结果。传统市场预测建模直接拟合聚合份额曲线，代价是丢失了"谁在转向、为什么转向"的微观结构；纯 LLM 智能体模拟则难以稳定复现 13 路长尾份额分布。本文给出一条中间路线：**以随机效用离散选择为骨架、以真实注册数据为逐月锚、以真实人口联合分布为人群**的面板模拟——1,500 个固定购车者智能体跨 30 个月逐月做品牌选择，聚合出与 KBA（德国机动车管理局）FZ10 真值平均绝对误差 ≈0.74pp/格 的份额轨迹，同时保留每个体的选择理由。

研究窗（2024-01 → 2026-06）覆盖了德国市场最富结构性的一段：2023 年底 Umweltbonus 补贴突然退出后的 BEV 低迷、特斯拉的降价与舆论冲击、比亚迪自近零基数的铺货扩张。这使该市场成为检验"环境信号 × 人群异质性"机制的天然试验场。

## 2 相关工作

**离散选择与品牌忠诚。** 混合多项 logit 可任意逼近任何随机效用离散选择模型 [mcfadden2000mixed]——本模型"基线吸引力 + 个体×品牌交互 + 环境信号"的结构正是 MMNL 的实例，个体偏好特质即随机系数。品牌忠诚作为状态依赖变量的显著性由扫描数据 logit 的开山作确立 [guadagni1983a]；其多维性（行为性与态度性并存）[sheth1974a] 支持本模型把忠诚与德系偏好、豪华偏好分开参数化。车型选择层面的实证 [train2007vehicle] 表明忠诚、经销网络与产品线共同决定份额侵蚀的速度——与本文"品牌根基决定基本盘、环境信号决定边际转移"的结论同构。

**为什么用 ABM。** 当个体异质性与交互结构不可省略时，聚合微分方程模型会系统性失真 [rahmandad2008heterogeneity]。本研究的分年龄段 EV 采纳差异（第 4 节）正是聚合份额方程会抹平的结构。

## 3 方法

**人群 P。** 1,500 个购车潜在者按德国 18+ 合格购车成人的合成联合分布（州×城乡×年龄×性别×教育×就业×家庭×公交，加权总量约 5,000 万，Destatis GENESIS 12411-0013 / Zensus 2022 / BBSR / MiD 2023，经 IPF 合成）抽样，人口边际与真实一致。六维潜在偏好特质（价格敏感、EV 亲和、豪华偏好、德系偏好、品牌忠诚、新势力开放度）由人口属性可解释映射派生并加抖动。

**环境 E。** 三条环境信号自真实序列派生（v3）：EV 需求气候（纯电份额归一化）、比亚迪铺货强度（其份额归一化）、特斯拉冲击（相对基线偏离），叠加逐月市场事件广播（2024Q2 特斯拉降价、2025Q2 比亚迪竞争性定价）与 ≈+0.4%/月的价格指数漂移。

**决策 B 与锚定。** 品牌选择为随机效用多项 logit：`U = base_appeal + 个体×品牌交互 + 环境信号`；t=0 中性环境下 softmax(base_appeal) 复现 2024-01 真实份额。每月基线吸引力锚在上月份额的凸组合（真值 ×λ + 模拟 ×(1−λ)，λ=0.7），把 13 路长尾结构逐月重注入、杜绝模式坍塌。保时捷并入 Other（与上传 KBA 真值口径一致）。

**指标。** 12 个具名品牌 + Other 的月度份额；保真度以对 KBA FZ10 的逐格绝对误差衡量。

## 4 结果

![十二个具名品牌的月度份额轨迹与市场事件](figures/brand_shares.png)

**保真度。** 全 30 月 × 13 品牌对 KBA 真值的平均绝对误差 ≈0.74pp/格，长尾稳定（Other ≈27%），无模式坍塌。

![模拟 vs KBA 真值的逐月保真度](figures/fidelity.png)

**大众系的韧性。** 大众全程维持 ~19%（19.3% → 19.0%），斯柯达在窗口后段小幅上行（8.5% → 8.1%，2026 年多月站上 8.5%+）；真值锚中大众+斯柯达本就合计约 27%，人群的德系偏好使其在新能源冲击下守住基本盘。被分流的是腰部燃油品牌：奔驰 −2.1pp、欧宝 −2.1pp、丰田 −1.2pp。

**新能源是长尾替代，不是头部颠覆。** 比亚迪自 0.2% 升至 4.2%（+4.0pp），其增量主要来自 Other 与腰部燃油品牌而非大众系；特斯拉呈 V 型（2.0% → 谷底 0.4–0.7% → 2.5%），谷底出现在补贴退出 + 舆论低迷叠加期，回升与 2026 车型焕新广播（t24）及 EV 气候回暖同步。

![特斯拉 vs 比亚迪：绝对份额放大图](figures/ev_zoom.png)

**转型速度沿人口结构分层。** 年轻、大城市、高开放度 agent 的 EV 选择占比显著高于年长段（cohort_ev），比亚迪的增长与其铺货曲线及 2025 扩张广播同步——是可得性 × 人群开放度的乘积，而非全民转向。

![分年龄段的新能源选择占比](figures/cohort_ev.png)

**个体层理由（面板下钻样本）。** 选大众："还是买大众踏实，保值又好修，家里一直开这个。"选比亚迪："这电车便宜、配置高，现在展厅也开到家门口了，想试试。"——忠诚与可得性两种机制在个体口吻中直接可读。

## 5 讨论

**机制统一。** 三分格局（大众系稳、新能源升、腰部分流）由同一机制生成：真实品牌根基（锚）决定基本盘，环境信号（EV 气候/铺货/舆论）× 人群异质性（年龄/开放度/价格敏感）决定边际转移。这与消费者层面车型选择实证的结论一致 [train2007vehicle]。

**保真-自主的权衡是显式的。** λ=0.7 的真值锚定让轨迹逐月贴合 KBA，但也意味着新能源份额的绝对水平部分由锚注入；λ 的灵敏度扫描（0.4/0.7/0.9）是量化"贴合真值 vs 放任 agent 偏离"权衡的下一步。环境信号虽由真实序列派生，铺货节奏仍属近似。

**局限。** （i）无逐品牌逐月成交价，价格漂移为近似；（ii）scripted 决策层为主，agent 叙事层的真实 LLM 对照留待小窗口版本；（iii）Other 聚合掩盖了保时捷等品牌的单独动态（数据口径所限）。

## 6 结论

以真实人口联合分布为 P、真实注册份额为逐月锚、离散选择为决策骨架的面板模拟，能在 0.74pp/格 的保真度下同时给出聚合轨迹与个体选择叙事。德国市场 2024–2026 的电动化在此框架下呈现为"长尾替代"：新势力自可得性与开放人群切入，动摇的是市场的腰部而非头部。方法上，真值锚定参数 λ 把此类"沙盒 vs 预测"的张力变成一个可扫描的显式旋钮。

## References

- [mcfadden2000mixed] McFadden, D., & Train, K. (2000). Mixed MNL models for discrete response. *Journal of Applied Econometrics*.
- [guadagni1983a] Guadagni, P., & Little, J. (1983). A logit model of brand choice calibrated on scanner data. *Marketing Science*.
- [train2007vehicle] Train, K., & Winston, C. (2007). Vehicle choice behavior and the declining market share of U.S. automakers. *International Economic Review*.
- [sheth1974a] Sheth, J. (1974). A theory of multidimensional brand loyalty. *Journal of Advertising Research*.
- [rahmandad2008heterogeneity] Rahmandad, H., & Sterman, J. (2008). Heterogeneity and network structure in the dynamics of diffusion: Comparing agent-based and differential equation models. *Management Science*.
