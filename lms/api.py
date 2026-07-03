from typing import Optional
from functools import wraps

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.utils.timezone import now
from django.core.cache import cache
from django.db import connection
from django.db.models import Count

from ninja import Schema, Body
from ninja.errors import ValidationError as NinjaValidationError
from pydantic import EmailStr

from ninja_extra import NinjaExtraAPI
from ninja_extra.exceptions import (
    APIException,
    PermissionDenied,
    NotFound as ApiNotFound,
    ValidationError as ApiValidationError,
)
from ninja_jwt.controller import NinjaJWTDefaultController
from ninja_jwt.authentication import JWTAuth

from .models import (
    User,
    Course,
    Category,
    Enrollment,
    Lesson,
    Progress,
    Announcement
)

from .mongodb import (
    db as mongo_db,
    activity_logs,
    learning_analytics
)

from .tasks import (
    send_enrollment_email,
    generate_certificate
)

from .responses import success_response, error_response

api = NinjaExtraAPI(
    title="Simple LMS API",
    version="1.0.0"
)

api.register_controllers(
    NinjaJWTDefaultController
)


# ==================================================
# EXCEPTION HANDLERS (Response & Error Format Konsisten)
# ==================================================
# Semua exception yang terjadi di endpoint manapun akan otomatis
# diubah menjadi format JSON yang seragam lewat handler di bawah ini,
# jadi tidak perlu try/except manual di tiap endpoint.

@api.exception_handler(APIException)
def api_exception_handler(request, exc):
    """
    Menangani semua exception dari ninja_extra.exceptions:
    PermissionDenied (403), NotFound (404), ValidationError (400), dll.
    """
    is_structured = isinstance(exc.detail, (list, dict))

    status_code, payload = error_response(
        message="Validasi gagal" if is_structured else str(exc.detail),
        errors=exc.detail if is_structured else None,
        status_code=exc.status_code,
    )
    return api.create_response(request, payload, status=status_code)


@api.exception_handler(Http404)
def http404_exception_handler(request, exc):
    message = str(exc) or "Data tidak ditemukan"

    status_code, payload = error_response(
        message=message,
        status_code=404,
    )
    return api.create_response(request, payload, status=status_code)


@api.exception_handler(NinjaValidationError)
def ninja_validation_exception_handler(request, exc):
    status_code, payload = error_response(
        message="Validasi input gagal",
        errors=exc.errors,
        status_code=422,
    )
    return api.create_response(request, payload, status=status_code)


@api.exception_handler(Exception)
def generic_exception_handler(request, exc):
    status_code, payload = error_response(
        message="Terjadi kesalahan pada server",
        errors=str(exc) if settings.DEBUG else None,
        status_code=500,
    )
    return api.create_response(request, payload, status=status_code)


# ==================================================
# ROLE CHECKERS
# ==================================================

def is_admin(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if request.user.role != "admin":
            raise PermissionDenied("Akses ditolak: khusus admin")
        return func(request, *args, **kwargs)

    return wrapper


def is_instructor(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if request.user.role != "instructor":
            raise PermissionDenied("Akses ditolak: khusus instructor")
        return func(request, *args, **kwargs)

    return wrapper


def is_student(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if request.user.role != "student":
            raise PermissionDenied("Akses ditolak: khusus student")
        return func(request, *args, **kwargs)

    return wrapper


# ==================================================
# SCHEMAS
# ==================================================

class RegisterIn(Schema):
    username: str
    email: EmailStr
    password: str
    role: str = "student"


class UserUpdateIn(Schema):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class CourseIn(Schema):
    title: str
    description: str
    category_id: Optional[int] = None


class CourseOut(Schema):
    id: int
    title: str
    description: str
    instructor_id: int
    category_id: Optional[int] = None


class AnnouncementIn(Schema):
    title: str
    content: str


class AnnouncementUpdateIn(Schema):
    title: Optional[str] = None
    content: Optional[str] = None


# ==================================================
# AUTH
# ==================================================

@api.post(
    "/auth/register",
    tags=["Auth"],
    response={200: dict, 201: dict},
)
def register(request, payload: RegisterIn = Body(...)):

    if User.objects.filter(username=payload.username).exists():
        raise ApiValidationError("Username sudah terdaftar, pakai yang lain!")

    user = User.objects.create_user(
        username=payload.username,
        email=payload.email,
        password=payload.password
    )

    user.role = payload.role
    user.save()

    return success_response(
        data={"id": user.id, "username": user.username, "role": user.role},
        message="User registered successfully",
        status_code=201,
    )


@api.get("/auth/me", auth=JWTAuth(), tags=["Auth"])
def get_me(request):

    return success_response(
        data={
            "id": request.user.id,
            "username": request.user.username,
            "role": request.user.role,
            "email": request.user.email,
        },
        message="Profil berhasil diambil",
    )


@api.put("/auth/me", auth=JWTAuth(), tags=["Auth"])
def update_me(
    request,
    data: UserUpdateIn = Body(...)
):

    user = request.user

    for attr, value in data.dict(exclude_unset=True).items():
        setattr(user, attr, value)

    user.save()

    return success_response(message="Profile updated")


# ==================================================
# COURSES
# ==================================================

def _serialize_course(course: Course) -> dict:
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "instructor_id": course.instructor_id,
        "category_id": course.category_id,
    }


@api.get("/courses", tags=["Courses"])
def list_courses(request):

    cached = cache.get("course_list")

    if cached is not None:
        return success_response(data=cached, message="Daftar course (cache)")

    courses = Course.objects.all()

    data = [
        {
            "id": c.id,
            "title": c.title,
            "description": c.description
        }
        for c in courses
    ]

    cache.set("course_list", data, timeout=300)

    return success_response(data=data, message="Daftar course")


@api.get("/courses/{id}", tags=["Courses"])
def course_detail(request, id: int):

    key = f"course_{id}"

    cached = cache.get(key)

    if cached is not None:
        return success_response(data=cached, message="Detail course (cache)")

    course = get_object_or_404(Course, id=id)

    data = {
        "id": course.id,
        "title": course.title,
        "description": course.description
    }

    cache.set(key, data, timeout=300)

    return success_response(data=data, message="Detail course")


@api.post(
    "/courses",
    auth=JWTAuth(),
    tags=["Courses"],
    response={200: dict, 201: dict},
)
@is_instructor
def create_course(
    request,
    data: CourseIn = Body(...)
):

    course = Course.objects.create(
        instructor=request.user,
        **data.dict()
    )

    cache.delete("course_list")

    return success_response(
        data=_serialize_course(course),
        message="Course created successfully",
        status_code=201,
    )


@api.patch(
    "/courses/{id}",
    auth=JWTAuth(),
    tags=["Courses"]
)
@is_instructor
def update_course(
    request,
    id: int,
    data: CourseIn = Body(...)
):

    course = get_object_or_404(Course, id=id)

    if course.instructor != request.user:
        raise PermissionDenied("Bukan pemilik kursus")

    for attr, value in data.dict(exclude_unset=True).items():
        setattr(course, attr, value)

    course.save()

    cache.delete("course_list")
    cache.delete(f"course_{course.id}")

    return success_response(
        data=_serialize_course(course),
        message="Course updated successfully",
    )


@api.delete(
    "/courses/{id}",
    auth=JWTAuth(),
    tags=["Courses"]
)
@is_admin
def delete_course(request, id: int):

    course = get_object_or_404(Course, id=id)

    cache.delete("course_list")
    cache.delete(f"course_{course.id}")

    course.delete()

    return success_response(message="Course berhasil dihapus")


# ==================================================
# ENROLLMENTS
# ==================================================

@api.post(
    "/enrollments",
    auth=JWTAuth(),
    tags=["Enrollments"],
    response={200: dict, 201: dict},
)
@is_student
def enroll(request, course_id: int):

    course = get_object_or_404(Course, id=course_id)

    enrollment, created = Enrollment.objects.get_or_create(
        student=request.user,
        course=course
    )

    activity_logs.insert_one({
        "user_id": request.user.id,
        "username": request.user.username,
        "course_id": course.id,
        "course_title": course.title,
        "action": "enroll",
        "timestamp": now()
    })

    send_enrollment_email.delay(request.user.email)

    return success_response(
        data={"id": enrollment.id, "created": created},
        message="Enrolled" if created else "Sudah terdaftar sebelumnya",
        status_code=201 if created else 200,
    )


@api.get(
    "/enrollments/my-courses",
    auth=JWTAuth(),
    tags=["Enrollments"]
)
@is_student
def my_courses(request):

    enrollments = Enrollment.objects.filter(
        student=request.user
    ).select_related("course")

    data = [
        {
            "enrollment_id": e.id,
            "course_id": e.course.id,
            "course_title": e.course.title,
            "enrolled_at": e.enrolled_at,
        }
        for e in enrollments
    ]

    return success_response(data=data, message="Daftar course yang diikuti")


@api.post(
    "/enrollments/{lesson_id}/progress",
    auth=JWTAuth(),
    tags=["Enrollments"]
)
@is_student
def mark_progress(
    request,
    lesson_id: int
):

    lesson = get_object_or_404(Lesson, id=lesson_id)

    enrollment = get_object_or_404(
        Enrollment,
        student=request.user,
        course=lesson.course
    )

    progress, created = Progress.objects.update_or_create(
        enrollment=enrollment,
        lesson=lesson,
        defaults={
            "is_completed": True,
            "completed_at": now()
        }
    )

    learning_analytics.insert_one({
        "student_id": request.user.id,
        "student_name": request.user.username,
        "lesson_id": lesson.id,
        "lesson_title": lesson.title,
        "course_id": lesson.course.id,
        "course_title": lesson.course.title,
        "status": "completed",
        "completed_at": now()
    })

    generate_certificate.delay(request.user.id, lesson.course.id)

    return success_response(message="Progress updated")


# ==================================================
# COURSE ANNOUNCEMENTS
# ==================================================

def _serialize_announcement(a: Announcement) -> dict:
    return {
        "id": a.id,
        "course_id": a.course_id,
        "course_title": a.course.title,
        "title": a.title,
        "content": a.content,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


@api.post(
    "/courses/{course_id}/announcements",
    auth=JWTAuth(),
    tags=["Announcements"],
    response={200: dict, 201: dict},
)
@is_instructor
def create_announcement(
    request,
    course_id: int,
    data: AnnouncementIn = Body(...)
):

    course = get_object_or_404(Course, id=course_id)

    if course.instructor != request.user:
        raise PermissionDenied("Bukan pemilik kursus")

    announcement = Announcement.objects.create(
        course=course,
        **data.dict()
    )

    return success_response(
        data=_serialize_announcement(announcement),
        message="Announcement berhasil dibuat",
        status_code=201,
    )


@api.get(
    "/courses/{course_id}/announcements",
    auth=JWTAuth(),
    tags=["Announcements"],
)
def list_announcements(request, course_id: int):

    course = get_object_or_404(Course, id=course_id)
    user = request.user

    is_owner_instructor = (
        user.role == "instructor" and course.instructor_id == user.id
    )
    is_enrolled_student = (
        user.role == "student"
        and Enrollment.objects.filter(student=user, course=course).exists()
    )
    is_admin_user = user.role == "admin"

    if not (is_owner_instructor or is_enrolled_student or is_admin_user):
        raise PermissionDenied(
            "Kamu harus terdaftar di course ini untuk melihat pengumuman"
        )

    announcements = course.announcements.select_related("course").all()

    data = [_serialize_announcement(a) for a in announcements]

    return success_response(data=data, message="Daftar pengumuman course")


@api.patch(
    "/announcements/{id}",
    auth=JWTAuth(),
    tags=["Announcements"],
)
@is_instructor
def update_announcement(
    request,
    id: int,
    data: AnnouncementUpdateIn = Body(...)
):

    announcement = get_object_or_404(Announcement, id=id)

    if announcement.course.instructor != request.user:
        raise PermissionDenied("Bukan pemilik kursus")

    for attr, value in data.dict(exclude_unset=True).items():
        setattr(announcement, attr, value)

    announcement.save()

    return success_response(
        data=_serialize_announcement(announcement),
        message="Announcement berhasil diperbarui",
    )


@api.delete(
    "/announcements/{id}",
    auth=JWTAuth(),
    tags=["Announcements"],
)
@is_instructor
def delete_announcement(request, id: int):

    announcement = get_object_or_404(Announcement, id=id)

    if announcement.course.instructor != request.user:
        raise PermissionDenied("Bukan pemilik kursus")

    announcement.delete()

    return success_response(message="Announcement berhasil dihapus")


# ==================================================
# STUDENT DASHBOARD
# ==================================================

@api.get(
    "/dashboard/student",
    auth=JWTAuth(),
    tags=["Dashboard"],
)
@is_student
def student_dashboard(request):

    student = request.user

    enrollments = Enrollment.objects.filter(
        student=student
    ).for_student_dashboard()

    active_courses = []
    completed_courses = []
    enrolled_category_ids = set()
    enrolled_course_ids = []

    for e in enrollments:
        enrolled_course_ids.append(e.course_id)

        total_lessons = e.course.lessons.count()
        completed_lessons = e.progress_records.filter(is_completed=True).count()
        progress_percent = (
            round((completed_lessons / total_lessons) * 100, 1)
            if total_lessons else 0
        )

        course_data = {
            "course_id": e.course.id,
            "course_title": e.course.title,
            "total_lessons": total_lessons,
            "completed_lessons": completed_lessons,
            "progress_percent": progress_percent,
            "enrolled_at": e.enrolled_at,
        }

        if e.course.category_id:
            enrolled_category_ids.add(e.course.category_id)

        if total_lessons > 0 and completed_lessons == total_lessons:
            completed_courses.append(course_data)
        else:
            active_courses.append(course_data)

    recommendations_qs = Course.objects.filter(
        category_id__in=enrolled_category_ids
    ).exclude(id__in=enrolled_course_ids)[:5]

    recommendations = [
        {
            "course_id": c.id,
            "title": c.title,
            "category_id": c.category_id
        }
        for c in recommendations_qs
    ]

    recent_announcements_qs = Announcement.objects.filter(
        course_id__in=enrolled_course_ids
    ).select_related("course").order_by("-created_at")[:5]

    recent_announcements = [
        {
            "id": a.id,
            "course_id": a.course_id,
            "course_title": a.course.title,
            "title": a.title,
            "created_at": a.created_at,
        }
        for a in recent_announcements_qs
    ]

    return success_response(
        data={
            "total_enrolled": len(enrolled_course_ids),
            "active_courses": active_courses,
            "completed_courses": completed_courses,
            "recommendations": recommendations,
            "recent_announcements": recent_announcements,
        },
        message="Student dashboard",
    )


# ==================================================
# INSTRUCTOR DASHBOARD
# ==================================================

@api.get(
    "/dashboard/instructor",
    auth=JWTAuth(),
    tags=["Dashboard"],
)
@is_instructor
def instructor_dashboard(request):

    instructor = request.user

    courses = Course.objects.filter(instructor=instructor).annotate(
        total_enrollment=Count("enrollments", distinct=True),
        total_lessons_count=Count("lessons", distinct=True),
    )

    course_stats = []
    total_enrollment_all = 0
    most_popular = None

    for c in courses:
        total_enrollment_all += c.total_enrollment

        completed_progress_count = Progress.objects.filter(
            enrollment__course=c,
            is_completed=True
        ).count()

        course_stats.append({
            "course_id": c.id,
            "title": c.title,
            "total_enrollment": c.total_enrollment,
            "total_lessons": c.total_lessons_count,
            "total_completed_lesson_progress": completed_progress_count,
        })

        if most_popular is None or c.total_enrollment > most_popular["total_enrollment"]:
            most_popular = {
                "course_id": c.id,
                "title": c.title,
                "total_enrollment": c.total_enrollment
            }

    total_announcements = Announcement.objects.filter(
        course__instructor=instructor
    ).count()

    return success_response(
        data={
            "total_courses": courses.count(),
            "total_enrollment": total_enrollment_all,
            "most_popular_course": most_popular,
            "total_announcements": total_announcements,
            "courses": course_stats,
        },
        message="Instructor dashboard",
    )


# ==================================================
# ANALYTICS
# ==================================================

@api.get(
    "/analytics/report",
    auth=JWTAuth(),
    tags=["Analytics"]
)
@is_admin
def analytics_report(request):

    pipeline = [
        {
            "$group": {
                "_id": "$course_id",
                "total_completed": {"$sum": 1}
            }
        }
    ]

    result = list(learning_analytics.aggregate(pipeline))

    return success_response(data=result, message="Analytics report")


# ==================================================
# SYSTEM: HEALTH CHECK & API CHANGELOG
# ==================================================

@api.get("/health", tags=["System"])
def health_check(request):
    """
    Mengecek status koneksi ke Database (PostgreSQL), Cache (Redis),
    dan MongoDB. Berguna untuk memastikan semua service pendukung
    benar-benar hidup, terutama setelah deploy atau restart Docker Compose.
    """

    services = {}

    # --- Database (PostgreSQL) ---
    try:
        connection.ensure_connection()
        services["database"] = "up"
    except Exception as e:
        services["database"] = f"down ({e.__class__.__name__})"

    # --- Cache (Redis) ---
    try:
        cache.set("health_check_ping", "pong", timeout=5)
        services["redis"] = "up" if cache.get("health_check_ping") == "pong" else "down"
    except Exception as e:
        services["redis"] = f"down ({e.__class__.__name__})"

    # --- MongoDB ---
    try:
        mongo_db.command("ping")
        services["mongodb"] = "up"
    except Exception as e:
        services["mongodb"] = f"down ({e.__class__.__name__})"

    is_healthy = all(status == "up" for status in services.values())

    status_code, payload = success_response(
        data={
            "status": "healthy" if is_healthy else "unhealthy",
            "timestamp": now(),
            "services": services,
        },
        message="Health check berhasil" if is_healthy else "Ada service yang bermasalah",
        status_code=200 if is_healthy else 503,
    )
    return api.create_response(request, payload, status=status_code)


API_CHANGELOG = [
    {
        "version": "1.1.0",
        "date": "2026-07-01",
        "changes": [
            "Menambahkan format response dan error yang konsisten di seluruh endpoint",
            "Menambahkan endpoint health check (/health) untuk memantau status Database, Redis, dan MongoDB",
            "Menambahkan endpoint API changelog (/changelog)",
        ],
    },
    {
        "version": "1.0.0",
        "date": "2026-06-01",
        "changes": [
            "Rilis awal Simple LMS API",
            "Autentikasi JWT (register, login, refresh)",
            "Role-based access control: admin, instructor, student",
            "Endpoint course, enrollment, dan progress",
            "Integrasi caching Redis untuk course list/detail",
            "Activity logging dan learning analytics ke MongoDB",
            "Background task via Celery (email notifikasi, generate certificate)",
        ],
    },
]


@api.get("/changelog", tags=["System"])
def api_changelog(request):
    """
    Menampilkan riwayat perubahan API per versi, supaya frontend/klien
    tahu apa yang berubah di tiap rilis.
    """
    return success_response(data=API_CHANGELOG, message="API changelog")