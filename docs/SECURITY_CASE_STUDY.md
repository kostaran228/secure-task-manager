# Security case study

## Goal

Deliver a small API using a workflow that catches common supply-chain and deployment risks before production.

## Controls implemented

- Semgrep checks the application source on every pull request.
- Trivy scans the built container image for high and critical vulnerabilities.
- Dependabot opens weekly updates for Python packages and GitHub Actions.
- The container runs as a numeric non-root user with dropped Linux capabilities.
- Kubernetes NetworkPolicy limits API egress to PostgreSQL and DNS.
- Secrets are injected into Kubernetes and excluded from version control.
- All task-management routes require an `X-API-Key` token, compared using a constant-time Python comparison.
- Production disables interactive API documentation, and the Ingress exposes only `/health` and `/tasks`; Prometheus metrics stay inside the cluster.
- The serverless Worker requires a Cloudflare secret token for every task route and uses parameterized D1 queries.
- Email/password accounts store Argon2 password hashes, and users receive a 12-hour signed access token after registration or sign-in.
- Every task query is scoped to the authenticated owner, preventing one account from reading another account's tasks.
- The FastAPI dependency was upgraded from 0.115.6 to 0.139.2 as part of the audit.
- A PodDisruptionBudget preserves at least one running API replica during voluntary disruptions.

## Evidence to show

Open the Security workflow, the Kubernetes manifests and the Grafana dashboard. This demonstrates security automation, runtime hardening and operational ownership in one repository.
