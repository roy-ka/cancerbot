# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report them privately through GitHub: go to this repository's **Security** tab and click **Report a vulnerability**. Include:

- what the issue is and where (file, endpoint, or page)
- steps to reproduce, or a proof of concept
- the impact you think it has

You'll get a response as soon as possible. Please give us a reasonable amount of time to release a fix before disclosing the issue publicly.

## Scope

In scope: the code in this repository — the FastAPI backend (`src/`), the React frontend (`client/`), the NLP service (`nlp_service/`), and the deployment configuration (`docker-compose.yml`, `nginx.conf`, `scripts/`).

Out of scope: third-party services the app calls (Groq, Gemini, PubMed, CrossRef, Wikipedia, ClinicalTrials.gov, Brevo), and denial-of-service through sheer request volume.

## Design notes

The security-relevant design decisions — authentication and token revocation, rate limiting, outbound-fetch (SSRF) protection, prompt-injection fencing of retrieved evidence, and XML parsing — are documented in [CLAUDE.md](CLAUDE.md), under "Auth", "Prompt safety", "Outbound fetch safety (SSRF)" and "XML parsing". Reading those first will save you from reporting a limitation that's already known and documented there.
