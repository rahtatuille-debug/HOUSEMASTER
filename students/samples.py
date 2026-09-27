"""
Made-up people and words for the sample report card in the setup wizard and
for the demo schools: names that fit the school's country, teacher comments
in each report tone, and per-subject comments by how well a student did.
"""

NAMES = {  # country: (girls' first names, boys' first names, surnames)
    "ke": (["Achieng", "Wanjiru", "Amina", "Njeri", "Akinyi", "Wambui", "Chebet", "Faith", "Imani", "Zawadi",
            "Neema", "Halima", "Makena", "Kerubo", "Adhiambo"],
           ["Otieno", "Kamau", "Mwangi", "Kiprono", "Omondi", "Mutua", "Baraka", "Brian", "Juma", "Kipchoge",
            "Wafula", "Hassan", "Ochieng", "Kimani", "Barasa"],
           ["Otieno", "Kamau", "Wanjiku", "Mwangi", "Ochieng", "Njoroge", "Kiprotich", "Mutua", "Wafula", "Omondi",
            "Kariuki", "Chelimo", "Mohamed", "Nyaga", "Wambua", "Owino", "Karanja", "Maina", "Rotich", "Ndungu"]),
    "gb": (["Olivia", "Amelia", "Isla", "Ava", "Grace", "Freya", "Sophie", "Priya", "Ella", "Maya", "Zara",
            "Chloe", "Ruby", "Aisha", "Poppy"],
           ["Oliver", "George", "Harry", "Noah", "Jack", "Leo", "Arthur", "Oscar", "Samuel", "Rohan", "Theo",
            "Max", "Ethan", "Yusuf", "Finn"],
           ["Smith", "Jones", "Taylor", "Brown", "Williams", "Wilson", "Johnson", "Davies", "Patel", "Wright",
            "Evans", "Thomas", "Roberts", "Khan", "Walker", "Hughes", "Green", "Clarke", "Bennett", "Hall"]),
    "us": (["Emma", "Olivia", "Sophia", "Ava", "Mia", "Isabella", "Harper", "Abigail", "Emily", "Madison",
            "Chloe", "Layla", "Zoe", "Nora", "Riley"],
           ["Liam", "Noah", "Ethan", "Mason", "Lucas", "Logan", "Aiden", "Jacob", "Carter", "Elijah", "Wyatt",
            "Caleb", "Julian", "Owen", "Mateo"],
           ["Johnson", "Williams", "Brown", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Anderson",
            "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Lee", "Walker", "Young", "King", "Scott"]),
    "other": (["Maya", "Sofia", "Leila", "Ananya", "Amara", "Hana", "Chiara", "Nadia", "Ines", "Yuna", "Ayesha",
               "Elena", "Mei", "Zainab", "Freya"],
              ["Arjun", "Mateo", "Kenji", "Omar", "Luca", "Tariq", "Daniel", "Kofi", "Hugo", "Ravi", "Adam",
               "Felix", "Samir", "Jonas", "Ibrahim"],
              ["Okafor", "Rossi", "Tanaka", "Haddad", "Müller", "Sharma", "Dubois", "Mensah", "Silva", "Kim",
               "Novak", "Andersen", "Costa", "Rahman", "Fischer", "Nakamura", "Petrov", "Abdi", "Lopez", "Chen"]),
}

# The student on the wizard's sample report card.
SAMPLE_STUDENT = {"ke": ("Amani", "Wanjiku"), "gb": ("Olivia", "Bennett"), "us": ("Ethan", "Carter"),
                  "other": ("Maya", "Okafor")}


def names(country):
    return NAMES.get(country, NAMES["other"])


# A class teacher's end-of-term comment in each report tone.
TEACHER_COMMENTS = {
    "formal": "{name} has worked diligently this {term} and shows a secure understanding across most "
              "{subjects}. Results in {best} were particularly strong. {name} should now give more regular "
              "attention to {weakest} in order to reach the same standard there.",
    "warm": "{name} has had a lovely {term}, bringing curiosity and kindness to the classroom every day. "
            "{best} has been a real highlight, and it has been wonderful to see {name}'s confidence grow. "
            "With a little extra practice in {weakest}, next {term} promises to be even better. Well done!",
    "concise": "A good {term}. Strongest in {best}. Needs regular practice in {weakest}. Keep up the effort.",
}
PRINCIPAL_COMMENT = "A pleasing {term}. Keep working hard and aim high."

SUBJECT_COMMENTS = {
    "high": ["Excellent understanding; keep taking on the extension tasks.", "Consistently strong work and good questions.",
             "A very good term. Well done.", "Confident and accurate. Keep it up."],
    "mid": ["Steady progress; more regular revision will lift results.", "Good effort. Check work carefully before handing in.",
            "Participates well; needs to practise the harder topics.", "Improving. Keep asking for help when stuck."],
    "low": ["Needs more practice with the basics; extra support offered.", "Must complete homework regularly to improve.",
            "Finds this area hard; we will work on it together.", "More focus in class will help a lot."],
}


def band(percent):
    return "high" if percent >= 75 else "mid" if percent >= 50 else "low"
