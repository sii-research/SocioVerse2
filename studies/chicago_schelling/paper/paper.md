# 可达性不等于融合：一次轨道交通干预在芝加哥隔离动力学中的反向结果

## 摘要

改善低可达性社区的交通条件常被期待带来族群融合。本文用一个建立在 2010 年芝加哥真实人口普查数据上的 Schelling 型居住选择模型检验这一预期：570 个固定家庭按普查区落位，在第 2 步于南城 New City 普查区开通地铁站并配套反迁移保障广播，逐步记录四项隔离指数与迁移行为。结果与预期相反——黑白隔离指数 `D_black_white` 由 0.8160 升至 0.8464（Δ=+0.0304），西语裔-白人隔离由 0.5582 升至 0.6112。机制可以从面板中直接读出：车站吸引的是就近的西语裔流入（目标区西语裔 0→241 人），而非白人回流（白人 13→0 人），干预从两端同时推高了隔离指数。迁移量在干预步达峰 50 户后回落至 31 户，系统在一次重排序后收敛到比基线更隔离的稳态。本文的贡献不是"交通干预有害"这一结论——单一情景、四步、一次运行不足以支撑因果主张——而是展示一种可审计的政策沙盒形态：把宏观隔离指数的每一次变动追溯到具体普查区的具体族群流量。

## 1 引言

Schelling 的经典结论是宏观格局未必反映微观意图：温和的同族偏好足以产生高度隔离。半个世纪后，这一机制被反复重构与扩展，但一个实践问题仍然开放——**外生的可达性改善会把系统推向融合，还是推向新的隔离均衡？**

这个问题很难用观测数据回答：交通项目的选址本身与既有隔离格局相关，且效应要许多年才显现。模拟提供了一条替代路径，但只有当模拟建立在真实地理与真实人口构成之上时，它的答案才值得当作政策讨论的输入 [crooks2010constructing]。本文报告这样一次实验。

## 2 相关工作

**Schelling 机制与临界点。** 把 Schelling 形式化为空间博弈可以给出 tipping 的解析条件 [zhang2010tipping]，这为判断一次干预是否把系统推过临界点提供了标尺。同样重要的是不要落入"融合/隔离"二分：中间态与斑块结构同样稳定 [hatna2012the]，因此读取轨迹时不能只看终值高低。容忍度参数的心理学解释也被重新审视过——共同经验会改变接纳门槛 [berg2010fast]，这直接关系到本文 archetype 容忍度参数的可解释性。

**真实地理驱动的隔离 ABM。** 把 Schelling 从棋盘格搬到真实地块几何上会改变其动力学 [crooks2010constructing]；用真实迁居微观数据校准邻里族裔隔离模型则暴露出"个体偏好与宏观格局对不上"的经验难题 [zuccotti2022exploring]。地理显式的移民人口城市动态模型进一步给出了外生人口冲击的建模范式 [prez2019a]，与本文的干预情景同属一类。

**隔离的外溢。** 隔离并不止于居住地。把视角扩展到一天中的时空轨迹会显著改变对隔离程度的判断 [cottineau2025an]——本文的交通干预恰恰改变的是日间可达性，这提示只看居住地隔离指数可能低估或高估效果。学校隔离相对居住隔离的超额部分也有其独立机制 [dignum2022mechanisms]，界定了本文结论不可直接外推到教育后果的原因。

## 3 方法

**人群 P。** 570 个固定家庭，由 2010 年芝加哥人口普查抽样生成并按普查区落位，携带族群、收入与容忍度等 archetype 参数；家庭身份跨步持久，因而可逐户追踪。

**环境 E。** 物理层为真实普查区几何与其人口构成；信息层承载干预广播。第 2 步在南城 New City 普查区开通 CTA 地铁站，并同步发布反迁移保障广播。

**行为函数 f。** 每步每户依据其所在普查区的邻里构成与自身容忍度决定是否迁出、迁往何处，即 Schelling 型离散选择；聚合后由收集器计算隔离指数。

**指标。** `D_black_white`、`D_hispanic_white`、`D_asian_white`（相异指数）与 `Isolation_black`（隔离指数），另记每步迁移户数。共 4 个时间步、2280 行面板数据。

## 4 结果

**假设被证伪。** 图 1 给出四项指数的逐步轨迹，第 2 步为干预步。

![四项隔离指数的逐步轨迹，第 2 步为干预步](figures/metric_timeline.png)

| step | D_black_white | D_hispanic_white | D_asian_white | Isolation_black | 迁移户数 |
|---|---|---|---|---|---|
| 0 | 0.8160 | 0.5582 | 0.3282 | 0.6137 | — |
| 1 | 0.8068 | 0.5730 | 0.3364 | 0.6240 | 41 |
| 2（干预） | 0.8447 | 0.5891 | 0.3085 | 0.6083 | 50 |
| 3 | 0.8464 | 0.6112 | 0.3237 | 0.6162 | 31 |

黑白隔离在干预步跳升 0.0379，并在第 3 步继续微升，全程净变化 +0.0304；西语裔-白人隔离单调上升 +0.0530。唯一下降的是亚裔-白人隔离（−0.0045），幅度在噪声量级。

**机制：流入的是西语裔，不是白人。** 空间分布图给出了直接证据。

![干预前（step 0）各普查区主导族群分布](figures/step_000.png)

![期末（step 3）各普查区主导族群分布：目标区由混居转为西语裔主导](figures/step_003.png)

目标普查区的西语裔人口由 0 增至 241 人，白人由 13 减至 0。也就是说，可达性改善确实产生了迁入，但迁入者来自邻近的同族聚居区而非跨族回流；目标区因此由混居转为西语裔主导。两端同时移动——目标区更均质、原白人区更均质——使总体相异指数上升。这与"个体迁居选择如何聚合成宏观格局"这一经典难题的经验发现一致 [zuccotti2022exploring]。

**系统收敛到更隔离的稳态。** 迁移户数 41 → 50（干预步）→ 31：冲击引发一轮重排序后迁移意愿回落。按 tipping 的判据 [zhang2010tipping]，这次干预并未把系统推过临界点使其翻转，而是在原有吸引域内制造了一次位移，最终稳定在比基线更隔离的位置。终态并非全隔离，而是稳定的斑块格局，符合 Schelling 结局的中间态刻画 [hatna2012the]。

## 5 讨论

结果的政策含义是有限而具体的：**一次性的可达性冲击不必然带来融合，其方向取决于谁在地理上更接近这次改善**。当目标区周边是同族聚居区时，可达性改善优先降低的是同族迁入成本，从而强化而非削弱空间分选。反迁移保障广播在本情景中不足以抵消这一效应。

**边界必须说清。** 其一，这是**单一情景、4 步、一次运行**，没有反事实基线（无干预的平行版本），因此不能作因果强度的主张；本文能主张的是"在该模型设定下，干预未产生预期方向的效应，且机制可追溯"。其二，容忍度等 archetype 参数是载荷参数，其心理学解释并非唯一 [berg2010fast]，参数敏感性未在此报告。其三，本文只测量**居住地**隔离；干预改变的恰是日间可达性，而把时空轨迹纳入后隔离度量会显著变化 [cottineau2025an]，因此这里的指数可能低估了干预的真实社会效果。其四，结论不可外推到教育后果——学校隔离有其相对居住隔离的独立超额机制 [dignum2022mechanisms]。

**真正的贡献在形态而非结论。** 每一次宏观指数变动都能被追溯到具体普查区的具体族群流量，是因为人群是固定的、有身份的，且每步状态都被记录。这使"假设被证伪"成为一个可以继续追问的结果，而不是一次失败的运行。**下一步**应当是：跑一版无干预基线做差分；把干预点换到周边族群构成不同的普查区，检验"谁更近"这一机制解释；以及延长时间跨度，看新稳态是否在更长的窗口上仍然稳定。

## 参考文献

- [zhang2010tipping] Zhang. *Tipping and Residential Segregation: A Unified Schelling Model.* Journal of Regional Science, 2010.
- [crooks2010constructing] Crooks. *Constructing and implementing an agent-based model of residential segregation through vector GIS.* International Journal of Geographical Information Science, 2010.
- [hatna2012the] Hatna & Benenson. *The Schelling Model of Ethnic Residential Dynamics: Beyond the Integrated–Segregated Dichotomy.* JASSS, 2012.
- [zuccotti2022exploring] Zuccotti et al. *Exploring the dynamics of neighbourhood ethnic segregation with agent-based modelling: an empirical application.* Journal of Ethnic and Migration Studies, 2022.
- [prez2019a] Pérez et al. *A geospatial agent-based model of the spatial urban dynamics of immigrant population.* PLoS ONE, 2019.
- [cottineau2025an] Cottineau et al. *An agent-based model to investigate the effects of urban segregation around the clock on inequality.* EPJ Data Science, 2025.
- [dignum2022mechanisms] Dignum et al. *Mechanisms for increased school segregation relative to residential segregation: a model-based analysis.* Computers, Environment and Urban Systems, 2022.
- [berg2010fast] Berg et al. *Fast Acceptance by Common Experience: FACE-recognition in Schelling's model of neighborhood segregation.* Judgment and Decision Making, 2010.
