# Graph Report - InstaKeep  (2026-11-02)

## Corpus Check
- 24 files · ~20,838 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 605 nodes · 1097 edges · 23 communities (16 shown, 7 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 127 edges (avg confidence: 0.87)
- Token cost: 163,908 input · 0 output

## Community Hubs (Navigation)
- Store & Username Validation
- Entry Script & Error Policy
- Window App (gui.App)
- Project Architecture Docs
- Download Time Estimates
- Shared State & Test Rules
- Downloader & CLI Tests
- Setup Bootstrap
- Hashtag EXIF Tags
- Screenshot Generator
- CI Test Workflow
- Runner Tests
- Window Tests
- Stats Merge & Estimate Tests
- README Usage Docs
- Security Tests
- Test Fixtures
- Version Sync Rule
- instakeep Package

## God Nodes (most connected - your core abstractions)
1. `App` - 38 edges
2. `Store` - 37 edges
3. `strip_control()` - 21 edges
4. `run_all()` - 20 edges
5. `describe_unexpected()` - 14 edges
6. `download_user()` - 13 edges
7. `ensure_ready()` - 13 edges
8. `RunLock` - 13 edges
9. `run_headless()` - 13 edges
10. `run()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `First-start setup check (Python 3.10+, tkinter, venv install)` --references--> `ensure_ready()`  [INFERRED]
  README.md → src/instakeep/bootstrap.py
- `Download Log Pane and Status Bar` --conceptually_related_to--> `run_all()`  [INFERRED]
  docs/screenshot-batch.png → src/instakeep/runner.py
- `Network and rate-limit rules (no login, never skip RateController pauses)` --rationale_for--> `_PauseAwareRateController`  [INFERRED]
  memory/python/CLAUDE.md → src/igdl/downloader.py
- `Post link field + Download post button (single post/reel download)` --conceptually_related_to--> `download_single_post()`  [INFERRED]
  docs/screenshot-individual.png → src/igdl/downloader.py
- `InstaKeep Batch Tab Screenshot` --references--> `App`  [INFERRED]
  docs/screenshot-batch.png → src/instakeep/gui.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Cross-process shared-store safety (window + --run)** — claude_shared_store_processes, claude_atomic_mutate, claude_run_lock, claude_settings_validation, memory_python_claude_shared_state_threads [EXTRACTED 1.00]
- **Untrusted input defense** — claude_untrusted_input, memory_python_claude_untrusted_input, src_igdl_security_is_valid_username, src_igdl_security_strip_control [EXTRACTED 1.00]
- **Error reporting flow (known errors vs bugs, exit codes)** — claude_error_handling_policy, memory_python_claude_errors, src_igdl_cli_describe_error, src_igdl_security_describe_unexpected, readme_run_exit_codes, readme_igdl_exit_codes [INFERRED 0.85]

## Communities (23 total, 7 thin omitted)

### Community 0 - "Store & Username Validation"
Cohesion: 0.06
Nodes (26): stub_store(), normalize_username(), _clean(), default_settings(), _optional_text(), Store, change(), change() (+18 more)

### Community 1 - "Entry Script & Error Policy"
Cohesion: 0.05
Nodes (18): _headless_say(), main(), parse_args(), run(), _write_log_line(), build_parser(), describe_error(), _err() (+10 more)

### Community 3 - "Project Architecture Docs"
Cohesion: 0.06
Nodes (21): igdl package (download library + CLI), InstaKeep (project guidance), instakeep package (the app), Timing and estimates (DownloadStats, STAT_FIELDS, estimate.py), Batch User Table (Username, Last download, Result, Downloaded, Time, Longest, Total time, Images, Videos), Python guidelines for InstaKeep, Caveats (public only, 401/429 blocks, rate-limit pauses), Estimated download time (+13 more)

### Community 4 - "Download Time Estimates"
Cohesion: 0.07
Nodes (16): ceil_queries(), _check_seconds(), Estimate, estimate(), estimate_user(), _expected_new_posts(), format_duration(), pause_seconds() (+8 more)

### Community 5 - "Shared State & Test Rules"
Cohesion: 0.06
Nodes (13): Store._mutate atomic read-modify-write, CI test workflow (Windows/Linux/macOS, Py 3.10 & 3.14), RunLock (data/run.lock, PID + staleness), exit_code(), make_logger(), log(), _media_files(), open_log() (+5 more)

### Community 6 - "Downloader & CLI Tests"
Cohesion: 0.08
Nodes (24): _fake_feed(), _fake_post(), _posts(), _rate_controller(), test_describe_error_for_a_single_post(), test_describe_error_maps_instaloader_errors(), test_images_only_by_default_and_limit_counts_images(), test_limit_includes_pinned_post_when_recent_enough() (+16 more)

### Community 7 - "Setup Bootstrap"
Cohesion: 0.08
Nodes (15): _ask_console(), _ask_gui(), ensure_ready(), has_tkinter(), in_venv(), _install(), missing_modules(), relaunch() (+7 more)

### Community 8 - "Hashtag EXIF Tags"
Cohesion: 0.09
Nodes (18): _decode_xp(), _encode_xp(), extract_hashtags(), read_tags(), tag_post_images(), write_tags(), pid_alive(), test_pid_alive() (+10 more)

### Community 9 - "Screenshot Generator"
Cohesion: 0.09
Nodes (14): capture(), main(), write_png(), InstaKeep Batch Tab Screenshot, Download Options (Videos, Caption, #tags, Metadata, Output folder), Estimated Download Time Panel, Download Log Pane and Status Bar, Newest N Posts Per User / Download All Posts (+6 more)

### Community 10 - "CI Test Workflow"
Cohesion: 0.07
Nodes (29): concurrency, cancel-in-progress, group, jobs, pytest, os, python, name (+21 more)

### Community 11 - "Runner Tests"
Cohesion: 0.13
Nodes (20): Blocked, describe(), FakeLoader, context, make_download(), download_user(), NotFound, run() (+12 more)

### Community 12 - "Window Tests"
Cohesion: 0.10
Nodes (8): app(), _run_post(), test_lock_failure_ends_the_run_and_reenables_buttons(), test_missing_post_shows_a_short_error(), test_post_download_can_add_its_account(), test_post_download_leaves_the_list_alone_when_unticked(), test_remove_asks_first_and_keeps_files(), tk_root()

### Community 13 - "Stats Merge & Estimate Tests"
Cohesion: 0.22
Nodes (15): _clean_stats(), empty_stats(), merge_stats(), change(), settings(), test_all_posts_counts_whats_missing_from_disk(), test_all_posts_without_a_post_count_uses_the_posts_seen(), test_format_duration() (+7 more)

### Community 14 - "README Usage Docs"
Cohesion: 0.19
Nodes (12): --run and igdl exit codes, Architecture flowchart (mermaid), Batch tab, Command line (--run, --check, --list, --add, --remove), Captions and hashtag Tags (EXIF XPKeywords), igdl single-profile CLI, igdl exit codes table, InstaKeep: Save it or lose it (README) (+4 more)

### Community 15 - "Security Tests"
Cohesion: 0.20
Nodes (3): test_is_valid_username(), test_parse_post_url(), test_parse_post_url_rejects_other_text()

### Community 16 - "Test Fixtures"
Cohesion: 0.20
Nodes (5): app_files_in_tmp(), Dialogs, dialogs(), fake(), hidden_windows()

## Knowledge Gaps
- **11 isolated node(s):** `instakeep`, `CI test workflow (Windows/Linux/macOS, Py 3.10 & 3.14)`, `igdl.__version__ synced with pyproject.toml`, `--run and igdl exit codes`, `igdl exit codes table` (+6 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 252 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `App` connect `Window App (gui.App)` to `Store & Username Validation`, `Screenshot Generator`, `Download Time Estimates`, `Shared State & Test Rules`?**
  _High betweenness centrality (0.123) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `App` (e.g. with `InstaKeep Batch Tab Screenshot` and `Individual Tab Screenshot (InstaKeep window)`) actually correct?**
  _`App` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `instakeep`, `CI test workflow (Windows/Linux/macOS, Py 3.10 & 3.14)`, `igdl.__version__ synced with pyproject.toml` to the rest of the system?**
  _11 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Store & Username Validation` be split into smaller, more focused modules?**
  _Cohesion score 0.05961538461538462 - nodes in this community are weakly interconnected._
- **Why does `Store` connect `Store & Username Validation` to `Entry Script & Error Policy`, `Window App (gui.App)`, `Download Time Estimates`, `Shared State & Test Rules`, `Runner Tests`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `Store` (e.g. with `stub_store()` and `main()`) actually correct?**
  _`Store` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Should `Entry Script & Error Policy` be split into smaller, more focused modules?**
  _Cohesion score 0.05245901639344262 - nodes in this community are weakly interconnected._