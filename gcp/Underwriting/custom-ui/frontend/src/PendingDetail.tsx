import { useState, useEffect } from 'react';
import { fetchSubmission, fetchSubmissionFiles } from './api';

interface Props {
  caseId: string;
  onBack: () => void;
  onAction: () => void;
}

export default function PendingDetail({ caseId, onBack, onAction }: Props) {
  const [data, setData] = useState<any>(null);
  const [files, setFiles] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [comment, setComment] = useState('');

  useEffect(() => {
    Promise.all([fetchSubmission(caseId), fetchSubmissionFiles(caseId)]).then(([sub, filesRes]) => {
      setData(sub);
      setFiles(filesRes.files || []);
      setLoading(false);
    });
  }, [caseId]);

  const handleApprove = async () => {
    setActing(true);
    const classifications = Object.entries(overrides)
      .filter(([_, v]) => v)
      .map(([filename, classified_as]) => ({ filename, classified_as }));
    await fetch(`/api/submissions/${caseId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ classifications, comment }),
    });
    setActing(false);
    onAction();
  };

  const handleReject = async () => {
    if (!comment.trim()) { alert('Please provide a reason for rejection'); return; }
    setActing(true);
    await fetch(`/api/submissions/${caseId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: comment }),
    });
    setActing(false);
    onAction();
  };

  if (loading) return <div className="detail-loading"><div className="thinking-dots"><span/><span/><span/></div></div>;
  if (!data) return <div className="detail-loading">Case not found</div>;

  let classifications: any[] = [];
  try { classifications = JSON.parse(data.classification_json || '[]'); } catch {}

  return (
    <div className="detail-page">
      <button className="btn btn-sm btn-secondary" onClick={onBack} style={{ marginBottom: 16 }}>← Back</button>

      <div className="detail-card">
        <h3>🔔 Pending Classification Approval</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 13 }}>
          <div><span className="muted">Case ID:</span> <strong style={{ color: 'var(--accent)' }}>{data.case_id}</strong></div>
          <div><span className="muted">Insured:</span> {data.insured_name || '—'}</div>
          <div><span className="muted">Status:</span> <span className="badge badge-amber">{data.status}</span></div>
          <div><span className="muted">Current Step:</span> {data.current_step}</div>
        </div>
      </div>

      <div className="detail-card">
        <h3>📂 Source Documents</h3>
        {files.length === 0 ? (
          <p className="muted">No files found</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {files.map((f: any, i: number) => (
              <a key={i} href={f.url} target="_blank" rel="noreferrer" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: 'rgba(99,102,241,0.05)', borderRadius: 6, border: '1px solid var(--border)', textDecoration: 'none', color: 'var(--text)', fontSize: 12 }}>
                <span>📄</span>
                <span style={{ flex: 1 }}>{f.name}</span>
                <span className="muted" style={{ fontSize: 10 }}>{f.size ? `${(f.size / 1024).toFixed(0)} KB` : ''}</span>
              </a>
            ))}
          </div>
        )}
      </div>

      <div className="detail-card">
        <h3>📄 Classification Results</h3>
        {classifications.length === 0 ? (
          <p className="muted">No classification data available</p>
        ) : (
          <table style={{ width: '100%', fontSize: 12 }}>
            <thead><tr>
              <th style={{ textAlign: 'left', padding: '8px', borderBottom: '1px solid var(--border)' }}>Filename</th>
              <th style={{ textAlign: 'left', padding: '8px', borderBottom: '1px solid var(--border)' }}>Classified As</th>
              <th style={{ textAlign: 'left', padding: '8px', borderBottom: '1px solid var(--border)' }}>Confidence</th>
              <th style={{ textAlign: 'left', padding: '8px', borderBottom: '1px solid var(--border)' }}>Reason</th>
              <th style={{ textAlign: 'left', padding: '8px', borderBottom: '1px solid var(--border)' }}>Override</th>
            </tr></thead>
            <tbody>
              {classifications.map((c: any, i: number) => (
                <tr key={i}>
                  <td style={{ padding: '8px', borderBottom: '1px solid var(--border)' }}>{c.filename}</td>
                  <td style={{ padding: '8px', borderBottom: '1px solid var(--border)' }}>
                    <span className={`badge ${c.classified_as === 'UNKNOWN' ? 'badge-declined' : 'badge-assigned'}`}>{c.classified_as}</span>
                  </td>
                  <td style={{ padding: '8px', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ color: c.confidence >= 80 ? '#22c55e' : c.confidence >= 50 ? '#f59e0b' : '#ef4444', fontWeight: 600 }}>{c.confidence}%</span>
                  </td>
                  <td style={{ padding: '8px', borderBottom: '1px solid var(--border)', fontSize: 11 }}>{c.reason || '—'}</td>
                  <td style={{ padding: '8px', borderBottom: '1px solid var(--border)' }}>
                    <select style={{ fontSize: 11, padding: '4px 6px', borderRadius: 4, background: 'var(--bg-card)', color: 'var(--text)', border: '1px solid var(--border)' }}
                      value={overrides[c.filename] || ''} onChange={e => setOverrides(prev => ({ ...prev, [c.filename]: e.target.value }))}>
                      <option value="">— Keep —</option>
                      <option value="ACORD_125">ACORD 125</option>
                      <option value="ACORD_140">ACORD 140</option>
                      <option value="LOSS_RUN">Loss Run</option>
                      <option value="SOV">Schedule of Values</option>
                      <option value="OTHER">Other</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="detail-card">
        <h3>💬 Underwriter Comments</h3>
        <textarea
          value={comment}
          onChange={e => setComment(e.target.value)}
          placeholder="Provide classification details (for approval) or reason for rejection..."
          style={{ width: '100%', minHeight: 80, padding: 10, fontSize: 12, borderRadius: 6, background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border)', color: 'var(--text)', resize: 'vertical' }}
        />
      </div>

      <div className="detail-card" style={{ display: 'flex', gap: 12 }}>
        <button className="btn btn-primary" onClick={handleApprove} disabled={acting}>
          {acting ? 'Processing...' : '✓ Approve & Continue Processing'}
        </button>
        <button className="btn btn-secondary" style={{ borderColor: '#ef4444', color: '#ef4444' }} onClick={handleReject} disabled={acting}>
          {acting ? 'Rejecting...' : '✕ Reject Submission'}
        </button>
      </div>
    </div>
  );
}
