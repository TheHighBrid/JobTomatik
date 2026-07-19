"""Recurring job-application question families and common option labels.

The catalog is intentionally broader than any one ATS, but it is not treated as a
claim that every employer question can be predicted. Unknown questions continue to
fail closed and require review.
"""

from typing import Any, Dict, List


def _item(
    canonical_key: str,
    label: str,
    category: str,
    sensitivity: str,
    description: str,
    patterns: List[str],
    *,
    setup_group: str,
    suggested_answers: List[str] | None = None,
    fallback_suggestions: List[str] | None = None,
    default_mode: str = "answer",
) -> Dict[str, Any]:
    return {
        "canonical_key": canonical_key,
        "label": label,
        "category": category,
        "sensitivity": sensitivity,
        "description": description,
        "patterns": patterns,
        "setup_group": setup_group,
        "suggested_answers": suggested_answers or [],
        "fallback_suggestions": fallback_suggestions or [],
        "default_mode": default_mode,
    }


QUESTION_CATALOG: List[Dict[str, Any]] = [
    # Legal eligibility and screening
    _item(
        "work_authorization", "Legally authorized to work", "work_authorization", "legal",
        "Whether you are legally authorized to work in the job location.",
        [r"authorized to work", r"legally authorized", r"eligible to work", r"right to work", r"work authorization", r"autorisé[e]? à travailler"],
        setup_group="Eligibility", suggested_answers=["Yes", "No"],
        fallback_suggestions=["Authorized", "Eligible", "I am legally authorized to work"],
    ),
    _item(
        "sponsorship_required", "Requires employer sponsorship", "sponsorship", "legal",
        "Whether you currently or later require visa or immigration sponsorship.",
        [r"require sponsorship", r"visa sponsorship", r"immigration sponsorship", r"need sponsorship", r"sponsorship now or in the future", r"parrainage"],
        setup_group="Eligibility", suggested_answers=["No", "Yes"],
        fallback_suggestions=["I do not require sponsorship", "No sponsorship required"],
    ),
    _item(
        "citizenship_residency", "Citizenship or residency status", "work_authorization", "legal",
        "Citizenship, permanent-residency, or immigration-status question.",
        [r"citizenship status", r"country of citizenship", r"permanent resident", r"residency status", r"immigration status", r"statut de citoyenneté", r"résident permanent"],
        setup_group="Eligibility",
        suggested_answers=["Canadian citizen", "Permanent resident", "Work permit", "Prefer not to answer"],
        fallback_suggestions=["Citizen", "Canada", "Canadian", "Legally entitled to work in Canada"],
    ),
    _item(
        "age_requirement", "Meets legal age requirement", "legal", "legal",
        "Confirmation that you meet a stated legal minimum-age requirement.",
        [r"at least 18", r"minimum age", r"legal age", r"18 years of age", r"age of majority", r"âge légal"],
        setup_group="Eligibility", suggested_answers=["Yes", "No"],
        fallback_suggestions=["I am 18 or older", "I meet the minimum age requirement"],
    ),
    _item(
        "criminal_history", "Criminal history declaration", "legal", "legal",
        "Any criminal-history, conviction, or pardon declaration.",
        [r"criminal record", r"criminal history", r"convicted", r"conviction", r"offence", r"offense", r"casier judiciaire"],
        setup_group="Eligibility", suggested_answers=["No", "Yes", "Prefer not to answer"],
        fallback_suggestions=["No convictions", "Decline to self-identify"],
    ),
    _item(
        "background_check_consent", "Background-check consent", "screening", "legal",
        "Authorization to conduct a lawful background or reference screening.",
        [r"background check", r"background screening", r"pre-employment screening", r"consent to a background", r"vérification des antécédents"],
        setup_group="Eligibility", suggested_answers=["Yes", "No"],
        fallback_suggestions=["I consent", "I agree"],
    ),
    _item(
        "security_clearance", "Security clearance", "screening", "legal",
        "Current clearance level or eligibility to obtain a clearance.",
        [r"security clearance", r"eligible for clearance", r"reliability status", r"secret clearance", r"cote de sécurité", r"fiabilité"],
        setup_group="Eligibility",
        suggested_answers=["None", "Reliability Status", "Secret", "Top Secret", "Eligible to obtain"],
        fallback_suggestions=["No current clearance", "Willing and eligible to obtain clearance"],
    ),
    _item(
        "drivers_license", "Driver's licence", "eligibility", "standard",
        "Whether you hold the driver's licence required for the role.",
        [r"driver'?s licen[cs]e", r"valid licen[cs]e", r"class [a-g][0-9]? licen[cs]e", r"permis de conduire"],
        setup_group="Eligibility", suggested_answers=["Yes", "No", "G", "G2"],
        fallback_suggestions=["Valid driver's licence", "Valid license"],
    ),
    _item(
        "reliable_transportation", "Reliable transportation", "eligibility", "standard",
        "Whether you have reliable transportation when the role requires it.",
        [r"reliable transportation", r"reliable transport", r"own transportation", r"moyen de transport fiable"],
        setup_group="Eligibility", suggested_answers=["Yes", "No"],
        fallback_suggestions=["I have reliable transportation"],
    ),
    _item(
        "professional_license", "Professional licence or registration", "qualification", "legal",
        "A regulated licence, registration, or good-standing requirement.",
        [r"professional licen[cs]e", r"professional registration", r"registered with", r"member in good standing", r"licence professionnelle", r"ordre professionnel"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),

    # Availability and work preferences
    _item(
        "willing_to_relocate", "Willing to relocate", "relocation", "standard",
        "Whether you are willing to relocate for the role.",
        [r"willing to relocate", r"open to relocation", r"relocat(?:e|ion)", r"déménager"],
        setup_group="Work preferences", suggested_answers=["Yes", "No", "Maybe"],
        fallback_suggestions=["Open to relocation", "Willing to relocate"],
    ),
    _item(
        "availability_date", "Availability or start date", "availability", "standard",
        "Your earliest start date or general availability.",
        [r"start date", r"available from", r"availability date", r"earliest.*start", r"date de disponibilité"],
        setup_group="Work preferences",
    ),
    _item(
        "notice_period", "Notice period", "availability", "standard",
        "The notice you must give before starting a new role.",
        [r"notice period", r"how much notice", r"weeks.*notice", r"délai de préavis", r"préavis"],
        setup_group="Work preferences", suggested_answers=["Immediately", "Two weeks", "One month"],
        fallback_suggestions=["Available immediately", "2 weeks", "14 days"],
    ),
    _item(
        "workplace_arrangement", "Remote, hybrid, or on-site preference", "work_arrangement", "standard",
        "Your preferred or accepted workplace arrangement.",
        [r"remote.*hybrid.*on.?site", r"workplace (?:type|preference)", r"work arrangement", r"working model", r"mode de travail"],
        setup_group="Work preferences", suggested_answers=["Hybrid", "Remote", "On-site", "No preference"],
        fallback_suggestions=["Hybrid/Flexible", "Remote eligible", "In office", "Onsite"],
    ),
    _item(
        "onsite_availability", "Available to work on site", "work_arrangement", "standard",
        "Whether you can work at the stated office or work site.",
        [r"work on.?site", r"work in (?:the )?office", r"report to (?:the )?(?:office|site)", r"présentiel"],
        setup_group="Work preferences", suggested_answers=["Yes", "No"],
        fallback_suggestions=["Available on-site", "Able to work in the office"],
    ),
    _item(
        "shift_availability", "Shift availability", "availability", "standard",
        "Availability for day, evening, night, rotating, or split shifts.",
        [r"shift availability", r"available.*shift", r"day shift", r"evening shift", r"night shift", r"rotating shift", r"quart de travail"],
        setup_group="Work preferences", default_mode="ask_each_time",
        suggested_answers=["Days", "Evenings", "Nights", "Rotating", "Any shift"],
    ),
    _item(
        "weekend_availability", "Weekend availability", "availability", "standard",
        "Whether you are available to work weekends or holidays.",
        [r"weekend availability", r"work weekends", r"saturday.*sunday", r"statutory holidays", r"fins de semaine"],
        setup_group="Work preferences", suggested_answers=["Yes", "No", "Occasionally"],
        fallback_suggestions=["Available weekends", "Flexible"],
    ),
    _item(
        "overtime_availability", "Overtime availability", "availability", "standard",
        "Whether you can work overtime when required.",
        [r"work overtime", r"overtime availability", r"additional hours", r"heures supplémentaires"],
        setup_group="Work preferences", suggested_answers=["Yes", "No", "Occasionally"],
    ),
    _item(
        "travel_willingness", "Willingness to travel", "travel", "standard",
        "Whether, and how often, you can travel for work.",
        [r"willing to travel", r"travel requirement", r"percentage.*travel", r"travel up to", r"déplacement"],
        setup_group="Work preferences", suggested_answers=["Yes", "No", "Up to 25%", "Up to 50%"],
        fallback_suggestions=["Willing to travel", "Occasional travel"],
    ),
    _item(
        "employment_type", "Employment type preference", "work_arrangement", "standard",
        "Preference for permanent, contract, temporary, part-time, or full-time work.",
        [r"employment type", r"full.?time.*part.?time", r"permanent.*contract", r"type d'emploi"],
        setup_group="Work preferences", suggested_answers=["Permanent", "Contract", "Full-time", "Part-time", "No preference"],
    ),
    _item(
        "salary_expectation", "Salary expectation", "compensation", "sensitive",
        "Desired salary, compensation range, or pay expectation.",
        [r"salary expectation", r"expected salary", r"desired salary", r"compensation expectation", r"pay expectation", r"desired compensation", r"prétentions salariales"],
        setup_group="Work preferences",
    ),

    # Education, skills, and experience
    _item(
        "highest_education", "Highest education", "education", "standard",
        "Your highest completed education level.",
        [r"highest education", r"highest degree", r"education level", r"level of education", r"niveau d'études"],
        setup_group="Qualifications",
        suggested_answers=["High school", "College diploma", "Bachelor's degree", "Master's degree", "Doctorate"],
        fallback_suggestions=["Diploma", "Associate degree", "Undergraduate degree"],
    ),
    _item(
        "field_of_study", "Field of study", "education", "standard",
        "Your program, major, specialization, or field of study.",
        [r"field of study", r"area of study", r"program of study", r"college major", r"specialization", r"domaine d'études"],
        setup_group="Qualifications",
    ),
    _item(
        "degree_completion", "Degree or diploma completion", "education", "standard",
        "Whether the stated degree, diploma, or program is completed.",
        [r"degree completed", r"completed.*degree", r"diploma completed", r"graduated", r"diplôme obtenu"],
        setup_group="Qualifications", suggested_answers=["Yes", "No", "In progress"],
        fallback_suggestions=["Completed", "Graduated"],
    ),
    _item(
        "certifications", "Certifications", "qualification", "standard",
        "Professional certifications held or currently in progress.",
        [r"certifications?", r"certificates? held", r"professional designation", r"accreditation", r"certification professionnelle"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),
    _item(
        "language_proficiency", "Language proficiency", "qualification", "standard",
        "Languages spoken and the requested proficiency level.",
        [r"language proficiency", r"languages? (?:do you|you) speak", r"fluency", r"proficient in", r"maîtrise.*langue"],
        setup_group="Qualifications", default_mode="ask_each_time",
        suggested_answers=["Native", "Fluent", "Professional working proficiency", "Intermediate", "Basic"],
    ),
    _item(
        "official_language_proficiency", "English or French proficiency", "qualification", "standard",
        "Canadian official-language proficiency or bilingual status.",
        [r"english.*french", r"french.*english", r"official language", r"bilingual", r"anglais.*français", r"français.*anglais"],
        setup_group="Qualifications", suggested_answers=["Bilingual English/French", "English", "French"],
        fallback_suggestions=["Fluent in English and French", "English and French", "Bilingual"],
    ),
    _item(
        "job_specific_experience", "Job-specific experience", "qualification", "standard",
        "A required number of years or level of experience in a named skill or duty.",
        [r"how many years.*experience", r"years of experience (?:do you have )?(?:with|in)", r"experience with", r"experience in", r"années d'expérience"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),

    # Employment relationships and conflicts
    _item(
        "currently_employed", "Currently employed", "employment", "standard",
        "Whether you are currently employed.",
        [r"currently employed", r"presently employed", r"actuellement en emploi"],
        setup_group="Employment", suggested_answers=["Yes", "No"],
    ),
    _item(
        "former_employee", "Former employee", "employment", "standard",
        "Whether you previously worked for this employer or an affiliate.",
        [r"previously worked (?:for|at)", r"former employee", r"ever been employed by", r"worked here before", r"ancien employé"],
        setup_group="Employment", suggested_answers=["No", "Yes"],
    ),
    _item(
        "reason_for_leaving", "Reason for leaving", "employment", "sensitive",
        "Why you left or plan to leave a current or prior employer.",
        [r"reason for leaving", r"why did you leave", r"why are you leaving", r"motif de départ"],
        setup_group="Employment", default_mode="ask_each_time",
    ),
    _item(
        "referral_source", "How you heard about the role", "source", "standard",
        "The source through which you discovered the position.",
        [r"how did you hear", r"how you heard", r"source of application", r"where did you (?:hear|find)", r"comment avez-vous entendu"],
        setup_group="Employment", suggested_answers=["LinkedIn", "Indeed", "Company website", "Employee referral", "Other"],
        fallback_suggestions=["Job board", "Career site", "Online search"],
    ),
    _item(
        "employee_referral", "Employee referral details", "source", "standard",
        "Name or details of the employee who referred you.",
        [r"employee referral", r"who referred you", r"referrer name", r"referred by", r"nom.*référence"],
        setup_group="Employment", default_mode="ask_each_time",
    ),
    _item(
        "relative_at_company", "Relative employed by company", "conflict", "sensitive",
        "Whether a family member or close relation works for the employer.",
        [r"relative.*(?:work|employ)", r"family member.*(?:work|employ)", r"related to (?:an )?employee", r"parent.*employé"],
        setup_group="Employment", suggested_answers=["No", "Yes"],
    ),
    _item(
        "conflict_of_interest", "Conflict of interest", "conflict", "legal",
        "A real or potential conflict-of-interest declaration.",
        [r"conflict of interest", r"potential conflict", r"personal or financial interest", r"conflit d'intérêts"],
        setup_group="Employment", suggested_answers=["No", "Yes"],
    ),
    _item(
        "non_compete_restriction", "Non-compete or restrictive covenant", "conflict", "legal",
        "Whether an agreement could restrict accepting or performing the role.",
        [r"non.?compete", r"restrictive covenant", r"non.?solicitation", r"agreement.*restrict", r"clause de non-concurrence"],
        setup_group="Employment", suggested_answers=["No", "Yes", "Unsure"],
    ),

    # Voluntary demographics. These always require the user's explicit answer.
    _item(
        "gender_identity", "Gender identity or sex", "demographic", "sensitive",
        "Voluntary gender, sex, or gender-identity disclosure.",
        [r"gender identity", r"gender", r"\bsex\b", r"identité de genre", r"\bsexe\b"],
        setup_group="Voluntary demographics",
        suggested_answers=["Male", "Female", "Non-binary", "Another gender", "Prefer not to answer"],
        fallback_suggestions=["Man", "Woman", "M", "F", "Decline to self-identify"],
    ),
    _item(
        "pronouns", "Pronouns", "demographic", "sensitive",
        "Pronouns you want the employer to use.",
        [r"pronouns?", r"preferred pronouns?", r"personal pronouns?"],
        setup_group="Voluntary demographics",
        suggested_answers=["He/him", "She/her", "They/them", "Prefer not to answer"],
    ),
    _item(
        "race_ethnicity", "Race or ethnicity", "demographic", "sensitive",
        "Voluntary race, ethnicity, or racial-background disclosure.",
        [r"race and ethnicity", r"race/ethnicity", r"racial background", r"ethnic background", r"racial or ethnic", r"origine ethnique"],
        setup_group="Voluntary demographics",
        suggested_answers=[
            "Black", "Middle Eastern or North African", "Asian",
            "Hispanic or Latino", "White", "Indigenous",
            "Two or more races", "Prefer not to answer",
        ],
        fallback_suggestions=[
            "Black or African American", "Black or African descent", "African",
            "North African", "Middle Eastern", "Middle Eastern or North African (MENA)",
            "Arab", "West Asian or North African", "American Indian or Alaska Native",
            "Native Hawaiian or Other Pacific Islander", "Decline to self-identify",
        ],
    ),
    _item(
        "visible_minority", "Visible-minority or racialized-group status", "demographic", "sensitive",
        "Canadian employment-equity visible-minority or racialized-group disclosure.",
        [r"visible minority", r"racialized (?:group|person)", r"member of a racialized", r"minorité visible"],
        setup_group="Voluntary demographics",
        suggested_answers=["Yes", "No", "Prefer not to answer"],
        fallback_suggestions=["Member of a visible minority", "Racialized person", "Decline to self-identify"],
    ),
    _item(
        "indigenous_identity", "Indigenous identity", "demographic", "sensitive",
        "Voluntary First Nations, Inuit, Métis, or Indigenous identity disclosure.",
        [r"indigenous", r"first nations", r"métis", r"\binuit\b", r"aboriginal", r"autochtone"],
        setup_group="Voluntary demographics",
        suggested_answers=["No", "First Nations", "Métis", "Inuit", "Prefer not to answer"],
        fallback_suggestions=["Not Indigenous", "Decline to self-identify"],
    ),
    _item(
        "veteran_status", "Veteran status", "demographic", "sensitive",
        "Voluntary veteran, protected-veteran, or military-service disclosure.",
        [r"veteran status", r"protected veteran", r"military service", r"served in the (?:military|armed forces)", r"ancien combattant"],
        setup_group="Voluntary demographics",
        suggested_answers=["I am not a veteran", "I am a veteran", "Prefer not to answer"],
        fallback_suggestions=["Not a protected veteran", "No military service", "Decline to self-identify"],
    ),
    _item(
        "disability_status", "Disability status", "demographic", "sensitive",
        "Voluntary disability self-identification.",
        [r"disability status", r"person with a disability", r"do you have a disability", r"disabled", r"handicap", r"personne en situation de handicap"],
        setup_group="Voluntary demographics",
        suggested_answers=["No", "Yes", "I do not wish to answer"],
        fallback_suggestions=["I do not have a disability", "Prefer not to answer", "Decline to self-identify"],
    ),
    _item(
        "accommodation_required", "Application or workplace accommodation", "accommodation", "sensitive",
        "Whether you need an accommodation during hiring or to perform the role.",
        [r"require an accommodation", r"need an accommodation", r"accommodation.*(?:interview|application|work)", r"reasonable accommodation", r"mesure d'adaptation"],
        setup_group="Voluntary demographics", suggested_answers=["No", "Yes", "Prefer to discuss later"],
        fallback_suggestions=["No accommodation required", "I will contact recruiting if needed"],
    ),
    _item(
        "sexual_orientation", "Sexual orientation", "demographic", "sensitive",
        "Voluntary sexual-orientation disclosure.",
        [r"sexual orientation", r"orientation sexuelle", r"lgbtq", r"2slgbtq"],
        setup_group="Voluntary demographics", default_mode="decline",
        suggested_answers=["Prefer not to answer", "Heterosexual", "Gay", "Lesbian", "Bisexual", "Another orientation"],
        fallback_suggestions=["Decline to self-identify", "I do not wish to answer"],
    ),

    # Consent and future contact
    _item(
        "terms_consent", "Application declaration or terms", "consent", "legal",
        "Consent to application terms, declarations, accuracy statements, or attestations.",
        [
            r"i certify", r"i acknowledge", r"terms and conditions",
            r"(?:i )?agree to (?:the )?(?:application )?terms", r"application terms",
            r"information.*(?:true|accurate|complete)", r"attest", r"j'accepte",
            r"je certifie",
        ],
        setup_group="Consent", suggested_answers=["Yes", "I agree"],
        fallback_suggestions=["Agree", "Accepted", "I certify"],
    ),
    _item(
        "data_processing_consent", "Applicant-data processing consent", "consent", "legal",
        "Consent to processing applicant data for the current application.",
        [
            r"process my data", r"processing.*applicant data", r"privacy consent",
            r"privacy (?:policy|notice)", r"data processing", r"traitement de mes données",
        ],
        setup_group="Consent", suggested_answers=["Yes", "I agree"],
        fallback_suggestions=["Consent", "I consent to processing"],
    ),
    _item(
        "data_retention_consent", "Applicant-data retention consent", "consent", "legal",
        "Consent to retain applicant data for a stated period or future use.",
        [r"retain my data", r"store my data", r"data retention", r"keep my (?:application|information)", r"conserver mes données"],
        setup_group="Consent", suggested_answers=["Yes", "No"],
        fallback_suggestions=["I consent", "Do not retain"],
    ),
    _item(
        "future_opportunities_consent", "Contact for future opportunities", "consent", "standard",
        "Whether the employer may contact you about future jobs.",
        [r"future opportunities", r"future job openings", r"talent community", r"contact me about other", r"occasions futures"],
        setup_group="Consent", suggested_answers=["Yes", "No"],
        fallback_suggestions=["Keep me in the talent pool", "Do not contact me about other roles"],
    ),
    _item(
        "marketing_consent", "Recruiting marketing consent", "consent", "standard",
        "Consent to recruiting newsletters or marketing communications.",
        [r"marketing communications", r"recruiting marketing", r"newsletter", r"promotional email", r"communications marketing"],
        setup_group="Consent", suggested_answers=["No", "Yes"],
        fallback_suggestions=["Do not subscribe", "Opt out"],
    ),
    _item(
        "ai_processing_consent", "AI-assisted application processing", "consent", "legal",
        "Consent or opt-out choice for automated or AI-assisted applicant review.",
        [r"artificial intelligence", r"ai-assisted", r"automated decision", r"automated processing", r"opt out.*ai", r"intelligence artificielle"],
        setup_group="Consent", default_mode="ask_each_time",
    ),
    _item(
        "reference_check_consent", "Reference-check consent", "consent", "legal",
        "Permission to contact references or verify employment.",
        [r"contact (?:my )?references", r"reference check", r"verify my employment", r"vérification des références"],
        setup_group="Consent", suggested_answers=["Yes", "No", "Ask me first"],
        fallback_suggestions=["I consent", "Contact me before contacting references"],
    ),

    # Employer-specific narrative questions are classified but should not reuse a
    # canned response unless the user creates and confirms one deliberately.
    _item(
        "why_this_role", "Why this role", "narrative", "standard",
        "Why you are interested in this position.",
        [r"why (?:are you interested|do you want).*(?:role|position|job)", r"interest in this (?:role|position)", r"pourquoi.*poste"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "why_this_company", "Why this company", "narrative", "standard",
        "Why you want to work for the employer.",
        [r"why (?:do you want|would you like) to work (?:for|at|with)", r"why our company", r"why join us", r"pourquoi.*entreprise"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "key_achievement", "Relevant achievement", "narrative", "standard",
        "A job-relevant achievement, example, or accomplishment.",
        [r"greatest achievement", r"key achievement", r"relevant accomplishment", r"example of (?:a time|when)", r"réalisation"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "employment_gap", "Employment gap explanation", "employment", "sensitive",
        "Explanation for a gap or break in employment.",
        [r"employment gap", r"gap in (?:your )?employment", r"career break", r"interruption.*emploi"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "additional_information", "Additional information", "narrative", "standard",
        "Optional information or comments not captured elsewhere.",
        [r"additional information", r"anything else", r"additional comments", r"other information", r"renseignements supplémentaires"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
]
