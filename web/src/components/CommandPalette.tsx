import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Icon } from "./Icon";
import { api } from "../lib/api";
import type { MeetingListItem } from "../types";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

const MAX_RESULTS = 12;

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);

  const { data: meetings = [] } = useQuery({
    queryKey: ["meetings", { all: true }],
    queryFn: () => api.meetings({ past_days: 3650, future_days: 365 }),
  });

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      // Focus after the panel paints so the input element exists.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return [...meetings]
        .sort((a, b) => b.meeting_date.localeCompare(a.meeting_date))
        .slice(0, MAX_RESULTS);
    }
    return meetings
      .filter((m) => {
        const hay = `${m.title} ${m.type_name} ${m.venue} ${m.type_short} ${m.location} ${m.tags.join(" ")}`.toLowerCase();
        return hay.includes(q);
      })
      .sort((a, b) => b.meeting_date.localeCompare(a.meeting_date))
      .slice(0, MAX_RESULTS);
  }, [meetings, query]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  if (!open) return null;

  const openMeeting = (m: MeetingListItem) => {
    navigate(`/meeting/${m.id}`);
    onClose();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, Math.max(results.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const m = results[selectedIndex];
      if (m) openMeeting(m);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  return (
    <div
      className="cmd-palette-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="cmd-palette" role="dialog" aria-label="Search meetings">
        <div className="cmd-palette-inputrow">
          <Icon name="search" size={14} />
          <input
            ref={inputRef}
            className="cmd-palette-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search meetings by title, tag, venue, location…"
          />
          <span className="kbd">esc</span>
        </div>

        {results.length === 0 ? (
          <div className="cmd-palette-empty">No meetings match.</div>
        ) : (
          <div className="cmd-palette-results" role="listbox">
            {results.map((m, i) => (
              <button
                key={m.id}
                type="button"
                role="option"
                aria-selected={i === selectedIndex}
                className={`cmd-palette-row ${i === selectedIndex ? "active" : ""}`}
                onMouseEnter={() => setSelectedIndex(i)}
                onClick={() => openMeeting(m)}
              >
                <span className="cmd-palette-title">{m.title}</span>
                <span className="cmd-palette-meta">
                  {m.meeting_date} · {m.venue} · {m.type_short}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
