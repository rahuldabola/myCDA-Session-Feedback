"use client";

import { useAuth } from "@/contexts/AuthContext";
import type { SessionFeedback } from "@/lib/types";
import DashboardCard from "./DashboardCard";
import { RatingDisplay } from "./RatingStars";

interface FeedbackHistoryCardProps {
  entries: SessionFeedback[];
  loading: boolean;
  error: string;
}

function FeedbackEntry({ entry }: { entry: SessionFeedback }) {
  const pending = entry.id < 0;
  return (
    <li className={`px-5 py-3 ${pending ? "opacity-60" : ""}`}>
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-900">{entry.class_name}</p>
        <p className="text-xs text-gray-500">
          {pending ? "Saving..." : new Date(entry.session_date).toLocaleDateString()}
        </p>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        <RatingDisplay label="Clarity" value={entry.rating_clarity} />
        <RatingDisplay label="Engagement" value={entry.rating_engagement} />
        <RatingDisplay label="Pace" value={entry.rating_pace} />
      </div>
      {entry.note && <p className="mt-1 text-sm italic text-gray-600">&ldquo;{entry.note}&rdquo;</p>}
    </li>
  );
}

export default function FeedbackHistoryCard({ entries, loading, error }: FeedbackHistoryCardProps) {
  const { user } = useAuth();
  const title = "Feedback History";

  if (loading) {
    return (
      <DashboardCard title={title}>
        <p className="text-sm text-gray-400">Loading...</p>
      </DashboardCard>
    );
  }

  if (error) {
    return (
      <DashboardCard title={title}>
        <p className="text-sm text-red-500">{error}</p>
      </DashboardCard>
    );
  }

  if (entries.length === 0) {
    return (
      <DashboardCard title={title}>
        <p className="text-sm text-gray-500">No feedback submitted yet.</p>
      </DashboardCard>
    );
  }

  const subtitle = `${entries.length} review${entries.length !== 1 ? "s" : ""}`;

  if (user?.role !== "parent") {
    return (
      <DashboardCard title={title} subtitle={subtitle} flush>
        <ul className="divide-y divide-gray-100">
          {entries.map((entry) => (
            <FeedbackEntry key={entry.id} entry={entry} />
          ))}
        </ul>
      </DashboardCard>
    );
  }

  // Parents: group by student, keeping each group's newest-first order.
  const groups = new Map<number, { name: string; items: SessionFeedback[] }>();
  for (const entry of entries) {
    const group = groups.get(entry.student) ?? {
      name: entry.student_display.display_name,
      items: [],
    };
    group.items.push(entry);
    groups.set(entry.student, group);
  }

  return (
    <DashboardCard title={title} subtitle={subtitle} flush>
      {Array.from(groups.entries()).map(([studentId, group]) => (
        <section key={studentId}>
          <h4 className="bg-gray-50 px-5 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            {group.name}
          </h4>
          <ul className="divide-y divide-gray-100">
            {group.items.map((entry) => (
              <FeedbackEntry key={entry.id} entry={entry} />
            ))}
          </ul>
        </section>
      ))}
    </DashboardCard>
  );
}
