# Design Decisions: Session Feedback

## Data model

`feedback.SessionFeedback`:

| Field | Type | Why |
|---|---|---|
| `session` | FK → `Session` (CASCADE) | Feedback is about one session. If the session goes, its feedback goes. |
| `student` | FK → `User`, `limit_choices_to={"role": "student"}` (CASCADE) | **Who the feedback represents.** The serializer only accepts IDs of users whose role is `student`. |
| `created_by` | FK → `User` (SET_NULL, nullable) | **The submitter**: the student or a linked parent. |
| `rating_clarity` / `rating_engagement` / `rating_pace` | `PositiveSmallIntegerField` + Min/Max validators (1-5) | Three separate columns, so each dimension can be aggregated on its own in SQL. |
| `note` | `CharField(max_length=500, blank=True)` | Optional. The length is enforced by the DB and by DRF. |
| `created_at` / `updated_at` | auto timestamps | Same as every other model in the project. |

**Why the submitter is `created_by`.** `created_by` is already the project's audit field (see `Class.created_by`). `BaseModelSerializer.create()` fills it from the request user through the audit middleware. Naming the submitter `created_by` means it gets set by that existing mechanism, and the client can never write it: it isn't in the serializer's `fields`, so a `created_by` in the request body is ignored. (A test covers this.) The API shows it as `created_by_display`, which follows the base class convention. I chose `SET_NULL` so that deleting a parent's account doesn't delete reviews that belong to the child.

**Why `student` and `submitter` are separate.** Feedback belongs to the student even when a parent types it in. History and uniqueness are keyed on the student, and the submitter is kept only as audit information.

**Uniqueness is `unique_together = ("session", "student")`**, not `(session, submitter)`. A student has one opinion per session. If the parent and the student could each submit, that session would count twice in the instructor's average.

**Defence in depth.** The 1-5 range is enforced in three places: by the DRF field validators, by the model validators (admin/`full_clean`), and by DB `CheckConstraint`s. Uniqueness is enforced both in `validate()`, with a friendly message, and by the DB constraint. `create()` catches the `IntegrityError` from a concurrent duplicate and returns the same 400.

## A bug I found in `core` and fixed

`RequestAuditMiddleware` stored `request.user` when the middleware ran. DRF authenticates `TokenAuthentication` later, inside the view. So for every API request from the frontend, `get_current_user()` returned `AnonymousUser`, and `BaseModelSerializer.create()` silently never set `created_by`. I confirmed this with a probe view.

The fix (`core/middleware.py`): the middleware now stores the *request*, and `get_current_user()` reads `request.user` when it is called. DRF's `Request.user` setter writes the authenticated user back onto the underlying `HttpRequest`, so by the time a serializer runs, the right user is there. The fix is small, keeps the same public API, and doesn't affect existing tests.

The feedback tests authenticate with a real `Authorization: Token …` header instead of `force_authenticate`, so they go through the same path as the frontend and would catch a regression.

## Validation (all server-side, in `SessionFeedbackSerializer.validate`)

Checks run in this order:

1. **Who.** If `student` is omitted, a student defaults to themselves and a parent gets a 400 ("Select which student…"). `can_submit_for(user, student)` checks that the user is that student, or is a parent with a `FamilyLink` to them. Anything else is a **403**: it's an authorization failure, not bad input.
2. `session.status == completed`.
3. The session is within **30 days**. There is no `completed_at` column, so `scheduled_date` stands in for the completion date.
4. The student is actively enrolled in the session's class. The spec doesn't list this rule, but without it a student could review any completed session in the academy, and those reviews would skew another instructor's scores.
5. No existing `(session, student)` row.

DRF would normally add a `UniqueTogetherValidator` for (session, student). That validator makes `student` required and runs before the "default to self" logic, so I disabled it (`Meta.validators = []`) and handle duplicates in step 5.

The same rules are exposed as a query, `eligible_sessions_for(student)` in `feedback/models.py`, and used by `GET /feedback/eligible-sessions/`. The form therefore only offers sessions the POST will accept, and there's one definition of "eligible" instead of a copy in the frontend.

## API

| Endpoint | Permission | Notes |
|---|---|---|
| `POST /api/v1/feedback/` | `IsStudentOrParent` | Generic `CreateAPIView`; all rules live in the serializer. |
| `GET /api/v1/feedback/my/` | `IsStudentOrParent` | Student: feedback *about* them, including anything a parent submitted for them, so their history and eligibility list agree. Parent: all linked students. Newest first; paginated by the project's `StandardPagination`. |
| `GET /api/v1/feedback/eligible-sessions/` | `IsStudentOrParent` | Parents pass `?student=<id>`. Unknown and unlinked IDs both return the same 403, so the endpoint can't be used to probe for student IDs. |
| `GET /api/v1/feedback/instructor-summary/` | `IsInstructorOrAdmin` | Instructors always get their own summary; passing another instructor's ID returns 403. Admins must pass `?instructor_id=` (missing → 400, not an instructor → 404). |

The views follow the patterns in `classes/views.py`: generic views, role branching in `get_queryset`, `FamilyLink` lookups for parents, and permissions from `core.permissions`.

## Anonymization

The instructor endpoint has **its own serializer** (`InstructorSummarySerializer`). It is a plain `Serializer` that lists the fields it returns explicitly, and every one of them is a count or an average:

```json
{"instructor_id": 2, "window_size": 10, "sessions_in_window": 10,
 "sessions_with_feedback": 2, "total_feedback": 3, "min_feedback_for_scores": 3,
 "averages": {"clarity": 3.91, "engagement": 4.45, "pace": 4.18, "overall": 4.18}}
```

- **No path to identity.** The view never serializes a `SessionFeedback` row. `summary.py` runs a `Session` query with `Avg`/`Count` annotations, and only the numbers leave that function. There are no student, submitter or note fields, and no per-row data.
- **Not `BaseModelSerializer`.** This is the one place I deliberately didn't use the base class. There's no model instance to serialize, and the base class would add `created_by_display`, which is an identity field.
- **No per-session breakdown.** Per-session averages would identify the only student who reviewed a given session, so the response is a single rolled-up number per dimension.
- **Minimum response threshold.** If fewer than 3 feedback entries fall in the window, `averages` is `null` and only the count is returned. With 1-2 responses an instructor can usually tell who wrote them, and the "average" is just that person's ratings. The UI explains why the scores are hidden.
- **Enforced at the API, not the UI.** `test_response_contains_no_identifying_data` checks the exact key set. It also dumps the raw JSON and asserts that no student name, email, note text, `student`, `submitter` or `note` string appears in it.

## Weighted rolling average (`feedback/summary.py`)

1. **Window.** Take the instructor's 10 most recent `completed` sessions across all their classes, ordered by `-scheduled_date`. Sessions with no feedback stay in the window but contribute nothing. This makes the window a true rolling "last 10 sessions": old feedback ages out even if recent sessions weren't reviewed.
2. **Per session**, one query annotates `feedback_count` and `Avg` of each rating.
3. **Weight** each session by `session_metadata["duration_minutes"]`:
   `weighted_avg_d = Σ(duration_i × avg_i,d) / Σ(duration_i)`
   This weights *sessions*, not individual entries. For example, a 90-minute session averaging 4.0 and a 60-minute session averaging 3.0 give (360 + 180) / 150 = **3.6**, not 3.5. A unit test asserts exactly this case.
4. **Overall** is the mean of the three dimension averages. Because all three use the same weights, this equals the duration-weighted average of each session's mean score.
5. **Duration is read from `session_metadata` directly**, not through `Session.duration_minutes`, whose fallback is 60. A session with a missing or invalid duration is left out of both the scores and `total_feedback`, rather than being weighted by an invented number. The seed data always has a duration, so this only matters for bad data.

The aggregation runs in the database. Python only does the weighting over at most 10 rows.

## Frontend

- `StudentFeedbackSection` (students and parents) owns the history state and renders two `DashboardCard`s: `FeedbackFormCard` and `FeedbackHistoryCard`.
- **Optimistic UI.** On submit, the entry goes straight into history (shown as "Saving…" with a negative temporary ID), the session leaves the eligible list, and the form resets. If the request fails, the entry is removed, the session and the draft (ratings and note) are restored, the server's error messages are shown, and the eligible list is re-fetched from the server. The re-fetch matters for the duplicate case, where someone else already reviewed the session.
- Eligible sessions are cached **per student**. If a parent switches child while a request is in flight, a rollback still restores the session to the right child's list.
- Parents pick a child from a dropdown, pre-selected if they have only one. History is grouped by student.
- `getErrorMessages()` in `lib/api.ts` flattens DRF error bodies (`detail`, `non_field_errors`, per-field errors).
- `InstructorFeedbackSummaryCard` (instructors and admins) shows the overall score, a bar per dimension, the response count, and an "Aggregated & anonymized" label. Admins get an instructor picker, built from the existing `/classes/` endpoint.
- Roles are checked in `dashboard/page.tsx`, following the existing pattern. The backend enforces every rule anyway.

## Trade-offs and what I'd do with more time

- **Feedback can't be edited or deleted.** That wasn't in scope, and editing makes the anonymity story more complicated.
- **The threshold doesn't stop differencing.** An instructor who checks the summary before and after a single new response can still estimate that response. Fixing this properly needs scores published in batches, or differential-privacy noise. A fixed k = 3 is the pragmatic step for one day of work.
- **`scheduled_date` stands in for the completion time.** The 30-day window and the "last 10" ordering would be more accurate with a real `completed_at` set when the status changes.
- **History loads one page** (`?page_size=100`) instead of paginating in the UI. That's fine at this scale.
- **I didn't add a separate Feedback page or sidebar entry.** The spec asks for dashboard cards.
- **The `core` middleware change** touches shared code. I kept it minimal and documented it above, because the base class's main feature (`created_by` auto-population) didn't work for token-authenticated requests without it.

## Running it

```bash
cd backend && python -m venv venv && venv\Scripts\activate   # or source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate && python manage.py seed_data
python manage.py test          # 49 tests: 13 existing + 36 feedback
python manage.py runserver

cd frontend && npm install && npm run dev
```
