/**
 * PipelineStepper — animated real-time processing pipeline visualization.
 * Shows each step with live status: completed (green glow), active (pulsing), pending (dim), error (red).
 */

interface StepInfo {
  key: string;
  label: string;
}

const STEPS: StepInfo[] = [
  { key: 'classification', label: 'Classification' },
  { key: 'extraction', label: 'Extraction' },
  { key: 'client_history', label: 'Client History' },
  { key: 'evaluation', label: 'Evaluation' },
  { key: 'complete', label: 'Complete' },
];

interface Props {
  currentStep: string | null;
  status: string;
  error?: { step: string; message: string } | null;
}

export default function PipelineStepper({ currentStep, status, error }: Props) {
  const getStepState = (stepKey: string): 'done' | 'active' | 'error' | 'pending' => {
    if (status === 'Assigned' || status === 'Complete' || status === 'Declined') {
      return 'done'; // All steps done
    }

    if (error && error.step === stepKey) return 'error';

    const currentIdx = STEPS.findIndex(s => s.key === currentStep);
    const stepIdx = STEPS.findIndex(s => s.key === stepKey);

    if (stepIdx < currentIdx) return 'done';
    if (stepIdx === currentIdx) return 'active';
    return 'pending';
  };

  return (
    <div className="pipeline-stepper">
      {STEPS.map((step, i) => {
        const state = getStepState(step.key);
        return (
          <div key={step.key} className={`pipeline-step step-${state}`}>
            <div className="step-connector">
              {i > 0 && <div className={`connector-line line-${state}`} />}
            </div>
            <div className="step-node">
              <div className={`step-circle circle-${state}`}>
                {state === 'done' && <svg width="12" height="12" viewBox="0 0 12 12"><path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round"/></svg>}
                {state === 'active' && <div className="step-pulse" />}
                {state === 'error' && <span className="step-x">!</span>}
              </div>
              <div className="step-label">
                <span className="step-name">{step.label}</span>
                {state === 'active' && <span className="step-status-text">In progress...</span>}
                {state === 'error' && error && <span className="step-error-text">{error.message}</span>}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
