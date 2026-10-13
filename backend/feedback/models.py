from datetime import timedelta

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from accounts.models import FamilyLink, User
from classes.models import Session


# Feedback is accepted for this many days after a session took place.
FEEDBACK_WINDOW_DAYS = 30

RATING_MIN = 1
RATING_MAX = 5
RATING_VALIDATORS = [MinValueValidator(RATING_MIN), MaxValueValidator(RATING_MAX)]


def feedback_window_start():
    """Earliest `scheduled_date` a session may have and still accept feedback.

    Sessions have no separate completion timestamp, so the scheduled date
    stands in for the date the session was completed.
    """
    return timezone.now() - timedelta(days=FEEDBACK_WINDOW_DAYS)


def can_submit_for(user, student):
    """A student may submit for themselves; a parent for linked students."""
    if user.role == User.Role.STUDENT:
        return user.pk == student.pk
    if user.role == User.Role.PARENT:
        return FamilyLink.objects.filter(parent=user, student=student).exists()
    return False


def eligible_sessions_for(student):
    """Sessions `student` can still review: completed, inside the feedback
    window, in a class they are actively enrolled in, not yet reviewed.

    Mirrors the checks in SessionFeedbackSerializer.validate so the form
    only offers sessions the API will accept.
    """
    return (
        Session.objects.filter(
            status=Session.Status.COMPLETED,
            scheduled_date__gte=feedback_window_start(),
            class_obj__enrollments__student=student,
            class_obj__enrollments__is_active=True,
        )
        .exclude(feedback__student=student)
        .select_related("class_obj", "class_obj__instructor")
    )


class SessionFeedback(models.Model):
    """
    A student's structured review of one completed session.

    `student` is who the feedback represents; `created_by` is who actually
    submitted it (the student themselves, or a parent linked via
    FamilyLink). `created_by` follows the project's audit-field convention
    so BaseModelSerializer populates it from the request user.

    Raw rows (student, submitter, note) are only ever exposed to the
    student/parent side. Instructors get aggregates only -- see
    InstructorSummaryView.
    """

    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="session_feedback",
        limit_choices_to={"role": "student"},
    )
    rating_clarity = models.PositiveSmallIntegerField(
        validators=RATING_VALIDATORS,
        help_text="How clearly the instructor explained concepts (1-5).",
    )
    rating_engagement = models.PositiveSmallIntegerField(
        validators=RATING_VALIDATORS,
        help_text="How engaging the session was (1-5).",
    )
    rating_pace = models.PositiveSmallIntegerField(
        validators=RATING_VALIDATORS,
        help_text="Whether the pacing felt right (1-5).",
    )
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_feedback",
        verbose_name="submitter",
    )

    class Meta:
        ordering = ["-created_at"]
        # One review per student per session, regardless of who submits it:
        # a parent re-submitting for the same child is still a duplicate.
        unique_together = ("session", "student")
        # Database-level backstop for the 1-5 range, in case rows are
        # written outside the serializer (admin, shell, data migrations).
        constraints = [
            models.CheckConstraint(
                condition=Q(**{f"{field}__gte": RATING_MIN, f"{field}__lte": RATING_MAX}),
                name=f"feedback_{field}_range",
            )
            for field in ("rating_clarity", "rating_engagement", "rating_pace")
        ]
        verbose_name = "session feedback"
        verbose_name_plural = "session feedback"

    def __str__(self):
        return f"Feedback by {self.student.get_display_name()} on {self.session}"
