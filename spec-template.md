# Tech Spec: [Feature Name]

## 1. Overview & Business Goal
* **Feature Slug:** `feature-name-slug`
* **Target Git Branch:** `feat/feature-name-slug`
* **Objective:** [1–2 sentences explaining what business or user problem this solves]

## 2. Scope & File Boundaries
* **Files to Create:**
  * `path/to/new_file.ts`
* **Files to Modify:**
  * `path/to/existing_file.ts` (limit changes strictly to function `X`)
* **Files NOT to Touch (Forbidden):**
  * `path/to/core_auth.ts`
  * `path/to/database_schema.sql`

## 3. Functional Requirements (Pass/Fail Criteria)
* The system **must** [exact deterministic behavior, e.g., reject a second export request while one is active].
* The system **must** return a `400 Bad Request` if `payload.email` is missing or invalid.
* The UI **must** display a loading spinner and disable the submit button upon click.

## 4. Edge Cases & Failure States
* **Empty State:** What happens if the query returns 0 rows? (e.g., render `<EmptyState />` component).
* **Permission/Auth Error:** What happens if the user lacks `admin` role? (e.g., redirect to `/unauthorized`).
* **Timeout / Network Drop:** What happens if the API request exceeds 5 seconds? (e.g., show retry banner).

## 5. Data Model & API Contract (If Applicable)
* **Request Payload / DDL:**
  ```json
  {
    "user_id": "string",
    "action": "string"
  }
  ```
* **Response Payload:**
  ```json
  {
    "status": "success",
    "data": {}
  }
  ```

## 6. Verification & Test Plan
* **Commands to Run:**
  * Unit test command: `npm test path/to/file.test.ts`
  * Linter command: `npm run lint`
* **Expected Evidence Required in Final Output:**
  * Exact terminal output log or test pass count.
  * Description of manual verification step or screenshot check.
