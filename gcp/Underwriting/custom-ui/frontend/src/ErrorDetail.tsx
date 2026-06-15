import { useState, useEffect } from 'react';
import { getErrorDetail, retryError, resolveError } from './api';
import PipelineStepper from './PipelineStepper';

interface Props {
  errorId: string;
  onBack: () => void;
  onAction: () => void;
}

export default function ErrorDetail({ errorId, onBack, onAction }: Props) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);

  useEffect(() => {
    getErrorDetail(errorId).then(d => { setData(d); setLoading(false); });
  }, [errorId]);

  const handleRetry = async () => {
    setActing(true);
    await retryError(errorId);
    setActing(false);
    onAction();
  };

  const handleResolve = async () => {
    setActing(true);
    await resolveError(errorId);
    setActing(false);
    onAction();
  };

  if (loading) return <div className="detail-loading"><div className="thinking-dots"><span/><span/><span/></div></div>;
  if (!data) return <div className="detail-loading">Error not found</div>;

  return (
    <div className="detail-page">
      <button className="btn btn-sm btn-secondary" onClick={onBack} style={{ marginBottom: 16 }}>← Back</button>

      <div className="detail-card">
        <h3>⚠️ Error Details</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 13 }}>
          <div><span className="muted">Error ID:</span> <strong style={{ color: '#ef4444' }}>{data.error_id}</strong></div>
          <div><span className="muted">Case ID:</span> <strong style={{ color: 'var(--accent)' }}>{data.case_id || '—'}</strong></div>
          <div><span className="muted">Timestamp:</span> {data.created_on ? new Date(data.created_on).toLocaleString() : '—'}</div>
          <div><span className="muted">Failed Step:</span> <span className="badge badge-declined">{data.error_step}</span></div>
          <div><span className="muted">Last OK Step:</span> {data.last_successful_step || 'None'}</div>
          <div><span className="muted">Retry Count:</span> {data.retry_count || 0}</div>
          <div><span className="muted">Resolved:</span> {data.resolved ? '✅ Yes' : '❌ No'}</div>
        </div>
      </div>

      <div className="detail-card">
        <h3>📂 Source</h3>
        <p style={{ fontSize: 12, wordBreak: 'break-all' }}>{data.gcs_folder}</p>
      </div>

      <div className="detail-card">
        <h3>⚡ Pipeline Status</h3>
        <PipelineStepper
          currentStep={data.error_step}
          status="Processing"
          error={{ step: data.error_step, message: data.error_message?.slice(0, 60) }}
        />
      </div>

      <div className="detail-card">
        <h3>📋 Error Message</h3>
        <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(239,68,68,0.05)', padding: 12, borderRadius: 8, border: '1px solid rgba(239,68,68,0.2)', color: '#fca5a5' }}>
          {data.error_message}
        </pre>
      </div>

      <div className="detail-card" style={{ display: 'flex', gap: 12 }}>
        <button className="btn btn-primary" onClick={handleRetry} disabled={acting || data.resolved}>
          {acting ? 'Retrying...' : '🔄 Retry Processing'}
        </button>
        <button className="btn btn-secondary" onClick={handleResolve} disabled={acting || data.resolved}>
          {acting ? 'Resolving...' : '✓ Mark Resolved'}
        </button>
      </div>
    </div>
  );
}
