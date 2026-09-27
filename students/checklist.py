"""
The first-week checklist on an admin's home page: the first things a new
school does in HouseMaster, with a few steps of its own for each education
system. Each step ticks itself once the school has actually done it.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Invite, Profile, TeachingAssignment
from accounts.permissions import HasSchoolProfile, IsSchoolAdmin
from attendance.models import AttendanceRecord
from communications.models import Announcement
from gradebook.models import AssessmentType, Grade, StudentSubject, Subject, SubjectReport
from guardians.models import Guardian, GuardianInvite

from .models import Student, YearGroup
from .presets import SYSTEMS, school_vocab


def _step(key, title, detail, done, tab):
    return {"key": key, "title": title, "detail": detail, "done": bool(done), "tab": tab}


def _year_groups(school, *prefixes):
    return YearGroup.objects.filter(school=school, name__iregex=r"^(%s)" % "|".join(prefixes)).exists()


def _system_steps(school, words):
    """The steps that belong to the school's own education system."""
    system = school.education_system
    subjects = words["subjects"].lower()
    choices = StudentSubject.objects.filter(student__school=school)
    weighted = AssessmentType.objects.filter(school=school).exists()
    if system == "cbc":
        steps = [_step("cbc_assessments", "Check formative and summative weights",
                       "Decide how classwork and end-of-term assessments count towards each learning area's level.",
                       weighted, "setup")]
        if _year_groups(school, "Grade 10", "Grade 11", "Grade 12"):
            steps.append(_step("cbc_pathways", "Set senior school pathways",
                               "Record each senior student's pathway (STEM, Social Sciences, or Arts and Sports "
                               "Science) under Subject choices.",
                               Student.objects.filter(school=school).exclude(pathway="").exists(), "students"))
        steps.append(_step("cbc_competencies", "Rate core competencies and values",
                           "On each learner's report, rate the core competencies and values from EE to BE.",
                           school.students.filter(reports__extra__has_key="competencies").exists(), "reports"))
        return steps
    if system == "844":
        return [
            _step("844_assessments", "Set up CATs and end-term exams",
                  "Check the weights for CATs and the end-term exam, so mean grades and points come out right.",
                  weighted, "setup"),
            _step("844_electives", "Choose Form 3 and 4 subjects",
                  "Mark the optional subjects as electives and record which ones each student takes.",
                  choices.exists(), "students"),
        ]
    if system == "british":
        return [
            _step("british_options", "Set GCSE and IGCSE options",
                  f"Mark optional {subjects} as electives and record each student's option choices.",
                  choices.exists(), "students"),
            _step("british_targets", "Set target grades",
                  "Give students a target grade (and an effort grade) in each subject for their report cards.",
                  SubjectReport.objects.filter(student__school=school).exclude(target="").exists(), "grades"),
        ]
    if system == "ib":
        steps = []
        if _year_groups(school, "DP"):
            steps.append(_step("ib_levels", "Set Diploma HL and SL choices",
                               "Record which subjects each Diploma student takes at Higher and Standard Level.",
                               choices.exclude(level="").exists(), "students"))
        if _year_groups(school, "MYP") or not steps:
            steps.append(_step("ib_criteria", "Assess the MYP criteria",
                               "Enter criteria A to D (out of 8) for each subject; the 1 to 7 grade follows from them.",
                               SubjectReport.objects.filter(student__school=school).exclude(criteria={}).exists(),
                               "grades"))
        steps.append(_step("ib_atl", "Rate approaches to learning",
                           "On each student's report, rate the five ATL skill categories.",
                           school.students.filter(reports__extra__has_key="atl").exists(), "reports"))
        return steps
    if system == "american":
        return [
            _step("american_credits", "Set course credits",
                  "Give each course its credits (e.g. 0.5 for a one-semester course) so GPAs are weighted correctly.",
                  Subject.objects.filter(school=school).exclude(credits=1).exists(), "setup"),
            _step("american_electives", "Record elective choices",
                  "Mark electives and record which ones each student takes.", choices.exists(), "students"),
        ]
    return []


def checklist(school):
    words = school_vocab(school)
    classes = words["classes"].lower()
    common = [
        _step("invite_staff", "Invite your teachers",
              "Invite staff one at a time or from an Excel sheet on the Staff page.",
              Profile.objects.filter(school=school, role="teacher").exists()
              or Invite.objects.filter(school=school).exists(), "staff"),
        _step("assign_classes", f"Give teachers their {classes} and {words['subjects'].lower()}",
              f"Each teacher sees only the {classes} and {words['subjects'].lower()} they're given.",
              TeachingAssignment.objects.filter(teacher__school=school).exists(), "staff"),
        _step("add_students", "Add your students",
              "Add them by hand or import a class list from Excel in Setup.",
              Student.objects.filter(school=school).exists(), "setup"),
        _step("invite_parents", "Invite parents",
              "Share a sign-up link with each class, or invite parents one by one.",
              Guardian.objects.filter(school=school).exists()
              or GuardianInvite.objects.filter(school=school).exists()
              or school.signup_links.exists(), "parents"),
        _step("attendance", "Take the first register", f"Mark attendance for a {words['class'].lower()}.",
              AttendanceRecord.objects.filter(student__school=school).exists(), "attendance"),
        _step("marks", "Record the first marks",
              "Enter marks for an assessment; results and levels update as you go.",
              Grade.objects.filter(student__school=school).exists(), "grades"),
    ]
    welcome = _step("announcement", "Send parents a welcome message",
                    "Tell parents the school is now on HouseMaster and how to log in.",
                    Announcement.objects.filter(school=school, status="published").exists(), "announcements")
    steps = common + _system_steps(school, words) + [welcome]
    system = SYSTEMS.get(school.education_system)
    return {
        "system": system["name"] if system else "",
        "hidden": school.checklist_hidden,
        "steps": steps,
        "done": sum(s["done"] for s in steps),
        "total": len(steps),
    }


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def first_week_checklist(request):
    """GET: the checklist for the admin's school. PATCH {hidden: bool}: hide or show it on the home page."""
    school = request.user.profile.school
    if request.method == "PATCH":
        hidden = request.data.get("hidden")
        if not isinstance(hidden, bool):
            raise ValidationError({"hidden": "Send true or false."})
        school.checklist_hidden = hidden
        school.save(update_fields=["checklist_hidden"])
    return Response(checklist(school))
