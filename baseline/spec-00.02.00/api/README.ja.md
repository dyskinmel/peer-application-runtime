# API契約の読み方

`par-contracts.d.ts`は公開意味を固定する宣言であり、npm packageやSDK実装ではない。`example-contract.ts`は型整合だけを検査する。`tsc --noEmit --strict --target ES2020 --lib ES2020,DOM api/par-contracts.d.ts api/example-contract.ts`で検査できる。実行すると存在しないruntime implementationが必要になるため、実行例として扱わない。

Resultを通常の業務/通信/保存結果に用い、言語例外はプログラミングエラー/host停止に限定する。AsyncIterableは有限bufferとresync-required snapshotを持ち、無制限event溜め込みをしない。watch中断は購読の停止であり保存済みwrite取消しではない。SDK設計書のthreading/cancel/ID/Unicode契約を併読する。

公開対象は、Runtime/Spaces/Documents/Blobs/Events/Presence/RPC/Replicationおよびheadless Presenter。handler登録、host ports、admin operationsのbinding固有詳細はG0/G6で型を追加する。`Rpc`はclient側契約のみであり、未記載server-side effect transactionを実装済みとしない。
