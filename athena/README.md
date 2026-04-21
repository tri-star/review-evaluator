# Athena Notes

このリポジトリでは Athena 自体を必須では作成しない。
外部リポジトリの Terraform などで Athena / Glue / S3 を作成する場合でも、このディレクトリの SQL をそのまま使えるようにする。

## 想定

- review result は `reviews/repo_partition={owner_repo}/year={YYYY}/month={MM}/day={DD}/pr={PR_NUMBER}/run={RUN_AT}.json` に保存される
- evaluation result は `evaluations/repo_partition={owner_repo}/year={YYYY}/month={MM}/day={DD}/pr={PR_NUMBER}.json` に保存される
- daily / weekly summary は `aggregates/` 配下の `repo_partition={owner_repo}` に保存される
- Athena で読む JSON は JSON Lines を前提とする。整形済み JSON が混在すると OpenX JSON SerDe では失敗する
- raw review JSON の本文には `repo`, `pr_number`, `run_at`, `head_sha` が必ずしも入らない。`repo_partition` はパーティション列、`pr_number` と `run_at` は S3 パスから別途抽出する

## 利用手順

1. 外部 IaC で Athena WorkGroup と Glue Database を作成する
2. このディレクトリの DDL を使って外部テーブルを作成する
3. `reviews/` を再配置した場合は、既存 partition を DROP してから再登録する
3. 代表クエリを必要に応じてダッシュボードや運用レポートに流用する
