# Architecture

```mermaid
flowchart LR
  Dev[Developer] -->|push / tag| GitHub[GitHub repository]
  GitHub --> CI[GitHub Actions]
  CI --> Scan[Semgrep + Trivy]
  CI --> GHCR[GitHub Container Registry]
  GHCR --> K8s[Kubernetes]

  subgraph K8s[Local Kubernetes]
    API1[Task Manager API]
    API2[Task Manager API]
    DB[(PostgreSQL)]
    API1 --> DB
    API2 --> DB
  end

  API1 --> Metrics[/metrics]
  API2 --> Metrics
  Metrics --> Prometheus
  Prometheus --> Grafana
```

## Engineering decisions

- API runs as a numeric non-root user and has a read-only root filesystem in Kubernetes.
- Health probes protect rollout reliability; the HPA is ready to scale API replicas by CPU.
- Secrets are injected at runtime and excluded from Git.
- Every pull request receives test, build and security checks.
- Release tags publish a container image to GitHub Container Registry.
