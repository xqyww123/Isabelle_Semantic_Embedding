"""Independent reference evaluators for eff (today) and eff* (proposed).

Deliberately written in a different shape from the production/prototype
iterative Tarjan closure: collect the reachable subgraph, run Tarjan to get the
strongly connected components in reverse topological order, then give every
component one value.  The prototype must agree with this on every node.

Store model: a mapping uk -> record | None.  A key that is absent, or maps to
None, is "no record" and contributes 0 (CHECK_OUTDATE_PLAN.md §4.4).  A record
needs three attributes: `version`, `interpreted_at`, `deps` (None reads as 0 /
empty).
"""
from __future__ import annotations


def _rec(store, k):
    return store.get(k)


def sccs(store, roots):
    """Tarjan over the records reachable from `roots`.

    Returns (comp_of: node -> component index, comps: list of member lists),
    with the components in REVERSE topological order (successors first).
    """
    index: dict = {}
    low: dict = {}
    on_stack: set = set()
    stack: list = []
    comp_of: dict = {}
    comps: list = []
    counter = 0

    for root in roots:
        if root in index or _rec(store, root) is None:
            continue
        # iterative DFS: frames are [node, dep-iterator]
        r0 = _rec(store, root)
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        frames = [[root, iter(r0.deps or [])]]
        while frames:
            k, it = frames[-1]
            advanced = False
            for d in it:
                if _rec(store, d) is None:
                    continue
                if d not in index:
                    index[d] = low[d] = counter
                    counter += 1
                    stack.append(d)
                    on_stack.add(d)
                    frames.append([d, iter(_rec(store, d).deps or [])])
                    advanced = True
                    break
                if d in on_stack and index[d] < low[k]:
                    low[k] = index[d]
            if advanced:
                continue
            frames.pop()
            if low[k] == index[k]:
                members = []
                while True:
                    m = stack.pop()
                    on_stack.discard(m)
                    comp_of[m] = len(comps)
                    members.append(m)
                    if m == k:
                        break
                comps.append(members)
            if frames and low[k] < low[frames[-1][0]]:
                low[frames[-1][0]] = low[k]
    return comp_of, comps


def contrib(store, d, e, shielded):
    """What dependency `d` with eff(*) value `e` hands to a parent outside its
    component.  Under the proposed rule a FRESH dependency (it absorbed
    everything upstream: e <= interpreted_at) with a real version and a real
    interpreted_at contributes only its own version."""
    r = _rec(store, d)
    if r is None:
        return 0
    if not shielded:
        return e
    ver = r.version or 0
    ia = r.interpreted_at or 0
    if ver > 0 and ia > 0 and e <= ia:
        return ver
    return e


def eff_all(store, roots, shielded: bool) -> dict:
    """eff (shielded=False) or eff* (shielded=True) for every node reachable
    from `roots` that has a record.  Nodes without a record are absent (0)."""
    comp_of, comps = sccs(store, roots)
    comp_val: list = [0] * len(comps)
    eff: dict = {}
    for ci, members in enumerate(comps):          # reverse topological order
        v = 0
        for m in members:
            r = _rec(store, m)
            v = max(v, r.version or 0)
            for d in r.deps or []:
                if _rec(store, d) is None:
                    continue
                if comp_of[d] == ci:              # intra-SCC: no wall
                    continue
                v = max(v, contrib(store, d, comp_val[comp_of[d]], shielded))
        comp_val[ci] = v
        for m in members:
            eff[m] = v
    return eff


def eff_all_rawtest(store, roots) -> dict:
    """The EARLIER phrasing of the proposed rule: the value handed upwards is
    eff*, but the freshness test that decides whether a dependency is a wall
    uses the RAW (today's) eff of that dependency instead of its eff*."""
    raw = eff_all(store, roots, shielded=False)
    comp_of, comps = sccs(store, roots)
    comp_val = [0] * len(comps)
    out: dict = {}
    for ci, members in enumerate(comps):
        v = 0
        for m in members:
            r = _rec(store, m)
            v = max(v, r.version or 0)
            for d in r.deps or []:
                rd = _rec(store, d)
                if rd is None or comp_of[d] == ci:
                    continue
                star = comp_val[comp_of[d]]
                ver, ia = rd.version or 0, rd.interpreted_at or 0
                if ver > 0 and ia > 0 and raw.get(d, 0) <= ia:
                    v = max(v, ver)
                else:
                    v = max(v, star)
        comp_val[ci] = v
        for m in members:
            out[m] = v
    return out


def eff_of(store, node, shielded: bool) -> int:
    """eff(*) of a single node (0 when it has no record)."""
    return eff_all(store, [node], shielded).get(node, 0)


def eff_entity(store, version: int, deps, shielded: bool) -> int:
    """Production's `eff_value`: the entity's own version folded with the
    contributions of its direct dependencies."""
    eff = eff_all(store, list(deps or []), shielded)
    best = version
    for d in deps or []:
        best = max(best, contrib(store, d, eff.get(d, 0), shielded))
    return best
