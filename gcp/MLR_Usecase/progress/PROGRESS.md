# MLR Agentic Validating Engine - Progress Tracker

## Last Updated: 2026-03-31

## Project Goal
Build an Agentic MLR Validating Engine on GCP that accelerates pharma/medical content approvals by catching compliance errors before human MLR review. Target: reduce MLR review cycle time by 30-40%.

## ✅ Completed

### Infrastructure
- GCS bucket: mlr_document
- Data store: mlr-disclaimer-library_1774874489588 (Healthcare option, Periodic sync)
- Data store connected to AI Application and validated (all test queries passed)

### MCP Server (Deployed to Cloud Run)
- Image: us-central1-docker.pkg.dev/gbu-demo-playground/mlr-repository/mcp-disclaimer-engine:latest
- Cloud Run URL: https://mcp-disclaimer-agent-146646146609.us-central1.run.app
- 3 tools: validate_file, generate_edited_file, apply_corrections
- Full disclaimer library loaded from GCS PDF (100% coverage)
- PDF editing via pymupdf (preserves original content)
- PPTX editing via python-pptx (preserves original content)
- DOCX editing via python-docx
- Signed URL generation for download links
- Dynamic footer placement (detects content + image bottom positions)
- UTF-8 encoding normalization for PDF text insertion
- Streamable HTTP transport (fastmcp http_app)

### Agent (Deployed to Vertex AI Reasoning Engine)
- Resource: projects/146646146609/locations/us-central1/reasoningEngines/6904669689398427648
- Works in Vertex AI Playground
- 3-tool workflow: validate_file → generate_edited_file → apply_corrections
- Correction loop: user can reject/modify → re-generates file with new download URL

### Testing Results
- 100% disclaimer accuracy validated against source of truth (all 8 pages pass)
- Page 1: Copyright + Rx ✅
- Page 2: Copyright + Rx + Data-on-file ✅
- Page 3: Corrected existing disclaimer + Copyright + Rx ✅
- Page 4: Copyright + Rx + Data-on-file ✅
- Page 5: Copyright + Rx + Data-on-file ✅
- Page 6: Corrected IDE disclaimer + In development + Copyright + Rx ✅
- Page 7: IDE caution + In development + 510(k) + Copyright + Rx ✅
- Page 8: Case study (8) + Case study (12) + Copyright + Rx ✅

## ⚠️ Pending / Known Issues
1. AI Application integration — agent works in Playground but output not reflected in AI Application
2. Background image overlap on pages 1, 4 (cosmetic — disclaimers readable but overlap background images)
3. Feedback loop (Firestore) — commented off, ready to enable
4. apply_corrections tool — built but not yet tested end-to-end

## File Locations
- MCP Server: /home/ec2-user/.cache/gcp/MLR_Usecase/mcp/disclaimer_agent_mcp/
- Agent: /home/ec2-user/.cache/gcp/MLR_Usecase/agent/disclaimer_agent/
- Input files: /home/ec2-user/.cache/gcp/MLR_Usecase/Files/
- Knowledge base: gs://mlr_document/mlr-knowledge-base/Disclaimer Library.pdf
- Input file: gs://mlr_document/Input_mlr_doc/mlr_input.pdf
- Output: gs://mlr_document/mlr-disclaimer-engine/edited/

## Next Steps
- Fix AI Application integration (agent → AI Application tool connection)
- Enable Firestore feedback loop
- Test apply_corrections end-to-end
- Build Claim Intelligence Agent (Phase 3)
