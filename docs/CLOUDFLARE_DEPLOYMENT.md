# Cloudflare Workers deployment

This directory contains a serverless implementation of the Task Manager API. It is deliberately separate from the Kubernetes version: the same business endpoints are implemented at the edge, with Cloudflare D1 instead of PostgreSQL.

## Free-tier deployment

1. Create a free Cloudflare account and install Node.js LTS.
2. In `cloudflare-worker`, run `npm install` and `npx wrangler login`. The browser window is used to authorize the CLI; do not share tokens with anyone.
3. Create the database:

   ```powershell
   npx wrangler d1 create secure-task-manager-db
   ```

4. Copy the returned `database_id` into `cloudflare-worker/wrangler.jsonc`.
5. Create the schema and deploy:

   ```powershell
   npx wrangler d1 execute secure-task-manager-db --remote --file=schema.sql
   npx wrangler secret put API_TOKEN
   npm test
   npm run deploy
   ```

6. Verify the generated `workers.dev` URL:

   ```powershell
   Invoke-RestMethod https://YOUR-WORKER.workers.dev/health
   ```

## Portfolio value

The repository demonstrates two deployment approaches for one API: a containerized Kubernetes deployment with PostgreSQL, and a serverless edge deployment with Cloudflare Workers and D1. This makes the trade-off explicit: Kubernetes provides infrastructure control and observability; Workers reduces operational overhead and has a free plan for small public demos.

## Safety notes

- Do not put credentials into `wrangler.jsonc` or commit `.dev.vars`.
- `API_TOKEN` is mandatory for every `/tasks` request. Store it with `wrangler secret put API_TOKEN`; do not put it in source control.
- Use `Authorization: Bearer YOUR_TOKEN` when calling the task endpoints.
- The Worker uses parameterized D1 statements and validates request data before it reaches the database.
