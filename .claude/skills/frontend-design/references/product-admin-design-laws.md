# Product Admin Design Laws

Use this reference for admin consoles, dashboards, dataset builders, review tools, editors, and dense operational web apps.

## Source Stack

- OpenAI, "Designing delightful frontends with GPT-5.4": define design constraints first, avoid generic overbuilt layouts, use real product content as the anchor, and verify with tools.
- Nielsen Norman Group, "10 Usability Heuristics": system status, real-world language, user control, consistency, error prevention, recognition, efficiency, minimalist focus, error recovery, and contextual help.
- Laws of UX: cognitive and perceptual laws for interface decisions.
- W3C WCAG 2.2 Quick Reference: perceivable, operable, understandable, robust UI.
- Carbon Design System, Data Table: tables need title/description, toolbar, clear rows, hover, search/filter, row actions, and enough horizontal space.
- GitHub Primer, NavList: side navigation should indicate the current view, use grouped sections for longer lists, leading visuals for recognition, and trailing visuals for counts/status.
- Mantine AppShell: admin apps should use a stable header/navbar/main/footer shell, with scrollable sections inside the shell.

## Admin Console Rules

- Persistent orientation: current dataset, current view, source status, sync state, and save state must remain visible.
- One primary workspace per view: dataset admin, candidate builder, sample admin, and operations should be separate surfaces.
- Real content is the visual anchor: for menu workflows, the menu image owns the builder view; metadata supports it.
- Tables over cards: use tables or structured rows for datasets, candidates, and samples; reserve cards for repeated object tiles only when visual browsing matters.
- Action locality: place add/remove/reorder/edit controls near the object they affect.
- Progressive disclosure: keep filters, JSON, local paths, git details, and drift details visible but not competing with the primary task.
- Dense but calm: compact rows, clear column alignment, strong labels, restrained borders, and no decorative gradients.
- Status-first color: color communicates source, drift, sync, dirty, destructive, and success states; it should not decorate layout.
- Defaults over explanation: use familiar side nav, toolbar, inspector, table, split pane, drawer/modal, and sticky status patterns.
- Mobile collapse: collapse into a navigable sequence while preserving current dataset and unsaved/sync warnings.

## UX Laws To Apply

- Visibility of system status: show API, git, unsaved, sync, drift, operation progress, and last commit.
- Match with the real world: use dataset, sample, source hash, local sync, menu images, and git terms consistently.
- User control and freedom: allow next/previous, remove, cancel/close preview, and avoid irreversible hidden actions.
- Consistency and standards / Jakob's Law: use recognizable admin patterns instead of novel navigation.
- Error prevention: block duplicate samples, warn on drift, disable invalid save/create/add actions.
- Recognition over recall: keep selected dataset, selected sample, filters, counts, and status visible.
- Flexibility and efficiency: support repeated review with sticky Next/Add controls and compact rows.
- Aesthetic and minimalist design: remove content that does not help operate, monitor, compare, decide, or recover.
- Error recovery: explain unreachable API, empty database, sync failures, and git failures with concrete next action.
- Help and documentation: put small contextual text in empty/error states, not tutorial copy.

## Laws of UX Checklist

- Aesthetic-Usability Effect: polish helps trust, but never use polish to hide unclear workflow.
- Choice Overload / Hick's Law: split dataset, builder, samples, and settings views; do not expose every operation at once.
- Chunking / Miller's Law: group controls into filters, review, selected samples, metadata, operations.
- Cognitive Load: visible state, stable layout, and predictable labels reduce mental work.
- Doherty Threshold: show immediate feedback and progress for sync/save/check actions.
- Fitts's Law: make repeated actions large enough and close to the review area.
- Goal-Gradient Effect: expose queue count, selected count, synced count, missing count, drift count.
- Jakob's Law: follow known admin sidebar, toolbar, table, and inspector patterns.
- Law of Common Region: use panes, table regions, and status bars to show relationships.
- Law of Proximity: keep labels, values, controls, and affected content close together.
- Law of Pragnanz: prefer the simplest recognizable structure that still represents the workflow.
- Law of Similarity: use consistent row, badge, and button treatments for same-kind objects.
- Law of Uniform Connectedness: use connected controls for next/add/reorder where actions form a sequence.
- Mental Model: expose source data vs local metadata vs local assets as different layers.
- Occam's Razor: remove ornamental UI and duplicate metrics unless they change decisions.
- Paradox of the Active User: users start using tools immediately; make first actions obvious without reading docs.
- Pareto Principle: optimize the frequent loop: filter -> inspect image -> add/skip -> edit sample -> save/sync.
- Parkinson's Law: keep task surfaces bounded; avoid open-ended configuration pages.
- Peak-End Rule: make save/sync completion clear and satisfying.
- Postel's Law: accept flexible input for tags/search, output conservative metadata.
- Selective Attention: use contrast only for active view, primary action, and warning states.
- Serial Position Effect: put high-frequency navigation first and dangerous/settings actions last.
- Tesler's Law: keep necessary complexity in the system where possible, but reveal source/git details when needed.
- Von Restorff Effect: reserve the distinct visual treatment for the one action/state that must stand out.
- Working Memory: do not make users remember source status, selected sample, split, or dirty state across panes.
- Zeigarnik Effect: make unfinished work visible with unsaved/missing/drift indicators.

## Visual System Rules

- Type scale: compact admin type, with page titles only in headers; avoid oversized headings inside panes.
- Spacing: use 4/8/12/16/24 rhythm; rely on whitespace and borders, not shadows.
- Palette: neutral background, white elevated work panes, one accent, semantic warning/error/success colors.
- Borders: thin, low-contrast borders for region separation; avoid heavy shadows and nested cards.
- Rows: table and list rows need stable height, hover state, selected state, and clear leading/trailing metadata.
- Buttons: primary actions are filled, secondary actions are subtle/light, icon actions have tooltips.
- Empty states: short diagnosis plus concrete next action; no marketing copy.
- Loading: prefer skeleton/inline progress for data regions; use spinners only for short blocking operations.
- Accessibility: visible focus, adequate contrast, semantic buttons/tables/nav, text labels for icon-only actions.
