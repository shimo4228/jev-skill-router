# Golden output

<!-- origin: shimo4228 -->

`inject-envelope.json` freezes the **whole shape** of what `route.py` writes to
stdout in `inject` mode. Claude Code parses that envelope; a partial assertion
("contains `<skill_relevance>`") stays green while the key names or the wording
drift underneath it.

The wording inside `additionalContext` is a measured input, verbatim from the
TypeSafe cookbook — the published error rates were obtained with that exact
sentence.

## Update rule

Updating this file is legitimate **only when the task at hand declares that it
changes the injected output**. A red golden from an unrelated change is the
detector working: report it as an incident, do not repaint it.

## Regenerate

```python
import json, sys

sys.path.insert(0, ".")
from scripts import router

print(
    json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": router.suggestion_block("tdd"),
            }
        },
        ensure_ascii=False,
        indent=2,
    )
)
```

Run that from the skill directory and redirect into
`tests/golden/inject-envelope.json`.

It lives here rather than in the harness's own `tests/golden/` because this
sub-project is published standalone: the harness golden layer is exercised by
`tests/golden-*.bats`, which would not travel with the skill.
