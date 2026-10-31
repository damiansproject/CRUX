# Agent notes

CRUX is a suite of skills for Claude Code, Codex and Cursor. The skills live in
this folder's `.claude/skills/<name>/SKILL.md`, installed as the README's
quickstart describes:

| Skill | Use |
| --- | --- |
| `crux` | The hypothesis loop (`/crux`): seeds, propose, critique, revise, tournament |
| `claim-extractor` | Sources → claim bank |
| `crux-report` | PDF reports and the review paper |

When the user asks for `/crux` or any CRUX stage, read the matching `SKILL.md`
in full and follow it from this folder, with absolute run paths.

Codex and Cursor have no Workflow tool. Wherever a skill names a slash workflow
(`/crux-…`), follow that skill's **No Workflow tool** route as written there: fresh
subagents with the same prompts and shards, then the scripts that route names
(the tournament judge is one judge subagent per batch, then `apply_elo.py`). Model
names in the skills are Claude Code's; each skill's "Model and effort" section
says what to use instead.

Before launching workers, create `<run>/shards/.scratch/`, where workers write
their temporary payloads: shell writes do not create missing folders. Tell each
worker to run the commands its prompt names as written, with no log redirects
or check scripts of its own.
