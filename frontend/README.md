# Resolvix Frontend

React 19 customer chat for Resolvix, built with Vite, Tailwind CSS, React
Router, and Axios. The interface signs in against the FastAPI backend, stores
the JWT for the browser session, and persists conversations and messages in
PostgreSQL through the conversation APIs.

## Requirements

- Node.js 20 or newer (developed with Node 24)
- The Resolvix backend running at `http://localhost:8000`
- PostgreSQL seeded with the synthetic demo accounts

## Setup

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Vite serves the app at http://localhost:5173. The backend must allow that origin
through `CORS_ORIGINS`.

`VITE_API_BASE_URL` configures the API origin. If it is omitted, the app uses
`http://<current-host>:8000`.

## Demo account

| Role | Email | Password |
|---|---|---|
| Customer | `alice.morgan@example.com` | `Customer123!` |

The login screen also includes a **Use demo** shortcut. These credentials are
development-only and use synthetic data.

## Routes

| Route | Access | Purpose |
|---|---|---|
| `/login` | public | Email/password sign-in |
| `/` | authenticated | Conversation sidebar and chat window |

Unauthenticated visitors are redirected to `/login`. An expired or rejected
token clears the stored session and returns the customer to sign-in with a
notice.

## Chat behavior

- The sidebar loads only the authenticated customer's conversations and
  restores the last selected conversation after a browser refresh.
- **New conversation** creates an empty thread. The first message becomes its
  sidebar title.
- Messages are validated before submission, stored by the backend, and rendered
  from the persisted response rather than an optimistic copy.
- Submissions are blocked while a request is in flight, preventing duplicates.
- The assistant reply is a stored placeholder marked as temporary until an AI
  provider is connected.
- Loading indicators, empty states, and dismissible error notifications cover
  slow, empty, and failed API responses.
- A `401` from a protected endpoint clears the JWT and redirects to login.

## Scripts

```powershell
npm run dev      # Vite development server
npm run build    # production build
npm run lint     # ESLint
npm test         # Vitest + Testing Library state tests
```

The tests cover login validation and errors, conversation loading, empty and
failed states, conversation creation, refresh restoration, and duplicate-send
prevention.

## Layout

```
src/
  components/         chat sidebar, message bubbles, icons, route guard
  context/            authentication state and JWT session restoration
  layouts/            authenticated app shell
  pages/              login and chat screens
  services/           Axios client, auth APIs, conversation APIs
  test/               Vitest setup
  utils/              session storage, API errors, date formatting
```
