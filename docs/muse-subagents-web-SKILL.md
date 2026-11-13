---
name: muse-subagents-web
description: Fan out several independent tasks to Muse (muse.ai, Meta's personal AI agent, used in the browser) as parallel subagents, then check in with Muse and verify what each one did before trusting it. Use when the user says "use Muse", "have Muse do these in parallel", "fire these tasks off with Muse", or "check what Muse did". Invoke as /muse-subagents-web <tasks>.
argument-hint: "<task list> | status | verify"
---

# /muse-subagents-web — run parallel tasks through Muse (browser), then verify

Tasks from the user: `$ARGUMENTS`

Adapted from a procedure that worked with the Muse desktop app on one Mac (four jobs, one chat, all four finished). **The browser version at muse.ai has not been tried with this skill.** Steps marked (unverified) are what should work, not what was seen. If the page looks different from what is described, trust the page, say so, and carry on.

## What is different from the desktop version
- Muse runs on **its own cloud computer** (a persistent Linux VM with its own browser), not on the user's machine. It cannot see local folders or `git worktree`s here unless the user has connected the two (for example over SSH). Assume it cannot, and move work through **git** instead: the code goes to a GitHub repo Muse can reach, each task gets its own **branch**, and Muse pushes to that branch. Ask the user which repo to use and whether Muse already has access to it (a deploy key, a token the user gave it, or a public repo for read-only work).
- You drive muse.ai through a browser tool (Claude in Chrome, or the built-in browser). The user signs in themselves. Never type their password or one-time codes; ask them to sign in, then continue.
- Muse asks the user before important actions (sending email, purchases). Fan-out tasks should not need any of that; if Muse asks for approval, pass the question to the user.

## Rules
- Only fan out tasks that are independent: none needs another's result, and each touches its own branch only. Anything that drives one shared thing (a single device, a live service, a database, one audio app) is not a fan-out task; do it yourself in order.
- Every task gets its own branch (`task/<name>`), created from the same starting commit. Muse may commit and push to its own task branch only. It must not touch `main` or any other branch, and must not open pull requests unless told to.
- A Muse report is a claim, not proof. Check it (step 5) before you tell the user the work is done.
- Do not put secrets (tokens, passwords, keys) in a prompt. If Muse needs repo access, the user sets that up.

## 1. Prepare the branches
```bash
cd <repo>
git push origin HEAD:refs/heads/base-<date>          # a fixed starting point everyone branches from
for n in <name1> <name2>; do git push origin base-<date>:refs/heads/task/$n; done
```
(Or let Muse create the branches itself from `base-<date>`; say which in the prompt.)

## 2. One brief per task
Keep the detail in a file in the repo on the base branch (`docs/tasks/<name>.md`) so the chat message stays short, or paste the brief into the message if the repo is not shared. Start every brief with the same block, then the task:

```
You are one of N parallel subagents for the lead agent. Repo: <url>. Work only on branch task/<name>
(clone it into its own folder). Do not touch main or other branches. Commit to your branch and push it;
do not open a pull request.
Your final report must be a file report-<name>.md committed on your branch, and must separate
what you ran and saw from what you expect, include failures verbatim (trimmed), and be concise.

YOUR TASK (<name>): <exactly what to do, the command to run, what "done" looks like, what to hand back>.
```

A read-only reviewer gets "READ-ONLY: make no commits except report-<name>.md" and a cap on findings (for example 15, most serious first, each with file:line and whether it was confirmed by running something or only by reading).

## 3. Open Muse and send one message (unverified in the browser)
1. Open https://muse.ai in the browser tool. If it shows the sign-in page, ask the user to sign in; continue when they say it is done.
2. Start a **new chat** for this batch (look for a new chat or side chat button; a side chat keeps it apart from the user's main conversation). Do not reuse an unrelated chat.
3. Click the message box and type the whole request as **one paragraph** (a newline probably sends the message), then press Return:

   > Please run N subagents in parallel, one per task brief, each working only on its own git branch of <repo>. <name>: brief <path or text>, branch task/<name>. … Each subagent should follow its brief exactly (no pushing anywhere except its own branch). When all finish, commit report-<name>.md on each branch and tell me here what each one did, separating what it ran and saw from what it expects.

4. Take a screenshot after a few seconds. Success looks like Muse restating the tasks and saying it is running them; it may check paths or access first. If it says it cannot reach the repo, stop and tell the user what access to set up; do not work around it.

## 4. Keep working; watch for results
Do your own non-conflicting work. Poll for finished work with git, not with the chat:
```bash
git fetch origin 'refs/heads/task/*:refs/remotes/origin/task/*'
for n in <names>; do git ls-tree -r --name-only origin/task/$n | grep -q "^report-$n.md$" && echo "report ready: $n"; done
```
A branch with no new commits after several minutes is not necessarily stuck (a read-only review writes only its report). Look at the Muse chat with a screenshot before concluding.

## 5. Check in with Muse and verify
1. Read Muse's summary in the chat. If something is unclear, ask in the **same** chat; do not start a second chat for the same tasks.
2. Read each `report-<name>.md` from its branch (`git show origin/task/<name>:report-<name>.md`).
3. Verify against the branch, not the report: `git diff base-<date>..origin/task/<name>`, then run the tests or the command the task named. In your own summary to the user, separate what you re-ran and saw from what Muse said. Spot-check what feeds a claim of "verified"; you do not need to redo the whole task.
4. Merge into the lead branch yourself, in arrival order, running the tests after each. Ask the user before anything goes to `main`.
5. Clean up when done: delete the `task/*` and `base-*` branches from the remote, only after the user agrees.

## Pitfalls
- Muse and your tools may not see the same files. If a path "does not exist" for Muse, it is probably on the user's machine; use git instead.
- Typing a newline into the message box can send a half-written message; keep the brief to one paragraph and refer to the brief files.
- Do not describe a task as done because Muse said so. The report is where the checking starts.
