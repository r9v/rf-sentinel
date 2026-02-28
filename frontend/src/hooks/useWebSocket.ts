import { useState, useEffect, useRef, useCallback } from 'react';

export interface LogEntry {
  job_id: string;
  message: string;
  timestamp: number;
}

export function useWebSocket(url: string) {
  const [connected, setConnected] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [lastMessage, setLastMessage] = useState<any>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number>();
  const disposed = useRef(false);

  const connect = useCallback(() => {
    if (disposed.current) return;

    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    const ws = new WebSocket(url);

    ws.onopen = () => {
      if (disposed.current) { ws.close(); return; }
      console.log('[WS] connected');
      setConnected(true);
    };

    ws.onmessage = (e) => {
      if (typeof e.data !== 'string') return;
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'log') {
          setLogs(prev => [...prev.slice(-200), {
            job_id: data.job_id,
            message: data.message,
            timestamp: Date.now(),
          }]);
        } else if (data.type === 'spectrum') {
          setLastMessage(data);
        }
      } catch { /* ignore non-JSON */ }
    };

    ws.onclose = () => {
      console.log('[WS] disconnected');
      setConnected(false);
      wsRef.current = null;
      if (!disposed.current) {
        reconnectTimer.current = window.setTimeout(connect, 3000);
      }
    };

    ws.onerror = () => ws.close();

    wsRef.current = ws;
  }, [url]);

  useEffect(() => {
    disposed.current = false;
    connect();
    return () => {
      disposed.current = true;
      clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
      setConnected(false);
    };
  }, [connect]);

  const clearLogs = useCallback(() => setLogs([]), []);

  return { connected, logs, clearLogs, lastMessage };
}
