# 00.59.10 P0 — Canonical Source Recovery

## 結論

ダウンロード可能な 00.57 / 00.58 / 00.59 成果物を比較した結果、3つの `repository/` はすべて同一の tracked source を持つ。

- HEAD: `1203f5b2463f092b176c94cad6f4c92532d1b9b3`
- tree: `44900db2293a8d2a4a258c6e6d823d14c868e140`
- tracked files: `1904`
- working tree: clean
- 00.57 ↔ 00.58 tracked byte differences: `0`
- 00.57 ↔ 00.59 tracked byte differences: `0`
- `git fsck`: 3/3 PASS
- 00.58 / 00.59 `source.bundle`: verify PASS、先頭sourceは同じ00.57 commit

したがって、00.58/00.59のチャット上の実装主張をsourceへ昇格せず、**00.57 verified baselineだけをcanonical sourceとして採用**する。

## Canonical recovery rule

1. ダウンロード可能な成果物に実在するbyteだけを回収対象とする。
2. report/evidenceに記載があってもGit sourceまたは復元可能patch/bundleに存在しない実装は回収済みとみなさない。
3. 00.58/00.59のreportはfailure history / provenanceとして保持できるが、source completion evidenceには使わない。
4. Harness Reliability Upgradeは00.57 sourceから新branch `work/0059.10-harness-reliability` で開始する。
5. 過去receiptは新sourceのPASSへ流用しない。

## Fresh baseline verification

新しいcanonical clone上で以下をfresh実行した。

- `python3 tools/harness.py doctor`: PASS
- `python3 tools/harness.py validate`: PASS
- `python3 tools/preflight_delivery.py`: PASS
- `python3 tools/check_migration_rehearsal.py`: 45/45 PASS
- `python3 tools/check_native_provider_handoff.py`: 57/57 PASS

変更前source digestは `2469b68f90a5d0d6542711acf08e93376bac6108294b6758073d74dd98d24953`。

## 00.58 / 00.59についての扱い

公開・開発ともに、以下は**非主張**とする。

- ダウンロード可能なGit sourceには00.58 operations hardening実装を確認できない。
- ダウンロード可能なGit sourceには00.59 device-handoff実装を確認できない。
- したがって、それらをcanonical sourceへ自動復元・再構築しない。

後続で必要なら、正式なTDDサイクルで再実装する。

## 次フェーズ

**P1 — Artifact Survival**

重いverificationより前に再開可能artifactを必ず残す構造をHarnessへ正式追加する。

- checkpoint
- `package --status partial`
- `package --status verified`
- emergency package
- artifact classification
- packaging reserve
- kill/timeout failure injection

推奨effort: **High**。
