// hooks/useFrameStream.js
// WebSocket stream to backend — sends webcam frames, receives face data + frame dims.

import { useEffect, useRef, useState, useCallback } from "react";

const WS_URL = import.meta.env.VITE_WEBSOCKET_URL || "ws://localhost:8000/ws";
const FRAME_INTERVAL_MS = Number(import.meta.env.VITE_FRAME_INTERVAL_MS) || 100;

export function useFrameStream(webcamRef, isActive) {
  const wsRef = useRef(null);
  const intervalRef = useRef(null);
  const [faces, setFaces] = useState([]);
  const [connected, setConnected] = useState(false);
  const [frameDims, setFrameDims] = useState(null);

  const sendFrame = useCallback(() => {
    if (!webcamRef.current || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    const frame = webcamRef.current.getScreenshot();
    if (!frame) return;
    const b64 = frame.replace(/^data:image\/\w+;base64,/, "");
    wsRef.current.send(JSON.stringify({ frame: b64 }));
  }, [webcamRef]);

  useEffect(() => {
    if (!isActive) {
      wsRef.current?.close();
      clearInterval(intervalRef.current);
      setConnected(false);
      setFaces([]);
      return;
    }

    const ws = new WebSocket(`${WS_URL}/frame`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      intervalRef.current = setInterval(sendFrame, FRAME_INTERVAL_MS);
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        setFaces(data.faces || []);
        if (data.frame_w && data.frame_h) {
          setFrameDims({ w: data.frame_w, h: data.frame_h });
        }
      } catch (_) {}
    };

    ws.onclose = () => {
      setConnected(false);
      clearInterval(intervalRef.current);
    };

    ws.onerror = () => ws.close();

    return () => {
      ws.close();
      clearInterval(intervalRef.current);
    };
  }, [isActive, sendFrame]);

  return { faces, connected, frameDims };
}
