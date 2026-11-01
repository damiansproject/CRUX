<img width="899" height="419" alt="9-isometric-crux" src="https://github.com/user-attachments/assets/26307dce-7d1e-4438-b47a-d89ed413cf0c" />
# CRUX

Crux Discovery is an open-source multi-agent AI research platform. Where every claim points back to its sentence.

It runs a hypothesis loop over a bank of claims extracted from a provided set of paper.

Groups papers around some research goal and proposes a hypothesis based on the papers. It then runs critiques and ranks them based on what is most promising/novel and is weighted by evidence.
Extracted claims come from [CRUX Claims](https://github.com/damiansproject/CRUX-CLAIMS)


## Works with

| Host        | Status      |
|-------------|-------------|
| [Claude Code](https://claude.com/claude-code) | Supported |
| Codex       | Supported  |
| Cursor | Supported |


## Quickstart

Paste this into your agent to install the whole CRUX suite:

```text
Install the CRUX suite. Run `git clone https://github.com/damiansproject/CRUX.git`, then `cd CRUX`, and clone each skill repo from https://github.com/damiansproject into `.claude/skills/` under its skill name: CRUX-CLAIMS as `claim-extractor`, CRUX-REPORTS as `crux-report`. Keep those names and install the skills nowhere else. If you're in Claude Code, also run `claude plugin marketplace add damiansproject/CRUX-VIEWER` and `claude plugin install crux-viewer@crux-viewer-local --scope local`, and accept the prompt to enable this folder's `crux` plugin. If you're in another agent, clone CRUX-VIEWER next to CRUX and follow its SKILL.md. Optional: `pip install docling` for PDFs, `pip install pypdf==6.14.2` and uv for the viewer. You can read the main skill at https://github.com/damiansproject/CRUX/blob/main/.claude/skills/crux/SKILL.md. Then start a new session in the CRUX folder and use /crux.
```

## Requirements

- Python 3.12+ — CRUX's own scripts use the standard library only

## Install

For one project, clone and open the folder in Claude Code:

```bash
git clone https://github.com/damiansproject/CRUX.git
```

To add it to another project as a plugin:

```bash
claude plugin marketplace add path/to/CRUX --scope project
claude plugin install crux@crux-local --scope project -y
```

## Usage

Needs a run with `claims.jsonl` — run `/claim-extractor` from CRUX Claims
first. Then:

```
/crux
```

Runs write under `.crux_run/`:

- `proposals.jsonl`, `critiques.jsonl` — the intermediate rounds
- `hypotheses.jsonl` — the finals, every hop tied to a claim
- `tournament/elo.jsonl` — the ranking

## Deepen

Optional feature: name hypotheses to deepen. Each round fills that hypothesis's
evidence gaps and revises it again.

## The CRUX suite

| Repo | Stage |
|------|-------|
| [CRUX Claims](https://github.com/damiansproject/CRUX-CLAIMS) | Sources → atomic claim bank |
| **CRUX** (this repo) | Hypothesis loop: propose → critique → revise → tournament |
| [CRUX Reports](https://github.com/damiansproject/CRUX-REPORTS) | PDF reports of a run |
| [CRUX Viewer](https://github.com/damiansproject/CRUX-VIEWER) | Claim quotes highlighted on the original sources |

## Acknowledgements

- Gottweis, J. and Natarajan, V. Accelerating scientific breakthroughs with an AI co-scientist (Google co-scientist). Google Research blog, 2025.
- Gottweis, J., Weng, W.-H., Daryin, A., et al. Towards an AI co-scientist. arXiv:2502.18864, 2025.
- Lu, C., Lu, C., Lange, R. T., Foerster, J., Clune, J., and Ha, D. The AI Scientist: Towards fully automated open-ended scientific discovery. arXiv:2408.06292, 2024.
