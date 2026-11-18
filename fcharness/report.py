"""Explain-it-to-me report: one Markdown file and one HTML file with the same content and pictures."""
import html
import os

from .verdict import ICON


class Report:
    def __init__(self, title):
        self.title = title
        self.blocks = []  # (kind, payload)

    def h(self, level, text):
        self.blocks.append(("h", (level, text)))

    def p(self, text):
        self.blocks.append(("p", text))

    def bullets(self, items):
        self.blocks.append(("ul", list(items)))

    def img(self, rel, caption):
        self.blocks.append(("img", (rel, caption)))

    def table(self, header, rows):
        self.blocks.append(("table", (header, rows)))

    def verdict(self, level, headline, text):
        self.blocks.append(("verdict", (level, headline, text)))

    def code(self, text):
        self.blocks.append(("code", text))

    def markdown(self):
        L = ["# " + self.title, ""]
        for kind, x in self.blocks:
            if kind == "h":
                L += ["#" * x[0] + " " + x[1], ""]
            elif kind == "p":
                L += [x, ""]
            elif kind == "ul":
                L += ["- " + i for i in x] + [""]
            elif kind == "img":
                L += ["![%s](%s)" % (x[1], x[0]), "", "*%s*" % x[1], ""]
            elif kind == "table":
                hdr, rows = x
                L.append("| " + " | ".join(hdr) + " |")
                L.append("|" + "---|" * len(hdr))
                L += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
                L.append("")
            elif kind == "verdict":
                L += ["> %s **%s** — %s" % (ICON[x[0]], x[1], x[2]), ""]
            elif kind == "code":
                L += ["```", x.rstrip(), "```", ""]
        return "\n".join(L)

    def html(self):
        e = html.escape
        css = ("body{font-family:system-ui,sans-serif;max-width:980px;margin:2em auto;padding:0 1em;color:#222;line-height:1.45}"
               "img{max-width:100%;border:1px solid #ddd;border-radius:6px}figure{margin:1em 0}figcaption{color:#555;font-size:.9em}"
               "table{border-collapse:collapse;margin:.5em 0}td,th{border:1px solid #ccc;padding:.25em .6em;text-align:left}"
               ".v{padding:.6em 1em;border-radius:6px;margin:.6em 0}.green{background:#e6f4e6}.amber{background:#fdf3d8}.red{background:#fbe3e3}"
               "pre{background:#f5f5f5;padding:.8em;overflow:auto}")
        L = ["<!doctype html><html><head><meta charset='utf-8'><title>%s</title><style>%s</style></head><body>" % (e(self.title), css),
             "<h1>%s</h1>" % e(self.title)]
        for kind, x in self.blocks:
            if kind == "h":
                L.append("<h%d>%s</h%d>" % (x[0], e(x[1]), x[0]))
            elif kind == "p":
                L.append("<p>%s</p>" % _inline(x))
            elif kind == "ul":
                L.append("<ul>" + "".join("<li>%s</li>" % _inline(i) for i in x) + "</ul>")
            elif kind == "img":
                L.append("<figure><img src='%s' alt='%s'><figcaption>%s</figcaption></figure>" % (e(x[0]), e(x[1]), e(x[1])))
            elif kind == "table":
                hdr, rows = x
                L.append("<table><tr>" + "".join("<th>%s</th>" % e(str(h)) for h in hdr) + "</tr>" +
                         "".join("<tr>" + "".join("<td>%s</td>" % _inline(str(c)) for c in r) + "</tr>" for r in rows) + "</table>")
            elif kind == "verdict":
                L.append("<div class='v %s'>%s <b>%s</b> — %s</div>" % (x[0], ICON[x[0]], e(x[1]), _inline(x[2])))
            elif kind == "code":
                L.append("<pre>%s</pre>" % e(x))
        L.append("</body></html>")
        return "\n".join(L)

    def write(self, outdir, stem="report"):
        md = os.path.join(outdir, stem + ".md")
        ht = os.path.join(outdir, stem + ".html")
        open(md, "w").write(self.markdown())
        open(ht, "w").write(self.html())
        return md, ht


def _inline(s):
    """Escape, then support **bold** and [text](link) - the only inline markup the harness emits."""
    import re
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<a href='\2'>\1</a>", s)
    return s
