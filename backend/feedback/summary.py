"""
Weighted rolling average of an instructor's feedback.

Window: the instructor's last ROLLING_WINDOW_SESSIONS completed sessions
(across all of their classes), newest first by scheduled date. Sessions
in the window with no feedback contribute nothing.

For each dimension d, with per-session average score a_i,d and session
duration w_i (minutes, from session_metadata["duration_minutes"]):

    weighted_avg_d = sum(w_i * a_i,d) / sum(w_i)

over the sessions in the window that have feedback. `overall` is the
mean of the three dimension averages, which equals the duration-weighted
average of each session's mean score because all three share the weights.
"""

import math

from django.db.models import Avg, Count

from classes.models import Session

ROLLING_WINDOW_SESSIONS = 10

# Below this many feedback entries the averages are withheld: with one or
# two responses an instructor could work out an individual's ratings.
MIN_FEEDBACK_FOR_SCORES = 3

DIMENSIONS = ("clarity", "engagement", "pace")


def _session_duration(session):
    """Duration in minutes from session_metadata, or None if missing/invalid.

    Deliberately not Session.duration_minutes, which falls back to 60:
    weighting by a made-up duration would skew the average silently.
    """
    value = session.session_metadata.get("duration_minutes")
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(minutes) or minutes <= 0:
        return None
    return minutes


def instructor_summary(instructor):
    window = list(
        Session.objects.filter(
            class_obj__instructor=instructor,
            status=Session.Status.COMPLETED,
        )
        .annotate(
            feedback_count=Count("feedback"),
            avg_clarity=Avg("feedback__rating_clarity"),
            avg_engagement=Avg("feedback__rating_engagement"),
            avg_pace=Avg("feedback__rating_pace"),
        )
        .order_by("-scheduled_date", "-id")[:ROLLING_WINDOW_SESSIONS]
    )

    total_weight = 0.0
    weighted_sums = dict.fromkeys(DIMENSIONS, 0.0)
    total_feedback = 0
    sessions_with_feedback = 0

    for session in window:
        if not session.feedback_count:
            continue
        duration = _session_duration(session)
        if duration is None:
            # Can't weight it, so leave it out entirely (score and count)
            # rather than guess a duration.
            continue
        sessions_with_feedback += 1
        total_feedback += session.feedback_count
        total_weight += duration
        for dim in DIMENSIONS:
            weighted_sums[dim] += duration * getattr(session, f"avg_{dim}")

    averages = None
    if total_feedback >= MIN_FEEDBACK_FOR_SCORES:
        averages = {
            dim: round(weighted_sums[dim] / total_weight, 2) for dim in DIMENSIONS
        }
        averages["overall"] = round(
            sum(weighted_sums.values()) / (len(DIMENSIONS) * total_weight), 2
        )

    return {
        "instructor_id": instructor.pk,
        "window_size": ROLLING_WINDOW_SESSIONS,
        "sessions_in_window": len(window),
        "sessions_with_feedback": sessions_with_feedback,
        "total_feedback": total_feedback,
        "min_feedback_for_scores": MIN_FEEDBACK_FOR_SCORES,
        "averages": averages,
    }
