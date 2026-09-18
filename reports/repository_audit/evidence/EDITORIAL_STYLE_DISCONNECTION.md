# Evidence — `docs/NEVER_BLANK_EDITORIAL_STYLE.md` stopped executing at `2466611`

Supporting evidence for finding **F-03** and for §2.1 of `docs/repository-audit/REPOSITORY_AUDIT.md`.

This file exists because the audit's most consequential historical claim — that a product
contract silently stopped reaching a prompt, and that no test noticed — must be checkable
from the audited repository itself, not from a document on an unmerged branch. Everything
below is reproduced from this repository's own history with the commands shown, and every
command can be re-run at the audited commit `4a121b2`.

---

## 1. The commit

```
$ git log -1 --format='%H %cI%n%s' 2466611
24666114958285901afa2788ea9e3a51e9dba6b8 2026-07-03T19:57:59-06:00
Wire Editorial Engine V2 into the live publish path
```

The commit message is long and explicit about what it changes: the flat generation in
`publish_packages.py` is replaced by `src/editorial/pipeline.py`, Threads moves from a
five-post sequence to one post, and hashtags are "intentionally dropped — the new spec does
not define them". It does not mention `docs/NEVER_BLANK_EDITORIAL_STYLE.md` anywhere. That
matters: every other semantic change in that commit was declared, and this one was not.

## 2. What the document reached before the commit

At `2466611^`, `scripts/research/publish_packages.py` opened the document and pasted its
whole text into the blog-article system prompt.

```
$ git grep -n 'NEVER_BLANK_EDITORIAL_STYLE\|_load_editorial_style' 2466611^ -- scripts/research/publish_packages.py
2466611^:scripts/research/publish_packages.py:6:Voice system: docs/NEVER_BLANK_EDITORIAL_STYLE.md + config/prompts/*.yaml
2466611^:scripts/research/publish_packages.py:43:EDITORIAL_PATH = Path("docs/NEVER_BLANK_EDITORIAL_STYLE.md")
2466611^:scripts/research/publish_packages.py:57:def _load_editorial_style() -> str:
2466611^:scripts/research/publish_packages.py:107:    editorial = _load_editorial_style()
2466611^:scripts/research/publish_packages.py:111:EDITORIAL STYLE (mandatory — follow exactly):
```

The loader, verbatim (`2466611^:scripts/research/publish_packages.py:42-60`):

```python
EDITORIAL_PATH = Path("docs/NEVER_BLANK_EDITORIAL_STYLE.md")

...

# ── Editorial style loader ─────────────────────────────────────────────────────

def _load_editorial_style() -> str:
    if EDITORIAL_PATH.exists():
        return EDITORIAL_PATH.read_text(encoding="utf-8")
    return ""
```

And the model message it fed (`2466611^:scripts/research/publish_packages.py:106-115`):

```python
def _generate_blog_article(signal: dict, package: dict) -> str:
    editorial = _load_editorial_style()

    system = f"""You write articles for Never Blank, a content practice for founders.

EDITORIAL STYLE (mandatory — follow exactly):
{editorial}

STRUCTURE (must follow in order):
1. Signal — what happened, with the core fact
...
```

This is the complete chain the audit requires — `file → loader → runtime value → prompt
composition → production model message` — and it is the only place in the repository's
history where a Markdown product contract has ever had one.

## 3. What the commit removed

```
$ git show 2466611 -- scripts/research/publish_packages.py
```

The relevant deletions, quoted from that diff:

```diff
-PACKAGES_DIR   = Path("reports/content_packages")
-PROMPTS_DIR    = Path("config/prompts")
-EDITORIAL_PATH = Path("docs/NEVER_BLANK_EDITORIAL_STYLE.md")
+PACKAGES_DIR = Path("reports/content_packages")
```

```diff
-# ── Editorial style loader ─────────────────────────────────────────────────────
-
-def _load_editorial_style() -> str:
-    if EDITORIAL_PATH.exists():
-        return EDITORIAL_PATH.read_text(encoding="utf-8")
-    return ""
```

```diff
-def _generate_blog_article(signal: dict, package: dict) -> str:
-    editorial = _load_editorial_style()
-
-    system = f"""You write articles for Never Blank, a content practice for founders.
-
-EDITORIAL STYLE (mandatory — follow exactly):
-{editorial}
```

No replacement reader was added, in that commit or since.

## 4. Why no test failed — stated precisely

The audit's claim is **not** that a CI run was observed and seen to be green; no workflow-run
record was queried anywhere in this audit. The claim is the stronger and checkable one that
**no test could have failed for this reason, because no test referenced the document or its
loader.** At the parent commit, the only two references in the entire `src/`, `scripts/` and
`tests/` trees were the two lines inside `publish_packages.py` that the commit itself deleted:

```
$ git grep -n 'NEVER_BLANK_EDITORIAL_STYLE' 2466611^ -- src scripts tests
2466611^:scripts/research/publish_packages.py:6:Voice system: docs/NEVER_BLANK_EDITORIAL_STYLE.md + config/prompts/*.yaml
2466611^:scripts/research/publish_packages.py:43:EDITORIAL_PATH = Path("docs/NEVER_BLANK_EDITORIAL_STYLE.md")

$ git grep -n 'EDITORIAL_STYLE\|_load_editorial_style' 2466611^ -- tests/
(no output)
```

A deletion that nothing asserts on cannot turn any test red. That is the failure mode, and
it is why guardrail **G-2** asserts on the model message rather than on the file's existence.

## 5. The state at the audited commit

```
$ git grep -n 'NEVER_BLANK_EDITORIAL_STYLE\|EDITORIAL_STYLE\|_load_editorial_style' 4a121b2 -- src scripts tests
(no output)
```

`docs/NEVER_BLANK_EDITORIAL_STYLE.md` is still tracked, and `docs/SYSTEM_MAP.md:4` still
presents it as *the* editorial style. Nothing opens it.

---

*Read-only. This file records evidence; it proposes no repair and makes no product decision.*
