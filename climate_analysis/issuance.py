"""已签发判断的不可变存档。

签发只追加、不覆盖：同一报告指纹重复签发是幂等的；
新签发报告记录上一份已签发报告指纹，形成判断链，
新基准发布后旧判断仍可原样取回复核。
"""
import json
import sqlite3

ISSUED_SCHEMA = """
CREATE TABLE IF NOT EXISTS issued_reports (
  fingerprint TEXT PRIMARY KEY,
  predecessor TEXT,
  issued_at TEXT NOT NULL,
  known_at TEXT NOT NULL,
  common_datum TEXT,
  report_json TEXT NOT NULL,
  FOREIGN KEY(predecessor) REFERENCES issued_reports(fingerprint)
);
"""


def init_issuance(db):
    db.executescript(ISSUED_SCHEMA)


def issue(db, report, issued_at, predecessor=None):
    init_issuance(db)
    fingerprint = report['fingerprint']
    row = db.execute('SELECT predecessor,issued_at FROM issued_reports WHERE fingerprint=?',
                     (fingerprint,)).fetchone()
    if row:
        return {'fingerprint': fingerprint, 'predecessor': row[0],
                'issued_at': row[1], 'duplicate': True}
    if predecessor is not None and not db.execute(
            'SELECT 1 FROM issued_reports WHERE fingerprint=?',
            (predecessor,)).fetchone():
        raise ValueError('前任签发报告不存在，判断链不能断')
    with db:
        db.execute('INSERT INTO issued_reports VALUES(?,?,?,?,?,?)',
                   (fingerprint, predecessor, issued_at, report['known_at'],
                    report.get('common_datum'),
                    json.dumps(report, ensure_ascii=False, sort_keys=True)))
    return {'fingerprint': fingerprint, 'predecessor': predecessor,
            'issued_at': issued_at, 'duplicate': False}


def load_issued(db, fingerprint):
    init_issuance(db)
    row = db.execute('SELECT report_json FROM issued_reports WHERE fingerprint=?',
                     (fingerprint,)).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def latest_issued(db):
    init_issuance(db)
    row = db.execute(
        'SELECT report_json FROM issued_reports ORDER BY rowid DESC LIMIT 1').fetchone()
    return json.loads(row[0]) if row else None
