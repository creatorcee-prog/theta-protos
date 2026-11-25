# Research: the "Grok Bot" reference app, and what Theta should learn from it

Date: 2026-11-25. Every factual claim has a source URL. Anything marked **(uncertain)** is an inference or comes from a weak or conflicting source. The reference screenshots are `docs/ref-*.png`.

## 0. What the screenshots show (direct observation, no source needed)

- **Splash (`ref-splash.png`):** a near-black screen with only the bot's avatar centered: a white circle with two slanted eye strokes. There is no text and no spinner.
- **Home (`ref-home.png`):** the user's initials sit top-left and a `+` (new Bot) top-right. One large avatar is labeled "Chester" and has an orange star badge. At the bottom are an upsell card ("Keep your Bots working with more usage" with an Upgrade button), a grid+ button and a Search pill.
- **Chat (`ref-chat.png`):**
  - The header is a pill with the avatar and name.
  - Bot bubbles are dark grey and left-aligned. User bubbles are lighter grey and right-aligned.
  - The bot offers options ("Which one sounds good?"). The user picks two. The bot then sends **two separate messages**: a short acknowledgement ("On it. I'll pull together...") and a status message ("Both are underway... Nothing gets unsubscribed until you pick.").
  - The usage-exhausted card sits *above* the composer, not in the transcript.
  - The composer reads "Ask Chester" and has `+`, a mic and a voice-chat button.
- **Connect apps (`ref-connect.png`):**
  - It is a full-height sheet with a "6 connected" pill.
  - Filter chips: All / iPhone / Password managers / Productivity.
  - "For you" suggestions give a reason ("Because you use Google Calendar").
  - A "Featured plugins" section lists Gmail and Drive as Connected, with a one-line capability description each.
  - A floating "Search across apps and skills" bar sits at the bottom.

## 1. What the app is

**Identification: Grok Bot, the iPhone app.** This matches the screenshots on product name, "Bots" capitalized as a noun, the usage model, the Connect apps / iPhone / plugins structure, the starred primary Bot, and proactive offers. I am fairly confident.

- **Maker.** Grok Bot is xAI's product of persistent "AI teammate" agents. The beta launched on 2026-08-11 and 1.0 shipped on 2026-11-11 ([unite.ai](https://www.unite.ai/xai-launches-grok-bot-always-on-ai-teammates-with-their-own-cloud-computers/), [cellcog 1.0](https://cellcog.ai/blog/grok-bot-1-0/)).
  - The official launch post's footer names "SpaceX Super Intelligence LLC" / "SpaceXSI" ([x.ai/news/introducing-grok-bot](https://x.ai/news/introducing-grok-bot)).
  - The product is closely tied to Cursor: it uses Cursor accounts and Cursor plans, and the cursor.com help pages redirect to docs.x.ai ([docs.x.ai/grok-bot/mobile](https://docs.x.ai/grok-bot/mobile), [composio guide](https://composio.dev/content/guide-to-frok-bot)).
  - **(uncertain)** Third-party sources conflict on the corporate naming (xAI vs SpaceXAI vs SpaceXSI) ([unite.ai](https://www.unite.ai/xai-launches-grok-bot-always-on-ai-teammates-with-their-own-cloud-computers/)).
- **"Chester" is almost certainly the user's own Bot, not a product mascot.**
  - Users name each Bot and pick "a shape and color for its picture" ([docs.x.ai/grok-bot/bots](https://docs.x.ai/grok-bot/bots)).
  - xAI's design post says avatars share "simple shapes and expressive eyes" ([x.ai/news/designing-grok-bot](https://x.ai/news/designing-grok-bot)).
  - No source mentions a mascot named Chester.
  - The orange star most likely marks the **primary Bot**. The docs say "Only your primary Bot, marked with a star in the sidebar, takes initiative" ([docs.x.ai/grok-bot/initiative](https://docs.x.ai/grok-bot/initiative)). Mapping that onto the phone screen is **(uncertain)**.
- **It is not Grok's companion characters** (Ani and the others). Those are a separate Grok app feature; this product's object model is work Bots ([designing-grok-bot](https://x.ai/news/designing-grok-bot)).

### How its Bots work

- **Persistent identity.**
  - "The main objects in Grok Bot are Bots, not conversations." Each Bot has a name, avatar, title, memory and its own computer, and "when you come back tomorrow, you are coming back to the same Bot" ([designing-grok-bot](https://x.ai/news/designing-grok-bot)).
  - Bots save preferences, facts and "a dated work log". Some facts about you are shared across all of your Bots ([docs bots](https://docs.x.ai/grok-bot/bots)).
- **Background work.**
  - Each Bot runs on a cloud computer and keeps working after you close the app ([docs mobile](https://docs.x.ai/grok-bot/mobile), [introducing](https://x.ai/news/introducing-grok-bot)).
  - All of an account's Bots share one cloud computer, but each gets its own screen ([composio](https://composio.dev/content/guide-to-frok-bot)).
- **Routines and skills.**
  - Routines run on a schedule or on an event, for example a morning briefing ([designing-grok-bot](https://x.ai/news/designing-grok-bot)).
  - A workflow you demonstrate becomes a reusable skill ([composio](https://composio.dev/content/guide-to-frok-bot)).
- **Connectors and plugins.**
  - Bots can use connectors, plugins and MCP servers, and connectors are preferred when one exists. They can also drive websites that have no API ([docs FAQ](https://docs.x.ai/grok-bot/faq), [composio](https://composio.dev/content/guide-to-frok-bot)).
  - Plugins live under Settings → Plugins → Marketplace ([composio](https://composio.dev/content/guide-to-frok-bot)).
  - On iPhone, Settings → Connect apps → iPhone grants Calendar, Contacts, Location, Reminders, Alarms and Home ([docs mobile](https://docs.x.ai/grok-bot/mobile)).
  - If access is missing, the Bot posts a "Grok Bot needs permission" card in the chat and waits up to 5 minutes for an answer. If the user allows it within an hour, the request can resume ([docs mobile](https://docs.x.ai/grok-bot/mobile)).
- **Approvals.**
  - Users can require approval for sending messages, publishing, deleting, purchasing and changing production systems ([composio](https://composio.dev/content/guide-to-frok-bot)).
  - Approvals raised by background work expire after about 30 minutes ([docs FAQ](https://docs.x.ai/grok-bot/faq)).
- **Proactive behavior.**
  - The primary Bot "spots tasks it can handle for you" and offers them. It does not act on its own: "offers first", then asks before risky actions ([docs initiative](https://docs.x.ai/grok-bot/initiative)).
  - Version 1.0 added proactive Bots that offer work and "follow up on unfinished tasks" ([cellcog 1.0](https://cellcog.ai/blog/grok-bot-1-0/)).
  - Check-ins are separate from notifications: turning notifications off does not stop check-ins ([docs initiative](https://docs.x.ai/grok-bot/initiative)).
  - **The source gives no cadence or quiet-hours rules.**
- **Push notifications.** The phone is notified when a Bot has a result, a question or an approval request, and notifications can be turned off per Bot or globally. Alerts route to the desktop app instead while it is in use ([docs mobile](https://docs.x.ai/grok-bot/mobile)).
- **Usage limits.**
  - There is a weekly usage pool, measured by "agent steps and tokens, not messages" ([docs FAQ](https://docs.x.ai/grok-bot/faq)).
  - A trial is a one-time credit that "one large task can use" entirely ([docs FAQ](https://docs.x.ai/grok-bot/faq)).
  - When the pool runs out, Bots stop and resume at the weekly reset. A spending cap does not stop a task mid-run ([docs FAQ](https://docs.x.ai/grok-bot/faq)).
  - At the limit, the phone shows a warning above the message box with "Use reset" ([docs mobile](https://docs.x.ai/grok-bot/mobile)). This matches the card's position in the screenshot.
  - Plans: Premium $30, Super $100 (3.5x usage), Ultra $200 (12x usage) per month ([x.ai/bot](https://x.ai/bot)).
- **Known weakness, worth learning from.**
  - Bots sometimes say "I'll do X later" and never do it, because a parked task resumes only when something wakes the Bot (a new message or a routine). Staff suggest having the Bot create a one-time routine whenever it promises later work ([Cursor forum 174751](https://forum.cursor.com/t/grok-bot-bot-ends-turn-without-finishing-work-it-committed-to-do-later/174751/7), [Cursor forum 177734](https://forum.cursor.com/t/grok-bot-now-following-through-with-tasks/177734)).
  - A user also asked for pending commitments to be shown in the app (same thread).

## 2. Model routing with one consistent voice

- **Grok Bot.**
  - There is "no model picker". The app picks a backend model **per task**, the choice can change from one request to the next, and the app **does not show which model answered**. All usage appears as plain Grok Bot usage ([docs FAQ](https://docs.x.ai/grok-bot/faq)).
  - The candidates include first-party and third-party models (same source). **No router signals are public.**
- **ChatGPT with GPT-5.**
  - A "real-time router" decides "based on conversation type, complexity, tool needs, and your explicit intent" (for example "think hard about this"). It is trained on users switching models, response preference rates and measured correctness ([openai.com/index/introducing-gpt-5](https://openai.com/index/introducing-gpt-5/)).
  - Once a user hits a limit, "a mini version of each model handles remaining queries" (same source).
- **Lessons from the GPT-5 launch.**
  - On launch day the autoswitcher broke and GPT-5 "seemed way dumber". Altman promised changes to the decision boundary and more transparency about which model answers ([Fortune](https://fortune.com/2025/08/12/openai-gpt-5-model-router-backlash-ai-future/), [TechCrunch](https://techcrunch.com/2025/08/12/chatgpts-model-picker-is-back-and-its-complicated/)).
  - OpenAI then added Auto / Fast / Thinking choices (TechCrunch, same).
  - Safety routing works per message, and switching away from the default is temporary. ChatGPT says which model is active **when asked** ([Simon Willison quoting Nick Turley](https://simonwillison.net/2025/Sep/28/nick-turley/), [TechCrunch](https://techcrunch.com/2025/09/29/openai-rolls-out-safety-routing-system-parental-controls-on-chatgpt/)).
- **Grok (the chat app).**
  - The default "Auto" mode picks between Fast and Expert ([mundobytes](https://mundobytes.com/en/What-are-the-heavy--expert--fast--and-auto-modes-in-Grok-used-for); secondary source).
  - In Auto, difficult queries use Grok 4 Fast. Reasoning and non-reasoning modes are "the same model weights, steered via system prompts", which reduces latency ([x.ai/news/grok-4-fast](https://x.ai/news/grok-4-fast)). Keeping the weights shared is one way to keep the voice consistent.
- **Poke (The Interaction Company, acquired by Cognition on 2026-07-23).**
  - Poke "picks the AI model that best fits each task" ([TechCrunch](https://techcrunch.com/2026/04/08/poke-makes-ai-agents-as-easy-as-sending-a-text/)).
  - It texts first, follows up and aims to feel "more like a friend than software" ([cognition.com/blog/interaction](https://cognition.com/blog/interaction)).
  - **(uncertain, secondhand)** Its architecture reportedly has one user-facing "interaction agent" that alone talks to the user and spawns "execution agents" that report back ([Substack on OpenPoke](https://tanishasrivatsa.substack.com/p/i-spent-30-minutes-arguing-with-a)). That design is how one voice survives many workers and models.
- **Shared pattern.**
  1. Route silently, per message.
  2. Have one persona layer speak.
  3. Reveal the model only on request.
  4. Offer a "think harder" escape hatch.
  5. Degrade to a smaller model instead of failing.

## 3. UX patterns that make it feel smooth

- **Acknowledge, then result, as two messages.** The screenshot shows a short "On it." message, then a status message, with the final result later. xAI's design post shows the same shape: "On it — pinging the team for status now", then the result later in the thread ([designing-grok-bot](https://x.ai/news/designing-grok-bot)). NN/g's limits explain why it works:
  - 0.1 s feels instant.
  - 1 s keeps the user's flow.
  - Past 10 s, the user needs progress information and a way to interrupt ([nngroup](https://www.nngroup.com/articles/response-times-3-important-limits/)).
- **Safety line in the ack.** "Nothing gets unsubscribed until you pick" states the approval boundary up front, which matches the "offers first, asks before risky actions" rule ([docs initiative](https://docs.x.ai/grok-bot/initiative)).
- **No three-dot typing indicator.** xAI rejected the "three animated dots" because users couldn't tell working from stuck. Instead, the **avatar's motion is the status**: calm at rest, acknowledging new work, active while working, different when waiting or blocked, settling when done ([designing-grok-bot](https://x.ai/news/designing-grok-bot)).
  - Step-by-step status text was tried and dropped. Users wanted reassurance, not a log (same source).
- **Cards for structured output.** Prose is used when it fits. Otherwise the Bot posts inline cards, such as an email draft with a "Ready to send" state and Send / Discard buttons ([designing-grok-bot](https://x.ai/news/designing-grok-bot)).
  - System actions (a routine created, a setting changed) appear in the transcript and can be expanded (same source).
  - Permission requests are cards ([docs mobile](https://docs.x.ai/grok-bot/mobile)).
- **Background task visibility comes in three levels.** A status icon, a pinned preview, and a full takeover. These exist to avoid "encouraging constant supervision" ([designing-grok-bot](https://x.ai/news/designing-grok-bot)).
  - Routines show what ran in the transcript (same source).
  - Live Activities on iOS are used for dictation and voice ([docs mobile](https://docs.x.ai/grok-bot/mobile)).
- **Streaming.** **(uncertain)** No Grok Bot source describes token streaming. The screenshots show whole bubbles, which suggests short messages delivered complete, in the style of texting.
  - For Theta, streaming still helps on long answers, but short acks should land whole.
- **Optimistic UI.** **(uncertain for Grok Bot; no source.)** As a general technique, show the user's bubble immediately and reconcile when the server confirms ([react.dev useOptimistic](https://react.dev/reference/react/useOptimistic)).
- **When it texts first.**
  - Only the primary Bot does. It offers spotted work, flags broken apps (for example "Gmail signed you out"), and follows up on unfinished work ([docs initiative](https://docs.x.ai/grok-bot/initiative), [cellcog 1.0](https://cellcog.ai/blog/grok-bot-1-0/)).
  - Poke texts reminders and alerts on schedules or events, for example a morning umbrella reminder ([TechCrunch](https://techcrunch.com/2026/04/08/poke-makes-ai-agents-as-easy-as-sending-a-text/)).
  - The screenshot's offer is concrete and personal: a sender's volume ("AliExpress (11 emails in 2 days)") and a tracked price ("down to $97"). It ends with a choice question.
- **Notification style.** Notifications fire only for a result, a question or an approval ([docs mobile](https://docs.x.ai/grok-bot/mobile)). Apple's HIG says:
  - Avoid "multiple notifications for the same thing".
  - Don't notify while the app is in the foreground; update the view instead.
  - Keep titles short, without the app name, and write the body as complete sentences.
  - Don't put sensitive information in notifications.
  - Source: [Apple HIG Notifications](https://developer.apple.com/design/human-interface-guidelines/notifications).
- **Onboarding and splash.**
  - Sign in with Apple, Google or email, or "Continue as" ([docs mobile](https://docs.x.ai/grok-bot/mobile)).
  - New users get a first-run tour and **pick a first Bot**, then wait while the computer is set up. Returning users go straight to the Bot list (same source).
  - The splash is just the avatar on a dark background (screenshot). The avatar *is* the brand moment, and there is no logo wordmark.
- **Upsell placement.** The upsell is a dismissable-looking card docked above the composer or the search bar, never a modal over the conversation (screenshot). Copy frames it as the user's benefit ("keep your Bots working").
- **Connect apps.** Suggestions come with a reason ("Because you use Google Calendar"). Each item has a one-line capability description, there are category chips, and a connected count shows (screenshot). Bots also ask for a missing app inline, with one tap ([composio](https://composio.dev/content/guide-to-frok-bot)).

## 4. Copy the pattern, not the brand

| Copy as pattern | Theirs. Do not copy |
|---|---|
| Ack message, then result message | The names "Grok", "Grok Bot", "Chester", "Bots" as a product noun |
| Avatar motion as working/blocked/done status | The white ball with two slanted eye strokes; the orange star badge |
| Inline cards for drafts, approvals, permissions | Their exact copy ("Keep your Bots working…", "Ask Chester") |
| Offer-first proactivity with an explicit "nothing happens until you pick" | The near-black UI with white pill buttons, as a look |
| Silent per-message routing, one persona | Their icons (rocket, gauge), splash composition |
| Upsell or limit card docked above composer | Plan names and tiers |
| "For you" connector suggestions with a reason | Their marketplace and plugin naming |

Theta keeps its dot-globe avatar, dot themes, name and SOUL.md voice (`docs/SPEC.md`). The avatar-as-status idea maps naturally onto the dot-globe: dots can drift, pulse or converge. **The animation must be our own.**

## 5. Design implications for Theta (prioritized)

1. **Two-message ack/result.**
   - For anything over about 2 s or using tools, send a short ack in Theta's voice within 1 s ("On it — checking prices now."), then the result as a *separate* message.
   - Plain chat (quick tier) gets no ack, only the answer.
   - The ack states the safety boundary when an action is involved ("I won't send anything until you say so").
2. **Every promise backed by a scheduled wakeup.**
   - If Theta says "I'll tell you when / later", it must create a job (`proactive`/reminder row) at that moment.
   - Show pending commitments as small cards. This avoids the Grok Bot failure in the Cursor forum threads.
3. **Silent per-message routing, one voice.**
   - Keep `event: route`, but the UI must **not** show it in the bubble. Store it in `meta.model` and reveal it only on long-press or in the message's "info" view, or when asked "which model?".
   - Every model gets the same SOUL prompt plus a style post-pass.
   - Honor explicit intent ("think hard") as a router signal.
   - On failure or limits, fall back to the quick tier rather than showing an error.
4. **Avatar-as-status instead of typing dots.** Map the dot-globe to five states:
   - idle (slow drift)
   - ack (one pulse)
   - working (steady swirl)
   - waiting on you (dots gather, accent color)
   - done (settle)
   - Use it in the header pill and on the splash.
5. **Background task cards.** A compact card in the transcript shows a title, a live state (working / needs you / done) and a tap to expand the steps. The final result arrives as a normal message that replies to the card.
6. **Action cards with explicit choice.** Drafts, unsubscribe lists and purchases come as cards with Approve / Edit / Discard. Nothing destructive runs without a tap, and approvals from background work expire (about 30 min) with a gentle re-ask.
7. **Proactive cadence: offer first, few and concrete.**
   - Theta texts first for briefs (7:00 and 18:00), Vantage events, follow-ups on its own commitments, and broken connections.
   - Each text names specifics (numbers, names) and ends with a choice question.
   - Rules: daily cap (6), quiet hours (Red only), dedupe, never rumors, as in SPEC.
   - Notifications have their own toggle, separate from check-ins.
8. **Notification discipline.**
   - Push only for a result, a question or an alert. Collapse repeats into one notification per thread and never re-push for the same thing.
   - No push while the app is foregrounded; the message just appears.
   - Body text: one complete sentence with no sensitive details. The title is "Theta" or the topic.
9. **Optimistic send.** The user bubble appears instantly with a `client_id` and reconciles on `event: user`. Failed sends show inline retry, never a modal.
10. **Short messages land whole, long answers stream.** Acks and proactive texts appear as complete bubbles, like texting. Long answers stream deltas.
11. **Splash.** The dot-globe alone on the theme background, animating into its idle state. No wordmark and no spinner. Hand off to the chat with the same avatar position for continuity.
12. **Connections sheet.**
    - Full-height sheet with an "N connected" pill and a one-line capability description per item.
    - "Suggested because …" reasons.
    - Inline "Connect X" cards when a request needs a missing connection.
13. **Limit and status banners docked above the composer.** For example, a provider outage or quota reached. Write them in Theta's voice, never as a blocking modal, and never place them inside the transcript.
