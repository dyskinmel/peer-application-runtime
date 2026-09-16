# 管理ジョブで参照した一次資料
確認日: 2026-09-06。実装計測と外部文書を混同しない。

- Python 3.13 os: https://docs.python.org/3.13/library/os.html — fsync / replace のAPI契約。
- SQLite Atomic Commit: https://www.sqlite.org/atomiccommit.html — OS/FSの前提と故障境界。job journalとbackendを一つのtransactionにする根拠ではない。
- SQLite WAL: https://www.sqlite.org/wal.html — WALの制約と修正情報。搭載3.46.1を修正版として認定していない。

外部sourceは設計の参考。実際のlocal PASSは同梱テストとログでのみ主張し、独立reviewの代わりにはしない。
