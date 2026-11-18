# 沿海堤段指标分析

项目保存沿海堤段的来源版次，把站点观测、基准换算依据、海平面背景值和堤段风险规则
放在同一分析版本下，形成可复核的堤段风险排序。样本是合成数据。

## 分析链路

1. **证据入库（evidence）**：来源、文档版次、取得时间、SHA256 全部只增保存；
   同一来源同版次内容冲突会报错。按 `known_at` 取数时只看到该时点之前已收到的证据，
   支持时间旅行复核。
2. **基准换算（datum）**：`conversion` 记录构成有向换算图，
   `value(目标基准) = value(来源基准) + offset`，支持多跳链路与反向使用（偏移取负）。
   每条换算依据都带有效期 `[valid_from, valid_to)`，观测时点不在窗口内则不得套用。
3. **同口径比较（metrics）**：带 `datum` 的观测必须先凭完整换算链转到资料包声明的
   统一基准 `common_datum`，才能与同基准的海平面背景值比较。
   换算证据不足（无相关依据、链路不通或有效期不符）的站点保留原始记录，
   列入 `excluded` 但**不进入可比较的风险名单**。
4. **规则判断（context）**：堤段级规则精确匹配，缺省时回退区域兜底规则；
   风险指数统一为相对本堤段阈值的越限比例，跨堤段可排序。
5. **报告与签发（report / issuance）**：报告指纹覆盖统一基准、全部证据 SHA 与计算结果，
   同输入复算指纹不变。`issue` 只追加、不覆盖，重复签发幂等；
   新报告记录前任指纹形成判断链，新基准发布后旧判断仍可按指纹原样取回。
6. **两期归因（report.difference）**：按证据 SHA 区分
   `观测更新 / 换算口径变化 / 换算证据补齐 / 换算证据撤回 / 背景值更新 / 规则更新`；
   `ranking_changed` 给出真实名次移动，`caliber_only_changes` 只列
   “记录始终在名单内、且移动纯粹由换算口径修订造成”的堤段；
   从排除名单新进入的资格变化不算纯口径变化。

无 `datum` 字段的旧式记录继续走基线的同口径直接比较路径，旧资料包不受影响。

## 运行

Python 3.11 以上，在项目根目录执行：

    python -m unittest discover -s tests -v
    python -m compileall -q climate_analysis tests

    # 基线单期示例（旧式无基准记录）
    python -m climate_analysis.cli inspect data/example.json

    # 潮位基准换算、风险排序、两期归因，并把两期判断签发到持久库
    python -m climate_analysis.cli run data/coastal.json --db coastal.db --issue

    # 按指纹取回历史签发判断（不给指纹则取最新一期）
    python -m climate_analysis.cli verify coastal.db <fingerprint>

Dockerfile 可在 Linux 容器运行：`docker build -t climate-analysis-001 .`；
`docker run --rm climate-analysis-001`。
