"""Shared claim-kind vocabulary for write_claims / workflows.

Keep in sync with CLAIM_KINDS in:
  .claude/skills/crux/workflows/crux-propose.js
  .claude/skills/crux/workflows/crux-critique.js
  .claude/skills/crux/workflows/crux-revise.js
"""

from __future__ import annotations

CLAIM_KINDS: tuple[str, ...] = (
    'finding',
    'mechanism',
    'method',
    'limitation',
    'assumption',
    'problem',
    'other',
)

ALLOWED_KINDS = frozenset(CLAIM_KINDS)
