"""
One demo school for each education system besides CBC (which has the full
HouseMaster Demo Academy): an 8-4-4 secondary, a British international school,
an IB school and an American high school.

Each is a smaller, complete school in its own system's style: its own
words, grading, terms, subjects and report cards, staff and parent logins,
last term's finalized reports and this term's marks and attendance so far.
Its logins are on its own subdomain of the reserved demo domain, e.g.
principal@secondary.housemaster-demo.example, so no email reaches a real
person and each school is completely separate from the others.
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import Profile, TeachingAssignment
from activity.services import log_activity
from attendance.models import AttendanceRecord
from communications.models import Announcement
from gradebook.levels import level_for
from gradebook.models import AssessmentType, Grade, StudentSubject, Subject, SubjectReport, Term
from gradebook.systems import REPORT_EXTRAS
from guardians.models import Guardian
from reporting.models import StudentReport

from .models import School, SchoolClass, Student, YearGroup
from .presets import school_vocab, suggested_terms
from .samples import PRINCIPAL_COMMENT, SUBJECT_COMMENTS, TEACHER_COMMENTS, band, names

BASE_DOMAIN = "housemaster-demo.example"

DEMOS = [
    {
        "key": "844", "name": "HouseMaster Demo Secondary", "subdomain": "secondary", "country": "ke",
        "scale": "kcse", "tone": "formal", "motto": "Strive to excel", "address": "Thika Road, Nairobi",
        "phone": "+254 000 300 400", "id_prefix": "HDS",
        "year_groups": [("Form 1", ["1 East", "1 West"]), ("Form 2", ["2 East", "2 West"]),
                        ("Form 3", ["3 East", "3 West"]), ("Form 4", ["4 East", "4 West"])],
        "subjects": ["English", "Kiswahili", "Mathematics", "Biology", "Chemistry", "Physics", "Geography",
                     "History and Government", "Christian Religious Education", "Business Studies", "Agriculture"],
        # Form 3 and 4 choose two of these.
        "electives": ["Geography", "Business Studies", "Agriculture"],
        "assessments": [("CAT", 30), ("End-term exam", 70)],
        "staff": [("Joseph Mutua", "principal"), ("Ruth Chebet", "r.chebet"), ("Daniel Ouma", "d.ouma"),
                  ("Agnes Wairimu", "a.wairimu"), ("Hassan Ali", "h.ali")],
    },
    {
        "key": "british", "name": "HouseMaster Demo International School", "subdomain": "british", "country": "gb",
        "scale": "igcse9", "tone": "warm", "motto": "Curious minds, kind hearts", "address": "Riverside Drive, Nairobi",
        "phone": "+44 0000 000 100", "id_prefix": "HIS",
        "year_groups": [("Year 9", ["9 Blue", "9 Green"]), ("Year 10", ["10 Blue", "10 Green"]),
                        ("Year 11", ["11 Blue", "11 Green"])],
        "subjects": ["English Language", "English Literature", "Mathematics", "Biology", "Chemistry", "Physics",
                     "History", "Geography", "French", "Computer Science", "Art and Design"],
        "electives": ["History", "Geography", "Computer Science", "Art and Design"],
        "assessments": [("Classwork", 40), ("Assessment week", 60)],
        "staff": [("Helen Clarke", "principal"), ("James Walker", "j.walker"), ("Priya Shah", "p.shah"),
                  ("Tom Hughes", "t.hughes"), ("Sarah Green", "s.green")],
    },
    {
        "key": "ib", "name": "HouseMaster Demo IB School", "subdomain": "ib", "country": "other",
        "scale": "ib", "tone": "warm", "motto": "Inquire, reflect, act", "address": "Gigiri, Nairobi",
        "phone": "+254 000 500 600", "id_prefix": "HIB",
        "year_groups": [("MYP 4", ["MYP 4A", "MYP 4B"]), ("MYP 5", ["MYP 5A", "MYP 5B"]), ("DP 1", ["DP 1"]),
                        ("DP 2", ["DP 2"])],
        "subjects": ["Language and Literature", "Language Acquisition", "Mathematics", "Sciences",
                     "Individuals and Societies", "Arts", "Design", "Physical and Health Education"],
        "electives": [],
        "assessments": [("Formative", 30), ("Summative", 70)],
        "staff": [("Elena Rossi", "principal"), ("Kofi Mensah", "k.mensah"), ("Mei Tanaka", "m.tanaka"),
                  ("Omar Haddad", "o.haddad"), ("Ines Silva", "i.silva")],
    },
    {
        "key": "american", "name": "HouseMaster Demo American School", "subdomain": "american", "country": "us",
        "scale": "american", "tone": "concise", "motto": "Excellence in all things", "address": "Runda, Nairobi",
        "phone": "+1 000 000 0100", "id_prefix": "HAS",
        "year_groups": [("Grade 9", ["9-1", "9-2"]), ("Grade 10", ["10-1", "10-2"]), ("Grade 11", ["11-1"]),
                        ("Grade 12", ["12-1"])],
        "subjects": ["English", "Algebra II", "Biology", "US History", "Spanish", "Physical Education", "Art",
                     "Computer Science"],
        "credits": {"Physical Education": "0.5", "Art": "0.5"},
        "electives": ["Art", "Computer Science"],
        "assessments": [("Homework and quizzes", 40), ("Tests", 60)],
        "staff": [("Karen Mitchell", "principal"), ("David Johnson", "d.johnson"), ("Maria Garcia", "m.garcia"),
                  ("Brian Lee", "b.lee"), ("Ashley Scott", "a.scott")],
    },
]
STUDENTS_PER_CLASS = (15, 19)
# American letter grades start higher, so its students score a little higher.
LIFT = {"american": 10}


def domain(spec):
    return f"{spec['subdomain']}.{BASE_DOMAIN}"


def demo_users(spec):
    return User.objects.filter(email__iendswith=f"@{domain(spec)}")


def _terms(system, today):
    """Last school year's final term and this year's terms, so there is always a finished term."""
    last_year = suggested_terms(system, today.replace(year=today.year - 1))[-1:]
    this_year = suggested_terms(system, today)
    specs = [t for t in last_year if t["name"] not in {x["name"] for x in this_year}] + this_year
    return [(t["name"], date.fromisoformat(t["start_date"]), date.fromisoformat(t["end_date"])) for t in specs]


def build(spec, password_hash, today=None):
    """Create one demo school. Returns a one-line summary."""
    rng = random.Random(f"{spec['key']}-2026")
    today = today or timezone.localdate()
    now = timezone.now()
    system = spec["key"]
    dom = domain(spec)
    school = School.objects.create(
        name=spec["name"], education_system=system, grading_scale=spec["scale"], country=spec["country"],
        report_tone=spec["tone"], motto=spec["motto"], address=spec["address"], phone=spec["phone"],
        email=f"office@{dom}", setup_completed_at=now,
    )
    words = school_vocab(school)

    def user(local, name):
        first, _, last = name.partition(" ")
        return User.objects.create(username=f"{local}@{dom}", email=f"{local}@{dom}", password=password_hash,
                                   first_name=first, last_name=last)

    # --- structure
    classes = []
    last = len(spec["year_groups"]) - 1
    for order, (yg_name, class_names) in enumerate(spec["year_groups"]):
        yg = YearGroup.objects.create(school=school, name=yg_name, order=order, is_final=order == last)
        classes += [SchoolClass.objects.create(year_group=yg, name=n) for n in class_names]
    credits = spec.get("credits", {})
    subjects = [Subject.objects.create(school=school, name=n, credits=Decimal(credits.get(n, "1")),
                                       is_elective=n in spec["electives"]) for n in spec["subjects"]]
    types = [AssessmentType.objects.create(school=school, name=n, weight=w, order=i)
             for i, (n, w) in enumerate(spec["assessments"])]
    term_specs = _terms(system, today)
    terms = [Term.objects.create(school=school, name=n, start_date=s, end_date=e) for n, s, e in term_specs]
    current_index = max((i for i, t in enumerate(terms) if t.start_date <= today), default=len(terms) - 1)
    current, previous = terms[current_index], terms[max(0, current_index - 1)]
    terms[0].is_locked = current_index >= 2
    terms[0].locked_at = now - timedelta(days=60) if terms[0].is_locked else None
    terms[0].save(update_fields=["is_locked", "locked_at"])

    # --- staff: the principal, and teachers who each teach a spread of subjects and look after classes
    staff = []
    for i, (name, local) in enumerate(spec["staff"]):
        u = user(local, name)
        u.last_login = now - timedelta(days=rng.randint(0, 5), hours=rng.randint(1, 10))
        u.save(update_fields=["last_login"])
        staff.append(Profile.objects.create(user=u, school=school, role="admin" if i == 0 else "teacher",
                                            display_name=name))
    principal, teachers = staff[0], staff[1:]
    for i, klass in enumerate(classes):
        TeachingAssignment.objects.create(teacher=teachers[i % len(teachers)], school_class=klass, subject=None)
        for j, subject in enumerate(subjects):
            TeachingAssignment.objects.create(teacher=teachers[(i + j) % len(teachers)], school_class=klass,
                                              subject=subject)

    # --- students
    girls, boys, surnames = names(spec["country"])
    students, ability = [], {}
    n = 0
    for klass in classes:
        level = rng.gauss(64, 6)
        for _ in range(rng.randint(*STUDENTS_PER_CLASS)):
            n += 1
            female = rng.random() < 0.5
            students.append(Student(
                school=school, school_class=klass, external_id=f"{spec['id_prefix']}/{n:03d}",
                first_name=rng.choice(girls if female else boys), last_name=rng.choice(surnames),
                gender="female" if female else "male", enrolled_on=date(today.year - 1, 9, 1),
                date_of_birth=date(today.year - 15, 1, 1) + timedelta(days=rng.randint(0, 900)),
                mode_of_learning="day",
            ))
            ability[len(students) - 1] = rng.gauss(level, 11) + LIFT.get(system, 0)
    Student.objects.bulk_create(students)
    students = list(Student.objects.filter(school=school).select_related("school_class__year_group").order_by("id"))
    ability = {s.id: ability[i] for i, s in enumerate(students)}

    # --- subject choices: electives in the upper years, IB Higher and Standard Level in the Diploma years
    takes = {}
    choices = []
    upper = {yg for yg, _ in spec["year_groups"][len(spec["year_groups"]) // 2:]}
    for s in students:
        chosen = set()
        yg = s.school_class.year_group.name
        electives = [x for x in subjects if x.is_elective]
        if electives:
            picks = rng.sample(electives, min(2, len(electives))) if yg in upper else electives
            chosen = {x.id for x in picks}
            choices += [StudentSubject(student=s, subject=x) for x in picks]
        if system == "ib" and yg.startswith("DP"):
            hl = set(x.id for x in rng.sample(subjects, 3))
            choices += [StudentSubject(student=s, subject=x, level="HL" if x.id in hl else "SL") for x in subjects]
        takes[s.id] = [x for x in subjects if not x.is_elective or x.id in chosen]
    StudentSubject.objects.bulk_create(choices)

    # --- marks: every earlier term in full, this term's first few subjects so far
    bias = {x.id: rng.gauss(0, 5) for x in subjects}
    grades = []
    for number, term in enumerate(terms[: current_index + 1]):
        for s in students:
            taken = takes[s.id] if term != current else takes[s.id][:4]
            for subject in taken:
                for kind in (types if term != current else types[:1]):
                    score = ability[s.id] + bias[subject.id] + number * 1.5 + rng.gauss(0, 7)
                    grades.append(Grade(student=s, subject=subject, term=term, assessment_type=kind,
                                        score=Decimal(max(10, min(100, round(score)))), max_score=Decimal(100)))
    Grade.objects.bulk_create(grades)
    # Last term's weighted result in each subject, so the comments match the marks.
    weight = {t.id: float(t.weight) for t in types}
    earned = {}
    for g in grades:
        if g.term == previous:
            key = (g.student.id, g.subject.id)
            total, weights = earned.get(key, (0.0, 0.0))
            earned[key] = (total + float(g.score) * weight[g.assessment_type.id], weights + weight[g.assessment_type.id])

    # --- last term's report cards: subject entries, then finalized reports
    entries, reports = [], []
    for s in students:
        scores = {}
        for subject in takes[s.id]:
            crng = random.Random(s.id * 1000 + subject.id)
            total, weights = earned.get((s.id, subject.id), (0.0, 0.0))
            score = total / weights if weights else ability[s.id]
            scores[subject.name] = score
            entry = SubjectReport(student=s, subject=subject, term=previous,
                                  comment=crng.choice(SUBJECT_COMMENTS[band(score)]))
            if system == "british":
                entry.effort = str(crng.choice([1, 2, 2, 3]))
                entry.target = level_for(min(100, score + 10), spec["scale"]) or ""
            elif system == "ib" and not s.school_class.year_group.name.startswith("DP"):
                entry.criteria = {c: max(1, min(8, round(score / 100 * 8 + crng.gauss(0, 0.8)))) for c in "ABCD"}
            entries.append(entry)
        best, weakest = max(scores, key=scores.get), min(scores, key=scores.get)
        erng = random.Random(s.id)
        extra = {g["key"]: {item: erng.choice(g["ratings"][:3]) for item in g["items"]}
                 for g in REPORT_EXTRAS.get(system, [])}
        reports.append(StudentReport(
            student=s, term=previous, status="finalized", tone_used=spec["tone"], extra=extra,
            progress_summary=f"Average {sum(scores.values()) / len(scores):.0f}%. Strongest in {best}, weakest in {weakest}.",
            report_comment=TEACHER_COMMENTS[spec["tone"]].format(name=s.first_name, best=best, weakest=weakest,
                                                                 subjects=words["subjects"].lower(),
                                                                 term=words["term"].lower()),
            principal_comment=PRINCIPAL_COMMENT.format(term=words["term"].lower()),
            submitted_by=teachers[0].user, submitted_at=now - timedelta(days=30),
            finalized_by=principal.user, finalized_at=now - timedelta(days=25),
        ))
    if previous != current:
        SubjectReport.objects.bulk_create(entries)
        StudentReport.objects.bulk_create(reports)

    # --- attendance for this term so far
    records = []
    day = current.start_date
    while day < min(today, current.end_date + timedelta(days=1)):
        if day.weekday() < 5:
            for s in students:
                roll = rng.random()
                records.append(AttendanceRecord(student=s, date=day,
                                                status="absent" if roll < 0.04 else "late" if roll < 0.07 else "present"))
        day += timedelta(days=1)
    AttendanceRecord.objects.bulk_create(records)

    # --- parents: about two thirds of students; the first is the well-known parent@ login
    linked = students[:]
    rng.shuffle(linked)
    parents = 0
    for k, s in enumerate(linked[: len(linked) * 2 // 3]):
        female = rng.random() < 0.6
        pname = f"{rng.choice(girls if female else boys)} {s.last_name}"
        u = user("parent" if k == 0 else f"parent{k:03d}", pname)
        g = Guardian.objects.create(user=u, school=school, display_name=pname,
                                    relationship="mother" if female else "father")
        g.students.set([s])
        parents += 1

    Announcement.objects.create(
        school=school, title=f"Welcome back for {current.name}", audience="all_parents", status="published",
        created_by=principal.user, published_at=now - timedelta(days=10),
        body=f"Welcome back. {words['term']} reports for {previous.name} are now available to download from "
             f"HouseMaster. Please get in touch with your child's teacher with any questions.",
    )
    log_activity(school=school, actor=None, action="school.demo_created",
                 summary=f"Created {spec['name']} with {len(students)} students and {parents} parent accounts")
    return (f"Created {spec['name']}: {len(staff)} staff, {len(students)} students in {len(classes)} classes, "
            f"{parents} parents. Log in as principal@{dom}, {spec['staff'][1][1]}@{dom} or parent@{dom}.")
