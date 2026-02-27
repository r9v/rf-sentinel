const API = '';

export interface JobResponse {
  job_id: string;
  status: string;
}

export interface JobInfo {
  id: string;
  type: string;
  status: 'pending' | 'running' | 'complete' | 'error';
  params: Record<string, any>;
  result_url: string | null;
  error: string | null;
  created_at: string;
  duration_s: number | null;
}

export async function getStatus(): Promise<{ status: string; demo_mode: boolean }> {
  const res = await fetch(`${API}/api/status`);
  return res.json();
}

export async function startScan(params: {
  start_mhz: number;
  stop_mhz: number;
  duration: number;
  gain: number;
}): Promise<JobResponse> {
  const res = await fetch(`${API}/api/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function startWaterfall(params: {
  start_mhz: number;
  stop_mhz: number;
  duration: number;
  gain: number;
}): Promise<JobResponse> {
  const res = await fetch(`${API}/api/waterfall`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function getJobs(): Promise<JobInfo[]> {
  const res = await fetch(`${API}/api/jobs`);
  return res.json();
}

export async function getJob(id: string): Promise<JobInfo> {
  const res = await fetch(`${API}/api/jobs/${id}`);
  return res.json();
}

// ── Live mode ──────────────────────────────────────────

export async function startLive(params: {
  start_mhz: number;
  stop_mhz: number;
  gain: number;
}): Promise<{ status: string; start_mhz: number; stop_mhz: number }> {
  const res = await fetch(`${API}/api/live/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function stopLive(): Promise<{ status: string }> {
  const res = await fetch(`${API}/api/live/stop`, { method: 'POST' });
  return res.json();
}

export async function getLiveStatus(): Promise<{ active: boolean }> {
  const res = await fetch(`${API}/api/live/status`);
  return res.json();
}
