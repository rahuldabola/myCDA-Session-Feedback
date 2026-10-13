import json
from datetime import timedelta

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import FamilyLink, User
from classes.models import Class, ClassEnrollment, Session
from feedback.models import SessionFeedback

URL = "/api/v1/feedback/"
MY_URL = "/api/v1/feedback/my/"
ELIGIBLE_URL = "/api/v1/feedback/eligible-sessions/"
SUMMARY_URL = "/api/v1/feedback/instructor-summary/"

RATINGS = {"rating_clarity": 4, "rating_engagement": 5, "rating_pace": 3}


def make_user(username, role, first="", last=""):
    return User.objects.create_user(
        username=username,
        email=f"{username}@cda.test",
        password="testpass123",
        role=role,
        first_name=first,
        last_name=last,
    )


def make_session(cls, days_ago, status="completed", duration=60):
    metadata = {"topic_covered": "Topic"}
    if duration is not None:
        metadata["duration_minutes"] = duration
    return Session.objects.create(
        class_obj=cls,
        scheduled_date=timezone.now() - timedelta(days=days_ago),
        status=status,
        session_metadata=metadata,
    )


class FeedbackTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin", "admin")
        cls.sarah = make_user("sarah", "instructor", "Sarah", "Chen")
        cls.marcus = make_user("marcus", "instructor", "Marcus", "Rivera")
        cls.emma = make_user("emma", "student", "Emma", "Wilson")
        cls.liam = make_user("liam", "student", "Liam", "Wilson")
        cls.zara = make_user("zara", "student", "Zara", "Adams")
        cls.james = make_user("james", "parent", "James", "Wilson")
        cls.priya = make_user("priya", "parent", "Priya", "Sharma")
        FamilyLink.objects.create(parent=cls.james, student=cls.emma)
        FamilyLink.objects.create(parent=cls.james, student=cls.liam)

        cls.ld = Class.objects.create(name="LD Fundamentals", instructor=cls.sarah)
        cls.pf = Class.objects.create(name="PF Advanced", instructor=cls.marcus)
        for student in (cls.emma, cls.liam):
            ClassEnrollment.objects.create(class_obj=cls.ld, student=student)
        for student in (cls.emma, cls.zara):
            ClassEnrollment.objects.create(class_obj=cls.pf, student=student)

        cls.recent = make_session(cls.ld, days_ago=5, duration=90)
        cls.old = make_session(cls.ld, days_ago=35)
        cls.cancelled = make_session(cls.ld, days_ago=3, status="cancelled")
        cls.scheduled = make_session(cls.ld, days_ago=-7, status="scheduled")
        cls.pf_recent = make_session(cls.pf, days_ago=4)

    def client_for(self, user):
        """Authenticate with a real token header (not force_authenticate) so
        the request goes through the same path as the frontend."""
        client = APIClient()
        token, _ = Token.objects.get_or_create(user=user)
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client


class SubmitFeedbackTests(FeedbackTestBase):
    def test_student_submits_for_self_by_default(self):
        response = self.client_for(self.emma).post(
            URL, {"session": self.recent.id, **RATINGS, "note": "Great"}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        feedback = SessionFeedback.objects.get()
        self.assertEqual(feedback.student, self.emma)
        self.assertEqual(feedback.created_by, self.emma)
        self.assertEqual(response.data["class_name"], "LD Fundamentals")

    def test_submitter_in_body_is_ignored(self):
        response = self.client_for(self.emma).post(
            URL,
            {"session": self.recent.id, **RATINGS, "created_by": self.james.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SessionFeedback.objects.get().created_by, self.emma)

    def test_parent_submits_for_linked_student(self):
        response = self.client_for(self.james).post(
            URL, {"session": self.recent.id, "student": self.liam.id, **RATINGS}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        feedback = SessionFeedback.objects.get()
        self.assertEqual(feedback.student, self.liam)
        self.assertEqual(feedback.created_by, self.james)

    def test_parent_must_choose_student(self):
        response = self.client_for(self.james).post(
            URL, {"session": self.recent.id, **RATINGS}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("student", response.data)

    def test_parent_cannot_submit_for_unlinked_student(self):
        response = self.client_for(self.priya).post(
            URL, {"session": self.recent.id, "student": self.emma.id, **RATINGS}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(SessionFeedback.objects.exists())

    def test_student_cannot_submit_for_another_student(self):
        response = self.client_for(self.emma).post(
            URL, {"session": self.recent.id, "student": self.liam.id, **RATINGS}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_field_must_be_a_student(self):
        response = self.client_for(self.james).post(
            URL, {"session": self.recent.id, "student": self.sarah.id, **RATINGS}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("student", response.data)

    def test_rejects_non_completed_sessions(self):
        for session in (self.cancelled, self.scheduled):
            response = self.client_for(self.emma).post(
                URL, {"session": session.id, **RATINGS}
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("session", response.data)

    def test_rejects_sessions_older_than_30_days(self):
        response = self.client_for(self.emma).post(
            URL, {"session": self.old.id, **RATINGS}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("session", response.data)

    def test_rejects_session_from_unenrolled_class(self):
        response = self.client_for(self.zara).post(
            URL, {"session": self.recent.id, **RATINGS}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_is_per_student_not_per_submitter(self):
        self.client_for(self.emma).post(URL, {"session": self.recent.id, **RATINGS})
        response = self.client_for(self.james).post(
            URL, {"session": self.recent.id, "student": self.emma.id, **RATINGS}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already been submitted", str(response.data))
        self.assertEqual(SessionFeedback.objects.count(), 1)

    def test_same_session_different_students_is_allowed(self):
        client = self.client_for(self.james)
        for student in (self.emma, self.liam):
            response = client.post(
                URL, {"session": self.recent.id, "student": student.id, **RATINGS}
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_rejects_ratings_out_of_range(self):
        for bad in (0, 6):
            response = self.client_for(self.emma).post(
                URL, {"session": self.recent.id, **RATINGS, "rating_pace": bad}
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("rating_pace", response.data)

    def test_all_ratings_required(self):
        response = self.client_for(self.emma).post(
            URL, {"session": self.recent.id, "rating_clarity": 3}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rating_engagement", response.data)
        self.assertIn("rating_pace", response.data)

    def test_note_max_length(self):
        response = self.client_for(self.emma).post(
            URL, {"session": self.recent.id, **RATINGS, "note": "x" * 501}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("note", response.data)

    def test_instructor_cannot_submit(self):
        response = self.client_for(self.sarah).post(
            URL, {"session": self.recent.id, "student": self.emma.id, **RATINGS}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_database_constraints(self):
        with self.assertRaises(IntegrityError):
            SessionFeedback.objects.create(
                session=self.recent, student=self.emma,
                rating_clarity=6, rating_engagement=3, rating_pace=3,
            )

    def test_database_unique_constraint(self):
        SessionFeedback.objects.create(session=self.recent, student=self.emma, **RATINGS)
        with self.assertRaises(IntegrityError):
            SessionFeedback.objects.create(session=self.recent, student=self.emma, **RATINGS)


class MyFeedbackTests(FeedbackTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.emma_fb = SessionFeedback.objects.create(
            session=cls.recent, student=cls.emma, created_by=cls.emma, **RATINGS
        )
        cls.liam_fb = SessionFeedback.objects.create(
            session=cls.recent, student=cls.liam, created_by=cls.james, **RATINGS
        )

    def test_student_sees_only_their_feedback(self):
        response = self.client_for(self.emma).get(MY_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.emma_fb.id)

    def test_student_sees_feedback_their_parent_submitted(self):
        response = self.client_for(self.liam).get(MY_URL)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["created_by_display"], "James Wilson")

    def test_parent_sees_all_linked_students_newest_first(self):
        response = self.client_for(self.james).get(MY_URL)
        self.assertEqual(response.data["count"], 2)
        ids = [item["id"] for item in response.data["results"]]
        self.assertEqual(ids, [self.liam_fb.id, self.emma_fb.id])

    def test_unlinked_parent_sees_nothing(self):
        response = self.client_for(self.priya).get(MY_URL)
        self.assertEqual(response.data["count"], 0)

    def test_instructor_forbidden(self):
        response = self.client_for(self.sarah).get(MY_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class EligibleSessionsTests(FeedbackTestBase):
    def test_student_gets_completed_recent_unreviewed_enrolled_sessions(self):
        response = self.client_for(self.emma).get(ELIGIBLE_URL)
        ids = {s["id"] for s in response.data["results"]}
        self.assertEqual(ids, {self.recent.id, self.pf_recent.id})

    def test_reviewed_sessions_drop_out(self):
        SessionFeedback.objects.create(session=self.recent, student=self.emma, **RATINGS)
        response = self.client_for(self.emma).get(ELIGIBLE_URL)
        ids = {s["id"] for s in response.data["results"]}
        self.assertEqual(ids, {self.pf_recent.id})
        # Liam's eligibility is unaffected by Emma's review
        response = self.client_for(self.james).get(f"{ELIGIBLE_URL}?student={self.liam.id}")
        self.assertEqual({s["id"] for s in response.data["results"]}, {self.recent.id})

    def test_parent_must_pass_student(self):
        response = self.client_for(self.james).get(ELIGIBLE_URL)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_parent_cannot_query_unlinked_student(self):
        for student_id in (self.emma.id, 99999, "abc"):
            response = self.client_for(self.priya).get(f"{ELIGIBLE_URL}?student={student_id}")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class InstructorSummaryTests(FeedbackTestBase):
    def add_feedback(self, session, student, clarity, engagement=3, pace=3, note=""):
        return SessionFeedback.objects.create(
            session=session, student=student, created_by=student,
            rating_clarity=clarity, rating_engagement=engagement,
            rating_pace=pace, note=note,
        )

    def test_weighted_by_session_duration(self):
        # 90-minute session: clarity avg 4.0 (two responses)
        self.add_feedback(self.recent, self.emma, clarity=5, engagement=4, pace=2)
        self.add_feedback(self.recent, self.liam, clarity=3, engagement=4, pace=4)
        # 60-minute session: clarity avg 3.0
        self.add_feedback(self.old, self.emma, clarity=3, engagement=1, pace=3)

        response = self.client_for(self.sarah).get(SUMMARY_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        averages = response.data["averages"]
        # (90*4 + 60*3) / 150 = 3.6, not the simple per-session mean of 3.5
        # or the per-entry mean of 3.67
        self.assertEqual(averages["clarity"], 3.6)
        self.assertEqual(averages["engagement"], 2.8)  # (90*4 + 60*1) / 150
        self.assertEqual(averages["pace"], 3.0)
        self.assertEqual(averages["overall"], 3.13)    # mean(3.6, 2.8, 3.0)
        self.assertEqual(response.data["total_feedback"], 3)
        self.assertEqual(response.data["sessions_with_feedback"], 2)

    def test_only_last_ten_completed_sessions_count(self):
        oldest = make_session(self.ld, days_ago=200, duration=60)
        for days_ago in range(10, 20):
            session = make_session(self.ld, days_ago=days_ago, duration=60)
            for student in (self.emma, self.liam):
                self.add_feedback(session, student, clarity=4, engagement=4, pace=4)
        # Feedback on a session outside the window must not move the average
        for student in (self.emma, self.liam):
            self.add_feedback(oldest, student, clarity=1, engagement=1, pace=1)
        # self.recent (5 days ago) is also in the window, so 10 sessions =
        # self.recent + the 9 newest generated ones.
        response = self.client_for(self.sarah).get(SUMMARY_URL)
        self.assertEqual(response.data["sessions_in_window"], 10)
        self.assertEqual(response.data["total_feedback"], 18)
        self.assertEqual(response.data["averages"]["overall"], 4.0)

    def test_scopes_to_requesting_instructor(self):
        for student in (self.emma, self.zara):
            self.add_feedback(self.pf_recent, student, clarity=1)
        response = self.client_for(self.sarah).get(SUMMARY_URL)
        self.assertEqual(response.data["total_feedback"], 0)
        self.assertIsNone(response.data["averages"])

    def test_scores_withheld_below_minimum_responses(self):
        self.add_feedback(self.recent, self.emma, clarity=5)
        self.add_feedback(self.recent, self.liam, clarity=1)
        response = self.client_for(self.sarah).get(SUMMARY_URL)
        self.assertEqual(response.data["total_feedback"], 2)
        self.assertIsNone(response.data["averages"])

    def test_sessions_without_duration_are_excluded(self):
        no_duration = make_session(self.ld, days_ago=2, duration=None)
        self.add_feedback(no_duration, self.emma, clarity=1)
        for student, clarity in ((self.emma, 5), (self.liam, 5)):
            self.add_feedback(self.recent, student, clarity=clarity)
        self.add_feedback(self.old, self.emma, clarity=5)
        response = self.client_for(self.sarah).get(SUMMARY_URL)
        self.assertEqual(response.data["total_feedback"], 3)
        self.assertEqual(response.data["averages"]["clarity"], 5.0)

    def test_response_contains_no_identifying_data(self):
        self.add_feedback(self.recent, self.emma, clarity=4, note="SECRET NOTE ONE")
        self.add_feedback(self.recent, self.liam, clarity=4, note="SECRET NOTE TWO")
        self.add_feedback(self.old, self.emma, clarity=4)

        response = self.client_for(self.sarah).get(SUMMARY_URL)
        self.assertEqual(
            set(response.data),
            {
                "instructor_id", "window_size", "sessions_in_window",
                "sessions_with_feedback", "total_feedback",
                "min_feedback_for_scores", "averages",
            },
        )
        self.assertEqual(
            set(response.data["averages"]),
            {"clarity", "engagement", "pace", "overall"},
        )
        raw = json.dumps(response.data)
        for leak in ("SECRET NOTE", "Emma", "Liam", "emma@", "liam@",
                     "student", "submitter", "created_by", "note"):
            self.assertNotIn(leak, raw)

    def test_students_and_parents_forbidden(self):
        for user in (self.emma, self.james):
            response = self.client_for(user).get(SUMMARY_URL)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_instructor_cannot_view_another_instructor(self):
        response = self.client_for(self.sarah).get(f"{SUMMARY_URL}?instructor_id={self.marcus.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_must_pick_an_instructor(self):
        client = self.client_for(self.admin)
        self.assertEqual(client.get(SUMMARY_URL).status_code, status.HTTP_400_BAD_REQUEST)
        response = client.get(f"{SUMMARY_URL}?instructor_id={self.marcus.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["instructor_id"], self.marcus.id)
        for bad in (self.emma.id, 99999, "abc"):
            response = client.get(f"{SUMMARY_URL}?instructor_id={bad}")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
