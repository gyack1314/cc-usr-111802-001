"""命令行：单期检查、潮位堤段风险排序与签发复核。"""
import argparse
import json
from pathlib import Path

from .evidence import connect, receive
from .issuance import issue, latest_issued, load_issued
from .report import generate, difference


def _load_bundle(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def _ingest(db, data):
    for doc in data['documents']:
        receive(db, doc)


def _inspect(db, data):
    common_datum = data.get('common_datum')
    reports = [generate(db, point, common_datum) for point in data['known_at']]
    before, after = reports[0], reports[-1]
    return {'before': before, 'after': after, 'change': difference(before, after)}


def _run(db, data, do_issue):
    common_datum = data.get('common_datum')
    reports = [generate(db, point, common_datum) for point in data['known_at']]
    output = {'common_datum': common_datum, 'reports': reports,
              'changes': [difference(reports[i - 1], reports[i])
                          for i in range(1, len(reports))]}
    if do_issue:
        receipts = []
        predecessor = (latest_issued(db) or {}).get('fingerprint')
        for report, point in zip(reports, data['issued_at']):
            receipt = issue(db, report, point, predecessor)
            receipts.append(receipt)
            predecessor = receipt['fingerprint']
        output['issuance'] = receipts
    return output


def main():
    parser = argparse.ArgumentParser(description='沿海堤段指标分析')
    sub = parser.add_subparsers(dest='command', required=True)

    inspect_p = sub.add_parser('inspect', help='形成两个已知时点的报告与差异')
    inspect_p.add_argument('input')
    inspect_p.add_argument('--db', default=':memory:', help='证据库存放路径，默认内存库')

    run_p = sub.add_parser('run', help='潮位基准换算、堤段风险排序与两期归因')
    run_p.add_argument('input')
    run_p.add_argument('--db', default=':memory:', help='证据库存放路径，默认内存库')
    run_p.add_argument('--issue', action='store_true', help='顺序签发各期报告并保存判断链')

    verify_p = sub.add_parser('verify', help='按指纹取回已签发报告')
    verify_p.add_argument('db')
    verify_p.add_argument('fingerprint', nargs='?')

    args = parser.parse_args()
    if args.command == 'verify':
        db = connect(args.db)
        report = (load_issued(db, args.fingerprint)
                  if args.fingerprint else latest_issued(db))
        db.close()
        if report is None:
            raise SystemExit('未找到已签发报告')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    data = _load_bundle(args.input)
    db = connect(args.db)
    _ingest(db, data)
    if args.command == 'inspect':
        print(json.dumps(_inspect(db, data), ensure_ascii=False, indent=2))
    else:
        if args.issue and 'issued_at' not in data:
            db.close()
            raise SystemExit('签发需要资料包提供 issued_at 列表')
        print(json.dumps(_run(db, data, args.issue), ensure_ascii=False, indent=2))
    db.close()


if __name__ == '__main__':
    main()
