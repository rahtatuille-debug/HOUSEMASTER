"""
Create "HouseMaster Demo Academy": a complete, realistic CBC school for demos,
and one smaller demo school for each other system (8-4-4, British, IB and
American; see students/demo_systems.py).

It fills every part of the app: staff, teaching assignments, about 150
students over three year groups, parents, three terms of grades (the
current term partly graded), recent attendance, reports at every stage,
announcements, messages, an urgent alert, an approval request, invites,
a locked term and activity history.

Safe to run on every deploy (e.g. in Render's build command): it creates any
demo school that is missing and leaves the others alone, unless --reset is
given, which deletes and rebuilds the demo schools and their demo accounts only.

Demo logins all end in @housemaster-demo.example (a reserved domain, so no
email ever reaches a real person) and share the password in the
DEMO_PASSWORD environment variable. Without DEMO_PASSWORD it skips, so no
password is ever stored in the code.

It refuses to create anything when DEBUG is off (production) unless
ALLOW_DEMO_SEED=1 is set, for a server that exists only for demos: shared
demo logins must never appear on a server holding real schools. Refusing
exits normally, so a build command that runs this keeps working. The
password is never printed.

Usage:
  DEMO_PASSWORD=... python manage.py seed_demo_school [--reset]
"""
import os
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Invite, Profile, TeachingAssignment
from activity.services import log_activity
from approvals.models import ChangeRequest
from attendance.models import AttendanceRecord
from communications.models import AlertRecipient, Announcement, UrgentAlert
from gradebook.models import AssessmentType, Grade, Subject, SubjectReport, Term
from gradebook.systems import REPORT_EXTRAS
from guardians.models import Guardian, GuardianInvite
from messaging.models import Conversation, ConversationParticipant, Message
from reporting.models import StudentReport
from students.models import School, SchoolClass, Student, YearGroup

SCHOOL_NAME = "HouseMaster Demo Academy"
DOMAIN = "housemaster-demo.example"

FIRST_F = ["Achieng", "Wanjiru", "Amina", "Njeri", "Akinyi", "Wambui", "Nyambura", "Chebet", "Faith", "Mercy",
           "Imani", "Zawadi", "Neema", "Mumbua", "Atieno", "Nekesa", "Jebet", "Halima", "Grace", "Joy",
           "Wairimu", "Makena", "Kerubo", "Adhiambo", "Esther", "Mwikali", "Nafula", "Saida", "Tabitha", "Awino"]
FIRST_M = ["Otieno", "Kamau", "Mwangi", "Kiprono", "Omondi", "Mutua", "Baraka", "Brian", "Kevin", "Juma",
           "Kipchoge", "Wafula", "Onyango", "Njoroge", "Hassan", "Ochieng", "Kiptoo", "Musyoka", "Daniel", "Ian",
           "Mugo", "Wekesa", "Odhiambo", "Kimani", "Said", "Barasa", "Kibet", "Maina", "Victor", "Collins"]
LAST = ["Otieno", "Kamau", "Wanjiku", "Mwangi", "Ochieng", "Njoroge", "Kiprotich", "Achieng", "Mutua", "Wafula",
        "Omondi", "Kariuki", "Chelimo", "Mohamed", "Nyaga", "Oduya", "Kibet", "Wambua", "Owino", "Karanja",
        "Maina", "Rotich", "Makau", "Ndungu", "Barasa", "Kiplagat", "Muriuki", "Onyango", "Gitau", "Akinyi"]
HOUSES = ["Kilimanjaro", "Kenya", "Elgon", "Aberdare"]
SUBJECTS = ["Mathematics", "English", "Kiswahili", "Integrated Science", "Social Studies",
            "Pre-Technical Studies", "Agriculture"]
STAFF = [  # name, role, email local part, teaches [(class, subject or None for whole class)]
    ("Grace Wambui", "admin", "principal", []),
    ("Peter Otieno", "admin", "deputy", []),
    ("Mary Njeri", "teacher", "m.njeri", [("7 East", None), ("7 West", "Mathematics"), ("8 East", "Mathematics")]),
    ("John Kiprono", "teacher", "j.kiprono", [("7 West", None), ("7 East", "Integrated Science"), ("8 West", "Integrated Science")]),
    ("Esther Achieng", "teacher", "e.achieng", [("8 East", None), ("8 West", "English"), ("9 East", "English")]),
    ("Samuel Mwangi", "teacher", "s.mwangi", [("8 West", None), ("9 West", "Mathematics"), ("9 East", "Mathematics")]),
    ("Fatuma Hassan", "teacher", "f.hassan", [("9 East", None), ("7 East", "Kiswahili"), ("9 West", "Kiswahili")]),
    ("David Wafula", "teacher", "d.wafula", [("9 West", None), ("8 East", "Social Studies"), ("7 West", "Agriculture")]),
]
DEMO_STREETS = ["Ngong Road", "Kilimani Road", "Mombasa Road", "Thika Road", "Langata Road", "Jogoo Road",
                "Waiyaki Way", "Kiambu Road"]
DEMO_OCCUPATIONS = ["Teacher", "Nurse", "Farmer", "Accountant", "Driver", "Trader", "Engineer", "Mechanic",
                    "Civil servant", "Shopkeeper", "Doctor", "Tailor", "Banker", "Chef", ""]
SUBJECT_COMMENTS = {
    "high": ["Excellent understanding; keep taking on the extension tasks.", "Consistently strong work and good questions.",
             "A very good term. Well done.", "Confident and accurate. Keep it up."],
    "mid": ["Steady progress; more regular revision will lift results.", "Good effort. Check work carefully before handing in.",
            "Participates well; needs to practise the harder topics.", "Improving. Keep asking for help when stuck."],
    "low": ["Needs more practice with the basics; extra support offered.", "Must complete homework regularly to improve.",
            "Finds this learning area hard; we will work on it together.", "More focus in class will help a lot."],
}
COMMENTS = {
    "high": "{name} has had an excellent term, working with real focus and helping classmates along the way. "
            "Results in {best} were outstanding. Keep challenging yourself with the extension work.",
    "mid": "{name} has made steady progress this term and takes part well in class. {best} is a clear strength; "
           "more regular revision in {weakest} would lift the overall result.",
    "low": "{name} is capable of more than these results show. With support at home and consistent homework, "
           "especially in {weakest}, we expect good improvement next term.",
}


def _school_terms(today):
    """This school year's three terms, and the index of the current one (the last that has started)."""
    year = today.year
    terms = [
        (f"Term 1 {year}", date(year, 1, 6), date(year, 4, 3)),
        (f"Term 2 {year}", date(year, 4, 28), date(year, 8, 1)),
        (f"Term 3 {year}", date(year, 8, 25), date(year, 10, 30)),
    ]
    current = max((i for i, (_, start, _) in enumerate(terms) if start <= today), default=0)
    return terms, current


def _weekdays(start, end):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


class Command(BaseCommand):
    help = "Create the demo schools with realistic data (skips any that exist; --reset rebuilds them)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete and rebuild the demo school.")

    def handle(self, *args, **options):
        if not settings.DEBUG and os.environ.get("ALLOW_DEMO_SEED") != "1":
            self.stderr.write(
                "Refusing to create demo schools: DEBUG is off, so this looks like a production server, and "
                "demo accounts share one password. Set ALLOW_DEMO_SEED=1 only on a server that exists for demos."
            )
            return
        password = os.environ.get("DEMO_PASSWORD", "")
        if not password:
            self.stdout.write("DEMO_PASSWORD isn't set, so the demo school wasn't created.")
            return
        if len(password) < 10:
            raise CommandError("DEMO_PASSWORD must be at least 10 characters.")

        existing = School.objects.filter(name=SCHOOL_NAME).first()
        if existing and not options["reset"]:
            self.stdout.write(f"{SCHOOL_NAME} already exists; nothing to do (use --reset to rebuild it).")
        else:
            with transaction.atomic():
                if existing:
                    self._delete(existing)
                self._build(password)
        self._system_demos(password, options["reset"])

    def _system_demos(self, password, reset):
        """The 8-4-4, British, IB and American demo schools, each created if it's missing."""
        from students import demo_systems

        password_hash = None
        for spec in demo_systems.DEMOS:
            existing = School.objects.filter(name=spec["name"]).first()
            if existing and not reset:
                self.stdout.write(f"{spec['name']} already exists; nothing to do.")
                continue
            with transaction.atomic():
                if existing:
                    users = demo_systems.demo_users(spec)
                    if users.exclude(profile__school=existing).exclude(guardian__school=existing) \
                            .exclude(profile__isnull=True, guardian__isnull=True).exists():
                        raise CommandError(f"Some {spec['name']} accounts belong to another school; refusing to delete.")
                    existing.delete()
                    users.delete()
                password_hash = password_hash or make_password(password)
                self.stdout.write(self.style.SUCCESS(demo_systems.build(spec, password_hash)))

    def _delete(self, school):
        # Only the demo school and accounts on the demo domain are touched.
        users = User.objects.filter(email__iendswith=f"@{DOMAIN}")
        other = users.exclude(profile__school=school).exclude(guardian__school=school) \
            .exclude(profile__isnull=True, guardian__isnull=True)
        if other.exists():
            raise CommandError("Some demo-domain accounts belong to another school; refusing to delete.")
        school.delete()
        users.delete()
        self.stdout.write(f"Deleted the old {SCHOOL_NAME}.")

    def _build(self, password):
        rng = random.Random(2026)
        today = timezone.localdate()
        now = timezone.now()
        school = School.objects.create(
            name=SCHOOL_NAME, report_tone="warm", education_system="cbc", motto="Learning together, growing together",
            address="Ngong Road, Nairobi", phone="+254 000 100 200", email=f"office@{DOMAIN}",
            setup_completed_at=timezone.now(),
        )

        # Hashing is deliberately slow, so hash the shared demo password once.
        password_hash = make_password(password)

        def user(email_local, name):
            first, _, last = name.partition(" ")
            return User.objects.create(username=f"{email_local}@{DOMAIN}", email=f"{email_local}@{DOMAIN}",
                                       password=password_hash, first_name=first, last_name=last)

        # --- structure
        years, classes = {}, {}
        for grade in (7, 8, 9):
            years[grade] = YearGroup.objects.create(school=school, name=f"Grade {grade}", order=grade, is_final=grade == 9)
            for stream in ("East", "West"):
                classes[f"{grade} {stream}"] = SchoolClass.objects.create(
                    year_group=years[grade], name=f"{grade} {stream}")
        subjects = {name: Subject.objects.create(school=school, name=name) for name in SUBJECTS}
        term_specs, current_index = _school_terms(today)
        terms = [Term.objects.create(school=school, name=n, start_date=s, end_date=e) for n, s, e in term_specs]
        current = terms[current_index]

        # --- staff and teaching assignments
        staff = {}
        for name, role, local, teaches in STAFF:
            u = user(local, name)
            profile = Profile.objects.create(user=u, school=school, role=role, display_name=name)
            staff[local] = u
            for class_name, subject in teaches:
                TeachingAssignment.objects.create(teacher=profile, school_class=classes[class_name],
                                                  subject=subjects[subject] if subject else None)
            if role == "admin":
                u.last_login = now - timedelta(hours=rng.randint(1, 20))
            else:
                u.last_login = now - timedelta(days=rng.randint(0, 6), hours=rng.randint(0, 10))
            u.save(update_fields=["last_login"])
        principal = staff["principal"]

        # --- students (about 25 per class), each with an ability and a trend
        students, ability, trend = [], {}, {}
        # Each class has its own level and direction over the year, so the graphs show real contrasts:
        # 8 East is strong and steady, 8 West is slipping, 7 East is climbing, 9 West recovers in term 3.
        class_level = {"7 East": 60, "7 West": 57, "8 East": 72, "8 West": 60, "9 East": 68, "9 West": 52}
        class_shift = {"7 East": [0, 4, 9], "7 West": [0, 1, 2], "8 East": [0, 1, 2],
                       "8 West": [0, -4, -8], "9 East": [0, 2, 4], "9 West": [0, -5, 3]}
        n = 0
        for class_name, klass in classes.items():
            grade = int(class_name.split()[0])
            for _ in range(rng.randint(23, 27)):
                n += 1
                female = rng.random() < 0.5
                first = rng.choice(FIRST_F if female else FIRST_M)
                last = rng.choice(LAST)
                born = date(today.year - (grade + 5), 1, 1) + timedelta(days=rng.randint(0, 364))
                s = Student(
                    school=school, school_class=klass, external_id=f"HDA/{today.year - (grade - 7)}/{n:03d}",
                    first_name=first, last_name=last, house=rng.choice(HOUSES), gender="female" if female else "male",
                    date_of_birth=born, nationality="Kenyan" if rng.random() < 0.94 else rng.choice(["Ugandan", "Tanzanian"]),
                    mode_of_learning="boarding" if rng.random() < 0.3 else "day",
                    enrolled_on=date(today.year - (grade - 7), 1, 8),
                    medical_notes=rng.choice(["", "", "", "", "", "", "", "", "", "", "Asthma: inhaler kept in the school office.",
                                              "Peanut allergy. EpiPen in the school office.", "Wears glasses; sits near the front."]),
                )
                students.append(s)
                ability[len(students) - 1] = rng.gauss(class_level[class_name], 11)
                trend[len(students) - 1] = rng.choice([-4, -2, 0, 2, 3, 5])
        Student.objects.bulk_create(students)
        students = list(Student.objects.filter(school=school).order_by("id"))
        ability = {s.id: ability[i] for i, s in enumerate(students)}
        trend = {s.id: trend[i] for i, s in enumerate(students)}
        # Two students who left last year: inactive, history kept.
        for s in students[:2]:
            s.is_active = False
            s.save(update_fields=["is_active"])
        active = [s for s in students if s.is_active]

        # --- grades: full for past terms, part of the subjects for the current term
        subject_bias = {"Mathematics": -9, "English": 5, "Kiswahili": 3, "Integrated Science": -3,
                        "Social Studies": 4, "Pre-Technical Studies": 1, "Agriculture": 6}
        formative = AssessmentType.objects.create(school=school, name="Formative assessment", weight=40, order=0)
        end_term = AssessmentType.objects.create(school=school, name="End-term assessment", weight=60, order=1)
        grades = []
        for term_number, term in enumerate(terms[: current_index + 1]):
            graded = SUBJECTS if term != current else SUBJECTS[:4]
            for s in active:
                for name in graded:
                    shift = class_shift[s.school_class.name][min(term_number, 2)]
                    score = ability[s.id] + shift + trend[s.id] * term_number + subject_bias[name] + rng.gauss(0, 7)
                    grades.append(Grade(student=s, subject=subjects[name], term=term,
                                        score=Decimal(max(8, min(100, round(score)))), max_score=Decimal(100),
                                        # This term's marks so far are classwork; past terms are end-of-term.
                                        assessment_type=formative if term == current else end_term))
        Grade.objects.bulk_create(grades)
        grades_by_student = {}
        for g in grades:
            grades_by_student.setdefault((g.student.id, g.term.id), []).append(g)

        # --- attendance: every school day of the current term so far; today only for some classes
        records = []
        term_days = [d for d in _weekdays(current.start_date, min(current.end_date, today - timedelta(days=1)))][-45:]
        attendance_risk = {s.id: rng.choice([0.02, 0.03, 0.04, 0.05, 0.08, 0.15]) for s in active}
        for s in active:
            for day in term_days:
                roll = rng.random()
                risk = attendance_risk[s.id]
                status = "absent" if roll < risk else "late" if roll < risk + 0.04 else \
                    "excused" if roll < risk + 0.05 else "present"
                note = "Hospital appointment" if status == "excused" else ""
                records.append(AttendanceRecord(student=s, date=day, status=status, notes=note))
        if today.weekday() < 5 and current.start_date <= today <= current.end_date:
            for s in active:
                if s.school_class.name in ("7 East", "8 East", "9 East", "7 West"):
                    records.append(AttendanceRecord(student=s, date=today,
                                                    status="absent" if rng.random() < 0.05 else "present"))
        AttendanceRecord.objects.bulk_create(records)

        # --- parents: about 70% of students have one; some parents have two children
        parents, parent_n = [], 0
        pool = active[:]
        rng.shuffle(pool)
        linked = pool[: int(len(pool) * 0.7)]
        i = 0
        while i < len(linked):
            parent_n += 1
            child = linked[i]
            female = rng.random() < 0.6
            pname = f"{rng.choice(FIRST_F if female else FIRST_M)} {child.last_name}"
            u = user(f"parent{parent_n:03d}", pname)
            u.last_login = now - timedelta(days=rng.randint(0, 20)) if rng.random() < 0.8 else None
            u.save(update_fields=["last_login"])
            # Contact details use a separate random stream so the rest of the
            # demo data stays the same. Phone numbers start +254 000, which no
            # real line uses, so nobody can ring a stranger from the demo.
            crng = random.Random(parent_n)
            g = Guardian.objects.create(
                user=u, school=school, display_name=pname,
                phone=f"+254 000 {crng.randint(100, 999)} {crng.randint(100, 999)}",
                phone_alt=f"+254 000 {crng.randint(100, 999)} {crng.randint(100, 999)}" if crng.random() < 0.4 else "",
                relationship=("mother" if female else "father") if crng.random() < 0.85 else
                crng.choice(["guardian", "grandparent", "other"]),
                address=f"{crng.choice(['House', 'Plot', 'Flat'])} {crng.randint(1, 90)}, "
                        f"{crng.choice(DEMO_STREETS)}, Nairobi",
                occupation=crng.choice(DEMO_OCCUPATIONS),
                preferred_contact=crng.choice(["call", "call", "sms", "whatsapp", "whatsapp", "email"]),
                admin_note="Second contact collects the children on Fridays." if crng.random() < 0.08 else "",
            )
            kids = [child]
            if rng.random() < 0.15 and i + 1 < len(linked):  # a sibling
                i += 1
                sibling = linked[i]
                sibling.last_name = child.last_name
                sibling.save(update_fields=["last_name"])
                kids.append(sibling)
            g.students.set(kids)
            parents.append(g)
            i += 1
        # A well-known demo parent login.
        demo_parent = parents[0]
        demo_parent.user.username = demo_parent.user.email = f"parent@{DOMAIN}"
        demo_parent.user.save(update_fields=["username", "email"])

        # --- reports: last term finalized (a few waiting), this term some drafts
        previous = terms[current_index - 1] if current_index > 0 else None
        report_rows = []

        def comment(s, term):
            marks = {g.subject.name: float(g.score) for g in Grade.objects.filter(student=s, term=term).select_related("subject")}
            if not marks:
                return None, None
            avg = sum(marks.values()) / len(marks)
            best = max(marks, key=marks.get)
            weakest = min(marks, key=marks.get)
            band = "high" if avg >= 72 else "mid" if avg >= 55 else "low"
            text = COMMENTS[band].format(name=s.first_name, best=best, weakest=weakest)
            summary = (f"Average {avg:.0f}% across {len(marks)} subjects. Strongest in {best} ({marks[best]:.0f}%), "
                       f"weakest in {weakest} ({marks[weakest]:.0f}%).")
            return summary, text

        teachers = [u for local, u in staff.items() if local not in ("principal", "deputy")]
        if previous:
            for k, s in enumerate(active):
                summary, text = comment(s, previous)
                if not text:
                    continue
                waiting = k % 17 == 0
                # CBC competency and value ratings, from their own random stream so
                # the rest of the demo data doesn't change.
                erng = random.Random(s.id)
                marks = [g.score for g in grades_by_student.get((s.id, previous.id), [])]
                typical = "EE" if marks and sum(marks) / len(marks) >= 72 else "ME"
                extra = {group["key"]: {item: erng.choice([typical, typical, typical, "ME", "EE", "AE"])
                                        for item in group["items"]} for group in REPORT_EXTRAS["cbc"]}
                report_rows.append(StudentReport(
                    student=s, term=previous, progress_summary=summary, report_comment=text, tone_used="warm",
                    extra=extra,
                    status="submitted" if waiting else "finalized",
                    submitted_by=rng.choice(teachers), submitted_at=now - timedelta(days=rng.randint(40, 60)),
                    finalized_by=None if waiting else principal,
                    finalized_at=None if waiting else now - timedelta(days=rng.randint(30, 39)),
                ))
        for s in [s for s in active if s.school_class.name == "7 East"][:6]:
            summary, text = comment(s, current)
            if text:
                report_rows.append(StudentReport(student=s, term=current, progress_summary=summary,
                                                 report_comment=text, tone_used="warm", status="draft"))
        StudentReport.objects.bulk_create(report_rows)
        # Subject teachers' comments on last term's report cards.
        if previous:
            entries = []
            for s in active:
                for grade in grades_by_student.get((s.id, previous.id), []):
                    crng = random.Random(s.id * 1000 + grade.subject.id)
                    band = "high" if grade.score >= 75 else "mid" if grade.score >= 50 else "low"
                    entries.append(SubjectReport(student=s, subject=grade.subject, term=previous,
                                                 comment=crng.choice(SUBJECT_COMMENTS[band])))
            SubjectReport.objects.bulk_create(entries)
        # The first term of the year is finished and locked.
        if current_index >= 2:
            terms[0].is_locked = True
            terms[0].locked_at = now - timedelta(days=100)
            terms[0].save(update_fields=["is_locked", "locked_at"])

        # --- communications
        for title, body, audience, extra, days in [
            ("Half-term break", "School closes on Friday at 12.30pm for half-term and reopens the following "
             "Wednesday at 7.30am. Boarders may be collected from 11am.", "all_parents", {}, 12),
            ("Staff meeting: Thursday 3.30pm", "Agenda: end-of-term assessments, report deadlines and the sports "
             "day timetable. Library, 3.30pm.", "all_staff", {}, 5),
            ("Grade 9 science fair", "Grade 9 students will present their science projects next Friday from 10am. "
             "Parents are warmly invited to attend.", "year_group", {"year_group": years[9]}, 3),
        ]:
            a = Announcement.objects.create(school=school, title=title, body=body, audience=audience,
                                            status="published", created_by=principal, **extra)
            Announcement.objects.filter(id=a.id).update(published_at=now - timedelta(days=days),
                                                        created_at=now - timedelta(days=days))
        Announcement.objects.create(school=school, title="Sports day kit", body="Draft: kit list to follow.",
                                    audience="all_parents", status="draft", created_by=principal)

        # A direct conversation and a class notice.
        njeri = staff["m.njeri"]
        child = next(s for s in demo_parent.students.all())
        conv = Conversation.objects.create(school=school, created_by=njeri, student=child)
        ConversationParticipant.objects.create(conversation=conv, user=njeri, last_read_at=now)
        ConversationParticipant.objects.create(conversation=conv, user=demo_parent.user)
        for sender, body, hours in [
            (njeri, f"Good afternoon. {child.first_name} did very well in today's mathematics quiz. Well done!", 30),
            (demo_parent.user, "Thank you, that's lovely to hear. We've been practising fractions at home.", 28),
            (njeri, "It shows. Please keep it up, the next topic builds on it.", 27),
        ]:
            m = Message.objects.create(conversation=conv, sender=sender, body=body)
            Message.objects.filter(id=m.id).update(created_at=now - timedelta(hours=hours))
        notice = Conversation.objects.create(school=school, kind=Conversation.Kind.CLASS_NOTICE,
                                             school_class=classes["7 East"], created_by=njeri)
        ConversationParticipant.objects.create(conversation=notice, user=njeri, last_read_at=now)
        for g in Guardian.objects.filter(students__school_class=classes["7 East"]).distinct():
            ConversationParticipant.objects.create(conversation=notice, user=g.user)
        Message.objects.create(conversation=notice, sender=njeri,
                               body="Reminder: 7 East's trip to the National Museum is on Friday. Please send a "
                                    "packed lunch and a signed consent form.")

        # An earlier urgent alert, since ended, seen by most parents.
        alert = UrgentAlert.objects.create(
            school=school, title="Water supply interruption", audience="all_parents", created_by=principal,
            body="Water supply to the school is interrupted this morning. Day scholars will be released at 11am.",
        )
        UrgentAlert.objects.filter(id=alert.id).update(created_at=now - timedelta(days=9),
                                                       ended_at=now - timedelta(days=8))
        AlertRecipient.objects.bulk_create([
            AlertRecipient(alert=alert, user=g.user,
                           acknowledged_at=now - timedelta(days=9) + timedelta(minutes=rng.randint(3, 300))
                           if rng.random() < 0.85 else None)
            for g in parents
        ])

        # Waiting for the admin: a teacher's request, and invites not accepted yet.
        kiprono = staff["j.kiprono"]
        ChangeRequest.objects.create(
            school=school, requested_by=kiprono, requested_by_name="John Kiprono", kind="subject",
            operation="create", data={"name": "Computer Science"}, summary='Add subject "Computer Science"',
            reason="Grade 9 is starting the coding club syllabus next term.",
        )
        Invite.objects.create(school=school, email=f"new.teacher@{DOMAIN}", name="Lucy Chepkoech",
                              role="teacher", invited_by=principal)
        unlinked = [s for s in active if not s.guardians.exists()][:3]
        for k, s in enumerate(unlinked):
            inv = GuardianInvite.objects.create(school=school, email=f"invite{k + 1}@{DOMAIN}",
                                                name=f"{rng.choice(FIRST_F)} {s.last_name}", invited_by=principal)
            inv.students.add(s)

        log_activity(school=school, actor=None, action="school.demo_created",
                     summary=f"Created {SCHOOL_NAME} with {len(active)} students and {len(parents)} parent accounts")

        self.stdout.write(self.style.SUCCESS(
            f"Created {SCHOOL_NAME}: {len(STAFF)} staff, {len(active)} active students in {len(classes)} classes, "
            f"{len(parents)} parents, {len(grades)} grades, {len(records)} attendance records, "
            f"{len(report_rows)} reports."
        ))
        self.stdout.write(f"Log in as principal@{DOMAIN} (admin), m.njeri@{DOMAIN} (teacher) or "
                          f"parent@{DOMAIN} (parent), with the DEMO_PASSWORD password.")
