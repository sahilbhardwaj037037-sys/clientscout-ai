# Design system — Checkpoint 1

The original SVG compass mark has an accessible name; no third-party logo or raster artwork is used. Product name: ClientScout AI. Tagline: Your Personal Freelance Intelligence Workspace.

Semantic CSS variables in `frontend/src/themes/tokens.css` drive every rendered surface, border, input, badge, icon, foreground and action. Tailwind's Vite integration and preflight are enabled; geometry and components use small named CSS classes. There are no charts in this checkpoint.

| Token | Light | Dark |
|---|---|---|
| Page | #F7F3EB | #332820 |
| Sidebar | #F1E9DE | #2B211B |
| Card | #FFFCF8 | #433429 |
| Soft | #F3EDE5 | #514033 |
| Text | #463327 | #F8F2E8 |
| Muted | #796252 | #D6C3B1 |
| Border | #E8DCCC | #665344 |
| Action | #6C4F3D | #F1E5D5 |
| Action text | #FFFFFF | #332820 |

Light muted text is darker than the suggested #927969 to improve contrast on cream surfaces. Status dot uses #486448 light / #BCD2AC dark and always has a text label. Disabled controls are also explicitly labeled unavailable.

Sidebar: 248px expanded, 72px collapsed; desktop header: 72px; main maximum width: 1280px; padding: 32px desktop / 16px mobile horizontally. Cards: 14px radius. H1: 34px desktop / 30px mobile; section headings: 19px; body: 14–15px; helpers: 12–13px. Small uppercase decorative captions are 10–11px. Buttons and inputs: at least 44px high; icon buttons: 44×44px.

At 1100px search fields reflow to two columns. At 760px the sidebar becomes an accessible modal drawer, KPI cards stack and content padding reduces. At 400px fields stack. The drawer supports initial focus, focus trapping, Escape, close button, overlay close, navigation close and focus return. Route changes focus main content and reset scroll; links expose aria-current. Unknown routes show recovery navigation.

Appearance defaults to light when no explicit choice and no system dark preference exists. An explicit light/dark selection persists to localStorage; System clears it and follows system changes. Storage failure preserves a working session preference. Minimal color transitions only apply when reduced motion is not requested. No entrance animations or custom downloaded fonts.

## Checkpoint 2

Approved palette values, theme behavior, brand SVG, navigation and shell geometry are unchanged. New lead forms, list rows, status summaries, source details, import outcomes and confirmation controls reuse the existing card/button/input/badge styles and tokens. Form fields stack on mobile; long URLs/notes wrap. Statuses are user-assigned workflow states, not opportunity scores. KPI card labels/layout remain intact: Leads Found is a real database count; priority/draft cards stay unavailable until implemented.

## Checkpoint 3A

The Website Audit screen now uses the same card, input, button, badge, typography and semantic theme tokens. Evidence/recommendation cards, collapsible request sources, history, progress and optional mobile lab metrics add functionality without changing the shell, navigation, brand or color values. Severity is written as observed/attention/review; it is not a score. Status and provider failures have text labels. Native permission/PageSpeed checkboxes use accessible labels and minimum-height label targets. Reports wrap long URLs and evidence at mobile widths; target HTML is never rendered as HTML.
