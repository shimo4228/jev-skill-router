[English](README.md) | **日本語**

# jev-skill-router

Jev を skill の router として Claude Code に足すと、何が起きるか。そのコードとログと、外すことで終わった 1 週間の記録です。

[![tests](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml/badge.svg)](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![status: experiment concluded](https://img.shields.io/badge/status-experiment%20concluded-lightgrey.svg)](#1-週間で分かったこと)

<p align="center">
  <img src="assets/overview.ja.svg" width="760" alt="しくみを 4 つの枠で示した図。あなたがプロンプトを入力すると、Jev がどの skill が合うかを見立てる（例: adr-writer が 93%）。shadow モードでは見立てを記録するだけで、inject モードでは Claude に 1 行のヒントも渡す。その下で、Claude は変わらず全 skill を見て、最後に自分で選ぶ。">
</p>

jev-skill-router は、[TypeSafe](https://typesafe.ai) の Jev で何かを作る人のための参照実装です。Jev は文章を書かず、型の決まった質問に確率で答えるモデルです。このリポジトリの本体は Claude Code の hook で、プロンプトのたびに、インストール済みのどの skill が合うかを Jev に尋ねてログに残します。既定の shadow モードではそこまでで、inject モードにすると Claude に 1 行のヒントも渡します。そのログを、Claude Code が実際に次に何をしたかと突き合わせるスクリプトも同梱しています。Python 3.10 以上、標準ライブラリのみ、MIT ライセンス、バージョン 0.2.0 で、有料の TypeSafe API key が必要です。

私はこれを 1 週間動かし、自分の環境から外しました。539 回の提案のうち、提案した skill がその後に呼ばれたのは 28 回でした。次の一手を自分で決めるエージェントの中では、router が何を変えたのかを読み取れませんでした。その反省から作ったのが、コードがループを持ち、Jev は判定だけをする [jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline) です（[後述](#対になる実装-jev-research-pipeline)）。この README には、ほかの Jev の実装に持ち出せる部品と、全体としてはここで効かなかった理由を残しています。経緯の全体は記事「[「これ意味あるかな？」Claude Codeに入れたJevのプラグインを1週間で外すまで](https://zenn.dev/shimo4228/articles/jev-guard-blind-to-local-verify)」（[英語版](https://dev.to/shimo4228/is-there-any-point-to-this-removing-the-jev-plugins-i-added-to-claude-code-after-one-week-49eh)）に書きました。Jev を使ったほかの実験は「[著者のほかの仕事](#著者のほかの仕事)」にあります。

## 1 週間で分かったこと

**この router のようなプロンプトごとの hook は、ターンに 1 行を足せますが、skill 一覧は変えられません。** Claude Code は引き続き、全 skill の説明（description）を 1 本あたり 1,536 文字までモデルに見せ（[skills の docs](https://code.claude.com/docs/ja/skills)、2026-10-01 確認）、選ぶのはモデルです。router は、同じ説明をすでに読んでいる強いモデルに、より弱い判定器（[Opus と比べた測定](https://zenn.dev/shimo4228/articles/jev-vs-opus-skill-selection)）が出す二つ目の意見になります。移植元の TypeSafe の [skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion)（英語）は、違う条件で測られています。そのエージェントは `claude-haiku-4-5` で、見えていたのは skill 1 本あたり 60 文字に切られた索引だったので、全文を読める別の読み手が足せるものがありました。

**用意した依頼文ではうまくいき、実際のセッションではうまくいきませんでした。** 「この設計判断を ADR として記録したい」のような意図が 1 つの依頼文 6 件は、0.2.0 ですべて妥当な答えでした（2026-09-21）。そのあと 2026-09-21 から 2026-09-28 までの 1 週間、私自身の 52〜66 本の skill の名簿、`jev-1.13.0`、日本語のプロンプトで、shadow モードのまま動かしました。

| 件数 | 値 |
|---|---|
| 判定 | 1,242 |
| 提案 | 539 |
| 提案した skill が、同じセッションで 30 分以内に呼ばれた | 28（約 5%） |

外したあとで、使われなかった提案から無作為に 20 件を選んで読みました。13 件は的外れで、そのうち少なくとも 6 件は、エージェントが書いた文（サブエージェントへの依頼や、サブエージェントからの報告）に反応していました。こうした文も、あなたが打つ発言と同じ入口から hook に届きます。5 件は話題は近いものの、skill の要らないターンでした。1 件は、Claude Code が skill を呼ばずにそのファイルを直接読んでいました。Claude Code の見落としだったかもしれないのは 1 件です。スクリプトと使ったオプション、数字の全体は [evals/](evals/README.md)（英語）にあります。

**そこで止めた理由。** 28 という数には、Jev の選び方、Claude Code の次の一手の決め方、私の数え方の 3 つが混ざっています。次の一手を自分で決めるエージェントでは、1 行を足すだけでその後の動きが変わりえて、ログからはこの 3 つを分けられず、router が気づかないうちに性能を落としていないかも分かりません。手順をコードで固定したパイプラインなら、1 つの手順を Jev の判定に差し替えてもほかは変わらないので、その効果を読めます。

## 対になる実装: jev-research-pipeline

[jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline) は、この router の最初の結果を受けて作り、使い続けている Jev の実装です。毎朝のリサーチを見張るパイプラインで、同じループを素の Python が毎回同じように回し、新しい論文やリポジトリが私の問いに答える助けになるかを Jev が判定し、LLM はノートを書く部分だけを担います。Jev の判定はループの決まった位置にあるので、どの判定を下し、その先で何が変わったかを見られます。この router が Claude Code の中では一度も見せられなかったものです。自分の実装のどこに Jev を置くかを考えているなら、2 つを並べて読んでください。部品と測り方はこのリポジトリに、効いた形はあちらにあります。経緯は記事「[LLMに任せていたリサーチの判定を、判定専用モデルJevに移す](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)」（[英語版](https://dev.to/shimo4228/moving-my-research-pipelines-judgment-calls-from-an-llm-to-jev-a-judgment-only-model-4ncj)）に書きました。

## 持ち出せるもの

質問文と閾値は TypeSafe の cookbook から取っています。このリポジトリが足したのは、そのまわりの配管と、それを測る方法です。下の各行は、それぞれ自分の実装に持ち込める考え方を 1 つずつ指しています。出てくる Jev の質問の型は 2 つで、`choice` は一覧から 1 つを選び、`noul` は Yes/No の問いに確率で答えます。

| 作っているもの | 見る場所 | していること |
|---|---|---|
| Jev の API である System One の、依存なしのクライアント | [`scripts/jev_client.py`](scripts/jev_client.py) | 標準ライブラリだけで書いています。key の送り先は `api.typesafe.ai` だけで、例外はテスト用の loopback の代用サーバーです。ホストは固定し、リダイレクトは拒否します。再試行はしません。プロンプトの前で動く hook の持ち時間は数秒で、タイムアウトを再試行すれば同じ時間を二度使うからです。 |
| 長い一覧からの選択 | [`scripts/router.py`](scripts/router.py) | 2 回のリクエストで尋ねます。名前と説明に対する広い `choice` と、上位 3 件の全文に対する狭い `choice`、それに候補ごとの `noul` です。240 件を超える一覧は、API の 255 択の上限に収まるよう分割します。 |
| 版をまたいで比べられるログ | [`scripts/router.py`](scripts/router.py)（`question_hash`）、[`scripts/decision_log.py`](scripts/decision_log.py) | 各行に、モデル、router の版、質問の文言と全閾値のハッシュを残すので、質問や閾値を変えたあとの行は古い行と混ざりません。例外は候補ごとの適合度の質問で、まだハッシュに入っていません。プロンプトはハッシュと文字数だけを残します。 |
| まだ信用できない判定 | [`scripts/route.py`](scripts/route.py) | shadow モードでは、切り離した子プロセスに仕事を渡してすぐに戻るので、誰も読まない判定を待つことはありません。失敗はすべて exit 0 で終わります。 |
| エージェントが実際にしたことの確認 | [`evals/shadow_join.py`](evals/shadow_join.py) | 判定のログを Claude Code のセッション記録と突き合わせ、提案のあとに呼び出しが続いた数を数えます。使われなかった提案から、再現できる無作為抽出を作り、1 件ずつ読めるようにします。 |
| API を呼ばないテスト | [`tests/`](tests/) | Jev の答えはすべて台本どおりの代用品で、Claude Code が読む出力の形は golden ファイルで固定しています。 |

## 判定のしかた

1. **Wide（全体）。** 1 回のリクエストで、名簿（インストール済みの skill）全体を、skill 名と説明の全文に対する `choice` で順位付けします。同じリクエストで、プロンプトそのものについて `noul` の質問を 3 つ尋ねます。ユーザーのシステムに対する操作か、専門家なら文書化された手順に従うか、文章だけで足りるか、の 3 つです。3 つ目の答えは、高いほど skill が要るという向きにそろえるため反転します。3 つの平均が gate で、0.30 未満ならここで止まり、2 回目のリクエストは使いません。
2. **Narrow（絞り込み）。** 上位 3 件を、説明の全文と各 `SKILL.md` の本文全体つきで送り直します。Jev が `choice` で 1 本を選び、候補ごとに `noul` で 1 問答えます。「この skill は、頼まれた具体的なことをするか」です。この答えがその候補の適合度（fits）です。最も高い適合度が 0.30 未満なら、何も提案しません。そうでなければ Jev が選んだ 1 本を名指しします。ほかの候補の適合度のほうが高くても同じで、そのときはログの行に両方の名前が残ります。

cookbook の「説明を 60 文字に切る」索引は引き継がず、何も切り詰めません。先頭だけで順位付けすると、Claude がすでに見ているものより少ない情報で判断することになるからです。名簿は、ユーザーの skill、有効になっているプラグインの skill、セッションの作業ディレクトリから git のルートまでにあるプロジェクトの skill から組み立てます。`disable-model-invocation: true` の skill は除きます。

## 1 回の判定のログ

`off` 以外のモードでは、プロンプトごとに JSON を 1 行、プラグインのデータディレクトリにある `decisions.jsonl` へ追記します。次の行は `jev-1.13.0` に対する実際の呼び出し（`inject` モード）のものです。プロンプトは日本語で、設計判断を ADR として記録したい、という内容でした。`gate` は手順 1 の平均、`fits` は手順 2 の答えで、どちらも 0.30 を超えたので skill が名指しされました。行は一部を省略しています。

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

`shadow` モードでは、この 1 行がすべてです。`inject` モードでは、cookbook の文言そのままの下のブロックもターンに足されます。どの skill も閾値を超えなければ、何も足しません。

```
<skill_relevance>
Relevant to the current request: adr-writer. Ignore this if it does not fit what the user actually asked for.
</skill_relevance>
```

## 自分で動かす

いまもインストールして動かせます。shadow モードで始め、[evals/](evals/README.md)（英語）で自分のログを読んでから、Claude に伝えるかを決めてください。

```
/plugin marketplace add shimo4228/jev-skill-router
/plugin install jev-skill-router@jev-skill-router
```

プラグインを有効にするとき、Claude Code が 3 つの設定を尋ねます。TypeSafe の API key（[ここで作成](https://console.typesafe.ai/keys)。システムのキーチェーンに保存されます）、モード（既定は `shadow`）、任意のログの保存先です。モードの選択 UI には Claude Code 2.1.271 以上が必要です。それより古い版では、環境変数 `JEV_ROUTER` に `inject` か `off` を設定しない限り `shadow` のままです。key は環境変数 `TYPESAFE_API_KEY` で渡すことも、`~/.config/typesafe/api_key` に置くこともできます。`JEV_ROUTER=off` を設定すると、そのプロセスだけ hook が止まるので、無人で走るスクリプトを対象から外せます。プラグイン機構を使わずに配線するには、[運用マニュアル](skills/jev-skill-router/SKILL.md#install)（英語）を見てください。

**費用と待ち時間。** 判定のたびに 1〜2 リクエストを使い、名簿が 240 本を超えると 240 本ごとに 1 リクエスト増えます。0.2.0 で skill 52〜59 本の名簿の場合（2026-09-21）、gate で止まったときの入力は約 10,000 トークン、両方の手順が走ったときは 21,600〜25,300 トークンでした。現在の料金は [TypeSafe の料金ページ](https://docs.typesafe.ai/models)（英語）で確認してください。shadow モードはターンを待たせません。`inject` モードは 3 秒の上限の中で答えを待ち、実際の判定 6 回は 0.7〜1.6 秒でした。

### 外に送られるもの

判定のたびに `api.typesafe.ai` へ送られるのは、プロンプトの全文、名簿にある全 skill の名前と説明の全文、そして上位 3 件に限り、**その `SKILL.md` の本文全体**です。非公開のプロジェクトの `.claude/skills/` にある skill の本文も含みます。hook は会話の履歴もツールの出力も集めません。ただし、hook が読むプロンプトそのものが、サブエージェントの報告のようにエージェントが書いた文で、ツールの結果を引用していることがあります。**プロンプトに貼り付けた秘密情報は、そのまま送られます。** 取り除く処理はありません。

自分で書いたのではないリポジトリでは、`.claude/skills/` と、そこからリンクできるリポジトリ内のファイルも、判定のたびに送られうるものとして扱ってください。あなたが自分で置いて commit していない `.env` のようなファイルも含みます。あなた自身の `~/.claude/skills/` とプラグインの中では symlink の skill をたどりますが、プロジェクトの `SKILL.md` は、実体がそのリポジトリの中にある場合だけ読みます。プロジェクトの skill から手元のマシンのほかの場所へ張られたリンクが、読まれたり送られたりすることはありません。`TYPESAFE_BASE_URL` で key やプロンプトを別のホストへ向けることはできず、指定できるのはテストとローカルの代用サーバーのための loopback のアドレス（`localhost`、`127.0.0.1`、`::1`）だけです。`HTTPS_PROXY` のような標準のプロキシ変数は、ほかの Python の HTTPS クライアントと同じく効きます。

### 制約

- 閾値は cookbook の初期値です。ベンダーが英語の名簿と、より古いモデル版で測った値で、あなたの名簿や言語に合わせた較正はされていません。
- 提案を注入すると何かが良くなる、という証拠を、このリポジトリは持っていません。
- ディスクに `SKILL.md` を持たない組み込みの skill と、`--add-dir` で追加したディレクトリ配下の skill は提案できません。`/` で始まるプロンプトと 4,000 文字を超えるプロンプトは対象外です。
- Jev に送れる入力は、1 リクエスト最大 64k トークン、プロンプトと最も長い質問の合計で 32k トークンです（[TypeSafe の models ページ](https://docs.typesafe.ai/models)（英語）、2026-09-21 確認）。極端に長い `SKILL.md` が 3 本そろった場合や、名簿が大きい場合はこれを超えることがあり、そのターンは提案なしで通り、ログの行に理由が残ります。

すべてのモード、設定、ログの欄、対象外になる条件は[運用マニュアル](skills/jev-skill-router/SKILL.md)（英語）にあります。

## 関連する取り組み

- 手順の出所は [TypeSafe の skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion)（英語）です。
- [DECRUX9812/typesafe-skill-router](https://github.com/DECRUX9812/typesafe-skill-router) は、同じ cookbook を Hermes Agent 向けに実装しています。その文書から 2 つの知見を借りました。1 つの質問は 255 択が上限であること、そして順位付けと候補ごとの適合判定が食い違う場合があることです。コードはコピーしていません。
- Claude Code 向けの router はほかにもあります。[skillranker](https://github.com/Dicklesworthstone/skillranker) は、ローカルの履歴と較正を持つ Rust の CLI です。[typesafe-mod](https://github.com/BeLazy167/typesafe-mod) は、同じプロンプトごとの順位付けを function hooks の mod として行い、この router と同じく一覧には触りません。
- 1 行を足すのでなく、モデルに見せるもの自体を変える仕組みが、skill 自身の frontmatter（`disable-model-invocation` など）のほかに 2 つあり、このプロジェクトはどちらも使っていません。公式の設定 `skillOverrides` は、skill を「名前と説明」「名前だけ」「見せない」のどれで載せるかを決められます（[skills の docs](https://code.claude.com/docs/ja/skills)、2026-10-01 確認）。Claude Code の早期アクセス機能である function hooks（通称 mods、[設計スレッド](https://github.com/anthropics/claude-code/issues/91870)）は、モデルが見る前に一覧を書き換えられます。[jev-skill-suggestion](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/mods/productivity/jev-skill-suggestion) はこの 2 つを組み合わせ、一覧をモデルに読ませず、Jev に最大 1 本を選ばせて、その `SKILL.md` を添付します。私は試しておらず、効くかどうかは分かりません。

## 著者のほかの仕事

Jev を使った実験は、どれも記事にしています（日本語は Zenn、英語は Dev.to）。このリポジトリについての記事は 2 本です。

- 「[JevのスキルルーターをClaude Codeに足して、スキル一覧を書き換える手前で引き返した](https://zenn.dev/shimo4228/articles/jev-retrofit-limits)」（[英語版](https://dev.to/shimo4228/i-added-jevs-skill-router-to-claude-code-and-turned-back-just-before-rewriting-the-skill-listing-34in)）。作る話です。プロンプトの hook で何が変えられたか、どこで引き返したか、判定モデルを自分のハーネスに足す前に確かめる 3 つのことを書きました。
- 「[「これ意味あるかな？」Claude Codeに入れたJevのプラグインを1週間で外すまで](https://zenn.dev/shimo4228/articles/jev-guard-blind-to-local-verify)」（[英語版](https://dev.to/shimo4228/is-there-any-point-to-this-removing-the-jev-plugins-i-added-to-claude-code-after-one-week-49eh)）。動かした話です。この router と、完了を止めるプラグインの 1 週間、2 つとも外した理由、判定モデルの効果が固定したパイプラインでは読めてエージェントのループでは読めない理由を書きました。

Jev が効いた場所と、どこまで押し広げられるか:

- 「[LLMに任せていたリサーチの判定を、判定専用モデルJevに移す](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)」（[英語版](https://dev.to/shimo4228/moving-my-research-pipelines-judgment-calls-from-an-llm-to-jev-a-judgment-only-model-4ncj)）。上で紹介した対になる実装、[jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline) の経緯です。
- 「[文章を書かないモデルJevのスキル選択は、0.3秒でOpusにどこまで近づくか](https://zenn.dev/shimo4228/articles/jev-vs-opus-skill-selection)」（[英語版](https://dev.to/shimo4228/how-close-to-opus-does-jev-a-model-that-writes-no-text-get-at-skill-selection-in-03-seconds-1nfj)）。同じ 150 件の状況で、Jev と Claude Opus に skill を選ばせて比べました。Jev と Opus の一致は、Opus 同士の一致の約半分で、費用は約 560 分の 1 でした。
- 「[Jevの判断をローカルで再現するには何が要るか](https://zenn.dev/shimo4228/articles/local-decision-model-conditions)」（[英語版](https://dev.to/shimo4228/what-does-it-take-to-reproduce-jevs-decisions-locally-3i0n)）。手元で動く 4 つのモデルに同じ 150 件を解かせ、4 つとも、それぞれ別の理由で Jev の水準に届きませんでした。

エージェントの作り方、エージェントが失敗したとき誰が責任を持つか、AI 時代の著者性といった、私のほかの仕事の入口は [github.com/shimo4228](https://github.com/shimo4228) です。新しい実験は、まずそこに並びます。この router を測った名簿の大半を占める、私が書いた skill は [claude-harness](https://github.com/shimo4228/claude-harness) で公開しています。記事の一覧は [Zenn](https://zenn.dev/shimo4228)（日本語）と [Dev.to](https://dev.to/shimo4228)（英語）にあります。

## 来歴

このプロジェクトは TypeSafe AI とは無関係です。コードは、私の指示のもとで Claude Code が書きました。オフラインのテスト（`uv run pytest -q`、ネットワーク不要）で検査しています。key とプロンプトが通る経路は、自動のレビュー（LLM の security review エージェントと、Claude Code 組み込みの code review）にかけました。その結果、HTTP リダイレクト時の key の漏えいと、信頼できない文字列がモデルの文脈に届く経路が見つかり、修正しています。第三者の人間による監査は受けていません。

## 文書とライセンス

- [運用マニュアル](skills/jev-skill-router/SKILL.md)（英語）: すべてのモード、設定、ログの欄、対象外になる条件
- [Evals](evals/README.md)（英語）: ログとセッション記録を突き合わせるスクリプトと、私の 1 週間の数字
- [変更履歴](CHANGELOG.md)（英語）
- ライセンス: [MIT](LICENSE)
