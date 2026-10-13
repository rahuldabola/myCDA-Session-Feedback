"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api, getErrorMessages } from "@/lib/api";
import type {
  ClassItem,
  InstructorFeedbackSummary,
  PaginatedResponse,
  UserMinimal,
} from "@/lib/types";
import DashboardCard from "./DashboardCard";

const TITLE = "Session Feedback Summary";
const SUBTITLE = "Aggregated & anonymized";

const DIMENSIONS = [
  { key: "clarity", label: "Clarity" },
  { key: "engagement", label: "Engagement" },
  { key: "pace", label: "Pace" },
] as const;

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-gray-600">{label}</span>
        <span className="font-medium text-gray-900">{value.toFixed(2)}</span>
      </div>
      <div className="h-2 rounded-full bg-gray-100">
        <div
          className="h-2 rounded-full bg-cda-blue"
          style={{ width: `${(value / 5) * 100}%` }}
        />
      </div>
    </div>
  );
}

function SummaryBody({ summary }: { summary: InstructorFeedbackSummary }) {
  const { averages } = summary;
  const footnote = (
    <p className="mt-4 text-xs text-gray-500">
      {summary.total_feedback} response{summary.total_feedback !== 1 ? "s" : ""} across{" "}
      {summary.sessions_with_feedback} of your last {summary.window_size} completed sessions.
      Averages are weighted by session length. Individual responses, notes and
      student names are never shown.
    </p>
  );

  if (!averages) {
    return (
      <div>
        <p className="text-sm text-gray-600">
          Scores appear once at least {summary.min_feedback_for_scores} responses are in,
          so no individual student&apos;s ratings can be inferred.
        </p>
        {footnote}
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex items-baseline gap-2">
        <span className="text-3xl font-semibold text-cda-navy">{averages.overall.toFixed(2)}</span>
        <span className="text-sm text-gray-500">/ 5 overall</span>
      </div>
      <div className="space-y-3">
        {DIMENSIONS.map((dim) => (
          <ScoreBar key={dim.key} label={dim.label} value={averages[dim.key]} />
        ))}
      </div>
      {footnote}
    </div>
  );
}

export default function InstructorFeedbackSummaryCard() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  // Admins choose which instructor to view (derived from the class list);
  // instructors always see their own summary.
  const [instructors, setInstructors] = useState<UserMinimal[]>([]);
  const [instructorId, setInstructorId] = useState<number | null>(null);
  const [summary, setSummary] = useState<InstructorFeedbackSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isAdmin) return;
    api
      .get<PaginatedResponse<ClassItem>>("/classes/?page_size=100")
      .then((res) => {
        const unique = new Map<number, UserMinimal>();
        res.results.forEach((cls) => unique.set(cls.instructor, cls.instructor_display));
        const list = Array.from(unique.values());
        setInstructors(list);
        setInstructorId(list[0]?.id ?? null);
        if (list.length === 0) setLoading(false);
      })
      .catch(() => {
        setError("Could not load instructors.");
        setLoading(false);
      });
  }, [isAdmin]);

  useEffect(() => {
    if (isAdmin && instructorId === null) return;
    setLoading(true);
    setError("");
    const query = isAdmin ? `?instructor_id=${instructorId}` : "";
    api
      .get<InstructorFeedbackSummary>(`/feedback/instructor-summary/${query}`)
      .then(setSummary)
      .catch((err) => setError(getErrorMessages(err, "Could not load feedback summary.")[0]))
      .finally(() => setLoading(false));
  }, [isAdmin, instructorId]);

  const picker = isAdmin && instructors.length > 0 && (
    <select
      aria-label="Instructor"
      value={instructorId ?? ""}
      onChange={(e) => setInstructorId(Number(e.target.value))}
      className="rounded-md border border-gray-300 px-2 py-1 text-xs focus:border-cda-blue focus:outline-none"
    >
      {instructors.map((i) => (
        <option key={i.id} value={i.id}>
          {i.display_name}
        </option>
      ))}
    </select>
  );

  return (
    <DashboardCard title={TITLE} subtitle={SUBTITLE} action={picker || undefined}>
      {loading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : error ? (
        <p className="text-sm text-red-500">{error}</p>
      ) : summary ? (
        <SummaryBody summary={summary} />
      ) : (
        <p className="text-sm text-gray-500">No instructors found.</p>
      )}
    </DashboardCard>
  );
}
