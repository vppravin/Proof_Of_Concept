# Smart Underwriting Workbench

AI-powered insurance submission processing system built on Google Cloud Platform.

---

## Architecture

| Component | Technology |
|---|---|
| Orchestrator | Vertex AI Agent Engine (Gemini 2.5 Pro) |
| Sub-Agents | Vertex AI Agent Engine (Gemini Flash) |
| Document Extraction | Document AI Form Parser |
| Data Store | BigQuery |
| File Storage | Google Cloud Storage |
| Auto-Trigger | Cloud Function + Eventarc (pending IAM) |
| Project | gbu-demo-playground |
| Region | us-central1 |

---

## Deployed Agents

| Agent | Engine ID | Purpose |
|---|---|---|
| Orchestrator | 8799392106847141888 | Routes to sub-agents, 17 tools |
| Classification | 2783005217145225216 | Classifies documents (ACORD 125/140/Loss Run/Email) |
| Extraction v2 | 8617150253566525440 | Document AI Form Parser — field extraction |
| Rules Update | 855464576630652928 | Reads business rules from Excel in GCS |
| Client History | 5943406255652470784 | Fuzzy matches client records in GCS |
| UW Rules | 4573186069024997376 | Python rules engine |
| Submission | 5466728382592974848 | BigQuery CRUD operations |

---

## Features

### 1. End-to-End Submission Processing
- Upload ACORD 125 + 140 PDFs to GCS
- Automatic classification with numeric confidence scores (0-100)
- Document AI extraction — 100% field accuracy (FEIN, SIC, contact, phone, email, stories, sum insured)
- Business rules evaluation from Excel in GCS
- Client history lookup with fuzzy matching
- Risk scoring (Year Built, EQ Zone, Flood Zone, Construction Type)
- Priority assignment (P0-P4) with broker/sum insured/renewal overrides
- Underwriter auto-assignment based on LoB + priority
- Auto-decline checks (Marine LoB, pre-1970 buildings)
- Save to BigQuery with generated Case ID

### 2. Confidence-Based Classification
- All files confidence ≥ 80 → auto-approve, proceed immediately
- Any file confidence < 80 → save as "Pending Classification" in BigQuery
- Underwriter reviews and approves/corrects before processing continues

### 3. Underwriter Dashboard & Workload
- "Show me the dashboard" → all submissions with status
- "What are my submissions?" → filtered by underwriter
- Smart prioritization with urgency scores (priority + effective date + risk + sum insured)
- RAG status (Red/Amber/Green) based on urgency
- "What should I work on first?" → top-ranked recommendation

### 4. Deterministic Justification
- "Why is this P0?" → traces every rule decision
- "Explain the risk score" → shows factor-by-factor breakdown
- "Justify NB-26-XXXXX" → full report: priority, risk, assignment, auto-decline
- Runs as direct Python — 100% accurate, no LLM hallucination

### 5. Accept/Decline Workflow
- "Accept NB-26-XXXXX" / "Decline NB-26-XXXXX"
- Records decision, decision_by, decision_at in BigQuery
- Auto-suggests next submission after decision

### 6. Review Status Tracking
- Pending → In Review → Reviewed → Complete
- "Start reviewing NB-26-XXXXX" → marks In Review
- "Mark as reviewed" → updates status

### 7. Error Handling & Retry (Tested ✅)
- Processing errors auto-logged to BigQuery at Python level (no LLM dependency)
- Captures: error step, error message, last successful step, partial data
- Auto-resolve on successful retry
- Tested: fetch_rules failure → logged → retry → auto-resolved
- "Show me failed submissions" → lists unresolved errors
- "Retry [folder]" → re-processes from start
- Corrupt/irrelevant files → low confidence → pending → reject

### 8. Auto-Trigger (Pending IAM Permission)
- Cloud Function + Eventarc
- New files in `gs://underwriting-workbench/Input_Files/` → auto-process
- Deduplication: checks `_extracted_fields.json` before processing
- Blocker: Pub/Sub Publisher role needed on GCS service account

---

## GCS Bucket Structure

```
gs://underwriting-workbench/
├── Input_Files/
│   ├── Sample 1/  (Johnson Textiles — ACORD 125 + 140)
│   ├── Sample 2/  (Thomson Steels)
│   └── Sample 3/  (Vortis Automobiles)
├── Rules/UW Workbench_Business Rules.xlsx
├── Client_history/*.json  (6 client records)
├── location_risk/location_risk_data.json  (60 zip codes)
└── agent_engine/  (deployment artifacts)
```

---

## BigQuery Tables

### underwriting_workbench.submissions (33 fields)
case_id, created_on, insured_name, mailing_address, fein, sic_code, lob, effective_date, expiration_date, renewal_days, broker, proposed_carrier, sum_insured, no_of_employees, year_built, construction_type, eq_zone, flood_zone, risk_score, risk_level, priority, override_reasons, assigned_to, status, decision, decision_by, decision_at, auto_decline, decline_reason, extracted_json, uw_result_json, gcs_folder, review_status

### underwriting_workbench.processing_errors (11 fields)
error_id, gcs_folder, error_step, error_message, last_successful_step, partial_data, retry_count, created_on, resolved, resolved_at, resolved_by

---

## Orchestrator Tools (17)

| Tool | Method | Purpose |
|---|---|---|
| classify_submission | stream_query | Classify documents via Gemini Flash |
| extract_submission | stream_query | Extract fields via Document AI |
| fetch_rules | stream_query | Read business rules from GCS Excel |
| fetch_client_history | stream_query | Fuzzy match client records |
| evaluate_uw_rules | Direct Python | Apply UW rules engine |
| save_submission | Direct Python | Save to BigQuery |
| get_submission | Direct Python | Retrieve submission by Case ID |
| list_submissions | Direct Python | List/filter submissions |
| update_submission | Direct Python | Update submission fields |
| record_decision | Direct Python | Record accept/decline |
| justify_submission | Direct Python | Deterministic justification |
| get_prioritized_workload | Direct Python | Smart ranking with urgency |
| update_review_status | Direct Python | Track review progress |
| log_processing_error | Direct Python | Log errors to BigQuery |
| get_processing_errors | Direct Python | List failed submissions |
| resolve_processing_error | Direct Python | Mark errors resolved |
| save_pending_classification | Direct Python | Save low-confidence cases |

---

## Underwriters (12)

| LoB | P0 | P1-P3 | P4 |
|---|---|---|---|
| Commercial Property | John Larsson | Harry Wills | Mary Thomas |
| Workers Compensation | Tom Smith | Annie George | Merin John |
| Cyber | Katty Mathew | Basil Joy | — |
| Commercial Liability | Kane William | Peter Kings | — |
| Rest of LoB | Ruby keth | Tony Sams | — |

---

## Service Account
`146646146609-compute@developer.gserviceaccount.com` — BigQuery dataEditor, GCS access, Vertex AI Agent Engine

---

## TODO

### Blocked
- [ ] Deploy Cloud Function auto-trigger (blocked on Pub/Sub Publisher IAM)

### Features to Evaluate
- [ ] Decision notes — underwriter adds reason for accept/decline (audit requirement)
- [ ] Reassign submission — transfer to another underwriter
- [ ] GCS signed URL — view actual PDF from chat
- [ ] Submission timeline/history — event log per case (Created → Classified → Assigned → Accepted)
- [ ] Notifications — email/alert when new work arrives or approval needed
- [ ] Bulk operations — accept all Low Risk, reassign all P0
- [ ] Multi-underwriter awareness — leave/availability, auto-reassign

### Future Enhancements
- [ ] Custom UI (two paths — see UI Options below)
- [ ] Vertex AI Datastore (BigQuery sync for grounded chat)
- [ ] Add .docx/.xlsx support (Broker Spec, SOV, Loss Run spreadsheets)
- [ ] Client history — tighten fuzzy matching
- [ ] SLA/RAG dashboard
- [ ] Premium calculation / Rating Engine integration

---

## UI Options (Next Phase)

### Path 1: Gemini Enterprise Web App + A2UI Components (Preferred)
- Register our orchestrator as an A2A + A2UI agent with Gemini Enterprise
- Dashboard tables, cards, buttons rendered as A2UI components inside Gemini Enterprise chat
- Underwriters access via Gemini Enterprise web app URL (standalone, not Cloud Console)
- No custom app to build or host — everything lives inside Gemini Enterprise
- **Status:** A2UI is in Preview (pre-GA)
- **Docs:**
  - [Register A2UI agents](https://docs.cloud.google.com/gemini/enterprise/docs/a2ui-agents/register-and-manage-an-a2ui-agent)
  - [A2UI Component Gallery](https://docs.cloud.google.com/gemini/enterprise/docs/a2ui-agents/a2ui-component-gallery-reference)
  - [Cloud Run Tutorial](https://docs.cloud.google.com/gemini/enterprise/docs/a2ui-agents/tutorial-host-agent-cloud-run)
  - [Register A2A agents](https://docs.cloud.google.com/gemini/enterprise/docs/register-and-manage-an-a2a-agent)
- **Components available:** Row, Column, List, Tabs, Text, Image, Icon, Divider, Button, TextField, CheckBox, Card, Modal

### Path 2: Custom UI + Orchestrator API
- Build custom React/Angular frontend hosted on Cloud Run
- Left panel: Dashboard (BigQuery data — submissions, charts, stats)
- Right panel: Chat component calling orchestrator via Vertex AI `streamQuery` REST API
- Resizable panels
- Full control over branding, layout, features
- **API Endpoint:** `POST https://us-central1-aiplatform.googleapis.com/v1beta1/projects/146646146609/locations/us-central1/reasoningEngines/8799392106847141888:streamQuery`
- **Auth:** Google OAuth / Service Account
- **Hosting:** Cloud Run / App Engine / GKE

---

*Last updated: 2026-05-01*
