# 沿海堤段数据约定

资料包顶层声明 `common_datum`（统一潮位基准）、`known_at`（分析时点）与可选的
`issued_at`（各期签发时间，与 `known_at` 等长）。所有证据以文档形式入库，
文档含 `source / document_id / revision / received_at / records`，只增不改。

## 记录类型

### observation（站点观测）

旧式记录只含 `metric / region / unit / value`，走同口径直接比较。
潮位记录扩展以下字段：

- `station`、`segment`：站点与所属堤段
- `datum`：该记录使用的潮位基准（如港口自有零点）
- `year`：年度极值年份；缺省取记录 `valid_from` 的年份
- `value`：该基准下的原始读数，换算前始终保留

### conversion（基准换算依据）

- `from_datum` / `to_datum`：有向边，含义 `value(to)=value(from)+offset`
- `offset`、`unit`：偏移量与单位；反向使用同一证据时偏移取负
- `valid_from` / 可选 `valid_to`：有效期窗口，观测时点必须落在窗口内
- 同一换算 id 发布新 revision 即视为依据修订，旧 revision 原样保留

### reference（海平面背景值）

`metric / region / unit / value` 之外必须带 `datum`，且与资料包 `common_datum`
一致才参与比较；可选 `year` 匹配年度极值。

### rule（堤段风险规则）

`metric / region / unit / threshold / direction / action` 之外：

- 带 `segment` 时为堤段专属规则，精确匹配
- 不带 `segment` 时为区域兜底规则，堤段无专属规则时启用
- 可选 `datum` 声明规则适用的统一基准，不符则判“口径不符”

## 分析输出约定

- `ranking`：仅含换算证据充分、完成同口径比较的堤段，按风险指数（越限比例）降序
- `excluded`：证据不足或无参照的记录，保留 `raw_value / raw_datum / reason`，
  不参与排序与巡查派单
- 每条排序结果附完整证据链 SHA（观测、背景值、逐跳换算依据、规则）
- `reason` 取值：`未声明统一基准`、`换算证据不足`（无依据或链路不通）、
  `基准有效期不符`、`无参照`
