import { useState, useEffect, useRef, useCallback } from 'react';

export interface LogEntry {
  job_id: string;
  message: string;
  timestamp: number;
}

export function useWebSocket(url: string) {
  const [connected, setConnected] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number>();

  const connect = useCallback(() => {
    const ws = new WebSocket(url);

    ws.onopen = () => {
      setConnected(true);
      console.log('WebSocket connected');
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'log') {
          setLogs(prev => [...prev.slice(-200), {
            job_id: data.job_id,
            message: data.message,
            timestamp: Date.now(),
          }]);
        }
      } catch { /* ignore non-JSON */ }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      reconnectTimer.current = window.setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();

    wsRef.current = ws;
  }, [url]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const clearLogs = useCallback(() => setLogs([]), []);

  return { connected, logs, clearLogs };
}
