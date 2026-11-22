# UI Refinement Guide for Coding Agents

## Mission

Refine the visual quality, usability, and consistency of the **existing desktop application**. Use the provided Sapo Omni screenshot/reference and its design characteristics as inspiration—not as a template to clone.

This is a UI/UX polish task for an existing product. The application already has features, workflows, architecture, and business logic. Preserve them.

## Non-negotiable constraints

1. **Do not rewrite the application.** Work within the current architecture, framework, project structure, and conventions.
2. **Preserve functionality.** Do not remove, disable, rename, or change existing features, controls, navigation, workflows, business rules, data handling, APIs, database schema, or integrations unless explicitly requested.
3. **Avoid unrelated changes.** Do not refactor backend/business logic merely because you noticed it. Keep changes focused on presentation and usability.
4. **Inspect before editing.** Read the relevant source files and understand how the screen/component works before modifying it.
5. **Reuse existing components and styles** where practical. If a shared style or component is appropriate, improve it carefully and check its impact on other screens.
6. **Do not invent functionality.** Visual affordances must correspond to existing behavior. If a control's behavior is unclear, inspect its implementation before changing it.
7. **Keep the app buildable.** After changes, run the appropriate build/test checks available in the repository and report any issues.
8. **Respect the app's platform.** This guide is for desktop UI. Use native desktop conventions, sensible keyboard behavior, window resizing, and DPI scaling.

## Workflow

### Phase 1 — Inspect and establish a baseline

Before making changes:

- Identify the framework, target platform, UI architecture, and styling approach.
- Inspect the project structure and existing shared UI components/styles.
- Identify the screens/forms relevant to the task.
- Understand existing navigation, interactions, and validation behavior.
- Record visual and UX issues: spacing, alignment, hierarchy, readability, inconsistent controls, awkward sizing, excessive clutter, poor contrast, or inconsistent states.
- Do not make sweeping changes before understanding the existing implementation.

If the request targets a particular screen, prioritize that screen and the shared components it uses. Do not redesign the entire application unless asked.

### Phase 2 — Apply the visual direction

Use the following reference direction, adapting it to the existing app rather than forcing it onto every screen.

#### Theme and visual style

- Prefer a clean, restrained **light theme** unless the existing app already has an intentional theme system that should be preserved.
- Use neutral, light workspace surfaces with clear separation between content regions.
- Use a dark navy navigation region when appropriate to the current app layout.
- Use a strong blue accent sparingly for primary actions, selected navigation, focus states, links, and key data.
- Use green for positive chart series or status indicators where semantically appropriate.
- Favor clarity and hierarchy over decoration.
- Avoid heavy shadows, excessive rounded corners, unnecessary gradients, decorative effects, and oversized empty areas.
- Do not add decorative elements that reduce information density or distract from workflows.

#### Reference palette (approximate; adjust to existing app)

| Token | Suggested value | Usage |
|---|---|---|
| Navigation background | `#182537` | Sidebar/navigation surface, if applicable |
| Navigation active | `#0088FF` | Selected navigation item |
| Navigation hover | `#2B4263` | Hover state |
| Workspace background | `#F0F1F1` | Main app workspace |
| Surface | `#FFFFFF` | Cards, panels, dialogs |
| Muted surface | `#F3F4F5` | Hover/secondary surface |
| Border | `#D3D5D7` | Subtle dividers and control borders |
| Primary text | `#182537` | Main text |
| Secondary text | `#6B7280` | Supporting text, metadata |
| Accent blue | `#0088FF` | Primary action, selection, emphasis |
| Chart blue | `#33A0FF` | Chart series |
| Chart green | `#3FDA9E` | Chart series / positive trend |
| Warning | `#FFC13B` | Warning indicators |
| Danger | `#F04444` | Errors / destructive indicators |

These are **reference suggestions**, not mandatory colors for every component. Check contrast and semantic consistency before applying them. Do not change a component's semantic color merely to match the palette.

#### Typography

- Prefer the application's existing font if it is readable and consistent.
- On Windows desktop, **Segoe UI** or Segoe UI Variable are reasonable options when compatible with the framework.
- Establish a consistent hierarchy:
  - Screen title: around 20–22 px, semibold.
  - Section/card title: around 14–16 px, medium or semibold.
  - Body/control text: around 13–14 px.
  - Supporting labels/captions: around 12 px.
  - KPI/important figures: around 26–30 px, bold when the context calls for it.
- Treat sizes as starting points, not rigid requirements; account for platform DPI scaling and framework conventions.
- Avoid excessive font weights, all-caps labels, or inconsistent typography.

#### Spacing and layout

Use a consistent spacing rhythm, preferably based on multiples of 4 px (or the framework's equivalent logical units):

| Token | Reference |
|---|---:|
| `space-1` | 4 |
| `space-2` | 8 |
| `space-3` | 12 |
| `space-4` | 16 |
| `space-5` | 20 |
| `space-6` | 24 |
| `space-7` | 28 |
| `space-8` | 32 |

- Align related controls and labels consistently.
- Use spacing to group related elements and distinguish unrelated groups.
- Avoid cramped layouts and unnecessary gaps.
- Prefer consistent component heights, padding, and alignment.
- Preserve information density appropriate to business/administrative desktop apps.
- Do not enlarge controls or whitespace so much that important information becomes hidden or requires excessive scrolling.

#### Surfaces, panels, and cards

- Prefer clean, flat surfaces with subtle borders.
- Suggested corner radius: roughly 3–6 px where the framework supports it and it fits the existing visual language.
- Use subtle borders instead of strong shadows.
- Keep panel padding consistent, often around 16–24 px depending on density and screen size.
- Use headers, dividers, and spacing to establish hierarchy rather than ornamental effects.
- Do not convert every group into a card; use grouping only where it improves clarity.

#### Buttons and controls

- Make primary, secondary, neutral, and destructive actions visually distinct and consistent.
- Use blue for primary actions only where appropriate.
- Keep button sizes, padding, typography, and icon alignment consistent.
- Ensure focus, hover, pressed, disabled, and loading states are distinguishable.
- Make form labels clear; avoid placeholder text as the only label.
- Use consistent dropdown, textbox, checkbox, radio, date picker, and validation styles where possible.
- Preserve existing control behavior and keyboard interactions.
- Do not make controls look interactive if they are not interactive.

#### Navigation and icons

- Maintain the existing navigation structure and labels unless requested otherwise.
- Clearly distinguish active, hover, disabled, and expanded states.
- Use one consistent icon family/style.
- Suggested icon size: 16–20 px for typical desktop navigation and toolbar controls.
- Avoid mixing emoji, filled icons, and outline icons without a deliberate system.
- Icon-only actions should have tooltips or accessible labels.

#### Tables, lists, and data-heavy screens

- Preserve existing columns, actions, data, sorting, filtering, and pagination.
- Improve readability through consistent row heights, padding, column alignment, header hierarchy, and subtle separators.
- Keep action controls discoverable without making every row visually noisy.
- Use restrained hover and selected-row states.
- Maintain appropriate density for administrative applications; do not make tables unnecessarily spacious.
- Keep empty, loading, error, and populated states visually coherent.

#### Feedback and state handling

Improve visual presentation of existing states where they exist or can be safely represented without changing business behavior:

- Loading / busy
- Empty state
- Validation error
- General error
- Success / confirmation
- Disabled / unavailable
- Hover / focus / selected

Do not fabricate backend results or introduce new business states.

## Desktop-specific requirements

- Support window resizing and reasonable minimum dimensions.
- Avoid layouts that clip controls or content at common window sizes.
- Account for high-DPI displays and Windows scaling (e.g. 125%, 150%).
- Prefer logical units and framework layout mechanisms over brittle absolute positioning when feasible.
- Maintain keyboard navigation, tab order, visible focus, and accessible control labels.
- Use appropriate desktop interaction patterns for menus, dialogs, toolbars, and window behavior.
- Do not introduce web-only patterns that feel unnatural in a desktop application.

## Implementation strategy

- Make changes in small, coherent steps.
- Prefer shared style/token changes when they genuinely improve consistency and do not cause unwanted regressions.
- For broad shared changes, inspect all affected screens/components or at least identify the likely impact.
- Avoid replacing the UI framework, adding large dependencies, or creating a new styling architecture without a clear need and explicit approval.
- Avoid unnecessary code churn and preserve naming/conventions.
- Do not change data models, SQL, APIs, business logic, or security behavior as part of visual polish.
- If a visual improvement requires a functional change, explain the need and separate it from the styling work; do not silently implement it.

## Validation before completion

After refining the UI:

- [ ] The project builds successfully, if a build is available.
- [ ] Existing functionality and workflows are preserved.
- [ ] Navigation, dialogs, controls, and actions still behave as before.
- [ ] Layout works at different window sizes.
- [ ] DPI scaling does not cause clipping or broken alignment.
- [ ] Typography and spacing are consistent.
- [ ] Colors and contrast are reasonable.
- [ ] Hover, focus, selected, disabled, and error states are considered.
- [ ] No unrelated files or logic were changed unnecessarily.

## Reporting

At the end, provide a concise report:

1. **Screens/components refined** — list the areas touched.
2. **Visual improvements** — summarize the UI changes.
3. **Functional preservation** — explicitly mention whether any behavior/business logic was changed.
4. **Files changed** — list relevant files.
5. **Validation** — report build/test results honestly.
6. **Known issues or follow-up** — list anything that could not be verified.

Do not claim that tests, builds, or visual checks were performed if they were not.

## Agent instruction

Use this guide as the default design and safety constraint for UI refinement tasks in this existing application. **First inspect the current implementation, then improve it incrementally. Preserve existing functionality and architecture.** The Sapo Omni reference is inspiration for visual polish and consistency, not a mandate to clone its layout or replace the app.
