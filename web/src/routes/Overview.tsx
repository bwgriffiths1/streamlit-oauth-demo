import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Topbar } from "../components/Topbar";
import { Icon } from "../components/Icon";
import { Segmented } from "../components/Segmented";
import { MeetingRow } from "../components/MeetingRow";
import { api } from "../lib/api";
import { TODAY } from "../lib/fixtures";
import type { CurrentUser, MeetingListItem, MeetingStatus } from "../types";

type Venue = "All" | "ISO-NE";
type StatusFilter = "All" | MeetingStatus;
type View = "list" | "card";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Good evening";
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export function Overview() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [view, setView] = useState<View>("list");
  const [venueFilter, setVenueFilter] = useState<Venue>("All");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("All");

  const { data: me } = useQuery<CurrentUser>({ queryKey: ["me"] });
  const firstName = (me?.name || "").split(" ")[0] || "there";

  const { data: meetings = [] } = useQuery({
    queryKey: ["meetings", { past_days: 730, future_days: 365 }],
    queryFn: () => api.meetings({ past_days: 730, future_days: 365 }),
  });

  const refreshAll = useMutation({
    mutationFn: () => api.refreshAll(),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["meetings"] });
      alert(`Refreshed ${data.refreshed} of ${data.total} meetings.`);
    },
    onError: (err: Error) => {
      alert(`Refresh failed: ${err.message}`);
    },
  });

  const filtered = useMemo(() => {
    return meetings.filter((m) => {
      if (venueFilter !== "All" && m.venue !== venueFilter) return false;
      if (statusFilter !== "All" && m.status !== statusFilter) return false;
      return true;
    });
  }, [meetings, venueFilter, statusFilter]);

  const upcoming = useMemo(
    () =>
      filtered
        .filter((m) => m.meeting_date >= TODAY)
        .sort((a, b) => a.meeting_date.localeCompare(b.meeting_date)),
    [filtered]
  );
  const past = useMemo(
    () =>
      filtered
        .filter((m) => m.meeting_date < TODAY)
        .sort((a, b) => b.meeting_date.localeCompare(a.meeting_date)),
    [filtered]
  );

  const summarizedThisMonth = meetings.filter(
    (m) => m.status === "summarized" && m.meeting_date.startsWith(TODAY.slice(0, 7))
  ).length;
  const pendingReview = meetings.filter((m) => m.status === "materials").length;

  const openMeeting = (m: MeetingListItem) => navigate(`/meeting/${m.id}`);

  return (
    <>
      <Topbar
        crumbs={[{ label: "Overview" }]}
        actions={
          <>
            <button
              className="btn btn-sm"
              onClick={() => refreshAll.mutate()}
              disabled={refreshAll.isPending}
            >
              <Icon name="refresh" />
              {refreshAll.isPending ? "Refreshing…" : "Refresh materials"}
            </button>
            <button className="btn btn-sm" onClick={() => navigate("/add")}>
              <Icon name="calendar" /> Refresh calendars
            </button>
            <button
              className="btn btn-sm btn-primary"
              onClick={() => navigate("/add")}
            >
              <Icon name="plus" /> Add meeting
            </button>
          </>
        }
      />

      <div className="page">
        <div className="page-header">
          <div className="page-eyebrow">Meeting calendar · ISO-NE</div>
          <h1 className="page-title">{greeting()}, {firstName}.</h1>
          <p className="page-subtitle">
            {pendingReview > 0 ? (
              <>
                <span style={{ color: "var(--ink)" }}>
                  {pendingReview} meetings
                </span>{" "}
                with materials ready to summarize.{" "}
              </>
            ) : null}
            {summarizedThisMonth} briefings published this month.
          </p>
        </div>

        <Inbox meetings={meetings} onOpen={openMeeting} />

        <div className="kpi-grid">
          <div className="kpi">
            <div className="kpi-label">Upcoming</div>
            <div className="kpi-num">{upcoming.length}</div>
            <div className="kpi-sub">next 30 days</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Materials ready</div>
            <div className="kpi-num">{pendingReview}</div>
            <div className="kpi-sub">awaiting briefing</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Summarized</div>
            <div className="kpi-num">{summarizedThisMonth}</div>
            <div className="kpi-sub">this month</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Hours saved</div>
            <div className="kpi-num">~64</div>
            <div className="kpi-sub">vs. manual briefing time</div>
          </div>
        </div>

        <div className="filter-bar">
          <div className="row" style={{ gap: 6 }}>
            <Segmented
              value={venueFilter}
              onChange={setVenueFilter}
              options={[
                { value: "All", label: "All" },
                { value: "ISO-NE", label: "ISO-NE" },
              ]}
            />
            <Segmented
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "All", label: "All" },
                { value: "scheduled", label: "Scheduled" },
                { value: "materials", label: "Materials" },
                { value: "summarized", label: "Summarized" },
                { value: "updated", label: "Updated" },
              ]}
            />
          </div>
          <div className="spacer" />
          <Segmented
            value={view}
            onChange={setView}
            options={[
              {
                value: "list",
                label: (
                  <>
                    <Icon name="list" /> List
                  </>
                ),
              },
              {
                value: "card",
                label: (
                  <>
                    <Icon name="dot" /> Cards
                  </>
                ),
              },
            ]}
          />
        </div>

        <div className="section-h">
          <h2>Upcoming</h2>
          <span className="meta">{upcoming.length} meetings</span>
        </div>
        {view === "list" ? (
          <div className="mtg-list">
            {upcoming.length === 0 ? (
              <div className="empty">Nothing on the calendar.</div>
            ) : (
              upcoming.map((m) => (
                <MeetingRow key={m.id} m={m} onOpen={openMeeting} view="list" />
              ))
            )}
          </div>
        ) : (
          <div className="mtg-cards">
            {upcoming.map((m) => (
              <MeetingRow key={m.id} m={m} onOpen={openMeeting} view="card" />
            ))}
          </div>
        )}

        <div className="section-h">
          <h2>Recent</h2>
          <span className="meta">{past.length} meetings</span>
        </div>
        {view === "list" ? (
          <div className="mtg-list">
            {past.map((m) => (
              <MeetingRow key={m.id} m={m} onOpen={openMeeting} view="list" />
            ))}
          </div>
        ) : (
          <div className="mtg-cards">
            {past.map((m) => (
              <MeetingRow key={m.id} m={m} onOpen={openMeeting} view="card" />
            ))}
          </div>
        )}

        <div style={{ height: 48 }} />
      </div>
    </>
  );
}

// ── Inbox ─────────────────────────────────────────────────────────────────

type Bucket =
  | "stub"
  | "has_agenda"
  | "needs_categorization"
  | "ready_to_summarize"
  | "new_files"
  | "summarized";

interface BucketDef {
  key: Bucket;
  label: string;
  hint: string;
  match: (m: MeetingListItem) => boolean;
}

// Mutually-exclusive — each meeting falls into at most one bucket, by priority.
const BUCKETS: BucketDef[] = [
  {
    key: "needs_categorization",
    label: "Needs file categorization",
    hint: "Documents arrived but aren't matched to agenda items yet.",
    match: (m) => (m.unassigned_doc_count ?? 0) > 0,
  },
  {
    key: "new_files",
    label: "New files uploaded",
    hint: "Briefing already exists but new documents have landed since.",
    match: (m) => m.status === "updated",
  },
  {
    key: "ready_to_summarize",
    label: "Ready to summarize",
    hint: "Agenda + documents are in, everything categorized. Click into the meeting and run summaries.",
    match: (m) =>
      m.item_count > 0 &&
      m.doc_count > 0 &&
      (m.unassigned_doc_count ?? 0) === 0 &&
      m.status !== "summarized" &&
      m.status !== "updated",
  },
  {
    key: "has_agenda",
    label: "Has agenda",
    hint: "Agenda parsed but no documents yet — waiting on the next refresh.",
    match: (m) =>
      m.item_count > 0 &&
      m.doc_count === 0 &&
      m.status !== "summarized" &&
      m.status !== "updated",
  },
  {
    key: "stub",
    label: "Stub",
    hint: "Discovered by the scraper. No agenda or documents yet.",
    match: (m) =>
      m.item_count === 0 &&
      m.doc_count === 0 &&
      m.status === "scheduled",
  },
  {
    key: "summarized",
    label: "Summarized",
    hint: "Briefing has been generated. Open to read or re-run.",
    match: (m) => m.status === "summarized",
  },
];

function bucketize(meetings: MeetingListItem[]): Record<Bucket, MeetingListItem[]> {
  const result: Record<Bucket, MeetingListItem[]> = {
    needs_categorization: [],
    new_files: [],
    ready_to_summarize: [],
    has_agenda: [],
    stub: [],
    summarized: [],
  };
  // Inbox is about *active* work — limit to recent + upcoming, skip ancient stubs.
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 30);
  const cutoffIso = cutoff.toISOString().slice(0, 10);

  for (const m of meetings) {
    if (m.meeting_date < cutoffIso) continue;
    for (const b of BUCKETS) {
      if (b.match(m)) {
        result[b.key].push(m);
        break;
      }
    }
  }
  // Most-recent first within each bucket.
  for (const k of Object.keys(result) as Bucket[]) {
    result[k].sort((a, b) => b.meeting_date.localeCompare(a.meeting_date));
  }
  return result;
}

function Inbox({
  meetings,
  onOpen,
}: {
  meetings: MeetingListItem[];
  onOpen: (m: MeetingListItem) => void;
}) {
  const buckets = useMemo(() => bucketize(meetings), [meetings]);
  const [open, setOpen] = useState<Bucket | null>(null);

  // "Summarized" is a done state, not work — exclude from the attention count.
  const needsAttention =
    buckets.needs_categorization.length +
    buckets.new_files.length +
    buckets.ready_to_summarize.length +
    buckets.has_agenda.length +
    buckets.stub.length;

  return (
    <div className="inbox">
      <div className="inbox-head">
        <h2 className="section-head" style={{ margin: 0 }}>
          Inbox
        </h2>
        <span className="muted text-xs">
          {needsAttention === 0
            ? "All caught up."
            : `${needsAttention} meeting${needsAttention === 1 ? "" : "s"} need attention.`}
        </span>
      </div>
      <div className="inbox-grid">
        {BUCKETS.map((b) => {
          const list = buckets[b.key];
          const isOpen = open === b.key;
          return (
            <div key={b.key} className={`inbox-card ${list.length === 0 ? "muted-card" : ""}`}>
              <button
                type="button"
                className="inbox-card-head"
                onClick={() => setOpen(isOpen ? null : b.key)}
              >
                <div>
                  <div className="inbox-card-label">{b.label}</div>
                  <div className="inbox-card-hint">{b.hint}</div>
                </div>
                <div className="inbox-card-num">{list.length}</div>
              </button>
              {isOpen && list.length > 0 && (
                <div className="inbox-list">
                  {list.slice(0, 25).map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      className="inbox-row"
                      onClick={() => onOpen(m)}
                    >
                      <span className="mono text-xs muted">{m.meeting_date}</span>
                      <span className="inbox-row-title">{m.title || m.type_name}</span>
                      <span className="mono text-xs muted">{m.type_short}</span>
                    </button>
                  ))}
                  {list.length > 25 && (
                    <div className="muted text-xs" style={{ padding: "6px 10px" }}>
                      + {list.length - 25} more
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
