#!/usr/bin/env python3
"""Convert a markdown file to a styled HTML file in /tmp, print the output path."""

import sys
import subprocess
import hashlib
from pathlib import Path
from urllib.parse import quote

def md_to_html(md_path: str) -> str:
    """Convert markdown file to styled HTML, return output path."""
    md_file = Path(md_path)
    if not md_file.exists():
        print(f"Error: {md_path} not found", file=sys.stderr)
        sys.exit(1)

    md_content = md_file.read_text()

    # Use cmark if available, otherwise basic conversion
    try:
        result = subprocess.run(
            ["cmark-gfm", "--unsafe", "-e", "table", "-e", "strikethrough", "-e", "autolink"],
            input=md_content,
            capture_output=True,
            text=True,
            check=True,
        )
        body = result.stdout
    except FileNotFoundError:
        # Fallback: wrap in <pre> if cmark-gfm not installed
        import html as html_mod
        body = f"<pre>{html_mod.escape(md_content)}</pre>"

    title = md_file.stem.replace("--", " — ").replace("-", " ").title()

    # Determine if this is a transcript (affects TOC heading level)
    is_transcript = "--transcript" in md_file.name
    toc_heading = "h2" if is_transcript else "h2"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --serif: 'Palatino Linotype', Palatino, 'Book Antiqua', 'Georgia', serif;
    --mono: 'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace;
    --bg: #fcfbf9;
    --bg-sidebar: #f5f3ef;
    --text: #2a2520;
    --text-muted: #6b6560;
    --border: #ddd8d0;
    --accent: #8b4513;
    --link: #6b3a1f;
    --sidebar-w: 280px;
    --content-max: 700px;
  }}

  body {{
    font-family: var(--serif);
    font-size: 20px;
    line-height: 1.75;
    color: var(--text);
    background: var(--bg);
    -webkit-font-smoothing: antialiased;
  }}

  .layout {{
    display: flex;
    max-width: calc(var(--sidebar-w) + var(--content-max) + 5rem);
    margin: 0 auto;
    min-height: 100vh;
  }}

  nav.toc {{
    position: sticky;
    top: 0;
    align-self: flex-start;
    width: var(--sidebar-w);
    flex-shrink: 0;
    height: 100vh;
    overflow-y: auto;
    padding: 2.5rem 1.25rem 2rem 0;
  }}

  nav.toc .toc-title {{
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
  }}

  nav.toc ul {{ list-style: none; padding: 0; margin: 0; }}
  nav.toc li {{ margin-bottom: 0.15rem; }}

  nav.toc a {{
    display: block;
    padding: 0.3rem 0.6rem;
    font-size: 0.9rem;
    line-height: 1.4;
    color: var(--text-muted);
    text-decoration: none;
    border-radius: 4px;
    transition: color 0.15s, background 0.15s;
  }}

  nav.toc a:hover {{ color: var(--text); background: rgba(0,0,0,0.04); }}
  nav.toc a.active {{ color: var(--accent); background: rgba(139,69,19,0.06); font-weight: 600; }}

  .content {{
    flex: 1;
    max-width: var(--content-max);
    padding: 2.5rem 0 4rem 2.5rem;
    border-left: 1px solid var(--border);
  }}

  .source-link {{
    font-size: 0.78rem;
    color: var(--text-muted);
    margin-bottom: 1.5rem;
  }}
  .source-link a {{
    color: var(--text-muted);
    text-decoration: none;
    border-bottom: 1px solid var(--border);
  }}
  .source-link a:hover {{ color: var(--accent); border-color: var(--accent); }}

  h1 {{
    font-family: var(--serif);
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.2;
    margin: 3.5rem 0 0.5rem;
    padding-bottom: 0;
    border-bottom: none;
    color: var(--text);
  }}

  h1:first-child {{ margin-top: 0; }}
  h1 + hr {{ display: none; }}

  .metadata {{ font-size: 1rem; color: var(--text-muted); margin: 0 0 1rem; line-height: 1.6; }}
  .metadata + .metadata {{ margin-top: 0; }}
  .metadata strong {{ color: var(--text-muted); }}
  .metadata.metadata-date {{ margin-bottom: 0; }}

  h2 {{
    font-family: var(--serif);
    font-size: 1.5rem;
    font-weight: 700;
    margin: 1.75rem 0 0.5rem;
    color: var(--text);
  }}

  h3 {{
    font-family: var(--serif);
    font-size: 1rem;
    font-weight: 700;
    margin: 1.5rem 0 0.4rem;
    color: var(--text);
  }}

  h4 {{
    font-family: var(--serif);
    font-size: 0.95rem;
    font-weight: 700;
    margin: 1.25rem 0 0.35rem;
    color: var(--text-muted);
  }}

  p {{ margin: 0 0 1rem; }}
  strong {{ font-weight: 700; }}
  em {{ color: var(--text-muted); }}

  a {{ color: var(--link); text-decoration: underline; text-decoration-color: rgba(107,58,31,0.3); text-underline-offset: 2px; }}
  a:hover {{ text-decoration-color: var(--link); }}

  hr {{ border: none; border-top: 1px solid var(--border); margin: 2rem 0; }}

  ul, ol {{ margin: 0 0 1rem; padding-left: 1.4rem; }}
  li {{ margin-bottom: 0.3rem; }}
  li > ul, li > ol {{ margin-top: 0.3rem; margin-bottom: 0; }}

  blockquote {{ border-left: 2px solid var(--accent); padding: 0.4rem 0 0.4rem 1.25rem; margin: 0 0 1rem; color: var(--text-muted); font-style: italic; }}

  pre {{ background: #f0ede8; border: 1px solid var(--border); border-radius: 4px; padding: 1rem 1.25rem; overflow-x: auto; margin: 0 0 1rem; font-size: 0.82rem; line-height: 1.55; }}
  code {{ font-family: var(--mono); font-size: 0.85em; }}
  :not(pre) > code {{ background: #eeebe5; padding: 0.12em 0.35em; border-radius: 3px; }}

  table {{ width: 100%; border-collapse: collapse; margin: 0 0 1rem; font-size: 0.92rem; }}
  th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ font-weight: 700; font-size: 0.78rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-muted); }}

  @media (max-width: 860px) {{
    nav.toc {{ display: none; }}
    .toc-toggle {{ display: block; position: fixed; top: 0.6rem; right: 0.75rem; z-index: 20; background: var(--bg-sidebar); border: 1px solid var(--border); border-radius: 4px; padding: 0.3rem 0.6rem; font-family: var(--serif); font-size: 0.75rem; color: var(--text-muted); cursor: pointer; }}
    .content {{ padding: 2rem 1.25rem 3rem; border-left: none; }}
  }}
  @media (min-width: 861px) {{ .toc-toggle {{ display: none; }} }}

  h1[id], h2[id] {{ scroll-margin-top: 1rem; }}
  @media (max-width: 860px) {{ h1[id], h2[id] {{ scroll-margin-top: 3.5rem; }} }}
</style>
</head>
<body>
<button class="toc-toggle" onclick="document.querySelector('.toc').classList.toggle('open')">Contents</button>
<div class="layout">
  <nav class="toc">
    <div class="toc-title">Contents</div>
    <ul id="toc-list"></ul>
  </nav>
  <div class="content">
    <div class="source-link"><a href="raycast://script-commands/open-file?arguments={quote(str(md_file.resolve()), safe='')}">Open markdown source</a></div>
    {body}
  </div>
</div>
<script>
(function() {{
  var content = document.querySelector('.content');
  var tocList = document.getElementById('toc-list');
  var headings = content.querySelectorAll('h2');
  headings.forEach(function(h, i) {{
    var id = 'section-' + i;
    h.id = id;
    var li = document.createElement('li');
    var a = document.createElement('a');
    a.href = '#' + id;
    a.textContent = h.textContent;
    a.dataset.target = id;
    li.appendChild(a);
    tocList.appendChild(li);
  }});
  var tocLinks = tocList.querySelectorAll('a');
  if (!tocLinks.length) return;
  var observer = new IntersectionObserver(function(entries) {{
    entries.forEach(function(entry) {{
      if (entry.isIntersecting) {{
        tocLinks.forEach(function(a) {{ a.classList.remove('active'); }});
        var match = tocList.querySelector('a[data-target="' + entry.target.id + '"]');
        if (match) match.classList.add('active');
      }}
    }});
  }}, {{ rootMargin: '-10% 0px -80% 0px' }});
  headings.forEach(function(h) {{ observer.observe(h); }});
  tocLinks.forEach(function(a) {{
    a.addEventListener('click', function() {{
      document.querySelector('.toc').classList.remove('open');
    }});
  }});
  // Add .metadata class to Date/Participants paragraphs
  content.querySelectorAll('p').forEach(function(p) {{
    var strong = p.querySelector('strong');
    if (strong && /^(Date|Participants):$/.test(strong.textContent)) {{
      p.classList.add('metadata');
      if (strong.textContent === 'Date:') p.classList.add('metadata-date');
    }}
  }});
}})();
</script>
</body>
</html>"""

    # Write to /tmp with a stable name based on the source path
    path_hash = hashlib.md5(str(md_file.resolve()).encode()).hexdigest()[:8]
    out_name = f"{md_file.stem}-{path_hash}.html"
    out_path = Path("/tmp") / out_name
    out_path.write_text(html)
    return str(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: md-to-html.py <markdown-file> [<markdown-file> ...]", file=sys.stderr)
        sys.exit(1)

    for path in sys.argv[1:]:
        print(md_to_html(path))
