<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# FANTASEE: Agent Guidelines & Best Practices

As a senior engineer and architect on this project, follow these standards to ensure a professional, production-ready, and high-quality codebase.

## 1. Core Architecture & Philosophy
FANTASEE is a **local-first cinematic story studio**. Our goal is to provide a "killer app" experience with flawless multi-voice narration, cinematic immersion, and complete transparency.

- **Local-First**: Minimize external dependencies; prefer local LLMs (LM Studio) and local TTS (Kokoro).
- **Cinematic Experience**: Every UI element should contribute to the story's atmosphere.
- **High Performance**: Use parallel synthesis and pre-fetching to ensure instant playback.

## 2. Development Best Practices

### Frontend (Next.js & React)
- **Component Limits**: Keep components under **500 lines**. If it exceeds this, break it into smaller, reusable sub-components.
- **Server vs. Client**: Use `"use client"` only when necessary for hooks (`useState`, `useEffect`, etc.).
- **State Management**: Use `TanStack Query` (React Query) for server state and standard `useState`/`useContext` for UI state.
- **UI Consistency**: Follow the established theme engine (Dark, Sepia, Light) using Tailwind CSS.
- **Accessibility**: Ensure all interactive elements have proper labels and keyboard support.

### Backend (Python Worker)
- **Asyncio**: Always use `asyncio` for I/O bound tasks like LLM requests and audio synthesis.
- **Error Handling**: Implement robust retry logic with exponential backoff for external services (LM Studio, Kokoro, Unsplash).
- **Logging**: Use structured logging to track job progress and errors. Every major action should be logged.
- **Resource Management**: Be mindful of GPU/CPU usage during parallel synthesis.

### Database (Prisma & SQLite)
- **Schema First**: Always update `schema.prisma` and run migrations before manual database edits.
- **Performance**: Use appropriate indices for frequent queries (e.g., `storyId`, `partNumber`).
- **Data Integrity**: Use foreign key constraints to ensure story parts and segments are correctly linked.

## 3. Rigorous Testing Strategy

Testing is NOT optional. We strive for high coverage to ensure reliability.

### Unit Testing
- **Python**: Use `pytest` for testing worker logic, fuzzy matching, and data normalization.
- **Frontend**: Use `Jest` or `Vitest` for component and utility function tests.

### Integration Testing
- **API Endpoints**: Test all `/api` routes to ensure they return correct data and handle errors gracefully.
- **Worker Jobs**: Simulate end-to-end job processing from `queued` to `done`.

### E2E Testing
- **Playwright/Cypress**: Test the complete flow from story creation to full playback.
- **Visual Regression**: Ensure theme changes and UI transitions don't break the layout.

## 4. How to Run Tests

### Python Worker
```bash
# From the root directory
pytest worker/tests/
```

### Frontend
```bash
# From the root directory
npm test
```

## 5. Documentation Standards

- **Code Comments**: Use JSDoc for TypeScript and Docstrings for Python. Explain *why*, not just *what*.
- **READMEs**: Maintain clear `README.md` files in the root and major subdirectories (`/worker`, `/src/app/api`).
- **Schema Documentation**: Document complex JSON structures in the database (e.g., `continuityNotesJson`, `timingJsonPath`).

## 6. GitHub & Version Control

We use a structured workflow to maintain code quality and history.

### Branching Strategy
- **main**: Always stable, production-ready code.
- **develop**: Integration branch for new features.
- **feature/xxx**: Individual feature development.
- **bugfix/xxx**: Targeted bug fixes.

### Commit Messages
Follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat: ...` for new features.
- `fix: ...` for bug fixes.
- `docs: ...` for documentation updates.
- `test: ...` for adding/updating tests.
- `refactor: ...` for code cleanup.

### Pull Requests
- All PRs must pass linting and tests before merging.
- PR descriptions should include a summary of changes and links to relevant tasks.
- Require at least one peer review for major changes.

## 7. Proactiveness
- Always check the **IDE terminal** for errors.
- Read the **browser console** regularly during development.
- If you introduce a linter error, **fix it immediately**.
- Proactively suggest and implement optimizations (e.g., caching, parallelization).
