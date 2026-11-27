"""Files and photos you send Theta: files (server/files.py) keep their text (text, Word, Excel, PDF), ride along
with a chat message as outside content that taints the turn, can be read further with file_read and downloaded;
photos sent as a data: URL in JSON are saved (a WSGI Content-Type bug once refused every one). Model faked."""
import base64, io, json, os, sys, tempfile, zipfile
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.update(PROTOS_KEY="k", PROTOS_TICK="0", PROTOS_QUIET="1", PROTOS_DATA=tempfile.mkdtemp(), DEEPSEEK_API_KEY="sk-test")
from server import app, approvals, db, ext, files, models, tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


db.init()
ext.reset(); tools._ext_reset(); tools._ext()


def call(method, path, body=b"", ctype="application/json", headers=None):
    path, _, qs = path.partition("?")
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(body)),
           "CONTENT_TYPE": ctype, "wsgi.input": io.BytesIO(body), "HTTP_X_PROTOS_KEY": "k"}
    for k, v in (headers or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    got = {}
    out = b"".join(app.app(env, lambda s, h: got.update(s=int(s.split()[0]), h=dict(h))))
    return got["s"], out, got["h"]


# ---------------------------------------------------------------- photos as JSON
jpg = base64.b64decode("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////"
                       "////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=")
s, out, _ = call("POST", "/api/uploads", json.dumps({"data": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()}).encode())
check("a photo sent as a data: URL in JSON is saved", s == 200 and json.loads(out)["url"].startswith("/api/uploads/"))

# ---------------------------------------------------------------- reading files
t = files.save(b"Rent is due Dec 1.\nLandlord: Pat Lee.", "notes.txt", "text/plain")
check("a text file keeps its text", t["kind"] == "text" and files.text_of(t["id"]).startswith("Rent is due"))
docx = io.BytesIO()
with zipfile.ZipFile(docx, "w") as z:
    z.writestr("word/document.xml", '<w:document><w:body><w:p><w:r><w:t>Lease: 12 months</w:t></w:r></w:p>'
               '<w:p><w:r><w:t>Deposit &amp; fees: $500</w:t></w:r></w:p></w:body></w:document>')
d = files.save(docx.getvalue(), "lease.docx")
check("a Word file: paragraphs, entities decoded", d["kind"] == "docx" and "Lease: 12 months\nDeposit & fees: $500" in files.text_of(d["id"]))
xl = io.BytesIO()
with zipfile.ZipFile(xl, "w") as z:
    z.writestr("xl/sharedStrings.xml", "<sst><si><t>Item</t></si><si><t>Coffee</t></si></sst>")
    z.writestr("xl/worksheets/sheet1.xml", '<worksheet><sheetData><row><c t="s"><v>0</v></c><c><v>Cost</v></c></row>'
               '<row><c t="s"><v>1</v></c><c><v>4.5</v></c></row></sheetData></worksheet>')
x = files.save(xl.getvalue(), "budget.xlsx")
check("an Excel file: rows and shared strings", x["kind"] == "xlsx" and "Item\tCost\nCoffee\t4.5" in files.text_of(x["id"]))
try:
    from pypdf import PdfWriter
    from pypdf.generic import ContentStream, DecodedStreamObject, DictionaryObject, NameObject
    w = PdfWriter()
    page = w.add_blank_page(300, 200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject(); stream.set_data(b"BT /F1 12 Tf 20 100 Td (Invoice total: $42) Tj ET")
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = io.BytesIO(); w.write(buf)
    pdf = files.save(buf.getvalue(), "invoice.pdf")
    check("a PDF's text is read (pypdf), with its page count", pdf["kind"] == "pdf" and pdf["pages"] == 1
          and "Invoice total: $42" in files.text_of(pdf["id"]))
except ImportError:
    print("SKIP PDF (pypdf isn't installed)")
b = files.save(b"\x00\x01\x02binary", "thing.bin")
check("an unreadable file is kept, with no text", b["kind"] == "binary" and b["chars"] == 0)
try:
    files.save(b"", "empty.txt"); ok = False
except ValueError:
    ok = True
check("an empty file is refused", ok)

# ---------------------------------------------------------------- routes
s, out, _ = call("POST", "/api/files", b"Meeting at 3pm with Ana", "text/plain", {"x-file-name": "plan%20for%20Friday.txt"})
up = json.loads(out)
check("POST /api/files saves it under its real name", s == 200 and up["name"] == "plan for Friday.txt" and up["chars"] == 23)
s, out, h = call("GET", "/api/files/" + up["id"])
check("and it downloads back", s == 200 and out == b"Meeting at 3pm with Ana" and "attachment" in h.get("Content-Disposition", ""))
s, _, _ = call("GET", "/api/files/../../etc/passwd")
check("no path tricks", s in (404, 405))

# ---------------------------------------------------------------- in a chat turn
SEEN = []


def fake_call(provider, model, messages, tools_=None, max_tokens=1024, on_text=None, tool_choice="auto", timeout=None):
    SEEN.append(messages[-1]["content"] if isinstance(messages[-1]["content"], str) else json.dumps(messages[-1]["content"]))
    txt = "Dec 1, and the landlord is Pat Lee."
    if on_text:
        on_text(txt)
    return {"text": txt, "tool_calls": [], "reasoning": "", "usage": {"tokens_in": 1, "tokens_out": 1, "cache_read": 0, "cache_write": 0}}


models.call = fake_call
s, out, _ = call("POST", "/api/chat?stream=0", json.dumps({"bot": "theta", "text": "when is rent due?", "files": [t["id"]]}).encode())
j = json.loads(out)
check("a message with a file: the bubble lists it", s == 200 and j["user"]["meta"]["files"][0]["name"] == "notes.txt"
      and j["user"]["text"] == "when is rent due?")
check("and the model reads its text inside an outside-content frame", SEEN and "Rent is due Dec 1." in SEEN[-1]
      and "Outside content" in SEEN[-1] and "<<<file" in SEEN[-1])
s, out, _ = call("POST", "/api/chat?stream=0", json.dumps({"bot": "theta", "text": "", "files": [d["id"]]}).encode())
check("a file with no words is fine", s == 200 and json.loads(out)["user"]["text"] == "I attached a file.")
check("a turn with a file is tainted (it can't make Theta send on its own)", approvals.tainted({"tainted": True, "tools": []}))
ok, out = tools.execute("file_read", {"id": t["id"], "find": "landlord"}, {"bot": "theta"})
check("file_read finds the part asked for", ok and "Landlord: Pat Lee." in out)
check("recent files are in the turn context", "plan for Friday.txt" in tools.context_block("theta"))
print("all files checks passed")
