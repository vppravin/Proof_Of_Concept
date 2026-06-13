# TODO — Pending Items

## 1. Pending Approval Resume Flow
**Status**: Not implemented  
**What**: In `custom-ui/backend/main.py` → `/api/submissions/{case_id}/approve` endpoint, after saving corrected classifications, call the orchestrator agent directly with prompt "Approve classification for {case_id}" so it resumes from extraction step.  
**Why**: Currently pending approval has no way to resume processing. Error retry works (deletes + re-triggers) but pending needs to keep existing case_id and resume.  
**Agent instruction already supports this**: "Approve classification for <case_id> → resume from step 4"

## 2. UI Terminology Alignment with PPT
**Status**: Not implemented  
**What**: Align UI labels with the original PPT deck language:
- Pipeline steps: "Classification → Extraction → Risk Scoring → Assignment → Complete"
- "Risk Score" → "UW Risk Score"
- "Premises & Building" → "Premises Information"
- "Expiration Date" → "Expiry Date"
