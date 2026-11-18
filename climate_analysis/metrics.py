"""对同口径观测和参照形成单期偏离。

带 datum 的潮位观测必须先凭换算证据链转到统一基准（common_datum），
证据不足时保留原始记录并排除在可比风险名单之外；
无 datum 的旧式记录继续走基线的同口径直接比较路径。
"""
from .datum import conversion_path
from .evidence import records


def effective_year(record):
    payload = record['payload']
    if payload.get('year') is not None:
        return payload['year']
    return int(record['valid_from'][:4])


def compare(db, known_at, common_datum=None):
    observations = records(db, 'observation', known_at)
    references = records(db, 'reference', known_at)
    conversions = records(db, 'conversion', known_at)
    result = []
    for obs in observations:
        payload = obs['payload']
        if not payload.get('datum'):
            result.append(_legacy_compare(obs, references))
            continue
        year = effective_year(obs)
        if not common_datum:
            path, reason = None, '未声明统一基准'
        else:
            path, reason = conversion_path(
                conversions, payload['datum'], common_datum,
                obs['valid_from'], payload.get('unit'))
        if path is None:
            result.append({'id': obs['id'], 'status': '换算证据不足',
                           'reason': reason,
                           'region': payload.get('region'),
                           'segment': payload.get('segment'),
                           'station': payload.get('station'),
                           'metric': payload['metric'],
                           'unit': payload['unit'],
                           'year': year,
                           'raw_value': payload['value'],
                           'raw_datum': payload['datum'],
                           'sources': [obs['source']['sha256']]})
            continue
        matches = [r for r in references
                   if r['payload'].get('metric') == payload['metric']
                   and r['payload'].get('region') == payload.get('region')
                   and r['payload'].get('unit') == payload.get('unit')
                   and r['payload'].get('datum') == common_datum
                   and (r['payload'].get('year') in (None, year))]
        if not matches:
            result.append({'id': obs['id'], 'status': '无参照',
                           'segment': payload.get('segment'),
                           'sources': [obs['source']['sha256']]
                           + [h['source'] for h in path['hops']]})
            continue
        ref = matches[-1]
        common_value = payload['value'] + path['offset']
        sources = [obs['source']['sha256'], ref['source']['sha256']]
        for hop in path['hops']:
            if hop['source'] not in sources:
                sources.append(hop['source'])
        result.append({
            'id': obs['id'], 'status': '可比',
            'region': payload.get('region'),
            'segment': payload.get('segment'),
            'station': payload.get('station'),
            'metric': payload['metric'], 'unit': payload['unit'],
            'year': year,
            'raw_value': payload['value'],
            'raw_datum': payload['datum'],
            'common_datum': common_datum,
            'common_value': common_value,
            'conversion_offset': path['offset'],
            'conversion_hops': path['hops'],
            'reference_value': ref['payload']['value'],
            'delta': common_value - ref['payload']['value'],
            'sources': sources})
    return result


def _legacy_compare(obs, references):
    p = obs['payload']
    matches = [r for r in references
               if all(r['payload'][k] == p[k] for k in ('metric', 'region', 'unit'))]
    if not matches:
        return {'id': obs['id'], 'status': '无参照'}
    ref = matches[-1]
    return {'id': obs['id'], 'region': p['region'], 'metric': p['metric'],
            'unit': p['unit'], 'delta': p['value'] - ref['payload']['value'],
            'sources': [obs['source']['sha256'], ref['source']['sha256']],
            'status': '可比'}
