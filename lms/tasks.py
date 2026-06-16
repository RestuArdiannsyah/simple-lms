from celery import shared_task

@shared_task
def send_enrollment_email(email):

    print(f"Enrollment email sent to {email}")

    return True


@shared_task
def generate_certificate(user_id, course_id):

    print(
        f"Generate certificate {user_id} {course_id}"
    )

    return True


@shared_task
def update_course_statistics():

    print("Updating statistics")

    return True


@shared_task
def export_course_report():

    print("Generating report")

    return True