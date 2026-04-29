import sys
sys.path.insert(0, '.')
try:
    from app.main import app
    routes = sorted(
        f"{m:<8} {r.path}"
        for r in app.routes if hasattr(r, "methods")
        for m in r.methods
    )
    for r in routes:
        print(r)
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    sys.exit(1)
