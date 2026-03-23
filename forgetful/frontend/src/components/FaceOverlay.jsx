// components/FaceOverlay.jsx
// Renders face bounding boxes + labels over the webcam feed.

import React, { useMemo } from "react";

function regionArea(face) {
  const r = face.region || {};
  return (r.w ?? 0) * (r.h ?? 0);
}

function iouRegions(a, b) {
  const ax1 = a.x ?? 0,
    ay1 = a.y ?? 0,
    ax2 = ax1 + (a.w ?? 0),
    ay2 = ay1 + (a.h ?? 0);
  const bx1 = b.x ?? 0,
    by1 = b.y ?? 0,
    bx2 = bx1 + (b.w ?? 0),
    by2 = by1 + (b.h ?? 0);
  const ix1 = Math.max(ax1, bx1),
    iy1 = Math.max(ay1, by1),
    ix2 = Math.min(ax2, bx2),
    iy2 = Math.min(ay2, by2);
  const inter = Math.max(0, ix2 - ix1) * Math.max(0, iy2 - iy1);
  if (inter <= 0) return 0;
  const union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter;
  return union > 0 ? inter / union : 0;
}

/** Client-side safety net: one box per person_id, drop overlapping unknowns */
function dedupeFaces(faces) {
  if (!faces?.length) return faces;
  const known = faces.filter((f) => f.known && f.person_id);
  const unknown = faces.filter((f) => !f.known || !f.person_id);
  const byPid = new Map();
  for (const f of known) {
    const prev = byPid.get(f.person_id);
    if (!prev || regionArea(f) > regionArea(prev)) byPid.set(f.person_id, f);
  }
  const mergedKnown = [...byPid.values()];
  unknown.sort((a, b) => regionArea(b) - regionArea(a));
  const keptU = [];
  for (const f of unknown) {
    const r = f.region || {};
    if (keptU.some((u) => iouRegions(r, u.region || {}) > 0.42)) continue;
    keptU.push(f);
  }
  return [...mergedKnown, ...keptU];
}

export default function FaceOverlay({ faces, videoWidth, videoHeight, glassesMode = false }) {
  const displayFaces = useMemo(() => dedupeFaces(faces || []), [faces]);

  if (!displayFaces.length) return null;

  const fontHud = glassesMode
    ? "ui-monospace, 'Cascadia Code', 'SF Mono', Consolas, monospace"
    : "DM Sans, sans-serif";

  return (
    <svg
      className="face-overlay-svg"
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        zIndex: 10,
      }}
      viewBox={`0 0 ${videoWidth} ${videoHeight}`}
      preserveAspectRatio="xMidYMid slice"
    >
      {displayFaces.map((face, i) => {
        const r = face.region || {};
        const rawX = r.x ?? 0;
        const y = r.y ?? 0;
        const w = r.w ?? 80;
        const h = r.h ?? 80;

        const x = Math.max(0, videoWidth - rawX - w);

        const isPatient =
          String(face.role || "")
            .trim()
            .toLowerCase() === "patient";
        const color = glassesMode
          ? isPatient
            ? "#39ffb4"
            : face.known
              ? "#00e5ff"
              : "#ffe566"
          : isPatient
            ? "#22c55e"
            : face.known
              ? "#7dd3fc"
              : "#fbbf24";
        const strokeW = glassesMode ? (isPatient ? 2.5 : 1.8) : isPatient ? 3 : 1.5;
        const label = face.name || (face.known ? "Known" : "Analyzing...");
        const labelWidth = Math.max(label.length * (glassesMode ? 6.8 : 7.5) + 16, 80);
        const dash = glassesMode ? "6 4" : undefined;

        return (
          <g key={`${face.person_id || "u"}-${face.track_id ?? i}`}>
            <rect
              x={x}
              y={y}
              width={w}
              height={h}
              fill="none"
              stroke={color}
              strokeWidth={strokeW}
              strokeDasharray={dash}
              rx={glassesMode ? 2 : 4}
              opacity={glassesMode ? 0.92 : isPatient ? 0.95 : 0.72}
            />

            <rect
              x={x}
              y={y - 26}
              width={labelWidth}
              height={22}
              fill={glassesMode ? "#001018d0" : "#020814c9"}
              stroke={color + (glassesMode ? "aa" : "66")}
              strokeWidth="0.9"
              rx={glassesMode ? 2 : 4}
            />
            <text
              x={x + 8}
              y={y - 10}
              fill={color}
              fontSize={glassesMode ? 10 : 11}
              fontFamily={fontHud}
              fontWeight="500"
              letterSpacing={glassesMode ? "0.06em" : "0"}
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
