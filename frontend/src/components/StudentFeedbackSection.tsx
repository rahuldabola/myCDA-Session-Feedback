"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  PaginatedResponse,
  Session,
  SessionFeedback,
  SessionFeedbackInput,
  UserMinimal,
} from "@/lib/types";
import FeedbackFormCard from "./FeedbackFormCard";
import FeedbackHistoryCard from "./FeedbackHistoryCard";

/**
 * Owns the feedback history so the form can add an entry optimistically
 * and the history card shows it immediately. Renders two dashboard cards.
 */
export default function StudentFeedbackSection() {
  const [entries, setEntries] = useState<SessionFeedback[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<PaginatedResponse<SessionFeedback>>("/feedback/my/?page_size=100")
      .then((res) => setEntries(res.results))
      .catch(() => setError("Could not load feedback history."))
      .finally(() => setLoading(false));
  }, []);

  /**
   * Show the entry in history straight away (negative temp id marks it as
   * pending), then swap in the server's version or roll back on error.
   * Errors are re-thrown so the form can restore its draft and show them.
   */
  const submitFeedback = useCallback(
    async (input: SessionFeedbackInput, session: Session, student: UserMinimal) => {
      const tempId = -Date.now();
      const now = new Date().toISOString();
      const optimistic: SessionFeedback = {
        ...input,
        id: tempId,
        student: student.id,
        student_display: student,
        session_date: session.scheduled_date,
        class_name: session.class_name,
        session_topic: session.topic,
        created_by_display: null,
        created_at: now,
        updated_at: now,
      };
      setEntries((prev) => [optimistic, ...prev]);

      try {
        const saved = await api.post<SessionFeedback>("/feedback/", input);
        setEntries((prev) => prev.map((e) => (e.id === tempId ? saved : e)));
      } catch (err) {
        setEntries((prev) => prev.filter((e) => e.id !== tempId));
        throw err;
      }
    },
    []
  );

  return (
    <>
      <FeedbackFormCard onSubmit={submitFeedback} />
      <FeedbackHistoryCard entries={entries} loading={loading} error={error} />
    </>
  );
}
