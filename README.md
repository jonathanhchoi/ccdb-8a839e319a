# Canons and the Court: database website

A static website for exploring the canon dataset behind Jonathan H. Choi & Nina A. Mendelson, *Canons and the Court*, 136 Yale L.J. (forthcoming 2027). It is plain HTML/CSS/JavaScript with no build step and no server, hosted on GitHub Pages.

**Status:** preview. The site carries a `noindex` tag and isn't linked from anywhere public. Before the public launch:
- remove the `<meta name="robots" ...>` line in `docs/index.html`;
- remove the prototype banner;
- fill in `CONFIG` (paper link, DOI, license) at the top of `docs/assets/app.js`.

## Layout

| Path | What it is |
|---|---|
| `build/build_site.py` | Writes everything under `docs/data/` and `docs/downloads/` from the corrected dataset. |
| `docs/index.html`, `docs/assets/` | The site (hand-written). |
| `docs/data/` | Generated JSON:<br>• `meta.json`, `canons.json`, `cases.json`, `justices.json`;<br>• `canon/CNxxxx.json`, the observations per canon;<br>• `case/NNN.json`, the observations per case;<br>• `detail/NNN.json`, the passage around each quotation, loaded on click. |
| `docs/downloads/` | Generated `canons.csv`, `observations.csv` and `canons.sqlite`. |

## Data

The site reads the corrected dataset in the project folder: `outputs/2026-11-08_dataset_corrections/data/observations_corrected.csv.gz` (on Google Drive). That folder holds:
- the code for every correction;
- an observation-by-observation log of each change;
- a memo on what the corrections change relative to the draft (`MEMO.md`).

In brief, the corrections remove three kinds of rows:
- decisions of other courts filed under the Supreme Court, namely Pennsylvania cases in 1–4 Dall. and Court of Claims opinions;
- the reporter's text and arguments of counsel;
- duplicate records of the same decision.

They also re-date misdated records, separate the 2020–2024 opinions, and assign authors from opinion captions, SCDB and hand checks.

The passage text comes from `outputs/2026-10-09_round4_v002/data/source_evidence.jsonl.gz`. Only a window of about 1,800 characters around each quotation is shipped; the full opinion is a CourtListener link.

## Rebuild and preview

```bash
"/c/Users/Jon/AppData/Local/Programs/Python/Python313/python.exe" build/build_site.py
"/c/Users/Jon/AppData/Local/Programs/Python/Python313/python.exe" -m http.server 8765 --directory docs
```

Then open http://localhost:8765. To publish an update, commit and push; GitHub Pages redeploys automatically.

## Moving it to its permanent address

The site will become a section of Jonathan's personal site.
- Renaming this repository (for example, to `canons`) moves the site to `https://jonathanhchoi.github.io/canons/`. All paths are relative, so nothing else changes. Note that GitHub does not redirect the old Pages address.
- If jonathanhchoi.com is set as the custom domain of the `jonathanhchoi.github.io` repository (it is currently a registrar redirect), every project site, including this one, appears under `https://jonathanhchoi.com/<repo>/`.
