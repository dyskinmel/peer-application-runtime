# ADR-AUTH-0001 — bounded local authority model

00.07.00 / candidate / self-review only / production gate NOT_RUN。

## Rootと初期化
受信genesisをそのままtrust rootにしない。呼出側は別の信頼経路で得たAppIdとSpaceIdを渡す。genesis bodyのspace-id hash、initial authority署名を照合する。seq=1/epoch=1/action=initが唯一の最初のcontrol。genesisのpolicy digestは本候補ではinitial resource-policy rootに一致させる。

membershipはDeviceId昇順で最大256件、64件ごとのcanonical member-page。page hash=H(member-page-id,[raw])、root=H(membership-root,[ordered page hashes])。空集合は0ページ。ページ分割・ID順序・一意性を固定し、同件数で別集合を受け入れない。256はこの実験のresource profileで製品の絶対上限ではない。

## sequence / epoch / authority
署名済みcontrolを観測したらknown headを更新し、membershipが未検証なら共有操作を止める。認可の不足を旧権限へのfallbackで埋めない。permission-onlyはreader/editorの(DeviceId,cert digest,role)集合を完全保持し、Keeperのみ変更可能。rotationとcheckpointはrootsとpolicyを保持。content-transitionだけがepoch+1、fresh package-set/root/seed-rootを要求。checkpointによるsnapshot圧縮はこの実験では実装しない。

各controlの署名者は親から導出。rotationはold署名+new possessionを異なるdomainで検証し、次のentryからnewを採用。親が既知の同一位置の別の有効署名は、過去の位置であってもfreeze。無効署名/別Space/未知親/gapではfreezeしない。勝者選択やfreeze解除は行わない。

## key package anchor
同epochのKeeper変更やauthority rotationでは初期packageを再生成しない。packageのmembership rootと署名者はそのepochを開始したcontrolに固定。recipientはanchorと最新membershipの両方で同一certificateのreader/editorであること。鍵を得ることと現在のwrite許可は別。

## resource / failure
root受理前に入力数/長さを制限。historyは最大1024control・記録bytes合計768KiB（local profile、再取得可能なresource-blocked）。pure stateでthreadを跨ぐ操作は拒否する。判定tokenはstate revisionに結合し、変更後の使い回しを拒否。

## 残る境界
quota/resource-policyの業務意味、network session proof、最新control隠蔽検知、Automerge actor/merge、Storeへのatomic apply、永続auth journal、実機・独立cryptoレビューは未実装。署名・hashの成功からこれらを導出しない。
