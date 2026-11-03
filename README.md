# InstaKeep: Save it or lose it

InstaKeep keeps a list of public Instagram profiles and downloads the newest posts of each (5 by default), from a window or the command line. It saves images only unless you ask for more, and it writes every `#hashtag` from a post's caption into its images' Tags, which Windows shows under Properties → Details. Videos, caption files and metadata are opt-in; Tags can be turned off. It's built on [instaloader](https://instaloader.github.io/).

You'll mostly use `instakeep.py`, which opens the window and also has list commands such as `--run` and `--add`. For a one-off download of a single profile from the terminal, there's `igdl USERNAME`.

## Start

```powershell
cd InstaKeep
python instakeep.py      # Windows (not python3, which opens the Microsoft Store)
python3 instakeep.py     # macOS / Linux
```

You don't need to install anything first. On the first start the program checks its setup:

| Check | If it fails |
|-------|-------------|
| Python 3.10+ | Explains and exits. |
| tkinter (window only) | Prints the install command for your OS. |
| instaloader, piexif | Asks, then creates `.venv`, runs `pip install -e .` into it, and restarts inside it. |

From then on, `python instakeep.py` switches to `.venv` by itself. Run `python instakeep.py --check` to see the setup status.

## The window

The window has two tabs. **Batch** works on your saved list of users. **Individual** downloads one post from its link. Below the tabs, the download options, **Stop**, **Open folder** and the log are shared by both, and only one download runs at a time.

Files go to `InstaKeep/downloads/<username>/` unless you pick another folder. Existing files are skipped, so each run only adds new posts. Changes to the list and the options are saved to `data/instakeep.json` as you make them, so they're still there next time.

### Batch

![The Batch tab: saved users with their last download, the estimate, the shared options and the log](docs/screenshot-batch.png)

| Part | What it does |
|------|--------------|
| User table | Your saved list. Last download, Result (`ok`, `stopped`, `not found`...) and Downloaded (files saved) describe the latest run. Time counts up while that user downloads, then shows how long the run took. Longest is the slowest run so far. Total time, Images and Videos add up every download of that user. Click a column heading to sort by it, and click again to reverse. |
| Username box + **Add** | Adds a user (Enter works too). You can type `@name`. Invalid names and duplicates are refused. |
| **Remove selected** (or Delete key) | Removes users from the list. Downloaded files are kept. |
| **Full re-scan selected** | Makes the next Download all posts run of those users look at every post again, to fill gaps (see below). It doesn't start a download. |
| Download all posts / Newest _N_ posts per user | Newest 5 by default. Tick Download all posts to get every post; the Newest box is greyed out while it's ticked. Both are also used by `--run`. |
| Images / Videos / Caption (.txt) / #tags / Metadata | Images and #tags start on and the others start off. Untick Images and tick Videos to get only videos (single-image posts are skipped; carousels keep just their videos). At least one of Images and Videos must be on. See [Captions and hashtag Tags](#captions-and-hashtag-tags). |
| **Download all** / **Download selected** | Downloads for those users. **Stop** finishes the current post and then stops, and it also works during a rate-limit pause. |
| **Open folder** | Opens the selected user's folder, or the output folder. |

If one user fails because the profile doesn't exist or is private, the others still run. If Instagram rate-limits or blocks requests, the remaining users are skipped. **Download all** (and `--run`) starts with whoever has gone longest without a successful download, so the users a rate limit skipped go first next time. **Download selected** keeps the list order.

With Download all posts, a user's first download looks at every post. After that, a run stops once it reaches 3 posts in a row that are already downloaded (not counting the first 3, which may be old pinned posts). That keeps large profiles from using hundreds of Instagram requests on every run. If files went missing or a download was interrupted part way, use **Full re-scan selected** to look at every post again.

If a saved user isn't found, InstaKeep looks up the account by its ID (saved after each successful download). If the account was renamed, the list switches to the new name and its posts keep going into the old folder, so the history stays in one place. The new name downloads from the next run. Without a login Instagram doesn't always answer this lookup; then the user stays "not found".

### Individual

![The Individual tab: a post link, the add-to-list checkbox and the log of one post's download](docs/screenshot-individual.png)

Paste a post or reel link, such as `https://www.instagram.com/p/EXAMPLE_POST/` (anything after the code, like `?igsh=...`, is ignored), and press **Download post** or Enter. It uses one Instagram request for the post's details.

- The post is saved in `downloads/<account>/` with the same file names Batch uses, so a later Batch download of that account skips it.
- Images, Videos, Caption, #tags and Metadata apply as they do in Batch. With Videos off, a video post is skipped and the log says so; with Images off, so is a single-image post.
- Tick **Also add the post's account to the saved list** to add its account to the Batch list once the post has loaded.
- **Open folder** on this tab opens the folder of the last post's account.
- Only public accounts work. A deleted post and a private account's post both show "couldn't be loaded".

### Estimated download time

The Batch tab estimates how long Download all and Download selected will take. It works from each user's records: how long their images and videos took, how many files a post has, and how many new posts the last download found. A user who hasn't been downloaded yet is left out, since there's nothing to go on; the estimate says how many were left out.

The estimate includes rate-limit pauses. instaloader allows about 200 Instagram requests per 11 minutes and waits once it reaches that. Instagram can block for longer, so if earlier downloads paused more than that, the estimate uses what they saw. With Download all posts, a user's total post count comes from their last download.

## Command line

```powershell
python instakeep.py                     # window
python instakeep.py --run               # download for all saved users, no window
python instakeep.py --check             # setup status
python instakeep.py --list
python instakeep.py --add natgeo nasa
python instakeep.py --remove nasa
python instakeep.py --rescan natgeo     # next "all posts" download looks at every post again
```

While a download runs (in the window or with `--run`), InstaKeep asks the computer not to go to sleep, so a locked screen doesn't pause it. The screen can still turn off and lock. Once the download ends, sleep works as usual again. Closing a laptop lid or pressing the power button still puts it to sleep.

`--run` appends to `logs/run-YYYY-MM-DD.log` and keeps the last 30 log files. A `--run` and the window never download at the same time; whichever starts second gives up and says so.

Known problems (a profile that doesn't exist, a private profile, a rate limit) get one short line. Anything unexpected is a bug: you get its Python traceback, in the terminal, in the window's log, or in the `--run` log file.

| Exit code (`--run`) | Meaning |
|---|---|
| 0 | every user OK |
| 1 | at least one user failed, or a bug (with a traceback) |
| 3 | setup incomplete (run `python instakeep.py` once to install), or `data/instakeep.json` was saved by a newer InstaKeep (see below) |
| 4 | rate-limited or blocked by Instagram |
| 5 | another download was already running |
| 130 | interrupted (Ctrl+C) |

`data/instakeep.json` has a data version. A newer InstaKeep upgrades an older file when it opens it. An older InstaKeep can still read a newer file but won't save to it, because it would drop the settings it doesn't know. That can happen when the window has been open since before a `git pull` and the next `--run` uses the new code. The window then turns off downloading and editing and asks for a restart; `--run`, `--add`, `--remove` and `--rescan` exit with code 3.

## Single profile: `igdl`

`igdl` is installed into `.venv` with everything else. Activate the venv (`.venv\Scripts\activate`, or `source .venv/bin/activate` on macOS/Linux), then:

```powershell
igdl USERNAME [-o DIR] [--limit N] [--videos] [--no-images] [--caption] [--no-tags] [--metadata] [-q]

igdl natgeo --limit 10                # newest 10 image posts, hashtag Tags written -> InstaKeep/downloads/natgeo/
igdl natgeo --limit 10 --videos       # newest 10 posts, videos included
igdl natgeo --videos --no-images      # only videos
igdl natgeo --caption                 # all image posts + caption .txt
igdl natgeo --no-tags                 # all image posts, images left untouched
igdl natgeo -o D:\ig --metadata       # all image posts + .json data -> D:\ig\natgeo\
```

| Exit code (`igdl`) | Meaning |
|---|---|
| 0 | success |
| 1 | profile not found |
| 2 | private profile (can't be downloaded without login) |
| 4 | rate-limited or blocked by Instagram |
| 130 | interrupted (Ctrl+C) |

## What gets downloaded

| | Default (images only) | With videos on |
|---|---|---|
| Photo posts | saved | saved |
| Video and reel posts | skipped (not counted toward the limit) | `.mp4` + cover image |
| Video slides in a carousel | skipped | `.mp4` + cover image |

"Newest N" means the N most recent posts by date. A profile can pin up to 3 posts, which Instagram always lists first, so InstaKeep reads 3 extra posts and keeps the N newest. A pinned post is included only if it's among those N.

Each post is saved as `<username>_YYYY-MM-DD_HH-MM-SS_<shortcode>`, for example `natgeo_2026-11-01_23-53-04_DfN9Oosk9s2_1.jpg`:

| File | When |
|------|------|
| `.jpg` | always. Carousels get `_1`, `_2`, … suffixes |
| `.mp4` | with videos on |
| `.txt` (caption) | with captions on |
| `.json` (full post data) | with metadata on |

### Captions and hashtag Tags

#tags and Caption (.txt) are separate options. With #tags on (the default; `igdl --no-tags` turns it off), every image of a post gets the caption's `#hashtags` as Tags, and no extra file is created. With Caption (.txt) on (off by default; `igdl --caption`), each post also gets a `.txt` file with the full caption.

| Caption | Tags written |
|---------|--------------|
| `Wow this #portrait is awesome.` | `#portrait` |
| `#film #Portrait, shot on #cinestill800t #film` | `#film; #Portrait; #cinestill800t` |

- A tag is `#` followed by letters, digits or `_`, in any language. Duplicates are dropped, ignoring case.
- To see them in Windows Explorer, right-click an image and open Properties → Details → Tags, or search with `tags:#portrait`. They're stored in the EXIF `XPKeywords` field.
- The image isn't re-encoded, so quality doesn't change. Only `.jpg` files get tags.
- With #tags on, each run also tags earlier downloads that don't have Tags yet.

## Architecture

```mermaid
flowchart LR
    win(["instakeep.py<br/>window · --run · --add/--list"])
    term(["igdl USERNAME"])

    subgraph instakeep["instakeep package (the app)"]
        boot["bootstrap.py<br/>setup check · venv install"]
        gui["gui.py<br/>tkinter window"]
        run["runner.py<br/>loop over users · run lock · logs"]
        store["store.py<br/>data/instakeep.json"]
    end

    subgraph igdl["igdl package (the downloader)"]
        cli["cli.py<br/>igdl command · error messages"]
        dl["downloader.py<br/>build_loader · download_user"]
        tags["tags.py<br/>hashtags → EXIF Tags"]
        sec["security.py<br/>username check · strip_control"]
    end

    win --> boot
    win --> gui --> run
    win -->|"--run"| run
    run --> store
    gui --> store
    run --> dl
    run -.->|error messages| cli
    term --> cli --> dl
    dl --> tags
    dl -.-> sec
    dl --> il["instaloader"] --> out[("downloads/&lt;user&gt;/")]
    tags --> px["piexif"] --> out
```

| Path | What |
|------|------|
| [`instakeep.py`](instakeep.py) | Entry point: setup check, then window or command-line mode. |
| [`src/instakeep/bootstrap.py`](src/instakeep/bootstrap.py) | Setup check and venv install (standard library only). |
| [`src/instakeep/store.py`](src/instakeep/store.py) | Saved users and settings. |
| [`src/instakeep/runner.py`](src/instakeep/runner.py) | Downloads for each user, records results, run lock, `--run` logging. |
| [`src/instakeep/gui.py`](src/instakeep/gui.py) | The tkinter window: Batch and Individual tabs. |
| [`src/igdl/cli.py`](src/igdl/cli.py) | The `igdl` command; maps errors to messages and exit codes. |
| [`src/igdl/downloader.py`](src/igdl/downloader.py) | Configures instaloader, reports rate-limit pauses, runs the download loop, downloads a single post. |
| [`src/igdl/tags.py`](src/igdl/tags.py) | Writes caption hashtags into a JPEG's EXIF Tags. |
| [`src/igdl/security.py`](src/igdl/security.py) | Username and post-link checks, stripping control and bidi characters, one-line error messages. |
| [`docs/make_screenshots.py`](docs/make_screenshots.py) | Remakes the README screenshots from made-up users and links (Windows; nothing is downloaded). |

`.venv/`, `data/`, `logs/` and `downloads/` are created at runtime and are git-ignored.

## Tests

```powershell
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m pytest
```

## Caveats

- It only works for public profiles, because there is no login. Instagram may show logged-out visitors fewer posts or block their requests (401/429). If that happens, wait a while and try again.
- instaloader slows itself down to stay under Instagram's limits, and a pause can last several minutes. The log shows something like `Instagram rate limit: pausing 6 min (until 14:05)`, and the download carries on afterwards.
