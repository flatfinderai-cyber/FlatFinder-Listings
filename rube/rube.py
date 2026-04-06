#!/usr/bin/env python3
"""
rube — the Python-native continuous AI dev loop.
rube.works

Pure Python (stdlib only). Zero Node.js. Model-agnostic.
Automates: branch → AI coding → commit → PR (with @sourcery-ai review) → wait → merge → repeat.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

PROMPT_COMMIT = (
    "Please review all uncommitted changes in the git repository (both modified and new "
    "files). Write a commit message with: (1) a short one-line summary, (2) two newlines, "
    "(3) then a detailed explanation. Do not include any footers or metadata. "
    "First run 'git add .' to stage all changes including new untracked files, then commit "
    "using 'git commit -m \"your message\"' (don't push, just commit)."
)

PROMPT_WORKFLOW_CONTEXT = """\
## RUBE WORKFLOW CONTEXT

This is part of a continuous development loop where work happens incrementally across
multiple iterations. You might run once, then a human developer might make changes, then
you run again. This could happen on any schedule.

**Important**: You don't need to complete the entire goal in one iteration. Make meaningful
progress, then leave clear notes for the next iteration (human or AI). Think relay race.

**Do NOT commit or push changes** — Rube will handle that after you finish. Just focus on
code changes.

**Project Completion Signal**: If the ENTIRE project goal is fully complete, include the
exact phrase "{completion_signal}" in your response. Use this only when absolutely certain.

## PRIMARY GOAL

{prompt}
"""

PROMPT_NOTES_UPDATE = (
    "Update the `{notes_file}` file with relevant context for the next iteration. "
    "Add new notes and remove outdated information to keep it current and useful.\n\n"
    "This file should:\n"
    "- Contain relevant context and instructions for the next iteration\n"
    "- Stay concise and actionable\n"
    "- NOT include lists of completed work, full reports, or info discoverable from tests\n"
)

PROMPT_NOTES_CREATE = (
    "Create a `{notes_file}` file with relevant context and instructions for the next "
    "iteration. Keep it concise, actionable, and useful for the next developer (human or AI)."
)

PROMPT_REVIEWER = """\
## REVIEW CONTEXT

You are performing a review pass on changes just made by another developer. This is NOT
a new feature implementation — validate existing changes per the instructions below.

**Do NOT commit or push** — Rube handles that.

## REVIEW TASK

{review_prompt}
"""

PROMPT_CI_FIX = """\
## CI FAILURE FIX CONTEXT

You are analyzing and fixing a CI/CD failure for pull request #{pr_number} on {owner}/{repo}.

Commands to inspect failures:
  gh run list --status failure --limit 3
  gh run view <RUN_ID> --log-failed

Your task:
1. Inspect the failed CI workflow
2. Analyze error logs
3. Make minimal code changes to fix the issue
4. Stage, commit AND PUSH your changes (they will update the PR){run_id_hint}

Focus only on fixing CI, not adding new features.
"""

PROMPT_COMMENT_REVIEW = """\
## PR COMMENT REVIEW CONTEXT

Address review comments on PR #{pr_number} in {owner}/{repo}.

1. Read inline comments:  gh api repos/{owner}/{repo}/pulls/{pr_number}/comments
2. Read PR-level comments: gh api repos/{owner}/{repo}/issues/{pr_number}/comments
3. Make necessary code changes to address the feedback
4. Stage, commit AND PUSH with a clear message describing what you addressed
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(cmd: list[str], *, check: bool = True, capture: bool = False, cwd: str | None = None):
    """Run a subprocess, optionally capturing output."""
    result = subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        cwd=cwd,
    )
    return result


def run_capture(cmd: list[str], *, cwd: str | None = None) -> tuple[int, str, str]:
    """Run and return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def gh(*args: str, capture: bool = True, cwd: str | None = None) -> tuple[int, str, str]:
    return run_capture(["gh", *args], cwd=cwd)


def git(*args: str, capture: bool = True, cwd: str | None = None) -> tuple[int, str, str]:
    return run_capture(["git", *args], cwd=cwd)


def short_id() -> str:
    import hashlib, uuid
    return hashlib.md5(uuid.uuid4().bytes).hexdigest()[:8]


def now_slug() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def fmt_cost(usd: float) -> str:
    return f"${usd:.3f}"


def parse_duration(s: str) -> int:
    """Parse '2h', '30m', '1h30m', '90s' → seconds."""
    s = s.strip()
    total = 0
    for value, unit in re.findall(r"(\d+)([hHmMsS])", s):
        v = int(value)
        u = unit.lower()
        if u == "h":
            total += v * 3600
        elif u == "m":
            total += v * 60
        elif u == "s":
            total += v
    if total == 0:
        raise ValueError(f"Cannot parse duration: {s!r}")
    return total


def format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return "".join(parts)


def detect_github_remote(cwd: str | None = None) -> tuple[str, str] | None:
    """Return (owner, repo) from git remote origin, or None."""
    code, url, _ = git("remote", "get-url", "origin", cwd=cwd)
    if code != 0:
        return None
    # https://github.com/owner/repo(.git)
    m = re.match(r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)
    # git@github.com:owner/repo(.git)
    m = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)
    return None


def has_changes(cwd: str | None = None) -> bool:
    """Return True if working tree or index has any changes."""
    code1, _, _ = git("diff", "--quiet", "--ignore-submodules=dirty", cwd=cwd)
    code2, _, _ = git("diff", "--cached", "--quiet", "--ignore-submodules=dirty", cwd=cwd)
    _, untracked, _ = git("ls-files", "--others", "--exclude-standard", cwd=cwd)
    return code1 != 0 or code2 != 0 or bool(untracked)


def current_branch(cwd: str | None = None) -> str:
    _, branch, _ = git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    return branch or "main"


# ---------------------------------------------------------------------------
# AI runner (model-agnostic)
# ---------------------------------------------------------------------------


def run_ai(
    prompt: str,
    cfg: "Config",
    label: str,
    log_path: str,
) -> tuple[bool, str, float]:
    """
    Invoke the configured AI command with the given prompt.

    Returns (success, raw_output, cost_usd).
    cost_usd is extracted from JSON if available, else 0.0.
    """
    cmd = [cfg.ai_cmd] + cfg.ai_flags + ["-p", prompt]
    if cfg.extra_ai_flags:
        cmd += cfg.extra_ai_flags

    print(f"   {label} 🤖 Running {cfg.ai_cmd}...", file=sys.stderr)

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout_lines: list[str] = []
        assert proc.stdout
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            stdout_lines.append(line)
            # If JSON stream, pretty-print assistant text in real-time
            if cfg.ai_output_format == "stream-json":
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "assistant":
                        for block in obj.get("message", {}).get("content", []):
                            if block.get("type") == "text":
                                for txt_line in block["text"].splitlines():
                                    print(f"   {label} 💬 {txt_line}", file=sys.stderr)
                except (json.JSONDecodeError, AttributeError):
                    pass
            else:
                # Plain text output — just echo it
                print(f"   {label} 💬 {line}", file=sys.stderr)

        _, stderr_out = proc.communicate()
        exit_code = proc.returncode

        raw_output = "\n".join(stdout_lines)

        with open(log_path, "w") as f:
            f.write(stderr_out)
        with open(tmp_path, "w") as f:
            f.write(raw_output)

        cost = 0.0
        if cfg.ai_output_format == "stream-json" and raw_output:
            try:
                objs = [json.loads(l) for l in raw_output.splitlines() if l.strip()]
                if objs:
                    cost = float(objs[-1].get("total_cost_usd") or 0.0)
            except (json.JSONDecodeError, ValueError):
                pass

        if exit_code != 0:
            print(
                f"   {label} ⚠️  {cfg.ai_cmd} exited with code {exit_code}",
                file=sys.stderr,
            )
            if stderr_out:
                print(stderr_out, file=sys.stderr)
            return False, raw_output, cost

        return True, raw_output, cost

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def extract_result_text(raw: str, fmt: str) -> str:
    """Pull the final text result out of AI output."""
    if fmt == "stream-json":
        try:
            objs = [json.loads(l) for l in raw.splitlines() if l.strip()]
            if objs:
                return objs[-1].get("result", "") or ""
        except (json.JSONDecodeError, ValueError):
            pass
        return ""
    return raw


# ---------------------------------------------------------------------------
# Git / GitHub operations
# ---------------------------------------------------------------------------


def create_branch(prefix: str, iteration: int, cwd: str | None = None) -> str | None:
    branch = f"{prefix}iteration-{iteration}/{now_slug()}-{short_id()}"
    code, _, err = git("checkout", "-b", branch, cwd=cwd)
    if code != 0:
        print(f"   ❌ Failed to create branch: {err}", file=sys.stderr)
        return None
    print(f"   🌿 Created branch: {branch}", file=sys.stderr)
    return branch


def commit_changes(prompt: str, cfg: "Config", label: str, log_path: str, cwd: str | None = None) -> bool:
    """Ask the AI to commit all pending changes."""
    print(f"   {label} 💬 Committing changes...", file=sys.stderr)
    ok, _, _ = run_ai(prompt, cfg, label, log_path)
    if not ok:
        return False
    if has_changes(cwd=cwd):
        print(f"   {label} ⚠️  Changes still present after commit attempt", file=sys.stderr)
        return False
    print(f"   {label} 📦 Changes committed", file=sys.stderr)
    return True


def push_branch(branch: str, cwd: str | None = None) -> bool:
    print(f"   📤 Pushing {branch}...", file=sys.stderr)
    code, _, err = git("push", "-u", "origin", branch, cwd=cwd)
    if code != 0:
        print(f"   ⚠️  Push failed: {err}", file=sys.stderr)
        return False
    return True


def create_pr(
    owner: str,
    repo: str,
    base: str,
    title: str,
    body: str,
    reviewers: list[str],
    cwd: str | None = None,
) -> str | None:
    """Create a PR and return its number as a string, or None on failure."""
    cmd = [
        "gh", "pr", "create",
        "--repo", f"{owner}/{repo}",
        "--title", title,
        "--body", body,
        "--base", base,
    ]
    for r in reviewers:
        cmd += ["--reviewer", r]

    code, out, err = run_capture(cmd, cwd=cwd)
    if code != 0:
        print(f"   ⚠️  PR creation failed: {err}", file=sys.stderr)
        return None

    m = re.search(r"(?:pull/|#)(\d+)", out)
    if not m:
        print(f"   ⚠️  Could not parse PR number from: {out!r}", file=sys.stderr)
        return None
    return m.group(1)


def close_pr(owner: str, repo: str, pr: str, cwd: str | None = None) -> None:
    gh("pr", "close", pr, "--repo", f"{owner}/{repo}", "--delete-branch", cwd=cwd)


def merge_pr(owner: str, repo: str, pr: str, strategy: str, cwd: str | None = None) -> bool:
    flag = {"squash": "--squash", "rebase": "--rebase", "merge": "--merge"}.get(strategy, "--squash")
    code, _, err = gh("pr", "merge", pr, "--repo", f"{owner}/{repo}", flag, "--auto", cwd=cwd)
    if code != 0:
        # --auto might fail if not supported; try without
        code, _, err = gh("pr", "merge", pr, "--repo", f"{owner}/{repo}", flag, cwd=cwd)
    if code != 0:
        print(f"   ⚠️  Merge failed: {err}", file=sys.stderr)
        return False
    return True


def get_pr_title_body(branch: str, cwd: str | None = None) -> tuple[str, str]:
    _, log, _ = git("log", "-1", "--format=%B", branch, cwd=cwd)
    lines = log.strip().splitlines()
    title = lines[0] if lines else "Rube iteration"
    body = "\n".join(lines[3:]) if len(lines) > 3 else ""
    return title, body


def wait_for_pr_checks(
    owner: str, repo: str, pr: str, label: str, max_wait: int = 1800, poll: int = 10
) -> bool:
    """
    Poll PR checks + review status until all pass or timeout/failure.
    Returns True if all green and approved (or no checks/no review required).
    """
    deadline = time.time() + max_wait
    prev_state: dict = {}
    no_checks_warned = False

    while time.time() < deadline:
        # Checks
        code, raw, _ = gh("pr", "checks", pr, "--repo", f"{owner}/{repo}", "--json", "state,bucket")
        no_checks = False
        checks: list[dict] = []
        if code != 0:
            if "no checks" in raw.lower():
                no_checks = True
            else:
                print(f"   ⚠️  {label} Failed to read checks: {raw}", file=sys.stderr)
                time.sleep(poll)
                continue
        else:
            try:
                checks = json.loads(raw)
            except json.JSONDecodeError:
                checks = []

        total = len(checks)
        pending = sum(1 for c in checks if c.get("bucket") in ("pending", None, ""))
        failed = sum(1 for c in checks if c.get("bucket") == "fail")
        passed = total - pending - failed

        # Review
        code2, raw2, _ = gh(
            "pr", "view", pr, "--repo", f"{owner}/{repo}",
            "--json", "reviewDecision,reviewRequests,state"
        )
        pr_state = "OPEN"
        review_decision = "null"
        review_requests = 0
        if code2 == 0:
            try:
                info = json.loads(raw2)
                pr_state = info.get("state", "OPEN")
                review_decision = info.get("reviewDecision") or "null"
                review_requests = len(info.get("reviewRequests") or [])
            except json.JSONDecodeError:
                pass

        if pr_state in ("MERGED", "CLOSED"):
            print(f"   ℹ️  {label} PR is {pr_state}", file=sys.stderr)
            return pr_state == "MERGED"

        state_key = (total, pending, failed, review_decision, review_requests, no_checks)
        if state_key != prev_state.get("key"):
            prev_state["key"] = state_key
            if no_checks:
                if not no_checks_warned:
                    print(f"   {label} 📊 No checks configured", file=sys.stderr)
                    no_checks_warned = True
            else:
                review_label = review_decision if review_decision != "null" else (
                    f"{review_requests} requested" if review_requests else "None"
                )
                print(
                    f"   {label} 🔍 Checks: 🟢 {passed}  🟡 {pending}  🔴 {failed}  "
                    f"| Review: {review_label}",
                    file=sys.stderr,
                )

        # Waiting for checks to appear
        if total == 0 and not no_checks:
            waiting_elapsed = max_wait - (deadline - time.time())
            if waiting_elapsed > 180:
                print(f"   ⚠️  {label} No checks after 3 min, proceeding", file=sys.stderr)
                return True
            time.sleep(poll)
            continue

        if failed > 0:
            print(f"   ❌ {label} {failed} check(s) failed", file=sys.stderr)
            return False

        if pending > 0:
            msg = f"⏳ Waiting for {pending} check(s)"
            if review_decision == "REVIEW_REQUIRED" or review_requests > 0:
                msg += " + review"
            print(f"   {label} {msg}", file=sys.stderr)
            time.sleep(poll)
            continue

        # All checks done; evaluate review
        if review_decision == "CHANGES_REQUESTED":
            print(f"   {label} 🔴 Changes requested", file=sys.stderr)
            return False

        if review_decision == "APPROVED":
            print(f"   ✅ {label} All checks passed and PR approved", file=sys.stderr)
            return True

        # No review required (review_decision is null/empty and no requests) OR
        # sourcery / bot already reviewed — proceed
        if review_decision in ("null", "", None) and review_requests == 0:
            print(f"   ✅ {label} All checks passed (no review required)", file=sys.stderr)
            return True

        # Review pending — keep waiting
        time.sleep(poll)

    print(f"   ⚠️  {label} Timed out waiting for PR checks", file=sys.stderr)
    return False


def pull_main(main_branch: str, cwd: str | None = None) -> None:
    git("checkout", main_branch, cwd=cwd)
    git("pull", "--rebase", "origin", main_branch, cwd=cwd)


def delete_local_branch(branch: str, cwd: str | None = None) -> None:
    git("branch", "-D", branch, cwd=cwd)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class Config:
    prompt: str
    max_runs: int = 0          # 0 = unlimited
    max_cost: float = 0.0      # 0.0 = no limit
    max_duration: int = 0      # seconds, 0 = no limit

    owner: str = ""
    repo: str = ""

    ai_cmd: str = "claude"
    ai_flags: list[str] = field(default_factory=lambda: [
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--verbose",
    ])
    ai_output_format: str = "stream-json"   # "stream-json" | "text"
    extra_ai_flags: list[str] = field(default_factory=list)

    branch_prefix: str = "rube/"
    merge_strategy: str = "squash"
    notes_file: str = "SHARED_TASK_NOTES.md"

    enable_commits: bool = True
    disable_branches: bool = False
    dry_run: bool = False

    completion_signal: str = "RUBE_PROJECT_COMPLETE"
    completion_threshold: int = 3

    review_prompt: str = ""

    reviewers: list[str] = field(default_factory=lambda: ["sourcery-ai"])

    ci_retry: bool = True
    ci_retry_max: int = 1
    comment_review: bool = True
    comment_review_max: int = 1

    worktree: str = ""
    worktree_base: str = "../rube-worktrees"
    cleanup_worktree: bool = False


# ---------------------------------------------------------------------------
# Main loop state
# ---------------------------------------------------------------------------


@dataclass
class LoopState:
    successful: int = 0
    errors: int = 0
    extra_iterations: int = 0
    total_cost: float = 0.0
    completion_signal_count: int = 0
    start_time: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Iteration logic
# ---------------------------------------------------------------------------


def build_prompt(cfg: Config, iteration: int) -> str:
    ctx = PROMPT_WORKFLOW_CONTEXT.format(
        completion_signal=cfg.completion_signal,
        prompt=cfg.prompt,
    )

    notes_path = cfg.notes_file
    if os.path.exists(notes_path):
        with open(notes_path) as f:
            notes = f.read()
        ctx += f"\n## CONTEXT FROM PREVIOUS ITERATION\n\n{notes}\n"
        ctx += "\n" + PROMPT_NOTES_UPDATE.format(notes_file=notes_path)
    else:
        ctx += "\n" + PROMPT_NOTES_CREATE.format(notes_file=notes_path)

    return ctx


def run_reviewer(cfg: Config, label: str, log_path: str) -> bool:
    if not cfg.review_prompt:
        return True
    prompt = PROMPT_REVIEWER.format(review_prompt=cfg.review_prompt)
    ok, _, cost = run_ai(prompt, cfg, label, log_path)
    if cost:
        print(f"   {label} 💰 Reviewer cost: {fmt_cost(cost)}", file=sys.stderr)
    return ok


def run_ci_fix(
    cfg: Config, label: str, pr_number: str, branch: str, run_id: str, log_path: str
) -> bool:
    hint = f"\n- Failed Run ID: {run_id} (use: gh run view {run_id} --log-failed)" if run_id else ""
    prompt = PROMPT_CI_FIX.format(
        pr_number=pr_number,
        owner=cfg.owner,
        repo=cfg.repo,
        run_id_hint=hint,
    )
    ok, _, cost = run_ai(prompt, cfg, label, log_path)
    if cost:
        print(f"   {label} 💰 CI-fix cost: {fmt_cost(cost)}", file=sys.stderr)
    return ok


def run_comment_fix(cfg: Config, label: str, pr_number: str, log_path: str) -> bool:
    prompt = PROMPT_COMMENT_REVIEW.format(
        pr_number=pr_number,
        owner=cfg.owner,
        repo=cfg.repo,
    )
    ok, _, cost = run_ai(prompt, cfg, label, log_path)
    if cost:
        print(f"   {label} 💰 Comment-fix cost: {fmt_cost(cost)}", file=sys.stderr)
    return ok


def get_failed_run_id(owner: str, repo: str) -> str:
    code, out, _ = gh("run", "list", "--repo", f"{owner}/{repo}",
                      "--status", "failure", "--limit", "1", "--json", "databaseId")
    if code == 0:
        try:
            items = json.loads(out)
            if items:
                return str(items[0].get("databaseId", ""))
        except (json.JSONDecodeError, KeyError):
            pass
    return ""


def pr_has_review_comments(owner: str, repo: str, pr: str) -> bool:
    code, out, _ = gh("api", f"repos/{owner}/{repo}/pulls/{pr}/comments")
    if code != 0:
        return False
    try:
        comments = json.loads(out)
        return len(comments) > 0
    except (json.JSONDecodeError, TypeError):
        return False


def do_full_pr_flow(
    cfg: Config,
    label: str,
    branch: str,
    main_branch: str,
    log_path: str,
) -> bool:
    """Commit → push → PR → wait → (CI fix) → (comment fix) → merge. Returns True on success."""
    cwd = None  # always run in cwd

    if not commit_changes(PROMPT_COMMIT, cfg, label, log_path, cwd=cwd):
        return False

    _, commit_log, _ = git("log", "-1", "--format=%B", branch)
    lines = commit_log.strip().splitlines()
    pr_title = lines[0] if lines else "Rube: iteration update"
    pr_body = "\n".join(lines[3:]) if len(lines) > 3 else ""

    if not push_branch(branch, cwd=cwd):
        git("checkout", main_branch, cwd=cwd)
        return False

    print(f"   {label} 🔨 Creating PR...", file=sys.stderr)
    if cfg.dry_run:
        print(f"   {label} 🔍 (DRY RUN) Would create PR", file=sys.stderr)
        git("checkout", main_branch, cwd=cwd)
        return True

    pr_number = create_pr(
        cfg.owner, cfg.repo, main_branch, pr_title, pr_body,
        cfg.reviewers, cwd=cwd,
    )
    if not pr_number:
        git("checkout", main_branch, cwd=cwd)
        return False

    print(f"   {label} 🔍 PR #{pr_number} created — waiting 5s for GitHub...", file=sys.stderr)
    time.sleep(5)

    checks_ok = wait_for_pr_checks(cfg.owner, cfg.repo, pr_number, label)

    # CI retry loop
    if not checks_ok and cfg.ci_retry:
        for attempt in range(1, cfg.ci_retry_max + 1):
            print(f"   {label} 🔧 CI failed — fix attempt {attempt}/{cfg.ci_retry_max}...", file=sys.stderr)
            run_id = get_failed_run_id(cfg.owner, cfg.repo)
            if run_ci_fix(cfg, label, pr_number, branch, run_id, log_path):
                time.sleep(5)
                print(f"   {label} 🔍 Rechecking CI after fix...", file=sys.stderr)
                checks_ok = wait_for_pr_checks(cfg.owner, cfg.repo, pr_number, label)
                if checks_ok:
                    break
            else:
                break

    if not checks_ok:
        print(f"   {label} ⚠️  Closing PR #{pr_number} — checks failed", file=sys.stderr)
        close_pr(cfg.owner, cfg.repo, pr_number, cwd=cwd)
        git("checkout", main_branch, cwd=cwd)
        delete_local_branch(branch, cwd=cwd)
        return False

    # Comment review loop
    if cfg.comment_review and pr_has_review_comments(cfg.owner, cfg.repo, pr_number):
        for attempt in range(1, cfg.comment_review_max + 1):
            print(
                f"   {label} 💬 Addressing review comments (attempt {attempt}/{cfg.comment_review_max})...",
                file=sys.stderr,
            )
            if run_comment_fix(cfg, label, pr_number, log_path):
                time.sleep(5)
                checks_ok = wait_for_pr_checks(cfg.owner, cfg.repo, pr_number, label)
                if checks_ok:
                    break
            if not checks_ok:
                print(f"   {label} ⚠️  CI broke after comment fix", file=sys.stderr)
                break

    if not checks_ok:
        print(f"   {label} ⚠️  Closing PR #{pr_number} after comment fix failures", file=sys.stderr)
        close_pr(cfg.owner, cfg.repo, pr_number, cwd=cwd)
        git("checkout", main_branch, cwd=cwd)
        delete_local_branch(branch, cwd=cwd)
        return False

    print(f"   {label} 🔀 Merging PR #{pr_number}...", file=sys.stderr)
    if not merge_pr(cfg.owner, cfg.repo, pr_number, cfg.merge_strategy, cwd=cwd):
        code, state_out, _ = gh(
            "pr", "view", pr_number, "--repo", f"{cfg.owner}/{cfg.repo}",
            "--json", "state"
        )
        state = ""
        try:
            state = json.loads(state_out).get("state", "")
        except (json.JSONDecodeError, AttributeError):
            pass
        if state != "MERGED":
            close_pr(cfg.owner, cfg.repo, pr_number, cwd=cwd)
            git("checkout", main_branch, cwd=cwd)
            delete_local_branch(branch, cwd=cwd)
            return False

    print(f"   ✅ {label} PR #{pr_number} merged: {pr_title}", file=sys.stderr)
    pull_main(main_branch, cwd=cwd)
    delete_local_branch(branch, cwd=cwd)
    return True


def execute_iteration(cfg: Config, state: LoopState, iteration: int) -> bool:
    """Run one full iteration. Returns True on success."""
    if cfg.max_runs > 0:
        label = f"({iteration}/{cfg.max_runs})"
    else:
        label = f"({iteration}/∞)"

    print(f"\n🔄 {label} Starting iteration...", file=sys.stderr)

    main_br = current_branch()
    branch = ""

    if cfg.enable_commits and not cfg.disable_branches:
        branch = create_branch(cfg.branch_prefix, iteration) or ""
        if not branch:
            state.errors += 1
            state.extra_iterations += 1
            return False

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as tmp:
        log_path = tmp.name

    try:
        if cfg.dry_run:
            print(f"   {label} 🔍 (DRY RUN) Would run AI with prompt", file=sys.stderr)
            result_text = "DRY_RUN"
            cost = 0.0
            ok = True
        else:
            prompt = build_prompt(cfg, iteration)
            ok, raw, cost = run_ai(prompt, cfg, label, log_path)
            result_text = extract_result_text(raw, cfg.ai_output_format)

        if cost:
            print(f"\n   {label} 💰 Cost: {fmt_cost(cost)}", file=sys.stderr)
            state.total_cost += cost
            print(f"   Running total: {fmt_cost(state.total_cost)}", file=sys.stderr)

        if not ok:
            state.errors += 1
            state.extra_iterations += 1
            if branch:
                git("checkout", main_br)
                delete_local_branch(branch)
            if state.errors >= 3:
                print("❌ Fatal: 3 consecutive errors. Exiting.", file=sys.stderr)
                sys.exit(1)
            return False

        # Completion signal check
        if cfg.completion_signal in result_text:
            state.completion_signal_count += 1
            print(
                f"\n   🎯 {label} Completion signal detected "
                f"({state.completion_signal_count}/{cfg.completion_threshold})",
                file=sys.stderr,
            )
        else:
            if state.completion_signal_count > 0:
                print(f"\n   🔄 {label} Resetting completion signal counter", file=sys.stderr)
            state.completion_signal_count = 0

        # Reviewer pass
        if cfg.review_prompt:
            if not run_reviewer(cfg, label, log_path):
                print(f"   ❌ {label} Reviewer failed", file=sys.stderr)
                state.errors += 1
                state.extra_iterations += 1
                if branch:
                    git("checkout", main_br)
                    delete_local_branch(branch)
                if state.errors >= 3:
                    sys.exit(1)
                return False

        print(f"   ✅ {label} Work completed", file=sys.stderr)

        if cfg.enable_commits:
            if cfg.disable_branches:
                # Commit on current branch, no PR
                if not commit_changes(PROMPT_COMMIT, cfg, label, log_path):
                    state.errors += 1
                    state.extra_iterations += 1
                    if state.errors >= 3:
                        sys.exit(1)
                    return False
            else:
                if not do_full_pr_flow(cfg, label, branch, main_br, log_path):
                    state.errors += 1
                    state.extra_iterations += 1
                    if state.errors >= 3:
                        sys.exit(1)
                    return False
        else:
            print(f"   ⏭️  {label} Skipping commits (--disable-commits)", file=sys.stderr)
            if branch:
                git("checkout", main_br)
                delete_local_branch(branch)

        state.errors = 0
        if state.extra_iterations > 0:
            state.extra_iterations -= 1
        state.successful += 1
        return True

    finally:
        if os.path.exists(log_path):
            os.unlink(log_path)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def should_continue(cfg: Config, state: LoopState) -> bool:
    if cfg.max_runs > 0 and state.successful >= cfg.max_runs:
        return False
    if cfg.max_cost > 0 and state.total_cost >= cfg.max_cost:
        print(f"\n💸 Cost limit reached ({fmt_cost(state.total_cost)} ≥ {fmt_cost(cfg.max_cost)})", file=sys.stderr)
        return False
    if cfg.max_duration > 0:
        elapsed = int(time.time() - state.start_time)
        if elapsed >= cfg.max_duration:
            print(f"\n⏱️  Duration limit reached ({format_duration(elapsed)})", file=sys.stderr)
            return False
    if state.completion_signal_count >= cfg.completion_threshold:
        print(
            f"\n🎉 Project completion signal detected {state.completion_signal_count}x in a row!",
            file=sys.stderr,
        )
        return False
    return True


def main_loop(cfg: Config) -> None:
    state = LoopState()
    iteration = 1
    while should_continue(cfg, state):
        execute_iteration(cfg, state, iteration)
        time.sleep(1)
        iteration += 1

    elapsed = int(time.time() - state.start_time)
    if state.total_cost > 0:
        print(
            f"\n🎉 Done — {state.successful} iteration(s) | "
            f"total cost: {fmt_cost(state.total_cost)} | "
            f"elapsed: {format_duration(elapsed)}",
            file=sys.stderr,
        )
    else:
        print(
            f"\n🎉 Done — {state.successful} iteration(s) | elapsed: {format_duration(elapsed)}",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rube",
        description="rube — Python-native continuous AI dev loop. rube.works",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  rube -p "add unit tests" -m 5
  rube -p "fix all linting errors" --max-cost 10.00
  rube -p "improve docs" --max-duration 2h
  rube -p "refactor module" -m 3 --ai-cmd aider --ai-flags "--yes --no-auto-commits"
  rube -p "fix bugs" -m 5 --reviewer "Run pytest, fix failures"
  rube -p "add features" -m 10 --no-sourcery-review
  rube -p "quick fix" -m 1 --disable-commits
        """,
    )
    p.add_argument("-V", "--version", action="version", version=f"rube {VERSION}")

    req = p.add_argument_group("required")
    req.add_argument("-p", "--prompt", required=True, help="Task prompt for the AI")
    limits = p.add_argument_group("limits (at least one required)")
    limits.add_argument("-m", "--max-runs", type=int, default=0,
                        help="Max successful iterations (0 = unlimited, pair with --max-cost or --max-duration)")
    limits.add_argument("--max-cost", type=float, default=0.0, help="Max USD to spend")
    limits.add_argument("--max-duration", default="", help="Max wall-clock time, e.g. 2h, 30m, 1h30m")

    ai = p.add_argument_group("AI command")
    ai.add_argument("--ai-cmd", default="claude",
                    help="AI coding CLI to invoke (default: claude; also works with aider, codex, etc.)")
    ai.add_argument("--ai-flags", default="",
                    help="Space-separated flags to pass to the AI CLI (overrides defaults)")
    ai.add_argument("--ai-output-format", choices=["stream-json", "text"], default="stream-json",
                    help="How to parse AI stdout (default: stream-json; use 'text' for non-Claude CLIs)")

    gh_grp = p.add_argument_group("GitHub")
    gh_grp.add_argument("--owner", default="", help="Repo owner (auto-detected from git remote)")
    gh_grp.add_argument("--repo", default="", help="Repo name (auto-detected from git remote)")
    gh_grp.add_argument("--merge-strategy", choices=["squash", "merge", "rebase"], default="squash")
    gh_grp.add_argument("--reviewers", default="sourcery-ai",
                        help="Comma-separated PR reviewer(s) (default: sourcery-ai)")
    gh_grp.add_argument("--no-sourcery-review", action="store_true",
                        help="Remove sourcery-ai from reviewers (use --reviewers to set custom list)")

    wf = p.add_argument_group("workflow")
    wf.add_argument("--branch-prefix", default="rube/", help="Git branch prefix (default: rube/)")
    wf.add_argument("--notes-file", default="SHARED_TASK_NOTES.md")
    wf.add_argument("--disable-commits", action="store_true", help="Skip commits/PRs (test mode)")
    wf.add_argument("--disable-branches", action="store_true",
                    help="Commit on current branch, skip PRs")
    wf.add_argument("--dry-run", action="store_true", help="Simulate without changes")
    wf.add_argument("--completion-signal", default="RUBE_PROJECT_COMPLETE")
    wf.add_argument("--completion-threshold", type=int, default=3)
    wf.add_argument("-r", "--reviewer", default="",
                    help="Run a reviewer pass after each AI iteration (e.g. 'run pytest, fix failures')")
    wf.add_argument("--disable-ci-retry", action="store_true")
    wf.add_argument("--ci-retry-max", type=int, default=1)
    wf.add_argument("--disable-comment-review", action="store_true")
    wf.add_argument("--comment-review-max", type=int, default=1)

    return p


def build_config(args: argparse.Namespace) -> Config:
    # Validate limits
    if args.max_runs == 0 and not args.max_cost and not args.max_duration:
        print("❌ At least one of --max-runs, --max-cost, or --max-duration is required.", file=sys.stderr)
        sys.exit(1)

    # Parse duration
    max_dur = 0
    if args.max_duration:
        try:
            max_dur = parse_duration(args.max_duration)
        except ValueError as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(1)

    # Detect GitHub remote
    owner = args.owner
    repo = args.repo
    if not owner or not repo:
        detected = detect_github_remote()
        if detected:
            o, r = detected
            owner = owner or o
            repo = repo or r

    # AI flags
    if args.ai_flags:
        ai_flags = args.ai_flags.split()
    else:
        if args.ai_cmd in ("claude",):
            ai_flags = ["--dangerously-skip-permissions", "--output-format", "stream-json", "--verbose"]
        else:
            ai_flags = []

    # Reviewers
    reviewers = [r.strip() for r in args.reviewers.split(",") if r.strip()]
    if args.no_sourcery_review:
        reviewers = [r for r in reviewers if r != "sourcery-ai"]

    return Config(
        prompt=args.prompt,
        max_runs=args.max_runs,
        max_cost=args.max_cost,
        max_duration=max_dur,
        owner=owner,
        repo=repo,
        ai_cmd=args.ai_cmd,
        ai_flags=ai_flags,
        ai_output_format=args.ai_output_format,
        branch_prefix=args.branch_prefix,
        merge_strategy=args.merge_strategy,
        notes_file=args.notes_file,
        enable_commits=not args.disable_commits,
        disable_branches=args.disable_branches,
        dry_run=args.dry_run,
        completion_signal=args.completion_signal,
        completion_threshold=args.completion_threshold,
        review_prompt=args.reviewer,
        reviewers=reviewers,
        ci_retry=not args.disable_ci_retry,
        ci_retry_max=args.ci_retry_max,
        comment_review=not args.disable_comment_review,
        comment_review_max=args.comment_review_max,
    )


def validate_requirements(cfg: Config) -> None:
    errors = []
    for tool in ["git", "gh"]:
        code, _, _ = run_capture([tool, "--version"])
        if code != 0:
            errors.append(f"{tool} CLI not found")
    if cfg.enable_commits and not cfg.disable_branches:
        if not cfg.owner or not cfg.repo:
            errors.append(
                "GitHub owner/repo not found. Use --owner / --repo or run inside a GitHub repo."
            )
    if errors:
        for e in errors:
            print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = build_config(args)
    validate_requirements(cfg)

    print(f"🪄  rube {VERSION} — rube.works", file=sys.stderr)
    print(f"   AI: {cfg.ai_cmd}  |  Repo: {cfg.owner}/{cfg.repo}", file=sys.stderr)
    if cfg.reviewers:
        print(f"   PR reviewers: {', '.join(cfg.reviewers)}", file=sys.stderr)
    print(f"   Completion signal: {cfg.completion_signal!r}", file=sys.stderr)
    print(file=sys.stderr)

    main_loop(cfg)


if __name__ == "__main__":
    main()
