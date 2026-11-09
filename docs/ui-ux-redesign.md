# UI/UX redesign: modern light interface

The React frontend moved from a dark, dense, panel-heavy theme to a light, minimalist dashboard. It is a presentation and usability change only:
- **Unchanged:** routes, API contracts, request bodies, validation rules, and the SSE and polling lifecycle.
- **Untouched:** backend, worker, database, and messaging code.

## 1. Goals

- A bright, calm interface that is comfortable for long sessions and clear in a demonstration.
- A Detection page that a new user can complete in three actions: paste a link, choose a model, start.
- Fewer borders, nested panels, and technical labels by default. Technical details are still available on request.
- Honest states: real data only, failures that stay visible, and no placeholder metrics.
- Responsive from 360 px to large desktops, with accessible keyboard and screen-reader behaviour.

## 2. Visual direction

White cards sit on a soft off-white canvas, with one blue brand colour, a violet accent for "in progress" states and charts, and generous spacing.
- **Removed decoration:** the animated "vision engine" artwork and the phase card in the sidebar.
- **Hierarchy:** comes from type size, weight, and whitespace rather than uppercase labels and heavy borders.

## 3. Colour tokens

All colours are CSS custom properties on `:root` in `frontend/src/styles.css`. Components use the tokens, never raw values.

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#f8fafc` | Page canvas |
| `--surface` / `--surface-muted` | `#ffffff` / `#f1f5f9` | Cards / tracks, table headers, metric tiles |
| `--border` / `--border-strong` | `#e2e8f0` / `#cbd5e1` | Card outlines / inputs and secondary buttons |
| `--text` / `--text-secondary` / `--text-muted` | `#0f172a` / `#475569` / `#64748b` | Body, supporting, helper text (all ≥ 4.5:1 on white) |
| `--primary` / `--primary-hover` | `#2563eb` / `#1d4ed8` | Primary actions, active navigation, focus ring |
| `--primary-soft` / `--primary-text` | `#eff6ff` / `#1d4ed8` | Selected options, active nav background, info alerts |
| `--accent` / `--accent-soft` / `--accent-text` | `#8b5cf6` / `#f5f3ff` / `#6d28d9` | Detecting/encoding status, chart gradient |
| `--success-*`, `--warning-*`, `--danger-*` | green / amber / red families | Status badges, alerts, model availability |

Status is never shown by colour alone. Every badge carries a text label (Completed, Failed, Enabled, Disabled, Connected, and so on).

## 4. Typography and spacing

- **Font:** the system sans-serif stack (Inter if installed, otherwise the platform UI font). No web font is downloaded. The base size is 15 px.
- **Type scale:**

  | Element | Size |
  | --- | --- |
  | Page title | 28 px (24 px on phones) |
  | Card and section headings | 17–18 px |
  | Body | 15 px |
  | Helper text | 13–14 px |
  | Smallest text (badges, mono codes) | 12 px |

  The responsive check found no text below 12 px.
- **Spacing:** 24 px card padding (18 px on phones), 20–24 px between sections, and 16 px radius on cards (12 px on controls).
- **Shadows:** cards use one soft shadow; stronger shadows are reserved for the mobile drawer.

## 5. Layout and navigation

- **Sidebar (≥ 1024 px):** white, with a light right border, compact branding, and four links (Dashboard, Detection, History, Models). The active link uses a soft blue background with blue text and icon, and History stays highlighted on job pages.
- **Mobile drawer (< 1024 px):**
  - A menu button opens an off-canvas drawer with an overlay and a close button.
  - Escape, the overlay, and the close button dismiss it and return focus to the menu button.
  - Following a link closes it and navigates.
  - While closed, the drawer is `inert`, so it is out of the tab order and hidden from assistive technology.
  - The drawer uses `inert` rather than `visibility: hidden`: Chrome applies inherited visibility to children a frame late, which prevented focus from moving into a freshly opened drawer.
- **Header:** the current page name plus a single connection badge (*Connected*, *Checking connection*, or *Backend unavailable*). Breadcrumbs and the avatar were removed.

## 6. Pages

### Dashboard
- **Welcome:** a welcome section with **Start new detection** (primary) and **View history**.
- **KPIs:** five cards (Total jobs, Completed, In progress, Failed, YOLO models with an "N enabled" hint). Counts still come from pagination totals, never from one page of rows.
- **Recent detections:** a table with an empty state that links to the first detection.
- **System status:** one strip showing the connection badge, the Spring Boot version, the last check time, and a Refresh button.
- **Removed:** the decorative hero artwork, the model-family list, and the endpoint panel.

### Detection (highest priority)
One card with four numbered steps:

1. **Add your video:**
   - A large URL field with a clear button.
   - The helper text: "Paste a public YouTube video link that you are allowed to process."
   - Inline validation, unchanged and never stricter than the backend.
2. **Choose a model:**
   - A version dropdown ("YOLO11 (1 enabled)") and size options built from real catalog records.
   - Disabled sizes are labelled *Disabled* and cannot be submitted.
   - A single status line confirms the selected model.
   - When nothing is enabled: "No models are currently available for detection. Please ask an administrator to enable a model."
3. **Detection settings:**
   - Objects to detect uses three radio cards: **Vehicles** (default: bicycle, car, motorcycle, bus, truck), **All objects** (80 classes), and **Custom**.
   - Only *Custom* shows the searchable 80-class list, with chips and *Clear selection*.
   - **Advanced settings** (confidence 0.25, image size 640 px) is collapsed by default, and its header summarises the values. Collapsing never resets a value, and a validation error keeps it open.
4. **Start processing:**
   - The primary **Start detection** button, full width on phones, with a status line: *Ready to start*, *Complete the steps above*, or *N items to fix before starting*.
   - Submission banners (definite rejection, or an unclear result that points to History) appear here as alerts.

Unchanged behaviour:
- The synchronous double-submit guard.
- No automatic retry.
- Focus moves to the first invalid field.
- Server field errors are mapped to fields.
- The exact request body.
- Navigation to the job page on HTTP 202.

The separate "Detection configuration" summary card was removed (`ConfigurationSummary.tsx`), because it repeated the form.

### History
- **Layout:** a title, a short description, and one card holding the filters (status, model, rows per page, *Clear filters*), the table, and pagination.
- **Unchanged:** URL query state, server-side pagination, and filtering.
- **Columns:** Job, Model, Status (with the error code under the badge), Progress, Created, and View details.
- **Phones (≤ 720 px):** each row becomes a stacked card with field labels, so no horizontal table scrolling is needed.

### Models
- **Cards:** a readable title ("YOLO11 Nano"), the model key, an *Enabled*/*Disabled* badge, and **View details**.
- **Details panel:** the checkpoint filename and task type moved here. Selecting a card scrolls the panel into view, respecting reduced motion.
- **Unchanged:** filters (version, size, status) and URL state.
- **Explanation:** a short info alert explains that *Enabled* is administrative and does not prove that a worker prepared the weights.
- No enable, disable, or download controls exist.

### Job details
- **Status card:**
  - A plain-language heading for each state: *Processing your video*, *Detection complete*, *We couldn't process this video*, or *Detection cancelled*.
  - The exact status badge and a progress bar.
  - The live-update indicator (SSE, with polling fallback).
  - For failures, the backend message plus the real error code in a secondary line.
- **Completed jobs:**
  - The large video player (HTTP Range streaming) with **Download detected video** and **Download JSON** directly beneath.
  - The detection summary metrics, then *Objects detected* bars labelled as detection events, not unique objects.
  - The Result JSON viewer, loaded only on demand.
- **Job settings:** model, confidence, image size, object names, source, and timestamps.
- **Technical details:** a disclosure with the full job ID, class IDs, and last update time.

## 7. Shared components

| Component | Notes |
| --- | --- |
| `PageHeader` | Title, optional description and actions; the eyebrow is now optional |
| `StatusBadge` | Connection state with short labels |
| `JobStatusBadge`, `ProgressBar`, `StatCard` | Restyled; same props |
| `StateViews` | `LoadingSkeleton`, `EmptyState`, `ErrorState`, plus new **`Alert`** (info, success, warning, error) and **`Disclosure`** (button-controlled, `aria-expanded`, renders content only when open, optional `forceOpen`) |
| `DetectionTable` | `data-label` cells for the mobile card layout; *Completed* column optional (off by default) |
| `Icon` | Added `chevronDown`, `play`, `link`, `sliders` |

Buttons follow one scale (`button-primary`, `button-secondary`, `button-ghost`, `button-large`), and every focusable control uses the same blue focus ring.

## 8. Responsive design

The breakpoints are 1024 px (sidebar to drawer), 720 px (stacked tables, single-column choices, 2-up KPIs), and 480 px (full-width primary actions, 1-up KPIs). The video keeps a 16:9 frame. The JSON viewer and the class list scroll inside their own containers.

## 9. Accessibility

- Semantic landmarks and a skip link; one `h1` per page; steps use `h2` with a visually hidden "Step N:" prefix.
- Labelled inputs; radio groups for model size and class presets; validation errors announced with `role="alert"`; status messages use `aria-live`.
- Disclosures expose `aria-expanded` and `aria-controls`; the mobile drawer manages focus and inertness.
- `prefers-reduced-motion` removes animations and transitions.
- Contrast: body and helper text tokens meet WCAG AA on white and on the canvas.

## 10. Testing results

| Check | Result |
| --- | --- |
| Frontend tests (Vitest, Node 24.19.0) | **PASS**: 186 tests in 16 files (185 existing plus 1 new mobile-navigation test). Tests that depended on old copy or layout were updated to the new behaviour without dropping functional assertions. New assertions cover class presets, the advanced-settings disclosure (including the keep-open-on-error fix), the readiness status line, the welcome CTA, readable model titles, and the drawer's focus handling |
| Strict TypeScript (`tsc -b`, `strict: true`) | **PASS** |
| Production build (`npm run build`) | **PASS**: about 35.7 kB CSS (8.1 kB gzip), about 388 kB JS (123 kB gzip) |
| Lint | **NOT RUN**: no ESLint configuration exists in the project |
| Browser validation (headless Chrome via DevTools Protocol, real backend data) | **PASS**: Dashboard, Detection, History, Models, and Job details at 360, 390, 768, 1024, and 1440 px. No horizontal overflow, no console errors, and no text below 12 px. The completed job's video loaded through the backend (readyState 4, 136.9 s). The mobile drawer was verified: inert when closed, focus on open, Escape returns focus. The desktop sidebar is not inert. Screenshots were reviewed and are not committed |

Two defects found during validation were fixed:
- The advanced-settings section could collapse while the user was correcting a value.
- The mobile drawer did not receive focus in a real browser (jsdom could not show this).

## 11. Known limitations

- Browser checks used headless Chrome only; Firefox, Safari, and physical devices were not tested.
- There is no automated visual-regression or contrast tooling; contrast was checked against the token values.
- There is no dark mode, by design.
- No new detection jobs were submitted during validation; the existing completed job was used for media checks.
- The Docker `frontend` container was not rebuilt or restarted. Validation used a local Vite dev server against the running backend, so rebuild the frontend image to serve the new UI from Docker.
