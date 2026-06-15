# Underwriting Workbench — Build Progress

## Current State (Session 3 End — June 2025)

### Architecture Pattern: Routing Agent
Single Orchestrator agent with tool functions that call deployed Vertex AI Agent Engines
via `agent_engines.get(id).stream_query()` for Classification and Extraction.
Rules Update, Client History, and UW Rules agents run locally as tool functions.

### Agents Built & Tested
| # | Agent | Status | Package | Deployed ID |
|---|-------|--------|---------|-------------|
| 1 | Classification Agent | ✅ Deployed & working | `classification_agent/` | `8020181410381824000` |
| 2 | Extraction Agent | ✅ Deployed & working | `extraction_agent/` | `5114233750821011456` |
| 6 | Rules Update Agent | ✅ Built, tested locally | `rules_update_agent/` | Not yet deployed |
| 4 | Client History Agent | ✅ Built, tested locally | `client_history_agent/` | Not yet deployed |
| 3 | UW Rules Agent | ✅ Built, tested locally | `uw_rules_agent/` | Not yet deployed |
| — | Orchestrator Agent | ✅ E2E working (with known issue) | `orchestrator_agent/` | Not yet deployed |

### Deployed Agent Engine IDs (Current)
- Classification: `projects/146646146609/locations/us-central1/reasoningEngines/8020181410381824000`
- Extraction: `projects/146646146609/locations/us-central1/reasoningEngines/5114233750821011456`

### Orchestrator E2E Test — Working with Known Issue
Full flow working: classify → approve → extract → fetch rules → fetch client history → evaluate UW rules → present result.

**Known Issue: EQ Zone and Flood Zone returning "No" instead of correct values.**
- The deployed Extraction Agent returns `eq_zone: "No"` and `flood_zone: "No"` in the unified JSON
- In earlier standalone tests, it returned `eq_zone: "Medium"` and `flood_zone: "High"`
- This is an extraction consistency issue — Gemini Flash returns different raw values each run
- The `_classify_zone()` merge logic in extraction_agent/tools.py may need to be more robust
- The UW Rules evaluation engine correctly scores whatever it receives — the input is wrong, not the scoring

**All other fields validated correctly:**
- Priority: P0 ✅ (Commercial Property base + sum insured override)
- Year Built: 2 (1987) ✅
- Construction: 1 (Non-Combustible) ✅
- Assignment: John Larsson ✅
- Client History: Found, High confidence ✅

### UW Rules Agent — Built ✅
- Single tool: `apply_uw_rules(extracted_fields_json, rules_json, client_history_json)`
- Evaluation engine parses rules JSON dynamically — no hardcoded rule values
- Handles: LoB priority, override rules (renewal days, sum insured, broker), risk scoring
  (year_built, eq_zone, flood_zone, construction_type), assignment mapping, auto-decline
- Tested locally with all scenarios: normal, Marine decline, old building decline, broker override

### Client History Agent — Built ✅
- Two-step lookup: (1) fuzzy match filenames, (2) confirm with identifiers inside JSON
- 3 tools: `get_client_history`, `create_client_history`, `update_client_history`
- Files stored as name-based slugs in `gs://underwriting-workbench/Client_history/`
- Identifiers for confirmation: fein, mailing_address, sic_code, broker, contact_person
- Match confidence: high (2+), medium (1), name_only (0), uncertain/low (provided but don't match)

### Rules Update Agent — Built ✅
- Reads business rules from Excel: `gs://underwriting-workbench/Rules/UW Workbench_Business Rules.xlsx`
- 4 tools: `get_rules`, `get_all_rules`, `update_rules`, `validate_rules`
- Parses 3 sheets: Priority, Risk Score, Assignment

### Key Technical Learnings (Session 3)

**LLM cannot reliably pass large JSON strings as tool arguments.**
- When the Orchestrator LLM tries to pass the full extracted JSON (11K chars) or rules JSON
  as a string argument to `evaluate_uw_rules`, it malforms the JSON (nested quote escaping issues).
- Error manifests as "Malformed function call" in ADK.
- The working version has the LLM pass the JSON, but it sometimes drops or changes field values.
- **Future fix needed**: Either (a) tools fetch their own data internally instead of receiving
  from LLM, or (b) use simpler individual field parameters instead of JSON blobs.

**ADK instruction curly braces are template variables.**
- `{variable}` in instruction strings gets parsed by ADK as session state lookups.
- Avoid curly braces in instructions — use plain text descriptions instead.

### Agents Not Yet Built
| # | Agent | Status |
|---|-------|--------|
| 5 | Submission Record Agent | ❌ Not started |

### Environment
- **Venv**: `/home/ec2-user/.cache/gcp/MLR_Usecase/agent/venv311/bin/activate` (Python 3.11.14)
- **ADK**: google-adk==1.28.0
- **Project**: gbu-demo-playground (project number: 146646146609)
- **Bucket**: underwriting-workbench
- **Location**: us-central1
- **Orchestrator model**: gemini-2.5-pro
- **Sub-agent model**: gemini-2.0-flash

### GCS Bucket Structure
```
gs://underwriting-workbench/
├── submissions/                          ← Test ACORD, Loss Run, Email files
├── Rules/
│   └── UW Workbench_Business Rules.xlsx  ← Priority, Risk Score, Assignment rules
└── Client_history/
    ├── greenfield-manufacturing.json
    ├── globex-corporation.json
    ├── johnson-co.json
    ├── labyrinth-labs.json
    ├── vehement-capitals.json
    └── precision-engineering.json
```

### Next Session TODO
1. Fix EQ Zone / Flood Zone extraction consistency issue
   - Query deployed Extraction Agent directly to see raw values
   - May need to improve `_classify_zone()` or extraction prompts
2. Fix LLM JSON passing issue for evaluate_uw_rules
   - Option: make evaluate_uw_rules fetch rules internally (no LLM passing)
   - Option: use individual field params instead of JSON blob
3. Deploy Rules Update + Client History + UW Rules agents to Vertex AI
4. Build Agent 5 — Submission Record Agent (BigQuery persistence)
