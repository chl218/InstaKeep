# Graph Report - InstaKeep  (2026-11-02)

## Corpus Check
- 23 files · ~17,520 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 502 nodes · 934 edges · 21 communities (13 shown, 8 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 108 edges (avg confidence: 0.87)
- Token cost: 68,921 input · 0 output

## Community Hubs (Navigation)
- Store & Usernames
- igdl CLI & Downloader
- Window (gui.py App)
- Project Rules (CLAUDE.md)
- Test Fixtures (conftest)
- Setup Check (bootstrap)
- igdl CLI Tests
- Runner Tests
- Security & Tag Tests
- Time Estimates
- Security Helpers
- Headless Run & Stats
- Stats Merge & Estimate Tests
- Entry Point (main-program)
- Hashtag Tags (EXIF)
- Run Lock & Worker
- Logs & Media Files
- Duration Formatting
- instakeep Package

## God Nodes (most connected - your core abstractions)
1. `Store` - 33 edges
2. `App` - 30 edges
3. `strip_control()` - 19 edges
4. `run_all()` - 16 edges
5. `InstaKeep CLAUDE.md Project Guide` - 15 edges
6. `download_user()` - 13 edges
7. `run_headless()` - 13 edges
8. `describe_unexpected()` - 12 edges
9. `run()` - 12 edges
10. `normalize_username()` - 11 edges

## Surprising Connections (you probably didn't know these)
- `Startup Constraint (stdlib-only modules)` --semantically_similar_to--> `Stdlib-only Until Setup Passes`  [INFERRED] [semantically similar]
  memory/python/CLAUDE.md → CLAUDE.md
- `Error Rules (single mapping, boundary catches with noqa reason)` --semantically_similar_to--> `Error Handling Policy (describe_error / describe_unexpected)`  [INFERRED] [semantically similar]
  memory/python/CLAUDE.md → CLAUDE.md
- `Shared State and Thread Rules` --semantically_similar_to--> `Window and --run Share data/instakeep.json`  [INFERRED] [semantically similar]
  memory/python/CLAUDE.md → CLAUDE.md
- `Shared State and Thread Rules` --semantically_similar_to--> `GUI Worker Thread + App.messages Queue`  [INFERRED] [semantically similar]
  memory/python/CLAUDE.md → CLAUDE.md
- `Untrusted Input Rules (validate, strip_control, no shell=True)` --semantically_similar_to--> `Untrusted Input Handling`  [INFERRED] [semantically similar]
  memory/python/CLAUDE.md → CLAUDE.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Cross-process coordination between window and --run** — claude_shared_store_between_processes, claude_atomic_store_mutate, claude_runlock, claude_settings_validation, memory_python_claude_shared_state_rules [EXTRACTED 1.00]
- **Rate-limit visibility and stop handling** — claude_pause_aware_rate_controller, memory_python_claude_rate_limit_rules, memory_python_claude_should_stop, readme_estimated_download_time, readme_instaloader [INFERRED 0.85]
- **Error mapping and exit-code contract** — claude_error_handling_policy, memory_python_claude_error_rules, claude_run_exit_codes, claude_igdl_exit_codes, claude_shared_run_all [INFERRED 0.85]

## Communities (21 total, 8 thin omitted)

### Community 0 - "Store & Usernames"
Cohesion: 0.05
Nodes (28): is_valid_username(), normalize_username(), _clean(), _clean_stats(), default_settings(), empty_stats(), _optional_text(), Store (+20 more)

### Community 1 - "igdl CLI & Downloader"
Cohesion: 0.06
Nodes (19): build_parser(), describe_error(), _err(), main(), parse_args(), positive_int(), build_loader(), _count_new_files() (+11 more)

### Community 3 - "Project Rules (CLAUDE.md)"
Cohesion: 0.07
Nodes (29): Absolute Paths in instakeep/paths.py, Store._mutate Atomic Re-read/Write, Headless Network-free Tests (conftest dialogs fixture), igdl Exit Codes (0,1,2,4,130), InstaKeep CLAUDE.md Project Guide, _PauseAwareRateController, Pinned Post Handling (limit + 3), --run Exit Codes (0,1,3,4,5,130) (+21 more)

### Community 4 - "Test Fixtures (conftest)"
Cohesion: 0.06
Nodes (13): main(), app_files_in_tmp(), Dialogs, dialogs(), fake(), hidden_windows(), app(), store() (+5 more)

### Community 5 - "Setup Check (bootstrap)"
Cohesion: 0.09
Nodes (15): _ask_console(), _ask_gui(), ensure_ready(), has_tkinter(), in_venv(), _install(), missing_modules(), relaunch() (+7 more)

### Community 6 - "igdl CLI Tests"
Cohesion: 0.09
Nodes (19): _fake_feed(), _posts(), _rate_controller(), test_describe_error_maps_instaloader_errors(), test_images_only_by_default_and_limit_counts_images(), test_limit_includes_pinned_post_when_recent_enough(), test_limit_must_be_positive(), test_limit_skips_old_pinned_posts() (+11 more)

### Community 7 - "Runner Tests"
Cohesion: 0.15
Nodes (19): Blocked, describe(), FakeLoader, context, make_download(), download_user(), NotFound, run() (+11 more)

### Community 8 - "Security & Tag Tests"
Cohesion: 0.11
Nodes (11): test_is_valid_username(), _download_one(), fake_download_post(), make_jpeg(), test_download_leaves_tags_alone_when_tags_off(), test_download_writes_hashtags_when_tags_on(), test_extract_hashtags(), test_tag_post_images_single_and_carousel() (+3 more)

### Community 9 - "Time Estimates"
Cohesion: 0.15
Nodes (10): ceil_queries(), _check_seconds(), Estimate, estimate(), estimate_user(), _expected_new_posts(), pause_seconds(), _ratio() (+2 more)

### Community 11 - "Headless Run & Stats"
Cohesion: 0.17
Nodes (8): DownloadStats, exit_code(), make_logger(), log(), run_all(), run_headless(), _run_stats(), UserResult

### Community 12 - "Stats Merge & Estimate Tests"
Cohesion: 0.29
Nodes (11): merge_stats(), settings(), test_all_posts_counts_whats_missing_from_disk(), test_all_posts_unknown_until_first_download(), test_format_duration(), test_history_sets_the_speed_and_the_expected_new_posts(), test_never_downloaded_uses_defaults_for_all_n_posts(), test_rate_limit_pauses_from_history_when_larger() (+3 more)

### Community 13 - "Entry Point (main-program)"
Cohesion: 0.20
Nodes (5): _headless_say(), main(), parse_args(), run(), _write_log_line()

### Community 14 - "Hashtag Tags (EXIF)"
Cohesion: 0.26
Nodes (5): _decode_xp(), _encode_xp(), read_tags(), tag_post_images(), write_tags()

## Knowledge Gaps
- **7 isolated node(s):** `instakeep`, `Store._mutate Atomic Re-read/Write`, `Absolute Paths in instakeep/paths.py`, `igdl.__version__ Synced with pyproject.toml`, `File Naming <username>_YYYY-MM-DD_HH-MM-SS_<shortcode>` (+2 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 196 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Store` connect `Store & Usernames` to `Window (gui.py App)`, `Test Fixtures (conftest)`, `Security Helpers`, `Headless Run & Stats`, `Entry Point (main-program)`?**
  _High betweenness centrality (0.111) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `Store` (e.g. with `main()` and `App`) actually correct?**
  _`Store` has 16 INFERRED edges - model-reasoned connections that need verification._
- **What connects `instakeep`, `Store._mutate Atomic Re-read/Write`, `Absolute Paths in instakeep/paths.py` to the rest of the system?**
  _7 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Store & Usernames` be split into smaller, more focused modules?**
  _Cohesion score 0.054244306418219465 - nodes in this community are weakly interconnected._
- **Why does `App` connect `Window (gui.py App)` to `Store & Usernames`, `Security Helpers`, `Test Fixtures (conftest)`, `Run Lock & Worker`?**
  _High betweenness centrality (0.102) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `run_all()` (e.g. with `Store` and `.record_result()`) actually correct?**
  _`run_all()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Should `igdl CLI & Downloader` be split into smaller, more focused modules?**
  _Cohesion score 0.05584415584415584 - nodes in this community are weakly interconnected._