# CORUX

**AI lab-result interpretation for clinicians.**

Labs influence up to ~70% of clinical decisions, yet interpretation stays fragmented, manual, and
point-in-time. CORUX's thesis: interpretation is *pattern recognition over time* — multi-marker
patterns, multi-year trends, risk trajectory — exactly the work AI is now good at.

CORUX takes a de-identified lab JSON, runs it through a **code-orchestrated pipeline** that calls
Claude at specific reasoning steps and harmonizes cross-lab units deterministically, and renders a
single **physician report**: narrative, marker table with status + trend, derived ratios, a
recognized clinical pattern with structured follow-up, and a full processing trace for audit.

> **Decision-support only. Not a diagnosis. Clinical judgment required.**

---

## Table of contents

- [The idea in one screen](#the-idea-in-one-screen)
- [Architecture & pipeline](#architecture--pipeline)
- [The agents](#the-agents)
- [Deterministic harmonization & tools](#deterministic-harmonization--tools)
- [Traceability](#traceability)
- [Input contract](#input-contract)
- [Project layout](#project-layout)
- [Getting started](#getting-started)
- [Running CORUX](#running-corux)
- [Using CORUX with Claude Code](#using-corux-with-claude-code)
- [Example prompts to ask Claude Code](#example-prompts-to-ask-claude-code)
- [Testing](#testing)
- [Configuration](#configuration)
- [Data & privacy](#data--privacy)
- [Publish this repo](#publish-this-repo)

---

## The idea in one screen

The headline differentiator is **live cross-lab unit/range harmonization**. Results are stored
*exactly as each lab issued them* (original value, unit, range); CORUX harmonizes to one canonical
unit per analyte **at read time, deterministically** (not by the LLM). This makes a multi-lab signal
visible that no single point-in-time view shows:

```
Gamma-GT:  94 U/L (PL)  →  0.85 µkat/L (DE)  →  98 U/L (DE)
harmonized:  94      →     51            →     98   U/L     → fluctuating-elevated hepatic signal
```

The same patient's GGT, ALP, MCV (macrocytosis), FIB-4, and a resolved triglyceride spike together
read as a coherent **hepatic/metabolic signal flagged for structured follow-up** — not a diagnosis.

---

## Architecture & pipeline

CORUX is a **deterministic Python loop** (we own the control flow) that calls Claude at specific
reasoning steps. This is the recommended pattern for multi-step pipelines with code-controlled
logic — not an open-ended agent, not a managed-agents runtime.

| # | Step | Type | What it does |
|---|------|------|--------------|
| 1 | **Ingest** | code | Parse & validate JSON into typed models; sort panels by `collected_date`. |
| 2 | **PII firewall** | code | Input arrives de-identified; derive a salted `patient_key`, pass only age/sex/notes to the model — never the id. |
| 3 | **Retrieve history** | code | Merge panels with the stored record (dedupe by date); build the per-analyte series. |
| 4 | **Compare baseline** | agent | Classify each marker `Normal / Abnormal / Critical / Dangerous` with rationale. |
| 5 | **Reason across markers** | agent | Two-pass coherence check; 3-tier resonance verdict + data-quality gate. |
| 6 | **Harmonize & trends** | code (tools) | Deterministic cross-lab unit/range harmonization (§5 factors) via 3 tools; each call traced. |
| 7 | **Assess pattern** | agent | Do the harmonized trajectories co-occur as a recognizable signal worth follow-up? |
| 8 | **Consult literature** | agent | *(optional)* reputable medical evidence via web search. |
| 9 | **Orchestrate** | agent | Synthesize everything into the final clinician-facing report. |

Every agent step is constrained to a Pydantic schema via `client.messages.parse(...)`, so each
returns **validated JSON — no parsing, no regex**.

Model: **`claude-opus-4-8`** with adaptive thinking; effort tuned per step in
[`corux/config.py`](corux/config.py).

---

## The agents

Agents live in [`corux/agents/`](corux/agents/). Each is a thin module: a system prompt + a
Pydantic output schema + a `run()` that calls Claude through the shared wrapper
([`corux/llm.py`](corux/llm.py)).

| Agent | File | Role | Output schema |
|-------|------|------|---------------|
| **Baseline** | [`baseline.py`](corux/agents/baseline.py) | Per-marker severity (`Normal/Abnormal/Critical/Dangerous`) on the latest panel. Deterministic math pre-computes each value's position vs its reference range; one **batched** call classifies all markers. | `BaselineResult` |
| **Cross-marker** | [`cross_marker.py`](corux/agents/cross_marker.py) | Two passes: (A) a holistic panel overview, then (B) a marker-by-marker **resonance** check. Each notable marker gets a 3-tier verdict — **corroborated** (real, even if severe) / **uncorroborated** (isolated extreme → likely data error) / **ambiguous** (→ recommend re-test). Acts as the data-quality gate. | `CrossMarkerResult` |
| **Pattern** | [`pattern.py`](corux/agents/pattern.py) | Tool 4. Takes the harmonized cross-panel trajectories + the latest panel's abnormal results and decides whether they co-occur as a recognizable clinical pattern worth **structured follow-up**. This is the step that turns one marker into a signal. | `PatternResult` |
| **Literature** | [`literature.py`](corux/agents/literature.py) | *(optional, off by default)* Retrieves supporting evidence for notable findings via the server-side `web_search` tool, restricted to reputable medical sources. | `LiteratureResult` |
| **Orchestrator** | [`orchestrator.py`](corux/agents/orchestrator.py) | Synthesizes baseline + cross-marker + trajectories + pattern (+ literature) into the final report: headline, summary, key caveat, explanation, discussion points, next-panel recommendation, and carried-forward data-quality flags. | `OrchestratorResult` |

> A retired `longitudinal.py` agent remains in the tree but is **no longer wired in** — its job
> (trend analysis) moved to the deterministic harmonization tools below, per the design spec that
> harmonization be done in code, not by the LLM.

All output schemas are defined in [`corux/schemas.py`](corux/schemas.py) — the single place to look
for exactly what each agent returns.

---

## Deterministic harmonization & tools

The trend analysis is **deterministic code** ([`corux/harmonize.py`](corux/harmonize.py)) — more
credible to a clinician and free of on-screen arithmetic errors. Three tools run in sequence per
tracked analyte and are surfaced individually in the trace:

1. **`get_reference_ranges(analyte, value, unit, …)`** — harmonizes one value + its reference range
   to the canonical unit. This is where `µkat/L → U/L`, `mmol/L → mg/dL`, `µmol/L → mg/dL`, etc.
   happen, using the conversion factors in the module.
2. **`compare_to_prior(analyte)`** — returns every prior value across panels, harmonized, with deltas
   and dates/labs.
3. **`assess_trajectory(series)`** — classifies the harmonized series:
   `stable | rising | falling | fluctuating | resolved | insufficient`, flags whether any point was
   out of range, and surfaces the **worst excursion** (so a historical critical spike — e.g. a
   triglyceride of 789 mg/dL, ~8× the upper limit — is never hidden behind a bland shape label).

Tool 4, **`assess_pattern`**, is the LLM step above (clinical judgment, not arithmetic).

The physician-report view-model — marker rows with status tiers (incl. a **Watch** upper-normal
tier) + trend/change, derived ratios (TG/HDL, AST/ALT De Ritis), and the traditional-vs-CORUX
side-by-side — is assembled deterministically in [`corux/report.py`](corux/report.py).

---

## Traceability

CORUX records a **timestamped, auditable trace** of everything it does — built for certification.
Implemented in [`corux/tracing.py`](corux/tracing.py); a `Tracer` held in a context variable lets
deep code emit events without threading a tracer through every call.

**Event types**

| Event | Emitted when | Key fields |
|-------|--------------|------------|
| `pipeline` | run start / end | `status` |
| `step` | each pipeline step | `step`, `label`, `status` (started/completed/skipped), `duration_ms`, `reason` |
| `llm` | each Claude call | `step`, `model`, `effort`, `input_tokens`, `output_tokens`, `request_id`, `duration_ms` |
| `tool` | each deterministic tool call | `tool`, `analyte`, `input`, `output` |

Every event carries a monotonic `seq` and a UTC ISO `ts`.

**How to consume it**

- **Live in the UI** — the web app streams the trace via Server-Sent Events
  (`POST /api/run/stream`) into a fixed-height, scrollable **Processing trace** panel that updates
  as each step/tool/agent runs.
- **As an audit record** — the full trace is embedded in every result (`result.trace`) and a
  **⤓ Download** button exports it as timestamped JSON. The non-streaming `POST /api/run` returns
  the same trace in its response.

---

## Input contract

De-identified multi-panel lab results. Defined in [`corux/schemas.py`](corux/schemas.py) — **the
single swap point** for the real analyzer format. See [`data/mark_hahnfeld.json`](data/mark_hahnfeld.json)
for a full example.

```json
{
  "patient": { "patient_id": "PT-0001", "sex": "male", "age_years": 40, "notes": null },
  "panels": [{
    "panel_id": "PNL-2025-0207",
    "collected_date": "2025-02-07", "reported_date": "2025-02-08",
    "source_lab": { "name": "Diagnostyka", "country": "PL", "unit_system": "conventional" },
    "context": "ordering reason / panel context",
    "results": [{
      "name": "Gamma-GT (GGT)", "loinc": "2324-2", "value": 94, "unit": "U/L",
      "ref_low": 9, "ref_high": 60, "flag": "high", "ref_note": null, "derived": false
    }]
  }]
}
```

- Input is **already de-identified** (pseudonymous `patient_id`, `age_years` — no name/dob).
- `value` is numeric **or** a qualitative/censored string (`"negative"`, `">90"`, `"<0.6"`).
- `flag` is the lab's own `normal | low | high`; `derived` marks calculated values (eGFR, calc LDL, FIB-4).
- `unit_system` (`conventional | SI`) — results are stored as issued; CORUX harmonizes at read time.
- Optional per-result `analytical` block (`cv_percent`, `hemolysis_index`, `qc_status`, `method`) is
  the owned-signal moat — intentionally absent on external panels.

---

## Project layout

```
CORUX/
├── README.md
├── requirements.txt              # anthropic, pydantic, python-dotenv, fastapi, uvicorn
├── .env.example                  # ANTHROPIC_API_KEY=
├── cli.py                        # convenience entrypoint (= python -m corux)
├── corux/
│   ├── __main__.py               # CLI:  python -m corux <input.json> [--literature] [--no-persist]
│   ├── webapp.py                 # FastAPI app + SSE streaming endpoint
│   ├── web/index.html            # the physician-report single-page UI
│   ├── config.py                 # model, per-step effort, store path, salt
│   ├── llm.py                    # Anthropic wrapper (structured output + trace)
│   ├── schemas.py                # input contract + all agent output schemas
│   ├── ingest.py                 # step 1
│   ├── privacy.py                # step 2 (PII firewall)
│   ├── history.py                # step 3 (longitudinal store + series)
│   ├── harmonize.py              # step 6 deterministic tools (§5 conversions)
│   ├── report.py                 # physician-report view-model builder
│   ├── tracing.py                # the audit trace
│   ├── pipeline.py               # the code-controlled loop wiring steps 1→9
│   └── agents/                   # baseline, cross_marker, pattern, literature, orchestrator
├── data/
│   ├── mark_hahnfeld.json        # 3-panel hepatic-signal demo (PL→DE→DE, mixed units)
│   ├── sample_input.json         # synthetic 2-panel demo (qualitative + derived + outlier)
│   └── store/                    # persisted per-patient records (PHI — git-ignored)
└── tests/                        # deterministic steps run for real; agent calls mocked
```

---

## Getting started

### 1. Clone the repo

```bash
git clone https://github.com/<your-username>/corux.git
cd corux
```

> No remote yet? See [Publish this repo](#publish-this-repo) to push it first.

### 2. Install dependencies

Python 3.10+.

```bash
python3 -m pip install -r requirements.txt
```

### 3. Add your Anthropic API key

```bash
cp .env.example .env
# edit .env and set:  ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is git-ignored. The key is read automatically at startup.

---

## Running CORUX

### Web app (physician report)

```bash
python -m corux.webapp                    # serves http://127.0.0.1:8000
CORUX_PORT=8765 python -m corux.webapp    # use another port if 8000 is taken
```

Open the URL → **Load sample…** (`mark_hahnfeld.json` is the headline demo) or paste your own JSON →
**Run**. A run makes several Claude calls and takes ~1–2 minutes; the Processing trace streams live,
then the report renders. Toggle **Literature** for the evidence step and **Persist history** to
accumulate the patient's record across runs.

### CLI

```bash
python -m corux data/mark_hahnfeld.json               # full pipeline, prints JSON (incl. trace)
python -m corux data/mark_hahnfeld.json --literature  # add the evidence step
python -m corux data/mark_hahnfeld.json --no-persist  # ignore the longitudinal store
```

---

## Using CORUX with Claude Code

CORUX was built with [Claude Code](https://claude.com/claude-code) and is designed to be extended
the same way — you describe the change in plain English and Claude edits the code, runs the tests,
and verifies against the live pipeline.

**Open the project:**

```bash
cd corux
claude          # starts Claude Code in this directory (CLI)
```

Or open the `corux/` folder in the **VS Code / JetBrains extension** or the **desktop app**, or at
**claude.ai/code**. Claude Code reads this README and the codebase as context.

**A good first message** to orient it:

> Read the README and `corux/pipeline.py`. Then run the test suite and start the web app so I can
> see it working.

Because the deterministic steps are covered by tests and the agent calls are mocked in the smoke
test, Claude can iterate safely: `pytest` runs offline with no API key, and a live run only happens
when you ask for one.

---

## Example prompts to ask Claude Code

Concrete updates you can request — phrased the way they work well:

**Add or change clinical logic**

- *"Add a deterministic ‘Dangerous’ rule to the baseline step: triglycerides ≥ 1000 mg/dL and potassium ≥ 6.0 mmol/L should always classify as Dangerous regardless of the agent's judgment."*
- *"Add a new derived ratio in `report.py`: the AIP (log(TG/HDL)). Show it in the Derived ratios table with a reference band."*
- *"Add a harmonization factor for calcium (mmol/L ↔ mg/dL, × 4.0) and wire it into `harmonize.py` with a test."*

**Change models / cost / behavior**

- *"Switch the baseline step to `claude-haiku-4-5` to cut cost, keep the others on Opus, and re-run the demo to compare output."*
- *"Lower the effort for the cross-marker overview pass to `medium` and show me the token-usage delta in the trace."*

**Extend the pipeline**

- *"Add a new agent step after cross-marker that drafts a patient-friendly summary, wire it into the pipeline and the report, and add it to the trace."*
- *"Bring back an LLM longitudinal-narrative step that reasons over the harmonized trajectories, and add it to the orchestrator input."*

**Data & schema**

- *"Here's a new analyzer JSON format — update `corux/schemas.py` to match and convert the sample files."*
- *"Make the schema strict (reject unknown fields) and tell me which existing samples break."*

**UI & reporting**

- *"In the report, sort the markers table by severity (Dangerous first) and collapse all Normal markers behind a ‘show N normal’ toggle."*
- *"Bring the Next-panel card back to the sidebar, below Discussion points."*

**Traceability / certification**

- *"Add an optional verbose trace mode that records each agent's full structured input and output, gated behind an env var, and document it in the README."*
- *"Add token-cost estimation to the trace summary using the model's per-token pricing."*

When in doubt, ask Claude to *plan first*: *"Plan this change before editing, and flag anything that
could break existing behavior."*

---

## Testing

```bash
python3 -m pip install pytest
pytest        # deterministic steps run for real; agent calls are mocked (no API key needed)
```

Coverage includes: ingest/sorting, the PII firewall, the LOINC-keyed history series, the §5
harmonization math (e.g. `0.85 µkat/L → 51 U/L`), trajectory classification incl. the resolved-spike
peak, the report view-model, and a full pipeline smoke test with mocked agents.

---

## Configuration

All optional, via environment variables (or `.env`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | — | **Required.** Your Anthropic key. |
| `CORUX_MODEL` | `claude-opus-4-8` | Model for every agent. |
| `CORUX_PORT` | `8000` | Web app port. |
| `CORUX_STORE_DIR` | `data/store/` | Where per-patient records persist. |
| `CORUX_PATIENT_SALT` | `corux-dev-salt` | Salt for the `patient_key` hash — **override in production**. |

Per-step effort and `max_tokens` are tuned in [`corux/config.py`](corux/config.py).

---

## Data & privacy

- Input is **de-identified upstream** (pseudonymous id, no name/dob). The PII firewall (step 2)
  additionally keeps the `patient_id` out of every LLM prompt — only a salted hash is used, and only
  as a local storage key.
- The persisted store (`data/store/`) holds longitudinal records and is **git-ignored**. Treat it as
  PHI: set `CORUX_PATIENT_SALT` and secure the directory for any real use.
- CORUX is **decision-support only — not a diagnosis.** Every report carries that disclaimer.

---

## Publish this repo

Not in git yet? From inside the project folder:

```bash
cd corux
git init
git add .
git commit -m "Initial commit: CORUX lab-interpretation prototype"

# create the GitHub repo and push (requires the gh CLI, or create it in the browser):
gh repo create corux --private --source=. --push
# …or, after creating it manually on GitHub:
git remote add origin https://github.com/<your-username>/corux.git
git branch -M main
git push -u origin main
```

`.gitignore` already excludes `.env` and `data/store/` (your key and any PHI), so they won't be
committed.
