#!/usr/bin/env python3
"""End-to-end check of the demo workflows against a running `docker compose up` stack (stdlib only).

    python scripts/smoke_demo.py            # n8n on 127.0.0.1:5679, mock services on 127.0.0.1:8795
    N8N_HOST_PORT=5680 MOCK_HOST_PORT=8800 python scripts/smoke_demo.py

Every scenario posts to a real n8n webhook and then asserts on what the mock services recorded.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

N8N = f"http://127.0.0.1:{os.environ.get('N8N_HOST_PORT', '5679')}/webhook/demo"
MOCK = f"http://127.0.0.1:{os.environ.get('MOCK_HOST_PORT', '8795')}"
RUN = str(int(time.time()))  # unique emails per run: the workflow remembers leads for DEDUPE_WINDOW_MIN minutes
results: list[tuple[str, bool, str]] = []


def call(method: str, url: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, raw = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read().decode()
    try:
        return status, json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return status, raw


def hook(path: str, body: dict | None = None, method: str = "POST") -> tuple[int, object]:
    return call(method, f"{N8N}/{path}", body)


def mock(path: str, method: str = "GET", body: dict | None = None):
    return call(method, f"{MOCK}{path}", body)[1]


def wait_for(cond, timeout: float = 20.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.5)
    return False


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  <- {detail}"))


def slack_texts() -> list[str]:
    return [m["text"] for m in mock("/slack/messages")]


def state() -> dict:
    return mock("/state")


def triage() -> None:
    mock("/admin/reset", "POST")
    status, r = hook("email-triage", {"from": "Dana Lee <dana@bigclient.example>", "subject": "Production is down",
                                      "body": "Customers cannot log in. Please fix ASAP, can you call me?"})
    check("triage: urgent email is classified Urgent", status == 200 and r["category"] == "Urgent", str(r))
    check("triage: label applied, draft created (not sent), Slack alerted, row logged",
          wait_for(lambda: state()["labels_applied"] == 1 and state()["drafts"] == 1 and any("URGENT email" in t for t in slack_texts())
                   and state()["sheets"].get("triage") == 1), str(state()))
    drafts = mock("/gmail/drafts")
    check("triage: the draft is addressed to the sender and has sent=false",
          drafts and drafts[0]["to"] == "dana@bigclient.example" and drafts[0]["sent"] is False and drafts[0]["subject"].startswith("Re:"), str(drafts))

    before = state()
    status, r = hook("email-triage", {"from": "news@vendor.example", "subject": "Monthly newsletter", "body": "Release notes and a digest"})
    check("triage: newsletter is Informational with no draft and no alert",
          r["category"] == "Informational" and r["draft_created"] is False
          and wait_for(lambda: state()["sheets"]["triage"] == 2) and state()["drafts"] == before["drafts"]
          and state()["slack_messages"] == before["slack_messages"], str(r))

    status, r = hook("email-triage", {"from": "Bo <bo@x.com>", "subject": "Hello", "body": "hi", "simulate_classifier": "invalid_category"})
    check("triage: invalid model output falls back to Routine, no draft", r["category"] == "Routine" and r["fallback"] is True
          and r["draft_created"] is False and "category" in r["validation_errors"], str(r))
    status, r = hook("email-triage", {"from": "Bo <bo@x.com>", "subject": "Hello", "body": "hi", "simulate_classifier": "prose"})
    check("triage: prose instead of JSON falls back to Routine", r["category"] == "Routine" and r["fallback"] is True, str(r))

    wait_for(lambda: state()["sheets"]["triage"] == 4)
    status, r = hook("triage-summary", method="GET")
    check("triage: daily digest summarises the logged rows and posts to Slack",
          status == 200 and r["total"] == 4 and any("Daily inbox digest" in t for t in slack_texts()), str(r))


def support() -> None:
    mock("/admin/reset", "POST")
    status, r = hook("support-chat", {"message": "What is your refund policy?", "session_id": "s1"})
    check("support: known question is answered from the knowledge base", status == 200 and r["answered"] and "30 days" in r["answer"]
          and "faq/refunds.md" in r["sources"] and r["escalated"] is False, str(r))
    check("support: Q&A is logged and nothing is escalated",
          wait_for(lambda: state()["sheets"].get("support_qa") == 1) and state()["slack_messages"] == 0, str(state()))

    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello! How can I help?"}]
    status, r = hook("support-chat", {"message": "What is the weather in Paris tomorrow?", "session_id": "s2", "history": history})
    check("support: no context -> \"I'm not sure\" and escalated", status == 200 and r["answered"] is False and r["escalated"] is True
          and r["answer"].startswith("I'm not sure") and r["sources"] == [], str(r))
    check("support: Slack escalation contains the conversation",
          wait_for(lambda: any("Support bot could not answer" in t and "Customer: hi" in t and "weather in Paris" in t for t in slack_texts())), str(slack_texts()))

    status, r = hook("support-chat", {"message": "Do you offer student discounts?", "session_id": "s3"})
    check("support: weak match (below KB_MIN_SCORE) is not answered", r["answered"] is False and "no passage scored above" in r["reason"], str(r))
    status, r = hook("support-chat", {"message": "   "})
    check("support: empty message is rejected with 400", status == 400, str(r))


def leads() -> None:
    mock("/admin/reset", "POST")
    good = {"name": "Dana Whitfield", "email": f"Dana.{RUN}@BigCo.com", "company": "BigCo", "phone": "+1 555 010 0199", "source": "pricing-page",
            "message": "We need a quote for automating our client onboarding with AI. Budget is around 15k and we want to launch next week."}
    status, r = hook("lead-intake", good)
    check("leads: strong lead is created and scored hot", status == 200 and r["status"] == "created" and r["tier"] == "hot", str(r))
    contacts = mock("/crm/v3/objects/contacts")["results"]
    props = contacts[0]["properties"] if contacts else {}
    check("leads: CRM contact has normalised email and AI score properties",
          props.get("email") == f"dana.{RUN}@bigco.com" and props.get("ai_lead_tier") == "hot" and props.get("ai_lead_score", 0) >= 70, str(props))
    check("leads: hot lead is announced in Slack", wait_for(lambda: any("HOT LEAD" in t for t in slack_texts())), str(slack_texts()))

    status, r = hook("lead-intake", {**good, "message": "sent twice"})
    check("leads: same email again is a duplicate, no second contact", r["status"] == "duplicate" and len(mock("/crm/v3/objects/contacts")["results"]) == 1, str(r))
    status, r = hook("lead-intake", {"name": "", "email": "nope"})
    check("leads: invalid payload gets 422 with the reasons", status == 422 and len(r["errors"]) == 2, str(r))

    old = mock("/crm/v3/objects/contacts", "POST", {"properties": {"email": f"old.{RUN}@acme.example", "firstname": "Old", "company": "Acme"}})
    status, r = hook("lead-intake", {"name": "Old Timer", "email": f"old.{RUN}@acme.example", "company": "Acme", "message": "Need pricing, deadline next week"})
    check("leads: existing CRM contact is updated, not duplicated", r["status"] == "updated" and r["crm_id"] == old["id"], str(r))

    status, r = hook("lead-intake", {"name": "Eve Corp", "email": f"eve.{RUN}@corp.example", "message": "hello [simulate-invalid]"})
    check("leads: invalid score is stored as unscored (lead is not lost)", r["tier"] == "unscored" and r["scoring_failed"] is True and r["status"] == "created", str(r))

    mock("/admin/chaos", "POST", {"crm": 2})
    n503 = lambda: sum(1 for e in mock("/log?limit=500") if e["status"] == 503)  # noqa: E731
    status, r = hook("lead-intake", {"name": "Retry Rita", "email": f"rita.{RUN}@retry.example", "message": "Pricing for a retainer please"})
    check("leads: CRM fails twice, the HTTP node retries and the lead is still saved", status == 200 and r["status"] == "created" and n503() == 2, f"{r} 503s={n503()}")

    alerts_before = sum("[n8n ALERT]" in t for t in slack_texts())
    mock("/admin/chaos", "POST", {"crm": 10})
    status, r = hook("lead-intake", {"name": "Down Dan", "email": f"dan.{RUN}@down.example", "message": "hello"})
    check("leads: CRM down -> caller gets 502 (not a silent 200)", status == 502 and r["status"] == "error", f"{status} {r}")
    check("error workflow: Slack alert names the workflow, failed node and execution URL",
          wait_for(lambda: sum("[n8n ALERT]" in t for t in slack_texts()) == alerts_before + 1)
          and any("Workflow failed: DEMO 03" in t and "Failed node:" in t and "/executions/" in t for t in slack_texts()), str(slack_texts()[-1:]))
    mock("/admin/chaos", "POST", {"crm": 0})


if __name__ == "__main__":
    try:
        triage()
        support()
        leads()
    finally:
        mock("/admin/chaos", "POST", {"crm": 0})
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)
