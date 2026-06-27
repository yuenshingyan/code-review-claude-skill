# vendor/

Place your highlight.js files here to enable syntax highlighting in generated code reviews.

## Setup

1. Download highlight.js from https://highlightjs.org/download
   - Choose "Custom package" and select the languages you need, or download the full build
   - Extract the zip

2. Copy these two files into this directory:
   - `highlight.min.js` — the JavaScript library
   - Any one CSS theme file (e.g. `github-dark.min.css`, `atom-one-dark.min.css`) — rename or copy as-is

   For a dark-themed review (the default), pick a dark theme. Recommended: `github-dark.min.css`.

3. Re-run `build_review.py` — it will detect the files and embed them inline.

## How it works

`build_review.py` checks for `vendor/highlight.min.js` at build time. If found, it also picks up
the first `.css` file in this directory and embeds both inline into the output HTML. The output
remains a fully self-contained file — no network requests for highlighting.

If neither file is present, the review is generated without syntax highlighting (current behavior).

## Supported theme files

Any `.css` file in this directory is treated as the highlight.js theme. Name it anything you like.
Only one CSS file is used; if multiple are present, the first one (alphabetically) is picked.
