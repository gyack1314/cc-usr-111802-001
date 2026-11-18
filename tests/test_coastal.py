"""验证基准换算、证据不足排除、风险排序、签发判断链与变化归因。"""
import json
import tempfile
import unittest
from pathlib import Path

from climate_analysis.context import decide
from climate_analysis.datum import conversion_path
from climate_analysis.evidence import connect, receive, records
from climate_analysis.issuance import issue, load_issued, latest_issued
from climate_analysis.metrics import compare
from climate_analysis.report import generate, difference

DATA = json.loads((Path(__file__).resolve().parents[1]
                   / 'data/coastal.json').read_text(encoding='utf8'))
T1, T2 = DATA['known_at']
COMMON = DATA['common_datum']


class CoastalBase(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')
        for doc in DATA['documents']:
            receive(self.db, doc)

    def tearDown(self):
        self.db.close()

    def _ranking(self, report):
        return {row['id']: row for row in report['ranking']}


class ConversionGraph(CoastalBase):
    def test_multi_hop_chain_offsets_signs(self):
        conversions = records(self.db, 'conversion', T1)
        path, reason = conversion_path(conversions, '港口B旧零点', COMMON,
                                       '2025-11-20', 'cm')
        self.assertIsNone(reason)
        self.assertEqual(path['offset'], 5)
        self.assertEqual([h['conversion_id'] for h in path['hops']],
                         ['conv-b-old', 'conv-yellow-r1'])

    def test_reverse_edge_uses_negative_offset(self):
        conversions = records(self.db, 'conversion', T1)
        path, reason = conversion_path(conversions, COMMON, '港口A潮位零点',
                                       '2025-11-20', 'cm')
        self.assertIsNone(reason)
        self.assertEqual(path['offset'], -15)
        self.assertTrue(path['hops'][0]['reversed'])

    def test_validity_window_rejects_stale_observation(self):
        # T2 时 conv-c 已发布，但有效期自 2015 年起，2008 年观测不能套用
        conversions = records(self.db, 'conversion', T2)
        path, reason = conversion_path(conversions, '港口C历史零点', COMMON,
                                       '2008-11-20', 'cm')
        self.assertIsNone(path)
        self.assertEqual(reason, '基准有效期不符')

    def test_unpublished_conversion_is_insufficient_evidence(self):
        # T1 时 conv-c 尚未收到，任何时点都无证据可用
        conversions = records(self.db, 'conversion', T1)
        path, reason = conversion_path(conversions, '港口C历史零点', COMMON,
                                       '2025-11-20', 'cm')
        self.assertIsNone(path)
        self.assertEqual(reason, '换算证据不足')

    def test_no_related_edge_gives_insufficient_evidence(self):
        conversions = records(self.db, 'conversion', T1)
        path, reason = conversion_path(conversions, '未知零点', COMMON,
                                       '2025-11-20', 'cm')
        self.assertIsNone(path)
        self.assertEqual(reason, '换算证据不足')


class ComparisonAndRanking(CoastalBase):
    def test_insufficient_evidence_keeps_raw_record(self):
        measurements = compare(self.db, T1, COMMON)
        port_c = next(m for m in measurements if m['id'] == 'obs-port-c')
        self.assertEqual(port_c['status'], '换算证据不足')
        self.assertEqual(port_c['raw_value'], 300)
        self.assertEqual(port_c['raw_datum'], '港口C历史零点')
        history = next(m for m in measurements if m['id'] == 'obs-port-c-history')
        self.assertEqual(history['status'], '换算证据不足')
        self.assertEqual(history['reason'], '换算证据不足')

    def test_excluded_never_enters_ranking(self):
        report = generate(self.db, T1, COMMON)
        ranked_ids = {row['id'] for row in report['ranking']}
        self.assertNotIn('obs-port-c', ranked_ids)
        excluded = {row['id']: row for row in report['excluded']}
        self.assertIn('obs-port-c', excluded)
        self.assertEqual(excluded['obs-port-c']['raw_value'], 300)

    def test_common_datum_values_and_risk_order(self):
        report = generate(self.db, T1, COMMON)
        ranking = report['ranking']
        self.assertEqual([row['id'] for row in ranking],
                         ['obs-port-b', 'obs-port-a'])
        a = self._ranking(report)['obs-port-a']
        self.assertEqual(a['common_value'], 335)
        self.assertEqual(a['conversion_offset'], 15)
        self.assertEqual(a['status'], '关注')
        self.assertEqual(a['action'], '每周巡查')
        b = self._ranking(report)['obs-port-b']
        self.assertEqual(b['common_value'], 475)
        self.assertEqual(b['delta'], 170)
        self.assertEqual(b['status'], '关注')
        self.assertEqual(b['action'], '驻点值守')
        # 风险指数统一为相对堤段阈值的越限比例
        self.assertAlmostEqual(a['risk_index'], 0.5)
        self.assertAlmostEqual(b['risk_index'], 0.7)

    def test_region_rule_fallback_for_segment_without_rule(self):
        report = generate(self.db, T2, COMMON)
        c = self._ranking(report)['obs-port-c']
        # levee-c 无专属规则，回退区域兜底规则；delta=20 未越阈值 30
        self.assertIsNone(c['action'])
        self.assertEqual(c['status'], '常态')
        decision = next(d for d in report['decisions'] if d['id'] == 'obs-port-c')
        self.assertEqual(decision['rule_id'], 'rule-north-default')

    def test_every_ranked_entry_carries_full_evidence_chain(self):
        report = generate(self.db, T1, COMMON)
        for row in report['ranking']:
            # 观测 + 背景 + 至少一条换算证据 + 规则
            self.assertGreaterEqual(len(row['sources']), 4)


class ChangeAttribution(CoastalBase):
    def test_caliber_revision_is_separate_from_real_risk_change(self):
        before = generate(self.db, T1, COMMON)
        after = generate(self.db, T2, COMMON)
        change = difference(before, after)
        details = {d['id']: d for d in change['details']}
        # 港口B：只有换算口径修订，风险值变化但名次不变
        b = details['obs-port-b']
        self.assertEqual(b['reasons'], ['换算口径变化'])
        self.assertFalse(b['rank_moved'])
        after_b = self._ranking(after)['obs-port-b']
        self.assertEqual(after_b['conversion_offset'], -4)
        self.assertEqual(after_b['common_value'], 466)
        # 港口A：观测修订导致风险指数升高，但仍未超过 B，名次不变
        a = details['obs-port-a']
        self.assertEqual(a['reasons'], ['观测更新'])
        self.assertFalse(a['rank_moved'])
        self.assertEqual(a['rank_before'], 2)
        self.assertEqual(a['rank_after'], 2)
        # 名次实际发生改变的只有新进入名单的港口C
        self.assertEqual(change['ranking_changed'], ['obs-port-c'])
        self.assertEqual(change['caliber_only_changes'], [])

    def test_observation_surge_can_overturn_ranking(self):
        # 专项场景：观测本身的大幅修订真实反超，区别于口径变化
        db = connect(':memory:')
        for doc in DATA['documents']:
            receive(db, doc)
        receive(db, {
            'source': '沿海潮位中心', 'document_id': 'tide-observations-2025',
            'revision': 'r3', 'received_at': '2026-08-26T00:00:00+00:00',
            'records': [{
                'kind': 'observation', 'id': 'obs-port-a', 'revision': 'r3',
                'valid_from': '2025-11-20',
                'payload': {'metric': 'annual_max_level', 'region': 'north-coast',
                            'segment': 'levee-a', 'station': 'port-a',
                            'unit': 'cm', 'year': 2025, 'value': 420,
                            'datum': '港口A潮位零点'}}]})
        before = generate(db, T1, COMMON)
        after = generate(db, T2, COMMON)
        details = {d['id']: d for d in difference(before, after)['details']}
        a = details['obs-port-a']
        self.assertEqual(a['reasons'], ['观测更新'])
        self.assertEqual((a['rank_before'], a['rank_after']), (2, 1))
        self.assertFalse(a['caliber_only'])
        db.close()

    def test_evidence_gained_moves_station_into_ranking(self):
        before = generate(self.db, T1, COMMON)
        after = generate(self.db, T2, COMMON)
        details = {d['id']: d for d in difference(before, after)['details']}
        c = details['obs-port-c']
        self.assertEqual(c['status_before'], '换算证据不足')
        self.assertEqual(c['status_after'], '常态')
        self.assertEqual(c['reasons'], ['换算证据补齐'])
        self.assertEqual(c['rank_before'], None)
        self.assertEqual(c['rank_after'], 3)

    def test_caliber_only_label_when_ranking_moves_by_datum_alone(self):
        # 独立库：只载入 T1 时点已发布的证据，再追加一条换算修订，
        # 隔离出“仅基准口径变化导致名次移动”的情形
        db = connect(':memory:')
        cutoff = T1
        for doc in DATA['documents']:
            if doc['received_at'] <= cutoff:
                receive(db, doc)
        receive(db, {
            'source': '测绘基准院', 'document_id': 'datum-conversions',
            'revision': 'r3', 'received_at': '2026-08-25T00:00:00+00:00',
            'records': [{
                'kind': 'conversion', 'id': 'conv-b-old', 'revision': 'r3',
                'valid_from': '2010-01-01',
                'payload': {'from_datum': '港口B旧零点', 'to_datum': '黄海基面',
                            'offset': -80, 'unit': 'cm',
                            'valid_from': '2010-01-01'}}]})
        before = generate(db, T1, COMMON)
        after = generate(db, T2, COMMON)
        change = difference(before, after)
        details = {d['id']: d for d in change['details']}
        self.assertTrue(details['obs-port-b']['caliber_only'])
        self.assertEqual(details['obs-port-b']['reasons'], ['换算口径变化'])
        self.assertIn('obs-port-b', change['caliber_only_changes'])
        db.close()


class Issuance(unittest.TestCase):
    def test_issued_judgments_are_immutable_and_chained(self):
        db = connect(':memory:')
        for doc in DATA['documents']:
            receive(db, doc)
        first = generate(db, T1, COMMON)
        second = generate(db, T2, COMMON)
        receipt1 = issue(db, first, DATA['issued_at'][0])
        receipt2 = issue(db, second, DATA['issued_at'][1], receipt1['fingerprint'])
        self.assertEqual(receipt2['predecessor'], receipt1['fingerprint'])
        # 重复签发幂等，不新增判断
        again = issue(db, first, DATA['issued_at'][0])
        self.assertTrue(again['duplicate'])
        # 新基准发布后，旧判断原样可取回，指纹不变
        restored = load_issued(db, receipt1['fingerprint'])
        self.assertEqual(restored['fingerprint'], first['fingerprint'])
        self.assertEqual(latest_issued(db)['fingerprint'], receipt2['fingerprint'])
        db.close()

    def test_chain_cannot_skip_to_unknown_predecessor(self):
        db = connect(':memory:')
        for doc in DATA['documents']:
            receive(db, doc)
        report = generate(db, T1, COMMON)
        with self.assertRaises(ValueError):
            issue(db, report, DATA['issued_at'][0], predecessor='not-a-fingerprint')
        db.close()

    def test_persistent_db_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'evidence.db')
            db = connect(path)
            for doc in DATA['documents']:
                receive(db, doc)
            report = generate(db, T1, COMMON)
            issue(db, report, DATA['issued_at'][0])
            db.close()
            db2 = connect(path)
            self.assertEqual(load_issued(db2, report['fingerprint'])['fingerprint'],
                             report['fingerprint'])
            db2.close()


class Determinism(CoastalBase):
    def test_same_inputs_same_fingerprint_and_ranking(self):
        r1 = generate(self.db, T1, COMMON)
        r2 = generate(self.db, T1, COMMON)
        self.assertEqual(r1['fingerprint'], r2['fingerprint'])
        self.assertEqual([row['id'] for row in r1['ranking']],
                         [row['id'] for row in r2['ranking']])

    def test_decide_passes_through_excluded(self):
        measurements = compare(self.db, T1, COMMON)
        excluded = next(m for m in measurements if m['status'] == '换算证据不足')
        decision = decide(self.db, T1, excluded)
        self.assertEqual(decision['status'], '换算证据不足')
        self.assertNotIn('action', decision)


if __name__ == '__main__':
    unittest.main()
