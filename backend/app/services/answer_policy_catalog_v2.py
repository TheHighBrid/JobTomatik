"""Application Question Catalog V2.

These entries refine ambiguous legacy families and add recurring employer-question
families observed across common ATS workflows. More specific V2 definitions are
loaded before the legacy catalog. Dynamic or narrative questions default to
``ask_each_time`` so recognition does not become guessed reuse.
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


V2_QUESTION_CATALOG: List[Dict[str, Any]] = [
    # Eligibility, immigration, screening, and compliance
    _item(
        "sponsorship_required", "Requires employer sponsorship", "sponsorship", "legal",
        "Whether employer sponsorship is required, without a separate future-only qualifier.",
        [r"do you require (?:employer )?sponsorship", r"require visa sponsorship", r"need (?:employer )?sponsorship", r"immigration sponsorship required"],
        setup_group="Eligibility", suggested_answers=["No", "Yes"],
        fallback_suggestions=["I do not require sponsorship", "No sponsorship required"],
    ),
    _item(
        "sponsorship_future_required", "Future sponsorship requirement", "sponsorship", "legal",
        "Whether you will require visa or immigration sponsorship in the future.",
        [r"will you (?:now or )?in the future require.{0,40}sponsorship", r"future.{0,50}sponsorship", r"later require.{0,40}sponsorship"],
        setup_group="Eligibility", suggested_answers=["No", "Yes"],
        fallback_suggestions=["I will not require future sponsorship"],
    ),
    _item(
        "citizenship_status", "Citizenship status", "work_authorization", "legal",
        "Your citizenship or country of citizenship.",
        [r"citizenship status", r"country of citizenship", r"what is your citizenship", r"are you a (?:canadian|u\.s\.|us|british) citizen", r"statut de citoyenneté"],
        setup_group="Eligibility", default_mode="ask_each_time",
    ),
    _item(
        "permanent_residency_status", "Permanent-residency status", "work_authorization", "legal",
        "Whether you hold permanent-resident status in the relevant country.",
        [r"permanent resident status", r"are you a permanent resident", r"hold permanent residency", r"résident permanent"],
        setup_group="Eligibility", suggested_answers=["Yes", "No"],
    ),
    _item(
        "immigration_status", "Immigration status", "work_authorization", "legal",
        "Your current immigration category or legal status when specifically requested.",
        [r"current immigration status", r"what is your immigration status", r"immigration category", r"statut d'immigration"],
        setup_group="Eligibility", default_mode="ask_each_time",
    ),
    _item(
        "work_permit_status", "Work permit or visa status", "work_authorization", "legal",
        "Whether you hold a current work permit, visa, or equivalent work document.",
        [r"work permit status", r"current work permit", r"current work visa", r"type of work permit", r"visa status", r"permis de travail"],
        setup_group="Eligibility", default_mode="ask_each_time",
    ),
    _item(
        "security_clearance", "Current security clearance", "screening", "legal",
        "A clearance you currently hold, including its level.",
        [r"current security clearance", r"what security clearance do you (?:currently )?hold", r"hold (?:a )?(?:reliability|secret|top secret) clearance", r"clearance level"],
        setup_group="Eligibility", suggested_answers=["None", "Reliability Status", "Secret", "Top Secret"],
        fallback_suggestions=["No current clearance"],
    ),
    _item(
        "security_clearance_eligibility", "Eligible to obtain security clearance", "screening", "legal",
        "Whether you are eligible or willing to obtain a required clearance.",
        [r"eligible to obtain.{0,40}(?:security )?clearance", r"able to obtain.{0,40}(?:security )?clearance", r"willing to obtain.{0,40}(?:security )?clearance", r"qualify for.{0,40}clearance"],
        setup_group="Eligibility", suggested_answers=["Yes", "No", "Unsure"],
    ),
    _item(
        "export_control_eligibility", "Export-control eligibility", "screening", "legal",
        "Eligibility under export-control or controlled-technology requirements.",
        [r"export control", r"itar", r"ear controlled", r"controlled technology", r"export compliance"],
        setup_group="Eligibility", default_mode="ask_each_time",
    ),
    _item(
        "essential_functions_ability", "Able to perform essential job functions", "screening", "legal",
        "Whether you can perform the role's essential functions, with or without accommodation.",
        [r"perform (?:the )?essential functions", r"essential duties.{0,50}(?:with or without )?accommodation", r"able to perform.{0,60}job functions"],
        setup_group="Eligibility", default_mode="ask_each_time",
        suggested_answers=["Yes", "No", "With accommodation"],
    ),
    _item(
        "physical_requirements", "Physical-requirement capability", "screening", "sensitive",
        "Ability to meet a stated lifting, standing, mobility, or other physical requirement.",
        [r"able to lift.{0,30}(?:lbs?|pounds?|kg)", r"stand for.{0,30}hours", r"physical requirements", r"physical demands"],
        setup_group="Eligibility", default_mode="ask_each_time",
    ),
    _item(
        "drug_screening_consent", "Drug-screening consent", "screening", "legal",
        "Consent or willingness to complete a lawful pre-employment drug screen.",
        [r"drug test", r"drug screening", r"substance screening", r"pre-employment drug"],
        setup_group="Eligibility", default_mode="ask_each_time",
        suggested_answers=["Yes", "No"],
    ),
    _item(
        "credit_check_consent", "Credit-check consent", "screening", "legal",
        "Consent to a lawful employment-related credit check when required.",
        [r"credit check", r"credit screening", r"credit history check"],
        setup_group="Eligibility", default_mode="ask_each_time",
        suggested_answers=["Yes", "No"],
    ),
    _item(
        "driving_record_check_consent", "Driving-record check consent", "screening", "legal",
        "Consent to a motor-vehicle or driving-record check.",
        [r"driving record", r"motor vehicle record", r"mvr check", r"driver abstract"],
        setup_group="Eligibility", default_mode="ask_each_time",
        suggested_answers=["Yes", "No"],
    ),
    _item(
        "employment_verification_consent", "Employment-verification consent", "consent", "legal",
        "Permission to verify prior employment, separate from contacting references.",
        [r"verify (?:my |your )?(?:prior )?employment", r"employment verification", r"verify employment history"],
        setup_group="Consent", default_mode="ask_each_time",
        suggested_answers=["Yes", "No", "Ask me first"],
    ),
    _item(
        "education_verification_consent", "Education-verification consent", "consent", "legal",
        "Permission to verify education or credentials.",
        [r"verify (?:my |your )?education", r"education verification", r"verify (?:my |your )?(?:degree|diploma|credentials)"],
        setup_group="Consent", default_mode="ask_each_time",
        suggested_answers=["Yes", "No", "Ask me first"],
    ),
    _item(
        "confidentiality_agreement", "Confidentiality or NDA acknowledgement", "consent", "legal",
        "Acknowledgement of a confidentiality, proprietary-information, or NDA requirement.",
        [r"non-disclosure agreement", r"nondisclosure agreement", r"confidentiality agreement", r"proprietary information agreement", r"nda"],
        setup_group="Consent", default_mode="ask_each_time",
    ),
    _item(
        "vaccination_requirement", "Vaccination requirement", "screening", "sensitive",
        "A role-specific vaccination or immunization requirement.",
        [r"vaccination requirement", r"proof of vaccination", r"immunization requirement", r"vaccinated against"],
        setup_group="Eligibility", default_mode="ask_each_time",
    ),

    # Compensation and work preferences
    _item(
        "salary_expectation", "Base salary expectation", "compensation", "sensitive",
        "Desired base salary or salary range, excluding explicitly total-compensation questions.",
        [r"salary expectation", r"expected salary", r"desired salary", r"base salary expectation", r"desired base salary", r"salary range are you seeking", r"prétentions salariales"],
        setup_group="Compensation",
    ),
    _item(
        "compensation_expectation", "Compensation expectation", "compensation", "sensitive",
        "Desired compensation when the employer does not specify base salary versus total compensation.",
        [r"compensation expectation", r"expected compensation", r"desired compensation", r"pay expectation", r"compensation are you seeking"],
        setup_group="Compensation",
    ),
    _item(
        "total_compensation_expectation", "Total compensation expectation", "compensation", "sensitive",
        "Desired total compensation including bonus, equity, commission, or other variable pay.",
        [r"total compensation expectation", r"expected total compensation", r"desired total compensation", r"total comp", r"overall compensation package", r"base.{0,30}(?:bonus|equity|commission).{0,30}expect"],
        setup_group="Compensation",
    ),
    _item(
        "current_salary", "Current base salary", "compensation", "sensitive",
        "Current or most recent base salary when explicitly requested.",
        [r"current salary", r"present salary", r"most recent salary", r"current base salary"],
        setup_group="Compensation", default_mode="ask_each_time",
    ),
    _item(
        "current_total_compensation", "Current total compensation", "compensation", "sensitive",
        "Current total compensation or pay package when explicitly requested.",
        [r"current total compensation", r"current total comp", r"present total compensation", r"current compensation package"],
        setup_group="Compensation", default_mode="ask_each_time",
    ),
    _item(
        "hourly_rate_expectation", "Hourly-rate expectation", "compensation", "sensitive",
        "Desired hourly wage or contract rate.",
        [r"hourly rate expectation", r"expected hourly rate", r"desired hourly rate", r"hourly pay expectation", r"rate per hour"],
        setup_group="Compensation",
    ),
    _item(
        "compensation_negotiable", "Compensation negotiability", "compensation", "sensitive",
        "Whether your compensation expectation is negotiable or flexible.",
        [r"salary.{0,40}negotiable", r"compensation.{0,40}negotiable", r"flexible on.{0,30}(?:salary|compensation|pay)", r"open to negotiating.{0,30}(?:salary|compensation)"],
        setup_group="Compensation", suggested_answers=["Yes", "No", "Depends on total package"],
    ),
    _item(
        "commute_ability", "Able to commute to work location", "location", "standard",
        "Whether you can reliably commute to the stated work location.",
        [r"able to commute", r"reliably commute", r"commute to.{0,80}(?:office|location|site)", r"reasonable commuting distance"],
        setup_group="Work preferences", suggested_answers=["Yes", "No"],
    ),
    _item(
        "preferred_work_location", "Preferred work location", "location", "standard",
        "Your preferred office, city, region, or listed work location.",
        [r"preferred work location", r"preferred office", r"which location do you prefer", r"location preference", r"preferred city"],
        setup_group="Work preferences", default_mode="ask_each_time",
    ),
    _item(
        "multiple_location_availability", "Available across multiple locations", "location", "standard",
        "Whether you can work from multiple employer locations or branches.",
        [r"work at multiple locations", r"work across multiple locations", r"available at other locations", r"work at any of our locations"],
        setup_group="Work preferences", suggested_answers=["Yes", "No", "Some locations"],
    ),
    _item(
        "relocation_assistance", "Relocation assistance needed", "relocation", "sensitive",
        "Whether accepting the role would require relocation assistance.",
        [r"require relocation assistance", r"need relocation assistance", r"relocation support", r"relocation package"],
        setup_group="Work preferences", suggested_answers=["No", "Yes", "Open to discuss"],
    ),
    _item(
        "remote_workspace", "Suitable remote workspace", "work_arrangement", "standard",
        "Whether you have a suitable private or reliable workspace for remote work.",
        [r"dedicated workspace", r"suitable home office", r"private workspace", r"remote work environment", r"quiet workspace"],
        setup_group="Work preferences", suggested_answers=["Yes", "No"],
    ),
    _item(
        "remote_equipment", "Remote-work equipment or internet", "work_arrangement", "standard",
        "Whether you have required internet, computer, headset, or remote-work equipment.",
        [r"reliable internet", r"high-speed internet", r"own computer", r"remote work equipment", r"headset.{0,30}internet"],
        setup_group="Work preferences", default_mode="ask_each_time",
    ),
    _item(
        "hours_per_week", "Hours per week availability", "availability", "standard",
        "The number or range of hours you can work each week.",
        [r"how many hours.{0,20}(?:per|a) week", r"hours per week.{0,30}available", r"weekly hours.{0,30}available"],
        setup_group="Work preferences", default_mode="ask_each_time",
    ),
    _item(
        "schedule_availability", "Specific schedule availability", "availability", "standard",
        "Availability for specifically stated days or working hours.",
        [r"available to work.{0,80}(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)", r"available between.{0,50}(?:am|pm)", r"specific availability", r"what days.{0,40}available"],
        setup_group="Work preferences", default_mode="ask_each_time",
    ),
    _item(
        "on_call_availability", "On-call availability", "availability", "standard",
        "Whether you can participate in an on-call or standby rotation.",
        [r"on-call", r"on call rotation", r"standby rotation", r"after-hours rotation"],
        setup_group="Work preferences", suggested_answers=["Yes", "No", "Occasionally"],
    ),
    _item(
        "interview_availability", "Interview availability", "availability", "standard",
        "Your availability for interviews rather than your employment start date.",
        [r"availability for (?:an )?interview", r"available to interview", r"interview times", r"schedule an interview"],
        setup_group="Work preferences", default_mode="ask_each_time",
    ),

    # Skills, tools, and experience. These are recognized but intentionally fresh-review by default.
    _item(
        "skill_experience", "Experience with a named skill", "qualification", "standard",
        "Whether you have experience with a specifically named skill, method, or domain.",
        [r"do you have experience (?:with|using).{2,100}", r"experience (?:with|using).{2,100}\??$"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),
    _item(
        "skill_years_experience", "Years with a named skill", "qualification", "standard",
        "Years of experience with a specifically named skill, method, platform, or duty.",
        [r"how many years.{0,30}experience.{0,30}(?:with|using|in).{2,100}", r"years of experience.{0,30}(?:with|using|in).{2,100}"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),
    _item(
        "tool_proficiency", "Proficiency with a named tool", "qualification", "standard",
        "Your proficiency level with a specifically named software product, system, or tool.",
        [r"proficiency (?:with|using|in).{2,100}", r"how proficient are you.{0,30}(?:with|using|in).{2,100}", r"rate your proficiency.{2,100}"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),
    _item(
        "industry_experience", "Industry experience", "qualification", "standard",
        "Experience in a specifically named industry or sector.",
        [r"experience (?:working )?in (?:the )?.{2,70} industry", r"experience in (?:the )?.{2,70} sector", r"industry experience"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),
    _item(
        "management_experience", "People-management experience", "qualification", "standard",
        "Whether you have direct people-management, supervisory, or team-lead experience.",
        [r"people management experience", r"management experience", r"supervisory experience", r"managed (?:a )?team", r"led (?:a )?team"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),
    _item(
        "management_years", "Years of management experience", "qualification", "standard",
        "Years of direct people-management or supervisory experience.",
        [r"how many years.{0,30}(?:management|supervisory|people management)", r"years of (?:management|supervisory|people management) experience"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),
    _item(
        "team_size_managed", "Largest team size managed", "qualification", "standard",
        "The number of direct reports or largest team you have managed.",
        [r"how many (?:direct reports|people).{0,40}(?:manage|managed|supervise)", r"largest team.{0,30}(?:managed|led)", r"team size.{0,30}(?:managed|supervised)"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),
    _item(
        "gpa", "GPA or academic average", "education", "sensitive",
        "A grade-point average or academic average requested by the employer.",
        [r"\bgpa\b", r"grade point average", r"academic average"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),
    _item(
        "typing_speed", "Typing speed", "qualification", "standard",
        "Typing speed or keyboarding rate.",
        [r"typing speed", r"words per minute", r"\bwpm\b", r"keyboarding speed"],
        setup_group="Qualifications", default_mode="ask_each_time",
    ),

    # Employment history and employer-contact decisions
    _item(
        "prior_application", "Previously applied to employer", "employment", "standard",
        "Whether you previously applied for a role with this employer or affiliate.",
        [r"previously applied (?:to|for|with)", r"applied (?:to|for).{0,50}before", r"ever applied (?:to|with)"],
        setup_group="Employment", suggested_answers=["No", "Yes"],
    ),
    _item(
        "prior_interview", "Previously interviewed by employer", "employment", "standard",
        "Whether you previously interviewed with this employer or affiliate.",
        [r"previously interviewed", r"interviewed (?:with|at).{0,50}before", r"ever interviewed (?:with|at)"],
        setup_group="Employment", suggested_answers=["No", "Yes"],
    ),
    _item(
        "termination_history", "Termination or dismissal history", "employment", "sensitive",
        "Whether you have been terminated, dismissed, or asked to resign when specifically asked.",
        [r"ever been terminated", r"ever been dismissed", r"asked to resign", r"fired from (?:a )?job"],
        setup_group="Employment", default_mode="ask_each_time",
    ),
    _item(
        "rehire_eligibility", "Eligible for rehire", "employment", "sensitive",
        "Whether a former employer has indicated you are eligible for rehire.",
        [r"eligible for rehire", r"rehire eligibility", r"eligible to be rehired"],
        setup_group="Employment", default_mode="ask_each_time",
    ),
    _item(
        "current_employer_contact", "Permission to contact current employer", "consent", "sensitive",
        "Whether the prospective employer may contact your current employer.",
        [r"contact (?:my |your )?current employer", r"may we contact.{0,30}current employer", r"permission.{0,40}current employer"],
        setup_group="Employment", suggested_answers=["No", "Yes", "Ask me first"],
    ),
    _item(
        "former_employer_contact", "Permission to contact former employers", "consent", "sensitive",
        "Whether the prospective employer may contact prior employers.",
        [r"contact (?:my |your )?(?:former|previous|prior) employers?", r"may we contact.{0,30}(?:former|previous|prior) employers?"],
        setup_group="Employment", suggested_answers=["Yes", "No", "Ask me first"],
    ),
    _item(
        "reason_for_job_search", "Reason for job search", "employment", "sensitive",
        "Why you are currently seeking a new opportunity, distinct from why you left a specific employer.",
        [r"why are you looking for (?:a )?new (?:role|job|opportunity)", r"reason for (?:your )?job search", r"why are you seeking.{0,30}new opportunity"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),

    # Voluntary demographics split into narrower concepts.
    _item(
        "gender_identity", "Gender identity", "demographic", "sensitive",
        "Voluntary gender-identity disclosure, distinct from sexual orientation and legal/assigned sex.",
        [r"gender identity", r"what is your gender", r"how do you identify your gender", r"identité de genre"],
        setup_group="Voluntary demographics",
        suggested_answers=["Male", "Female", "Non-binary", "Another gender", "Prefer not to answer"],
        fallback_suggestions=["Man", "Woman", "M", "F", "Decline to self-identify"],
    ),
    _item(
        "sex_identity", "Sex or legal sex", "demographic", "sensitive",
        "Voluntary or legally requested sex disclosure when the form specifically asks sex rather than gender identity.",
        [r"sex assigned at birth", r"legal sex", r"what is your sex", r"\bsex\s*\*?$", r"\bsexe\b"],
        setup_group="Voluntary demographics", default_mode="ask_each_time",
        suggested_answers=["Male", "Female", "Intersex", "Prefer not to answer"],
    ),
    _item(
        "race_ethnicity", "Combined race and ethnicity", "demographic", "sensitive",
        "A combined race-and-ethnicity disclosure question.",
        [r"race and ethnicity", r"race/ethnicity", r"racial and ethnic", r"race or ethnicity", r"racial or ethnic"],
        setup_group="Voluntary demographics", default_mode="decline",
        suggested_answers=["Prefer not to answer"],
        fallback_suggestions=["Decline to self-identify"],
    ),
    _item(
        "race_identity", "Race", "demographic", "sensitive",
        "Voluntary race or racial-background disclosure when asked separately from ethnicity.",
        [r"what is your race", r"select your race", r"racial background", r"\brace\b"],
        setup_group="Voluntary demographics", default_mode="decline",
        suggested_answers=["Prefer not to answer"],
    ),
    _item(
        "ethnicity_identity", "Ethnicity", "demographic", "sensitive",
        "Voluntary ethnicity or ethnic-background disclosure when asked separately from race.",
        [r"what is your ethnicity", r"select your ethnicity", r"ethnic background", r"ethnicity"],
        setup_group="Voluntary demographics", default_mode="decline",
        suggested_answers=["Prefer not to answer"],
    ),
    _item(
        "hispanic_latino_identity", "Hispanic or Latino identity", "demographic", "sensitive",
        "Voluntary Hispanic, Latino, or Spanish-origin disclosure.",
        [r"hispanic or latino", r"hispanic/latino", r"latino or hispanic", r"spanish origin"],
        setup_group="Voluntary demographics", default_mode="decline",
        suggested_answers=["No", "Yes", "Prefer not to answer"],
    ),
    _item(
        "religion_belief", "Religion or belief", "demographic", "sensitive",
        "Voluntary religion, faith, or belief disclosure where collected for monitoring purposes.",
        [r"religion or belief", r"religious belief", r"what is your religion", r"faith or belief"],
        setup_group="Voluntary demographics", default_mode="decline",
        suggested_answers=["Prefer not to answer"],
    ),
    _item(
        "age_demographic", "Age or age band", "demographic", "sensitive",
        "Voluntary age or age-band disclosure, distinct from a legal minimum-age eligibility check.",
        [r"age range", r"age band", r"what is your age", r"select your age", r"date of birth.{0,30}diversity"],
        setup_group="Voluntary demographics", default_mode="decline",
        suggested_answers=["Prefer not to answer"],
    ),

    # Recurring narrative and behavioral question taxonomy. Recognize, do not canned-reuse.
    _item(
        "role_fit", "Why you are a strong fit", "narrative", "standard",
        "Why your background makes you a strong match for the role.",
        [r"why are you a (?:good|strong|great) fit", r"why should we hire you", r"what makes you (?:a )?(?:good|strong) candidate"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "relevant_project", "Relevant project or example", "narrative", "standard",
        "A project or piece of work relevant to the role.",
        [r"describe (?:a )?(?:relevant )?project", r"tell us about (?:a )?project", r"project most relevant"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "career_goals", "Career goals", "narrative", "standard",
        "Your short- or long-term career goals.",
        [r"career goals", r"where do you see yourself", r"professional goals", r"long-term goals"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "strengths", "Professional strengths", "narrative", "standard",
        "Your strengths or strongest professional qualities.",
        [r"greatest strengths", r"what are your strengths", r"top strengths", r"strongest qualities"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "weakness", "Development area or weakness", "narrative", "sensitive",
        "A weakness, growth area, or development priority.",
        [r"greatest weakness", r"what is your weakness", r"development area", r"area for improvement"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "teamwork_example", "Teamwork example", "narrative", "standard",
        "An example of collaboration or teamwork.",
        [r"example.{0,40}(?:teamwork|collaboration)", r"time you worked (?:on|with).{0,30}team", r"collaborated with"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "leadership_example", "Leadership example", "narrative", "standard",
        "An example demonstrating leadership or influence.",
        [r"example.{0,40}leadership", r"time you (?:led|influenced)", r"demonstrated leadership"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "conflict_example", "Conflict-resolution example", "narrative", "standard",
        "An example of handling disagreement or workplace conflict.",
        [r"time you (?:handled|resolved).{0,30}conflict", r"workplace conflict", r"disagreement with.{0,30}(?:coworker|colleague|manager)"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "difficult_customer_example", "Difficult customer example", "narrative", "standard",
        "An example of handling a difficult customer, client, or stakeholder.",
        [r"difficult (?:customer|client|stakeholder)", r"challenging (?:customer|client)", r"upset customer"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "deadline_example", "Deadline or prioritization example", "narrative", "standard",
        "An example of meeting a tight deadline or prioritizing competing work.",
        [r"tight deadline", r"competing priorities", r"multiple deadlines", r"prioritize your work"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "failure_learning", "Failure or lesson learned", "narrative", "sensitive",
        "An example of a failure, mistake, or lesson learned.",
        [r"time you failed", r"mistake you made", r"lesson you learned", r"learned from failure"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "feedback_example", "Feedback example", "narrative", "standard",
        "An example of receiving, giving, or acting on feedback.",
        [r"received feedback", r"constructive feedback", r"acted on feedback", r"give feedback"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "initiative_example", "Initiative example", "narrative", "standard",
        "An example of taking initiative without being asked.",
        [r"took initiative", r"showed initiative", r"without being asked", r"went above and beyond"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "process_improvement", "Process-improvement example", "narrative", "standard",
        "An example of improving a process, workflow, control, or outcome.",
        [r"improved (?:a )?process", r"process improvement", r"made.{0,30}(?:process|workflow).{0,30}better", r"efficiency improvement"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "problem_solving_example", "Problem-solving example", "narrative", "standard",
        "An example of diagnosing and solving a difficult problem.",
        [r"difficult problem.{0,30}solv", r"complex problem.{0,30}solv", r"problem-solving example", r"how did you solve"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "work_environment_preference", "Preferred work environment", "narrative", "standard",
        "The work environment or team culture in which you perform best.",
        [r"ideal work environment", r"preferred work environment", r"environment do you work best", r"team culture.{0,30}prefer"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
    _item(
        "management_style", "Management or leadership style", "narrative", "standard",
        "Your preferred management style or your own leadership approach.",
        [r"management style", r"leadership style", r"how do you manage", r"how do you lead"],
        setup_group="Narrative questions", default_mode="ask_each_time",
    ),
]
