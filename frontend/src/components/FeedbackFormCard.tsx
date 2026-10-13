"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api, getErrorMessages } from "@/lib/api";
import type {
  PaginatedResponse,
  Session,
  SessionFeedbackInput,
  UserMinimal,
} from "@/lib/types";
import DashboardCard from "./DashboardCard";
import { RatingInput } from "./RatingStars";

const NOTE_MAX = 500;

type Ratings = { clarity: number; engagement: number; pace: number };
const EMPTY_RATINGS: Ratings = { clarity: 0, engagement: 0, pace: 0 };

const DIMENSIONS: { key: keyof Ratings; label: string; hint: string }[] = [
  { key: "clarity", label: "Clarity", hint: "How clearly were concepts explained?" },
  { key: "engagement", label: "Engagement", hint: "How engaging was the session?" },
  { key: "pace", label: "Pace", hint: "Did the pacing feel right?" },
];

interface FeedbackFormCardProps {
  onSubmit: (
    input: SessionFeedbackInput,
    session: Session,
    student: UserMinimal
  ) => Promise<void>;
}

function byDateDesc(a: Session, b: Session) {
  return b.scheduled_date.localeCompare(a.scheduled_date);
}

export default function FeedbackFormCard({ onSubmit }: FeedbackFormCardProps) {
  const { user } = useAuth();
  const isParent = user?.role === "parent";
  const children = (user?.family_links ?? []).map((link) => link.student_display);

  // Parents pick a child (pre-selected if they only have one); students
  // always submit for themselves.
  const [studentId, setStudentId] = useState<number | null>(() => {
    if (!isParent) return user?.id ?? null;
    return children.length === 1 ? children[0].id : null;
  });
  // Eligible sessions cached per student, so a rollback can restore a
  // session to the right child's list even after switching children.
  const [eligible, setEligible] = useState<Record<number, Session[]>>({});
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadError, setLoadError] = useState("");

  const [sessionId, setSessionId] = useState<number | null>(null);
  const [ratings, setRatings] = useState<Ratings>(EMPTY_RATINGS);
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState("");

  const loadEligible = useCallback(
    (forStudent: number) => {
      setLoadingSessions(true);
      setLoadError("");
      const query = isParent ? `?student=${forStudent}` : "";
      return api
        .get<PaginatedResponse<Session>>(`/feedback/eligible-sessions/${query}`)
        .then((res) => setEligible((prev) => ({ ...prev, [forStudent]: res.results })))
        .catch(() => setLoadError("Could not load sessions."))
        .finally(() => setLoadingSessions(false));
    },
    [isParent]
  );

  useEffect(() => {
    if (studentId !== null && !(studentId in eligible)) {
      loadEligible(studentId);
    }
  }, [studentId, eligible, loadEligible]);

  if (!user) return null;

  const sessions = studentId !== null ? eligible[studentId] ?? [] : [];
  const selectedSession = sessions.find((s) => s.id === sessionId);
  const ready =
    studentId !== null &&
    selectedSession !== undefined &&
    ratings.clarity > 0 &&
    ratings.engagement > 0 &&
    ratings.pace > 0;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready || studentId === null || !selectedSession) return;

    const session = selectedSession;
    const forStudent = studentId;
    const student: UserMinimal = isParent
      ? children.find((c) => c.id === forStudent)!
      : { id: user.id, display_name: user.display_name, role: user.role };
    const input: SessionFeedbackInput = {
      session: session.id,
      // Students are defaulted to themselves server-side
      ...(isParent ? { student: forStudent } : {}),
      rating_clarity: ratings.clarity,
      rating_engagement: ratings.engagement,
      rating_pace: ratings.pace,
      note: note.trim(),
    };
    const draft = { ratings, note };

    // Optimistic: treat it as submitted -- drop the session and reset the form.
    setEligible((prev) => ({
      ...prev,
      [forStudent]: (prev[forStudent] ?? []).filter((s) => s.id !== session.id),
    }));
    setSessionId(null);
    setRatings(EMPTY_RATINGS);
    setNote("");
    setErrors([]);
    setNotice(`Feedback for ${session.class_name} submitted.`);

    try {
      await onSubmit(input, session, student);
    } catch (err) {
      // Roll back: put the session and the draft back, show why it failed.
      setNotice("");
      setErrors(getErrorMessages(err, "Could not submit feedback. Please try again."));
      setEligible((prev) => {
        const list = prev[forStudent] ?? [];
        if (list.some((s) => s.id === session.id)) return prev;
        return { ...prev, [forStudent]: [...list, session].sort(byDateDesc) };
      });
      setStudentId(forStudent);
      setSessionId(session.id);
      setRatings(draft.ratings);
      setNote(draft.note);
      // The server is the source of truth for eligibility (e.g. a sibling
      // device or parent already reviewed it) -- resync the list.
      loadEligible(forStudent);
    }
  };

  return (
    <DashboardCard title="Leave Session Feedback" subtitle="Anonymous to your instructor">
      <form onSubmit={handleSubmit} className="space-y-4">
        {isParent && (
          <div>
            <label htmlFor="feedback-student" className="mb-1 block text-sm font-medium text-gray-700">
              Submitting for
            </label>
            {children.length === 0 ? (
              <p className="text-sm text-gray-500">No students are linked to your account.</p>
            ) : (
              <select
                id="feedback-student"
                value={studentId ?? ""}
                onChange={(e) => {
                  setStudentId(e.target.value ? Number(e.target.value) : null);
                  setSessionId(null);
                  setErrors([]);
                  setNotice("");
                }}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-cda-blue focus:outline-none focus:ring-1 focus:ring-cda-blue"
              >
                <option value="">Select a student...</option>
                {children.map((child) => (
                  <option key={child.id} value={child.id}>
                    {child.display_name}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        {studentId !== null && (
          <div>
            <p className="mb-1 text-sm font-medium text-gray-700">Session</p>
            {loadingSessions && sessions.length === 0 ? (
              <p className="text-sm text-gray-400">Loading...</p>
            ) : loadError ? (
              <p className="text-sm text-red-500">{loadError}</p>
            ) : sessions.length === 0 ? (
              <p className="text-sm text-gray-500">
                No sessions awaiting feedback. Completed sessions can be reviewed for 30 days.
              </p>
            ) : (
              <ul className="divide-y divide-gray-100 rounded-md border border-gray-200">
                {sessions.map((s) => (
                  <li key={s.id}>
                    <label className="flex cursor-pointer items-start gap-3 px-3 py-2 hover:bg-gray-50">
                      <input
                        type="radio"
                        name="feedback-session"
                        className="mt-1"
                        checked={sessionId === s.id}
                        onChange={() => setSessionId(s.id)}
                      />
                      <span>
                        <span className="block text-sm font-medium text-gray-900">{s.class_name}</span>
                        <span className="block text-xs text-gray-500">
                          {new Date(s.scheduled_date).toLocaleDateString()}
                          {s.topic && ` · ${s.topic}`}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {selectedSession && (
          <>
            {DIMENSIONS.map((dim) => (
              <RatingInput
                key={dim.key}
                label={dim.label}
                hint={dim.hint}
                value={ratings[dim.key]}
                onChange={(value) => setRatings((prev) => ({ ...prev, [dim.key]: value }))}
              />
            ))}

            <div>
              <label htmlFor="feedback-note" className="mb-1 block text-sm font-medium text-gray-700">
                Note <span className="font-normal text-gray-400">(optional)</span>
              </label>
              <textarea
                id="feedback-note"
                rows={3}
                maxLength={NOTE_MAX}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-cda-blue focus:outline-none focus:ring-1 focus:ring-cda-blue"
              />
              <p className={`text-right text-xs ${note.length >= NOTE_MAX ? "text-red-500" : "text-gray-400"}`}>
                {note.length}/{NOTE_MAX}
              </p>
            </div>
          </>
        )}

        {errors.length > 0 && (
          <ul className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600" role="alert">
            {errors.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
        )}
        {notice && <p className="text-sm text-green-700">{notice}</p>}

        {selectedSession && (
          <button
            type="submit"
            disabled={!ready}
            className="w-full rounded-md bg-cda-navy px-4 py-2 text-sm font-medium text-white hover:bg-cda-navy/90 disabled:opacity-50"
          >
            Submit feedback
          </button>
        )}
      </form>
    </DashboardCard>
  );
}
