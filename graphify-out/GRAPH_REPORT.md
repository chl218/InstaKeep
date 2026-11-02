# Graph Report - InstaKeep  (2026-11-02)

## Corpus Check
- 21 files · ~10,581 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 329 nodes · 592 edges · 12 communities (11 shown, 1 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 64 edges (avg confidence: 0.86)
- Token cost: 54,766 input · 0 output

## Community Hubs (Navigation)
- Store & Settings
- igdl CLI & Downloader
- Python Coding Guidelines
- Entry Point (main-program)
- igdl CLI Tests
- Runner & Run Lock
- Setup Check (bootstrap)
- Window (gui.py)
- Runner Tests
- Hashtag Tags (EXIF)
- Tag Tests
- instakeep Package

## God Nodes (most connected - your core abstractions)
1. `Store` - 30 edges
2. `App` - 20 edges
3. `Python cybersecurity-tool development guidelines` - 17 edges
4. `strip_control()` - 14 edges
5. `run_headless()` - 12 edges
6. `run_all()` - 11 edges
7. `ensure_ready()` - 10 edges
8. `RunLock` - 10 edges
9. `run()` - 10 edges
10. `main()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `igdl cli.py` --semantically_similar_to--> `Custom exceptions mapped to CLI/API messages`  [INFERRED] [semantically similar]
  README.md → memory/python/CLAUDE.md
- `security.py username check and strip_control` --semantically_similar_to--> `Sanitize all external inputs`  [INFERRED] [semantically similar]
  README.md → memory/python/CLAUDE.md
- `Instagram rate-limit pauses` --semantically_similar_to--> `Rate-limiting and back-off for network operations`  [INFERRED] [semantically similar]
  README.md → memory/python/CLAUDE.md
- `main()` --calls--> `normalize_username()`  [INFERRED]
  main-program.py → src/instakeep/store.py
- `main()` --uses--> `Store`  [INFERRED]
  main-program.py → src/instakeep/store.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **igdl download pipeline** — readme_downloader, readme_tags, readme_piexif, readme_security [EXTRACTED 1.00]
- **instakeep app package** — readme_bootstrap_setup_check, readme_gui, readme_runner, readme_store [EXTRACTED 1.00]

## Communities (12 total, 1 thin omitted)

### Community 0 - "Store & Settings"
Cohesion: 0.07
Nodes (19): _clean(), default_settings(), normalize_username(), Store, change(), change(), store(), store() (+11 more)

### Community 1 - "igdl CLI & Downloader"
Cohesion: 0.07
Nodes (15): describe_error(), _err(), main(), parse_args(), build_loader(), download_user(), DownloadStopped, format_pause() (+7 more)

### Community 2 - "Python Coding Guidelines"
Cohesion: 0.06
Nodes (23): FastAPI docs, Module layout (scanners, enumerators, attackers, reporting, utils, types), NIST SP 800-115, OWASP Testing Guide, Pydantic v2 input validation, pytest and pytest-asyncio with mocked network, Python cybersecurity-tool development guidelines, downloader.py (build_loader, download_user) (+15 more)

### Community 3 - "Entry Point (main-program)"
Cohesion: 0.08
Nodes (6): _headless_say(), main(), parse_args(), build_parser(), positive_int(), test_is_valid_username()

### Community 4 - "igdl CLI Tests"
Cohesion: 0.10
Nodes (16): _fake_feed(), _posts(), _rate_controller(), test_describe_error_maps_instaloader_errors(), test_images_only_by_default_and_limit_counts_images(), test_limit_includes_pinned_post_when_recent_enough(), test_limit_must_be_positive(), test_limit_skips_old_pinned_posts() (+8 more)

### Community 5 - "Runner & Run Lock"
Cohesion: 0.12
Nodes (10): exit_code(), make_logger(), log(), _media_files(), open_log(), pid_alive(), run_all(), run_headless() (+2 more)

### Community 6 - "Setup Check (bootstrap)"
Cohesion: 0.12
Nodes (10): _ask_console(), _ask_gui(), ensure_ready(), has_tkinter(), in_venv(), _install(), missing_modules(), _relaunch() (+2 more)

### Community 7 - "Window (gui.py)"
Cohesion: 0.13
Nodes (3): App, format_last(), main()

### Community 8 - "Runner Tests"
Cohesion: 0.18
Nodes (13): Blocked, describe(), FakeLoader, context, make_download(), NotFound, run(), test_downloads_every_user_with_limit() (+5 more)

### Community 9 - "Hashtag Tags (EXIF)"
Cohesion: 0.24
Nodes (6): _decode_xp(), _encode_xp(), read_tags(), tag_post_images(), write_tags(), test_pid_alive()

### Community 10 - "Tag Tests"
Cohesion: 0.23
Nodes (9): _download_one(), fake_download_post(), make_jpeg(), test_download_leaves_tags_alone_when_caption_off(), test_download_writes_hashtags_when_caption_on(), test_extract_hashtags(), test_tag_post_images_single_and_carousel(), test_write_and_read_tags_round_trip() (+1 more)

## Ambiguous Edges - Review These
- `InstaKeep` → `Python cybersecurity-tool development guidelines`  [AMBIGUOUS]
  memory/python/CLAUDE.md · relation: conceptually_related_to

## Knowledge Gaps
- **12 isolated node(s):** `instakeep`, `data/instakeep.json`, `EXIF XPKeywords field`, `--run logging with 30-file retention`, `Exit codes (--run and igdl)` (+7 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 131 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Store` connect `Store & Settings` to `Entry Point (main-program)`, `Runner & Run Lock`, `Window (gui.py)`?**
  _High betweenness centrality (0.134) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `Store` (e.g. with `main()` and `App`) actually correct?**
  _`Store` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `instakeep`, `data/instakeep.json`, `EXIF XPKeywords field` to the rest of the system?**
  _12 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Store & Settings` be split into smaller, more focused modules?**
  _Cohesion score 0.07450980392156863 - nodes in this community are weakly interconnected._
- **Why does `App` connect `Window (gui.py)` to `Store & Settings`, `Runner & Run Lock`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `run_headless()` (e.g. with `.acquire()` and `Store`) actually correct?**
  _`run_headless()` has 3 INFERRED edges - model-reasoned connections that need verification._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `InstaKeep` and `Python cybersecurity-tool development guidelines`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._