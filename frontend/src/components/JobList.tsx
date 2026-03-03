import { useState } from 'react';
import { JobInfo } from '../api';

interface Props {
  jobs: JobInfo[];
  onSelectJob: (job: JobInfo) => void;
  selectedJobId: string | null;
  onCancel?: (jobId: string) => void;
  onDelete?: (jobId: string) => void;
}

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-yellow-500/20 text-yellow-300',
  running: 'bg-blue-500/20 text-blue-300',
  complete: 'bg-green-500/20 text-green-300',
  error: 'bg-red-500/20 text-red-300',
  cancelled: 'bg-gray-500/20 text-gray-400',
};

const TYPE_ICON: Record<string, string> = {
  scan: '📊',
};

const jobCardBtn = 'w-full text-left px-3 py-2 rounded-lg border transition-all';
const jobCardSelected = 'border-cyan-500/40 bg-cyan-500/5';
const jobCardDefault = 'border-gray-700/50 hover:border-gray-600 bg-gray-800/30';
const actionBtn = 'px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors';
const confirmOverlay = 'absolute inset-0 rounded-lg bg-gray-900/95 flex items-center justify-center gap-2 z-10';
const confirmBtn = 'px-2 py-1 rounded text-xs font-medium transition-colors';

function JobCard({ job, selected, onSelect, onCancel, onDelete }: {
  job: JobInfo;
  selected: boolean;
  onSelect: (job: JobInfo) => void;
  onCancel?: (jobId: string) => void;
  onDelete?: (jobId: string) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const canCancel = (job.status === 'pending' || job.status === 'running') && onCancel;
  const canDelete = (job.status === 'complete' || job.status === 'error' || job.status === 'cancelled') && onDelete;

  return (
    <button
      onClick={() => onSelect(job)}
      className={`${jobCardBtn} ${selected ? jobCardSelected : jobCardDefault} relative`}
    >
      {confirmDelete && (
        <div className={confirmOverlay} onClick={e => e.stopPropagation()}>
          <span className="text-xs text-gray-400">Delete scan?</span>
          <span onClick={() => { onDelete!(job.id); setConfirmDelete(false); }}
            className={`${confirmBtn} bg-red-500/20 text-red-300 hover:bg-red-500/30`}>
            Yes
          </span>
          <span onClick={() => setConfirmDelete(false)}
            className={`${confirmBtn} bg-gray-700/50 text-gray-400 hover:bg-gray-700`}>
            No
          </span>
        </div>
      )}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm">{TYPE_ICON[job.type] || '📦'}</span>
          <span className="text-sm text-gray-200 capitalize">{job.type}</span>
          {job.params.start_mhz && job.params.stop_mhz && (
            <span className="text-xs text-gray-500 font-mono">
              {job.params.start_mhz}–{job.params.stop_mhz} MHz
            </span>
          )}
        </div>
        <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_STYLE[job.status]}`}>
          {job.status}
        </span>
      </div>
      <div className="flex items-center justify-between mt-1">
        <span className="text-xs text-gray-600 font-mono">
          {job.created_at ? new Date(job.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : job.id.slice(0, 8)}
        </span>
        <div className="flex items-center gap-1.5">
          {job.duration_s !== null && (
            <span className="text-xs text-gray-600">{job.duration_s}s</span>
          )}
          {canCancel && (
            <span onClick={e => { e.stopPropagation(); onCancel!(job.id); }}
              className={`${actionBtn} text-yellow-400 hover:bg-yellow-500/20`}>
              ■ Stop
            </span>
          )}
          {canDelete && (
            <span onClick={e => { e.stopPropagation(); setConfirmDelete(true); }}
              className={`${actionBtn} text-red-400 hover:bg-red-500/20 text-sm`}>
              🗑
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

export default function JobList({ jobs, onSelectJob, selectedJobId, onCancel, onDelete }: Props) {
  if (jobs.length === 0) {
    return (
      <div className="text-center py-8 text-gray-600 text-sm italic">
        No jobs yet. Run a scan to get started.
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {jobs.map(job => (
        <JobCard
          key={job.id}
          job={job}
          selected={selectedJobId === job.id}
          onSelect={onSelectJob}
          onCancel={onCancel}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}
