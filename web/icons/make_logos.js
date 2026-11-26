// Writes web/logos.js. Run from a folder with simple-icons installed (npm i simple-icons): node make_logos.js > web/logos.js
const si = require('simple-icons'), ver = JSON.parse(require('fs').readFileSync('node_modules/simple-icons/package.json')).version;
// connection id -> simple-icons slug
const map = {gmail:'gmail', calendar:'googlecalendar', drive:'googledrive', phone:'twilio', giphy:'giphy',
  googlesheets:'googlesheets', googlemaps:'googlemaps', icloud:'icloud', slack:'slack', discord:'discord', telegram:'telegram',
  whatsapp:'whatsapp', notion:'notion', todoist:'todoist', obsidian:'obsidian', evernote:'evernote', dropbox:'dropbox', zoom:'zoom',
  '1password':'1password', bitwarden:'bitwarden', homeassistant:'homeassistant', philipshue:'philipshue', spotify:'spotify',
  youtube:'youtube', plex:'plex', netflix:'netflix', paypal:'paypal', venmo:'venmo', uber:'uber', doordash:'doordash',
  instacart:'instacart', airbnb:'airbnb', strava:'strava', fitbit:'fitbit', garmin:'garmin', github:'github', vercel:'vercel',
  linear:'linear', figma:'figma', reddit:'reddit'};
const bySlug = Object.fromEntries(Object.values(si).filter(x => x && x.slug).map(x => [x.slug, x]));
const out = {};
for (const [id, slug] of Object.entries(map)) { const i = bySlug[slug]; if (!i) throw new Error('missing ' + slug); out[id] = [i.hex, i.path]; }
process.stdout.write(`/* Brand logos for Settings > Connections: id -> [brand hex, SVG path on a 24x24 grid].
 * Generated from Simple Icons ${ver} (https://simpleicons.org, CC0-1.0); the marks belong to their owners and are
 * used only to show which service a connection is. Regenerate rather than hand-edit. */
window.ThetaLogos = ${JSON.stringify(out)};
`);
