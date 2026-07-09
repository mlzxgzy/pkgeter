# Custom Presets Design

## Goal

Separate built-in distribution presets from user customization so built-in presets remain source-controlled in `pkgeter/data/presets.yaml`, while user-defined additions and overrides live in `~/.config/pkgeter/custom-presets.yaml`.

## Requirements

1. Built-in presets are loaded from `pkgeter/data/presets.yaml`.
2. User custom presets are loaded only from `~/.config/pkgeter/custom-presets.yaml`.
3. Legacy `~/.config/pkgeter/presets.yaml` is no longer read.
4. Missing `custom-presets.yaml` is normal and must not raise an error.
5. User custom presets can:
   - define entirely new preset names
   - override `system`, `backend`, or `arch`
   - extend or replace individual repos by `repo.name`
   - extend or replace mirror entries by `mirror.name`
   - extend or replace mirror URL mappings by repo name inside `mirror.urls`
6. `preset apply <name>` continues current behavior: resolve merged preset result, then write concrete repos plus selected preset metadata into `config.yaml`.
7. No automatic seeding or copying of built-in presets into user config directory.
8. Documentation and tests must reflect `custom-presets.yaml` terminology and behavior.

## Architecture

`pkgeter/preset.py` remains single preset-loading module.

It will maintain two explicit paths:
- `_BUILTIN_PRESETS = pkgeter/data/presets.yaml`
- `_CUSTOM_PRESETS = ~/.config/pkgeter/custom-presets.yaml`

Loading order:
1. Read built-in presets
2. Read custom presets if file exists
3. Merge custom into built-in by preset key
4. Build grouped system index from merged result

## Merge Semantics

### Preset-level merge

If custom preset key does not exist in built-ins, add it as new preset.

If custom preset key exists in built-ins, merge field-by-field.

### Scalar fields

`system`, `backend`, `arch` from custom preset replace built-in values when provided.

### Repo merge

`repos` merge by `repo.name`.

Rules:
- built-in repos become initial map
- each custom repo with same `name` replaces that repo entry
- each custom repo with new `name` is appended logically by insertion into map
- final `repos` list is map values in insertion order

This lets users add `ceph-squid` to `pve-8` without copying full preset.

### Mirror merge

`mirrors` merge by `mirror.name`.

Rules:
- built-in mirrors become initial map
- matching custom mirror updates scalar metadata like `provider`
- `mirror.urls` merges by repo name
- new custom mirror names are added

## CLI Behavior

`get_preset()`, `list_presets()`, `all_preset_names()`, `complete_preset_name()`, and `run_preset()` all operate on merged result.

`preset apply <name>` keeps current behavior:
- resolve merged preset
- apply requested `@variant`
- write concrete repos to config
- write chosen preset name and mirror variant to config

This means editing `custom-presets.yaml` requires re-running `preset apply` if user wants persisted config repo list updated.

## Removed Behavior

These behaviors are intentionally removed:
- reading `~/.config/pkgeter/presets.yaml`
- seeding user preset file from built-ins
- resetting user file format automatically

## Testing

Add or update tests for:
1. no custom file present -> built-in presets still load
2. custom file adds new preset
3. custom file merges new repo into existing preset
4. custom file merges mirror URL into existing variant
5. legacy `presets.yaml` path is ignored
6. `preset apply` still writes merged repo list

## Risks

Only meaningful compatibility break: older local overrides stored in `~/.config/pkgeter/presets.yaml` will stop applying. This is acceptable for this project.
