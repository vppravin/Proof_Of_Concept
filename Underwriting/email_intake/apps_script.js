// ═══════════════════════════════════════════════════════════════
// UNDERWRITING EMAIL INTAKE - Google Apps Script
// ═══════════════════════════════════════════════════════════════

const CLOUD_FUNCTION_URL = "https://us-central1-gbu-demo-playground.cloudfunctions.net/email-intake";
const API_KEY = "uw-intake-2026";
const PROCESSED_LABEL = "UW-Processed";
const SUBJECT_KEYWORDS = ["submission", "new business", "acord", "quote request", "insurance application"];

function checkSubmissionEmails() {
  console.log("🔍 Starting email check...");
  
  const query = "is:unread has:attachment";
  const threads = GmailApp.search(query, 0, 10);
  console.log("📬 Found " + threads.length + " unread threads with attachments");
  
  // Get or create the processed label
  let label = GmailApp.getUserLabelByName(PROCESSED_LABEL);
  if (!label) {
    label = GmailApp.createLabel(PROCESSED_LABEL);
  }
  
  for (let i = 0; i < threads.length; i++) {
    const thread = threads[i];
    const messages = thread.getMessages();
    const latestMessage = messages[messages.length - 1];
    const subject = latestMessage.getSubject();
    console.log("📧 Checking: " + subject);
    
    // Skip if already labeled
    const labels = thread.getLabels().map(l => l.getName());
    if (labels.includes(PROCESSED_LABEL)) {
      console.log("⏭️ Already processed, skipping");
      continue;
    }
    
    // Check if subject matches submission keywords
    const subjectLower = subject.toLowerCase();
    const isSubmission = SUBJECT_KEYWORDS.some(kw => subjectLower.includes(kw));
    if (!isSubmission) {
      console.log("⏭️ Not a submission, skipping");
      continue;
    }
    
    console.log("✅ Matched as submission!");
    
    // Get ALL attachments from ALL messages in thread
    var pdfAttachments = [];
    for (var m = 0; m < messages.length; m++) {
      var msg = messages[m];
      var rawContent = msg.getRawContent();
      var atts = msg.getAttachments();
      console.log("  Message " + m + " attachments via getAttachments(): " + atts.length);
      
      for (var a = 0; a < atts.length; a++) {
        var att = atts[a];
        console.log("    → " + att.getName() + " (" + att.getContentType() + ", " + att.getSize() + " bytes)");
        if (att.getContentType() === "application/pdf" || att.getName().toLowerCase().endsWith(".pdf")) {
          pdfAttachments.push(att);
        }
      }
    }
    
    // If getAttachments() returned nothing, try fetching via Gmail API directly
    if (pdfAttachments.length === 0) {
      console.log("⚠️ getAttachments() returned 0, trying Gmail API...");
      var msgId = latestMessage.getId();
      var fullMsg = Gmail.Users.Messages.get("me", msgId);
      var parts = fullMsg.payload.parts || [];
      console.log("  Gmail API parts: " + parts.length);
      
      for (var p = 0; p < parts.length; p++) {
        var part = parts[p];
        console.log("    Part: " + part.filename + " (" + part.mimeType + ")");
        if (part.filename && (part.mimeType === "application/pdf" || part.filename.toLowerCase().endsWith(".pdf"))) {
          var attData = Gmail.Users.Messages.Attachments.get("me", msgId, part.body.attachmentId);
          pdfAttachments.push({
            getName: function() { return part.filename; },
            getBytes: function() { return Utilities.base64Decode(attData.data.replace(/-/g, '+').replace(/_/g, '/')); },
            _isApiAtt: true
          });
        }
      }
    }
    
    console.log("📄 Total PDF attachments found: " + pdfAttachments.length);
    
    if (pdfAttachments.length === 0) {
      console.log("⚠️ No PDFs found, skipping");
      continue;
    }
    
    // Prepare payload
    var attachmentData = [];
    for (var j = 0; j < pdfAttachments.length; j++) {
      var pdf = pdfAttachments[j];
      attachmentData.push({
        name: pdf.getName(),
        mimeType: "application/pdf",
        data: Utilities.base64Encode(pdf.getBytes())
      });
    }
    
    var payload = {
      subject: subject,
      sender: latestMessage.getFrom(),
      date: latestMessage.getDate().toISOString(),
      attachments: attachmentData
    };
    
    console.log("🚀 Sending " + attachmentData.length + " PDFs to Cloud Function...");
    
    // Send to Cloud Function
    try {
      var response = UrlFetchApp.fetch(CLOUD_FUNCTION_URL, {
        method: "post",
        contentType: "application/json",
        headers: { "X-API-Key": API_KEY },
        payload: JSON.stringify(payload),
        muteHttpExceptions: true
      });
      
      var code = response.getResponseCode();
      var result = JSON.parse(response.getContentText());
      console.log("📡 Response: " + code + " → " + JSON.stringify(result));
      
      if (code === 200) {
        thread.addLabel(label);
        thread.markRead();
        console.log("✅ Done! Files uploaded to: " + result.folder);
      } else {
        console.log("❌ Failed: " + result.error);
      }
    } catch (e) {
      console.log("❌ Error: " + e.message);
    }
  }
  
  console.log("🏁 Check complete");
}
