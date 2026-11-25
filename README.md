# Dealership AI Assistant

A car dealership website with an **AI sales assistant that only recommends vehicles that are actually on the lot**, captures leads from the conversation, and hands them to a back office.

Built with **FastAPI, Jinja2, SQLite and the Claude API** (structured outputs). It runs fully offline too: without an API key it switches to a deterministic demo assistant, so anyone can clone it and try it in one command.

> Crestline Motors is a fictional dealership. All inventory is made up.

## What it does

| Shopper side | Back office |
|---|---|
| Browse inventory with filters (body type, make, budget, sort) whose state lives in the URL | Sign in, then add, edit, hide or delete vehicles |
| Ask the assistant in plain English: *"hybrid SUV under $35k"* | Photo upload, validated by content and re-encoded (EXIF/GPS stripped) |
| The assistant answers with real vehicle cards from the live inventory | Body type auto-detected from the model name when left blank |
| "Book a test drive" from any vehicle page opens the chat with context | Leads list fed by the chat: name, contact and interest |

## How the assistant stays honest

LLMs are great at conversation and bad at knowing what is in your parking lot. The design keeps the model inside the facts:

1. **Live inventory in the prompt.** Every turn rebuilds the system prompt from the database, so a car sold five minutes ago is gone.
2. **Structured output, not free text.** Each reply is JSON validated against a schema: `reply`, `vehicle_ids` and `lead {customer_name, contact, interest}`.
3. **Server-side filtering of what the model points at.** Any `vehicle_id` that is not currently listed is dropped before reaching the page. The model cannot invent a car.
4. **Deterministic body types.** "Sedan vs. hatchback" is stored per vehicle and suggested by a keyword classifier, never left to the model's memory of model names.
5. **Graceful degradation.** API errors, refusals or malformed output fall back to the offline assistant, so the chat never shows a stack trace.
6. **Prompt-injection posture.** Shopper text only travels as user messages, the rules say it is data and not instructions, and leads only accept what the shopper actually typed.

```
Browser ──POST /api/chat──▶ ChatService
                              ├─ VehicleRepository.search()  (live inventory)
                              ├─ build_system_prompt()        (facts + rules + inventory)
                              ├─ Provider.respond()           (Claude API or offline demo)
                              ├─ drop vehicle_ids not on sale
                              ├─ ChatRepository.append()      (history, last 16 turns)
                              └─ LeadRepository.upsert()      (merge name/contact/interest)
```

## Security

- Parameterized SQL everywhere; `ORDER BY` comes from a whitelist.
- CSRF tokens on every admin form; signed, `HttpOnly`, `SameSite=Lax` session cookie, regenerated at login.
- Admin passwords hashed with scrypt (`python -m app.security hash`), compared in constant time.
- Rate limits: chat per IP and per session, login per IP.
- Strict security headers, including a CSP with no inline scripts or styles and `frame-ancestors 'none'`.
- Uploads: size limit, format checked by decoding the image (not the extension), random file names, re-encoded to WebP.
- Open-redirect-safe `next=` handling; the app refuses to start in production mode without `SECRET_KEY` and a password hash.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload
```

Open http://127.0.0.1:8000 and the admin at `/admin` (demo credentials are shown on the sign-in page). API docs are at `/api/docs`.

**Docker:** `docker compose up --build`

**Use Claude instead of the offline assistant:** set `ANTHROPIC_API_KEY` (see `.env.example`). The model defaults to `claude-opus-5-5` and can be changed with `ASSISTANT_MODEL`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

43 tests cover body-type classification, repository filters and SQL-injection attempts, the Claude provider against a fake client (structured parsing, refusals, malformed output, invented vehicle ids), the chat API (validation, rate limiting, fallback), admin auth, CSRF, uploads with EXIF stripping and path traversal, and open redirects.

## Project layout

```
app/
  main.py            routes: public site, JSON API, admin
  assistant/         prompt building, providers (Claude / demo), chat service
  repository.py      SQLite data access
  models.py          Pydantic validation
  security.py        passwords, CSRF, rate limiting, uploads, headers
  body_type.py       deterministic body-type classifier
  templates/ static/ server-rendered UI (mobile-first, light and dark themes)
tests/
```

## License

MIT
