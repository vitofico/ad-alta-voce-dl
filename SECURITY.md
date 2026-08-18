# Security Policy

## Supported versions

This project is pre-1.0. Only the latest commit on `main` is supported. Older tags and published container images get no backports.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Use GitHub's private vulnerability reporting:

**https://github.com/vitofico/ad-alta-voce-dl/security/advisories/new**

Include:

- A description of the issue.
- Steps to reproduce, with a minimal proof of concept if you have one.
- Affected component (web UI, REST API, poller, CLI, container image).
- Your assessment of impact.

You will get an acknowledgement within **5 business days**. If the report is accepted, expect a fix or mitigation within **30 days** for high-severity issues, longer for lower-severity ones.

## Scope

In scope:

- Path traversal or arbitrary file read/write through download paths, filenames, or the file-serving routes.
- Command or code injection through URLs, episode metadata, or environment variables.
- Cross-site scripting or CSRF in the web UI.
- Credential leakage, in particular anything that could expose the VPN credentials in `.env`.
- Container escape or privilege issues in the shipped image.
- Dependency vulnerabilities with a demonstrated path to exploitation here.

Out of scope, because it is documented behaviour rather than a defect:

- **The web UI has no authentication.** This is deliberate and prominently documented: it is a personal, local-network tool running on Flask's development server. The README says not to expose port 5000. Reporting "the UI is unauthenticated" tells us something we already say on the front page.
- **No rate limiting.** Same reasoning.
- Anything requiring an attacker to already have local filesystem or shell access.
- Reports about RAI's own endpoints or infrastructure. Those are not ours.

If you find a way for a *remote* page or a hostile RAI response to compromise the host, for example a crafted `Content-Disposition` filename escaping the downloads directory, that **is** in scope and worth reporting even though the UI is unauthenticated.

## Handling credentials

If you believe a released commit or container image ever contained real VPN credentials, report it privately rather than opening an issue, so they can be rotated before the detail is public.
