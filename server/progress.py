"""Progress for multi-step jobs: the phases of a job, each done, in progress or still to come, shown as a live card
in the chat ("Research completed / Comparing findings / Verification pending") and kept on the reply.

    progress_update {steps: ["Look up prices", "Compare stores", "Check delivery"], done: 1}

Theta calls it when a job has 3+ distinct phases: once at the start (done 0), then each time a phase finishes.
steps[:done] show as done, steps[done] as in progress, the rest as to come. The loop (agent.run) passes
ctx["progress"], which streams a "progress" event {steps: [{text, state}]} and keeps the latest for the reply's
meta.progress. When the turn ends, a phase still marked in progress or to come is shown as not done: the card never
claims more than Theta said it finished.
"""
import re

MAX_STEPS = 8


def states(steps, done, final=False):
    """[{text, state}] with state done | active | pending | skipped (final: the turn ended before it)."""
    done = max(0, min(len(steps), int(done or 0)))
    out = []
    for i, s in enumerate(steps):
        st = "done" if i < done else ("skipped" if final else "active" if i == done else "pending")
        out.append({"text": s, "state": st})
    return out


def clean(args):
    steps = [re.sub(r"\s+", " ", str(s or "")).strip()[:60] for s in (args.get("steps") or [])]
    steps = [s for s in steps if s][:MAX_STEPS]
    if not 2 <= len(steps):
        raise ValueError("give 2 to 8 short phases, e.g. {\"steps\": [\"Look up prices\", \"Compare stores\", "
                         "\"Check delivery\"], \"done\": 0}")
    try:
        done = int(args.get("done") or 0)
    except (TypeError, ValueError):
        done = 0
    return steps, max(0, min(len(steps), done))


def _t_progress(args, ctx):
    from .tools import ToolError
    try:
        steps, done = clean(args)
    except ValueError as e:
        raise ToolError(str(e)) from None
    show = (ctx or {}).get("progress")
    if show:
        show(steps, done)
    if done >= len(steps):
        return "All phases marked done on the card."
    return f"Card updated: {done} of {len(steps)} done; now: {steps[done]}. Call again with done={done + 1} when it's finished."


TOOLS = [
    {"name": "progress_update", "risk": "read", "run": _t_progress,
     "description": ("Show the user a live progress card for a job with 3 or more distinct phases (e.g. research, "
                     "compare, verify). Call it first with the phases and done 0, then again each time a phase "
                     "finishes (done = how many are finished), and done = all at the end. Phases are short, in "
                     "plain words, in the order you'll do them. Skip it for quick one-step answers. Example: "
                     "{\"steps\": [\"Find the lamp at 4 stores\", \"Compare prices\", \"Check delivery\"], \"done\": 0}."),
     "params": {"type": "object", "properties": {
         "steps": {"type": "array", "items": {"type": "string"}, "description": "2-8 short phases, in order."},
         "done": {"type": "integer", "description": "How many phases are finished."}},
         "required": ["steps", "done"]}},
]


def context(bot, now):
    return ""
