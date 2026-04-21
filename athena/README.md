# Athena Notes

このリポジトリでは Athena 自体を必須では作成しない。
外部リポジトリの Terraform などで Athena / Glue / S3 を作成する場合でも、このディレクトリの SQL をそのまま使えるようにする。

## 想定

- review result は `reviews/` に JSON で保存される
- evaluation result は `evaluations/` に JSON で保存される
- daily / weekly summary は `aggregates/` に JSON で保存される

## 利用手順

1. 外部 IaC で Athena WorkGroup と Glue Database を作成する
2. このディレクトリの DDL を使って外部テーブルを作成する
3. 代表クエリを必要に応じてダッシュボードや運用レポートに流用する
