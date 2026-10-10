[English](README.md) | **日本語**

# jev-skill-router

Jev を skill の router として Claude Code に足すと、何が起きるか。そのコードとログと、外すことで終わった 1 週間の記録です。

[![tests](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml/badge.svg)](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![status: experiment concluded](https://img.shields.io/badge/status-experiment%20concluded-lightgrey.svg)](#1-週間で分かったこと)

<p align="center">
  <img src="assets/overview.ja.svg" width="760" alt="しくみの図。Jev がプロンプトに合う skill を見立てる（例: adr-writer が 93%）。shadow モードは見立てを記録するだけで、inject モードは Claude にヒントも渡す。Claude は変わらず全 skill を見て、最後に自分で選ぶ。">
</p>

jev-skill-router は、[TypeSafe](https://typesafe.ai) の Jev で何かを作る人のための参照実装です。Jev は文章を書かず、型の決まった質問に確率で答えるモデルです。本体は Claude Code の hook で、プロンプトのたびに、インストール済みのどの skill が合うかを Jev に尋ねてログに残します。既定の shadow モードではそこまでで、inject モードにすると Claude に 1 行のヒントも渡します。どちらのモードでも、Claude は変わらず全 skill を見て、最後に自分で選びます。そのログを Claude Code が次にしたことと突き合わせるスクリプトも同梱しています。Python 3.10 以上、標準ライブラリのみ、MIT ライセンス、バージョン 0.2.0 で、有料の TypeSafe API キーが必要です。

私はこれを 1 週間動かし、自分の環境から外しました。539 回の提案のうち、提案した skill がその後に呼ばれたのは 28 回でした。次の一手を自分で決めるエージェントの中では、router が何を変えたのかを読み取れませんでした。その反省から作ったのが、コードがループを持ち、Jev は判定だけをする [jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline) です（[後述](#対になる実装-jev-research-pipeline)）。この README には、ほかの Jev の実装に持ち出せる部品と、全体としてはここで効かなかった理由を残しています。経緯の全体と、Jev を使ったほかの実験は「[著者のほかの仕事](#著者のほかの仕事)」にあります。

## 1 週間で分かったこと

**この router のようなプロンプトごとの hook は、ターンに 1 行を足せますが、skill 一覧は変えられません。** Claude Code は今も、全 skill の説明（description）を 1 本あたり 1,536 文字までモデルに見せ（[skills の docs](https://code.claude.com/docs/ja/skills)、2026-09-21 確認）、選ぶのはモデルです。router は、同じ説明をすでに読んでいる強いモデルに、より弱い判定器（[Opus と比べた測定](#著者のほかの仕事)）が出す二つ目の意見になります。移植元の TypeSafe の [skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion)（英語）は、違う条件で測られています。そのエージェントは `claude-haiku-4-5` で、見えていたのは skill 1 本あたり 60 文字に切られた索引だったので、全文を読める別の読み手が足せるものがありました。

**用意した依頼文ではうまくいき、実際のセッションではうまくいきませんでした。** 「この設計判断を ADR として記録したい」のような意図が 1 つの依頼文 6 件は、0.2.0 ですべて妥当な答えでした（2026-09-21）。そのあと 2026-09-21〜09-28 の 1 週間、私自身の 52〜66 本の skill の名簿、`jev-1.13.0`、日本語のプロンプトで、shadow モードのまま動かしました。

| 件数 | 値 |
|---|---|
| 判定 | 1,242 |
| 提案 | 539 |
| 提案した skill が、同じセッションで 30 分以内に呼ばれた | 28（約 5%） |

外したあと、使われなかった提案を無作為に 20 件読みました。13 件は的外れで、そのうち少なくとも 6 件は、エージェントが書いた文（サブエージェントへの依頼や、その報告）に反応していました。こうした文も、あなたが打つ発言と同じ入口から hook に届きます。5 件は話題は近いものの、skill の要らないターンでした。1 件は Claude Code が skill を呼ばずにそのファイルを直接読んでおり、1 件は Claude Code の見落としだったかもしれません。スクリプト、オプション、数字の全体は [evals/](evals/README.md)（英語）にあります。

**そこで止めた理由。** 28 という数には、Jev の選び方、Claude Code の次の一手の決め方、私の数え方の 3 つが混ざっています。次の一手を自分で決めるエージェントでは、1 行を足すだけでその後の動きが変わりえて、ログからはこの 3 つを分けられず、router が性能を落としていても、それに気づけません。手順をコードで固定したパイプラインなら、1 つの手順を Jev の判定に差し替えてもほかは変わらないので、その効果を読めます。

## 対になる実装: jev-research-pipeline

[jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline) は、この router の最初の結果を受けて作り、使い続けている Jev の実装です。毎朝のリサーチを見張るパイプラインで、素の Python が同じループを毎回回し、新しい論文やリポジトリが私の問いに答える助けになるかを Jev が判定し、LLM はノートを書く部分だけを担います。自分の実装には、部品と測り方をこのリポジトリから、効いた形をあちらから持ち出してください。経緯は[記事](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)（[英語版](https://dev.to/shimo4228/moving-my-research-pipelines-judgment-calls-from-an-llm-to-jev-a-judgment-only-model-4ncj)）に書きました。

## 持ち出せるもの

質問文と閾値は TypeSafe の cookbook から取り、このリポジトリはそのまわりの配管と測り方を足しました。Jev の質問の型は 2 つで、`choice` は一覧から 1 つを選び、`noul` は Yes/No の問いに確率で答えます。

| 作っているもの | 見る場所 | していること |
|---|---|---|
| Jev の API である System One の、依存なしのクライアント | [`scripts/jev_client.py`](scripts/jev_client.py) | ホストは `api.typesafe.ai`（テストでは loopback の代用サーバー）に固定し、リダイレクトは拒否するので、`TYPESAFE_BASE_URL` やリダイレクトで API キーが別のホストへ送られることはありません（[固定が及ばない範囲](#外に送られるもの)）。再試行はしません。プロンプトの前で動く hook の持ち時間は数秒で、タイムアウトを再試行すれば同じ時間を二度使うからです。 |
| 長い一覧からの選択 | [`scripts/router.py`](scripts/router.py) | 2 回のリクエストで、広く尋ねてから絞り込みます（[判定のしかた](#判定のしかた)）。240 件を超える一覧は、API の 255 択の上限に収まるよう分割します。 |
| 版をまたいで比べられるログ | [`scripts/router.py`](scripts/router.py)（`question_hash`）、[`scripts/decision_log.py`](scripts/decision_log.py) | 各行に、モデル、router の版、順位付けと gate の質問の文言と全閾値のハッシュを残すので、それらを変えたあとの行は古い行と混ざりません。候補ごとの適合度の質問は、まだハッシュの外です。プロンプトはハッシュと文字数だけを残します。 |
| まだ信用できない判定 | [`scripts/route.py`](scripts/route.py) | shadow モードでは仕事を切り離した子プロセスに渡してすぐに戻るので、誰も読まない判定を待ちません。失敗はすべて exit 0 で終わります。 |
| エージェントが実際にしたことの確認 | [`evals/shadow_join.py`](evals/shadow_join.py) | 判定のログを Claude Code のセッション記録と突き合わせ、提案のあとに呼び出しが続いた数を数え、使われなかった提案から、手で読むための再現できる無作為抽出を作ります。 |
| API を呼ばないテスト | [`tests/`](tests/) | Jev の答えはすべて台本どおりの代用品で、Claude Code が読む出力の形は golden ファイルで固定しています。 |

## 判定のしかた

1. **Wide（全体）。** 1 回のリクエストで、名簿（インストール済みの skill）全体を、skill 名と説明の全文に対する `choice` で順位付けします。同じリクエストで、プロンプトそのものについて `noul` の質問を 3 つ尋ねます。ユーザーのシステムに対する操作か、専門家なら文書化された手順に従うか、文章だけで足りるか、の 3 つです。3 つ目の答えは、高いほど skill が要るという向きにそろえるため反転します。3 つの平均が gate で、0.30 未満ならここで止まり、2 回目のリクエストは使いません。
2. **Narrow（絞り込み）。** 上位 3 件を、説明の全文と各 `SKILL.md` の本文全体つきで送り直します。Jev が `choice` で 1 本を選び、候補ごとに `noul` で「この skill は、頼まれた具体的なことをするか」に答えます。この答えがその候補の適合度（fits）です。最も高い適合度が 0.30 未満なら、何も提案しません。そうでなければ、ほかの候補の適合度のほうが高くても Jev が選んだ 1 本を名指しし、ログの行に両方の名前を残します。

cookbook の「説明を 60 文字に切る」索引は引き継がず、何も切りません。先頭だけで順位付けすると、Claude がすでに見ているものより少ない情報で判断することになるからです。名簿は、ユーザーの skill、有効になっているプラグインの skill、セッションの作業ディレクトリから git のルートまでにあるプロジェクトの skill から組み立てます。`disable-model-invocation: true` の skill は除きます。

## 1 回の判定のログ

`off` 以外のモードでは、プロンプトごとに JSON を 1 行、プラグインのデータディレクトリにある `decisions.jsonl` へ追記します。次の行（一部省略）は `jev-1.13.0` に対する `inject` モードでの実際の呼び出しで、プロンプトは日本語で設計判断を ADR として記録したい、という内容でした。`gate` は手順 1 の平均、`fits` は手順 2 の答えで、どちらも 0.30 を超えたので skill が名指しされました。

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

`shadow` モードでは、この 1 行がすべてです。`inject` モードでは、cookbook の文言そのままの下のブロックもターンに足され、どの skill も閾値を超えなければ何も足しません。

```
<skill_relevance>
Relevant to the current request: adr-writer. Ignore this if it does not fit what the user actually asked for.
</skill_relevance>
```

## 自分で動かす

shadow モードで始め、自分のログを読んでから、Claude に伝えるかを決めてください。clone した場所で `python3 evals/shadow_join.py`（[evals/](evals/README.md)、英語）を実行すると、どこにも送らずに手元で、提案のあとに呼び出しが続いた数を出します。

```
/plugin marketplace add shimo4228/jev-skill-router
/plugin install jev-skill-router@jev-skill-router
```

プラグインを有効にするとき、Claude Code が 3 つの設定を尋ねます。TypeSafe の API キー（[ここで作成](https://console.typesafe.ai/keys)。システムのキーチェーンに保存されます）、モード（既定は `shadow`）、任意のログの保存先です。モードの選択 UI には Claude Code 2.1.271 以上が必要です。それより古い版では、環境変数 `JEV_ROUTER` に `inject` か `off` を設定しない限り `shadow` のままです。API キーは環境変数 `TYPESAFE_API_KEY` で渡すことも、`~/.config/typesafe/api_key` に置くこともできます。`JEV_ROUTER=off` でそのプロセスだけ hook が止まるので、無人で走るスクリプトを外せます。プラグイン機構を使わない配線は[運用マニュアル](skills/jev-skill-router/SKILL.md#install)（英語）にあります。

**費用と待ち時間。** 判定のたびに 1〜2 リクエストを使い、名簿が 240 本を超えると 240 本ごとに 1 リクエスト増えます。0.2.0 で skill 52〜59 本の名簿の場合（2026-09-21）、gate で止まったときの入力は約 10,000 トークン、両方の手順が走ったときは 21,600〜25,300 トークンでした。現在の料金は [TypeSafe の料金ページ](https://docs.typesafe.ai/models)（英語）にあります。`inject` モードは 3 秒の上限の中で答えを待ち、実際の判定 6 回は 0.7〜1.6 秒でした。

### 外に送られるもの

判定のたびに `api.typesafe.ai` へ送られるのは、プロンプトの全文、名簿にある全 skill の名前と説明の全文、そして上位 3 件に限り、**その `SKILL.md` の本文全体**です。非公開のプロジェクトの `.claude/skills/` にある skill の本文も含みます。hook は会話の履歴もツールの出力も集めませんが、hook が読むプロンプト自体が、ツールの結果を引用したサブエージェントの報告のような、エージェントが書いた文であることがあります。**プロンプトに貼り付けた秘密情報は、そのまま送られます。** 取り除く処理はありません。

自分で書いたのではないリポジトリでは、`.claude/skills/` の `SKILL.md` が symlink になっていることがあり、hook はそのリポジトリ内のどのファイルへでもそれをたどります。`.claude/skills/` と、そこから symlink で指せるリポジトリ内のファイルも、判定のたびに送られうるものとして扱ってください。あなたが自分で置いて commit していない `.env` のようなファイルも含みます。ホストの固定は、hook の環境を握る相手（`HTTPS_PROXY` と `SSL_CERT_FILE`、`PYTHONPATH` など）には効きません。環境を信頼できないプロジェクト（その direnv など）では、プラグインを無効にしてください。`JEV_ROUTER=off` 自体が、その環境に上書きされうる環境変数だからです。symlink の扱いの詳細と、固定が及ばないほかの範囲は[運用マニュアル](skills/jev-skill-router/SKILL.md#what-leaves-the-machine)（英語）にあります。

### 制約

- 閾値は cookbook の初期値で、ベンダーが英語の名簿とより古いモデル版で測った値です。あなたの名簿や言語に合わせた較正はされていません。
- 提案を注入すると何かが良くなる、という証拠を、このリポジトリは持っていません。
- ディスクに `SKILL.md` を持たない組み込みの skill と、`--add-dir` で追加したディレクトリ配下の skill は提案できません。`/` で始まるプロンプトと 4,000 文字を超えるプロンプトは対象外です。
- Jev に送れる入力は、1 リクエスト最大 64k トークン、プロンプトと最も長い質問の合計で 32k トークンです（[TypeSafe の models ページ](https://docs.typesafe.ai/models)（英語）、2026-09-21 確認）。極端に長い `SKILL.md` が 3 本そろった場合や、名簿が大きい場合はこれを超えることがあり、そのターンは提案なしで通り、ログの行に理由が残ります。

## 関連する取り組み

- [DECRUX9812/typesafe-skill-router](https://github.com/DECRUX9812/typesafe-skill-router) は、同じ cookbook を Hermes Agent 向けに実装しています。その文書から 2 つの知見を借りました。1 つの質問は 255 択が上限であること、順位付けと候補ごとの適合判定が食い違う場合があることです。コードはコピーしていません。
- skill を外すことと skill 自身の frontmatter（`disable-model-invocation` など）のほかに、1 行を足すのでなくモデルに見せるもの自体を変える仕組みが 2 つあり、このプロジェクトはどちらも使っていません。公式の設定 `skillOverrides` は、skill を「名前と説明」「名前だけ」「見せない」のどれで載せるかを決められます（skills の docs、2026-09-21 確認）。Claude Code の function hooks（通称 mods、[設計スレッド](https://github.com/anthropics/claude-code/issues/91870)（英語））は、モデルが見る前に一覧を書き換えられます。[jev-skill-suggestion](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/mods/productivity/jev-skill-suggestion) はこの 2 つを組み合わせ、一覧をモデルに読ませず、Jev に最大 1 本を選ばせて、その `SKILL.md` を添付します。私は試していません。
- Claude Code 向けの router はほかにもあります。[skillranker](https://github.com/Dicklesworthstone/skillranker) は、ローカルの履歴と較正を持つ Rust の CLI です。[typesafe-mod](https://github.com/BeLazy167/typesafe-mod) は、同じプロンプトごとの順位付けを function hooks の mod として行い、この router と同じく一覧には触りません。

## 来歴

このプロジェクトは TypeSafe AI とは無関係です。コードは、私の指示のもとで Claude Code が書きました。オフラインのテスト（`uv run pytest -q`、ネットワーク不要）で検査しています。API キーとプロンプトが通る経路は、LLM の security review エージェントと Claude Code 組み込みの code review にかけました。その結果、HTTP リダイレクト時の API キーの漏えいと、信頼できない文字列がモデルの文脈に届く経路が見つかり、修正しています。第三者の人間による監査は受けていません。

## 著者のほかの仕事

このリポジトリについての記事:

- **[JevのスキルルーターをClaude Codeに足して、スキル一覧を書き換える手前で引き返した](https://zenn.dev/shimo4228/articles/jev-retrofit-limits)**（[English](https://dev.to/shimo4228/i-added-jevs-skill-router-to-claude-code-and-turned-back-just-before-rewriting-the-skill-listing-34in)）: 作る話です。プロンプトの hook で何が変えられたか、どこで引き返したか、判定モデルをハーネスに足す前に確かめる 3 つのことを書きました。
- **[「これ意味あるかな？」Claude Codeに入れたJevのプラグインを1週間で外すまで](https://zenn.dev/shimo4228/articles/jev-guard-blind-to-local-verify)**（[English](https://dev.to/shimo4228/is-there-any-point-to-this-removing-the-jev-plugins-i-added-to-claude-code-after-one-week-49eh)）: 動かした話です。この router と、完了を止めるプラグインの 1 週間と、2 つとも外した理由を書きました。

Jev をどこまで押し広げられるか:

- **[文章を書かないモデルJevのスキル選択は、0.3秒でOpusにどこまで近づくか](https://zenn.dev/shimo4228/articles/jev-vs-opus-skill-selection)**（[English](https://dev.to/shimo4228/how-close-to-opus-does-jev-a-model-that-writes-no-text-get-at-skill-selection-in-03-seconds-1nfj)）: 同じ 150 件の状況で、Jev と Claude Opus の一致は Opus 同士の一致の約半分で、費用は約 560 分の 1 でした。
- **[Jevの判断をローカルで再現するには何が要るか](https://zenn.dev/shimo4228/articles/local-decision-model-conditions)**（[English](https://dev.to/shimo4228/what-does-it-take-to-reproduce-jevs-decisions-locally-3i0n)）: 手元で動く 4 つのモデルに同じ 150 件を解かせると、どれもそれぞれ別の理由で Jev の判断を再現できませんでした。

関連するリポジトリ:

- **[jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline)**: [上で紹介した](#対になる実装-jev-research-pipeline)対になる実装で、Jev が効いた場所です。
- **[claude-harness](https://github.com/shimo4228/claude-harness)**: 私が毎日使う Claude Code のハーネスで、skill・subagent・rule・hook を 1 つずつ持ち出せます。この router を測った名簿の大半を占める、私が書いた skill もここにあります。
- **[shimo4228（ハブ）](https://github.com/shimo4228/shimo4228)**: 私の研究プロジェクトとその DOI（エージェントの作り方、エージェントが失敗したとき誰が責任を持つか、AI 時代の著者性）と、Claude Code と TypeSafe Jev のためのツールがあります。新しい実験は、まずそこに並びます。

記事の一覧は [Zenn](https://zenn.dev/shimo4228)（日本語）と [Dev.to](https://dev.to/shimo4228)（英語）にあります。

## 文書とライセンス

- [運用マニュアル](skills/jev-skill-router/SKILL.md)（英語）: すべてのモード、設定、ログの欄、対象外になる条件
- [Evals](evals/README.md)（英語）: 突き合わせのスクリプトと、私の 1 週間の数字
- [変更履歴](CHANGELOG.md)（英語）
- ライセンス: [MIT](LICENSE)

<details>
<summary>ツールと AI アシスタント向けの資料</summary>

jev-skill-router は、TypeSafe の Jev で何かを作る人のための参照実装です。Claude Code のプラグインで、その `UserPromptSubmit` の hook がプロンプトのたびに、インストール済みのどの skill が合うかを Jev に尋ね、答えをログに残すか（shadow モード）、Claude にヒントとしても渡します（inject モード）。

これがあるのは、次の一手を自分で決めるエージェントの中で、こうした router が何を変えるかを記録するためです。著者は 1 週間で外しました。効いた形は [jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline) です。

ライセンスは MIT、Python 3.10 以上、標準ライブラリのみ、バージョンは 0.2.0 です。実験は終わり、参照実装として残しています。実行するコード・テスト・運用マニュアルは著者のハーネスから一方向に同期され、Python のパッケージ設定（`pyproject.toml`、`uv.lock`）と LICENSE も同じ同期で届きます。この README、プラグインのマニフェスト、hook の配線はリポジトリ側のものです。必要なのは Claude Code（設定画面でモードを選ぶには 2.1.271 以上）と、有料の TypeSafe API キーです。TypeSafe AI とは無関係で、第三者の人間による監査は受けていません。

例: shadow モードで動かした 1 週間（2026-09-21〜09-28）で、539 回の提案のうち、提案した skill が呼ばれたのは 28 回（約 5%）でした。

参照先は、[運用マニュアル](skills/jev-skill-router/SKILL.md)（英語）、[evals/](evals/README.md)（英語）、著者のハブ [shimo4228/shimo4228](https://github.com/shimo4228/shimo4228) です。

</details>
