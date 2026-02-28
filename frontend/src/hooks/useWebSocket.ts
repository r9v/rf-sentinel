import { useState, useEffect, useRef, useCallback } from 'react';

export interface LogEntry {
  job_id: string;
  message: string;
  timestamp: number;
}

interface UseWebSocketOptions {
  onAudioData?: (data: ArrayBuffer) => void;
}

export function useWebSocket(url: string, options?: UseWebSocketOptions) {
  const [connected, setConnected] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [lastMessage, setLastMessage] = useState<any>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number>();
  const disposed = useRef(false);
  const onAudioRef = useRef(options?.onAudioData);
  onAudioRef.current = options?.onAudioData;

  const connect = useCallback(() => {
    if (disposed.current) return;

    // Close any existing connection first
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    const ws = new WebSocket(url);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      if (disposed.current) { ws.close(); return; }
      console.log('[WS] connected');
      setConnected(true);
    };

    ws.onmessage = (e) => {
      // Binary frame = audio PCM data
      if (e.data instanceof ArrayBuffer) {
        if (onAudioRef.current) {
          onAudioRef.current(e.data);
        }
        return;
      }

      // Text frame = JSON (spectrum, log, pong)
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
