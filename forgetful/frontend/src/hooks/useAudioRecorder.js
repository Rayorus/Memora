// hooks/useAudioRecorder.js
// Captures microphone audio in chunks and sends to the backend for transcription.

import { useRef, useState, useCallback } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const CHUNK_MS = 3000;
const HARD_MIN_AUDIO_BYTES = 220;

function pickAudioMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg"];
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return "audio/webm";
  }
  return candidates.find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

function extensionFromMime(mimeType) {
  if (!mimeType) return "webm";
  if (mimeType.includes("webm")) return "webm";
  if (mimeType.includes("ogg")) return "ogg";
  if (mimeType.includes("mp4")) return "mp4";
  if (mimeType.includes("wav")) return "wav";
  return "webm";
}

export function useAudioRecorder(onTranscript, onError) {
  const speechRecognitionRef = useRef(null);
  const usingBrowserSttRef = useRef(false);
  const mediaRecorderRef = useRef(null);
  const mediaExtensionRef = useRef("webm");
  const chunkQueueRef = useRef([]);
  const processingRef = useRef(false);
  const stopRequestedRef = useRef(false);
  const shortChunkRef = useRef(0);
  const [recording, setRecording] = useState(false);

  const sendChunk = useCallback(
    async (blob) => {
      if (!blob || blob.size < HARD_MIN_AUDIO_BYTES) return;
      const formData = new FormData();
      formData.append("file", blob, `audio.${mediaExtensionRef.current}`);
      try {
        const res = await fetch(`${API_BASE}/api/recognition/transcribe`, {
          method: "POST",
          body: formData,
        });
        if (res.ok) {
          const { text } = await res.json();
          if (text?.trim()) onTranscript(text.trim());
        } else {
          const err = await res.json().catch(() => ({}));
          const message = err.detail || `Transcription failed (HTTP ${res.status})`;
          const lowerMessage = String(message).toLowerCase();
          if (lowerMessage.includes("could not process file")) return;
          if (lowerMessage.includes("audio file is too short")) {
            shortChunkRef.current += 1;
            if (shortChunkRef.current >= 3) {
              onError?.("Audio is too short repeatedly. Speak a bit longer/clearer and keep mic close.");
              shortChunkRef.current = 0;
            }
            return;
          }
          shortChunkRef.current = 0;
          onError?.(message);
        }
      } catch (error) {
        onError?.(error.message || "Unable to reach transcription endpoint");
      }
    },
    [onTranscript, onError]
  );

  const processQueue = useCallback(async () => {
    if (processingRef.current) return;
    processingRef.current = true;
    try {
      while (chunkQueueRef.current.length > 0) {
        const blob = chunkQueueRef.current.shift();
        await sendChunk(blob);
      }
    } finally {
      processingRef.current = false;
    }
  }, [sendChunk]);

  const start = useCallback(async () => {
    try {
      stopRequestedRef.current = false;

      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SpeechRecognition) {
        const sr = new SpeechRecognition();
        sr.continuous = true;
        sr.interimResults = false;
        sr.lang = "en-US";

        sr.onresult = (event) => {
          const i = event.results.length - 1;
          const text = event.results[i]?.[0]?.transcript?.trim();
          if (text) onTranscript(text);
        };

        sr.onerror = (event) => {
          const err = event?.error || "unknown";
          if (err !== "no-speech") {
            onError?.(`Speech recognition error: ${err}`);
          }
        };

        sr.onend = () => {
          if (!stopRequestedRef.current) {
            try {
              sr.start();
            } catch {
              // no-op
            }
          }
        };

        speechRecognitionRef.current = sr;
        usingBrowserSttRef.current = true;
        sr.start();
        setRecording(true);
        return;
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      const mimeType = pickAudioMimeType();
      const mr = mimeType
        ? new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 128000 })
        : new MediaRecorder(stream, { audioBitsPerSecond: 128000 });
      mediaRecorderRef.current = mr;
      mediaExtensionRef.current = extensionFromMime(mr.mimeType || mimeType);
      chunkQueueRef.current = [];
      shortChunkRef.current = 0;

      mr.ondataavailable = (e) => {
        if (!e.data || e.data.size < HARD_MIN_AUDIO_BYTES) return;
        chunkQueueRef.current.push(e.data);
        processQueue();
      };

      mr.onstop = () => {
        if (!stopRequestedRef.current) {
          onError?.("Microphone recorder stopped unexpectedly. Press Start again.");
          setRecording(false);
        }
      };

      mr.onerror = () => {
        onError?.("Microphone recorder error. Try Start again.");
      };

      // Timeslice mode is generally more reliable across browsers for steady chunk emission.
      mr.start(CHUNK_MS);
      setRecording(true);
    } catch (err) {
      onError?.(`Microphone access denied: ${err.message}`);
    }
  }, [processQueue, onError]);

  const stop = useCallback(() => {
    stopRequestedRef.current = true;

    if (usingBrowserSttRef.current && speechRecognitionRef.current) {
      try {
        speechRecognitionRef.current.onend = null;
        speechRecognitionRef.current.stop();
      } catch {
        // no-op
      }
      speechRecognitionRef.current = null;
      usingBrowserSttRef.current = false;
    }

    mediaRecorderRef.current?.stop?.();
    mediaRecorderRef.current?.stream?.getTracks().forEach((t) => t.stop());
    setRecording(false);
  }, []);

  return { recording, start, stop };
}
