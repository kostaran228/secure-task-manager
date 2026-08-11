# Email authentication

## Local mode

The dashboard at `http://localhost:8000` sends registration and sign-in requests only to the API running on the same computer. The email is stored in the local PostgreSQL container. Passwords are never stored in plain text: the application stores an Argon2 password hash.

After a successful registration or sign-in, the API issues a signed access token that lasts 12 hours. The dashboard stores it only in the current browser tab session and sends it as a Bearer token when calling task routes. Each task belongs to the account that created it.

## Cloud mode

After deployment, the same information travels over HTTPS to the hosted API and is stored in the hosted database. The JWT signing secret must be placed in the cloud secret manager or Kubernetes Secret, never in Git.

This version does not send email. Email verification, password recovery, and notifications require an explicitly configured transactional email provider and a verified sending domain.
