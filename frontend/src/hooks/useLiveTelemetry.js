import { useEffect, useState } from "react";
import { getDashboard } from "../services/api";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
  || (import.meta.env.DEV ? "http://127.0.0.1:8000/api/v1" : `${window.location.origin}/api/v1`);
const socketUrl = import.meta.env.VITE_WS_URL
  || `${apiBaseUrl.replace(/^http/, "ws").replace(/\/api\/v1\/?$/, "")}/ws/grid-telemetry`;

export default function useLiveTelemetry(publicDemoMode, apiToken, onFallback) {
  const [telemetry, setTelemetry] = useState(null);
  const [connection, setConnection] = useState("connecting");

  useEffect(() => {
    if (publicDemoMode === null) return undefined;
    if (!publicDemoMode && !apiToken) {
      setTelemetry(null);
      setConnection("offline");
      return undefined;
    }

    let active = true;
    let socket;
    let retryTimer;
    let pollTimer;
    let polling = false;

    const poll = async () => {
      try {
        const dashboard = await getDashboard();
        if (active) onFallback(dashboard);
      } catch {
        if (active) setConnection("offline");
      }
    };
    const connect = () => {
      if (!active) return;
      try {
        socket = new WebSocket(socketUrl);
        socket.onopen = () => {
          if (!active) return;
          if (!publicDemoMode) {
            socket.send(JSON.stringify({ type: "auth", token: apiToken }));
          }
          setConnection("live");
          polling = false;
          window.clearInterval(pollTimer);
        };
        socket.onmessage = (event) => {
          if (!active) return;
          try {
            setTelemetry(JSON.parse(event.data));
          } catch {
            setConnection("polling");
          }
        };
        socket.onerror = () => socket.close();
        socket.onclose = () => {
          if (!active) return;
          setTelemetry(null);
          setConnection("polling");
          if (!polling) {
            polling = true;
            poll();
            pollTimer = window.setInterval(poll, 10000);
          }
          retryTimer = window.setTimeout(connect, 5000);
        };
      } catch {
        setConnection("polling");
        poll();
        pollTimer = window.setInterval(poll, 10000);
      }
    };
    connect();
    return () => {
      active = false;
      window.clearTimeout(retryTimer);
      window.clearInterval(pollTimer);
      socket?.close();
    };
  }, [apiToken, onFallback, publicDemoMode]);

  return { telemetry, connection };
}
