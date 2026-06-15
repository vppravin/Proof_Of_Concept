import os
import json
import logging
import tempfile
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastmcp import FastMCP
import uvicorn

from google.cloud import storage
# from google.cloud import firestore  # Commented off — will enable for feedback loop later
from google.cloud import discoveryengine_v1 as discoveryengine
from google import genai
from google.genai import types

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from docx import Document
import PyPDF2
import fitz  # pymupdf — for editing PDFs while preserving original content

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [DISCLAIMER_MCP] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# GCP Config
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "gbu-demo-playground")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
GCS_BUCKET = os.getenv("GCS_BUCKET", "mlr_document")
GCS_OUTPUT_PREFIX = os.getenv("GCS_OUTPUT_PREFIX", "mlr-disclaimer-engine")
DATASTORE_ID = os.getenv("DATASTORE_ID", "mlr-disclaimer-library_1774874489588")
DATA_STORE_LOCATION = os.getenv("DATA_STORE_LOCATION", "global")
DISCLAIMER_PDF_GCS = os.getenv("DISCLAIMER_PDF_GCS", "gs://mlr_document/mlr-knowledge-base/Disclaimer Library.pdf")
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.5-flash")

# Initialize clients
storage_client = storage.Client(project=PROJECT_ID)
# firestore_client = firestore.Client(project=PROJECT_ID)  # Commented off
genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

logger.info("Initializing FastMCP server for Disclaimer Engine...")
mcp = FastMCP("Disclaimer_Engine_Tools")
logger.info("FastMCP server initialized")

# Internal cache to pass validation results between tools without going through the agent
_validation_cache = {}


# ---------------------------------------------------------------------------
# Dynamic Disclaimer Library Retrieval
# ---------------------------------------------------------------------------

def _search_datastore(query: str, num_results: int = 10) -> list[str]:
    """Search the Agent Builder Data Store for relevant disclaimers."""
    try:
        client = discoveryengine.SearchServiceClient()
        serving_config = (
            f"projects/{PROJECT_ID}/locations/{DATA_STORE_LOCATION}"
            f"/collections/default_collection/dataStores/{DATASTORE_ID}"
            f"/servingConfigs/default_search"
        )
        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=query,
            page_size=num_results,
            content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                    return_snippet=True,
                    max_snippet_count=5,
                ),
                extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                    max_extractive_answer_count=5,
                    max_extractive_segment_count=5,
                ),
            ),
        )
        response = client.search(request)
        results = []
        for result in response.results:
            doc = result.document
            if doc.derived_struct_data:
                snippets = doc.derived_struct_data.get("snippets", [])
                for snippet in snippets:
                    if snippet.get("snippet"):
                        results.append(snippet["snippet"])
                segments = doc.derived_struct_data.get("extractive_segments", [])
                for seg in segments:
                    if seg.get("content"):
                        results.append(seg["content"])
        logger.info(f"Data store search for '{query[:50]}...' returned {len(results)} results")
        return results
    except Exception as e:
        logger.warning(f"Data store search failed: {e}. Falling back to GCS PDF.")
        return []


def _load_disclaimer_library_from_gcs() -> str:
    """Fallback: Load the full disclaimer library PDF from GCS and extract text."""
    try:
        gcs_path = DISCLAIMER_PDF_GCS
        bucket_name = gcs_path.split("/")[2]
        blob_path = "/".join(gcs_path.split("/")[3:])
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        blob.download_to_filename(tmp.name)
        pages = []
        with open(tmp.name, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text = page.extract_text() or ""
                pages.append(text.strip())
        os.unlink(tmp.name)
        full_text = "\n\n".join(pages)
        logger.info(f"Loaded disclaimer library from GCS: {len(full_text)} chars")
        return full_text
    except Exception as e:
        logger.error(f"Failed to load disclaimer library from GCS: {e}")
        return ""


def _get_disclaimer_library(content_context: str = "") -> str:
    """
    Dynamically retrieve the disclaimer library.
        Strategy: Always load the FULL disclaimer library from GCS PDF as primary source.
    This ensures 100% coverage — Gemini sees every disclaimer context every time.
    Data store search is used as supplementary context only.
    """
    # Primary: Always load full PDF from GCS for complete coverage
    logger.info("Loading full disclaimer library from GCS for 100% coverage")
    pdf_text = _load_disclaimer_library_from_gcs()

    if pdf_text:
        library = f"DISCLAIMER LIBRARY (complete):\n\n{pdf_text}"

        # Supplementary: Add data store results for additional context if available
        if DATASTORE_ID and content_context:
            try:
                extra = _search_datastore(f"what disclaimers are required for: {content_context[:500]}")
                if extra:
                    library += "\n\nADDITIONAL CONTEXT FROM DATA STORE:\n" + "\n".join(extra)
            except Exception:
                pass  # Non-critical — full library already loaded

        return library

    # Fallback: Data store only if GCS fails
    if DATASTORE_ID:
        queries = [
            "all disclaimers and their contexts",
            "copyright disclaimer footer",
            "investigational device disclaimer",
            "case study disclaimer",
            "patient facing material disclaimer",
            "internal use disclaimer",
        ]
        all_results = []
        seen = set()
        for q in queries:
            results = _search_datastore(q)
            for r in results:
                if r not in seen:
                    all_results.append(r)
                    seen.add(r)
        if all_results:
            return "DISCLAIMER LIBRARY (from data store):\n\n" + "\n\n".join(all_results)

    return "ERROR: Could not retrieve disclaimer library from data store or GCS."


# --- Feedback retrieval (commented off — will enable later) ---
# def _get_past_feedback() -> str:
#     """Retrieve recent feedback from Firestore for few-shot context."""
#     try:
#         feedback_ref = firestore_client.collection("disclaimer_feedback")
#         docs = (
#             feedback_ref
#             .order_by("timestamp", direction=firestore.Query.DESCENDING)
#             .limit(10)
#             .stream()
#         )
#         entries = []
#         for doc in docs:
#             data = doc.to_dict()
#             entries.append(
#                 f"- Page {data.get('page_number', 'N/A')}: "
#                 f"AI suggested: \"{data.get('ai_suggestion', '')}\" | "
#                 f"User correction: \"{data.get('user_correction', '')}\" | "
#                 f"Reason: \"{data.get('reason', '')}\""
#             )
#         if entries:
#             return "\n\nPAST HUMAN FEEDBACK (learn from these corrections):\n" + "\n".join(entries)
#     except Exception as e:
#         logger.warning(f"Could not fetch feedback: {e}")
#     return ""


# ---------------------------------------------------------------------------
# File Extraction Helpers
# ---------------------------------------------------------------------------

def _download_from_gcs(gcs_path: str) -> str:
    """Download a file from GCS to a local temp path."""
    bucket_name = gcs_path.split("/")[2]
    blob_path = "/".join(gcs_path.split("/")[3:])
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    suffix = os.path.splitext(gcs_path)[1]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    blob.download_to_filename(tmp.name)
    logger.info(f"Downloaded {gcs_path} to {tmp.name}")
    return tmp.name


def _extract_text_from_pdf(file_path: str) -> list[dict]:
    pages = []
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append({"page_number": i + 1, "text": text.strip()})
    return pages


def _extract_text_from_pptx(file_path: str) -> list[dict]:
    prs = Presentation(file_path)
    pages = []
    for i, slide in enumerate(prs.slides):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    texts.append(para.text)
        pages.append({"page_number": i + 1, "text": "\n".join(texts).strip()})
    return pages


def _extract_text_from_docx(file_path: str) -> list[dict]:
    doc = Document(file_path)
    full_text = "\n".join([p.text for p in doc.paragraphs])
    return [{"page_number": 1, "text": full_text.strip()}]


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool
def validate_file(file_path: str) -> dict:
    """
    Extract content from an uploaded file (PDF, PPTX, DOCX) and validate its
    disclaimers against the Disclaimer Library. Returns page-by-page findings
    of found, missing, and incorrect disclaimers.

    Args:
        file_path: GCS path (gs://bucket/path) or local path to the file.
    """
    logger.info(f"Tool invoked: validate_file for {file_path}")
    result_text = ""
    try:
        # Step 1: Download if GCS
        local_path = file_path
        if file_path.startswith("gs://"):
            local_path = _download_from_gcs(file_path)

        # Step 2: Extract text page by page
        ext = os.path.splitext(local_path)[1].lower()
        if ext == ".pdf":
            pages = _extract_text_from_pdf(local_path)
        elif ext == ".pptx":
            pages = _extract_text_from_pptx(local_path)
        elif ext == ".docx":
            pages = _extract_text_from_docx(local_path)
        else:
            return {"error": f"Unsupported file type: {ext}. Supported: PDF, PPTX, DOCX"}

        logger.info(f"Extracted {len(pages)} pages from {file_path}")

        # Step 3: Build content summary for context-aware retrieval
        content_summary = " ".join([p.get("text", "")[:200] for p in pages[:3]])

        # Dynamically fetch disclaimer library
        disclaimer_library = _get_disclaimer_library(content_context=content_summary)
        # past_feedback = _get_past_feedback()  # Commented off

        prompt = f"""You are an expert MLR (Medical, Legal, Regulatory) disclaimer validation engine.

You have access to the organization's Disclaimer Library below. Each disclaimer in the library has a CONTEXT that defines when it is required and a STATEMENT that is the required text.

{disclaimer_library}

CONTENT TO VALIDATE (page by page):
{json.dumps(pages, indent=2)}

YOUR TASK:
1. Read each page of the content carefully and understand what the page is about.
2. For each page, match its content against the CONTEXT of each disclaimer in the Disclaimer Library.
3. If a page's content matches a disclaimer's context, that disclaimer is REQUIRED for that page.
4. Check if the required disclaimer is already present in the page content.
5. If present, verify the text matches the library statement exactly.
6. If not present, flag it as missing.
7. You MUST analyze ALL {len(pages)} pages. Do not stop early.

IMPORTANT:
- Only flag disclaimers whose CONTEXT genuinely matches the page content. Do NOT assume every page needs every disclaimer.
- Do NOT invent new disclaimer requirements - only use what exists in the Disclaimer Library.
- Use the EXACT disclaimer statement text from the library when reporting required text.
- If a page has no content matching any disclaimer context, report it with empty found and missing lists.
- Product codes, reference numbers (e.g. MKT-02904, AP123), document version numbers, and similar identifiers are NOT disclaimers. Do NOT flag them as found disclaimers or try to correct them.
- For "correction_needed": provide ONLY the exact corrected text that should replace the existing text. Do NOT include explanations, instructions, or descriptions. Just the replacement text itself. For example, if the text says "data on file at company name" and it should say "data on file at Company", then correction_needed should be exactly: "Tests performed by and data on file at Company." - nothing else.
- For "required_text": provide ONLY the exact disclaimer statement from the library. No explanations.
- When content contains product performance claims, comparative statements, or data-driven assertions (e.g. "unparalleled support", "high performance", "maximized control"), check if a data-on-file disclaimer is required per the library.

RESPOND IN THIS EXACT JSON FORMAT:
{{
    "summary": "Brief overall summary of findings",
    "total_issues": <number>,
    "findings": [
        {{
            "page_number": <int>,
            "page_content_summary": "Brief summary of what this page contains",
            "found_disclaimers": [
                {{
                    "disclaimer_id": "Disclaimer X",
                    "text_found": "exact text found in content",
                    "status": "correct" or "needs_correction",
                    "correction_needed": "the exact corrected replacement text only, or empty string if correct"
                }}
            ],
            "missing_disclaimers": [
                {{
                    "disclaimer_id": "Disclaimer X",
                    "required_text": "the exact disclaimer statement text from the library only",
                    "reason": "why this disclaimer is needed for this page",
                    "suggested_placement": "footer" or "footnote" or "after_claim" or "slide_bottom"
                }}
            ]
        }}
    ]
}}

Return ONLY valid JSON. No markdown, no code blocks."""

        response = genai_client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=16384),
        )

        result_text = response.text.strip()
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1]
            result_text = result_text.rsplit("```", 1)[0]

        validation_result = json.loads(result_text)
        validation_result["file_path"] = file_path
        logger.info(f"Validation complete. Found {validation_result.get('total_issues', 0)} issues")

        # Cache the result so generate_edited_file can use it without the agent passing large JSON
        _validation_cache[file_path] = validation_result

        return validation_result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response: {e}")
        return {"error": f"JSON parse error: {e}", "raw_response": result_text}
    except Exception as e:
        logger.error(f"Error in validate_file: {e}")
        return {"error": str(e)}


@mcp.tool
def generate_edited_file(file_path: str) -> dict:
    """
    Auto-edit the uploaded file by inserting missing disclaimers and correcting
    existing ones based on the validation results from validate_file.
    Returns the GCS path to the edited file and a change summary for human approval.
    Must be called AFTER validate_file for the same file_path.

    Args:
        file_path: Same GCS path or local path used in validate_file.
    """
    logger.info(f"Tool invoked: generate_edited_file for {file_path}")
    try:
        # Retrieve cached validation result
        validation = _validation_cache.get(file_path)
        if not validation:
            return {"error": f"No validation result found for {file_path}. Run validate_file first."}
        findings = validation.get("findings", [])

        local_path = file_path
        if file_path.startswith("gs://"):
            local_path = _download_from_gcs(file_path)

        ext = os.path.splitext(local_path)[1].lower()
        changes_made = []
        original_name = os.path.splitext(os.path.basename(file_path.replace("gs://", "")))[0]

        # ---- PDF editing (preserves original content using pymupdf) ----
        if ext == ".pdf":
            pdf_doc = fitz.open(local_path)

            for finding in findings:
                page_num = finding.get("page_number", 1)
                page_idx = page_num - 1
                if page_idx >= len(pdf_doc):
                    continue
                page = pdf_doc[page_idx]
                page_rect = page.rect

                # Correct existing disclaimers
                for disc in finding.get("found_disclaimers", []):
                    if disc.get("status") == "needs_correction" and disc.get("correction_needed"):
                        text_found = disc.get("text_found", "")
                        if text_found:
                            text_instances = page.search_for(text_found)
                            for inst in text_instances:
                                page.add_redact_annot(inst, fill=(1, 1, 1))
                            page.apply_redactions()
                            if text_instances:
                                insert_point = text_instances[0].tl
                                page.insert_text(
                                    insert_point,
                                    disc["correction_needed"],
                                    fontsize=7,
                                    fontname="helv",
                                    encoding=fitz.TEXT_ENCODING_LATIN,
                                    color=(0, 0, 0),
                                )
                            changes_made.append({
                                "page": page_num,
                                "type": "corrected",
                                "disclaimer_id": disc.get("disclaimer_id"),
                                "old_text": text_found,
                                "new_text": disc["correction_needed"],
                                "reason": "Corrected to match disclaimer library",
                            })

                # Insert missing disclaimers below existing content
                missing = finding.get("missing_disclaimers", [])
                if missing:
                    disclaimer_texts = []
                    for disc in missing:
                        req_text = disc.get("required_text", "")
                        if req_text:
                            disclaimer_texts.append(req_text)
                            changes_made.append({
                                "page": page_num,
                                "type": "inserted",
                                "disclaimer_id": disc.get("disclaimer_id"),
                                "new_text": req_text,
                                "reason": disc.get("reason"),
                                "placement": disc.get("suggested_placement"),
                            })

                    combined = " | ".join(disclaimer_texts)
                    if combined:
                        # Find where existing content ends to avoid overlap
                        # Check both text blocks AND image blocks
                        text_blocks = page.get_text("blocks")
                        content_bottom = 0
                        for block in text_blocks:
                            if block[3] > content_bottom:
                                content_bottom = block[3]

                        # Also check image positions
                        for img in page.get_images(full=True):
                            try:
                                img_rects = page.get_image_rects(img[0])
                                for img_rect in img_rects:
                                    if img_rect.y1 > content_bottom:
                                        content_bottom = img_rect.y1
                            except Exception:
                                pass

                        # Place footer below content with 15px gap, but not beyond page
                        footer_top = content_bottom + 15
                        footer_bottom = footer_top + 45
                        # If footer would go off page, place at absolute bottom
                        if footer_bottom > page_rect.y1:
                            footer_top = page_rect.y1 - 50
                            footer_bottom = page_rect.y1 - 5

                        footer_rect = fitz.Rect(
                            page_rect.x0 + 20,
                            footer_top,
                            page_rect.x1 - 20,
                            footer_bottom,
                        )
                        # Normalize special characters for PDF font compatibility
                        combined = combined.replace("\u2013", "-").replace("\u2014", "-").replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\u00a9", "(c)").replace("\u2022", "-")
                        page.insert_textbox(
                            footer_rect,
                            combined,
                            fontsize=8,
                            fontname="helv",
                            encoding=fitz.TEXT_ENCODING_LATIN,
                            color=(0.3, 0.3, 0.3),
                            align=fitz.TEXT_ALIGN_LEFT,
                        )

            output_path = os.path.join(tempfile.gettempdir(), f"{original_name}_EDITED.pdf")
            pdf_doc.save(output_path)
            pdf_doc.close()
            output_gcs_blob = f"{GCS_OUTPUT_PREFIX}/edited/{original_name}_EDITED.pdf"
            output_format = "PDF"

        # ---- PPTX editing (preserves original content) ----
        elif ext == ".pptx":
            prs = Presentation(local_path)

            for finding in findings:
                page_num = finding.get("page_number", 1)
                slide_idx = page_num - 1
                if slide_idx >= len(prs.slides):
                    continue
                slide = prs.slides[slide_idx]

                # Correct existing disclaimers
                for disc in finding.get("found_disclaimers", []):
                    if disc.get("status") == "needs_correction" and disc.get("correction_needed"):
                        for shape in slide.shapes:
                            if shape.has_text_frame:
                                for para in shape.text_frame.paragraphs:
                                    if disc.get("text_found", "") and disc["text_found"] in para.text:
                                        old_text = para.text
                                        para.text = disc["correction_needed"]
                                        para.font.size = Pt(8)
                                        changes_made.append({
                                            "page": page_num,
                                            "type": "corrected",
                                            "disclaimer_id": disc.get("disclaimer_id"),
                                            "old_text": old_text,
                                            "new_text": disc["correction_needed"],
                                            "reason": "Corrected to match disclaimer library",
                                        })

                # Insert missing disclaimers
                missing = finding.get("missing_disclaimers", [])
                if missing:
                    disclaimer_texts = []
                    for disc in missing:
                        req_text = disc.get("required_text", "")
                        if req_text:
                            disclaimer_texts.append(req_text)
                            changes_made.append({
                                "page": page_num,
                                "type": "inserted",
                                "disclaimer_id": disc.get("disclaimer_id"),
                                "new_text": req_text,
                                "reason": disc.get("reason"),
                                "placement": disc.get("suggested_placement"),
                            })

                    combined = " | ".join(disclaimer_texts)
                    if combined:
                        txBox = slide.shapes.add_textbox(
                            Inches(0.5),
                            prs.slide_height - Inches(0.8),
                            prs.slide_width - Inches(1),
                            Inches(0.6),
                        )
                        tf = txBox.text_frame
                        tf.word_wrap = True
                        p = tf.paragraphs[0]
                        p.text = combined
                        p.font.size = Pt(7)
                        p.font.italic = True
                        p.alignment = PP_ALIGN.LEFT

            output_path = os.path.join(tempfile.gettempdir(), f"{original_name}_EDITED.pptx")
            prs.save(output_path)
            output_gcs_blob = f"{GCS_OUTPUT_PREFIX}/edited/{original_name}_EDITED.pptx"
            output_format = "PPTX"

        # ---- DOCX editing ----
        elif ext == ".docx":
            doc = Document(local_path)
            for finding in findings:
                for disc in finding.get("found_disclaimers", []):
                    if disc.get("status") == "needs_correction" and disc.get("correction_needed"):
                        for para in doc.paragraphs:
                            if disc.get("text_found", "") and disc["text_found"] in para.text:
                                old_text = para.text
                                para.text = disc["correction_needed"]
                                changes_made.append({
                                    "page": finding.get("page_number", 1),
                                    "type": "corrected",
                                    "disclaimer_id": disc.get("disclaimer_id"),
                                    "old_text": old_text,
                                    "new_text": disc["correction_needed"],
                                    "reason": "Corrected to match disclaimer library"
                                })

                for disc in finding.get("missing_disclaimers", []):
                    req_text = disc.get("required_text", "")
                    if req_text:
                        doc.add_paragraph("")
                        p = doc.add_paragraph(req_text)
                        p.style.font.size = Pt(8)
                        p.style.font.italic = True
                        changes_made.append({
                            "page": finding.get("page_number", 1),
                            "type": "inserted",
                            "disclaimer_id": disc.get("disclaimer_id"),
                            "new_text": req_text,
                            "reason": disc.get("reason"),
                            "placement": disc.get("suggested_placement")
                        })

            output_path = os.path.join(tempfile.gettempdir(), f"{original_name}_EDITED.docx")
            doc.save(output_path)
            output_gcs_blob = f"{GCS_OUTPUT_PREFIX}/edited/{original_name}_EDITED.docx"
            output_format = "DOCX"
        else:
            return {"error": f"Unsupported file type for editing: {ext}"}

        # Upload edited file to GCS
        bucket = storage_client.bucket(GCS_BUCKET)
        blob = bucket.blob(output_gcs_blob)
        blob.upload_from_filename(output_path)
        gcs_uri = f"gs://{GCS_BUCKET}/{output_gcs_blob}"
        logger.info(f"Edited file uploaded to {gcs_uri}")

        # Generate signed URL for direct download (valid for 7 days)
        try:
            download_url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(days=7),
                method="GET",
            )
            logger.info(f"Signed URL generated, valid for 7 days")
        except Exception as e:
            logger.warning(f"Could not generate signed URL: {e}")
            download_url = f"https://storage.cloud.google.com/{GCS_BUCKET}/{output_gcs_blob}"

        # Clean up temp file
        os.unlink(output_path)

        return {
            "total_changes": len(changes_made),
            "edited_file_gcs": gcs_uri,
            "download_url": download_url,
            "edited_file_format": output_format,
            "changes": changes_made,
            "status": "pending_approval",
            "message": "Edited file generated. Review the changes below and approve or reject."
        }
    except Exception as e:
        logger.error(f"Error generating edited file: {e}")
        return {"error": str(e)}


@mcp.tool
def apply_corrections(file_path: str, corrections: str) -> dict:
    """
    Apply user corrections to the validation result and re-generate the edited file.
    Call this when the user rejects or modifies specific disclaimer changes.

    Args:
        file_path: Same GCS path used in validate_file and generate_edited_file.
        corrections: JSON string describing user corrections. Format:
            {
                "corrections": [
                    {
                        "page_number": 3,
                        "action": "replace",
                        "disclaimer_id": "Disclaimer X",
                        "new_text": "the user's corrected disclaimer text"
                    },
                    {
                        "page_number": 5,
                        "action": "remove",
                        "disclaimer_id": "Disclaimer Y"
                    }
                ]
            }
            Actions: "replace" = use user's text instead, "remove" = don't add this disclaimer
    """
    logger.info(f"Tool invoked: apply_corrections for {file_path}")
    try:
        user_corrections = json.loads(corrections) if isinstance(corrections, str) else corrections
        correction_list = user_corrections.get("corrections", [])

        # Get cached validation result
        validation = _validation_cache.get(file_path)
        if not validation:
            return {"error": f"No validation result found for {file_path}. Run validate_file first."}

        # Apply user corrections to the cached validation
        findings = validation.get("findings", [])
        for corr in correction_list:
            page_num = corr.get("page_number")
            action = corr.get("action")
            disc_id = corr.get("disclaimer_id", "")
            new_text = corr.get("new_text", "")

            for finding in findings:
                if finding.get("page_number") != page_num:
                    continue

                if action == "replace":
                    # Update the text in found_disclaimers corrections
                    for disc in finding.get("found_disclaimers", []):
                        if disc.get("disclaimer_id") == disc_id:
                            disc["correction_needed"] = new_text
                            disc["status"] = "needs_correction"
                    # Update the text in missing_disclaimers
                    for disc in finding.get("missing_disclaimers", []):
                        if disc.get("disclaimer_id") == disc_id:
                            disc["required_text"] = new_text

                elif action == "remove":
                    # Remove from missing_disclaimers
                    finding["missing_disclaimers"] = [
                        d for d in finding.get("missing_disclaimers", [])
                        if d.get("disclaimer_id") != disc_id
                    ]
                    # Remove correction from found_disclaimers
                    for disc in finding.get("found_disclaimers", []):
                        if disc.get("disclaimer_id") == disc_id:
                            disc["status"] = "correct"
                            disc["correction_needed"] = ""

        # Update cache with corrected validation
        _validation_cache[file_path] = validation
        logger.info(f"Applied {len(correction_list)} user corrections")

        # Re-generate the edited file using the corrected validation
        # Call generate_edited_file internally
        result = generate_edited_file(file_path)
        result["message"] = f"File re-generated with {len(correction_list)} user corrections applied."
        return result

    except Exception as e:
        logger.error(f"Error applying corrections: {e}")
        return {"error": str(e)}


# --- Feedback tool (commented off — will enable later) ---
# @mcp.tool
# def store_feedback(feedback_data: str) -> dict:
#     """
#     Store human feedback (approval/rejection) for disclaimer suggestions.
#     Feedback is used to improve future validations via few-shot learning.
#
#     Args:
#         feedback_data: JSON string with format:
#             {
#                 "file_name": "original file name",
#                 "entries": [
#                     {
#                         "page_number": 1,
#                         "disclaimer_id": "Disclaimer X",
#                         "ai_suggestion": "what AI suggested",
#                         "action": "approved" or "rejected",
#                         "user_correction": "correct text if rejected",
#                         "reason": "why rejected"
#                     }
#                 ]
#             }
#     """
#     logger.info("Tool invoked: store_feedback")
#     try:
#         feedback = json.loads(feedback_data) if isinstance(feedback_data, str) else feedback_data
#         file_name = feedback.get("file_name", "unknown")
#         entries = feedback.get("entries", [])
#
#         stored = 0
#         for entry in entries:
#             firestore_client.collection("disclaimer_feedback").document().set({
#                 "file_name": file_name,
#                 "page_number": entry.get("page_number"),
#                 "disclaimer_id": entry.get("disclaimer_id"),
#                 "ai_suggestion": entry.get("ai_suggestion"),
#                 "action": entry.get("action"),
#                 "user_correction": entry.get("user_correction", ""),
#                 "reason": entry.get("reason", ""),
#                 "timestamp": datetime.utcnow().isoformat(),
#             })
#             stored += 1
#
#         logger.info(f"Stored {stored} feedback entries for {file_name}")
#         return {
#             "status": "success",
#             "stored_entries": stored,
#             "message": f"{stored} feedback entries saved."
#         }
#     except Exception as e:
#         logger.error(f"Error storing feedback: {e}")
#         return {"error": str(e)}


# ---------------------------------------------------------------------------
# Streamable HTTP App
# ---------------------------------------------------------------------------
app = mcp.http_app()

if __name__ == "__main__":
    logger.info("🚀 Starting Disclaimer Engine MCP Server (Streamable HTTP)...")
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
