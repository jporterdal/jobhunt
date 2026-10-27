"""Recommendations: a match score per posting from the profile's skills and their links, the postings to look at
first, and the skills that would raise those matches most. Computed from stored data each time; no writes, no
model requests, no Flask."""

from __future__ import annotations

import math
import re
from collections import ChainMap, defaultdict
from collections.abc import Iterable, Mapping

from sqlalchemy.engine import Connection

from . import queries
from .userdata import level_rank

# The weights, all in one place. Guesses until there are ratings to tune them against.
RELATION_WEIGHT = {"same": 1.0, "specific": 1.0, "general": 0.6, "related": 0.3}
LEVEL_WEIGHT = {"missing": 0.0, "learning": 0.25, "familiar": 0.5, "proficient": 0.85, "expert": 1.0}
IMPORTANCE_WEIGHT = {"required": 2, "preferred": 1, None: 1}  # a mark without an importance counts as preferred
HAVE_LEVEL = "proficient"  # skill gains ask "what if I had it at this level"
NEUTRAL_INTEREST = 3  # an unrated posting counts as this interest, so its factor is 1
TOP_POSTINGS = 20
TOP_SKILLS = 15
TOP_GAPS = 3
TOP_IMPROVED = 5
# Pooling unlinked skills: a key joins a pool when its name embedding is this similar to the pool's first member's,
POOL_SIMILARITY = 0.90
# or when the first member's words are a run of its words and they are at least this similar.
POOL_NAME_SIMILARITY = 0.80


def best_option(options: list[dict], levels: Mapping[int, str]) -> dict | None:
    """The link option ({skill_id, relation}) with the highest relation weight × level weight, the first on a
    tie; None with no options. Best credit, not strongest relation: a `same` link to a `missing` skill mustn't
    hide a weaker link to a skill the user has."""
    best, best_credit = None, -1.0
    for o in options:
        value = RELATION_WEIGHT[o["relation"]] * LEVEL_WEIGHT.get(levels.get(o["skill_id"]), 0.0)
        if value > best_credit:
            best, best_credit = o, value
    return best


def credit(options: list[dict], levels: Mapping[int, str]) -> float:
    """The credit of a posting skill's best link option (see `best_option`); 0 with none."""
    best = best_option(options, levels)
    return (
        0.0 if best is None else RELATION_WEIGHT[best["relation"]] * LEVEL_WEIGHT.get(levels.get(best["skill_id"]), 0.0)
    )


def _weight(skill: dict) -> int:
    return IMPORTANCE_WEIGHT.get(skill["importance"], 1)


def _value(skills: list[dict], credits: Mapping[str, float]) -> float:
    """The importance-weighted average credit of a posting's skills (at least one)."""
    return sum(_weight(s) * credits.get(s["key"], 0.0) for s in skills) / sum(_weight(s) for s in skills)


def score(skills: list[dict], credits: Mapping[str, float], options: Mapping[str, list]) -> dict:
    """A posting's match: score (None without skills), its number of skills, how many have no link option, and
    up to TOP_GAPS gaps, the skills losing the most weighted credit (required first on a tie)."""
    if not skills:
        return {"score": None, "skills": 0, "unlinked": 0, "gaps": []}
    lost = [
        (_weight(s) * (1 - credits.get(s["key"], 0.0)), s) for s in skills if credits.get(s["key"], 0.0) < 1
    ]
    lost.sort(key=lambda pair: (-pair[0], -_weight(pair[1]), pair[1]["key"]))
    return {
        "score": _value(skills, credits),
        "skills": len(skills),
        "unlinked": sum(not options.get(s["key"]) for s in skills),
        "gaps": [
            {"key": s["key"], "name": s["name"], "importance": s["importance"], "credit": credits.get(s["key"], 0.0)}
            for _, s in lost[:TOP_GAPS]
        ],
    }


def interest_factor(interest: int | None) -> float:
    return (interest or NEUTRAL_INTEREST) / NEUTRAL_INTEREST


def rank_postings(
    postings: list[dict], skills_by_job: Mapping[int, list[dict]], credits: Mapping[str, float],
    options: Mapping[str, list],
) -> tuple[list[dict], int]:
    """(ranked, no_skills): the postings to consider, by score × interest factor, ties newest last seen first,
    each with its score fields, `factor` and `value`; and how many were left out for having no skills. Dismissed
    postings and postings with an application are left out too."""
    ranked, no_skills = [], 0
    for row in postings:
        if row["dismissal_id"] is not None or row["application_id"] is not None:
            continue
        asked = skills_by_job.get(row["job_id"], [])
        if not asked:
            no_skills += 1
            continue
        match = score(asked, credits, options)
        factor = interest_factor(row["interest"])
        ranked.append({**row, **match, "factor": factor, "value": match["score"] * factor})
    ranked.sort(key=lambda r: r["last_seen_at"], reverse=True)
    ranked.sort(key=lambda r: r["value"], reverse=True)
    return ranked, no_skills


def _words(key: str) -> list[str]:
    """A key's words for name containment: split on anything not a letter or digit, a plural `s` dropped."""
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
            for w in re.findall(r"[^\W_]+", key)]


def _contains(words: list[str], leader: list[str]) -> bool:
    """Whether the leader's words are a contiguous run of `words` (equal lists count)."""
    n = len(leader)
    return n > 0 and any(words[i:i + n] == leader for i in range(len(words) - n + 1))


def pool(counts: Mapping[str, int], names: Mapping[str, str], vectors: Mapping[str, list[float]]) -> dict[str, str]:
    """key -> its pool's leader (its first member), in pooling order: most asked first (`counts`), then shorter
    display name, then key. Each key is compared with each pool's leader only, so pools don't chain, and joins
    the qualifying pool it is most similar to (by unit vectors): similarity ≥ POOL_SIMILARITY, or the leader's
    words in its words and similarity ≥ POOL_NAME_SIMILARITY. A key without a vector is alone, as is one
    qualifying for no pool."""
    order = sorted(counts, key=lambda key: (-counts[key], len(names[key]), key))
    leaders: list[tuple[str, list[float], list[str]]] = []
    out: dict[str, str] = {}
    for key in order:
        vector = vectors.get(key)
        if vector is None:
            out[key] = key
            continue
        words, best, joined = _words(key), -2.0, None
        for leader, theirs, leader_words in leaders:
            similarity = math.sumprod(vector, theirs)
            if similarity > best and (
                similarity >= POOL_SIMILARITY
                or (similarity >= POOL_NAME_SIMILARITY and _contains(words, leader_words))
            ):
                best, joined = similarity, leader
        if joined is None:
            leaders.append((key, vector, words))
            joined = key
        out[key] = joined
    return out


def skill_gains(
    ranked: list[dict], skills_by_job: Mapping[int, list[dict]], credits: Mapping[str, float],
    options: Mapping[str, list], profile: Mapping[int, dict], vectors: Mapping[str, list[float]] | None = None,
) -> list[dict]:
    """Candidate skills by gain: Σ (score rise × interest factor) over the ranked postings if the user had the
    skill at HAVE_LEVEL. Candidates are pools of posting skills without a link option (`pool`, over unit
    `vectors` by key; none means every key is alone; credit `same` × HAVE_LEVEL to every member wherever asked)
    and profile skills ({name, level} by id) below HAVE_LEVEL (their level raised, and so the credit of every
    posting skill with an option to them). Candidates with no gain are left out. Each: key (the pool's leader,
    unlinked) or skill_id (profile), name, level, also (the pool's other names, most asked first), gain,
    improved (how many postings rise) and postings (up to TOP_IMPROVED, most improved first, each with its
    `rise`)."""
    by_key: dict[str, list[dict]] = defaultdict(list)
    names: dict[str, str] = {}
    for posting in ranked:
        for s in skills_by_job[posting["job_id"]]:
            by_key[s["key"]].append(posting)
            if s["key"] not in names or s.get("source") == "mark":
                names[s["key"]] = s["name"]
    keys_by_skill: dict[int, list[str]] = defaultdict(list)
    for key in by_key:
        for option in options.get(key, []):
            keys_by_skill[option["skill_id"]].append(key)

    have = RELATION_WEIGHT["same"] * LEVEL_WEIGHT[HAVE_LEVEL]
    unlinked = {key: len(postings) for key, postings in by_key.items() if not options.get(key)}
    pools: dict[str, list[str]] = defaultdict(list)
    for key, leader in pool(unlinked, names, vectors or {}).items():
        pools[leader].append(key)
    candidates = [
        (
            {"key": leader, "skill_id": None, "name": names[leader], "level": None,
             "also": [names[key] for key in members[1:]]},
            {key: have for key in members},
        )
        for leader, members in pools.items()
    ]
    levels = {skill_id: skill["level"] for skill_id, skill in profile.items()}
    for skill_id, skill in profile.items():
        if level_rank(skill["level"]) >= level_rank(HAVE_LEVEL):
            continue
        raised = levels | {skill_id: HAVE_LEVEL}
        changed = {key: credit(options[key], raised) for key in keys_by_skill[skill_id]}
        candidates.append(
            ({"key": None, "skill_id": skill_id, "name": skill["name"], "level": skill["level"], "also": []}, changed)
        )

    out = []
    for candidate, changed in candidates:
        new_credits = ChainMap(changed, credits)
        affected = {p["job_id"]: p for key in changed for p in by_key[key]}
        improved = []
        for posting in affected.values():
            rise = _value(skills_by_job[posting["job_id"]], new_credits) - posting["score"]
            if rise > 0:
                improved.append({**posting, "rise": rise})
        gain = sum(p["rise"] * p["factor"] for p in improved)
        if gain > 0:
            improved.sort(key=lambda p: -p["rise"])
            out.append(candidate | {"gain": gain, "improved": len(improved), "postings": improved[:TOP_IMPROVED]})
    out.sort(key=lambda c: (-c["gain"], c["name"].casefold()))
    return out


def workplace_choice(values: Iterable[str]) -> frozenset[str] | None:
    """The workplace types chosen by the URL's `workplace` values: the known ones, or None (no filter) when that
    leaves none or every type, so an all-ticked form and the default page agree."""
    chosen = frozenset(v for v in values if v in queries.WORKPLACE_TYPES)
    return chosen if 0 < len(chosen) < len(queries.WORKPLACE_TYPES) else None


def recommendations(conn: Connection, workplaces: frozenset[str] | None = None) -> dict:
    """Both lists for the Insights page: postings (top TOP_POSTINGS of `considered`, with `no_skills` left out
    for having no skills) and skills (top TOP_SKILLS, unlinked skills pooled by the name embeddings stored for
    the newest link judgment's model), plus whether any posting has skills and whether the profile has any.
    `workplaces` (see `workplace_choice`) narrows the postings both lists consider to those types; it is
    returned as `workplaces`."""
    from .enrich.links import stored_vectors, unit

    asked = queries.posting_skills(conn)
    skills_by_job: dict[int, list[dict]] = defaultdict(list)
    for s in asked:
        skills_by_job[s["job_id"]].append(s)
    keys = sorted({s["key"] for s in asked})
    options = {key: link["options"] for key, link in queries.effective_links(conn, keys).items()} if keys else {}
    profile = {row.id: {"name": row.name, "level": row.level} for row in queries.profile_skills(conn)}
    levels = {skill_id: skill["level"] for skill_id, skill in profile.items()}
    credits = {key: credit(opts, levels) for key, opts in options.items()}

    rows = queries.posting_list(conn, queries.ListFilters(dismissed="included"))
    if workplaces is not None:
        rows = [row for row in rows if row["workplace_type"] in workplaces]
    ranked, no_skills = rank_postings(rows, skills_by_job, credits, options)
    embed_model = queries.latest_embed_model(conn)
    unlinked = {key for key in keys if not options.get(key)}
    vectors = {
        key: unit(vector) for key, vector in stored_vectors(conn, embed_model).items() if key in unlinked
    } if embed_model else {}
    return {
        "postings": ranked[:TOP_POSTINGS],
        "considered": len(ranked),
        "no_skills": no_skills,
        "skills": skill_gains(ranked, skills_by_job, credits, options, profile, vectors)[:TOP_SKILLS],
        "has_posting_skills": bool(asked),
        "has_profile_skills": bool(profile),
        "workplaces": workplaces,
    }


def posting_summary(conn: Connection, job_id: int) -> dict:
    """One posting's skill summary for its page, from the same credit and score as Insights: score (the `score`
    dict), `have` (skills with credit: the profile skill it comes from, its level, the relation, the credit),
    `dont_have` (the rest, each with a `reason`: `missing` (and the linked profile skill), `not-judged` or
    `no-link`), both as lists of {importance, entries} groups (required, preferred, None; empty groups left
    out), and has_profile_skills. Have is ordered by credit then name, Don't have by name."""
    asked = queries.posting_skills(conn, job_id)
    profile = {row.id: {"name": row.name, "level": row.level} for row in queries.profile_skills(conn)}
    levels = {skill_id: skill["level"] for skill_id, skill in profile.items()}
    links = queries.effective_links(conn, [s["key"] for s in asked]) if asked else {}
    credits = {key: credit(link["options"], levels) for key, link in links.items()}
    have, dont_have = [], []
    for s in asked:
        link = links[s["key"]]
        entry = {"key": s["key"], "name": s["name"], "importance": s["importance"], "source": s["source"],
                 "credit": credits[s["key"]]}
        if entry["credit"] > 0:
            option = best_option(link["options"], levels)
            have.append(entry | {
                "skill_id": option["skill_id"], "skill_name": profile[option["skill_id"]]["name"],
                "level": levels[option["skill_id"]], "relation": option["relation"],
                "same": option["skill_id"] == link["skill_id"] and link["source"] == "same",
            })
        elif link["options"]:
            best = best_option(link["options"], levels)
            dont_have.append(entry | {
                "reason": "missing", "skill_id": best["skill_id"], "skill_name": profile[best["skill_id"]]["name"],
            })
        else:
            dont_have.append(entry | {"reason": "no-link" if link["judged"] or link["source"] else "not-judged"})
    have.sort(key=lambda e: (-e["credit"], e["name"].casefold()))
    dont_have.sort(key=lambda e: e["name"].casefold())

    def grouped(entries):
        return [
            {"importance": importance, "entries": [e for e in entries if e["importance"] == importance]}
            for importance in ("required", "preferred", None)
            if any(e["importance"] == importance for e in entries)
        ]

    return {
        "score": score(asked, credits, {key: link["options"] for key, link in links.items()}),
        "have": grouped(have), "have_count": len(have),
        "dont_have": grouped(dont_have), "dont_have_count": len(dont_have),
        "has_profile_skills": bool(profile),
    }
