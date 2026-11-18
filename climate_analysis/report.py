"""形成带统一分析版本指纹的堤段风险报告，并解释两期变化。

报告指纹覆盖统一基准、全部观测/换算/背景/规则证据 SHA 及计算结果，
同一 known_at 复算必然得到同一指纹。
difference 按证据 SHA 归因，区分真实排序改变与仅换算口径变化。
"""
import hashlib
import json

from .context import decide
from .metrics import compare


def _risk_index(decision, measurement):
    if decision['direction'] == 'above':
        return (measurement['delta'] - decision['threshold']) / decision['threshold']
    return (decision['threshold'] - measurement['delta']) / decision['threshold']


def generate(db, known_at, common_datum=None):
    measurements = compare(db, known_at, common_datum)
    decisions = [decide(db, known_at, row) for row in measurements]
    by_id = {m['id']: m for m in measurements}
    ranking = []
    for decision in decisions:
        if decision['status'] not in ('关注', '常态'):
            continue
        measurement = by_id[decision['id']]
        ranking.append({
            'id': decision['id'],
            'segment': decision.get('segment'),
            'station': measurement.get('station'),
            'risk_index': _risk_index(decision, measurement),
            'status': decision['status'],
            'action': decision['action'],
            'common_value': measurement.get('common_value'),
            'reference_value': measurement.get('reference_value'),
            'delta': measurement['delta'],
            'common_datum': measurement.get('common_datum'),
            'conversion_offset': measurement.get('conversion_offset'),
            'sources': decision['sources']})
    ranking.sort(key=lambda row: (-row['risk_index'], row['id'] or ''))
    for position, row in enumerate(ranking, start=1):
        row['rank'] = position
    excluded = [{'id': m['id'], 'segment': m.get('segment'),
                 'station': m.get('station'), 'status': m['status'],
                 'reason': m.get('reason'),
                 'raw_value': m.get('raw_value'),
                 'raw_datum': m.get('raw_datum'),
                 'sources': m['sources']}
                for m in measurements if m['status'] not in ('可比',)]
    out = {'known_at': known_at, 'common_datum': common_datum,
           'measurements': measurements, 'decisions': decisions,
           'ranking': ranking, 'excluded': excluded}
    out['fingerprint'] = hashlib.sha256(
        json.dumps(out, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return out


# 差异原因标签
OBSERVATION_UPDATED = '观测更新'
DATUM_CALIBER = '换算口径变化'
EVIDENCE_GAINED = '换算证据补齐'
EVIDENCE_LOST = '换算证据撤回'
BACKGROUND_UPDATED = '背景值更新'
RULE_UPDATED = '规则更新'
RANK_CHANGED = '排序改变'
CALIBER_ONLY = '仅口径变化'
# 仅口径变化：记录始终在可比名单内，变化只来自换算依据本身的修订；
# 证据补齐/撤回改变的是参与资格，不在此列
CALIBER_REASONS = {DATUM_CALIBER}


def _evidence_map(report):
    out = {}
    for measurement in report.get('measurements', []):
        out[measurement['id']] = {
            'observation': measurement['sources'][0]
            if measurement.get('sources') else None,
            'reference': measurement.get('reference_value'),
            'conversions': tuple(h['source'] for h in measurement.get('conversion_hops', [])),
            'offset': measurement.get('conversion_offset'),
            'exclusion_reason': measurement.get('reason'),
            'raw': (measurement.get('raw_value'), measurement.get('raw_datum'))}
    return out


def difference(before, after):
    old_ev = _evidence_map(before)
    new_ev = _evidence_map(after)
    old_rank = {row['id']: row for row in before.get('ranking', [])}
    new_rank = {row['id']: row for row in after.get('ranking', [])}
    old_dec = {r['id']: r for r in before['decisions']}
    new_dec = {r['id']: r for r in after['decisions']}
    details = []
    for record_id in sorted(set(old_dec) | set(new_dec)):
        old_d, new_d = old_dec.get(record_id), new_dec.get(record_id)
        if old_d == new_d and old_rank.get(record_id) == new_rank.get(record_id) \
                and old_ev.get(record_id) == new_ev.get(record_id):
            continue
        reasons = []
        old_e, new_e = old_ev.get(record_id), new_ev.get(record_id)
        if old_e and new_e:
            if old_e['observation'] != new_e['observation']:
                reasons.append(OBSERVATION_UPDATED)
            old_conv, new_conv = old_e['conversions'], new_e['conversions']
            if old_conv != new_conv or old_e['offset'] != new_e['offset']:
                if old_conv and new_conv:
                    reasons.append(DATUM_CALIBER)
                elif new_conv:
                    reasons.append(EVIDENCE_GAINED)
                elif old_conv:
                    reasons.append(EVIDENCE_LOST)
                else:
                    # 两侧都未进入可比名单，但适用性结论变化（如有效期不符）
                    reasons.append(DATUM_CALIBER)
            elif old_e.get('exclusion_reason') != new_e.get('exclusion_reason'):
                # 始终被排除的记录：排除原因变化来自换算证据的发布或失效
                reasons.append(DATUM_CALIBER)
            # 参照/规则只在该记录真正进入过可比名单后才比较，
            # 避免把"此前无资格、证据补齐后首次取得参照"误记为背景更新
            if (old_conv or new_conv) and old_e['reference'] != new_e['reference'] \
                    and old_e['reference'] is not None and new_e['reference'] is not None:
                reasons.append(BACKGROUND_UPDATED)
        if old_d and new_d and old_d.get('rule_sha') and new_d.get('rule_sha') \
                and old_d.get('rule_sha') != new_d.get('rule_sha'):
            reasons.append(RULE_UPDATED)
        if not reasons:
            reasons.append(OBSERVATION_UPDATED)
        rank_before = old_rank.get(record_id, {}).get('rank')
        rank_after = new_rank.get(record_id, {}).get('rank')
        rank_moved = rank_before != rank_after
        # 仅当两侧都在可比名单内、且变化全部来自基准证据时，才算纯口径变化；
        # 从排除名单新进入的资格变化另由“换算证据补齐/撤回”表达
        comparable_both = record_id in old_rank and record_id in new_rank
        caliber_only = (rank_moved and comparable_both
                        and all(r in CALIBER_REASONS for r in reasons))
        details.append({
            'id': record_id,
            'segment': (new_d or old_d).get('segment'),
            'status_before': old_d.get('status') if old_d else None,
            'status_after': new_d.get('status') if new_d else None,
            'rank_before': rank_before, 'rank_after': rank_after,
            'reasons': reasons,
            'rank_moved': rank_moved,
            'caliber_only': rank_moved and all(r in CALIBER_REASONS for r in reasons)})
    moved = [d['id'] for d in details if d['rank_moved']]
    caliber_only = [d['id'] for d in details if d['caliber_only']]
    return {'before': before['fingerprint'], 'after': after['fingerprint'],
            'changed': sorted(d['id'] for d in details),
            'ranking_changed': moved,
            'caliber_only_changes': caliber_only,
            'details': details}
