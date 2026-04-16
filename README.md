# 柱状図→圧入自動運転設定値 自動生成ロジック設計プロジェクト

## 概要

柱状図（ボーリング柱状図）から圧入自動運転の設定値を自動生成する機能を実現するため、必要なデータ・ロジック・設計を体系的にドキュメント化するプロジェクト。

## 目的

- 柱状図データと圧入管理データの収集・整理
- 地質情報から圧入設定値への変換ロジックの設計
- 自動生成アルゴリズムのドキュメント化
- 将来の実装に向けた仕様策定

## プロジェクト構成

```
histogram-to-config/
├── README.md                          # 本ファイル
├── .github/
│   ├── copilot-instructions.md        # ワークスペース共通指示
│   ├── agents/                        # カスタムエージェント
│   │   ├── geology-analyst.agent.md   # 地質データ分析エージェント
│   │   ├── config-designer.agent.md   # 圧入設定値設計エージェント
│   │   └── document-writer.agent.md   # ドキュメント作成エージェント
│   └── skills/                        # カスタムスキル
│       ├── geology-data-analysis/     # 柱状図データ分析スキル
│       ├── press-in-config-logic/     # 圧入設定値変換ロジックスキル
│       └── design-document/           # 設計ドキュメント作成スキル
├── docs/
│   ├── 01_data-collection/            # データ収集資料
│   │   ├── borehole-data-spec.md      # 柱状図データ仕様
│   │   └── press-in-management-data.md # 圧入管理データ仕様
│   ├── 02_analysis/                   # 分析資料
│   │   ├── geology-classification.md  # 地質分類体系
│   │   └── correlation-analysis.md    # 地質-設定値相関分析
│   ├── 03_design/                     # 設計資料
│   │   ├── conversion-logic.md        # 変換ロジック設計
│   │   ├── parameter-mapping.md       # パラメータマッピング定義
│   │   └── algorithm-spec.md          # アルゴリズム仕様
│   └── 04_validation/                 # 検証資料
│       └── test-cases.md              # テストケース定義
└── data/
    ├── samples/                       # サンプルデータ
    └── schemas/                       # データスキーマ定義
```

## エージェント

| エージェント | 説明 | 用途 |
|---|---|---|
| `geology-analyst` | 地質データ分析の専門家 | 柱状図データの読み解き、地質分類、N値分析 |
| `config-designer` | 圧入設定値変換ロジック設計者 | 地質→設定値の変換ルール設計、アルゴリズム策定 |
| `document-writer` | 技術ドキュメントライター | 設計資料・仕様書の作成・整理 |

## スキル

| スキル | 説明 |
|---|---|
| `geology-data-analysis` | 柱状図データの構造解析、地層情報の抽出・整理 |
| `press-in-config-logic` | 圧入設定値の変換ロジック設計・検証 |
| `design-document` | 設計ドキュメントの構造化・テンプレート適用 |

## ワークフロー

```
1. データ収集 → 柱状図・圧入管理データの収集と構造化
2. 分析       → 地質情報と圧入パラメータの相関分析
3. 設計       → 変換ロジック・アルゴリズムの設計
4. 検証       → テストケースによるロジック検証
5. 文書化     → 設計資料・仕様書の作成
```

## 関連プロジェクト

- G-LabNexus（親プロジェクト）
