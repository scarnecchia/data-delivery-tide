# Creating Lexicons

Lexicons define the status vocabulary for a delivery type. Different kinds of deliveries have different lifecycles — a QA package moves through `pending → passed / failed`, while a query package might move through `run → distributed → inputfiles_updated`. Lexicons make these differences configurable without changing pipeline code.

This guide covers what lexicons are, how to create one, and the advanced features available when you need them.

## What a Lexicon Does

A lexicon answers five questions about a delivery type:

1. **What statuses can a delivery have?** (e.g., `pending`, `passed`, `failed`)
2. **What transitions between statuses are allowed?** (e.g., `pending` can become `passed` or `failed`, but `passed` is terminal)
3. **Which directory names on disk map to which statuses?** (e.g., a directory named `msoc` means `passed`)
4. **Which statuses mean the delivery is ready for downstream processing?** (e.g., only `passed` deliveries should be converted)
5. **Should anything happen automatically when a delivery changes status?** (e.g., record a timestamp when it transitions to `passed`)

Each lexicon is a JSON file stored under `pipeline/lexicons/`. The file's location determines its ID — `soc/qar.json` becomes the lexicon ID `soc.qar`.

## Minimal Lexicon

The simplest lexicon defines statuses, transitions, directory mappings, and actionable statuses:

```json
{
  "$schema": "../lexicon.schema.json",
  "statuses": ["pending", "passed", "failed"],
  "transitions": {
    "pending": ["passed", "failed"],
    "passed": [],
    "failed": []
  },
  "dir_map": {
    "msoc": "passed",
    "msoc_new": "pending"
  },
  "actionable_statuses": ["passed"]
}
```

This is the actual content of `pipeline/lexicons/soc/_base.json` — the base lexicon that other SOC lexicons inherit from.

### Field Reference

| Field                  | Required | Purpose |
|------------------------|----------|---------|
| `statuses`             | yes*     | Array of valid status values. |
| `transitions`          | yes*     | Object mapping each status to an array of statuses it can transition to. An empty array means the status is terminal. |
| `dir_map`              | yes*     | Object mapping terminal directory names (on the network share) to statuses. The crawler uses this to determine a delivery's initial status from its directory path. |
| `actionable_statuses`  | yes*     | Array of statuses that mean "this delivery is ready for downstream processing." The `/deliveries/actionable` API endpoint filters to these. |
| `extends`              | no       | Inherit from another lexicon (see [Inheritance](#inheritance)). |
| `metadata_fields`      | no       | Auto-populate metadata on status transitions (see [Metadata Fields](#metadata-fields)). |
| `derive_hook`          | no       | Run custom logic during crawling (see [Derivation Hooks](#derivation-hooks)). |
| `sub_dirs`             | no       | Register subdirectories as separate deliveries (see [Sub-Directories](#sub-directories)). |

*Required unless the lexicon uses `extends` to inherit them from a parent.

### The `$schema` Line

The `$schema` line at the top is optional but recommended. It points to `lexicon.schema.json` and gives your editor (VS Code, etc.) autocompletion and inline validation. Adjust the relative path based on where your lexicon file sits:

```json
"$schema": "../lexicon.schema.json"
```

This line is stripped at load time and has no effect on the pipeline.

## Creating a New Lexicon

### Step 1: Define Your Statuses

Think about the lifecycle of your delivery type. What states can it be in? What transitions are valid? Which states are terminal (no further transitions)?

For example, a query package that gets run, distributed, and then updated:

- Statuses: `run`, `distributed`, `inputfiles_updated`
- Transitions: `run → distributed → inputfiles_updated` (linear, each is terminal once reached)
- Actionable: `distributed` (ready for downstream consumers)

### Step 2: Create the JSON File

Place the file under `pipeline/lexicons/` in a namespace directory. The namespace groups related delivery types. For example:

```
pipeline/lexicons/
├── soc/           # SOC delivery types
│   ├── _base.json
│   ├── qar.json
│   └── ...
└── requests/      # Request delivery types
    └── query_pkg.json
```

The file `requests/query_pkg.json` gets the lexicon ID `requests.query_pkg`.

Write the JSON:

```json
{
  "$schema": "../lexicon.schema.json",
  "statuses": ["run", "distributed", "inputfiles_updated"],
  "transitions": {
    "run": ["distributed"],
    "distributed": ["inputfiles_updated"],
    "inputfiles_updated": []
  },
  "dir_map": {
    "run": "run",
    "distributed": "distributed",
    "inputfiles_updated": "inputfiles_updated"
  },
  "actionable_statuses": ["distributed"]
}
```

### Step 3: Wire It to a Scan Root

In `pipeline/config.json`, add a scan root entry that references your new lexicon:

```json
{
  "scan_roots": [
    {
      "path": "/data/requests/mplr",
      "label": "MPLR Requests",
      "lexicon": "requests.query_pkg",
      "target": "packages"
    }
  ]
}
```

The `lexicon` value must match the lexicon ID exactly (`requests.query_pkg`).

### Step 4: Restart the Registry API

The registry API loads lexicons at startup. After adding a new lexicon file or modifying an existing one, restart the API for changes to take effect.

That's it for a basic lexicon. The crawler will use `dir_map` to derive statuses from directory names, the API will validate status transitions, and the `/deliveries/actionable` endpoint will filter to your `actionable_statuses`.

## Inheritance

If multiple delivery types share the same status model, define a base lexicon and extend it rather than duplicating the definition.

### How It Works

A child lexicon uses the `extends` field to reference a parent lexicon ID. The child inherits all fields from the parent and can override any of them:

```json
{
  "$schema": "../lexicon.schema.json",
  "extends": "soc._base",
  "metadata_fields": {
    "passed_at": {
      "type": "datetime",
      "set_on": "passed"
    }
  }
}
```

This is the actual content of `pipeline/lexicons/soc/qar.json` (minus the derive hook and sub_dirs, for clarity). It inherits `statuses`, `transitions`, `dir_map`, and `actionable_statuses` from `soc._base` and adds a `metadata_fields` definition.

### Merge Rules

- Top-level scalar fields (like `derive_hook`) in the child replace the parent's value.
- Top-level array fields (like `statuses`) in the child replace the parent's array entirely.
- Nested objects (like `transitions`, `dir_map`, `metadata_fields`) merge recursively — child keys override matching parent keys, parent-only keys are preserved.

### Constraints

- Maximum inheritance depth: 3 levels (deeper chains make merge behavior hard to reason about).
- Circular inheritance chains are detected and rejected.
- The parent lexicon must exist in the same `lexicons_dir`.

### Convention

Base lexicons are prefixed with `_` by convention (e.g., `_base.json`). This isn't enforced — it just makes the intent clear.

## Metadata Fields

Metadata fields are values that get auto-populated on a delivery's `metadata` JSON when it transitions to a specific status. They're useful when you want timestamps or flags recorded automatically — the caller doesn't need to supply them.

### Defining Metadata Fields

Add a `metadata_fields` object to your lexicon. Each key is the field name, and the value specifies its type and the trigger status:

```json
"metadata_fields": {
  "passed_at": {
    "type": "datetime",
    "set_on": "passed"
  },
  "reviewed": {
    "type": "boolean",
    "set_on": "passed"
  },
  "outcome": {
    "type": "string",
    "set_on": "distributed"
  }
}
```

### Types

| Type       | Value set when triggered      | Example value                    |
|------------|-------------------------------|----------------------------------|
| `datetime` | Current UTC time as ISO 8601  | `"2026-04-29T14:30:00+00:00"`   |
| `boolean`  | `true`                        | `true`                           |
| `string`   | The new status value          | `"distributed"`                  |

### When They Fire

Metadata fields are populated only when a delivery transitions to the `set_on` status via the API's PATCH endpoint. They aren't set on initial delivery creation (POST). This means a delivery created directly in the `passed` status won't have `passed_at` set — only a delivery that transitions from `pending` to `passed`.

## Derivation Hooks

A derivation hook is a Python function that runs during the crawler's second pass — after directories are parsed but before deliveries are POSTed to the registry. It can modify statuses based on cross-delivery logic that can't be expressed with simple directory mappings.

### When You Need One

Most lexicons don't need a derivation hook. You need one when the correct status for a delivery depends on other deliveries. For example, the `soc.qar` hook marks pending deliveries as `failed` when they have been superseded by a newer version of the same workplan and data provider.

### Writing a Hook

A derivation hook is a regular Python function with this signature:

```python
from pipeline.crawler.parser import ParsedDelivery
from pipeline.lexicons.models import Lexicon


def derive(
    deliveries: list[ParsedDelivery],
    lexicon: Lexicon,
) -> list[ParsedDelivery]:
    ...
```

Rules:

- The function receives all deliveries for the given lexicon from the current crawl.
- It must return a new list. Don't mutate the input list or its elements — use `dataclasses.replace()` to create modified copies.
- The function runs at crawl time, not at API time. It affects the status that gets POSTed, not subsequent transitions.

### Real Example

The QA derivation hook (`src/pipeline/lexicons/soc/qa.py`) marks older pending versions as failed:

```python
from dataclasses import replace
from itertools import groupby

from pipeline.crawler.parser import ParsedDelivery
from pipeline.lexicons.models import Lexicon


def derive(
    deliveries: list[ParsedDelivery],
    lexicon: Lexicon,
) -> list[ParsedDelivery]:
    if not deliveries:
        return []

    result = []
    sorted_deliveries = sorted(deliveries, key=lambda d: (d.workplan_id, d.dp_id))

    for _key, group in groupby(sorted_deliveries, key=lambda d: (d.workplan_id, d.dp_id)):
        group_list = list(group)
        if len(group_list) == 1:
            result.append(group_list[0])
            continue

        by_version = sorted(group_list, key=lambda d: d.version, reverse=True)
        highest_version = by_version[0].version

        for delivery in group_list:
            if delivery.status == "pending" and delivery.version != highest_version:
                result.append(replace(delivery, status="failed"))
            else:
                result.append(delivery)

    return result
```

### Registering a Hook

Reference the hook in your lexicon as a `"module.path:function"` string:

```json
{
  "derive_hook": "pipeline.lexicons.soc.qa:derive"
}
```

The function is imported at lexicon load time. If the import fails (bad module path, missing function), the lexicon loader raises a `LexiconLoadError`.

Place hook modules under `src/pipeline/lexicons/` alongside the lexicon code. Follow the existing pattern: `src/pipeline/lexicons/{namespace}/{module}.py`.

## Sub-Directories

Lexicons can declare `sub_dirs` to register subsidiary data found inside a delivery as separate deliveries with their own lexicon. This is useful when a delivery contains nested data that has a different lifecycle.

### Example

A QAR delivery might contain an SCDM snapshot in a subdirectory called `scdm_snapshot`. The `soc.qar` lexicon declares this:

```json
{
  "sub_dirs": {
    "scdm_snapshot": "soc.scdm"
  }
}
```

When the crawler finds a `scdm_snapshot` directory inside a matched QAR terminal directory, it registers it as a separate delivery governed by the `soc.scdm` lexicon. The sub-delivery inherits identity fields (`dp_id`, `request_id`, `workplan_id`, `version`) from the parent but gets its own `source_path`, `delivery_id`, file inventory, and conversion tracking.

### Constraints

- The target lexicon (`soc.scdm` in this example) must exist.
- The target lexicon cannot itself declare `sub_dirs`. Recursive nesting is not allowed.
- Sub-directories that don't exist on disk are silently skipped — they are possibilities, not requirements.

## Validation

All lexicons in the `lexicons_dir` are loaded and cross-validated together at startup. The loader checks:

**Syntax and structure:**
- JSON syntax is valid.
- Required fields are present (unless `extends` is used).

**Cross-references** (all must point to values declared in `statuses`):
- `transitions` keys
- `dir_map` values
- `actionable_statuses` values
- `metadata_fields[].set_on` values

**Inheritance:**
- All `extends` references point to existing lexicons.
- No circular `extends` chains.
- Inheritance depth doesn't exceed 3.

**Sub-directories and hooks:**
- All `sub_dirs` values reference existing lexicons.
- No `sub_dirs` target has its own `sub_dirs`.
- All `derive_hook` imports resolve to callable functions.

If any check fails, the loader collects all errors and raises a single `LexiconLoadError` listing every problem — you see all issues at once rather than fixing them one at a time.

## Shipped Lexicons

The pipeline ships with four lexicons for SOC delivery types:

| ID          | File                | Purpose |
|-------------|---------------------|---------|
| `soc._base` | `soc/_base.json`   | Base tri-state model (`pending`/`passed`/`failed`). No hook, no metadata. Other SOC lexicons extend this. |
| `soc.qar`   | `soc/qar.json`     | QA Results. Extends `_base`, adds `passed_at` timestamp, version-supersession hook, and `scdm_snapshot` sub-directory. |
| `soc.qmr`   | `soc/qmr.json`     | QMR Results. Extends `_base`, same hook and metadata as `soc.qar`. |
| `soc.scdm`  | `soc/scdm.json`    | SCDM Snapshots. Extends `_base` with no additions. Used as a sub-delivery type. |

These serve as working examples. Read through them alongside this guide to see how the pieces fit together.
