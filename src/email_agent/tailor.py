"""Resume tailor.

Hard rule: never invent or change figures, employers, dates, titles, schools,
or technologies. Only rephrase, reorder, and reweight what's already in the
master resume to better match the job description.

Uses Anthropic prompt caching: the master resume + system prompt are cached
across calls in a run, so per-job marginal cost is just the job description
plus the tailored output.
"""

from typing import Optional

import anthropic

from .models import JobPosting, TailoredResume


SYSTEM_PROMPT = """You are a resume editor. You receive a candidate's master resume and a job description. Produce a tailored resume optimized for the role.

ABSOLUTE RULES — violations are unacceptable:
1. NEVER fabricate or alter figures, percentages, dollar amounts, dates, employer names, job titles, school names, degrees, or technologies. If a number isn't in the master resume, it does not appear in the output.
2. NEVER add experience, skills, or accomplishments that are not present in the master resume in some form.
3. NEVER change the candidate's actual title at any employer. You may add a parenthetical clarification if it's clearly supported by the master resume content (e.g. "Product Manager (Data Platform)").
4. You MAY rephrase bullets, reorder them, drop ones that aren't relevant, and choose vocabulary that matches the job's language.
5. You MAY consolidate or split bullets, as long as the underlying facts come from the master resume.
6. You MAY rewrite the Summary section to emphasize aspects of the candidate's background most relevant to the role.

The goal is to pass automated screeners (ATS keyword matching) and grab a recruiter's attention in 6 seconds. Mirror the job's vocabulary where it's accurate to do so.

Output format: return the tailored resume in clean Markdown. No commentary, no explanation, no preamble — just the resume. Then a separator line `---` and a 2-3 sentence cover blurb tailored to this role (also drawing only from facts in the master resume)."""


def tailor_resume(
    job: JobPosting,
    master_resume: str,
    client: anthropic.Anthropic,
    model: str = "claude-opus-4-7",
) -> TailoredResume:
    # The system prompt + master resume are stable across calls in a run, so
    # cache them with cache_control. Per-job marginal cost is the job text
    # plus the tailored output. See SKILL.md prompt-caching guidance.
    system_blocks = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
        },
        {
            "type": "text",
            "text": f"<master_resume>\n{master_resume}\n</master_resume>",
            "cache_control": {"type": "ephemeral"},
        },
    ]

    user = (
        f"Tailor the resume for this role:\n\n"
        f"Company: {job.company}\n"
        f"Title: {job.title}\n"
        f"Location: {job.location or 'unspecified'}\n"
        f"URL: {job.url}\n\n"
        f"Job description:\n{(job.description or '').strip() or '(no description available; use the title and company to infer focus)'}\n"
    )

    # Stream so we don't trip the SDK's HTTP-timeout guard at higher max_tokens.
    with client.messages.stream(
        model=model,
        max_tokens=8000,
        system=system_blocks,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        message = stream.get_final_message()

    text = next((b.text for b in message.content if b.type == "text"), "")
    resume_md, _, blurb = text.partition("\n---\n")
    return TailoredResume(
        job=job,
        markdown=resume_md.strip(),
        cover_blurb=blurb.strip(),
    )
