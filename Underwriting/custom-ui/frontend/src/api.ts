const API_BASE = import.meta.env.VITE_API_URL || '';

export async function fetchSubmissions(status = '', assignedTo = '') {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (assignedTo) params.set('assigned_to', assignedTo);
  const res = await fetch(`${API_BASE}/api/submissions?${params}`);
  return res.json();
}

export async function fetchSubmission(caseId: string) {
  const res = await fetch(`${API_BASE}/api/submissions/${caseId}`);
  return res.json();
}

export async function fetchSubmissionFiles(caseId: string) {
  const res = await fetch(`${API_BASE}/api/submissions/${caseId}/files`);
  return res.json();
}

export async function fetchJustification(caseId: string) {
  const res = await fetch(`${API_BASE}/api/submissions/${caseId}/justify`);
  return res.json();
}

export async function fetchCaseChatHistory(caseId: string) {
  const res = await fetch(`${API_BASE}/api/submissions/${caseId}/chat-history`);
  return res.json();
}

export async function* streamCaseChat(caseId: string, message: string, userId = 'underwriter') {
  const res = await fetch(`${API_BASE}/api/submissions/${caseId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, user_id: userId }),
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          if (data.text) yield data.text;
          if (data.done) return;
        } catch {}
      }
    }
  }
}

export async function recordDecision(caseId: string, decision: string, decisionBy: string, notes = '') {
  const res = await fetch(`${API_BASE}/api/submissions/${caseId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, decision_by: decisionBy, notes }),
  });
  return res.json();
}

export async function fetchStats() {
  const res = await fetch(`${API_BASE}/api/stats`);
  return res.json();
}

export async function fetchStatsByStatus() {
  const res = await fetch(`${API_BASE}/api/stats/by-status`);
  return res.json();
}

export async function fetchStatsByPriority() {
  const res = await fetch(`${API_BASE}/api/stats/by-priority`);
  return res.json();
}

export async function fetchStatsByAssignee() {
  const res = await fetch(`${API_BASE}/api/stats/by-assignee`);
  return res.json();
}

export async function fetchErrors() {
  const res = await fetch(`${API_BASE}/api/errors?resolved=false`);
  return res.json();
}

export async function fetchPendingClassifications() {
  const res = await fetch(`${API_BASE}/api/submissions?status=Pending+Classification`);
  return res.json();
}

export async function* streamChat(message: string, history: {role: string, text: string}[] = [], userId = 'underwriter', uiContext?: {view: string, caseId?: string, tab?: string}) {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, user_id: userId, history, ui_context: uiContext }),
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          if (data.text) yield data.text;
          if (data.done) return;
          if (data.error) throw new Error(data.error);
        } catch {}
      }
    }
  }
}

// Chat session history
export async function listChatSessions(): Promise<any[]> {
  const res = await fetch('/api/chat-sessions');
  return res.json();
}

export async function loadChatSession(sessionId: string): Promise<any> {
  const res = await fetch(`/api/chat-sessions/${sessionId}`);
  return res.json();
}

export async function saveChatSession(sessionId: string, title: string, messages: any[]): Promise<void> {
  await fetch('/api/chat-sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, title, messages }),
  });
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await fetch(`/api/chat-sessions/${sessionId}`, { method: 'DELETE' });
}

// Error handling
export async function getErrorDetail(errorId: string): Promise<any> {
  const res = await fetch(`/api/errors/${errorId}`);
  return res.json();
}

export async function retryError(errorId: string): Promise<any> {
  const res = await fetch(`/api/errors/${errorId}/retry`, { method: 'POST' });
  return res.json();
}

export async function resolveError(errorId: string): Promise<any> {
  const res = await fetch(`/api/errors/${errorId}/resolve`, { method: 'POST' });
  return res.json();
}

export async function fetchTrace(caseId: string) {
  const res = await fetch(`${API_BASE}/api/submissions/${caseId}/trace`);
  return res.json();
}

export async function fetchAgentLogs(caseId: string) {
  const res = await fetch(`${API_BASE}/api/submissions/${caseId}/logs`);
  return res.json();
}
