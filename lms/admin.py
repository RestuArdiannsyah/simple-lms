from django.contrib import admin
from .models import User, Category, Course, Lesson, Enrollment, Progress


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 1


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("username", "email")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent")
    search_fields = ("name",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "instructor", "category", "created_at")
    list_filter = ("category",)
    search_fields = ("title", "description")
    inlines = [LessonInline]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "enrolled_at")
    list_filter = ("course",)
    search_fields = ("student__username", "course__title")


@admin.register(Progress)
class ProgressAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "lesson", "is_completed")
    list_filter = ("is_completed",)