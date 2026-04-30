from typing import List, Optional
from django.shortcuts import get_object_or_404
from django.http import HttpResponseForbidden
from django.utils.timezone import now
from ninja import Schema, Query, Body
from ninja.pagination import paginate, PageNumberPagination
from pydantic import EmailStr
from ninja_extra import NinjaExtraAPI
from ninja_jwt.controller import NinjaJWTDefaultController
from ninja_jwt.authentication import JWTAuth
from functools import wraps

from .models import User, Course, Category, Enrollment, Lesson, Progress

api = NinjaExtraAPI(title="Simple LMS API", version="1.0.0")


api.register_controllers(NinjaJWTDefaultController) 



def is_admin(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'admin':
            return HttpResponseForbidden("Akses Ditolak: Khusus Admin")
        return func(request, *args, **kwargs)
    return wrapper

def is_instructor(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'instructor':
            return HttpResponseForbidden("Akses Ditolak: Khusus Instructor")
        return func(request, *args, **kwargs)
    return wrapper

def is_student(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'student':
            return HttpResponseForbidden("Akses Ditolak: Khusus Student")
        return func(request, *args, **kwargs)
    return wrapper



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

class CourseFilter(Schema):
    search: Optional[str] = None




@api.post("/auth/register", tags=["Auth"])
def register(request, payload: RegisterIn = Body(...)):

    if User.objects.filter(username=payload.username).exists():
        return {"error": "Username sudah terdaftar, pakai yang lain!"}


    user = User.objects.create_user(
        username=payload.username,
        email=payload.email,
        password=payload.password
    )
    user.role = payload.role  
    user.save()
    return {"message": "User registered successfully", "id": user.id}

@api.get("/auth/me", auth=JWTAuth(), tags=["Auth"])
def get_me(request):
    return {
        "id": request.user.id,
        "username": request.user.username, 
        "role": request.user.role, 
        "email": request.user.email
    }

@api.put("/auth/me", auth=JWTAuth(), tags=["Auth"])
def update_me(request, data: UserUpdateIn = Body(...)): 
    user = request.user
    for attr, value in data.dict(exclude_unset=True).items():
        setattr(user, attr, value)
    user.save()
    return {"message": "Profile updated"}

# [COURSES] Public
@api.get("/courses", response=List[CourseOut], tags=["Courses"])
@paginate(PageNumberPagination, page_size=10)
def list_courses(request, filters: CourseFilter = Query(...)):
    qs = Course.objects.all()
    if filters.search:
        qs = qs.filter(title__icontains=filters.search)
    return qs

@api.get("/courses/{id}", response=CourseOut, tags=["Courses"])
def course_detail(request, id: int):
    return get_object_or_404(Course, id=id)


@api.post("/courses", auth=JWTAuth(), tags=["Courses"])
@is_instructor
def create_course(request, data: CourseIn = Body(...)): 
    course = Course.objects.create(instructor=request.user, **data.dict())
    return course

@api.patch("/courses/{id}", auth=JWTAuth(), tags=["Courses"])
@is_instructor
def update_course(request, id: int, data: CourseIn = Body(...)): 
    course = get_object_or_404(Course, id=id)
    if course.instructor != request.user:
        return HttpResponseForbidden("Bukan pemilik kursus")
    for attr, value in data.dict(exclude_unset=True).items():
        setattr(course, attr, value)
    course.save()
    return course

@api.delete("/courses/{id}", auth=JWTAuth(), tags=["Courses"])
@is_admin
def delete_course(request, id: int):
    course = get_object_or_404(Course, id=id)
    course.delete()
    return {"success": True}

# [ENROLLMENTS]
@api.post("/enrollments", auth=JWTAuth(), tags=["Enrollments"])
@is_student
def enroll(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    enrollment, created = Enrollment.objects.get_or_create(student=request.user, course=course)
    return {"message": "Enrolled", "id": enrollment.id, "created": created}

@api.get("/enrollments/my-courses", auth=JWTAuth(), tags=["Enrollments"])
@is_student
def my_courses(request):
    return Enrollment.objects.filter(student=request.user).select_related('course')

@api.post("/enrollments/{lesson_id}/progress", auth=JWTAuth(), tags=["Enrollments"])
@is_student
def mark_progress(request, lesson_id: int):
    lesson = get_object_or_404(Lesson, id=lesson_id)
    enrollment = get_object_or_404(Enrollment, student=request.user, course=lesson.course)
    Progress.objects.update_or_create(
        enrollment=enrollment, 
        lesson=lesson, 
        defaults={"is_completed": True, "completed_at": now()}
    )
    return {"message": "Progress updated"}