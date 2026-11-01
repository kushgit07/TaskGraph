# TaskGraph on Render

This runs the **collapsed single-process** deployment topology of
TaskGraph (API + orchestrator + worker all in one container) so the
public demo is free to host. The reference architecture — independently
scalable services via Docker Compose — is documented and runnable from
the main repo. See the root `README.md`'s "Deployment topologies" section.

## Setup

1. Create a new **Web Service** on Render, pointing at this repo.
2. Set the **Dockerfile path** to `deploy/render/Dockerfile` (Render lets
   you pick a non-root Dockerfile when creating the service).
3. Add these environment variables in the Render dashboard:
   - `DATABASE_URL` — a free Postgres instance (Neon/Supabase both work).
   - `GROQ_API_KEY` — optional; without it the demo runs on a
     deterministic mock LLM instead of a real one.
4. Deploy. Render auto-redeploys on every push to `main` by default.

Render's free tier spins the service down on idle, so the first request
after a period of inactivity will be slow while it cold-starts — that's
expected, not a bug.
