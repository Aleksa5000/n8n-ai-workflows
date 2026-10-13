#!/usr/bin/env python3
"""Dev tool: screenshot the workflow canvases from the running local demo n8n (headless browser).

    pip install playwright          # no browser download needed, an installed Edge/Chrome is used
    python scripts/capture_screenshots.py

Needs the stack from `docker compose up`, the workflows imported with `scripts/import_workflows.sh all`, and the demo owner
from `scripts/setup_demo_owner.sh`. Writes PNGs to docs/. Set BROWSER_CHANNEL=chrome to use Chrome instead of Edge.
"""
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = f"http://127.0.0.1:{os.environ.get('N8N_HOST_PORT', '5679')}"
CANVASES = {
    "00-error-handler": "n8nAiErrorHandle",
    "01-gmail-ai-triage": "n8nAiGmailTriage",
    "02-support-chatbot-rag": "n8nAiSupportRag0",
    "03-lead-intake-qualification": "n8nAiLeadIntake0",
}
# One demo request per workflow; its execution is then opened in the editor to show a real green run.
RUN_ID = str(int(time.time()))
DEMO_RUNS = {
    "demo-run-01-triage": ("n8nAiDemoTriage0", "email-triage", {
        "from": "Dana Lee <dana@bigclient.example>", "subject": "Production is down",
        "body": "Customers cannot log in. Please fix ASAP, can you call me?"}),
    "demo-run-02-support": ("n8nAiDemoSupport", "support-chat", {
        "message": "What is the weather in Paris tomorrow?", "session_id": "demo",
        "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello! How can I help?"}]}),
    "demo-run-03-leads": ("n8nAiDemoLeads00", "lead-intake", {
        "name": "Dana Whitfield", "email": f"dana.{RUN_ID}@bigco.com", "company": "BigCo", "phone": "+1 555 010 0199",
        "message": "We need a quote for automating our client onboarding with AI. Budget is around 15k and we want to launch next week."}),
}


def owner() -> dict:
    env_file = ROOT / ".env" if (ROOT / ".env").exists() else ROOT / ".env.example"
    env = dict(line.split("=", 1) for line in env_file.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {"emailOrLdapLoginId": env["DEMO_OWNER_EMAIL"], "password": env["DEMO_OWNER_PASSWORD"]}


HIDE_OVERLAYS = """
.vue-flow__panel, .vue-flow__minimap { display: none !important; }
[data-test-id='canvas-wrapper'] > [class*='canvas' i] ~ div, [data-test-id='radio-button-workflow'] { visibility: hidden; }
"""


def settle(page, nodes_expected: int = 1) -> None:
    page.wait_for_selector(".vue-flow__node", timeout=30000)
    page.wait_for_function(f"document.querySelectorAll('.vue-flow__node').length >= {nodes_expected}", timeout=30000)
    page.wait_for_timeout(1500)
    page.keyboard.press("1")  # zoom to fit
    page.wait_for_timeout(1500)
    page.add_style_tag(content=HIDE_OVERLAYS)
    page.wait_for_timeout(300)


def shoot(page, path: Path, pad: int = 24) -> None:
    """Screenshot only the region holding the nodes (leaves out the editor chrome)."""
    box = page.evaluate("""() => {
        const r = [...document.querySelectorAll('.vue-flow__node')].map((e) => e.getBoundingClientRect());
        return { x: Math.min(...r.map((a) => a.left)), y: Math.min(...r.map((a) => a.top)),
                 x2: Math.max(...r.map((a) => a.right)), y2: Math.max(...r.map((a) => a.bottom)) };
    }""")
    x, y = max(0, box["x"] - pad), max(0, box["y"] - pad)
    page.screenshot(path=str(path), clip={"x": x, "y": y, "width": box["x2"] + pad - x, "height": box["y2"] + pad - y})


def main() -> int:
    out = ROOT / "docs"
    out.mkdir(exist_ok=True)
    only = set(sys.argv[1:])
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("BROWSER_CHANNEL", "msedge"), headless=True)
        ctx = browser.new_context(viewport={"width": 1900, "height": 1000}, device_scale_factor=1.5)
        r = ctx.request.post(f"{BASE}/rest/login", data=owner())
        assert r.ok, f"login failed: {r.status}"
        page = ctx.new_page()
        for name, wf_id in CANVASES.items():
            if only and name not in only:
                continue
            page.goto(f"{BASE}/workflow/{wf_id}")
            settle(page, 5)
            shoot(page, out / f"{name}.png")
            print("saved", out / f"{name}.png")
        for name, (wf_id, path, payload) in DEMO_RUNS.items():
            if only and name not in only:
                continue
            ctx.request.post(f"{BASE}/webhook/demo/{path}", data=payload)
            time.sleep(3)
            page.goto(f"{BASE}/workflow/{wf_id}/executions")
            iframe = page.locator("iframe").first
            iframe.wait_for(timeout=30000)
            frame = next(f for f in page.frames if "/workflows/demo" in f.url)
            frame.wait_for_selector(".vue-flow__node", timeout=30000)
            page.wait_for_timeout(2500)
            frame.add_style_tag(content=HIDE_OVERLAYS)
            box = iframe.bounding_box()
            nodes = frame.evaluate("""() => {
                const r = [...document.querySelectorAll('.vue-flow__node')].map((e) => e.getBoundingClientRect());
                return { x2: Math.max(...r.map((a) => a.right)), y2: Math.max(...r.map((a) => a.bottom)) };
            }""")
            # keep the "Succeeded in ... ID#" header, drop the editor chrome above it and the empty space below the nodes
            clip = {"x": box["x"], "y": box["y"] + 16, "width": box["width"], "height": min(box["height"], nodes["y2"] + 24) - 16}
            page.screenshot(path=str(out / f"{name}.png"), clip=clip)
            print("saved", out / f"{name}.png")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
