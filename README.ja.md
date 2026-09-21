[English](README.md) | **日本語**

# jev-skill-router

インストール済みの skill のうちどれが今のプロンプトに合うかを、高速な確率モデルに尋ね、その答えを agent に届ける前にログへ残す Claude Code の hook です。

[![tests](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml/badge.svg)](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

jev-skill-router は、skill を何十本も入れている人のための Claude Code プラグインです。プロンプトを送るたびに `UserPromptSubmit` hook が、プロンプトと skill の名簿を [TypeSafe](https://typesafe.ai) の Jev モデルへ送ります。Jev は文章ではなく、型の決まった質問に確率で答えるモデルです。その確率をコードが読み、skill を最大 1 本だけ名指しするか、何も名指ししません。Python 3.10 以上、標準ライブラリのみ、MIT ライセンス、バージョン 0.1.0 で、まだ実験段階です。

Claude Code は、すべての skill の 1 行説明をモデルに見せて、選択をモデルに任せます。名簿が長くなると、モデルは合う skill を読み飛ばしたり、何も合わないのに 1 本読み込んだりします。このプラグインは、その選択を独立した、あとから調べられる判定に変えます。最初は **shadow モード**で動きます。提案したはずの内容を記録するだけで何も注入しないので、実際にセッションが使った skill と見比べてから有効にできます。

## インストール

```
/plugin marketplace add shimo4228/jev-skill-router
/plugin install jev-skill-router@jev-skill-router
```

プラグインを有効にするとき、Claude Code が 3 つの設定を尋ねます。TypeSafe の API key（[ここで作成](https://console.typesafe.ai/keys)。システムのキーチェーンに保存されます）、モード（既定は `shadow`）、任意のログの保存先です。モードの選択 UI には Claude Code 2.1.271 以上が必要です。それより古い版では、環境変数 `JEV_ROUTER` に `inject` か `off` を設定しない限り `shadow` のままです。key は環境変数 `TYPESAFE_API_KEY` で渡すことも、`~/.config/typesafe/api_key` に置くこともできます。環境変数で `JEV_ROUTER=off` を設定すると、そのプロセスだけ hook が止まります。無人で走るスクリプトを対象から外したいときに使います。

プラグイン機構を使わずに動かす場合は、[運用マニュアル](skills/jev-skill-router/SKILL.md#install)の手動配線を見てください。

## 判定のしかた

手順は TypeSafe が公開している [skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion) を、Claude Code の hook に移したものです。質問文と閾値は cookbook からそのまま取り、1 つのファイルに定数として置いています。

1. **Wide（全体）。** 1 回のリクエストで、名簿全体を skill 名と説明の先頭 60 文字で順位付けします。同時に、プロンプトそのものについて Yes/No の質問を 3 つ尋ねます。ユーザーのシステムに対する操作か、専門家なら文書化された手順に従うか、文章だけで足りるか、の 3 つです。その平均が 0.30 未満なら、ここで止まります。skill は不要と判断し、2 回目のリクエストは使いません。
2. **Narrow（絞り込み）。** 上位 3 件を、説明の全文と各 `SKILL.md` の先頭 700 文字つきで送り直します。モデルが 1 本を選び、候補ごとにもう 1 問答えます。「この skill は、頼まれた具体的なことをするか」です。最も高い答えが 0.30 未満なら、何も提案しません。

名簿は 3 か所から組み立てます。ユーザーの skill、設定で有効になっているプラグインの skill、そしてセッションの作業ディレクトリから git のルートまでに見つかる project skill です。`disable-model-invocation: true` の skill は除きます。Claude Code がモデルの文脈に置く skill 一覧を、この hook が書き換えることはありません。足すのは下に示すブロック 1 つだけなので、その一覧に対する prompt cache には影響しません。

失敗はすべて exit 0 で終わります。key が無い、タイムアウトした、API がエラーを返した、いずれの場合もログが 1 行増えるだけで、ターンは止まりません。`shadow` モードでは、hook は切り離した子プロセスに仕事を渡してすぐに戻るので、ターンは遅れません。`inject` モードは答えを待つ必要があり、全リクエストを合わせて 3 秒の上限の中で動きます。2026-09-21 に行った実際の判定 3 回は、0.5〜1.3 秒でした。

## 1 回の判定はこう見えます

`off` 以外のモードでは、プロンプトごとに JSON を 1 行、プラグインのデータディレクトリにある `decisions.jsonl` へ追記します。次の行は `jev-1.13.0` に対する実際の呼び出し（`inject` モード）のものです。プロンプトは日本語で、設計判断を ADR として記録したい、という内容でした。`gate` は手順 1 の平均、`fits` は手順 2 の候補ごとの答えで、どちらも 0.30 を超えたので skill が名指しされました。行は一部を省略しています。

```json
{"mode": "inject", "model": "jev-1.13.0", "question_hash": "662772b42ed4",
 "n_skills": 50, "n_by_source": {"user": 45, "plugin": 5, "project": 0},
 "gate": 0.4833, "shortlist": ["adr-writer", "adhd:adhd", "archify"],
 "fits": {"adr-writer": 0.93, "adhd:adhd": 0.15, "archify": 0.05},
 "suggestion": "adr-writer", "elapsed_ms": 1329}
```

プロンプトの本文はログに書きません。書くのはハッシュと文字数だけです。`shadow` モードでは、この 1 行がすべてです。`inject` モードでは、判定に加えて次のブロックがターンに足されます。どの skill も閾値を超えなければ、何も足しません。

```
<skill_relevance>
Relevant to the current request: adr-writer. Ignore this if it does not fit what the user actually asked for.
</skill_relevance>
```

## 機外に出るもの

判定のたびに `api.typesafe.ai` へ送られるのは、プロンプトの全文、名簿にある全 skill の名前と説明の先頭 60 文字、そして上位 3 件に限り、説明の全文と `SKILL.md` の先頭 700 文字です。会話の履歴、あなたのプロジェクトのファイル、ツールの出力は送りません。

**プロンプトに貼り付けた secret は、そのまま送られます。** 除去する処理はありません。送信先のホストはコード内で固定し、リダイレクトは拒否するので、環境変数ひとつで key やプロンプトを別のホストへ送らせることはできません。

## 制約

- 閾値は cookbook の出発値です。ベンダーが英語の名簿と、より古いモデル版で測った値で、あなたの名簿や言語に合わせた較正はされていません。shadow モードはそのためにあります。
- この repo 自身の効果の数値は、まだありません。cookbook が報告しているのはベンダーの実験で、提案が「agent が正しくできていたターン」を壊した例も含まれています。あなたの名簿での結果ではなく、彼らの名簿での方向性として読んでください。
- ディスクに `SKILL.md` を持たない組み込みの skill と、`--add-dir` で追加したディレクトリ配下の skill は提案できません。
- `/` で始まるプロンプトと 4000 文字を超えるプロンプトは対象外です。
- TypeSafe は有料の外部 API で、判定のたびに 1〜2 リクエストを使います。skill 50 本の名簿で行った上記の実際の判定では、手順 1 で止まった場合に入力が約 2,400 トークン、両方の手順が走った場合に 4,200〜4,800 トークンでした。現在の料金と上限は [TypeSafe の料金ページ](https://docs.typesafe.ai/models)で確認してください。変わりうる値なので、この README には書いていません。

## 自分のログを読む

`model`、`router_version`、`question_hash` のいずれかが違う行は、別の判定器が出したものなので、分けて読んでください。`inject` を有効にする価値があるかは、ログを `session` と時刻で、各セッションが実際に使った skill の自前の記録と突き合わせ、3 つの件数を読んで決めます。提案して使われた、提案したが使われなかった、使われたが提案しなかった、の 3 つです。ログが無いことは「未測定」を意味し、「提案ゼロ」ではありません。

## 関連する取り組み

- 手順の出所は [TypeSafe の skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion) です。
- [DECRUX9812/typesafe-skill-router](https://github.com/DECRUX9812/typesafe-skill-router) は、同じ cookbook を Hermes Agent 向けに実装しています。その文書から 2 つの知見を借りました。1 つの質問は 255 択が上限なので大きな名簿は分割すること、そして順位付けと候補ごとの適合判定が食い違う場合があることです。コードはコピーしていません。
- Claude Code 向けの router はほかにもあります。たとえば [skillranker](https://github.com/Dicklesworthstone/skillranker) は、ローカルの履歴と較正コマンドを持つ Rust の CLI です。こちらは、追加のパッケージを入れずに（TypeSafe の API は必要です）`/plugin install` で入り、プラグインと project の skill も名簿に含め、提案する前に測りたい人のためのものです。

## 来歴

このプロジェクトは TypeSafe AI とは無関係です。コードは、著者の指示のもとで Claude Code が書きました。オフラインのテスト（`uv run pytest -q`、ネットワーク不要）で検査しています。key とプロンプトが通る経路は、自動のレビュー（LLM の security review エージェントと、Claude Code 組み込みの code review）にかけました。その結果、HTTP リダイレクト時の key の漏えいと、信頼できない文字列がモデルの文脈に届く経路が見つかり、修正しています。第三者の人間による監査は受けていません。

## そのほか

- [運用マニュアル](skills/jev-skill-router/SKILL.md)（英語）: すべてのモード、設定、ログの欄、対象外になる条件
- [変更履歴](CHANGELOG.md)
- ライセンス: [MIT](LICENSE)
