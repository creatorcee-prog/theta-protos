"""Theta writes like a person: the signs from Wikipedia's "Signs of AI writing" are in the style rules, and the
unmistakable ones are removed from every reply by persona.clean (and, character by character, while it streams)."""
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from server import persona as p


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  got: {got!r}"))
    if not cond:
        sys.exit(1)


c = p.clean
check("openers go", c("Certainly! The fix is simple.") == "The fix is simple.", c("Certainly! The fix is simple."))
check("'You're absolutely right' goes", c("You're absolutely right! It's Tuesday.") == "It's Tuesday.")
check("em dashes become commas", c("The café — downtown — opens at 7.") == "The café, downtown, opens at 7.")
check("unspaced em dash too", c("Two options—both fine.") == "Two options, both fine.")
check("number ranges keep their en dash", "3–5" in c("Range 3–5 is fine."))
check("curly quotes become straight", c("It’s “fine”.") == 'It\'s "fine".')
check("'it's important to note that' goes and the sentence starts capitalized",
      c("It's important to note that banks lag.") == "Banks lag.", c("It's important to note that banks lag."))
check("mid-sentence 'it is worth noting that' goes", c("Rates rose, and it is worth noting that banks lag.") == "Rates rose, and banks lag.")
check("wrap-up openers go", c("Fine.\n\nIn conclusion, it works.") == "Fine.\n\nIt works.")
check("'delve into' becomes 'dig into'", c("Let's delve into it.") == "Let's dig into it.")
check("sign-offs go", c("Done. Is there anything else I can do?") == "Done." and c("Done. I hope this helps!") == "Done.")
check("'e.g.' isn't treated as a sentence end", c("Use a range, e.g. pages 10 to 12.") == "Use a range, e.g. pages 10 to 12.")
check("tracking tags leave links", "utm_source" not in c("See https://x.com/a?utm_source=chatgpt.com for more."))
check("Theta's own offers stay ('Want me to...')", c("Pay it off. Want me to remind you on the 1st?") == "Pay it off. Want me to remind you on the 1st?")

cl = p.Cleaner()
streamed = cl.feed("Here's the plan for tomorrow morning, start to finish, step by step. ") + cl.feed("First — coffee. ") + cl.feed("Then “work”.") + cl.finish()
check("while streaming, em dashes and curly quotes are fixed as they arrive", "—" not in streamed and "“" not in streamed, streamed)

sp = p.system_prompt()
check("the style rules name the signs", all(w in sp for w in ("delve", "serves as", "not only X but also Y", "em dashes", "I hope this helps")))
