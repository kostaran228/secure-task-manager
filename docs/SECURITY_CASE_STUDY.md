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
- A PodDisruptionBudget preserves at least one running API replica during voluntary disruptions.

## Evidence to show

Open the Security workflow, the Kubernetes manifests and the Grafana dashboard. This demonstrates security automation, runtime hardening and operational ownership in one repository.
