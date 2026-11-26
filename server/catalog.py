"""Apps Theta could connect to but doesn't yet. They show in Settings > Apps as "Soon" so the list reads like
a real app directory, and so Theta can tell the user plainly that one isn't built (rather than inventing a way).
Each entry: id (matches web/logos.js), name, cat (the filter chip), what (one line: what Theta would do with it).
Built connections come from app.connections() and the features; an id here that a feature also reports is
dropped from this list, so building one never shows it twice."""

CATS = {  # category chip for the built connections, by id
    "gmail": "Google", "calendar": "Google", "drive": "Google",
    "vantage": "Theta", "search": "Web", "browser": "Web", "phone": "Messaging", "giphy": "Media",
}

SOON = [
    ("googlesheets", "Google Sheets", "Google", "Read and update your spreadsheets"),
    ("googlemaps", "Google Maps", "Travel & food", "Directions, drive times and places near you"),
    ("icloud", "iCloud", "iPhone", "Apple Calendar, Reminders and Contacts"),
    ("slack", "Slack", "Messaging", "Read channels, catch you up and draft replies"),
    ("discord", "Discord", "Messaging", "Catch you up on servers and DMs"),
    ("telegram", "Telegram", "Messaging", "Read and send messages with your OK"),
    ("whatsapp", "WhatsApp", "Messaging", "Send messages with your OK"),
    ("notion", "Notion", "Productivity", "Search, read and add to your pages"),
    ("todoist", "Todoist", "Productivity", "Add, sort and finish your tasks"),
    ("obsidian", "Obsidian", "Productivity", "Read and add to your vault"),
    ("evernote", "Evernote", "Productivity", "Search and add notes"),
    ("dropbox", "Dropbox", "Productivity", "Find, read and save files"),
    ("zoom", "Zoom", "Productivity", "See and schedule meetings"),
    ("1password", "1Password", "Passwords", "Sign Theta's browser in without it seeing the password"),
    ("bitwarden", "Bitwarden", "Passwords", "Sign Theta's browser in without it seeing the password"),
    ("homeassistant", "Home Assistant", "Home", "Lights, locks and the thermostat"),
    ("philipshue", "Philips Hue", "Home", "Turn lights on, off and dim them"),
    ("spotify", "Spotify", "Media", "Play, queue and find music"),
    ("youtube", "YouTube", "Media", "Find videos and keep your watch list"),
    ("plex", "Plex", "Media", "What you're watching and what's next"),
    ("netflix", "Netflix", "Media", "Track what you're watching"),
    ("paypal", "PayPal", "Money", "See payments and send money with your OK"),
    ("venmo", "Venmo", "Money", "Request and pay friends with your OK"),
    ("uber", "Uber", "Travel & food", "Price and book rides with your OK"),
    ("doordash", "DoorDash", "Travel & food", "Reorder favorites with your OK"),
    ("instacart", "Instacart", "Travel & food", "Build and order your grocery list with your OK"),
    ("airbnb", "Airbnb", "Travel & food", "Search stays and track trips"),
    ("strava", "Strava", "Health", "Your runs, rides and weekly totals"),
    ("fitbit", "Fitbit", "Health", "Sleep, steps and heart rate"),
    ("garmin", "Garmin", "Health", "Workouts, sleep and training load"),
    ("github", "GitHub", "Developer", "Issues, pull requests and builds"),
    ("vercel", "Vercel", "Developer", "Deploys, logs and errors"),
    ("linear", "Linear", "Developer", "Issues and cycles"),
    ("figma", "Figma", "Developer", "Find files and read comments"),
    ("reddit", "Reddit", "Web", "Catch up on the subreddits you follow"),
]


def merge(built):
    """The built connections, each with its category, followed by the catalog entries not already built."""
    out = [{**c, "cat": c.get("cat") or CATS.get(c.get("id"), "Other")} for c in built]
    have = {c.get("id") for c in out}
    out += [{"id": i, "name": n, "cat": cat, "what": w, "connected": False, "soon": True}
            for i, n, cat, w in SOON if i not in have]
    return out
