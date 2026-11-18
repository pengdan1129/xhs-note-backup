# Xiaohongshu Note Backup

[简体中文](README.md) · [English](README.en.md)

Back up your own Xiaohongshu notes, downloadable images and videos, and the comments and replies the website can load.

## Run it with an AI assistant

Open [Xiaohongshu Creator Center · Note Management](https://creator.xiaohongshu.com/new/note-manager) to find your notes.

**Share this repository with an AI assistant that has terminal and browser access. It can install the dependencies and run the tool for you.** For example:

> Read this repository's README and back up my Xiaohongshu notes. Test the first three notes and check the results before running a full backup. Let me know if I need to scan a QR code to sign in.

The assistant should clone the repository, create a virtual environment, install the dependencies, and run the commands below in an environment that can open a browser window and write local files. Use the 24-character ID after `/user/profile/` in the user's profile URL. If Xiaohongshu asks for sign-in, have the user scan the QR code in the browser. Once the notes are visible in Creator Center, press Enter in the script's terminal to continue.

## Run it from the terminal

From the repository directory, replace `OWNER_ID` with your profile ID. The first four lines are for initial setup.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
python xhs_backup.py --owner OWNER_ID --limit 3
```

After checking the test backup, run `python xhs_backup.py --owner OWNER_ID` for a full backup. The default destination is `~/Downloads/XHS-Code-Backup`. Use `--output` to change it.

Each note has its own folder with `note.md`, media files, and `comments.json`. If comment loading stops early, the script keeps the comments it collected and tries again on a later run. Check the terminal output and `failures.jsonl` for missing items.

## How it works

The Python script uses Playwright to control a browser. It locates titles, text, comments, and controls through the page's **DOM**. When Playwright opens a note or expands a reply thread, the site's own JavaScript fetches more data and updates the DOM. The script then reads the updated nodes. It also runs its own JavaScript through Playwright's `evaluate()` to read page elements and scroll the comment panel.

Element selection uses the structure of the page, so the script does not need screenshot recognition, OCR, or fixed screen coordinates. It leaves note and comment requests to the website. For images and videos, it reads the media URLs from the note page and downloads the files over HTTP.
