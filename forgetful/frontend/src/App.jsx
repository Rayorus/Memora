// App.jsx — Main application layout

import React, { useRef, useState, useCallback, useEffect, useMemo } from "react";
import Webcam from "react-webcam";
import { useFrameStream } from "./hooks/useFrameStream";
import { useAudioRecorder } from "./hooks/useAudioRecorder";
import {
  createInteraction,
  listPersons,
  getLatestInteraction,
  resetAllDemoData,
} from "./utils/api";
import FaceOverlay from "./components/FaceOverlay";
import RegisterModal from "./components/RegisterModal";
import TranscriptLog from "./components/TranscriptLog";

function toNumberOr(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

const VIDEO_W = toNumberOr(import.meta.env.VITE_CAMERA_WIDTH, 1920);
const VIDEO_H = toNumberOr(import.meta.env.VITE_CAMERA_HEIGHT, 1080);
const VIDEO_FPS = toNumberOr(import.meta.env.VITE_CAMERA_FPS, 30);
const VIDEO_ASPECT = toNumberOr(import.meta.env.VITE_CAMERA_ASPECT_RATIO, 16 / 9);
const MEMORY_POPUP_MS = toNumberOr(import.meta.env.VITE_MEMORY_POPUP_MS, 12000);
const GLASSES_MODE_KEY = "memora_glasses_demo";

export default function App() {
  const webcamRef = useRef(null);
  const [isMonitoring, setIsMonitoring] = useState(false);
  const [showRegister, setShowRegister] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const [transcripts, setTranscripts] = useState([]);
  const [runtimeError, setRuntimeError] = useState("");
  const [saveToast, setSaveToast] = useState("");
  const [requiresPatientRegistration, setRequiresPatientRegistration] = useState(false);
  const [memoryPopup, setMemoryPopup] = useState(null);
  const [activePersonId, setActivePersonId] = useState(null);
  const activePersonIdRef = useRef(null);
  const pendingTranscriptRef = useRef("");
  const sessionTranscriptRef = useRef("");
  const lastSavedTranscriptRef = useRef("");
  const interactionTimerRef = useRef(null);
  const saveToastTimerRef = useRef(null);
  const memoryPopupTimerRef = useRef(null);
  /** Who was visible on the previous face update (null = not bootstrapped yet) */
  const prevVisiblePersonIdsRef = useRef(null);
  /** Everyone who has appeared at least once this page session (for return detection) */
  const everSeenPersonIdsRef = useRef(new Set());
  /** Demo HUD layout for future smart-glasses / Meta Ray-Ban–style devices */
  const [glassesMode, setGlassesMode] = useState(() => {
    try {
      return localStorage.getItem(GLASSES_MODE_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(GLASSES_MODE_KEY, glassesMode ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [glassesMode]);

  const videoConstraints = useMemo(
    () => ({
      width: { ideal: VIDEO_W, max: VIDEO_W },
      height: { ideal: VIDEO_H, max: VIDEO_H },
      aspectRatio: { ideal: VIDEO_ASPECT },
      facingMode: "user",
      frameRate: { ideal: VIDEO_FPS, max: VIDEO_FPS },
    }),
    []
  );

  useEffect(() => {
    const bootstrap = async () => {
      try {
        const data = await listPersons();
        const hasPatient = (data.persons || []).some(
          (p) => String(p.role || "").toLowerCase() === "patient"
        );
        if (!hasPatient) {
          setRequiresPatientRegistration(true);
          setShowRegister(true);
        }
      } catch {
        setRuntimeError("Could not load patient profile. Check backend/Supabase connection.");
      }
    };
    bootstrap();
  }, []);

  const streamActive = !showRegister;
  const { faces, connected, frameDims } = useFrameStream(webcamRef, streamActive);

  /** Deduped visitors in frame — for “update Visitor 1 → real name” in Register modal */
  const visitorUpdateTargets = useMemo(() => {
    if (requiresPatientRegistration) return [];
    const known = faces.filter((f) => f.known && f.person_id);
    const visitors = known.filter((f) => f.role !== "patient");
    const byId = new Map();
    for (const f of visitors) {
      const area = (f.region?.w ?? 0) * (f.region?.h ?? 0);
      const prev = byId.get(f.person_id);
      if (!prev || area > prev.area) {
        byId.set(f.person_id, {
          person_id: f.person_id,
          name: f.name || "Visitor",
          area,
        });
      }
    }
    return [...byId.values()]
      .sort((a, b) => b.area - a.area)
      .map(({ person_id, name }) => ({ person_id, name }));
  }, [faces, requiresPatientRegistration]);

  const overlayW = frameDims?.w || VIDEO_W;
  const overlayH = frameDims?.h || VIDEO_H;

  // ── Track the best person to save interactions with ──
  useEffect(() => {
    const knownFaces = faces.filter((f) => f.known && f.person_id);
    if (knownFaces.length === 0) {
      setActivePersonId(null);
      activePersonIdRef.current = null;
      return;
    }
    const visitors = knownFaces.filter((f) => f.role !== "patient");
    const pool = visitors.length > 0 ? visitors : knownFaces;
    const biggest = pool.reduce((best, cur) => {
      const ba = (best.region?.w ?? 0) * (best.region?.h ?? 0);
      const ca = (cur.region?.w ?? 0) * (cur.region?.h ?? 0);
      return ca > ba ? cur : best;
    });
    setActivePersonId(biggest.person_id);
    activePersonIdRef.current = biggest.person_id;
  }, [faces]);

  // ── Memory reminder: only when someone RETURNS after leaving the camera ──
  // Fetches latest interaction via REST immediately (don't wait for WebSocket to attach it).
  useEffect(() => {
    const known = faces.filter((f) => f.known && f.person_id);
    const currentIds = new Set(known.map((f) => f.person_id));

    const pickPreferredVisitor = (candidates) => {
      if (candidates.length === 0) return null;
      const visitors = candidates.filter((f) => f.role !== "patient");
      return visitors[0] || candidates[0];
    };

    const pickLargest = (arr) =>
      arr.reduce((best, cur) => {
        const ba = (best.region?.w ?? 0) * (best.region?.h ?? 0);
        const ca = (cur.region?.w ?? 0) * (cur.region?.h ?? 0);
        return ca > ba ? cur : best;
      });

    if (currentIds.size === 0) {
      prevVisiblePersonIdsRef.current = new Set();
      return;
    }

    if (prevVisiblePersonIdsRef.current === null) {
      currentIds.forEach((id) => everSeenPersonIdsRef.current.add(id));
      prevVisiblePersonIdsRef.current = new Set(currentIds);
      return;
    }

    const prev = prevVisiblePersonIdsRef.current;
    const newlyInFrame = [...currentIds].filter((id) => !prev.has(id));

    const trueReturnIds = newlyInFrame.filter((id) =>
      everSeenPersonIdsRef.current.has(id)
    );

    for (const id of newlyInFrame) {
      if (!everSeenPersonIdsRef.current.has(id)) {
        everSeenPersonIdsRef.current.add(id);
      }
    }

    if (trueReturnIds.length > 0) {
      const patientOnlyInFrame =
        known.length === 1 && known[0].role === "patient";

      let targetFace = null;
      let usePatientSoloLatest = false;

      if (patientOnlyInFrame) {
        // Only the patient is visible → remind them of last solo conversation (not visitor chats)
        targetFace = known[0];
        usePatientSoloLatest = true;
      } else if (known.length >= 2) {
        const visitors = known.filter((f) => f.role !== "patient");
        if (visitors.length > 0) {
          targetFace = pickLargest(visitors);
        }
      }
      if (!targetFace) {
        const returnedFaces = trueReturnIds
          .map((id) => known.find((f) => f.person_id === id))
          .filter(Boolean);
        targetFace = pickPreferredVisitor(returnedFaces) || returnedFaces[0];
      }

      if (targetFace) {
        const pid = targetFace.person_id;
        const label = targetFace.name || "Person";
        const loadLatest = () => {
          if (usePatientSoloLatest) {
            return getLatestInteraction(pid, { patientSoloOnly: true }).catch(() =>
              getLatestInteraction(pid)
            );
          }
          return getLatestInteraction(pid);
        };
        void loadLatest()
          .then((row) => {
            if (!row?.summary) return;
            setMemoryPopup({
              name: label,
              summary: row.summary,
              timestamp: row.timestamp,
              kind: usePatientSoloLatest ? "return_patient_solo" : "return",
            });
            clearTimeout(memoryPopupTimerRef.current);
            memoryPopupTimerRef.current = setTimeout(() => {
              setMemoryPopup(null);
            }, MEMORY_POPUP_MS);
          })
          .catch(() => {});
      }
    }

    prevVisiblePersonIdsRef.current = new Set(currentIds);
  }, [faces]);

  useEffect(
    () => () => clearTimeout(memoryPopupTimerRef.current),
    []
  );

  // ── Save interaction + show popup ──
  const saveInteraction = useCallback(async (personId, fullText) => {
    const normalized = fullText.trim();
    if (!normalized || !personId) return;
    if (normalized === lastSavedTranscriptRef.current) return;

    const shot = webcamRef.current?.getScreenshot();
    const b64 = shot?.replace(/^data:image\/\w+;base64,/, "") || null;

    const knownFaces = faces.filter((f) => f.known && f.person_id);
    const anyVisitorVisible = knownFaces.some((f) => f.role !== "patient");
    const savingAsPatient = knownFaces.some(
      (f) => f.person_id === personId && f.role === "patient"
    );
    const patientSolo = savingAsPatient && !anyVisitorVisible;

    let summaryText = normalized;
    let ts = new Date().toISOString();

    try {
      const response = await createInteraction(
        personId,
        normalized,
        b64,
        patientSolo ? true : undefined
      );
      const interaction = response?.interaction;
      if (interaction?.summary) summaryText = interaction.summary;
      if (interaction?.timestamp) ts = interaction.timestamp;
    } catch (e) {
      console.error("Interaction save failed:", e);
    }

    setSaveToast("Conversation context saved");
    clearTimeout(saveToastTimerRef.current);
    saveToastTimerRef.current = setTimeout(() => setSaveToast(""), 2200);
    lastSavedTranscriptRef.current = normalized;
  }, [faces]);

  const getPersonIdForSave = useCallback(() => {
    if (activePersonIdRef.current) return activePersonIdRef.current;
    const knownFaces = faces.filter((f) => f.known && f.person_id);
    if (knownFaces.length === 0) return null;
    const visitors = knownFaces.filter((f) => f.role !== "patient");
    const pool = visitors.length > 0 ? visitors : knownFaces;
    const largest = pool.reduce((best, cur) => {
      const ba = (best.region?.w ?? 0) * (best.region?.h ?? 0);
      const ca = (cur.region?.w ?? 0) * (cur.region?.h ?? 0);
      return ca > ba ? cur : best;
    });
    return largest.person_id;
  }, [faces]);

  // ── Audio transcript handler ──
  const handleTranscript = useCallback(
    (text) => {
      setTranscripts((prev) => [...prev, { text, time: Date.now() }]);
      pendingTranscriptRef.current += " " + text;
      sessionTranscriptRef.current += " " + text;

      clearTimeout(interactionTimerRef.current);
      interactionTimerRef.current = setTimeout(() => {
        const personId = getPersonIdForSave();
        if (personId) {
          saveInteraction(personId, sessionTranscriptRef.current.trim());
        }
        pendingTranscriptRef.current = "";
      }, 8000);
    },
    [getPersonIdForSave, saveInteraction]
  );

  const { recording, start: startMic, stop: stopMic } = useAudioRecorder(handleTranscript, setRuntimeError);

  const handleStartOver = useCallback(async () => {
    const ok = window.confirm(
      "Delete EVERY person and ALL saved conversations in Supabase?\n\nThis cannot be undone. You will register the patient again from scratch."
    );
    if (!ok) return;
    try {
      await resetAllDemoData();
    } catch (e) {
      setRuntimeError(
        e.message ||
          "Reset failed. Enable ALLOW_FULL_DATABASE_RESET=true in backend .env.local and restart the API."
      );
      return;
    }
    clearTimeout(interactionTimerRef.current);
    clearTimeout(memoryPopupTimerRef.current);
    clearTimeout(saveToastTimerRef.current);
    stopMic();
    setIsMonitoring(false);
    setTranscripts([]);
    setMemoryPopup(null);
    setRequiresPatientRegistration(true);
    setShowRegister(true);
    setActivePersonId(null);
    activePersonIdRef.current = null;
    prevVisiblePersonIdsRef.current = null;
    everSeenPersonIdsRef.current = new Set();
    pendingTranscriptRef.current = "";
    sessionTranscriptRef.current = "";
    lastSavedTranscriptRef.current = "";
    setRuntimeError("");
    setSaveToast("Database cleared — register the patient");
    saveToastTimerRef.current = setTimeout(() => setSaveToast(""), 4000);
  }, [stopMic]);

  // ── Toggle monitoring ──
  const toggleMonitor = () => {
    if (requiresPatientRegistration) {
      setShowRegister(true);
      return;
    }
    if (isMonitoring) {
      clearTimeout(interactionTimerRef.current);
      const transcript = sessionTranscriptRef.current.trim();
      if (transcript) {
        const personId = getPersonIdForSave();
        if (personId) {
          saveInteraction(personId, transcript);
        } else {
          setSaveToast("No recognized person to save interaction with");
          clearTimeout(saveToastTimerRef.current);
          saveToastTimerRef.current = setTimeout(() => setSaveToast(""), 3000);
        }
      } else {
        setSaveToast("No speech detected in this session");
        clearTimeout(saveToastTimerRef.current);
        saveToastTimerRef.current = setTimeout(() => setSaveToast(""), 2500);
      }
      pendingTranscriptRef.current = "";
      stopMic();
      setIsMonitoring(false);
      setRuntimeError("");
    } else {
      setRuntimeError("");
      setTranscripts([]);
      pendingTranscriptRef.current = "";
      sessionTranscriptRef.current = "";
      lastSavedTranscriptRef.current = "";
      setIsMonitoring(true);
      startMic();
    }
  };

  return (
    <div className={`app-shell${glassesMode ? " glasses-mode" : ""}`}>
      {glassesMode && (
        <div className="glasses-hud-layer" aria-hidden="true">
          <div className="glasses-vignette" />
          <div className="glasses-lens-rim glasses-lens-rim--left" />
          <div className="glasses-lens-rim glasses-lens-rim--right" />
          <span className="glasses-hud-badge">Smart glasses · demo HUD</span>
          <span className="glasses-hud-corners glasses-hud-corners--tl" />
          <span className="glasses-hud-corners glasses-hud-corners--tr" />
          <span className="glasses-hud-corners glasses-hud-corners--bl" />
          <span className="glasses-hud-corners glasses-hud-corners--br" />
          <div className="glasses-scanlines" />
        </div>
      )}
      {!showRegister ? (
        <>
          <Webcam
            ref={webcamRef}
            screenshotFormat="image/jpeg"
            screenshotQuality={1}
            forceScreenshotSourceSize
            minScreenshotWidth={VIDEO_W}
            minScreenshotHeight={VIDEO_H}
            width={VIDEO_W}
            height={VIDEO_H}
            className="fullscreen-webcam"
            videoConstraints={videoConstraints}
            onUserMedia={() => {
              setCameraReady(true);
              setCameraError("");
            }}
            onUserMediaError={(e) => {
              setCameraReady(false);
              setCameraError(e?.message || "Camera unavailable");
            }}
          />
          <FaceOverlay
            faces={faces}
            videoWidth={overlayW}
            videoHeight={overlayH}
            glassesMode={glassesMode}
          />
        </>
      ) : (
        <div className="camera-paused-bg" />
      )}

      {!cameraReady && !showRegister && (
        <div className="camera-fallback fade-in">
          <p className="camera-fallback-title">Camera not visible</p>
          <p className="camera-fallback-body">
            {cameraError || "Allow camera permission and close other apps using the webcam."}
          </p>
        </div>
      )}

      <div className="top-overlay fade-in">
        <div className="top-overlay-chips">
          <div className="live-chip">
            <span className={`dot ${connected ? "dot-on" : ""}`} />
            {connected ? "Live Tracking" : "Connecting"}
          </div>
          <div className="live-chip">
            <span className={`dot ${recording ? "dot-on" : ""}`} />
            {recording ? "Listening" : "Mic Off"}
          </div>
          <div className="live-chip">{faces.length} faces</div>
        </div>
        <div className="top-overlay-actions">
          <button
            type="button"
            className={`btn-glasses${glassesMode ? " btn-glasses--on" : ""}`}
            title="Demo: heads-up display layout like smart glasses (e.g. Meta Ray-Ban) — for future device integration"
            onClick={() => setGlassesMode((v) => !v)}
          >
            Specs
          </button>
          <button
            type="button"
            className="btn-restart"
            title="Remove all saved faces & patient, clear conversations — start fresh"
            onClick={handleStartOver}
          >
            Restart
          </button>
        </div>
      </div>

      {memoryPopup && (
        <div className="memory-popup fade-in">
          {memoryPopup.kind === "return" && (
            <p className="memory-subtitle" style={{ margin: "0 0 0.35rem", fontSize: "0.72rem", color: "var(--muted)", letterSpacing: "0.04em", textTransform: "uppercase" }}>
              Last time you spoke together
            </p>
          )}
          {memoryPopup.kind === "return_patient_solo" && (
            <p className="memory-subtitle" style={{ margin: "0 0 0.35rem", fontSize: "0.72rem", color: "var(--muted)", letterSpacing: "0.04em", textTransform: "uppercase" }}>
              Last time on your own
            </p>
          )}
          <p className="memory-title">{memoryPopup.name}</p>
          <p className="memory-summary">{memoryPopup.summary}</p>
          <p className="memory-meta">{new Date(memoryPopup.timestamp).toLocaleString()}</p>
        </div>
      )}

      <div className="bottom-controls fade-in">
        <button className={isMonitoring ? "btn-danger" : "btn-primary"} onClick={toggleMonitor}>
          {isMonitoring ? "Stop" : "Start"}
        </button>
        <button className="btn-secondary" onClick={() => setShowRegister(true)}>
          Register Face
        </button>
      </div>

      <div className="transcript-panel fade-in">
        <TranscriptLog entries={transcripts} />
      </div>

      {runtimeError && <div className="error-toast fade-in">{runtimeError}</div>}
      {saveToast && <div className="ok-toast fade-in">{saveToast}</div>}

      {!isMonitoring && (
        <div className="center-hint">
          {requiresPatientRegistration
            ? "Register patient face to begin"
            : "Face detection is active. Press Start when you want to record conversation"}
        </div>
      )}

      {showRegister && (
        <RegisterModal
          onClose={() => setShowRegister(false)}
          requiredRole={requiresPatientRegistration ? "patient" : null}
          updateTargets={visitorUpdateTargets}
          onRegistered={(p) => {
            if (p.role === "patient") {
              setRequiresPatientRegistration(false);
            }
            setRuntimeError("");
            console.log("Registered:", p);
          }}
        />
      )}
    </div>
  );
}
