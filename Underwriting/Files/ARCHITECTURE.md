# Smart Underwriting Workbench — GCP Native POC
## Complete Architecture & Design Document
**Version:** 2.1 | **Date:** August 2025 | **Cloud:** Google Cloud Platform

---

## 1. Project Goal

Build a **GCP-native AI-powered Underwriting Workbench** where insurance underwriters can upload submission documents (PDFs, Excel, images, emails) inside **Gemini Enterprise UI** and get back a fully processed result — priority, risk score, underwriter assignment, client history, and a final Accept/Decline recommendation — all inside a single chat session.

**No custom UI. No separate portal. No manual data entry.**

---

## 2. The Big Picture

```
Broker sends submission documents
        ↓
Underwriter opens Gemini Enterprise UI (existing Google Workspace app)
        ↓
Uploads file + types "Process this submission"
        ↓
Vertex AI Orchestrator Agent takes over
        ↓
Orchestrator → Doc Classification Agent classifies each file
        ↓
Orchestrator presents classification to underwriter for approval
        ↓
Underwriter approves (or corrects)
        ↓
Orchestrator → Extraction Agent extracts fields using approved types
        ↓
Orchestrator → remaining sub-agents score, fetch history, assign, save
        ↓
Underwriter sees full summary in chat
        ↓
Types "accept" or "decline"
        ↓
Done. Case saved. Broker notified.
```

---

## 3. What We Are Building

### Building (POC Scope)
- Vertex AI Orchestrator Agent + 6 Sub-Agents (tools embedded inside each agent — no separate MCP servers)
- Document classification with human-in-the-loop approval (Doc Classification Agent)
- Document extraction using Gemini Flash multimodal (multi-file submission support)
- Priority, Risk Score, Assignment rules engine (from business rules JSON in GCS)
- Client history fetch (mocked from GCS)
- Submission record persistence in BigQuery
- Rules management via natural language (Rules Update Agent)
- Full integration with Gemini Enterprise UI

---

## 4. GCP Services — What, Why, Why Not Others

---

### 4.1 Gemini Enterprise UI (Google Workspace)

**What:** The chat interface where underwriters interact with the system.

---

### 4.2 Vertex AI Agent Builder — Orchestrator + Sub-Agents

**What:** GCP's native platform for building, deploying, and connecting AI agents. Hosts the orchestrator and all 6 sub-agents. Each agent has its own tools defined as embedded Python functions — no separate MCP servers or Cloud Run services needed.

**Why Vertex AI Agent Builder:**
- Native integration with Gemini Enterprise UI — one configuration to publish the agent into the chat
- Supports multi-agent orchestration natively — orchestrator can call sub-agents as tools
- No infrastructure to manage — fully serverless
- Built-in conversation memory within a session
- Supports tool/function calling out of the box

---

### 4.3 Gemini 2.0 Pro — Only for Orchestrator Agent

**What:** The LLM powering the Orchestrator Agent.

**Why Pro:**
- Orchestrator does complex multi-step reasoning — reads extracted JSON, decides which sub-agent to call next, combines results from multiple agents, forms a coherent final response
- Pro handles long context, complex reasoning chains, and nuanced decision making better than Flash
- The orchestrator is the brain — it needs the most capable model

**Why not Flash for orchestrator:**
- Flash is optimized for speed and single focused tasks
- Orchestration requires reasoning across multiple data sources simultaneously — Flash can miss nuance

---

### 4.4 Gemini 2.0 Flash — Sub-Agent Model

**What:** The LLM powering all 6 sub-agents.

**Why Flash:**
- Each sub-agent does one focused task — classify documents, extract fields, apply rules, fetch data, write record, manage rules
- Flash is faster and cheaper than Pro
- Flash supports multimodal input (PDFs, images) natively — critical for extraction agent
- For focused single-purpose tasks Flash performs on par with Pro at a fraction of the cost

---

### 4.5 Cloud Storage (GCS)

**What:** Stores three categories of files:
1. Raw uploaded submission files (PDFs, Excel, images, Word docs)
2. Business rules JSON files (priority, risk score, assignment rules)
3. Mock client history JSON files (Insurance Middle Office — mock data from GCS for POC)

**Why GCS for rules files:**
- Rules are JSON files that rarely change
- Storing in GCS means rules can be updated by editing a file — no code deployment needed
- Agent reads the file at runtime — always gets the latest rules
- No database overhead for static reference data

**Why GCS for client mock data:**
- In POC, client history is static — it doesn't change between requests
- Simple JSON files per client — no query complexity needed

---

### 4.6 BigQuery

**What:** Stores processed submission records — the output after the agent has extracted, scored, and assigned a submission.

**Why BigQuery:**
- Submission records are append-heavy, read-light — a perfect fit for BigQuery's columnar storage
- Native JSON column support — handles varying fields across LoB without schema pain
- Serverless — no instance to manage, scales automatically
- Built-in analytics: underwriting managers can run SQL queries across all submissions with zero extra infrastructure
- Streaming inserts via BigQuery Storage Write API — low latency writes suitable for agent tool calls
- Cost: ~$5/TB queried, storage ~$0.02/GB/month — negligible for POC volume
- Single store for both operational record-keeping and future analytics — no need to migrate data later

---

### 4.7 Secret Manager

**What:** Stores API keys, service account credentials, any sensitive config.

---

---

## 5. Agent Architecture — Detailed

```
┌─────────────────────────────────────────────────────────────┐
│                  Gemini Enterprise UI                        │
│         (Underwriter's existing Google Workspace)           │
└─────────────────────┬───────────────────────────────────────┘
                      │ chat input + file upload
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              ORCHESTRATOR AGENT                              │
│              Model: Gemini 2.0 Pro                          │
│                                                             │
│  - Receives underwriter input                               │
│  - Decides which sub-agents to call and in what order       │
│  - Passes data between sub-agents                           │
│  - Handles human approval loop for classification           │
│  - Compiles final response                                  │
│  - Handles follow-up questions in same session              │
└──┬────────┬──────────┬──────────┬──────────┬──────────┬─────┘
   │        │          │          │          │          │
   ▼        ▼          ▼          ▼          ▼          ▼
┌──────┐┌──────┐┌───────┐┌───────┐┌───────┐┌───────────┐
│DOC   ││EXTRAC││UW     ││CLIENT ││SUBMIS ││RULES      │
│CLASS ││-TION ││RULES  ││HISTORY││RECORD ││UPDATE     │
│      ││      ││       ││       ││       ││           │
│Flash ││Flash ││Flash  ││Flash  ││Flash  ││Flash      │
│2.0   ││2.0   ││2.0    ││2.0    ││2.0    ││2.0        │
│      ││      ││       ││       ││       ││           │
│Tools:││Tools:││Tools: ││Tools: ││Tools: ││Tools:     │
│inline││inline││inline ││inline ││inline ││inline     │
└──┬───┘└──┬───┘└──┬────┘└──┬────┘└──┬────┘└──┬────────┘
   │       │       │        │        │        │
   ▼       ▼       ▼        ▼        ▼        ▼
  GCS    GCS     GCS      GCS    BigQuery   GCS
 (files) (files) (rules)  (client)          (rules)

 No MCP servers. No Cloud Run for tools.
 All tools are Python functions embedded inside each agent.
 All agent-to-agent handoffs go through the Orchestrator.
 Flow: Orchestrator → Classification → Orchestrator → Human Approval
     → Orchestrator → Extraction → Orchestrator → remaining agents
```

---

## 6. Sub-Agent Details

---

### Agent 1 — Doc Classification Agent (NEW)

**Responsibility:** Validate and classify uploaded submission documents before extraction. Reads the first page of each file to determine its type, presents classification to the user for approval, and on approval invokes the Extraction Agent directly (A2A — no orchestrator in between).

**Model:** Gemini 2.0 Flash (multimodal)

**Tools (embedded Python functions):**
- `list_submission_files(gcs_folder_uri)` — lists all files in a GCS submission folder with filenames and sizes
- `classify_document(gcs_uri)` — reads the first page of a document using Gemini Flash multimodal, classifies it as one of: `ACORD`, `LOSS_RUN`, `EMAIL`, `UNKNOWN`
- `classify_submission(gcs_folder_uri)` — orchestrates: lists all files → classifies each → returns classification summary for human review

**Classification Flow:**
```
classify_submission(gs://bucket/submissions/NB-25-34677/)
  │
  ├─ Step 1: LIST all files in folder
  │   → ACORD_125_140_NB-25-34677.pdf, LossRun_NB-25-34677.pdf, Email_Transcript_NB-25-34677.txt
  │
  ├─ Step 2: CLASSIFY each file (read first page only, not full document)
  │   → ACORD_125_140_NB-25-34677.pdf → ACORD
  │   → LossRun_NB-25-34677.pdf → LOSS_RUN
  │   → Email_Transcript_NB-25-34677.txt → EMAIL
  │
  ├─ Step 3: PRESENT to user for approval
  │   → "I found 3 files. Here's how I classified them:
  │       1. ACORD_125_140_NB-25-34677.pdf → ACORD
  │       2. LossRun_NB-25-34677.pdf → LOSS_RUN
  │       3. Email_Transcript_NB-25-34677.txt → EMAIL
  │      Do you approve this classification?"
  │
  ├─ Step 4a: USER APPROVES → returns approved classification to Orchestrator
  │   → Orchestrator then calls Extraction Agent with approved types
  │
  └─ Step 4b: USER REJECTS / CORRECTS → update classification per user input → re-present → loop
```

**Human-in-the-Loop:**
- Agent always waits for explicit human approval before proceeding to extraction
- If user says "No, that PDF is a Loss Run not an ACORD", the agent updates the classification and re-presents
- User corrections override the AI classification — the corrected type is passed to the Extraction Agent

**Handoff to Extraction Agent (via Orchestrator):**
- Once approved, the Orchestrator passes the approved classification to the Extraction Agent
- All agent-to-agent handoffs go through the Orchestrator — no direct agent-to-agent calls
- Orchestrator passes: GCS folder URI + approved classification map (filename → type)

**Supported File Types (current scope):**

| Classification | Description |
|---|---|
| ACORD | ACORD 125/140 insurance application forms |
| LOSS_RUN | Loss run / claims history reports |
| EMAIL | Email transcripts, broker communications |
| UNKNOWN | Unrecognized — flagged for user to classify manually |

**Input:** GCS folder URI (e.g. `gs://bucket/submissions/NB-25-34677/`)

**Output (to user for approval):**
```json
{
  "folder": "gs://bucket/submissions/NB-25-34677/",
  "file_count": 3,
  "classifications": [
    {"filename": "ACORD_125_140_NB-25-34677.pdf", "gcs_uri": "gs://...", "classified_as": "ACORD", "confidence": "High"},
    {"filename": "LossRun_NB-25-34677.pdf", "gcs_uri": "gs://...", "classified_as": "LOSS_RUN", "confidence": "High"},
    {"filename": "Email_Transcript_NB-25-34677.txt", "gcs_uri": "gs://...", "classified_as": "EMAIL", "confidence": "High"}
  ],
  "status": "awaiting_approval"
}
```

**Output (to Extraction Agent after approval):**
```json
{
  "folder": "gs://bucket/submissions/NB-25-34677/",
  "approved_classifications": {
    "ACORD_125_140_NB-25-34677.pdf": "ACORD",
    "LossRun_NB-25-34677.pdf": "LOSS_RUN",
    "Email_Transcript_NB-25-34677.txt": "EMAIL"
  }
}
```

---

### Agent 2 — Extraction Agent

**Responsibility:** Read uploaded submission documents (multiple files per submission) and extract all structured fields into a unified JSON. Receives pre-classified file types from the Doc Classification Agent — does not classify files itself.

**Model:** Gemini 2.0 Flash (multimodal)

**Tools (embedded Python functions — no MCP server):**
- `list_submission_files(gcs_folder_uri)` — lists all files in a GCS submission folder
- `read_submission_file(gcs_uri)` — confirms a single file exists in GCS and is readable
- `extract_fields(gcs_uri, file_type)` — applies type-specific prompt based on pre-classified type, calls Gemini Flash multimodal, returns structured JSON
- `process_submission(gcs_folder_uri, classifications)` — orchestrates full multi-file extraction using the approved classification map: lists files → extracts each with type-specific prompts → merges into unified JSON

**Multi-File Processing Flow:**
```
process_submission(gs://bucket/submissions/NB-25-34677/, classifications)
  │
  ├─ Step 1: LIST all files in folder
  │   → ACORD.pdf, LossRun.pdf, Email.txt
  │
  ├─ Step 2: USE PRE-CLASSIFIED TYPES (from Doc Classification Agent)
  │   → No self-classification — types already approved by human
  │
  ├─ Step 3: EXTRACT from each file using TYPE-SPECIFIC PROMPT
  │   → ACORD → insured_name, lob, broker, locations, coverage, hazards
  │   → Loss Run → loss_history array
  │   → Email → additional context, clarifications, urgency
  │
  └─ Step 4: MERGE all extractions into ONE unified JSON
      → Priority: ACORD > Email
      → Returns single consolidated output
```

**Supported File Types (current scope — 3 types, pre-classified by Doc Classification Agent):**

| Document Type | Typical Format | Fields Extracted |
|---|---|---|
| ACORD Form | PDF | insured_name, lob, broker, locations, coverage, hazards, employees |
| Loss Run Report | PDF | loss_history array (date, description, amount, status, claim_number) |
| Email / Transcript | TXT, PDF | additional context, clarifications, urgency notes |

**Input:** GCS folder URI of uploaded submission (e.g. `gs://bucket/submissions/NB-25-34677/`)

**Output (unified JSON):**
```json
{
  "submission_id": "NB-25-34677",
  "insured_name": "Greenfield Manufacturing LLC",
  "lob": "Commercial Property",
  "broker": "Pinnacle Commercial Insurance Group",
  "effective_date": "2025-08-01",
  "sum_insured": 29480000,
  "renewal_days": 24,
  "year_built": 1979,
  "construction_type": "Ordinary",
  "eq_zone": "Medium",
  "flood_zone": "High",
  "roof_type": "Built-up",
  "fire_protection": "Central station + Sprinklers",
  "no_of_employees": 299,
  "loss_history": [
    {"date": "2020-09-14", "description": "CNC press hydraulic failure", "amount": 47200, "status": "Closed", "claim_number": "CLM-2020-83741"},
    {"date": "2021-03-22", "description": "Sprinkler freeze water damage", "amount": 138500, "status": "Closed", "claim_number": "CLM-2021-91034"}
  ],
  "locations": [
    {"loc_number": 1, "address": "4820 Industrial Pkwy, Columbus, OH 43228", "occupancy": "Manufacturing", "building_value": 8500000, "contents_value": 3200000},
    {"loc_number": 2, "address": "7710 Westbelt Drive, Columbus, OH 43228", "occupancy": "Warehouse", "building_value": 3100000, "contents_value": 1850000},
    {"loc_number": 3, "address": "920 Chartiers Ave, Carnegie, PA 15106", "occupancy": "Distribution", "building_value": 4200000, "contents_value": 980000}
  ],
  "broker_requirements": {"target_premium_min": 165000, "target_premium_max": 185000, "endorsements": ["Agreed Value", "Utility Services", "Ordinance or Law", "Equipment Breakdown", "Flood sub-limit"]},
  "additional_context": {"urgency": "Bind by 2025-08-01", "notes": "Incumbent non-renewed; $400K+ facility upgrades completed"},
  "files_processed": [{"file": "ACORD_125_140_NB-25-34677.docx", "type": "ACORD", "status": "extracted"}, "..."]
}
```

**Handles:** PDF, Excel, Word, scanned images, email text

---

### Agent 3 — UW Rules Agent

**Responsibility:** Apply all three business rule sets — Priority, Risk Score, Assignment. Contains no hardcoded rule logic — reads rules from GCS JSON files at runtime.

**Model:** Gemini 2.0 Flash

**Tools (embedded Python functions — no MCP server):**
- `apply_priority(extracted_fields)` — reads `rules/priority_rules.json` from GCS, evaluates extracted fields, returns priority
- `apply_risk_score(extracted_fields)` — reads `rules/risk_score_rules.json` from GCS, evaluates fields, returns score + risk level
- `apply_assignment(priority, lob)` — reads `rules/assignment_rules.json` from GCS, returns assigned underwriter

**How it works:**
- Agent receives extracted JSON from Orchestrator
- Calls `apply_priority` — reads priority_rules.json from GCS and evaluates
- Calls `apply_risk_score` — reads risk_score_rules.json from GCS and evaluates
- Calls `apply_assignment` — reads assignment_rules.json from GCS and evaluates
- Returns combined output to Orchestrator

**No inbuilt rule logic — all rule evaluation reads from GCS JSON files at runtime.**

**Input:** Extracted JSON from Extraction Agent + client history from Client History Agent

**Rules Applied:**

Priority Rules:
```
LoB = Commercial Property → P0
LoB = Workers Compensation → P1
LoB = Cyber → P2
LoB = Liability → P3
LoB = Rest of LoB → P4
LoB = Marine → Decline
Renewal days < 5 → P0 (override)
Sum Insured > $10M → P0 (override)
Broker = Marsh / Aon / AJG → P0 (override)
```

Risk Score Rules:
```
Year Built after 2010 → 0
Year Built 1990-2010 → 1
Year Built 1980-1990 → 2
Year Built 1970-1980 → 3
Year Built before 1970 → Decline

EQ Zone No → 0 | Low → 1 | Medium → 2 | High → 3
Flood Zone No → 0 | Low → 1 | Medium → 2 | High → 3
Construction Fire-resistive → 0 | Non-combustible → 1 | Ordinary → 2 | Heavy timber → 3

Total Score = sum of all four scores
```

Assignment Rules:
```
P0 - Commercial Property → John Larsson
P1 to P3 - Commercial Property → Harry Wills
P4 - Commercial Property → Mary Thomas
P0 - Workers Compensation → Tom Smith
P1 to P3 - Workers Compensation → Annie George
P4 - Workers Compensation → Merin John
P0 - Cyber → Katty Mathew
P1 to P4 - Cyber → Basil Joy
P0 - Commercial Liability → Kane William
P1 to P4 - Commercial Liability → Peter Kings
P0 - Rest of LoB → Ruby Keth
P1 to P4 - Rest of LoB → Tony Sams
```

**Output:**
```json
{
  "priority": "P2",
  "risk_score": 6,
  "risk_level": "Medium Risk",
  "assigned_to": "Mathew Ben",
  "assignee_id": "10086",
  "auto_decline": false,
  "decline_reason": null
}
```

---

### Agent 4 — Client History Agent

**Responsibility:** Fetch existing client history — what the insurance company already knows about this insured.

**Model:** Gemini 2.0 Flash

**Tools (embedded Python functions — no MCP server):**
- `get_client_history(client_id)` — reads `client_data/{client-id}.json` from GCS, returns client history JSON

**Input:** Insured name / client ID from orchestrator

**Output:**
```json
{
  "client_id": "amerijet-international",
  "total_premium_collected": 256000,
  "claims_paid": 3400,
  "potential_hazard": "Nil",
  "previous_risk_score": "Good",
  "active_policies": 2
}
```
---

### Agent 5 — Submission Record Agent

**Responsibility:** Persist the processed submission to BigQuery. Read back submissions on request. Update status on Accept/Decline.

**Model:** Gemini 2.0 Flash

**Tools (embedded Python functions — no MCP server):**
- `bq_read_submission(case_id)` — fetches submission row from BigQuery by case ID
- `bq_write_submission(submission_data)` — inserts full submission record into BigQuery via Storage Write API
- `bq_update_status(case_id, status, decision_by)` — updates submission status (Accepted/Declined) via BigQuery DML

**Input:** Full processed submission data from orchestrator

**BigQuery Table Schema (`uw_workbench.submissions`):**
```json
{
  "case_id": "NB-25-34677",
  "created_at": "2025-02-24T08:20:50Z",
  "insured_name": "Amerijet International",
  "lob": "Commercial Property",
  "broker": "Aon",
  "effective_date": "2025-03-20",
  "sum_insured": 480000,
  "priority": "P2",
  "risk_score": 6,
  "risk_level": "Medium Risk",
  "assigned_to": "Mathew Ben",
  "assignee_id": "10086",
  "status": "Pending",
  "client_history": "<JSON string>",
  "extracted_fields": "<JSON string>",
  "loss_history": "<JSON string>",
  "processed_at": "2025-02-24T08:21:30Z"
}
```

---

### Agent 6 — Rules Update Agent

**Responsibility:** Manage CRUD operations on business rules stored in GCS. Allows underwriting managers to view, add, modify, and delete rules via natural language in the Gemini chat UI.

**Model:** Gemini 2.0 Flash

**Tools (embedded Python functions — no MCP server):**
- `get_rules(rule_type)` — reads a rules JSON file from GCS (`priority_rules.json`, `risk_score_rules.json`, or `assignment_rules.json`) and returns the current rules
- `update_rules(rule_type, updated_rules_json)` — validates and writes updated rules JSON back to GCS, replacing the existing file
- `validate_rules(rule_type, rules_json)` — validates the JSON structure matches the expected schema before saving (prevents broken rules)
- `get_rules_history(rule_type)` — lists GCS object versions for a rules file so managers can see what changed and when (requires GCS object versioning enabled)

**Why this agent exists:**
- Business rules change frequently in insurance — new LoB, new underwriters, threshold adjustments
- Without this agent, every rule change requires a developer or manual GCS access
- With this agent, business users manage rules through natural language in the same Gemini UI

**Example interactions:**
```
👤 Manager: "Show me the current priority rules"
🤖 Agent: [calls get_rules("priority") → returns current rules JSON formatted as readable table]

👤 Manager: "Add a new priority rule: LoB = Aviation should be P2"
🤖 Agent: [calls get_rules → modifies → validate_rules → update_rules → confirms change]

👤 Manager: "Change the assignment for P0 Cyber from Katty Mathew to Sarah Chen"
🤖 Agent: [calls get_rules("assignment") → modifies → validate_rules → update_rules → confirms]

👤 Manager: "Remove the Marine auto-decline rule"
🤖 Agent: [calls get_rules("priority") → removes Marine rule → validate_rules → update_rules]

👤 Manager: "What changes were made to the risk score rules this month?"
🤖 Agent: [calls get_rules_history("risk_score") → returns version history with timestamps]
```

**Input:** Natural language request from underwriting manager via orchestrator

**Output:** Confirmation of rule change with before/after comparison, or current rules display

**Safety:**
- Always validates JSON structure before writing
- Returns before/after diff to the manager for confirmation
- GCS object versioning provides automatic rollback capability

---

## 7. GCS Bucket Structure

```
gs://uw-workbench-poc/
│
├── submissions/
│   └── NB-25-34677/
│       ├── ACORD_125_140_NB-25-34677.docx     ← ACORD application
│       ├── LossRun_NB-25-34677.xlsx           ← Loss run report
│       ├── SOV_NB-25-34677.xlsx               ← Schedule of values
│       ├── SupplementalRisk_NB-25-34677.docx  ← Risk questionnaire
│       ├── BrokerSpec_NB-25-34677.docx        ← Broker cover letter
│       └── EmailTranscript_NB-25-34677.txt    ← Email thread
│
├── rules/                                     ← GCS object versioning ENABLED
│   ├── priority_rules.json                    ← priority business rules
│   ├── risk_score_rules.json                  ← risk scoring rules
│   └── assignment_rules.json                  ← underwriter assignment rules
│
└── client_data/
    ├── amerijet-international.json            ← mock Insurance Middle Office data
    ├── greenfield-manufacturing.json
    ├── labyrinth-labs.json
    ├── globex-corporation.json
    ├── johnson-co.json
    └── vehement-capitals.json
```

**Note:** GCS object versioning is enabled on the `rules/` prefix to support the Rules Update Agent's `get_rules_history` tool. Every rule update creates a new version — previous versions are retained for audit and rollback.

---

## 8. Complete End-to-End Dry Run

**Scenario:** Underwriter processes Amerijet International submission

---

**T=0 — Underwriter action**
```
Underwriter opens Gemini Enterprise UI
Types: "Process this submission"
Attaches: Amerijet_ACORD_Form.pdf
```

---

**T=1 — Gemini UI → Orchestrator**
```
Gemini Enterprise UI detects the UW Workbench agent is registered
Routes the message + file to Vertex AI Orchestrator Agent
Orchestrator receives: user message + file reference
```

---

**T=2 — Orchestrator → GCS**
```
Orchestrator saves uploaded file to GCS:
gs://uw-workbench-poc/submissions/NB-25-34677/Amerijet_ACORD_Form.pdf

Generates case ID: NB-25-34677
```

---

**T=3 — Orchestrator calls Doc Classification Agent**
```
Orchestrator → Doc Classification Agent
Input: gs://uw-workbench-poc/submissions/NB-25-34677/

Doc Classification Agent calls embedded tool: classify_submission(gcs_folder_uri)
  - Lists all files in the submission folder
  - Reads first page of each file using Gemini Flash multimodal
  - Classifies each file by content (not filename)

Output → presented to underwriter in chat:
```

```
🤖 Gemini Agent:

I found 3 files in this submission. Here’s my classification:

  1. ACORD_125_140_NB-25-34677.pdf  →  ACORD (insurance application)
  2. LossRun_NB-25-34677.pdf        →  LOSS_RUN (claims history)
  3. Email_Transcript_NB-25-34677.txt →  EMAIL (broker communication)

Do you approve this classification? If any file is misclassified,
please let me know and I’ll correct it.
```

---

**T=3.5 — Human Approval**
```
👤 Underwriter: "Yes, looks correct. Proceed."
```

---

**T=4 — Orchestrator calls Extraction Agent with approved classification**
```
Orchestrator → Extraction Agent
Input: gs://uw-workbench-poc/submissions/NB-25-34677/ + approved classification map

Extraction Agent calls embedded tool: process_submission(gcs_folder_uri, classifications)
  - Uses pre-classified types (no self-classification)
  - Extracts fields from each file using type-specific prompts via Gemini Flash
  - Merges all extractions into one unified JSON

Output → back to Orchestrator:
{
  "insured_name": "Amerijet International",
  "lob": "Commercial Property",
  "broker": "Aon",
  "sum_insured": 480000,
  "renewal_days": 47,
  "year_built": 2010,
  "construction_type": "Non-Combustible",
  "eq_zone": "Medium",
  "flood_zone": "High",
  "loss_history": [...],
  "locations": [...],
  ...
}
```

---

**T=5 — Orchestrator calls Client History Agent**
```
Orchestrator → Client History Agent
Input: "Amerijet International"

Client History Agent calls embedded tool: get_client_history("amerijet-international")
Reads: gs://uw-workbench-poc/client_data/amerijet-international.json

Output → back to Orchestrator:
{
  "total_premium_collected": 256000,
  "claims_paid": 3400,
  "potential_hazard": "Nil",
  "previous_risk_score": "Good"
}
```

---

**T=6 — Orchestrator calls UW Rules Agent**
```
Orchestrator → UW Rules Agent
Input: extracted JSON + client history JSON

UW Rules Agent calls embedded tool: apply_priority(extracted_fields)
  Reads priority_rules.json from GCS
  LoB = Commercial Property → base P0
  Broker = Aon → P0 confirmed
  Renewal days = 47 → no override
  Sum insured = $480K → no override
  Final Priority = P0

UW Rules Agent calls embedded tool: apply_risk_score(extracted_fields)
  Reads risk_score_rules.json from GCS
  Year Built 2010 → score 0
  EQ Zone Medium → score 2
  Flood Zone High → score 3
  Construction Non-Combustible → score 1
  Total Risk Score = 6 → Medium Risk
  Auto decline? No

UW Rules Agent calls embedded tool: apply_assignment("P0", "Commercial Property")
  Reads assignment_rules.json from GCS
  P0 + Commercial Property → John Larsson (10012)

Output → back to Orchestrator:
{
  "priority": "P0",
  "risk_score": 6,
  "risk_level": "Medium Risk",
  "assigned_to": "John Larsson",
  "assignee_id": "10012",
  "auto_decline": false
}
```

---

**T=7 — Orchestrator calls Submission Record Agent**
```
Orchestrator → Submission Record Agent
Input: all combined data

Submission Record Agent calls embedded tool: bq_write_submission(submission_data)
Inserts row into BigQuery table: uw_workbench.submissions
{
  "case_id": "NB-25-34677",
  "insured_name": "Amerijet International",
  "lob": "Commercial Property",
  "broker": "Aon",
  "priority": "P0",
  "risk_score": 6,
  "risk_level": "Medium Risk",
  "assigned_to": "John Larsson",
  "assignee_id": "10012",
  "status": "Pending",
  ...
}

Output → back to Orchestrator: "Saved successfully"
```

---

**T=8 — Orchestrator compiles and responds to Gemini UI**
```
Orchestrator combines all outputs and sends final response
to Gemini Enterprise UI chat window:
```

```
🤖 Gemini Agent:

I've processed the submission for Amerijet International.
Here's the full summary:

─────────────────────────────────────
SUBMISSION SUMMARY
─────────────────────────────────────
Case ID         : NB-25-34677
Insured         : Amerijet International
Line of Business: Commercial Property
Broker          : Aon
Effective Date  : 03-20-2025
Sum Insured     : $480,000
Renewal Days    : 47 days

─────────────────────────────────────
PREMISES DETAILS
─────────────────────────────────────
Year Built      : 2010
Construction    : Non-Combustible
EQ Zone         : Medium
Flood Zone      : High
Roof Type       : Slate
Fire Protection : Alarm & Sprinklers

─────────────────────────────────────
LOSS HISTORY
─────────────────────────────────────
1. Fire due to short circuit — $24,000 (Closed)
2. Breakdown of Machinery   — $8,500  (Closed)

─────────────────────────────────────
CLIENT HISTORY (Insurance Middle Office — mock data from GCS for POC)
─────────────────────────────────────
Total Premium Collected : $256,000
Claims Paid             : $3,400
Potential Hazard        : Nil
Previous Risk Score     : Good

─────────────────────────────────────
RISK SCORE BREAKDOWN
─────────────────────────────────────
Year Built (2010)       : 0
EQ Zone (Medium)        : 2
Flood Zone (High)       : 3
Construction Type       : 1
─────────────────────────────────────
Overall Score           : 6 — Medium Risk

─────────────────────────────────────
DECISION
─────────────────────────────────────
Priority    : P0
Risk Score  : 6 (Medium Risk)
Assigned To : John Larsson (10012)
Recommendation: Acceptable — review flood zone exposure
                before finalizing terms.
─────────────────────────────────────

Submission saved as NB-25-34677.
Type "accept" to accept or "decline" to decline this risk.
```

---

**T=9 — Underwriter responds**
```
👤 Underwriter: "accept"
```

---

**T=10 — Orchestrator → Submission Record Agent → BigQuery update**
```
Submission Record Agent calls embedded tool: bq_update_status("NB-25-34677", "Accepted", "John Larsson")
Executes BigQuery DML:
  UPDATE uw_workbench.submissions
  SET status = 'Accepted',
      decision_by = 'John Larsson',
      decision_at = '2025-02-24T08:25:00Z'
  WHERE case_id = 'NB-25-34677'
```

---

**T=11 — Final confirmation in chat**
```
🤖 Gemini Agent:

Submission NB-25-34677 has been accepted.
Assigned to John Larsson (10012).
Broker Aon will be notified for quotation processing.
```

---

**Total time: ~8-12 seconds end to end**

---

## 9. Auto-Decline Dry Run

**Scenario:** Marine submission — auto declined by rules

```
👤 Underwriter: "Process this submission"
    [attaches: PrecisionEngineering_Marine.pdf]

🤖 Gemini Agent:

⚠️ This submission has been automatically declined.

─────────────────────────────────────
Insured         : Precision Engineering Co
Line of Business: Marine
Broker          : King & Company
─────────────────────────────────────
Decline Reason  : Marine is outside risk appetite.
                  Auto-declined per underwriting policy.
─────────────────────────────────────

Submission recorded as DECLINED (NB-25-34682).
Broker King & Company will be notified.
```

---

## 10. Cost Estimate (POC)

| Service | Usage | Est. Monthly Cost |
|---|---|---|
| Vertex AI Agent Builder | ~500 sessions/month | ~$20-40 |
| Gemini 2.0 Pro (orchestrator) | ~500 sessions | ~$15-25 |
| Gemini 2.0 Flash (sub-agents + extraction) | ~3000 calls (6 agents) | ~$7-14 |
| Cloud Storage | ~50GB + object versioning on rules/ | ~$1-2 |
| BigQuery | ~1GB storage + streaming inserts | ~$1-2 |
| Secret Manager | minimal | ~$0 |
| **Total** | | **~$44-83/month** |

**Cost savings vs. previous architecture:** Removed 4 Cloud Run MCP services (~$4-8/month) and eliminated associated networking, cold start, and maintenance overhead. All tools now run embedded inside agents at zero additional infrastructure cost.

---
