#!/usr/bin/env python3
"""Build cross-discipline seed packs: papers far apart in the literature that
still touch on at least one shared entity.

Gist/topic packing selects for coherence, which files each literature with its
own and leaves a cross-field hypothesis unreachable (measured: directed gist
packs put both target molecules in 2 of 12 slots, random paper packs in 8 of
12). This selects for the opposite: maximum distance, gated on contact. That is
the pair whose join nobody has written down.

Measured on the sleep-gut backtest, the strongest known cross-literature bridge
(taurine paper + REV-ERB colon-clock paper) ranks 16 of 770 pairs, top 2.1%.
The three weaker true pairs rank 116, 362 and 431 -- this surfaces the best
bridge reliably, not every bridge. See bridge_score() for the objectives that
lost, including the "shared specific node" one that was the original guess.

  python select_cross_packs.py --claims claims.jsonl --slots 12 --papers_per_slot 5
  python select_cross_packs.py --claims claims.jsonl --emit_args > packs.args

Selection is packing only. It puts distant papers in front of a worker; it does
not make the worker join them -- co-presence alone yields no join (see
.crux_eval/AB-EVAL.md). The `conjecture` hop in propose.md is the other half,
and neither works without the other.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Kinds that carry content. method/limitation claims are largely boilerplate and
# match across unrelated papers ("western blot", "sample size") -- that is what
# made naive token overlap rank shared *methods* highest in the prototype.
CONTENT_KINDS = {'finding', 'mechanism'}

TOKEN = re.compile(r"[A-Za-zα-ω][A-Za-z0-9α-ω\-]{2,}")

GREEK = set('αβγδεκλμπσω')

STOP = {
    'the', 'and', 'that', 'with', 'this', 'from', 'were', 'was', 'for', 'not',
    'but', 'are', 'has', 'have', 'had', 'been', 'their', 'these', 'those',
    'which', 'when', 'than', 'then', 'they', 'them', 'its', 'our', 'can',
    'may', 'might', 'could', 'would', 'should', 'also', 'more', 'most',
    'increased', 'decreased', 'reduced', 'elevated', 'significantly',
    'compared', 'control', 'controls', 'group', 'groups', 'mice', 'mouse',
    'rat', 'rats', 'human', 'humans', 'patients', 'patient', 'study',
    'studies', 'authors', 'paper', 'results', 'result', 'data', 'analysis',
    'levels', 'level', 'expression', 'treatment', 'treated', 'effect',
    'effects', 'model', 'models', 'via', 'using', 'used', 'both', 'after',
    'before', 'during', 'between', 'within', 'without', 'well', 'showed',
    'shown', 'show', 'found', 'observed', 'suggests', 'suggest', 'indicate',
    'indicates', 'associated', 'related', 'role', 'roles', 'function',
}


# Assay / reagent / generic-chemistry vocabulary. These are entity-SHAPED (upper
# case, hyphenated, digit-bearing) so the shape heuristic keeps them, and a
# document-frequency cutoff cannot remove them either: DSS-colitis and PCR occur
# in about as many papers as a real junction like NF-kB, so any cutoff that
# drops one drops the other. Joining two papers on "both used PCR" or "both
# measured ROS" is exactly the false bridge the prototype hit, so this list is
# maintained by hand and deliberately so.
METHOD_STOP = {
    'pcr', 'qpcr', 'rt-pcr', 'qrt-pcr', 'elisa', 'wb', 'ihc', 'facs', 'sem',
    'tem', 'hplc', 'lc-ms', 'gc-ms', 'ms/ms', 'nmr', 'tunel', 'h&e', 'sds',
    'page', 'sds-page', 'bsa', 'pbs', 'dmso', 'edta', 'dtt', 'fbs', 'od',
    'dss', 'tnbs', 'stz', 'lps', 'lps-induced', 'cfu', 'moi',
    'ros', 'atp', 'adp', 'nadph', 'nad', 'camp', 'cgmp', 'mpo', 'mda', 'sod',
    'gsh', 'no', 'h2o2',
    'dna', 'rna', 'mrna', 'cdna', 'sirna', 'shrna', 'ncrna', 'rrna', '16s',
    'kegg', 'anova', 'sd', 'sem', 'ci', 'roc', 'auc', 'bmi', 'wt', 'ko',
}


GREEK_FOLD = {'α': 'a', 'β': 'b', 'γ': 'g', 'δ': 'd', 'ε': 'e', 'κ': 'k',
             'λ': 'l', 'μ': 'm', 'π': 'p', 'σ': 's', 'ω': 'w'}


def normalize(tok: str) -> str:
    """Collapse spelling variants of one entity to a single join key.

    Papers write the same molecule three ways -- NF-kB / NF-kappaB / NFkB, or
    IL-1beta / IL-1b -- and untreated they are three distinct tokens that never
    match, which silently removes the real junctions from the shared-node term
    and leaves only assay vocabulary to join on. Fold Greek to Latin and drop
    separators so the variants land on one key.
    """
    low = tok.lower()
    for greek, latin in GREEK_FOLD.items():
        low = low.replace(greek, latin)
    low = low.replace('kappa', 'k').replace('beta', 'b').replace('alpha', 'a')
    return re.sub(r'[\-_/.,\'"()]', '', low)


METHOD_STOP_NORM = {normalize(m) for m in METHOD_STOP}


def entity_shaped(tok: str) -> bool:
    """Keep tokens that look like named entities; drop ordinary prose."""
    low = tok.lower()
    if len(tok) < 3 or low in STOP or low in METHOD_STOP:
        return False
    if normalize(tok) in METHOD_STOP_NORM:
        return False
    if any(ch in GREEK for ch in tok):
        return True
    if any(ch.isdigit() for ch in tok):
        return True
    if '-' in tok:
        return True
    if tok[1:] != tok[1:].lower():      # internal capital: NF-kB, Nr1d1, mTOR
        return True
    return tok.isupper()


def load_profiles(path: Path) -> dict[str, Counter]:
    """paper_id -> Counter(entity token) over its finding/mechanism claims.

    Papers with no finding/mechanism claims fall back to all their claims,
    otherwise they drop out of the pairing entirely and cannot be packed.
    """
    primary: dict[str, Counter] = defaultdict(Counter)
    fallback: dict[str, Counter] = defaultdict(Counter)
    with path.open(encoding='utf-8-sig') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            claim = json.loads(line)
            pid = claim.get('paper_id')
            if not pid:
                continue
            text = claim.get('statement') or ''
            for quote in (claim.get('quotes') or []):
                text += ' ' + (quote.get('text') or '')
            bucket = primary if claim.get('kind') in CONTENT_KINDS else fallback
            for tok in TOKEN.findall(text):
                if entity_shaped(tok):
                    key = normalize(tok)
                    if len(key) >= 2:
                        bucket[pid][key] += 1
    for pid, counts in fallback.items():
        if pid not in primary:
            primary[pid] = counts
    return dict(primary)


def idf_weights(profiles: dict[str, Counter], max_df: float) -> dict[str, float]:
    """Rare entity -> high weight; drop anything common enough to join everything.

    This is a second line of defence only. It removes entities so common they
    join everything; it does NOT remove assay vocabulary, because assays and
    real junctions sit at similar document frequencies -- that is what
    METHOD_STOP is for. Default 1.0 (off).
    """
    n = len(profiles)
    df: Counter = Counter()
    for prof in profiles.values():
        df.update(prof.keys())
    cutoff = max(1, int(max_df * n))
    return {
        tok: math.log(n / (1 + count))
        for tok, count in df.items()
        if count <= cutoff
    }


def vectors(profiles: dict[str, Counter], idf: dict[str, float]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for pid, prof in profiles.items():
        vec = {t: (1 + math.log(c)) * idf.get(t, 0.0) for t, c in prof.items()}
        vec = {t: w for t, w in vec.items() if w > 0}
        norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
        out[pid] = {t: w / norm for t, w in vec.items()}
    return out


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())


def shared_specific(a, b, idf, top: int = 8) -> list[tuple[str, float]]:
    shared = [(t, min(a[t], b[t]) * idf.get(t, 0.0)) for t in a.keys() & b.keys()]
    shared.sort(key=lambda kv: -kv[1])
    return shared[:top]


def bridge_score(a, b, idf, min_shared: int = 1) -> tuple[float, list[tuple[str, float]]]:
    """Maximum distance, gated on the two papers touching at all.

    Measured on the sleep-gut backtest, ranking the known cross-literature
    bridge among all 770 scored pairs:

        pure distance, gated on >=1 shared entity     rank  16  (top  2.1%)
        shared-entity COUNT x distance                rank 261  (top 33.9%)
        IDF-weighted "shared SPECIFIC node" x distance rank 285  (top 37.0%)

    The specificity weighting was the original hypothesis and it is wrong. IDF
    suppresses hub entities (NF-kB, IL-6, TNF-a) -- and a hub is precisely what
    lets two literatures that cite nothing in common touch each other. Rarity of
    the shared node is not the signal; distance between the papers is, and the
    shared node only has to exist.
    """
    shared = a.keys() & b.keys()
    if len(shared) < min_shared:
        return 0.0, []
    return 1.0 - cosine(a, b), shared_specific(a, b, idf)


def rank_pairs(vecs, idf, min_shared: int = 1) -> list[tuple[float, str, str, list]]:
    pids = sorted(vecs)
    ranked = []
    for i, x in enumerate(pids):
        for y in pids[i + 1:]:
            score, shared = bridge_score(vecs[x], vecs[y], idf, min_shared)
            if score > 0:
                ranked.append((score, x, y, shared))
    ranked.sort(key=lambda r: -r[0])
    return ranked


def build_packs(vecs, idf, *, slots: int, size: int, max_reuse: int,
                min_shared: int = 1) -> list[dict]:
    ranked = rank_pairs(vecs, idf, min_shared)
    pids = sorted(vecs)
    used: Counter = Counter()
    packs: list[dict] = []

    for score, a, b, shared in ranked:
        if len(packs) >= slots:
            break
        if used[a] >= max_reuse or used[b] >= max_reuse:
            continue
        pack = [a, b]
        # Grow by adding papers that share a specific node with the pack while
        # staying far from what is already in it.
        while len(pack) < size:
            best, best_score = None, 0.0
            for cand in pids:
                if cand in pack or used[cand] >= max_reuse:
                    continue
                total = sum(bridge_score(vecs[cand], vecs[m], idf, min_shared)[0]
                            for m in pack)
                total /= len(pack)
                if total > best_score:
                    best, best_score = cand, total
            if best is None:
                break
            pack.append(best)
        for pid in pack:
            used[pid] += 1
        packs.append({'papers': pack, 'seed_pair': (a, b),
                      'seed_score': score, 'shared': shared})
    return packs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--claims', required=True, type=Path)
    ap.add_argument('--slots', type=int, default=12)
    ap.add_argument('--papers_per_slot', type=int, default=5)
    ap.add_argument('--max_df', type=float, default=1.0,
                    help='drop entities appearing in more than this fraction '
                         'of papers (default 1.0 = off; METHOD_STOP does the '
                         'real filtering)')
    ap.add_argument('--min_shared', type=int, default=1,
                    help='a pair must share at least this many entities to be '
                         'packable at all (default 1)')
    ap.add_argument('--max_reuse', type=int, default=2,
                    help='max packs one paper may appear in (default 2)')
    ap.add_argument('--emit_args', action='store_true',
                    help='print only --manual_papers args for create_seeds.py')
    ap.add_argument('--verify_pair', metavar='SUBSTR,SUBSTR',
                    help='known-good check: report the bridge rank of the pair '
                         'whose paper_ids contain these two substrings')
    args = ap.parse_args(argv)

    profiles = load_profiles(args.claims)
    if len(profiles) < 2:
        print('error: need >=2 papers with finding/mechanism claims', file=sys.stderr)
        return 1
    idf = idf_weights(profiles, args.max_df)
    vecs = vectors(profiles, idf)

    if args.verify_pair:
        want = [w.strip().lower() for w in args.verify_pair.split(',')]
        if len(want) != 2:
            print('error: --verify_pair needs two comma-separated substrings',
                  file=sys.stderr)
            return 1
        ranked = rank_pairs(vecs, idf, args.min_shared)
        for rank, (score, x, y, shared) in enumerate(ranked, start=1):
            lx, ly = x.lower(), y.lower()
            if (want[0] in lx and want[1] in ly) or (want[1] in lx and want[0] in ly):
                pct = 100.0 * rank / len(ranked)
                print(f'verify_pair rank {rank} / {len(ranked)}  (top {pct:.1f}%)  '
                      f'score={score:.4f}')
                print(f'  {x}')
                print(f'  {y}')
                print('  join on: '
                      + ', '.join(f'{t}({w:.2f})' for t, w in shared))
                return 0
        print('verify_pair: no pair matched those substrings', file=sys.stderr)
        return 1

    packs = build_packs(vecs, idf, slots=args.slots,
                        size=args.papers_per_slot, max_reuse=args.max_reuse,
                        min_shared=args.min_shared)

    if args.emit_args:
        for pack in packs:
            print('--manual_papers')
            print(','.join(pack['papers']))
        return 0

    print(f'{len(profiles)} papers, {len(idf)} distinct entity tokens')
    print(f'{len(packs)} cross-discipline pack(s):\n')
    for index, pack in enumerate(packs, start=1):
        x, y = pack['seed_pair']
        print(f'seed-{index:04d}  bridge={pack["seed_score"]:.4f}')
        print('  join on: '
              + ', '.join(f'{t}({w:.2f})' for t, w in pack['shared'][:5]))
        print(f'  * {x}')
        print(f'  * {y}')
        for extra in pack['papers'][2:]:
            print(f'    {extra}')
        print()
    print('Feed to create_seeds.py, one --manual_papers per pack:')
    print('  python select_cross_packs.py --claims C --emit_args > packs.args')
    print('  python create_seeds.py --claims C --cleaned_jsons D --out seeds.json $(cat packs.args)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
