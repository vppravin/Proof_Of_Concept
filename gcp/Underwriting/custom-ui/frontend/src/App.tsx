import { useState, useEffect, useRef, useCallback } from 'react';
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { fetchSubmissions, fetchStats, fetchStatsByStatus, fetchStatsByPriority, fetchStatsByAssignee, fetchErrors, fetchPendingClassifications, streamChat, streamCaseChat, fetchCaseChatHistory, listChatSessions, loadChatSession, saveChatSession } from './api';
import SubmissionDetail from './SubmissionDetail';
import ErrorDetail from './ErrorDetail';
import PendingDetail from './PendingDetail';
import './index.css';

const COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

function App() {
  const [dashWidth, setDashWidth] = useState(68);
  const [dragging, setDragging] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>('light');
  const tooltipStyle = theme === 'dark'
    ? { background: '#1a1b2e', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, color: '#f0f0f5', fontSize: 12 }
    : { background: '#ffffff', border: '1px solid rgba(0,0,0,0.1)', borderRadius: 10, color: '#111827', fontSize: 12 };
  const appRef = useRef<HTMLDivElement>(null);

  // Dashboard
  const [submissions, setSubmissions] = useState<any[]>([]);
  const [stats, setStats] = useState<any>({});
  const [statusData, setStatusData] = useState<any[]>([]);
  const [priorityData, setPriorityData] = useState<any[]>([]);
  const [assigneeData, setAssigneeData] = useState<any[]>([]);
  const [errors, setErrors] = useState<any[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<any[]>([]);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterAssignee, setFilterAssignee] = useState('');
  const [activeTab, setActiveTab] = useState<'submissions' | 'errors' | 'pending'>('submissions');
  const [showStatusInfo, setShowStatusInfo] = useState(false);

  // Chat
  const [messages, setMessages] = useState<{ role: string; text: string }[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [thinkingText, setThinkingText] = useState('');
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<any>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const [chatSessionId, setChatSessionId] = useState<string>(crypto.randomUUID());
  const [chatSessions, setChatSessions] = useState<any[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  // Detail view
  const [selectedCase, setSelectedCase] = useState<string | null>(null);
  const [selectedError, setSelectedError] = useState<string | null>(null);
  const [selectedPending, setSelectedPending] = useState<string | null>(null);
  // Case chat mode
  const [caseChatId, setCaseChatId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [subRes, statsRes, statusRes, prioRes, assignRes, errRes, pendRes] = await Promise.all([
        fetchSubmissions(filterStatus, filterAssignee),
        fetchStats(), fetchStatsByStatus(), fetchStatsByPriority(), fetchStatsByAssignee(),
        fetchErrors(), fetchPendingClassifications(),
      ]);
      setSubmissions(subRes.submissions || []);
      setStats(statsRes);
      setStatusData(statusRes);
      setPriorityData(prioRes);
      setAssigneeData(assignRes);
      setErrors(errRes.errors || []);
      setPendingApprovals(pendRes.submissions || []);
    } catch (e) { console.error('Load failed', e); }
  }, [filterStatus, filterAssignee]);

  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  // Resizer
  const onMouseMove = useCallback((e: MouseEvent) => {
    if (!dragging || !appRef.current) return;
    const pct = (e.clientX / appRef.current.offsetWidth) * 100;
    setDashWidth(Math.min(85, Math.max(25, pct)));
  }, [dragging]);

  useEffect(() => {
    const up = () => setDragging(false);
    if (dragging) { window.addEventListener('mousemove', onMouseMove); window.addEventListener('mouseup', up); }
    return () => { window.removeEventListener('mousemove', onMouseMove); window.removeEventListener('mouseup', up); };
  }, [dragging, onMouseMove]);

  // Chat
  const sendMessage = async () => {
    if (!input.trim() || streaming) return;
    const userMsg = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', text: userMsg }]);
    setStreaming(true);
    setThinkingText('Analyzing your request...');
    setMessages(prev => [...prev, { role: 'agent', text: '' }]);

    try {
      if (caseChatId) {
        // Case-specific chat with persistent session
        for await (const chunk of streamCaseChat(caseChatId, userMsg)) {
          if (thinkingText) setThinkingText('');
          setMessages(prev => {
            const u = [...prev];
            u[u.length - 1] = { role: 'agent', text: u[u.length - 1].text + chunk };
            return u;
          });
        }
      } else {
        // General chat with history context + UI state
        const history = messages.filter(m => m.text.length > 0);
        const uiContext = {
          view: selectedCase ? 'submission_detail' : selectedError ? 'error_detail' : selectedPending ? 'pending_detail' : 'dashboard',
          caseId: selectedCase || selectedPending || undefined,
          tab: activeTab,
        };
        for await (const chunk of streamChat(userMsg, history, 'underwriter', uiContext)) {
          if (thinkingText) setThinkingText('');
          setMessages(prev => {
            const u = [...prev];
            u[u.length - 1] = { role: 'agent', text: u[u.length - 1].text + chunk };
            return u;
          });
        }
      }
    } catch {
      setMessages(prev => {
        const u = [...prev];
        u[u.length - 1] = { role: 'agent', text: 'Sorry, an error occurred.' };
        return u;
      });
    }
    setThinkingText('');
    setStreaming(false);
    loadData();
  };

  const clearChat = () => {
    // Save current session if it has messages
    if (messages.length > 0) {
      const title = messages.find(m => m.role === 'user')?.text.slice(0, 50) || 'Untitled';
      saveChatSession(chatSessionId, title, messages);
    }
    setMessages([]); setCaseChatId(null);
    setChatSessionId(crypto.randomUUID());
  };

  const loadSession = async (sid: string) => {
    if (messages.length > 0) {
      const title = messages.find(m => m.role === 'user')?.text.slice(0, 50) || 'Untitled';
      await saveChatSession(chatSessionId, title, messages);
    }
    const session = await loadChatSession(sid);
    setMessages(session.messages || []);
    setChatSessionId(sid);
    setShowHistory(false);
  };

  const toggleVoice = () => {
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) { alert('Speech recognition not supported in this browser'); return; }
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';
    recognition.onresult = (e: any) => {
      const transcript = e.results[0][0].transcript;
      setInput(transcript);
      setListening(false);
    };
    recognition.onerror = () => setListening(false);
    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  };

  const openHistory = async () => {
    const sessions = await listChatSessions();
    setChatSessions(sessions);
    setShowHistory(!showHistory);
  };

  // Load case chat history when entering case chat mode
  useEffect(() => {
    if (caseChatId) {
      (async () => {
        const res = await fetchCaseChatHistory(caseChatId);
        if (res.messages && res.messages.length > 0) {
          setMessages(res.messages);
        }
      })();
    }
  }, [caseChatId]);

  const askAgent = (msg: string) => { setInput(msg); };

  const priBadge = (p: string) => p ? `badge badge-${p.toLowerCase()}` : '';
  const stsBadge = (s: string) => {
    if (!s) return 'badge';
    const k = s.toLowerCase();
    if (k.includes('assigned')) return 'badge badge-assigned';
    if (k.includes('pending')) return 'badge badge-pending';
    if (k.includes('complete')) return 'badge badge-complete';
    if (k.includes('declined')) return 'badge badge-declined';
    return 'badge';
  };

  return (
    <div ref={appRef} data-theme={theme} className={`app-root theme-${theme}`} style={{ height: '100vh', display: 'flex', flexDirection: 'column', userSelect: dragging ? 'none' : 'auto' }}>
      {/* Header */}
      <div className="app-header">
        <h1>
          <img src="/helio-logo.png" alt="Helio" style={{ height: 30, borderRadius: 6 }} />
          Smart Underwriting Workbench
          <span className="header-subtitle">| AI-Powered Underwriter Accelerator</span>
        </h1>
        <div className="user-info">
          <span className="powered-by"></span>
          <button className="btn-icon" onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')} title="Toggle theme">
            {theme === 'dark' ? '☀️' : '🌙'}
          </button>
        </div>
      </div>

      <div className="app-body">
        {/* ── Dashboard ── */}
        <div className="dashboard-panel" style={{ width: `${dashWidth}%` }}>
          {selectedCase ? (
            <SubmissionDetail
              caseId={selectedCase}
              onBack={() => setSelectedCase(null)}
              onDecisionMade={() => { setSelectedCase(null); loadData(); }}
            />
          ) : selectedError ? (
            <ErrorDetail
              errorId={selectedError}
              onBack={() => setSelectedError(null)}
              onAction={() => { setSelectedError(null); loadData(); }}
            />
          ) : selectedPending ? (
            <PendingDetail
              caseId={selectedPending}
              onBack={() => setSelectedPending(null)}
              onAction={() => { setSelectedPending(null); loadData(); }}
            />
          ) : (
          <div className="detail-page" style={{ paddingBottom: 40 }}>
          {/* Stats */}
          <div className="stats-row">
            {[
              { val: stats.total || 0, label: 'Total Submissions', cls: 'accent' },
              { val: stats.assigned || 0, label: 'Assigned', cls: 'green' },
              { val: stats.pending || 0, label: 'Pending', cls: 'amber' },
              { val: stats.p0_count || 0, label: 'P0 Priority', cls: 'red' },
              { val: `$${((stats.total_sum_insured || 0) / 1e6).toFixed(1)}M`, label: 'Total Sum Insured', cls: '' },
              { val: (stats.avg_risk_score || 0).toFixed(1), label: 'Avg Risk Score', cls: '' },
            ].map((s, i) => (
              <div key={i} className={`stat-card ${s.cls}`}>
                <div className="stat-value">{s.val}</div>
                <div className="stat-label">{s.label}</div>
              </div>
            ))}
          </div>

          {/* Alert banners */}
          {errors.length > 0 && (
            <div className="alert-banner alert-red" onClick={() => setActiveTab('errors')}>
              ⚠️ {errors.length} unresolved processing error{errors.length > 1 ? 's' : ''} — click to view
            </div>
          )}
          {pendingApprovals.length > 0 && (
            <div className="alert-banner alert-amber" onClick={() => setActiveTab('pending')}>
              🔔 {pendingApprovals.length} submission{pendingApprovals.length > 1 ? 's' : ''} pending classification approval
            </div>
          )}

          {/* Charts */}
          <div className="charts-row">
            <div className="chart-card">
              <h3>📊 Case Status Distribution</h3>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={statusData} dataKey="count" nameKey="status" cx="50%" cy="50%" outerRadius={75} innerRadius={40}
                    paddingAngle={3} label={({ status, count }: any) => `${status} (${count})`} labelLine={true}>
                    {statusData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="none" />)}
                  </Pie>
                  <Tooltip contentStyle={tooltipStyle} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="chart-card">
              <h3>🎯 Priority Breakdown</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={priorityData} barCategoryGap="30%">
                  <defs>
                    <linearGradient id="gradP0" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#f43f5e" /><stop offset="100%" stopColor="#e11d48" stopOpacity={0.6} /></linearGradient>
                    <linearGradient id="gradP1" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#f59e0b" /><stop offset="100%" stopColor="#d97706" stopOpacity={0.6} /></linearGradient>
                    <linearGradient id="gradDefault" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6366f1" /><stop offset="100%" stopColor="#4f46e5" stopOpacity={0.6} /></linearGradient>
                  </defs>
                  <XAxis dataKey="priority" tick={{ fill: '#8b8fa3', fontSize: 12, fontWeight: 600 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#555770', fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(99,102,241,0.05)' }} />
                  <Bar dataKey="count" radius={[8, 8, 4, 4]} maxBarSize={50}>
                    {priorityData.map((d: any, i: number) => (
                      <Cell key={i} fill={d.priority === 'P0' ? 'url(#gradP0)' : d.priority === 'P1' ? 'url(#gradP1)' : 'url(#gradDefault)'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="chart-card">
              <h3>👥 Workload by Assignee</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={assigneeData} layout="vertical" barCategoryGap="25%">
                  <defs>
                    <linearGradient id="gradGreen" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor="#10b981" /><stop offset="100%" stopColor="#06b6d4" /></linearGradient>
                  </defs>
                  <XAxis type="number" tick={{ fill: '#555770', fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <YAxis type="category" dataKey="assigned_to" tick={{ fill: '#8b8fa3', fontSize: 11, fontWeight: 500 }} width={100} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(16,185,129,0.05)' }} />
                  <Bar dataKey="count" fill="url(#gradGreen)" radius={[0, 8, 8, 0]} maxBarSize={35} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Analytics Section */}
          <div className="charts-row two-col">
            <div className="chart-card">
              <h3>💰 Cases by Sum Insured</h3>
              <ResponsiveContainer width="100%" height={150}>
                <BarChart data={(() => {
                  const buckets = [
                    { range: '<100K', min: 0, max: 100000 },
                    { range: '100K-500K', min: 100000, max: 500000 },
                    { range: '500K-1M', min: 500000, max: 1000000 },
                    { range: '1M-5M', min: 1000000, max: 5000000 },
                    { range: '5M-10M', min: 5000000, max: 10000000 },
                    { range: '>10M', min: 10000000, max: Infinity },
                  ];
                  return buckets.map(b => ({
                    range: b.range,
                    count: submissions.filter(s => { const v = Number(s.sum_insured) || 0; return v >= b.min && v < b.max; }).length
                  }));
                })()}>
                  <defs><linearGradient id="gradCyan" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#06b6d4" /><stop offset="100%" stopColor="#0891b2" stopOpacity={0.6} /></linearGradient></defs>
                  <XAxis dataKey="range" tick={{ fill: '#8b8fa3', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#8b8fa3', fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(6,182,212,0.05)' }} />
                  <Bar dataKey="count" fill="url(#gradCyan)" radius={[6, 6, 2, 2]} maxBarSize={40} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="chart-card">
              <h3>🚫 Decline Reasons</h3>
              {submissions.filter(s => s.status === 'Declined').length === 0 ? (
                <div className="empty-state" style={{ height: 130, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12 }}>No declined cases yet</div>
              ) : (
                <ResponsiveContainer width="100%" height={150}>
                  <PieChart>
                    <Pie data={(() => {
                      const declined = submissions.filter(s => s.status === 'Declined');
                      const reasons: Record<string, number> = {};
                      declined.forEach(s => { reasons[s.decline_reason || 'Declined by UW'] = (reasons[s.decline_reason || 'Declined by UW'] || 0) + 1; });
                      return Object.entries(reasons).map(([name, value]) => ({ name, value }));
                    })()} cx="50%" cy="50%" outerRadius={55} innerRadius={30} paddingAngle={3} dataKey="value"
                      label={({ name, value }: any) => `${name} (${value})`} labelLine={true}>
                      {COLORS.map((c, i) => <Cell key={i} fill={c} stroke="none" />)}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Tab bar */}
          <div className="tab-bar">
            <button className={`tab ${activeTab === 'submissions' ? 'tab-active' : ''}`} onClick={() => setActiveTab('submissions')}>
              📄 Submissions ({submissions.length})
            </button>
            <button className={`tab ${activeTab === 'errors' ? 'tab-active' : ''}`} onClick={() => setActiveTab('errors')}>
              ⚠️ Errors ({errors.length})
            </button>
            <button className={`tab ${activeTab === 'pending' ? 'tab-active' : ''}`} onClick={() => setActiveTab('pending')}>
              🔔 Pending Approval ({pendingApprovals.length})
            </button>
            <div className="status-info-wrapper">
              <button className="status-info-btn" onClick={() => setShowStatusInfo(!showStatusInfo)} title="Status Guide">ℹ</button>
              {showStatusInfo && (
                <div className="status-info-popover">
                  <div className="status-info-title">Status Guide</div>
                  <div className="status-info-item"><span className="si-dot" style={{background:'#6366f1'}}/>Classification — Identifying document types (ACORD 125, 140, etc.)</div>
                  <div className="status-info-item"><span className="si-dot" style={{background:'#8b5cf6'}}/>Extraction — Pulling key fields from documents using AI</div>
                  <div className="status-info-item"><span className="si-dot" style={{background:'#a855f7'}}/>Client History — Checking prior submissions and claims</div>
                  <div className="status-info-item"><span className="si-dot" style={{background:'#f59e0b'}}/>Evaluation — Applying underwriting rules and scoring risk</div>
                  <div className="status-info-item"><span className="si-dot" style={{background:'#10b981'}}/>Assigned — Ready for underwriter review</div>
                  <div className="status-info-item"><span className="si-dot" style={{background:'#22c55e'}}/>Complete — Accepted by underwriter</div>
                  <div className="status-info-item"><span className="si-dot" style={{background:'#ef4444'}}/>Declined — Rejected by underwriter</div>
                </div>
              )}
            </div>
          </div>

          {/* Submissions Table */}
          {activeTab === 'submissions' && (
            <div className="table-card">
              <div className="table-header">
                <div className="filters">
                  <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
                    <option value="">All Status</option>
                    <option value="Assigned">Assigned</option>
                    <option value="Complete">Complete</option>
                    <option value="Declined">Declined</option>
                  </select>
                  <input placeholder="Filter assignee..." value={filterAssignee} onChange={e => setFilterAssignee(e.target.value)} />
                  <button className="btn btn-primary btn-sm" onClick={loadData}>↻ Refresh</button>
                </div>
              </div>
              <div className="table-scroll">
                <table>
                  <thead><tr>
                    <th>Case ID</th><th>Insured</th><th>LoB</th><th>Broker</th>
                    <th>Priority</th><th>Risk</th><th>Sum Insured</th><th>Status</th><th>Assignee</th><th>Created</th><th></th>
                  </tr></thead>
                  <tbody>
                    {submissions.filter(s => s.status !== 'Pending Classification').map((s: any) => {
                      const rag = (() => {
                        if (!s.effective_date) return '';
                        try {
                          const parts = s.effective_date.includes('/') ? s.effective_date.split('/') : null;
                          const eff = parts ? new Date(`${parts[2]}-${parts[0]}-${parts[1]}`) : new Date(s.effective_date);
                          const days = Math.ceil((eff.getTime() - Date.now()) / 86400000);
                          if (days < 3) return 'red';
                          if (days < 10) return 'amber';
                          return 'green';
                        } catch { return ''; }
                      })();
                      const createdStr = (() => {
                        try {
                          const v = s.created_on?.value || s.created_on;
                          return v ? new Date(v).toLocaleDateString() : '';
                        } catch { return ''; }
                      })();
                      return (
                      <tr key={s.case_id}>
                        <td style={{ color: 'var(--accent)', fontWeight: 600, cursor: 'pointer' }}
                          onClick={() => setSelectedCase(s.case_id)}>{s.case_id}</td>
                        <td>{s.insured_name}</td>
                        <td style={{ fontSize: 11 }}>{s.lob}</td>
                        <td>{s.broker}</td>
                        <td><span className={priBadge(s.priority)}>{s.priority}</span></td>
                        <td>{s.risk_score != null ? `${s.risk_score} — ${s.risk_level || ''}` : '—'}</td>
                        <td>{s.sum_insured ? `$${Number(s.sum_insured).toLocaleString()}` : '—'}</td>
                        <td>
                          {s.status === 'Processing' ? (
                            <span className="badge badge-processing">
                              <span className="processing-dot" />
                              {(s.current_step || 'starting').replace('_', ' ')}
                            </span>
                          ) : (
                            <span className={stsBadge(s.status)}>{s.status}</span>
                          )}
                        </td>
                        <td style={{ fontSize: 12 }}>{s.assigned_to}</td>
                        <td style={{ fontSize: 11, opacity: 0.7 }}>{createdStr}</td>
                        <td className="action-cell">
                          <button className="btn btn-sm btn-primary" onClick={() => setSelectedCase(s.case_id)}>View</button>
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Errors Table */}
          {activeTab === 'errors' && (
            <div className="table-card">
              <div className="table-header"><h3>⚠️ Unresolved Processing Errors</h3></div>
              {errors.length === 0 ? (
                <div className="empty-state">✅ No unresolved errors</div>
              ) : (
                <div className="table-scroll">
                  <table>
                    <thead><tr>
                      <th>Error ID</th><th>Case ID</th><th>Failed Step</th><th>Error</th><th>Last OK Step</th><th>Time</th><th></th>
                    </tr></thead>
                    <tbody>
                      {errors.map((e: any) => (
                        <tr key={e.error_id}>
                          <td style={{ color: 'var(--red)', fontWeight: 600 }}>{e.error_id}</td>
                          <td style={{ color: 'var(--accent)', fontSize: 12 }}>{e.case_id || '—'}</td>
                          <td><span className="badge badge-declined">{e.error_step}</span></td>
                          <td style={{ fontSize: 11, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.error_message}</td>
                          <td>{e.last_successful_step}</td>
                          <td style={{ fontSize: 11 }}>{e.created_on ? new Date(e.created_on.value || e.created_on).toLocaleString() : ''}</td>
                          <td>
                            <button className="btn btn-sm btn-primary" onClick={() => setSelectedError(e.error_id)}>View</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Pending Approval Table */}
          {activeTab === 'pending' && (
            <div className="table-card">
              <div className="table-header"><h3>🔔 Pending Classification Approval</h3></div>
              {pendingApprovals.length === 0 ? (
                <div className="empty-state">✅ No pending approvals</div>
              ) : (
                <div className="table-scroll">
                  <table>
                    <thead><tr>
                      <th>Case ID</th><th>Insured</th><th>GCS Folder</th><th>Created</th><th></th>
                    </tr></thead>
                    <tbody>
                      {pendingApprovals.map((s: any) => (
                        <tr key={s.case_id}>
                          <td style={{ color: 'var(--amber)', fontWeight: 600 }}>{s.case_id}</td>
                          <td>{s.insured_name || '—'}</td>
                          <td style={{ fontSize: 11 }}>{s.gcs_folder}</td>
                          <td style={{ fontSize: 11 }}>{s.created_on ? new Date(s.created_on.value || s.created_on).toLocaleString() : ''}</td>
                          <td>
                            <button className="btn btn-sm btn-primary" onClick={() => setSelectedPending(s.case_id)}>Review</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          </div>
          )}
        </div>

        {/* Resizer */}
        <div className="resizer" onMouseDown={() => setDragging(true)} />

        {/* ── Chat ── */}
        <div className="chat-panel" style={{ width: `${100 - dashWidth}%` }}>
          <div className="chat-header">
            <svg width="20" height="20" viewBox="0 0 28 28" fill="none"><path d="M14 0C14 7.732 7.732 14 0 14c7.732 0 14 6.268 14 14 0-7.732 6.268-14 14-14C20.268 14 14 7.732 14 0Z" fill="url(#gemini-grad)"/><defs><linearGradient id="gemini-grad" x1="0" y1="0" x2="28" y2="28"><stop stopColor="#4285F4"/><stop offset="0.5" stopColor="#9B72CB"/><stop offset="1" stopColor="#D96570"/></linearGradient></defs></svg>
            <h3>{caseChatId ? `Case: ${caseChatId}` : 'Powered by Gemini'}</h3>
            <div style={{ flex: 1 }} />
            {caseChatId && <button className="btn btn-sm btn-exit-case" onClick={() => { setCaseChatId(null); setMessages([]); }}>✕ Exit Case</button>}
            <button className="btn-icon chat-history-btn" onClick={openHistory} title="Chat history">💬</button>
            <button className="btn-icon chat-new-btn" onClick={clearChat} title="New chat">✦</button>
          </div>
          {showHistory && (
            <div className="chat-history-dropdown">
              <div className="chat-history-header">
                <span>💬 Recent Conversations</span>
                <button className="btn-icon" onClick={() => setShowHistory(false)} style={{fontSize:12}}>✕</button>
              </div>
              {chatSessions.length === 0 ? (
                <div className="chat-history-empty">No saved conversations yet</div>
              ) : chatSessions.map(s => (
                <div key={s.session_id} className="chat-history-item" onClick={() => loadSession(s.session_id)}>
                  <div className="chat-history-item-icon">💬</div>
                  <div className="chat-history-item-content">
                    <span className="chat-history-item-title">{s.title || 'Untitled'}</span>
                    <span className="chat-history-item-date">{new Date(s.created_on).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="chat-messages">
            {messages.length === 0 && !caseChatId && (
              <div className="chat-welcome">
                <svg width="42" height="42" viewBox="0 0 28 28" fill="none" style={{margin: '0 auto 12px'}}><path d="M14 0C14 7.732 7.732 14 0 14c7.732 0 14 6.268 14 14 0-7.732 6.268-14 14-14C20.268 14 14 7.732 14 0Z" fill="url(#gemini-grad2)"/><defs><linearGradient id="gemini-grad2" x1="0" y1="0" x2="28" y2="28"><stop stopColor="#4285F4"/><stop offset="0.5" stopColor="#9B72CB"/><stop offset="1" stopColor="#D96570"/></linearGradient></defs></svg>
                <h2>Hello!</h2>
                <p>Let's get some work done.</p>
                <div className="quick-actions">
                  <button className="chip" onClick={() => askAgent('What are my submissions?')}>📊 My Submissions</button>
                  <button className="chip" onClick={() => askAgent('What should I work on first?')}>🎯 Top Priority</button>
                  <button className="chip" onClick={() => askAgent('Any failed submissions?')}>⚠️ Check Errors</button>
                </div>
              </div>
            )}
            {messages.length === 0 && caseChatId && (
              <div className="chat-welcome">
                <h2>Case: {caseChatId}</h2>
                <p>This is a persistent conversation for this case. Ask anything — your chat history is saved and will resume next time.</p>
                <div className="quick-actions">
                  <button className="chip" onClick={() => setInput('Show me the full details')}>Details</button>
                  <button className="chip" onClick={() => setInput('Justify the priority and risk score')}>Justify</button>
                  <button className="chip" onClick={() => setInput('What should I check before deciding?')}>Review Guide</button>
                  <button className="chip" onClick={() => setInput('Compare with similar past cases')}>Compare</button>
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`msg msg-${m.role}`}>
                {m.role === 'agent' ? (
                  <>
                    {streaming && i === messages.length - 1 && !m.text && (
                      <div className="thinking-indicator">
                        <div className="thinking-dots"><span/><span/><span/></div>
                      </div>
                    )}
                    {m.text && (
                      <div className={streaming && i === messages.length - 1 ? 'msg-streaming' : ''}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                          a: ({href, children}) => {
                            const text = String(children);
                            const caseMatch = text.match(/^(NB-\d+-\d+)$/);
                            if (caseMatch) {
                              return <span style={{ color: 'var(--accent)', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline' }} onClick={() => { setSelectedCase(caseMatch[1]); setSelectedError(null); setSelectedPending(null); }}>{text}</span>;
                            }
                            if (href?.startsWith('case:')) {
                              const cid = href.replace('case:', '');
                              return <span style={{ color: 'var(--accent)', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline' }} onClick={() => { setSelectedCase(cid); setSelectedError(null); setSelectedPending(null); }}>{children}</span>;
                            }
                            return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
                          }
                        }}>{m.text.replace(/\[\[CASE:(NB-\d+-\d+)\]\]/g, '[$1](case:$1)')}</ReactMarkdown>
                      </div>
                    )}
                  </>
                ) : m.text}
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>

          <div className="chat-input-area">
            <div className="chat-input-wrapper">
              <input
                className="chat-input"
                placeholder="Ask anything, @mention or /tools"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendMessage()}
                disabled={streaming}
              />
              <button className={`mic-btn${listening ? ' mic-active' : ''}`} onClick={toggleVoice} title={listening ? 'Stop listening' : 'Voice input'}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
              </button>
              <button className="chat-send" onClick={sendMessage} disabled={streaming || !input.trim()}>➤</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
