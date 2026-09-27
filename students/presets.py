"""
Starting points for the setup wizard: each education system's stages (with
their year groups and usual subjects), term pattern and grading scales.

Everything here is only a suggestion. Schools tick the stages they offer,
can add, rename or remove year groups and subjects, and edit term dates, so
the lists cover what's common rather than every variation.
"""
from datetime import date

KENYA_TERMS = [("Term 1", (1, 6), (4, 3)), ("Term 2", (4, 28), (8, 1)), ("Term 3", (8, 25), (10, 30))]
UK_TERMS = [("Autumn term", (9, 3), (12, 12)), ("Spring term", (1, 6), (3, 27)), ("Summer term", (4, 20), (7, 10))]
US_TERMS = [("Fall semester", (8, 25), (12, 19)), ("Spring semester", (1, 12), (5, 29))]

SYSTEMS = {
    "cbc": {
        "name": "CBC (Competency Based Curriculum)",
        "country": "Kenya",
        "description": "Pre-primary to Grade 12 under Kenya's Competency Based Curriculum.",
        "terms": KENYA_TERMS,
        "year_starts": "january",
        "scales": ["cbc4", "cbc8", "percent"],
        "stages": [
            {"key": "pre_primary", "name": "Pre-primary", "year_groups": ["PP1", "PP2"], "subjects": [
                "Language Activities", "Mathematical Activities", "Environmental Activities",
                "Psychomotor and Creative Activities", "Religious Education Activities"]},
            {"key": "lower_primary", "name": "Lower primary", "year_groups": ["Grade 1", "Grade 2", "Grade 3"],
             "subjects": ["English", "Kiswahili", "Mathematics", "Indigenous Language", "Religious Education",
                          "Environmental Activities", "Creative Activities"]},
            {"key": "upper_primary", "name": "Upper primary", "year_groups": ["Grade 4", "Grade 5", "Grade 6"],
             "subjects": ["English", "Kiswahili", "Mathematics", "Religious Education", "Science and Technology",
                          "Agriculture and Nutrition", "Social Studies", "Creative Arts"]},
            {"key": "junior", "name": "Junior school", "year_groups": ["Grade 7", "Grade 8", "Grade 9"],
             "scale": "cbc8",
             "subjects": ["English", "Kiswahili", "Mathematics", "Religious Education", "Integrated Science",
                          "Agriculture and Nutrition", "Social Studies", "Creative Arts and Sports",
                          "Pre-Technical Studies"]},
            {"key": "senior", "name": "Senior school", "year_groups": ["Grade 10", "Grade 11", "Grade 12"],
             "scale": "cbc8",
             "subjects": ["English", "Kiswahili", "Core Mathematics", "Community Service Learning",
                          "Physical Education", "Biology", "Chemistry", "Physics", "Geography",
                          "History and Citizenship", "Business Studies", "Computer Studies", "Agriculture",
                          "Christian Religious Education", "Islamic Religious Education"]},
        ],
    },
    "844": {
        "name": "8-4-4",
        "country": "Kenya",
        "description": "Form 1 to Form 4 secondary, examined by KCSE.",
        "terms": KENYA_TERMS,
        "year_starts": "january",
        "scales": ["kcse", "percent"],
        "stages": [
            {"key": "secondary", "name": "Secondary (Form 1 to 4)", "year_groups": ["Form 1", "Form 2", "Form 3", "Form 4"],
             "subjects": ["English", "Kiswahili", "Mathematics", "Biology", "Chemistry", "Physics", "Geography",
                          "History and Government", "Christian Religious Education", "Islamic Religious Education",
                          "Business Studies", "Agriculture", "Computer Studies", "Home Science", "French"]},
        ],
    },
    "british": {
        "name": "British / Cambridge",
        "country": "United Kingdom",
        "description": "Early Years to A Level, with Cambridge IGCSE.",
        "terms": UK_TERMS,
        "year_starts": "september",
        "scales": ["igcse", "igcse9", "percent"],
        "stages": [
            {"key": "early_years", "name": "Early Years", "year_groups": ["Nursery", "Reception"], "subjects": [
                "Communication and Language", "Literacy", "Mathematics", "Understanding the World",
                "Expressive Arts and Design", "Physical Development"]},
            {"key": "primary", "name": "Primary (Years 1 to 6)",
             "year_groups": ["Year 1", "Year 2", "Year 3", "Year 4", "Year 5", "Year 6"],
             "subjects": ["English", "Mathematics", "Science", "Computing", "History", "Geography",
                          "Art and Design", "Music", "Physical Education", "French", "Kiswahili"]},
            {"key": "lower_secondary", "name": "Lower Secondary (Years 7 to 9)", "year_groups": ["Year 7", "Year 8", "Year 9"],
             "subjects": ["English", "Mathematics", "Science", "Computing", "History", "Geography", "French",
                          "Kiswahili", "Art and Design", "Music", "Physical Education"]},
            {"key": "igcse", "name": "IGCSE (Years 10 and 11)", "year_groups": ["Year 10", "Year 11"],
             "subjects": ["English Language", "English Literature", "Mathematics", "Biology", "Chemistry",
                          "Physics", "Computer Science", "History", "Geography", "Business Studies",
                          "Economics", "French", "Kiswahili", "Art and Design", "Physical Education"]},
            {"key": "a_level", "name": "A Level (Years 12 and 13)", "year_groups": ["Year 12", "Year 13"],
             "subjects": ["Mathematics", "Further Mathematics", "Biology", "Chemistry", "Physics", "Economics",
                          "Business", "Computer Science", "History", "Geography", "English Literature",
                          "Psychology"]},
        ],
    },
    "ib": {
        "name": "International Baccalaureate (IB)",
        "country": "International",
        "description": "Primary Years, Middle Years and Diploma Programmes.",
        "terms": UK_TERMS,
        "year_starts": "september",
        "scales": ["ib", "percent"],
        "stages": [
            {"key": "pyp", "name": "Primary Years Programme (PYP)",
             "year_groups": ["PYP Early Years", "PYP 1", "PYP 2", "PYP 3", "PYP 4", "PYP 5"],
             "subjects": ["Language", "Mathematics", "Science", "Social Studies", "Arts",
                          "Personal, Social and Physical Education"]},
            {"key": "myp", "name": "Middle Years Programme (MYP)",
             "year_groups": ["MYP 1", "MYP 2", "MYP 3", "MYP 4", "MYP 5"],
             "subjects": ["Language and Literature", "Language Acquisition", "Individuals and Societies",
                          "Sciences", "Mathematics", "Arts", "Physical and Health Education", "Design"]},
            {"key": "dp", "name": "Diploma Programme (DP)", "year_groups": ["DP 1", "DP 2"],
             "subjects": ["Studies in Language and Literature", "Language Acquisition", "Individuals and Societies",
                          "Sciences", "Mathematics", "The Arts", "Theory of Knowledge", "Extended Essay"]},
        ],
    },
    "american": {
        "name": "American",
        "country": "United States",
        "description": "Kindergarten to Grade 12, in two semesters.",
        "terms": US_TERMS,
        "year_starts": "august",
        "scales": ["american", "percent"],
        "stages": [
            {"key": "elementary", "name": "Elementary (K to Grade 5)",
             "year_groups": ["Kindergarten", "Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5"],
             "subjects": ["English Language Arts", "Mathematics", "Science", "Social Studies", "Art", "Music",
                          "Physical Education"]},
            {"key": "middle", "name": "Middle school (Grades 6 to 8)", "year_groups": ["Grade 6", "Grade 7", "Grade 8"],
             "subjects": ["English Language Arts", "Mathematics", "Science", "Social Studies", "World Language",
                          "Computer Science", "Art", "Music", "Physical Education"]},
            {"key": "high", "name": "High school (Grades 9 to 12)",
             "year_groups": ["Grade 9", "Grade 10", "Grade 11", "Grade 12"],
             "subjects": ["English", "Algebra", "Geometry", "Pre-Calculus", "Biology", "Chemistry", "Physics",
                          "World History", "US History", "Economics", "Spanish", "French", "Computer Science",
                          "Art", "Physical Education"]},
        ],
    },
}


def suggested_terms(system, today=None):
    """This school year's terms for a system, with the usual dates, as [{name, start_date, end_date}]."""
    today = today or date.today()
    terms = SYSTEMS[system]["terms"]
    if SYSTEMS[system]["year_starts"] == "january":
        years = [today.year] * len(terms)
        label = str(today.year)
    else:
        # The school year starts in August/September: the first term is in
        # this calendar year if we're past the summer, otherwise last year.
        start = today.year if today.month >= 7 else today.year - 1
        years = [start if month >= 7 else start + 1 for _name, (month, _day), _end in terms]
        label = f"{start}/{str(start + 1)[2:]}"
    return [
        {"name": f"{name} {label}", "start_date": date(year, *start_md).isoformat(),
         "end_date": date(year, *end_md).isoformat()}
        for (name, start_md, end_md), year in zip(terms, years)
    ]


def suggested_scale(system, stage_keys):
    """The default scale: a stage-specific one (e.g. CBC junior school's 8 levels) if every chosen stage uses it."""
    stages = [s for s in SYSTEMS[system]["stages"] if s["key"] in stage_keys]
    special = {s.get("scale") for s in stages}
    if len(special) == 1 and None not in special:
        return special.pop()
    return SYSTEMS[system]["scales"][0]


def catalogue(today=None):
    """Everything the wizard needs to show the choices, in one payload."""
    from gradebook.levels import SCALE_LABELS, levels_key

    return {
        "systems": [
            {"key": key, "name": s["name"], "country": s["country"], "description": s["description"],
             "stages": s["stages"], "terms": suggested_terms(key, today), "scales": s["scales"]}
            for key, s in SYSTEMS.items()
        ],
        "scales": [{"key": k, "label": v, "key_text": levels_key(k)} for k, v in SCALE_LABELS.items()],
        "countries": [country(code) for code in COUNTRIES],
    }


# What each system calls things, so every screen uses the school's own words.
DEFAULT_VOCAB = {
    "year_group": "Year group", "year_groups": "Year groups", "class": "Class", "classes": "Classes",
    "subject": "Subject", "subjects": "Subjects", "term": "Term", "terms": "Terms",
    "student_id": "Admission no.",
}
VOCAB = {
    "cbc": {**DEFAULT_VOCAB, "year_group": "Grade", "year_groups": "Grades", "class": "Stream", "classes": "Streams",
            "subject": "Learning area", "subjects": "Learning areas"},
    "844": {**DEFAULT_VOCAB, "year_group": "Form", "year_groups": "Forms", "class": "Stream", "classes": "Streams"},
    "british": {**DEFAULT_VOCAB, "year_group": "Year", "year_groups": "Years", "class": "Form", "classes": "Forms",
                "student_id": "Student ID"},
    "ib": {**DEFAULT_VOCAB, "student_id": "Student ID"},
    "american": {**DEFAULT_VOCAB, "year_group": "Grade", "year_groups": "Grades", "class": "Homeroom",
                 "classes": "Homerooms", "subject": "Course", "subjects": "Courses", "term": "Semester",
                 "terms": "Semesters", "student_id": "Student ID"},
}


def vocab(system):
    return VOCAB.get(system, DEFAULT_VOCAB)


# Where the school is, which decides the privacy law it follows and local formats.
# Separate from the education system: a British-curriculum school in Nairobi
# is still under Kenyan law.
COUNTRIES = {
    "ke": {"name": "Kenya", "locale": "en-KE", "phone_example": "+254 712 345 678",
           "law": "Kenya's Data Protection Act, 2019",
           "regulator": "the Office of the Data Protection Commissioner (ODPC)"},
    "gb": {"name": "United Kingdom", "locale": "en-GB", "phone_example": "+44 7700 900123",
           "law": "the UK GDPR and the Data Protection Act 2018",
           "regulator": "the Information Commissioner's Office (ICO)"},
    "us": {"name": "United States", "locale": "en-US", "phone_example": "+1 555 010 0123",
           "law": "the Family Educational Rights and Privacy Act (FERPA) and your state's student privacy laws",
           "regulator": "the US Department of Education's Student Privacy Policy Office"},
    "other": {"name": "Another country", "locale": "en-GB", "phone_example": "+000 000 000 000",
              "law": "the data protection laws of your country",
              "regulator": "your national data protection authority"},
}


def country(code):
    return {"code": code if code in COUNTRIES else "ke", **COUNTRIES.get(code, COUNTRIES["ke"])}


# How the AI should write for each system, so drafted report comments and
# announcements sound like they came from that kind of school.
REPORT_GUIDANCE = {
    "cbc": (
        "The school follows Kenya's Competency Based Curriculum (CBC). Call subjects learning areas and the student "
        "a learner. Describe performance with the CBC levels given (Exceeding, Meeting, Approaching or Below "
        "Expectations) rather than raw marks. Where the data supports it, link progress to the CBC core competencies "
        "(communication and collaboration, critical thinking and problem solving, creativity and imagination, "
        "citizenship, digital literacy, learning to learn, self-efficacy). Never rank or compare the learner with "
        "classmates."
    ),
    "844": (
        "The school follows Kenya's 8-4-4 system and prepares students for the KCSE. Use the KCSE letter grades "
        "given, name the subjects where improvement would most raise the mean grade, and set specific, achievable "
        "targets for next term."
    ),
    "british": (
        "The school follows the British curriculum (Cambridge, IGCSE and A Level). Comment on attainment using the "
        "grades given (A* to G or 9 to 1) and finish with clear next steps."
    ),
    "ib": (
        "The school is an International Baccalaureate (IB) school. Use the 1 to 7 grades given, and where the data "
        "supports it relate progress to IB learner profile attributes (inquirer, knowledgeable, thinker, "
        "communicator, principled, open-minded, caring, risk-taker, balanced, reflective) and approaches to learning."
    ),
    "american": (
        "The school follows the American system. Refer to courses and the letter grades given (A to F), note "
        "strengths and areas to improve, and keep the style of a US report card comment."
    ),
}


def writing_context(school):
    """Instructions that tell the AI which system, words and spelling this school uses."""
    words = vocab(school.education_system)
    spelling = "American English" if school.country == "us" else "British English"
    lines = [REPORT_GUIDANCE[school.education_system]] if school.education_system in REPORT_GUIDANCE else []
    lines.append(
        f"Use the school's own words: a year group is a \"{words['year_group'].lower()}\", a class is a "
        f"\"{words['class'].lower()}\", a subject is a \"{words['subject'].lower()}\" and a term is a "
        f"\"{words['term'].lower()}\". Write in {spelling}."
    )
    return "\n".join(lines)
