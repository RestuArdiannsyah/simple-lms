from django.db import connection, reset_queries
from .models import Course, Enrollment


def n_plus_one_demo():
    reset_queries()

    courses = Course.objects.all()
    for course in courses:
        print(course.instructor.username)

    print("N+1 Query Count:", len(connection.queries))


def optimized_demo():
    reset_queries()

    courses = Course.objects.for_listing()
    for course in courses:
        print(course.instructor.username)

    print("Optimized Query Count:", len(connection.queries))


def student_dashboard_demo(student_id):
    reset_queries()

    enrollments = Enrollment.objects.for_student_dashboard().filter(
        student_id=student_id
    )

    for enrollment in enrollments:
        print(enrollment.course.title)
        for lesson in enrollment.course.lessons.all():
            print(" -", lesson.title)

    print("Dashboard Query Count:", len(connection.queries))