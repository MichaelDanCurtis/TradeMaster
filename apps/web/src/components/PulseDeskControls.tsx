"use client";
import { useEffect, useRef, useState } from "react";
import {
  DEFAULT_DESK,
  DESK_KEY,
  readDesk,
  type DeskLayout,
  type DetailTab,
  type Dock,
} from "@/lib/pulse-workbench";
export function usePulseDesk() {
  const [layout, setLayout] = useState<DeskLayout>({ ...DEFAULT_DESK });
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    try {
      setLayout(readDesk(localStorage.getItem(DESK_KEY)));
    } catch {}
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (!loaded) return;
    const timer = setTimeout(() => {
      try {
        localStorage.setItem(DESK_KEY, JSON.stringify(layout));
      } catch {}
    }, 150);
    return () => clearTimeout(timer);
  }, [layout, loaded]);
  return { layout, setLayout };
}
const TABS: [DetailTab, string][] = [
  ["catalyst", "Catalyst Desk"],
  ["charts", "Charts"],
  ["company", "Company & Figures"],
];
export function DeskControls({
  layout,
  onChange,
  onDrag,
}: {
  layout: DeskLayout;
  onChange: (value: DeskLayout) => void;
  onDrag: (dragging: boolean) => void;
}) {
  return (
    <>
      <div className="pulse-desk-controls">
        <button
          type="button"
          draggable
          className="pulse-drag-handle"
          aria-label="Drag detail panel to a docking area"
          title="Drag to move the panel, or use the position menu"
          onDragStart={(event) => {
            event.dataTransfer.setData(
              "application/x-trademaster-panel",
              "pulse-desk",
            );
            event.dataTransfer.effectAllowed = "move";
            onDrag(true);
          }}
          onDragEnd={() => onDrag(false)}
        >
          ⠿ <span>News & research</span>
        </button>
        <label>
          Position{" "}
          <select
            aria-label="Detail panel position"
            value={layout.dock}
            onChange={(event) =>
              onChange({ ...layout, dock: event.target.value as Dock })
            }
          >
            <option value="right">Right</option>
            <option value="left">Left</option>
            <option value="bottom">Below</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() => onChange({ ...DEFAULT_DESK })}
          title="Restore default position, width and tab"
        >
          Reset
        </button>
      </div>
      <div
        className="pulse-detail-tabs"
        role="tablist"
        aria-label="Selected stock views"
      >
        {TABS.map(([id, label], index) => (
          <button
            key={id}
            id={`pulse-tab-${id}`}
            type="button"
            role="tab"
            aria-controls="pulse-detail-panel"
            aria-selected={layout.tab === id}
            tabIndex={layout.tab === id ? 0 : -1}
            onClick={() => onChange({ ...layout, tab: id })}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowRight"
                  ? (index + 1) % 3
                  : event.key === "ArrowLeft"
                    ? (index + 2) % 3
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? 2
                        : null;
              if (next != null) {
                event.preventDefault();
                onChange({ ...layout, tab: TABS[next][0] });
                document.getElementById(`pulse-tab-${TABS[next][0]}`)?.focus();
              }
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </>
  );
}
export function DeskResize({
  layout,
  onChange,
}: {
  layout: DeskLayout;
  onChange: (value: DeskLayout) => void;
}) {
  const drag = useRef<{ x: number; width: number } | null>(null);

  return (
    <div
      className="pulse-resize"
      role="separator"
      tabIndex={0}
      aria-label="Detail panel width"
      aria-orientation="vertical"
      aria-valuemin={320}
      aria-valuemax={900}
      aria-valuenow={layout.width}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        drag.current = {
          x: event.clientX,
          width:
            event.currentTarget.parentElement?.getBoundingClientRect().width ??
            layout.width,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
        event.preventDefault();
      }}
      onPointerMove={(event) => {
        if (!drag.current) return;
        const delta =
          (event.clientX - drag.current.x) * (layout.dock !== "right" ? 1 : -1);
        onChange({
          ...layout,
          width: Math.max(
            320,
            Math.min(900, Math.round(drag.current.width + delta)),
          ),
        });
      }}
      onPointerUp={(event) => {
        drag.current = null;
        event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onPointerCancel={() => {
        drag.current = null;
      }}
      onLostPointerCapture={() => {
        drag.current = null;
      }}
      onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
          return;
        event.preventDefault();
        const width =
          event.key === "Home"
            ? 320
            : event.key === "End"
              ? 900
              : (event.currentTarget.parentElement?.getBoundingClientRect()
                  .width ?? layout.width) +
                (event.key === "ArrowRight" ? 20 : -20) *
                  (layout.dock !== "right" ? 1 : -1);
        onChange({ ...layout, width: Math.max(320, Math.min(900, width)) });
      }}
    >
      <span />
    </div>
  );
}
export function DeskDropZones({ onDrop }: { onDrop: (dock: Dock) => void }) {
  return (
    <div className="pulse-dropzones">
      {(
        [
          ["left", "Dock left"],
          ["right", "Dock right"],
          ["bottom", "Dock below"],
        ] as const
      ).map(([dock, label]) => (
        <div
          key={dock}
          className={`pulse-drop-${dock}`}
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
          }}
          onDrop={(event) => {
            event.preventDefault();
            if (
              event.dataTransfer.getData("application/x-trademaster-panel") ===
              "pulse-desk"
            )
              onDrop(dock);
          }}
        >
          {label}
        </div>
      ))}
    </div>
  );
}
