# PASTE YOUR RESUME HERE

The agent reads this file as your master resume and produces a tailored
variant per job. Replace this entire file with your resume in markdown.

The tailor is instructed (in src/email_agent/tailor.py) to never invent
metrics, employers, dates, titles, or technologies — it only rephrases
and reorders what's already here. So the more complete this is, the
better the tailored versions will be.

Recommended structure:

## Summary
2-3 sentences.

## Experience
### <Title> — <Company>  (<dates>)
- Bullet with concrete metric.
- Bullet with concrete metric.

## Education
...

## Skills
...
