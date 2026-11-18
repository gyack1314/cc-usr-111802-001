"""按当前区域或堤段规则解释已比较的指标。

规则按 segment 精确匹配，缺省时回退到 region 级规则；
证据不足的比较结果原样保留，不进入风险判断。
"""
from .evidence import records


def decide(db, known_at, comparison):
    if comparison['status'] == '换算证据不足':
        return {'id': comparison['id'], 'status': '换算证据不足',
                'reason': comparison['reason'],
                'segment': comparison.get('segment')}
    if comparison['status'] != '可比':
        return {'id': comparison['id'], 'status': '待核实'}
    rules = records(db, 'rule', known_at)
    segment = comparison.get('segment')
    region_rules = [r for r in rules
                    if 'segment' not in r['payload']
                    and r['payload']['region'] == comparison['region']]
    if segment:
        scoped = [r for r in rules
                  if r['payload'].get('segment') == segment]
        if not scoped:
            scoped = region_rules
    else:
        scoped = region_rules
    if not scoped:
        return {'id': comparison['id'], 'status': '无规则'}
    rule = scoped[-1]
    payload = rule['payload']
    if payload['metric'] != comparison['metric'] or payload['unit'] != comparison['unit']:
        return {'id': comparison['id'], 'status': '口径不符'}
    if payload.get('datum') and payload['datum'] != comparison.get('common_datum'):
        return {'id': comparison['id'], 'status': '口径不符'}
    hit = (comparison['delta'] >= payload['threshold']
           if payload['direction'] == 'above'
           else comparison['delta'] <= payload['threshold'])
    return {'id': comparison['id'], 'status': '关注' if hit else '常态',
            'action': payload['action'] if hit else None,
            'segment': segment, 'threshold': payload['threshold'],
            'direction': payload['direction'],
            'rule_id': rule['id'], 'rule_revision': rule['revision'],
            'rule_sha': rule['source']['sha256'],
            'sources': comparison['sources'] + [rule['source']['sha256']]}
