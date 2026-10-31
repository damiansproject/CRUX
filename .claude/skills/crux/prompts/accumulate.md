# Accumulating across rounds

The deepen loop keeps one hypothesis across rounds, so evidence accumulates.
What does **not** accumulate by default is what the loop has ruled *out*. A
later round therefore re-proposes a branch an earlier round already killed,
and the loop reads as busy while circling.

Three artifacts fix that, and `branch_tree.py` enforces the one rule that
makes them safe.

## The three artifacts

**Verified-results ledger.** Every computation main ran between rounds that
came back checked, banked as claims with `origin: computation-ledger`. This
is what the next round builds *on*. Each page states the setup once and then
one result per page, with the method that produced it (exact arithmetic,
mod-p at a stated prime, N digits of precision) — not "verified", but
verified *how*.

**Closed-branches ledger.** One page per dead end, with three mandatory
fields:

| field | what it holds |
| --- | --- |
| the why | the proof or computation, as prose, before the labelled fields |
| `EVIDENCE:` | proved / machine-verified / structural / empirical |
| `SCOPE BOUNDARY:` | exactly what the closure does **not** exclude |

**Branch tree.** Nodes, statuses, and the frontier the next round consumes.
Built and checked with `branch_tree.py`.

## Scope discipline, which is the whole point

A closure is a wall **only inside the scope it states**. Write "the route is
dead" and you delete live branches by accident; write "closes only shape Y at
n = 3, and only with the collision placed at z = 0" and the sentence names
its own siblings, which become the next round's frontier.

This is not hypothetical caution. In the run this was built from, three
over-scoped negatives each closed a branch that was in fact open, and one of
them — "collision at z = 0" — turned out to be an artifact of the closure's
own phrasing; the goal never required it. The boundary line of a dead end is
the most productive line in the ledger.

So every closed node must **either** name the siblings its boundary implies,
**or** be explicitly marked exhausted with a reason:

```
python branch_tree.py close --tree tree.json --node N05b \
  --why "ideal-passing coordinates cannot equalize at any collision pair" \
  --evidence structural \
  --scope "closes only {k^3, single feedback, collision at z=0, c in {t,h,f}}" \
  --spawn 'N10:collision at UNEQUAL z; the goal never requires z=0'
```

`check` fails on a closure missing a field or leaving its boundary unmined.
Run it before starting a round; the frontier it prints is the round's agenda,
cheapest first:

```
python branch_tree.py check    --tree tree.json --ledger closed_branches.json
python branch_tree.py frontier --tree tree.json
```

## Round-boundary verification

Each round advances the frontier **and** emits new unverified artifacts. In
the run this came from, a single round produced both a genuine advance and a
numeric artifact that was wrong, plus a dead-branch declaration that was
false. Both were caught in minutes by executing the draft's own artifacts
outside the loop.

So between rounds, main does three things in order:

1. **Execute what the draft asserted.** If it names a map, a pair, a bound —
   run it. A draft's own kill experiment is the cheapest thing on the table.
2. **Control the verdict before trusting it.** An all-green result with no
   known-bad input proves nothing, and an all-red result with no known-good
   input is indistinguishable from a sign error. Both directions have burned
   this loop. Supply both controls, then read the verdict.
3. **Bank the outcome**, into the verified ledger if it held and the
   closed-branches ledger if it did not — with the scope line written at the
   same time, while the reason is still fresh.

Relayed verdicts lose their qualifiers. If a subagent reports a branch dead,
the ledger records what was *checked*, not what was concluded.

## Feeding it back

Ledger claims go into the slot like any other claims (`add_seed_claims.py`),
so the next round's workers read them as evidence and as walls. Tell workers
plainly: do not respawn a branch inside a closure's stated scope; probing a
stated boundary is exactly what a `conjecture` hop is for.

**Keep the notes clean.** Notes that name the answer's ingredients make the
next round's success unreadable — you cannot tell whether the loop found
something or was told it. If a round is meant to measure what the loop can
reach on its own, the notes name the walls and nothing else, and anything
main happens to know stays out of the pack and out of the run directory.

## Stopping

Beyond the deepen loop's own stop conditions, stop when `frontier` is empty —
every branch closed and every boundary mined. A frontier that keeps growing
is not failure: closures spawning siblings is the loop working.
