from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Count


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        INSTRUCTOR = "instructor", "Instructor"
        STUDENT = "student", "Student"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)

    def __str__(self):
        return f"{self.username} ({self.role})"


class Category(models.Model):
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children"
    )

    def __str__(self):
        return self.name


class CourseQuerySet(models.QuerySet):
    def for_listing(self):
        return self.select_related("instructor", "category").annotate(
            total_lessons=Count("lessons")
        )


class Course(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    instructor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="courses",
        limit_choices_to={"role": "instructor"}
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        related_name="courses"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CourseQuerySet.as_manager()

    def __str__(self):
        return self.title


class Lesson(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="lessons"
    )
    title = models.CharField(max_length=200)
    content = models.TextField()
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order"]
        unique_together = ["course", "order"]

    def __str__(self):
        return f"{self.course.title} - {self.title}"


class EnrollmentQuerySet(models.QuerySet):
    def for_student_dashboard(self):
        return self.select_related("student", "course").prefetch_related(
            "course__lessons",
            "progress_records",
        )


class Enrollment(models.Model):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="enrollments",
        limit_choices_to={"role": "student"}
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments"
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)

    objects = EnrollmentQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"],
                name="unique_student_course_enrollment"
            )
        ]

    def __str__(self):
        return f"{self.student.username} -> {self.course.title}"


class Progress(models.Model):
    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.CASCADE,
        related_name="progress_records"
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="progress_records"
    )
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "lesson"],
                name="unique_progress_per_lesson"
            )
        ]

    def __str__(self):
        return f"{self.enrollment.student.username} - {self.lesson.title}"