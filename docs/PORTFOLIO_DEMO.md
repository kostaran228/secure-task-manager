# Five-minute portfolio demo

## Opening

"This is a small task-management API that I used to demonstrate a production-oriented DevSecOps delivery flow."

## What to show

1. Open GitHub Actions and show the CI, Security and Release workflows.
2. Open the container package in GitHub Container Registry.
3. Show the Kubernetes manifests: non-root runtime, probes, limits, HPA and secrets.
4. Run the API health-check and create a task.
5. Open Grafana and point out API availability and HTTP request-rate panels.

## Strong interview talking points

- Explain why an image scan belongs before deployment.
- Explain the difference between readiness and liveness probes.
- Explain why database credentials never live in the repository.
- Describe the path from a git tag to an immutable container image and then to Kubernetes.
