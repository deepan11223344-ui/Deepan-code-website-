from pathlib import Path

p = Path(__file__).resolve().parent.parent / "deepans_code" / "cli.py"
t = p.read_text(encoding="utf-8")
bad = 'ctx[\\"theme\\"]'
good = 'ctx["theme"]'
n = t.count(bad)
t = t.replace(bad, good)
p.write_text(t, encoding="utf-8")
print("fixed:", n, "remaining bad:", t.count(bad))
