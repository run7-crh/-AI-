# Knowledge Graph Smoothness and Legend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the knowledge graph smooth during drag/zoom and replace the clipped ECharts legend with a complete, filterable top legend.

**Architecture:** Keep ECharts 5 for rendering. Move legend state into `GraphView.vue`; make `buildGraphOption` a pure builder that filters nodes and edges by visible categories and uses a neutral fallback category for unknown data. Update ECharts only for data/filter changes and coalesce resize callbacks.

**Tech Stack:** Vue 3, TypeScript, ECharts 5, Vitest, Vue TSC, Vite.

---

### Task 1: Make graph options filterable and animation-light

**Files:**
- Modify: `frontend/src/utils/graphOption.ts`
- Test: `frontend/src/utils/__tests__/graphOption.test.ts`

- [ ] **Step 1: Write failing tests**

Extend the current fixture tests with:

```ts
it('filters nodes and links by visible categories', () => {
  const option = buildGraphOption(data, new Set(['Agent工程'])) as {
    series: Array<{ data: Array<Record<string, unknown>>; links: Array<Record<string, unknown>> }>
  }
  expect(option.series[0].data.map((node) => node.id)).toEqual(['a'])
  expect(option.series[0].links).toHaveLength(0)
})

it('maps unknown categories to neutral 其他', () => {
  const option = buildGraphOption(data, new Set(['其他'])) as {
    series: Array<{ data: Array<Record<string, unknown>>; categories: Array<Record<string, unknown>> }>
  }
  expect(option.series[0].data.find((node) => node.id === 'c')).toMatchObject({ category: 5 })
  expect(option.series[0].categories[5]).toMatchObject({ name: '其他' })
})

it('disables continuous force relayout', () => {
  const option = buildGraphOption(data) as { animation: boolean; series: Array<{ force: Record<string, unknown> }> }
  expect(option.animation).toBe(false)
  expect(option.series[0].force.layoutAnimation).toBe(false)
})
```

Replace the existing legend assertion with an assertion that `option.series[0].categories.slice(0, 5).map((item) => item.name)` equals `Object.keys(CATEGORY_COLORS)`; the option no longer contains an ECharts legend.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `npm test -- --run src/utils/__tests__/graphOption.test.ts` from `frontend`.

Expected: FAIL because the builder has no category filter, no `其他` category, and still enables layout animation.

- [ ] **Step 3: Implement the minimal builder changes**

In `frontend/src/utils/graphOption.ts`:

1. Add `OTHER_CATEGORY = '其他'`, `OTHER_COLOR = '#a8a29e'`, and a category-color helper.
2. Change the signature to `buildGraphOption(data: GraphData, visibleCategories?: ReadonlySet<string>)`.
3. Include `其他` when any node category is unknown; map unknown nodes to that index and neutral color.
4. Filter nodes by category and retain only links whose source and target IDs are visible.
5. Preserve tooltip data, line styles, node sizing, and existing force values.
6. Set `animation: false`, `animationDurationUpdate: 0`, and `force.layoutAnimation: false`.
7. Remove ECharts `legend`; the Vue view will render it.

- [ ] **Step 4: Run the focused test and confirm pass**

Run: `npm test -- --run src/utils/__tests__/graphOption.test.ts`.

Expected: all graph option tests PASS.

- [ ] **Step 5: Commit the focused change**

Run:

```powershell
git add frontend/src/utils/graphOption.ts frontend/src/utils/__tests__/graphOption.test.ts
git commit -m "perf(graph): filter categories and disable force relayout"
```

If `.git/index.lock` is rejected by the workspace policy, leave the files unchanged and report that permission limitation.

### Task 2: Add the top legend and stable update lifecycle

**Files:**
- Modify: `frontend/src/views/GraphView.vue`

- [ ] **Step 1: Add derived category state**

Add a `visibleCategories` ref initialized from `Object.keys(CATEGORY_COLORS)`, a `legendCategories` computed that appends `其他` when unknown node categories exist, and a `hasVisibleNodes` computed that treats unknown categories as `其他`. Reset the set after successful `fetchGraph()`.

Define `normalizeCategory(category: string): string` in the same script: return `category` when it is a key in `CATEGORY_COLORS`, otherwise return `其他`.

- [ ] **Step 2: Render the custom legend and data hints**

Add a top toolbar above the chart canvas. Render one button per `legendCategories` item with a color dot, label, selected opacity, and `@click` toggle. Keep the chart in a separate `min-h-0 flex-1` child. Show a compact notice beside the counts when `data.edges.length === 0`, and show an empty-filter hint when no visible nodes remain.

- [ ] **Step 3: Update only on filter/data changes**

Add:

```ts
function toggleCategory(category: string): void {
  const next = new Set(visibleCategories.value)
  if (next.has(category)) next.delete(category)
  else next.add(category)
  visibleCategories.value = next
  if (selected.value && !next.has(normalizeCategory(selected.value.category))) selected.value = null
  renderChart()
}
```

Use `buildGraphOption(data.value, visibleCategories.value)` in `renderChart()`. Do not call it from node click or neighbor selection.

- [ ] **Step 4: Coalesce resize callbacks**

Add a `resizeFrame` handle. The `ResizeObserver` schedules one `requestAnimationFrame` callback that calls `chart?.resize()`; cancel the pending frame on unmount before disposing the chart.

- [ ] **Step 5: Run frontend tests and typecheck**

Run from `frontend`: `npm test -- --run` and `npx vue-tsc -b`.

Expected: all tests PASS and TypeScript exits 0.

### Task 3: Build, diff-check, and manually verify

**Files:**
- Modify only the files from Tasks 1–2 if a focused verification failure requires it.

- [ ] **Step 1: Run `npm run build`**

Expected: Vue TSC and Vite build complete successfully.

- [ ] **Step 2: Run `git diff --check` from the repository root**

Expected: no output and exit code 0.

- [ ] **Step 3: Manually verify `/graph`**

Check complete top legend visibility, drag stability, wheel zoom/pan, category filtering with incident-edge removal, hide-all/re-enable behavior, node details, neighbor switching, one-click Agent question, and the 0-edge data hint.

- [ ] **Step 4: Commit the completed implementation**

Run:

```powershell
git add frontend/src/views/GraphView.vue frontend/src/utils/graphOption.ts frontend/src/utils/__tests__/graphOption.test.ts
git commit -m "perf(graph): smooth interactions and show complete legend"
```
