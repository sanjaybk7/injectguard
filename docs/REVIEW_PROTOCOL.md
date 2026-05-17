# Review protocol — pasting URLs for review

Operational guidance for anyone (Claude Code, the maintainer, or a future
contributor) pasting GitHub URLs into review conversations so the
reviewer fetches the *intended* version of the file rather than a stale
cached one.

## Why this document exists

During the v0.2 PR cycle, the same problem hit twice in a row:

1. **PR #4 fixture-inventory review:** the maintainer's fetch tool
   served the pre-update content even though the post-update content
   was already on GitHub. Root cause was the maintainer's tool caching
   the branch URL response and ignoring a custom `?cachebust=...`
   query string.
2. **PR #7 README review:** the same fetch-tool cache served pre-fix
   content for the README. Three different cache-bust query patterns
   (`?v=<timestamp>`, `?nocache=<uuid>`, `Cache-Control: no-cache`
   header) all failed to dislodge the maintainer-side cache for that
   specific URL.

Both incidents wasted ~30 minutes of review cycle each on diagnostics
to prove that GitHub was already serving the correct content. The root
cause in both cases was that the URL the reviewer's fetch tool was
asked to load resolved to the same cache key as a previous, stale
fetch — and the cache key was based on the branch URL, not the commit
state.

## The protocol

**When pasting URLs for review, include both forms:**

### Branch URL (for context — humans browse this)

```
https://raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>
```

Example:
```
https://raw.githubusercontent.com/sanjaybk7/agentic-guard/main/docs/THREAT_MODEL.md
```

Mutable. Resolves to whatever the branch tip currently is. Good for
the human reviewer who wants to "always see the latest." Bad for
fetch tools that cache by URL — the cache entry for this URL can
hold stale content indefinitely.

### Commit-SHA URL (for fetch — immutable, cache-safe)

```
https://raw.githubusercontent.com/<owner>/<repo>/<full-40-char-commit-sha>/<path>
```

Example:
```
https://raw.githubusercontent.com/sanjaybk7/agentic-guard/de7e3cc7c0a4f1b2e9d8c3a5b7e6f8a9d0c1e2f3/docs/THREAT_MODEL.md
```

Immutable. The URL itself contains a content-addressable commit SHA;
GitHub serves exactly that revision forever. Fetch tools treat each
SHA as a distinct cache entry — a previous fetch of the branch URL
cannot poison this read.

**Always use the full 40-character SHA**, not the abbreviated 7-char
form. The 7-char form is ambiguous as the repo grows; the full SHA is
content-addressable and unambiguous.

## How to produce the commit-SHA URL

After committing and pushing, get the full SHA:

```bash
git rev-parse HEAD          # full 40-char SHA of current HEAD
git log --format=%H -1       # same, alternative
```

Then construct the URL:

```bash
echo "https://raw.githubusercontent.com/<owner>/<repo>/$(git rev-parse HEAD)/<path>"
```

For Claude Code in this project: the convention going forward is to
include both URLs in any review-pasting status message. The branch URL
is for the maintainer's bookmark / browser; the commit-SHA URL is for
their fetch tool.

## What this protocol does NOT fix

- It doesn't fix GitHub's CDN if GitHub itself is serving stale
  content. The PR #4 and PR #7 incidents were both maintainer-side,
  but a future GitHub-side incident would need a different remediation
  (try the Contents API at `api.github.com/repos/<owner>/<repo>/contents/<path>?ref=<ref>`
  as a different code path).
- It doesn't fix browser caches. A browser viewing a `raw.githubusercontent.com`
  URL caches per its own rules; a hard refresh / private window is the
  fix there.
- It doesn't fix tools that pre-resolve the branch URL into a commit-SHA
  URL internally and then cache by the resolved URL. Such tools should
  in principle handle this correctly, but if they're caching the
  *resolution* itself (mapping branch → SHA) and reusing it past the
  branch's actual movement, the cache will still serve stale content.
  Cache-busting at the URL level can't help; the fix is tool-level
  cache invalidation or tool restart.

## When the protocol fails

If even commit-SHA URLs are serving stale content on the reviewer's
end, the diagnostic protocol from the PR #7 review session applies:

1. Hash the file locally (`shasum -a 256 <file>`).
2. Hash what `raw.githubusercontent.com` serves (with `curl -sL`).
3. Hash what the GitHub Contents API returns (decode the base64
   `content` field).
4. If all three agree but the reviewer's tool disagrees, the issue is
   tool-side. Use a different fetch mechanism (different tool, browser,
   `gh api`, etc.) or restart the tool.
