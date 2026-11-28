/* media: shows generated images (server/media.py) in Theta's replies. Uses window.Theta (app.js).
 * The tool's output tells the model to put [image:<id>] in its reply; this finds that marker in the rendered text,
 * replaces it with <img src="/api/media/<id>.png"> and hides the marker. DOM nodes only, never innerHTML. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const MARK = /\[image:([0-9a-f]{32})\]/g;

  const style = document.createElement("style");
  style.textContent = `
.media-img { display: block; max-width: 100%; width: 320px; height: auto; border-radius: var(--r-l); margin: 8px 0; background: var(--sunk); }
.media-img.broken { min-height: 48px; }
.media-gone { color: var(--muted); font-size: var(--fs-sm); }
`;
  document.head.append(style);

  function image(id) {
    const img = document.createElement("img");
    img.className = "media-img"; img.alt = "Image made by Theta"; img.loading = "lazy"; img.decoding = "async";
    img.src = "/api/media/" + id + ".png";
    img.addEventListener("error", () => {
      const s = document.createElement("span"); s.className = "media-gone";
      s.textContent = T.state.demo ? "(an image would show here)" : "(the image isn't available)";
      img.replaceWith(s);
    }, {once: true});
    return img;
  }

  // split each text node that holds a marker into: text before, the image, text after
  function swap(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const hits = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) if (/\[image:[0-9a-f]{32}\]/.test(n.nodeValue)) hits.push(n);
    for (const node of hits) {
      const text = node.nodeValue, frag = document.createDocumentFragment();
      let last = 0;
      for (const m of text.matchAll(MARK)) {
        const before = text.slice(last, m.index);
        if (before.trim()) frag.append(document.createTextNode(before));
        frag.append(image(m[1]));
        last = m.index + m[0].length;
      }
      const after = text.slice(last);
      if (after.trim()) frag.append(document.createTextNode(after));
      node.replaceWith(frag);
    }
    return hits.length;
  }

  T.decorate((m, row, bubble) => {
    if (!m || m.role !== "assistant" || !bubble || !/\[image:[0-9a-f]{32}\]/.test(m.text || "")) return;
    swap(bubble);
  });
})();
