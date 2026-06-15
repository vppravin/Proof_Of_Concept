import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { fetchSubmission, fetchSubmissionFiles, fetchJustification, recordDecision, fetchAgentLogs } from './api';

interface Props {
  caseId: string;
  onBack: () => void;
  onDecisionMade: () => void;
}

function RadialGauge({ score, max = 12, level }: { score: number; max?: number; level: string }) {
  const pct = Math.min((score / max) * 100, 100);
  const angle = (pct / 100) * 180;
  const color = pct <= 25 ? '#22c55e' : pct <= 50 ? '#f59e0b' : '#ef4444';
  const r = 60, cx = 70, cy = 70;
  const startX = cx - r, startY = cy;
  const rad = (angle * Math.PI) / 180;
  const endX = cx - r * Math.cos(rad), endY = cy - r * Math.sin(rad);
  const largeArc = angle > 180 ? 1 : 0;
  const path = `M ${startX} ${startY} A ${r} ${r} 0 ${largeArc} 1 ${endX} ${endY}`;

  return (
    <div className="radial-gauge">
      <svg width="140" height="80" viewBox="0 0 140 80">
        <path d="M 10 70 A 60 60 0 0 1 130 70" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="10" strokeLinecap="round" />
        <path d={path} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" />
      </svg>
      <div className="gauge-text">
        <span className="gauge-score" style={{ color }}>{score}</span>
        <span className="gauge-max">/ {max}</span>
      </div>
      <div className="gauge-level" style={{ color }}>{level}</div>
    </div>
  );
}

const STEPS = ['Classification', 'Extraction', 'Client History', 'Evaluation', 'Complete'];
const STEP_KEYS = ['classification', 'extraction', 'client_history', 'evaluation', 'complete'];

function HorizontalPipeline({ currentStep, status }: { currentStep: string; status: string }) {
  const currentIdx = STEP_KEYS.indexOf(currentStep);
  return (
    <div className="h-pipeline">
      {STEPS.map((step, i) => {
        const isDone = i < currentIdx || status === 'Assigned' || status === 'Complete' || status === 'Declined';
        const isActive = i === currentIdx && status === 'Processing';
        return (
          <div key={i} className="h-pipeline-step">
            <div className={`h-step-node ${isDone ? 'done' : isActive ? 'active' : 'pending'}`}>
              {isDone ? '✓' : isActive ? <span className="h-step-pulse" /> : (i + 1)}
            </div>
            <span className={`h-step-label ${isDone ? 'done' : isActive ? 'active' : ''}`}>{step}</span>
            {i < STEPS.length - 1 && <div className={`h-step-arrow ${isDone ? 'done' : ''}`} />}
          </div>
        );
      })}
    </div>
  );
}

export default function SubmissionDetail({ caseId, onBack, onDecisionMade }: Props) {
  const [data, setData] = useState<any>(null);
  const [files, setFiles] = useState<any[]>([]);
  const [extracted, setExtracted] = useState<any>({});
  const [uwResult, setUwResult] = useState<any>({});
  const [justification, setJustification] = useState<string>('');
  const [justLoading, setJustLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [deciding, setDeciding] = useState(false);
  const [notes, setNotes] = useState('');
  const [activeTab, setActiveTab] = useState<'details' | 'logs'>('details');
  const [agentLogs, setAgentLogs] = useState<any[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      const [sub, filesRes] = await Promise.all([
        fetchSubmission(caseId),
        fetchSubmissionFiles(caseId),
      ]);
      setData(sub);
      setFiles(filesRes.files || []);
      try { setExtracted(JSON.parse(sub.extracted_json || '{}')); } catch { setExtracted({}); }
      try { setUwResult(JSON.parse(sub.uw_result_json || '{}')); } catch { setUwResult({}); }
      setLoading(false);

      setJustLoading(true);
      const justRes = await fetchJustification(caseId);
      setJustification(justRes.justification || '');
      setJustLoading(false);
    })();
  }, [caseId]);

  // Fetch agent logs — poll every 1s during processing, once when done
  useEffect(() => {
    if (!data) return;
    const poll = async () => {
      const r = await fetchAgentLogs(caseId);
      if (r.logs?.length) setAgentLogs(r.logs);
    };
    poll();
    if (data.status === 'Processing') {
      const interval = setInterval(poll, 500);
      return () => clearInterval(interval);
    }
  }, [caseId, data?.status]);

  // Auto-scroll logs
  useEffect(() => {
    if (activeTab === 'logs') logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [agentLogs, activeTab]);

  const handleDecision = async (decision: string) => {
    setDeciding(true);
    await recordDecision(caseId, decision, 'Underwriter', notes);
    onDecisionMade();
    setDeciding(false);
  };

  if (loading) return <div className="detail-loading"><div className="thinking-dots"><span/><span/><span/></div></div>;
  if (!data) return <div className="detail-loading">Submission not found</div>;

  const riskBreakdown = uwResult.risk_breakdown || {};
  const lossHistory = extracted.loss_history || [];
  const locationRisk = (extracted.location_risk_enrichment || [])[0] || {};
  const renewalDays = extracted.renewal_days;
  const isOverdue = renewalDays != null && renewalDays < 0;
  const isUrgent = renewalDays != null && renewalDays >= 0 && renewalDays < 30;

  return (
    <div className="detail-page">
      {/* Header */}
      <div className="detail-header">
        <button className="btn btn-back" onClick={onBack}>← Back to Dashboard</button>
        <div className="detail-title">
          <h2>{caseId}</h2>
          <span className="detail-insured">{data.insured_name}</span>
        </div>
        <div className="detail-badges">
          <span className={`badge badge-${(data.priority || '').toLowerCase()}`}>{data.priority}</span>
          <span className={`badge badge-${data.status?.toLowerCase().includes('assigned') ? 'assigned' : data.status?.toLowerCase().includes('complete') ? 'complete' : 'declined'}`}>{data.status}</span>
        </div>
      </div>

      {/* Horizontal Pipeline */}
      <HorizontalPipeline currentStep={data.current_step} status={data.status} />

      {/* Tabs */}
      <div className="detail-tabs">
        <button className={`detail-tab ${activeTab === 'details' ? 'active' : ''}`} onClick={() => setActiveTab('details')}>
          📋 Details
        </button>
        <button className={`detail-tab ${activeTab === 'logs' ? 'active' : ''}`} onClick={() => setActiveTab('logs')}>
          🖥️ Agent Logs {data.status === 'Processing' && <span className="processing-dot" />}
          {agentLogs.length > 0 && <span className="tab-badge">{agentLogs.length}</span>}
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === 'details' ? (
        <div className="detail-body">
          {/* Left */}
          <div className="detail-left">
            <div className="detail-card">
              <h3>📄 Source Documents</h3>
              {files.length === 0 ? (
                <p className="muted">No files available</p>
              ) : (
                <div className="file-list">
                  {files.map((f, i) => (
                    <a key={i} href={f.url} target="_blank" rel="noopener noreferrer" className="file-item">
                      <div className="file-info">
                        <span className="file-name">{f.filename}</span>
                        <span className="file-size">{(f.size_bytes / 1024).toFixed(0)} KB</span>
                      </div>
                      {f.classified_as && (
                        <div className="file-classification">
                          <span className="file-type-badge">{f.classified_as}</span>
                          {f.confidence && <span className="file-confidence">{f.confidence}%</span>}
                        </div>
                      )}
                    </a>
                  ))}
                </div>
              )}
            </div>

            {data.created_on && (
              <div className="detail-card">
                <h3>📅 Timeline</h3>
                <div className="timeline">
                  <div className="timeline-item"><span className="tl-dot green" /><span>Created: {new Date(data.created_on).toLocaleDateString()}</span></div>
                  {data.updated_on && <div className="timeline-item"><span className="tl-dot blue" /><span>Updated: {new Date(data.updated_on).toLocaleDateString()}</span></div>}
                  {data.decision_at && <div className="timeline-item"><span className="tl-dot" style={{background: data.decision === 'accept' ? '#22c55e' : '#ef4444'}} /><span>{data.decision === 'accept' ? 'Accepted' : 'Declined'}: {new Date(data.decision_at).toLocaleDateString()} by {data.decision_by}</span></div>}
                </div>
              </div>
            )}
          </div>

          {/* Right */}
          <div className="detail-right">
            <div className="detail-card risk-card">
              <h3>📈 Risk Assessment</h3>
              <div className="risk-section">
                <RadialGauge score={data.risk_score || 0} level={data.risk_level || 'Unknown'} />
                <table className="detail-table risk-table">
                  <thead><tr><th>Factor</th><th>Value</th><th>Rule</th><th>Score</th></tr></thead>
                  <tbody>
                    {Object.entries(riskBreakdown).map(([key, val]: [string, any]) => (
                      <tr key={key}>
                        <td className="factor-name">{key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</td>
                        <td>{val?.value ?? '—'}</td>
                        <td className="muted">{val?.rule ?? '—'}</td>
                        <td><span className="score-pill" style={{background: val?.score > 0 ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)', color: val?.score > 0 ? '#f87171' : '#4ade80'}}>{val?.score ?? 0}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="detail-card">
              <h3>🎯 Priority & Assignment</h3>
              <div className="detail-grid">
                <div className="dg-item"><span className="dg-label">Priority</span><span className={`badge badge-${(data.priority || '').toLowerCase()}`}>{data.priority}</span></div>
                <div className="dg-item"><span className="dg-label">Base Rule</span><span>{uwResult.matched_lob_rule || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Overrides</span><span>{(uwResult.override_reasons || []).length > 0 ? (uwResult.override_reasons || []).join(', ') : 'None triggered'}</span></div>
                <div className="dg-item"><span className="dg-label">Assigned To</span><span>{data.assigned_to || '—'}</span></div>
                {data.auto_decline && <div className="dg-item"><span className="dg-label">Auto-Decline</span><span className="red">{data.decline_reason}</span></div>}
              </div>
            </div>

            <div className="detail-card">
              <h3>👤 Insured Details</h3>
              <div className="detail-grid two-col">
                <div className="dg-item"><span className="dg-label">Name</span><span>{data.insured_name}</span></div>
                <div className="dg-item"><span className="dg-label">Address</span><span>{data.mailing_address || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">FEIN</span><span>{data.fein || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">SIC / NAICS</span><span>{data.sic_code || '—'}{extracted.naics_code ? ` / ${extracted.naics_code}` : ''}</span></div>
                <div className="dg-item"><span className="dg-label">Contact</span><span>{extracted.contact_person || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Phone</span><span>{extracted.contact_phone || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Email</span><span>{extracted.contact_email || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Employees</span><span>{data.no_of_employees || '—'}</span></div>
              </div>
            </div>

            <div className="detail-card">
              <h3>📄 Policy Information</h3>
              <div className="detail-grid two-col">
                <div className="dg-item"><span className="dg-label">Line of Business</span><span>{data.lob || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Broker</span><span>{data.broker || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Carrier</span><span>{data.proposed_carrier || extracted.proposed_carrier || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Effective Date</span><span>{data.effective_date || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Expiration Date</span><span>{data.expiration_date || extracted.expiration_date || '—'}</span></div>
                <div className="dg-item">
                  <span className="dg-label">Renewal</span>
                  <span className={isOverdue ? 'red' : isUrgent ? 'amber' : ''}>
                    {renewalDays != null ? `${renewalDays} days${isOverdue ? ' ⚠️ OVERDUE' : isUrgent ? ' ⚠️ URGENT' : ''}` : '—'}
                  </span>
                </div>
                <div className="dg-item"><span className="dg-label">Sum Insured</span><span className="highlight">${(data.sum_insured || 0).toLocaleString()}</span></div>
              </div>
            </div>

            <div className="detail-card">
              <h3>🏢 Premises & Building</h3>
              <div className="detail-grid two-col">
                <div className="dg-item"><span className="dg-label">Address</span><span>{extracted.premises_address || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Year Built</span><span>{data.year_built || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Construction</span><span>{data.construction_type || '—'}{extracted.construction_type_raw ? ` (${extracted.construction_type_raw})` : ''}</span></div>
                <div className="dg-item"><span className="dg-label">Roof</span><span>{extracted.roof_type || '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Stories / Area</span><span>{extracted.stories || '—'} stories • {extracted.total_area_sqft ? `${extracted.total_area_sqft.toLocaleString()} sqft` : '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Sprinkler</span><span>{extracted.sprinkler_pct != null ? `${extracted.sprinkler_pct}%` : '—'}</span></div>
                <div className="dg-item"><span className="dg-label">Fire Alarm</span><span>{extracted.fire_alarm_manufacturer || '—'} (Class {extracted.fire_protection_class || '—'})</span></div>
                <div className="dg-item"><span className="dg-label">Security</span><span>{extracted.burglar_alarm_type || '—'} • Guards: {extracted.security_guards || '—'}</span></div>
              </div>
            </div>

            <div className="detail-card">
              <h3>🌍 Location Risk</h3>
              <div className="detail-grid two-col">
                <div className="dg-item"><span className="dg-label">EQ Zone</span><span className={data.eq_zone === 'High' ? 'red' : data.eq_zone === 'Medium' ? 'amber' : ''}>{data.eq_zone || 'No'}</span></div>
                <div className="dg-item"><span className="dg-label">Flood Zone</span><span className={data.flood_zone === 'High' ? 'red' : data.flood_zone === 'Medium' ? 'amber' : ''}>{data.flood_zone || 'No'}</span></div>
                {locationRisk.zip_code && <div className="dg-item"><span className="dg-label">Location</span><span>{locationRisk.city}, {locationRisk.state} ({locationRisk.zip_code})</span></div>}
              </div>
            </div>

            <div className="detail-card">
              <h3>📊 Loss History</h3>
              {lossHistory.length === 0 ? (
                <p className="muted">No loss history recorded</p>
              ) : (
                <>
                  <div className="loss-summary">
                    <span>Total Claims: <strong>{extracted.total_claims || lossHistory.length}</strong></span>
                    <span>Total Incurred: <strong className="red">${(extracted.total_incurred || 0).toLocaleString()}</strong></span>
                  </div>
                  <table className="detail-table">
                    <thead><tr><th>Date</th><th>Description</th><th>Paid</th><th>Reserved</th><th>Total</th></tr></thead>
                    <tbody>
                      {lossHistory.map((l: any, i: number) => (
                        <tr key={i}>
                          <td>{l.date_of_loss}</td>
                          <td>{l.description}</td>
                          <td>${(l.paid_amount || 0).toLocaleString()}</td>
                          <td>${(l.reserved_amount || 0).toLocaleString()}</td>
                          <td className="highlight">${(l.total_incurred || 0).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>

            <div className="detail-card justification-card">
              <h3>🧠 Agent Justification</h3>
              {justLoading ? (
                <div className="just-loading">
                  <div className="thinking-dots"><span/><span/><span/></div>
                  <span className="muted">Generating justification...</span>
                </div>
              ) : (
                <div className="justification-text">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{justification || ''}</ReactMarkdown>
                </div>
              )}
            </div>

            {data.status === 'Assigned' && (
              <div className="detail-card decision-card">
                <h3>⚖️ Decision</h3>
                <textarea
                  className="decision-notes"
                  placeholder="Add decision notes (optional)..."
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                />
                <div className="decision-buttons">
                  <button className="btn btn-accept" onClick={() => handleDecision('accept')} disabled={deciding}>✅ Accept</button>
                  <button className="btn btn-decline" onClick={() => handleDecision('decline')} disabled={deciding}>❌ Decline</button>
                </div>
              </div>
            )}

            {data.decision && (
              <div className="detail-card">
                <h3>✓ Decision Recorded</h3>
                <div className="detail-grid">
                  <div className="dg-item"><span className="dg-label">Decision</span><span className={data.decision === 'accept' ? 'green' : 'red'}>{data.decision.toUpperCase()}</span></div>
                  <div className="dg-item"><span className="dg-label">By</span><span>{data.decision_by}</span></div>
                  {data.decision_at && <div className="dg-item"><span className="dg-label">At</span><span>{new Date(data.decision_at).toLocaleString()}</span></div>}
                  {data.decline_reason && <div className="dg-item"><span className="dg-label">Notes</span><span>{data.decline_reason}</span></div>}
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        /* Agent Logs Tab */
        <div className="agent-logs-tab">
          <div className="agent-timeline">
            {agentLogs.length === 0 ? (
              <div className="timeline-empty">
                {data.status === 'Processing' ? (
                  <div className="timeline-waiting">
                    <div className="waiting-pulse" />
                    <span>Agent is processing...</span>
                  </div>
                ) : 'No activity logs available.'}
              </div>
            ) : (
              agentLogs.map((l, i) => {
                const time = l.ts ? new Date(l.ts).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '';
                const isLast = i === agentLogs.length - 1;
                const hasMarkdown = l.text && (l.text.includes('|---|') || l.text.includes('##'));
                return (
                  <div key={i} className={`tl-entry ${isLast && data.status === 'Processing' ? 'tl-active' : ''}`} style={{animationDelay: `${i * 0.05}s`}}>
                    <div className="tl-connector">
                      <div className={`tl-dot ${isLast && data.status !== 'Processing' ? 'tl-dot-done' : ''}`} />
                      {i < agentLogs.length - 1 && <div className="tl-line" />}
                    </div>
                    <div className="tl-content">
                      <span className="tl-time">{time}</span>
                      {hasMarkdown ? (
                        <div className="tl-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{l.text}</ReactMarkdown></div>
                      ) : (
                        <p className="tl-text">{l.text}</p>
                      )}
                    </div>
                  </div>
                );
              })
            )}
            {agentLogs.length > 0 && data.status !== 'Processing' && (
              <div className="tl-entry tl-complete">
                <div className="tl-connector"><div className="tl-dot tl-dot-done" /></div>
                <div className="tl-content"><span className="tl-badge-done">Complete</span></div>
              </div>
            )}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}
    </div>
  );
}
