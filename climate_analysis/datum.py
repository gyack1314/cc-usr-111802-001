"""潮位基准换算图：按有效期寻找可复核的换算证据链。

换算记录表示有向边 from_datum -> to_datum，含义为
value(to_datum) = value(from_datum) + offset。
反向走过同一证据时 offset 取负，不产生新证据。
每条边都必须在观测时点处于有效期 [valid_from, valid_to) 内。
"""
from collections import deque
from datetime import date


def _within_window(record, as_of):
    payload = record['payload']
    day = date.fromisoformat(as_of[:10])
    if day < date.fromisoformat(payload['valid_from']):
        return False
    valid_to = payload.get('valid_to')
    if valid_to and day >= date.fromisoformat(valid_to):
        return False
    return True


def _live_edges(conversions, as_of, unit):
    edges = []
    for record in conversions:
        payload = record['payload']
        if unit and payload.get('unit') not in (None, unit):
            continue
        if not _within_window(record, as_of):
            continue
        edges.append((payload['from_datum'], payload['to_datum'],
                      payload['offset'], record))
    return edges


def conversion_path(conversions, from_datum, to_datum, as_of, unit=None):
    """返回 (路径, None)；找不到时返回 (None, 原因)。

    路径含总偏移与逐跳证据（换算记录 id、版次、SHA256、是否反向使用）。
    """
    if from_datum == to_datum:
        return {'offset': 0, 'hops': []}, None
    edges = _live_edges(conversions, as_of, unit)
    queue = deque([(from_datum, [])])
    seen = {from_datum}
    while queue:
        node, hops = queue.popleft()
        for source_datum, target_datum, offset, record in edges:
            if source_datum == node:
                nxt, applied, reversed_edge = target_datum, offset, False
            elif target_datum == node:
                nxt, applied, reversed_edge = source_datum, -offset, True
            else:
                continue
            if nxt in seen:
                continue
            hop = {'from': node, 'to': nxt, 'offset': applied,
                   'reversed': reversed_edge,
                   'conversion_id': record['id'],
                   'revision': record['revision'],
                   'source': record['source']['sha256']}
            new_hops = hops + [hop]
            if nxt == to_datum:
                total = sum(hop['offset'] for hop in new_hops)
                return {'offset': total, 'hops': new_hops}, None
            seen.add(nxt)
            queue.append((nxt, new_hops))
    related = [r for r in conversions
               if from_datum in (r['payload'].get('from_datum'),
                                 r['payload'].get('to_datum'))]
    if related:
        expired = [r for r in related if not _within_window(r, as_of)]
        if expired:
            return None, '基准有效期不符'
    return None, '换算证据不足'
