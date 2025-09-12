# PubMed API × MCP サーバー実装ガイド（Search / Fetch / GetFullText）

最終更新: 2025-09-12（JST）

---

## 0. 目的

このドキュメントは、\*\*PubMed/PMC の公式 API（NCBI Entrez E-utilities と PMC OA サービス）\*\*を用いて、以下 3 機能を提供する **MCP サーバー**を実装するための技術仕様と実装指針です。

* **Search**: PubMed の **MeSH 検索**に対応し、クエリに対して **最大 100 件**の論文タイトルを返す
* **Fetch**: **PMID の配列**に対して、抄録（Abstract）を返す
* **GetFullText**: **PMCID の配列**に対して、PMC からフルテキスト（JATS XML もしくは PDF/TAR の取得先）を返す

> **重要**: NCBI のレート制限・自動ダウンロード規約・著作権ポリシーに必ず従ってください（詳細は後述）。

---

## 1. 使う API 一覧（要点）

* **E-utilities 共通ベース URL**: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`

  * 代表的ツール: `esearch.fcgi` / `esummary.fcgi` / `efetch.fcgi` / `epost.fcgi` / `elink.fcgi` / `einfo.fcgi` / `espell.fcgi` / `ecitmatch.cgi`
* **PMC OA Web Service（OA サブセットの配布情報）**: `https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi`
* **PMCID/PMID/DOI 変換**: `https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/`

---

## 2. レート制限・運用ポリシー（遵守事項）

* **レート**: API キーなし **最大 3 req/s**、API キーあり **最大 10 req/s**（*超過でエラー*）。大量処理は \*\*夜間/週末（ET）\*\*推奨。
* **識別子**: クエリに `tool`（自アプリ名）と `email`（開発者連絡先）を付与し、NCBI に登録することが推奨。
* **大量取得**: `usehistory=y`（History サーバ）と `WebEnv`/`query_key` を活用し、**分割取得**・**POST** 利用を推奨。
* **PubMed の検索上限**: `esearch` の `retmax` は **最大 10,000**。PubMed では**最初の 10,000 件しか直接は取得不可**の制限があるため、日付等でクエリを分割。
* **PMC の自動取得**: **自動一括ダウンロード**は **PMC OA サービス / PMC FTP / BioC API / AWS RODA** のみ許可。通常の Web 画面や非許可経路でのクロールは不可。

---

## 3. Search（MeSH 対応・最大100件タイトル）

### 3.1 目的

* 入力: `term`（MeSH 対応のクエリ文字列）
* 出力: **最大 100 件**の `{pmid, title, pubdate, journal}` の配列

### 3.2 推奨フロー

1. **ESearch**（JSON で UID リスト）

```http
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
  ?db=pubmed
  &term={ENCODED_QUERY}
  &retmode=json
  &retmax=100
  &retstart={offset}
  &usehistory=y
  &tool={your_tool}&email={your_email}&api_key={api_key}
```

* **MeSH 検索例**: `"asthma"[MeSH Terms] AND adult[MeSH Terms]`

  * フィールドタグ例: `[mh]`（MeSH）, `[majr]`（MeSH Major Topic）, `[tiab]`（Title/Abstract）など
* レスポンス: `esearchresult.idlist` に PMID の配列
* 注意: `retmax` の上限は 10,000。PubMed は 10,000 超の直接取得不可のため、必要に応じて **日付で分割**（例: `2020:2021[dp]`）。

2. **ESummary**（タイトル等をまとめ取り）

```http
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi
  ?db=pubmed
  &id=PMID1,PMID2,...
  &retmode=json
  &tool={your_tool}&email={your_email}&api_key={api_key}
```

* レスポンス: `result[PMID].title`, `pubdate`, `fulljournalname` など
* 100 件以内なら 1 回の呼び出しで十分。

### 3.3 実装メモ

* \*\*ATM（Automatic Term Mapping）\*\*への配慮: フィールドタグ指定（例: `[mh]`, `[tiab]`）で意図を明示
* **ページング**: `retstart` を用意
* **エラー**: JSON の `error`（レート超過等）・`esearchresult.errorlist` を確認

---

## 4. Fetch（PMID リスト→Abstract）

### 4.1 目的

* 入力: `id: PMID[]`（**配列**）
* 出力: 各 PMID の **抄録（Abstract）** とメタデータ

### 4.2 推奨フロー

* **EFetch（PubMed）**

```http
POST https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
Content-Type: application/x-www-form-urlencoded

db=pubmed&retmode=xml&rettype=abstract&id=PMID1,PMID2,...
  &tool={your_tool}&email={your_email}&api_key={api_key}
```

* **解析ポイント（XML）**

  * 抄録本文: `PubmedArticleSet/PubmedArticle/MedlineCitation/Article/Abstract/AbstractText`
  * 複数セクション（例: `Label` 属性）に注意
* 返却形: `[{ pmid, title, abstract, journal, year, authors[] }, ... ]`

> 注: `efetch` は **JSON 非対応**です（PubMed では XML/テキスト）。必要に応じて XML→JSON へ変換してください。

---

## 5. GetFullText（PMCID リスト→フルテキスト）

### 5.1 目的

* 入力: `id: PMCID[]`（**配列**）
* 出力: 各 PMCID の **フルテキスト JATS XML**（`efetch`）または **OA サービス経由の PDF/TAR の URL 情報**

### 5.2 方法 A: **EFetch（PMC, JATS XML）**

```http
POST https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
Content-Type: application/x-www-form-urlencoded

db=pmc&id=PMCXXXXXXX,PMCYYYYYYY&retmode=xml
  &tool={your_tool}&email={your_email}&api_key={api_key}
```

* 返却: **JATS XML**（本文, 図表等の参照含む）

### 5.3 方法 B: **PMC OA Web Service（ダウンロード可能リソース情報）**

```http
GET https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMCXXXXXXX
```

* 返却: 当該 PMCID の **利用可能なファイル一覧（PDF/TAR 等）**
* **自動一括ダウンロード**は **OA サービス / FTP / BioC / AWS RODA** の **許可ルートのみ**利用可

> **注意**: OA サブセット外の記事は自動ダウンロード不可。画面の直接クロールも不可。ライセンス表記の尊重を徹底。

### 5.4 付録: BioC / AWS / FTP

* **BioC API**（OA のみ、XML/JSON 提供）
* **PMC FTP**（OA/Author Manuscript/History OCR などのバルク）
* **AWS RODA**（OA データセットのクラウドホスティング）

---

## 6. ID 変換（PMID/PMCID/DOI）

* **ID Converter API**

```http
GET https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids=10.1093/nar/gkab1105,PMC1234567,12345678&format=json
```

* 返却: 与えた各 ID に対して、対応する **PMID / PMCID / DOI** を解決

---

## 7. History サーバ（大規模取得の基本）

* `usehistory=y` を付けた `esearch` / `epost` の応答から **`WebEnv` と `query_key`** を取得
* 以降の `esummary` / `efetch` に `WebEnv`+`query_key` を渡すと、**UID リストを URL に展開せず**に取得可能（大量/長 URL 回避）

**例**

```
1) esearch?db=pubmed&term=...&usehistory=y → WebEnv, query_key
2) esummary?db=pubmed&WebEnv=...&query_key=...
3) efetch?db=pubmed&WebEnv=...&query_key=...&rettype=abstract&retmode=xml
```

---

## 8. MCP サーバー I/O 仕様（提案）

### 8.1 共通

* **HTTP**: JSON over HTTPS
* **入出力**: UTF-8 / `application/json`
* **エラー**: `status`, `error.code`, `error.message`, `error.retryAfterSec`（429 等）
* **スロットリング**: サーバー側で **10 req/s（API キー想定）** を超えないよう制御、指数バックオフ再試行

### 8.2 `POST /search`

**Request**

```json
{
  "term": "asthma[mh] AND adult[mh]",
  "retmax": 100,
  "retstart": 0
}
```

**Response**

```json
{
  "count": 1234,
  "items": [
    {"pmid": "12345678", "title": "...", "pubdate": "2023", "journal": "..."}
  ],
  "retmax": 100,
  "retstart": 0
}
```

### 8.3 `POST /fetch`

**Request**

```json
{
  "id": ["40930554", "40929575", "40929571"]
}
```

**Response（抜粋）**

```json
{
  "items": [
    {"pmid": "40930554", "title": "...", "abstract": "...", "journal": "...", "year": 2024}
  ]
}
```

### 8.4 `POST /getFullText`

**Request**

```json
{
  "id": ["PMC1234567", "PMC7654321"],
  "format": "xml|pdf|auto"  // auto: OAならPDF/TAR URL、非OAはJATS XMLのみ  
}
```

**Response（例）**

```json
{
  "items": [
    {"pmcid": "PMC1234567", "jatsXml": "<article>...</article>", "pdf": "https://.../PMC1234567.pdf"},
    {"pmcid": "PMC7654321", "jatsXml": "<article>...</article>", "pdf": null}
  ],
  "notes": ["非OAはPDF配布不可。OAのみ PDF/TAR の自動配布可"]
}
```

---

## 9. 実装のポイント（詳細）

* **HTTP メソッド**: 長い `id` リストは **POST** を使用（URL 長制限とログ漏れ回避）
* **ヘッダ**: `Accept: application/json`（ESearch/ESummary）, `Accept: application/xml`（EFetch）
* **ID 配列**: 受信後、**重複除去**・**最大バッチサイズ**で分割（例: 200 件/リクエスト）
* **再試行**: 429/5xx は指数バックオフ（初回 1s→2s→4s、最大 4 回など）
* **文字コード**: UTF-8 固定。URL エンコード（特に `"` `%22`, `#` `%23`, 空白 `+`）
* **抽出**: PubMed 抄録は XML の `AbstractText` が複数要素/見出し付きの場合あり。連結時に改行やラベル見出しを保持
* **JSON 非対応**: `efetch` は JSON 不可（PubMed/PMC ともに XML 基本）。必要ならサーバー側で変換
* **MeSH**: `mesh:noexp` で展開抑制、`[majr]` で主要トピック指定などを UI でサポート

---

## 10. サンプル（cURL）

### 10.1 MeSH 検索 → タイトル（最大100件）

```bash
# 1) ESearch (MeSH 検索)
curl -G "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi" \
  --data-urlencode "db=pubmed" \
  --data-urlencode "term=asthma[mh] AND adult[mh]" \
  --data-urlencode "retmode=json" \
  --data-urlencode "retmax=100" \
  --data-urlencode "usehistory=y" \
  --data-urlencode "tool=YOUR_TOOL" \
  --data-urlencode "email=YOUR_EMAIL" \
  --data-urlencode "api_key=YOUR_KEY"

# 2) ESummary (タイトル取得)
curl -G "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi" \
  --data-urlencode "db=pubmed" \
  --data-urlencode "id=PMID1,PMID2,..." \
  --data-urlencode "retmode=json" \
  --data-urlencode "tool=YOUR_TOOL" \
  --data-urlencode "email=YOUR_EMAIL" \
  --data-urlencode "api_key=YOUR_KEY"
```

### 10.2 PMID→抄録

```bash
curl -X POST "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "db=pubmed&id=40930554,40929575,40929571&retmode=xml&rettype=abstract&tool=YOUR_TOOL&email=YOUR_EMAIL&api_key=YOUR_KEY"
```

### 10.3 PMCID→フルテキスト

```bash
# JATS XML（efetch）
curl -X POST "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "db=pmc&id=PMC1234567,PMC7654321&retmode=xml&tool=YOUR_TOOL&email=YOUR_EMAIL&api_key=YOUR_KEY"

# OA Web Service（PDF/TAR の有無・URL 検出）
curl -G "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi" --data-urlencode "id=PMC1234567"
```

---

## 11. 典型エラーと対処

* **429 / レート超過**: `{"error":"API rate limit exceeded","count":"11"}` のような JSON が返る場合あり → **リトライ + スロットリング強化**
* **長 URL 問題**: `id` が多い場合は **POST に切替**
* **10,000 件制限**: PubMed の `esearch` は **最初の 10,000 件**のみ → **日付分割**やフィルタで回避
* **JSON 非対応**: `efetch` は XML（PubMed/PMC）。**XML パース**の堅牢化（タイムアウト・不正 XML の例外処理）

---

## 12. フィールドタグ（MeSH など）

* 例: `[mh]`（MeSH）, `[majr]`（MeSH Major Topic）, `[tiab]`（タイトル/抄録）, `[dp]`（発行年・日付）, `[ta]`（誌名）
* 例: `covid-19[mh] AND vaccination[tiab] AND 2022:2024[dp]`

---

## 13. セキュリティ/コンプライアンス

* API キーの保管（サーバー側のシークレット管理）
* 著作権/ライセンス順守（OA サブセットのみ自動取得可）
* タイムアウト・監視・アクセスログ（個人情報なし）

---

## 14. 参考（必読）

* E-utilities 総合: A General Introduction / Quick Start / In-Depth Parameters
* レート/キー/運用: API Keys, 3→10 req/s, tool/email
* ESearch `retmax`=10,000・PubMed の 10,000 件上限
* History サーバ（WebEnv/query\_key）
* フィールドタグ（MeSH 等）
* PMC OA Web Service / 許可された自動取得経路（OA/FTP/BioC/AWS）
* ID Converter API（PMID/PMCID/DOI）

---

## 付録: 最小実装チェックリスト

* [ ] `tool`/`email`/`api_key` の添付とレート制御（10 req/s 以下）
* [ ] Search: `esearch.json` → `esummary.json` でタイトル 100 件
* [ ] Fetch: `efetch.xml`（PubMed）から Abstract 抽出
* [ ] GetFullText: `efetch.xml`（PMC, JATS）または OA サービスで PDF/TAR 検出
* [ ] 大量処理は `usehistory=y` + `WebEnv/query_key` で分割
* [ ] バッチ `id` は POST、XML 例外処理、指数バックオフ
* [ ] ライセンス遵守（OA 以外は PDF 自動配布不可）
