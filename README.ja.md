[English](README.md) | **日本語**

# jev-skill-router

インストール済みの skill のうちどれが今のプロンプトに合うかを、高速な確率モデルに尋ね、その答えを agent に届ける前にログへ残す Claude Code の hook です。

[![tests](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml/badge.svg)](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

jev-skill-router は、skill を何十本も入れている人のための Claude Code プラグインです。プロンプトを送るたびに `UserPromptSubmit` hook が、プロンプトと skill の名簿を [TypeSafe](https://typesafe.ai) の Jev モデルへ送ります。Jev は文章ではなく、型の決まった質問に確率で答えるモデルです。その確率をコードが読み、skill を最大 1 本だけ名指しするか、何も名指ししません。Python 3.10 以上、標準ライブラリのみ、MIT ライセンス、バージョン 0.2.0 で、まだ実験段階です。

**インストールの前に読んでください。** 作って、動かして、「Claude Code の強いモデルに対する router としては、役に立つ見込みが小さい」という結論になりました。それでも公開しているのは、動く参考実装と計測器としてです。同じことを考える人が、私たちの分かったところから始められるように、理由を下に書いています。既定は **shadow モード**で、提案したはずの内容を記録するだけで、何も注入しません。

## 動かして分かったこと

**Claude Code 自身の skill 選択は、置き換えられません。** `UserPromptSubmit` hook にできるのは、ターンに文章を足すことだけです。Claude Code は引き続き全 skill の description をモデルに見せ、選ぶのはモデルです。router はその横で並走します。skill 一覧に使われるトークンは、1 つも減りません。

**cookbook の条件は、そのまま当てはまりません。** TypeSafe の実験では、agent は `claude-haiku-4-5` で、見えていたのは skill 1 本あたり 60 文字に切られた索引でした。だから、全文を読める別の読み手が足せるものがありました。Claude Code は、各 skill の description を全文（[skills の docs](https://code.claude.com/docs/en/skills) によれば 1,536 文字まで）モデルに見せます。ここでは router は、同じ description をすでに見ている強いモデルに、より弱い判定器が助言する形になります。router が足せる情報は `SKILL.md` の本文だけです。

**測ったこと**（すべて 2026-09-21、著者自身の名簿 50〜59 本、`jev-1.13.0`、プロンプトは日本語）:

- 意図が 1 つの依頼文（「この設計判断を ADR として記録したい」など）を用意して流した場合: 0.2.0 で 6 件中 6 件が妥当でした。5 件は人が選ぶであろう skill を fits 0.93〜0.98 で名指しし、お礼の一言には正しく何も提案しませんでした。
- 著者の実際のセッション（0.1.0、shadow モード）: 6 件中 3 件が妥当、3 件が外れでした。外れたのは、会話の途中の受け答え（「なぜそのガードを入れたのか」など）です。実際のセッションの大半は、こういう発話です。gate はこれらを 0.34〜0.64 と、skill が要るかのように採点しました。3 件とも、順位付けの勝者と、候補ごとの適合が最も高い候補が食い違っていました。
- 実セッションの 6 行は逸話であって、率ではありません。それでも載せるのは、このプロジェクトが持っている実セッションのデータが、これだけだからです。この 6 行は、切り詰めた文章で順位付けしていた 0.1.0 のものです。実セッションは 0.2.0 では取り直していません。版の違う行を混ぜて読まない、というこのプロジェクト自身の決まりに従って、分けて書いています。

**それでも役に立つかもしれない場面。** モデルが skill を使わない理由が、「間違った skill を選ぶ」ことではなく「skill を読まずに自分でやってしまう」ことにあるなら、ターンごとの名指しは、情報としてではなく、きっかけとして働きます。shadow のログで、この 2 つを見分けられます（「自分のログを読む」を見てください）。著者が shadow のまま動かし続けている理由はこれで、ログからそれが読み取れなければ外します。

**モデルに見せるもの自体を変えたいなら、この道具ではありません。** それができる仕組みは 2 つあります。

- 公式の設定 `skillOverrides` は、skill をモデルに「名前と description」「名前だけ」「見せない」のどれで載せるかを決められます（[skills の docs](https://code.claude.com/docs/en/skills)、値は `on` / `name-only` / `user-invocable-only` / `off`、2026-09-21 確認）。
- Claude Code の early access 機能である function hooks（通称 mods、[設計スレッド](https://github.com/anthropics/claude-code/issues/91870)）は、skill 一覧を書き換え可能な添付として公開しています。`anthropics/claude-code` の `mods/types/claude-code.d.ts` が、`prompt.attachment` の種別として `skill_listing` を挙げています（2026-09-21 確認）。私たちは試していません。cookbook が名簿を動かさずに 1 行だけ足している理由として挙げているのは、名簿が変わらなければ、その部分の prefix cache が効き続けることです。一覧をターンごとに書き換えれば、おそらくそれが失われます。このプロジェクトは、どちらの仕組みも使っていません。

## インストール

```
/plugin marketplace add shimo4228/jev-skill-router
/plugin install jev-skill-router@jev-skill-router
```

プラグインを有効にするとき、Claude Code が 3 つの設定を尋ねます。TypeSafe の API key（[ここで作成](https://console.typesafe.ai/keys)。システムのキーチェーンに保存されます）、モード（既定は `shadow`）、任意のログの保存先です。モードの選択 UI には Claude Code 2.1.271 以上が必要です。それより古い版では、環境変数 `JEV_ROUTER` に `inject` か `off` を設定しない限り `shadow` のままです。key は環境変数 `TYPESAFE_API_KEY` で渡すことも、`~/.config/typesafe/api_key` に置くこともできます。環境変数で `JEV_ROUTER=off` を設定すると、そのプロセスだけ hook が止まります。無人で走るスクリプトを対象から外したいときに使います。

プラグイン機構を使わずに動かす場合は、[運用マニュアル](skills/jev-skill-router/SKILL.md#install)の手動配線を見てください。

## 判定のしかた

手順は TypeSafe が公開している [skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion) を、Claude Code の hook に移したものです。質問文と閾値は cookbook からそのまま取り、1 つのファイルに定数として置いています。ただし cookbook の「説明を 60 文字に切る」索引は引き継いでいません。60 文字は cookbook が題材にした agent が自分の索引に表示する幅で、Claude Code は説明を切らずにモデルへ見せます。先頭だけで順位付けすると、agent が既に見ているものより少ない情報で判断することになるので、ここでは何も切り詰めません。

1. **Wide（全体）。** 1 回のリクエストで、名簿全体を skill 名と説明の全文で順位付けします。同時に、プロンプトそのものについて Yes/No の質問を 3 つ尋ねます。ユーザーのシステムに対する操作か、専門家なら文書化された手順に従うか、文章だけで足りるか、の 3 つです。その平均が 0.30 未満なら、ここで止まります。skill は不要と判断し、2 回目のリクエストは使いません。
2. **Narrow（絞り込み）。** 上位 3 件を、説明の全文と各 `SKILL.md` の本文全体つきで送り直します。モデルが 1 本を選び、候補ごとにもう 1 問答えます。「この skill は、頼まれた具体的なことをするか」です。最も高い答えが 0.30 未満なら、何も提案しません。

名簿は 3 か所から組み立てます。ユーザーの skill、設定で有効になっているプラグインの skill、そしてセッションの作業ディレクトリから git のルートまでに見つかる project skill です。`disable-model-invocation: true` の skill は除きます。Claude Code がモデルの文脈に置く skill 一覧を、この hook が書き換えることはありません。足すのは下に示すブロック 1 つだけなので、その一覧に対する prompt cache には影響しません。

失敗はすべて exit 0 で終わります。key が無い、タイムアウトした、API がエラーを返した、いずれの場合もログが 1 行増えるだけで、ターンは止まりません。`shadow` モードでは、hook は切り離した子プロセスに仕事を渡してすぐに戻るので、ターンは遅れません。`inject` モードは答えを待つ必要があり、全リクエストを合わせて 3 秒の上限の中で動きます。0.2.0 で行った実際の判定 6 回（2026-09-21）は、0.7〜1.6 秒でした。

## 1 回の判定はこう見えます

`off` 以外のモードでは、プロンプトごとに JSON を 1 行、プラグインのデータディレクトリにある `decisions.jsonl` へ追記します。次の行は `jev-1.13.0` に対する実際の呼び出し（`inject` モード）のものです。プロンプトは日本語で、設計判断を ADR として記録したい、という内容でした。`gate` は手順 1 の平均、`fits` は手順 2 の候補ごとの答えで、どちらも 0.30 を超えたので skill が名指しされました。行は一部を省略しています。

```json
{"mode": "inject", "model": "jev-1.13.0", "router_version": "0.2.0",
 "question_hash": "662772b42ed4",
 "n_skills": 52, "n_by_source": {"user": 45, "plugin": 7, "project": 0},
 "gate": 0.47, "shortlist": ["adr-writer", "adhd:adhd", "archify"],
 "fits": {"adr-writer": 0.93, "adhd:adhd": 0.14, "archify": 0.05},
 "suggestion": "adr-writer", "reason": "shortlist winner adr-writer (fits 0.93)",
 "usage": {"input_tokens": 21597, "output_tokens": 702, "calls": 2},
 "elapsed_ms": 1567}
```

プロンプトの本文はログに書きません。書くのはハッシュと文字数だけです。`shadow` モードでは、この 1 行がすべてです。`inject` モードでは、判定に加えて次のブロックがターンに足されます。どの skill も閾値を超えなければ、何も足しません。

```
<skill_relevance>
Relevant to the current request: adr-writer. Ignore this if it does not fit what the user actually asked for.
</skill_relevance>
```

## 機外に出るもの

判定のたびに `api.typesafe.ai` へ送られるのは、プロンプトの全文、名簿にある全 skill の名前と説明の全文、そして上位 3 件に限り、**その `SKILL.md` の全文**です。非公開のプロジェクトの `.claude/skills/` にある skill の本文も含みます。会話の履歴、あなたのプロジェクトのファイル、ツールの出力は送りません。

あなた自身の `~/.claude/skills/` とプラグインの中では、skill のディレクトリが symlink ならそれをたどります。project の `.claude/skills/` は、その repository を書いた人のものです。そこでは、`SKILL.md` の実体がそのディレクトリの外にある場合、名簿に入れません。あなたの機械のほかのファイルへのリンクが、読まれたり送られたりすることはありません。project 自身の skill ファイルは送られます。自分で書いたのではない repository では、`.claude/skills/` も判定のたびに送られうるものとして扱ってください。

**プロンプトに貼り付けた secret は、そのまま送られます。** 除去する処理はありません。送信先のホストはコード内で固定し、リダイレクトは拒否するので、環境変数ひとつで key やプロンプトを別のホストへ送らせることはできません。

## 制約

- 閾値は cookbook の出発値です。ベンダーが英語の名簿と、より古いモデル版で測った値で、あなたの名簿や言語に合わせた較正はされていません。shadow モードはそのためにあります。
- 提案を注入すると何かが良くなる、という証拠を、この repo は持っていません。cookbook が報告しているのはベンダーの実験で、提案が「agent が正しくできていたターン」を壊した例も含まれています。その実験の条件は Claude Code とは違います（「動かして分かったこと」を見てください）。
- ディスクに `SKILL.md` を持たない組み込みの skill と、`--add-dir` で追加したディレクトリ配下の skill は提案できません。
- `/` で始まるプロンプトと 4000 文字を超えるプロンプトは対象外です。
- Jev の入力上限は 1 リクエスト 64k トークン、state と最も長い質問の合計で 32k トークンです。これに届きうる入力が 2 つあります。極端に長い `SKILL.md` が 3 本同時に候補へ入った場合と、名簿が 240 本の分割単位を超えて、1 段目の質問がその本数ぶんの説明全文を運ぶ場合です。送信前に大きさを見積もる処理は持ちません。API がエラーを返し、そのターンは提案なしで通り、ログの行に理由が残ります。
- TypeSafe は有料の外部 API で、判定のたびに 1〜2 リクエストを使います。0.2.0 で、skill 52〜59 本の名簿の場合（2026-09-21）、手順 1 で止まったときの入力は約 10,000 トークン、両方の手順が走ったときは 21,600〜25,300 トークンでした。現在の料金と上限は [TypeSafe の料金ページ](https://docs.typesafe.ai/models)で確認してください。変わりうる値なので、この README には書いていません。

## 自分のログを読む

`model`、`router_version`、`question_hash` のいずれかが違う行は、別の判定器が出したものなので、分けて読んでください。`inject` を有効にする価値があるかは、ログを `session` と時刻で、各セッションが実際に使った skill の自前の記録と突き合わせ、3 つの件数を読んで決めます。提案して使われた、提案したが使われなかった、使われたが提案しなかった、の 3 つです。ログが無いことは「未測定」を意味し、「提案ゼロ」ではありません。

## 関連する取り組み

- 手順の出所は [TypeSafe の skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion) です。
- [DECRUX9812/typesafe-skill-router](https://github.com/DECRUX9812/typesafe-skill-router) は、同じ cookbook を Hermes Agent 向けに実装しています。その文書から 2 つの知見を借りました。1 つの質問は 255 択が上限なので大きな名簿は分割すること、そして順位付けと候補ごとの適合判定が食い違う場合があることです。コードはコピーしていません。
- Claude Code 向けの router はほかにもあります。たとえば [skillranker](https://github.com/Dicklesworthstone/skillranker) は、ローカルの履歴と較正コマンドを持つ Rust の CLI です。[typesafe-mod](https://github.com/BeLazy167/typesafe-mod) は、同じプロンプトごとの順位付けを function hooks の mod として行うもので、上に書いた限界も同じです。1 行を足すだけで、一覧には触りません。こちらは、追加のパッケージが要らず（TypeSafe の API は必要です）、`/plugin install` で入り、プラグインと project の skill も名簿に含め、提案する前にログに残します。

## 来歴

このプロジェクトは TypeSafe AI とは無関係です。コードは、著者の指示のもとで Claude Code が書きました。オフラインのテスト（`uv run pytest -q`、ネットワーク不要）で検査しています。key とプロンプトが通る経路は、自動のレビュー（LLM の security review エージェントと、Claude Code 組み込みの code review）にかけました。その結果、HTTP リダイレクト時の key の漏えいと、信頼できない文字列がモデルの文脈に届く経路が見つかり、修正しています。第三者の人間による監査は受けていません。

## そのほか

- [運用マニュアル](skills/jev-skill-router/SKILL.md)（英語）: すべてのモード、設定、ログの欄、対象外になる条件
- [変更履歴](CHANGELOG.md)
- ライセンス: [MIT](LICENSE)
