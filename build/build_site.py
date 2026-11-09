"""Build the data files for the Canons and the Court website.

Reads the corrected dataset (outputs/2026-11-08_dataset_corrections/data/observations_corrected.csv.gz, built by that
folder's code/build_corrected.py from the paper's Round 4 v002 data) and the v002 evidence file for the passage
around each quotation. Writes:
  docs/data/meta.json            totals, decade denominators, field codes, corrections summary
  docs/data/canons.json          one row per canon
  docs/data/canon/CNxxxx.json    observations of one canon (loaded when a canon page opens)
  docs/data/case/NNN.json        observations of each case, sharded by CourtListener cluster id
  docs/data/detail/NNN.json      passage around the quotation + canon restatement, sharded by unique_id
  docs/data/cases.json           case index (case -> canons)
  docs/data/justices.json        Justices with counts and top canons
  docs/downloads/*.csv, *.sqlite

Usage:  python build/build_site.py [--project ...] [--corrections ...]
"""
import argparse, csv, gzip, json, os, re, shutil, sqlite3, sys
from collections import Counter, defaultdict
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DOCS = os.path.join(REPO, "docs")

ap = argparse.ArgumentParser()
ap.add_argument("--project", default=r"G:\My Drive\Colab Notebooks\nina_project_code")
ap.add_argument("--corrections", default=None)
args = ap.parse_args()
P = args.project
CORR = args.corrections or os.path.join(P, "outputs", "2026-11-08_dataset_corrections")
EVIDENCE = os.path.join(P, "outputs", "2026-10-09_round4_v002", "data", "source_evidence.jsonl.gz")

DATA_VERSION = "1.1-prototype"
DATA_SOURCE = ("Round 4 v002 canon clusters as analyzed in the draft sent to the Yale Law Journal on 2026-10-28, "
               "with the corrections of 2026-11-08 (outputs/2026-11-08_dataset_corrections)")
N_SHARDS = 64        # fewer files: Cloudflare Pages dashboard uploads take up to 1,000 files
CONSENSUS_MIN = 20


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- corrected observations
obs = pd.read_csv(os.path.join(CORR, "data", "observations_corrected.csv.gz"), dtype={"unique_id": str}, low_memory=False)
t4 = json.load(open(os.path.join(CORR, "data", "table4_corrected.json"), encoding="utf8"))
exc = pd.read_csv(os.path.join(CORR, "data", "excluded_observations.csv"), dtype={"unique_id": str})
OPTYPE_CODES = {"010combined": "M", "020lead": "L", "025plurality": "L", "015unamimous": "L", "030concurrence": "C",
                "035concurrenceinpart": "P", "040dissent": "D", "050statement": "S", "070rehearing": "H"}
USAGE_CODES = {"applied": "A", "approved, conditions not met": "C", "approved, outweighed": "O",
               "approved, not applied (other reason)": "N", "rejected": "R", "unclear": "U"}
fr = pd.DataFrame({
    "uid": obs.unique_id, "canon_id": obs.canon_id, "canon_label": obs.canon_label, "ctype": obs.canon_type,
    "slug": obs.case_key, "cl_slug": obs.slug, "case_name": obs.case_name, "date_filed": obs.date_filed,
    "year": obs.decision_year.astype(int), "cluster_id": obs.courtlistener_cluster_id.astype(int),
    "optype": obs.opinion_type, "author": obs.author.fillna(""), "justice": obs.justice.fillna(""),
    "author_str": obs.author_as_recorded.fillna(""), "label_source": obs.label_source.fillna(""),
    "quotation": obs.quotation.fillna("")})
fr["author_in"] = fr.author
unknown_types = set(fr.optype.dropna()) - set(OPTYPE_CODES)
assert not unknown_types, unknown_types
fr["opt"] = fr.optype.map(OPTYPE_CODES).fillna("")
fr["eic"] = obs.explicit_or_implicit.map({"explicit": "E", "implicit": "I"}).fillna("")
fr["usage"] = obs.usage.map(USAGE_CODES).fillna("")
types = fr.drop_duplicates("canon_id").set_index("canon_id").ctype.to_dict()
checks = t4["published_table4"]
R = exc.reason.value_counts()
adj = {"excludedByReason": R.to_dict(),
       "nonScotusObservations": int(R.get("not a Supreme Court case", 0)),
       "nonScotusCases": int(exc[exc.reason == "not a Supreme Court case"].detail.nunique()),
       "frontMatterObservations": int(R.get("reporter's front matter (before the opinion of the Court)", 0)),
       "duplicateObservations": int(R.get("duplicate of another record of the same decision", 0)),
       "relabelled2020s": int(fr.label_source.str.startswith("2020-24").sum()),
       "authorsAssigned": int(fr.label_source.str.startswith("author from").sum()),
       "canonsDropped": int(exc[exc.reason == "canon no longer used explicitly after corrections"].canon_id.nunique())}
log("observations", len(fr), "| canons", fr.canon_id.nunique(), "| cases", fr.slug.nunique())

uids = set(fr.uid)
ev = {}
with gzip.open(EVIDENCE, "rt", encoding="utf8") as f:
    for line in f:
        m = json.loads(line)["source_metadata"]
        if m.get("unique_id") in uids:
            ev[m["unique_id"]] = m
assert not (uids - set(ev)), "observations without an evidence record"

# ------------------------------------------------------------- labels
def clean_label(s):
    s = re.sub(r'^[\s:;,"\']+', "", str(s)).strip()
    if s.count('"') % 2 == 1 and s.endswith('"'):
        s = s[:-1].rstrip()
    return s


labels = fr.drop_duplicates("canon_id").set_index("canon_id").canon_label.map(clean_label).to_dict()

# ------------------------------------------------------------- output folders
DATA = os.path.join(DOCS, "data")
DL = os.path.join(DOCS, "downloads")
for d in (os.path.join(DATA, "canon"), os.path.join(DATA, "detail")):
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
os.makedirs(DL, exist_ok=True)


def dump(obj, path):
    with open(path, "w", encoding="utf8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


fr["decade"] = (fr.year // 10) * 10
decades = list(range(int(fr.decade.min()), int(fr.decade.max()) + 10, 10))
dec_ix = {d: i for i, d in enumerate(decades)}
decade_cases = fr.groupby("decade").slug.nunique().reindex(decades, fill_value=0).astype(int).tolist()
decade_obs = fr.groupby("decade").size().reindex(decades, fill_value=0).astype(int).tolist()

# ------------------------------------------------------------- canons.json
canons = []
for cid, g in fr.groupby("canon_id", sort=False):
    ex = g[g.eic == "E"]
    dc = g.groupby("decade").slug.nunique()
    dvec = [0] * len(decades)
    for d, n in dc.items():
        dvec[dec_ix[d]] = int(n)
    auth = Counter(a for a in g.justice if a)
    canons.append({
        "id": cid, "label": labels[cid], "type": types[cid],
        "n": int(len(g)), "cases": int(g.slug.nunique()),
        "opinions": int(g[["slug", "optype", "author_in"]].astype(str).drop_duplicates().shape[0]),
        "explicit": int((g.eic == "E").sum()), "implicit": int((g.eic == "I").sum()),
        "first": int(g.year.min()), "firstExplicit": int(ex.year.min()) if len(ex) else None,
        "last": int(g.year.max()),
        "consensus": bool(len(g) >= CONSENSUS_MIN),
        "usage": dict(Counter(u for u in g.usage if u)),
        "opt": dict(Counter(o for o in g.opt if o)),
        "dec": dvec,
        "topAuthors": auth.most_common(5),
    })
canons.sort(key=lambda c: -c["n"])
for i, c in enumerate(canons, 1):
    c["rank"] = i
dump(canons, os.path.join(DATA, "canons.json"))
log("canons.json", len(canons))

# ------------------------------------------------------------- per-canon observations
OBS_FIELDS = ["uid", "case", "date", "author", "opt", "ei", "usage", "quote", "cl", "slug", "cs"]
fr = fr.sort_values(["canon_id", "date_filed", "uid"])
for cid, g in fr.groupby("canon_id"):
    obs = [[r.uid, r.case_name, r.date_filed, r.author, r.opt, r.eic, r.usage,
            (r.quotation or "").strip(), int(r.cluster_id), r.slug, r.cl_slug] for r in g.itertuples()]
    dump({"id": cid, "fields": OBS_FIELDS, "obs": obs}, os.path.join(DATA, "canon", f"{cid}.json"))

# ------------------------------------------------------------- detail shards
# The site shows the passage around each quotation, not the opinion's full text (readers follow the CourtListener
# link for that). Older opinions are often stored as one block of text, so long "paragraphs" are cut to a window
# around the quotation.
EXCERPT_MAX, PAD, HARD_MAX = 1800, 650, 3200

def quote_fragments(q):
    out = []
    for p in re.split(r"\s*(?:\.\s?\.\s?\.|…)\s*", q or ""):
        p = re.sub(r"^[\"“”'‘’]+|[\"“”'‘’]+$", "", p.strip()).strip()
        if len(p) >= 20:
            out.append(p)
    return out

def excerpt(par, quote):
    par = re.sub(r"\s+", " ", par or "").strip()
    if len(par) <= EXCERPT_MAX:
        return par
    hits = [(par.find(f), len(f)) for f in quote_fragments(quote)]
    hits = [(i, n) for i, n in hits if i >= 0]
    if hits:
        a = max(0, min(i for i, _ in hits) - PAD)
        b = min(len(par), max(i + n for i, n in hits) + PAD)
    else:
        a, b = 0, EXCERPT_MAX
    b = min(b, a + HARD_MAX)
    if a > 0:
        s = par.rfind(" ", 0, a)
        a = s + 1 if s > 0 else a
    if b < len(par):
        s = par.find(" ", b)
        b = s if s > 0 else b
    return ("… " if a > 0 else "") + par[a:b].strip() + (" …" if b < len(par) else "")

shards = defaultdict(dict)
q_by_uid = fr.drop_duplicates("uid").set_index("uid").quotation.to_dict()
for u in fr.uid.unique():
    m = ev[u]
    shards[int(u) % N_SHARDS][u] = {"p": excerpt(m.get("paragraph"), q_by_uid.get(u)), "s": (m.get("general_canon") or "").strip()}
for k, v in shards.items():
    dump(v, os.path.join(DATA, "detail", f"{k:03d}.json"))
log("detail shards", len(shards))

# ------------------------------------------------------------- cases.json
cases = []
for slug, g in fr.groupby("slug"):
    r0 = g.iloc[0]
    cnt = Counter(g.canon_id)
    cases.append([slug, r0.case_name, r0.date_filed, int(r0.cluster_id), [[c, n] for c, n in cnt.most_common()]])
cases.sort(key=lambda c: c[2] or "")
dump({"fields": ["slug", "case", "date", "cl", "canons"], "cases": cases}, os.path.join(DATA, "cases.json"))
log("cases.json", len(cases))

# case shards: observations of each case, sharded by CourtListener cluster id
CASE_FIELDS = ["uid", "canon", "author", "opt", "ei", "usage", "quote", "cl", "cs"]
cdir = os.path.join(DATA, "case")
if os.path.isdir(cdir):
    shutil.rmtree(cdir)
os.makedirs(cdir)
cshards = defaultdict(dict)
for slug, g in fr.groupby("slug"):
    cl = int(g.cluster_id.iloc[0])
    cshards[cl % N_SHARDS][slug] = [[r.uid, r.canon_id, r.author, r.opt, r.eic, r.usage, (r.quotation or "").strip(), int(r.cluster_id), r.cl_slug]
                                    for r in g.itertuples()]
for k, v in cshards.items():
    dump({"fields": CASE_FIELDS, "cases": v}, os.path.join(cdir, f"{k:03d}.json"))
log("case shards", len(cshards))

# ------------------------------------------------------------- justices.json
justices = []
for a, g in fr[fr.justice != ""].groupby("justice"):
    justices.append({"name": a, "n": int(len(g)), "cases": int(g.slug.nunique()),
                     "first": int(g.year.min()), "last": int(g.year.max()),
                     "opt": dict(Counter(o for o in g.opt if o)),
                     "types": dict(Counter(g.ctype)),
                     "top": Counter(g.canon_id).most_common(15)})
justices.sort(key=lambda j: j["first"])
dump(justices, os.path.join(DATA, "justices.json"))
log("justices.json", len(justices))

# ------------------------------------------------------------- meta.json
meta = {
    "version": DATA_VERSION, "source": DATA_SOURCE,
    "built": pd.Timestamp.now().strftime("%Y-%m-%d"),
    "totals": {"observations": int(len(fr)), "distinctObservations": int(fr.uid.nunique()),
               "canons": int(fr.canon_id.nunique()), "consensusCanons": int(sum(c["consensus"] for c in canons)),
               "cases": int(fr.slug.nunique()), "opinions": int(fr[["slug", "optype", "author_in"]].astype(str).drop_duplicates().shape[0]),
               "byType": {t: {"canons": int(fr[fr.ctype == t].canon_id.nunique()), "observations": int((fr.ctype == t).sum())}
                          for t in ["meta-canon", "substantive", "language"]},
               "attributedToJustice": int((fr.justice != "").sum()),
               "unattributed": {
                   "noAuthor": int(((fr.justice == "") & (fr.author == "")).sum()),
                   "perCuriam": int((fr.author == "Per Curiam").sum()),
                   "other": int(((fr.justice == "") & ~fr.author.isin(["", "Per Curiam"])).sum())},
               "noAuthor2021on": int(((fr.year >= 2021) & (fr.justice == "")).sum()),
               "obs2021on": int((fr.year >= 2021).sum()),
               "yearMin": int(fr.year.min()), "yearMax": int(fr.year.max())},
    "paperTable4": {"observations": checks["all_obs"], "canons": checks["all_canons"], "cases": checks["cases_any"],
                    "opinions": checks["opinions_any"], "consensusCanons": checks["min20_canons"]},
    "adjustments": adj,
    "decades": decades, "decadeCases": decade_cases, "decadeObs": decade_obs,
    "nShards": N_SHARDS, "consensusMin": CONSENSUS_MIN,
    "codes": {
        "opt": {"L": "Lead opinion (majority or plurality)", "C": "Concurrence",
                "P": "Concurrence in part / dissent in part", "D": "Dissent", "S": "Statement respecting an order (e.g., denial of certiorari)", "H": "Opinion on rehearing",
                "M": "Combined text (CourtListener did not separate the opinions)"},
        "ei": {"E": "Explicit", "I": "Implicit"},
        "usage": {"A": "Applied with approval", "C": "Approved, but its conditions were not met",
                  "O": "Approved, but outweighed", "N": "Approved, but not applied for other reasons",
                  "R": "Rejected", "U": "Unclear"},
    },
}

# ------------------------------------------------------------- downloads
OPT_TXT, EI_TXT, US_TXT = meta["codes"]["opt"], meta["codes"]["ei"], meta["codes"]["usage"]
canon_cols = ["canon_id", "label", "canon_type", "observations", "cases", "opinions", "explicit_observations",
              "implicit_observations", "first_year", "first_explicit_year", "last_year", "consensus_canon"]
canon_rows = [[c["id"], c["label"], c["type"], c["n"], c["cases"], c["opinions"], c["explicit"], c["implicit"],
               c["first"], c["firstExplicit"], c["last"], int(c["consensus"])] for c in canons]
obs_cols = ["observation_id", "canon_id", "case_name", "date_filed", "year", "justice", "opinion_author_as_recorded",
            "opinion_type", "opinion_label_source", "explicit_or_implicit", "usage", "quotation",
            "courtlistener_cluster_id", "courtlistener_url"]
fr = fr.sort_values(["date_filed", "uid", "canon_id"])
obs_rows = [[r.uid, r.canon_id, r.case_name, r.date_filed, r.year, r.justice,
             r.author_str if isinstance(r.author_str, str) else "",
             OPT_TXT.get(r.opt, ""), r.label_source, EI_TXT.get(r.eic, ""), US_TXT.get(r.usage, ""), (r.quotation or "").strip(),
             int(r.cluster_id), f"https://www.courtlistener.com/opinion/{int(r.cluster_id)}/{r.cl_slug}/"]
            for r in fr.itertuples()]
for name, cols, data in [("canons.csv", canon_cols, canon_rows), ("observations.csv", obs_cols, obs_rows)]:
    with open(os.path.join(DL, name), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(data)
dbp = os.path.join(DL, "canons.sqlite")
if os.path.exists(dbp):
    os.remove(dbp)
con = sqlite3.connect(dbp)
con.execute(f"CREATE TABLE canons ({', '.join(canon_cols)}, PRIMARY KEY (canon_id))")
con.executemany(f"INSERT INTO canons VALUES ({','.join('?' * len(canon_cols))})", canon_rows)
con.execute(f"CREATE TABLE observations ({', '.join(obs_cols)})")
con.executemany(f"INSERT INTO observations VALUES ({','.join('?' * len(obs_cols))})", obs_rows)
for col in ["canon_id", "year"]:   # keep the file under 25 MiB (Cloudflare Pages file limit)
    con.execute(f"CREATE INDEX idx_obs_{col} ON observations ({col})")
con.commit()
con.execute("VACUUM")
con.close()
meta["downloads"] = {}
for n in sorted(os.listdir(DL)):
    meta["downloads"][n] = os.path.getsize(os.path.join(DL, n))
    log(f"downloads/{n}: {meta['downloads'][n] / 1e6:.1f} MB")
dump(meta, os.path.join(DATA, "meta.json"))
log("done")
