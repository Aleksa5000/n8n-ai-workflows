"""Unit tests for the JavaScript inside the Code nodes, run with node against a fake n8n context.

These cover the logic that guards the LLM output (schema validation, fallbacks, thresholds), which the demo
mode cannot fully exercise because the fake classifier answers politely most of the time."""
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def run(name, input=None, nodes=None, env=None, static=None, today="2026-10-13"):
    req = {"file": str(ROOT / "scripts" / "code_nodes" / f"{name}.js"), "input": input or [], "nodes": nodes or {},
           "env": env or {}, "staticData": static or {}, "today": today}
    p = subprocess.run([NODE, str(ROOT / "tests" / "js_harness.js")], input=json.dumps(req), capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_every_code_node_source_is_syntactically_valid():
    for f in sorted((ROOT / "scripts" / "code_nodes").glob("*.js")):
        wrapped = f"(function ($input, $, $env, $getWorkflowStaticData, $now) {{\n{f.read_text(encoding='utf-8')}\n}})"
        p = subprocess.run([NODE, "--check", "-"], input=wrapped, capture_output=True, text=True)
        assert p.returncode == 0, f"{f.name}: {p.stderr}"


# --- Gmail triage: validate classification ----------------------------------------------------------------------

EMAIL = {"message_id": "m1", "thread_id": "t1", "from_email": "a@b.com", "from_name": "A", "subject": "Hi", "received_at": "x"}
GOOD = {"category": "Billing", "confidence": 0.8, "summary": "Invoice question", "needs_reply": True, "reply_draft": "Hello,\nThanks.",
        "reason": "invoice"}


def classify(*outputs):
    items = [o if isinstance(o, dict) and "error" in o else {"output": o} for o in outputs]
    return run("validate_classification", input=items,
               nodes={"Normalize email": [{**EMAIL, "message_id": f"m{i}"} for i in range(len(items))]})["items"]


def test_valid_classification_passes_through():
    (r,) = classify(GOOD)
    assert r["category"] == "Billing" and r["fallback"] is False and r["needs_reply"] is True and r["reply_draft"] == "Hello,\nThanks."
    assert r["message_id"] == "m0" and r["thread_id"] == "t1"


@pytest.mark.parametrize("bad", [
    {**GOOD, "category": "Spam"},                      # not in the enum
    {**GOOD, "category": "urgent"},                    # wrong case
    {**GOOD, "confidence": 1.5},                       # out of range
    {**GOOD, "confidence": "high"},                    # wrong type
    {**GOOD, "summary": "   "},                        # empty summary
    {**GOOD, "needs_reply": "yes"},                    # wrong type
    {k: v for k, v in GOOD.items() if k != "reply_draft"},
    "Sure! I think this is Urgent.",                   # prose, no JSON
    "{not json at all}",
    None,
    [GOOD],                                            # array instead of object
    {"error": "429 rate limited"},                     # chain failed (continue-on-error item)
])
def test_invalid_output_falls_back_to_routine_without_a_draft(bad):
    (r,) = classify(bad)
    assert r["category"] == "Routine" and r["fallback"] is True and r["confidence"] == 0
    assert r["needs_reply"] is False and r["reply_draft"] == "" and r["validation_errors"]
    assert r["message_id"] == "m0"  # the email is never lost


def test_json_wrapped_in_prose_or_fences_is_accepted():
    (r,) = classify("Here you go:\n```json\n" + json.dumps({**GOOD, "category": "Client"}) + "\n```")
    assert r["category"] == "Client" and r["fallback"] is False


def test_reply_needed_but_draft_empty_means_no_draft():
    (r,) = classify({**GOOD, "reply_draft": "  "})
    assert r["needs_reply"] is False and r["fallback"] is False


def test_each_email_keeps_its_own_result_in_order():
    a, b = classify({**GOOD, "category": "Urgent"}, "garbage")
    assert (a["message_id"], a["category"]) == ("m0", "Urgent") and (b["message_id"], b["category"]) == ("m1", "Routine")


def test_attach_label_id_maps_category_to_gmail_label_id():
    labels = [{"id": "Label_9", "name": "AI/Urgent"}, {"id": "INBOX", "name": "INBOX"}]
    triaged = [{"category": "Urgent", "message_id": "m1"}, {"category": "Billing", "message_id": "m2"}]
    out = run("attach_label_id", input=labels, nodes={"Validate classification": triaged})["items"]
    assert out[0]["label_id"] == "Label_9" and out[1]["label_id"] == "" and out[1]["label_name"] == "AI/Billing"


def test_normalize_gmail_flattens_the_parsed_email():
    mail = {"id": "m1", "threadId": "t1", "subject": "Hello", "text": "Hi\r\n\r\n\r\n\r\nthere", "date": "2026-10-13T08:00:00Z",
            "from": {"value": [{"address": "Ana@Example.com", "name": "Ana"}]}}
    (r,) = run("normalize_gmail", input=[mail])["items"]
    assert r["from_email"] == "ana@example.com" and r["thread_id"] == "t1" and r["body"] == "Hi\n\nthere"
    long = run("normalize_gmail", input=[{**mail, "text": "x" * 9000}])["items"][0]
    assert len(long["body"]) == 6000


def test_normalize_demo_email_parses_name_and_address():
    body = {"from": "Dana Lee <Dana@X.com>", "subject": "S", "body": "B", "simulate_classifier": "prose"}
    (r,) = run("normalize_demo_email", input=[{"body": body}])["items"]
    assert (r["from_name"], r["from_email"], r["simulate"]) == ("Dana Lee", "dana@x.com", "prose")
    (bare,) = run("normalize_demo_email", input=[{"body": {"from": "x@y.com"}}])["items"]
    assert bare["from_email"] == "x@y.com" and bare["from_name"] == ""


def test_build_digest_counts_today_only():
    rows = [{"Date": "2026-10-13", "Category": "Urgent", "Needs Reply": "TRUE", "Fallback": "FALSE", "From": "a", "Subject": "s", "Summary": "x"},
            {"Date": "2026-10-13", "Category": "Routine", "Needs Reply": "FALSE", "Fallback": "TRUE"},
            {"Date": "2026-10-12", "Category": "Urgent", "Needs Reply": "TRUE", "Fallback": "FALSE"}, {}]
    (d,) = run("build_digest", input=rows)["items"]
    assert d["total"] == 2 and d["counts"] == {"Urgent": 1, "Routine": 1} and d["needs_reply"] == 1 and d["fallbacks"] == 1
    assert d["urgent"] == [{"from": "a", "subject": "s", "summary": "x"}]
    assert run("build_digest", input=[{}])["items"][0]["total"] == 0


# --- support chatbot ----------------------------------------------------------------------------------------------

def test_normalize_message_web_and_telegram():
    web = {"body": {"message": "  hi   there ", "session_id": "s1", "history": [{"role": "assistant", "content": "x"}] * 9}}
    (w,) = run("normalize_message", input=[web])["items"]
    assert w["route"] == "process" and w["question"] == "hi there" and w["channel"] == "web" and len(w["history"]) == 6
    (e,) = run("normalize_message", input=[{"body": {"message": "  "}}])["items"]
    assert e["route"] == "reject_web" and e["error"] == "message is required"
    (big,) = run("normalize_message", input=[{"body": {"message": "x" * 1001}}])["items"]
    assert big["route"] == "reject_web"
    tg = {"message": {"text": "Where is my order?", "chat": {"id": 42}, "from": {"first_name": "Ana", "last_name": "K"}}}
    (t,) = run("normalize_message", input=[tg])["items"]
    assert (t["channel"], t["chat_id"], t["user_name"], t["route"]) == ("telegram", "42", "Ana K", "process")
    (cmd,) = run("normalize_message", input=[{"message": {**tg["message"], "text": "/start"}}])["items"]
    assert cmd["route"] == "ignore"


Q = {"channel": "web", "session_id": "s", "chat_id": "", "user_name": "", "question": "q?"}
SSE = ('event: sources\ndata: {"demo": true, "sources": [{"n": 1, "doc_id": 3, "filename": "refund_policy.md", "page": null, "chunk": 2, '
       '"text": "Annual plans are <b>refundable</b> within 14 days.", "score": 6.687}, '
       '{"n": 2, "filename": "faq.pdf", "page": 4, "text": "weak", "score": 1.2}]}\n\n'
       'event: token\ndata: {"text": "[DEMO MODE]"}\n\nevent: done\ndata: {}\n\n')


def parse_kb(res, env=None):
    return run("parse_kb_response", input=[res], nodes={"Normalize message": [Q]}, env=env)["items"][0]


def test_parse_kb_json_filters_by_min_score_and_escapes_markup():
    body = {"results": [{"text": "A <script>", "source": "a.md", "score": 0.9}, {"text": "B", "source": "b.md", "score": 0.2}]}
    r = parse_kb({"data": json.dumps(body)})
    assert r["has_context"] and [c["source"] for c in r["context"]] == ["a.md"] and r["best_score"] == 0.9
    assert "&lt;script&gt;" in r["context_text"] and "<script>" not in r["context_text"]
    assert parse_kb({"data": json.dumps(body)}, env={"KB_MIN_SCORE": "0.95"})["has_context"] is False


def test_parse_kb_understands_docs_rag_assistant_sse():
    r = parse_kb({"data": SSE}, env={"KB_MIN_SCORE": "4"})
    assert r["has_context"] and r["context"][0]["source"] == "refund_policy.md" and r["top_score"] == 6.687 and len(r["context"]) == 1
    both = parse_kb({"data": SSE}, env={"KB_MIN_SCORE": "1"})
    assert [c["source"] for c in both["context"]] == ["refund_policy.md", "faq.pdf, p.4"]


def test_parse_kb_error_empty_and_garbage_never_crash():
    assert "boom" in parse_kb({"error": {"message": "boom"}})["kb_error"] and parse_kb({"error": "x"})["has_context"] is False
    assert parse_kb({"data": ""})["has_context"] is False
    assert parse_kb({"data": "<html>502</html>"})["has_context"] is False
    bad = parse_kb({"data": "{not json"})
    assert bad["has_context"] is False and bad["kb_error"]


KB_OK = {**Q, "has_context": True, "kb_error": "", "best_score": 0.9, "min_score": 0.4, "history": [{"role": "user", "content": "hi"}],
         "context": [{"n": 1, "source": "faq/refunds.md", "text": "t", "score": 0.9}]}


def decide(llm, kb=None, env=None):
    return run("decide_reply", input=[llm], nodes={"Parse KB response": [kb or KB_OK]}, env=env)["items"][0]


def test_decide_reply_answers_only_when_valid_answerable_and_confident():
    r = decide({"output": {"answer": "30 days.", "answerable": True, "confidence": 0.9}})
    assert r["answered"] and r["escalate"] is False and r["reply_text"] == "30 days." and r["sources"] == ["faq/refunds.md"]


@pytest.mark.parametrize("llm,reason", [
    ({"output": {"answer": "maybe", "answerable": True, "confidence": 0.3}}, "low confidence"),
    ({"output": {"answer": "", "answerable": False, "confidence": 0.9}}, "does not answer"),
    ({"output": {"answer": "x", "answerable": True, "confidence": 7}}, "invalid"),
    ({"output": {"answer": "  ", "answerable": True, "confidence": 0.9}}, "invalid"),
    ({"output": "I think the answer is 30 days"}, "invalid"),
    ({"error": "overloaded"}, "invalid"),
])
def test_decide_reply_escalates_otherwise(llm, reason):
    r = decide(llm)
    assert r["escalate"] is True and r["answered"] is False and r["reply_text"].startswith("I'm not sure") and reason in r["escalate_reason"]
    assert "Customer: hi" in r["slack_text"] and "Customer: q?" in r["slack_text"] and r["sources"] == []


def test_decide_reply_without_context_never_uses_the_model_output():
    r = decide({"output": {"answer": "made up", "answerable": True, "confidence": 1}}, kb={**KB_OK, "has_context": False, "context": []})
    assert r["escalate"] and "made up" not in r["reply_text"] and "no passage scored above 0.4" in r["escalate_reason"]
    r = decide({}, kb={**KB_OK, "has_context": False, "kb_error": "timeout", "best_score": 0})
    assert "knowledge base unavailable: timeout" in r["escalate_reason"]
    r = decide({}, kb={**KB_OK, "has_context": False, "best_score": 0})
    assert r["escalate_reason"] == "no relevant context found"


def test_decide_reply_confidence_threshold_is_configurable():
    llm = {"output": {"answer": "ok", "answerable": True, "confidence": 0.5}}
    assert decide(llm)["escalate"] is True
    assert decide(llm, env={"ANSWER_MIN_CONFIDENCE": "0.4"})["escalate"] is False


# --- lead intake ----------------------------------------------------------------------------------------------------

def lead(body, headers=None, env=None):
    return run("validate_lead", input=[{"body": body, "headers": headers or {}}], env=env)["items"][0]


def test_validate_lead_normalises():
    r = lead({"name": "  Dana   Whitfield ", "email": " Dana@BigCo.COM ", "phone": "+1 (555) 010-0199", "company": " BigCo ", "message": " hi "})
    assert r["ok"] and r["lead"]["email"] == "dana@bigco.com" and r["lead"]["firstname"] == "Dana" and r["lead"]["lastname"] == "Whitfield"
    assert r["lead"]["phone"] == "+15550100199" and r["lead"]["company"] == "BigCo" and r["lead"]["source"] == "web-form"


@pytest.mark.parametrize("body,errors", [
    ({}, ["email is missing or invalid", "name is required"]),
    ({"name": "A", "email": "not-an-email"}, ["email is missing or invalid"]),
    ({"name": "A", "email": "a@b.com", "phone": "12"}, ["phone is invalid"]),
])
def test_validate_lead_rejects_with_422(body, errors):
    r = lead(body)
    assert r["ok"] is False and r["status_code"] == 422 and r["errors"] == errors


def test_validate_lead_shared_secret():
    body = {"name": "A", "email": "a@b.com"}
    env = {"LEAD_WEBHOOK_SECRET": "s3cret"}
    assert lead(body, env=env)["status_code"] == 401
    assert lead(body, headers={"x-webhook-secret": "wrong"}, env=env)["status_code"] == 401
    assert lead(body, headers={"x-webhook-secret": "s3cret"}, env=env)["ok"] is True
    assert lead(body)["ok"] is True  # no secret configured = open (documented)


def test_dedupe_check_window():
    inp = {"ok": True, "lead": {"email": "a@b.com"}}
    inside = {"leads": {"a@b.com": {"ts": int(time.time() * 1000), "crm_id": "7"}}}  # seen just now
    old = {"leads": {"a@b.com": {"ts": 1_000_000_000_000, "crm_id": "7"}}}  # year 2001: always outside
    assert run("dedupe_check", input=[inp], static=inside)["items"][0]["duplicate"] is True
    assert run("dedupe_check", input=[inp], static=inside)["items"][0]["previous_crm_id"] == "7"
    assert run("dedupe_check", input=[inp], static=old)["items"][0]["duplicate"] is False
    assert run("dedupe_check", input=[inp])["items"][0]["duplicate"] is False
    assert run("dedupe_check", input=[inp], static=inside, env={"DEDUPE_WINDOW_MIN": "0"})["items"][0]["duplicate"] is False


def score(llm, env=None):
    return run("validate_score", input=[llm], nodes={"Dedupe check": [{"lead": {"email": "a@b.com"}}]}, env=env)["items"][0]


@pytest.mark.parametrize("value,tier", [(100, "hot"), (70, "hot"), (69.6, "hot"), (69, "warm"), (40, "warm"), (39, "cold"), (0, "cold")])
def test_score_tier_is_derived_in_code(value, tier):
    r = score({"output": {"score": value, "reason": "why", "tier": "cold"}})  # a "tier" from the model is ignored
    assert r["tier"] == tier and r["scoring_failed"] is False and r["score"] == round(value)


@pytest.mark.parametrize("bad", [{"score": "high", "reason": "x"}, {"score": 101, "reason": "x"}, {"score": -1, "reason": "x"},
                                 {"score": 50}, {"score": 50, "reason": " "}, "no json", None, {"error": "429"}])
def test_invalid_score_becomes_unscored_not_lost(bad):
    r = score({"output": bad} if not (isinstance(bad, dict) and "error" in bad) else bad)
    assert r["tier"] == "unscored" and r["scoring_failed"] is True and r["score"] == 0 and r["lead"]["email"] == "a@b.com"


def test_score_thresholds_are_configurable():
    assert score({"output": {"score": 55, "reason": "r"}}, env={"LEAD_HOT_SCORE": "50"})["tier"] == "hot"


def test_build_crm_payload_drops_empty_values():
    d = {"lead": {"email": "a@b.com", "firstname": "A", "lastname": "", "company": "", "phone": "", "message": "m", "source": "web-form"},
         "score": 80, "tier": "hot", "reason": "r"}
    props = run("build_crm_payload", input=[d])["items"][0]["crm_properties"]
    assert props == {"email": "a@b.com", "firstname": "A", "message": "m", "lead_source": "web-form", "ai_lead_score": 80,
                     "ai_lead_tier": "hot", "ai_lead_reason": "r"}
    assert run("build_crm_payload", input=[{**d, "score": 0}])["items"][0]["crm_properties"]["ai_lead_score"] == 0  # zero is a real score


def test_finalize_lead_remembers_the_lead_and_prunes_old_entries():
    merged = {"lead": {"email": "a@b.com", "name": "A", "company": "", "source": "x"}, "score": 80, "tier": "hot", "reason": "r",
              "scoring_failed": False, "crm_contact_id": ""}
    stale = {"leads": {"old@x.com": {"ts": 1, "crm_id": "1"}}}
    out = run("finalize_lead", input=[{"id": "55"}], nodes={"Merge lookup result": [merged]}, static=stale)
    assert out["items"][0]["status"] == "created" and out["items"][0]["crm_id"] == "55"
    assert list(out["staticData"]["leads"]) == ["a@b.com"]
    merged["crm_contact_id"] = "55"
    assert run("finalize_lead", input=[{"id": "55"}], nodes={"Merge lookup result": [merged]})["items"][0]["status"] == "updated"


def test_merge_crm_lookup():
    payload = {"lead": {}, "crm_properties": {"a": 1}}
    found = run("merge_crm_lookup", input=[{"total": 1, "results": [{"id": "9"}]}], nodes={"Build CRM payload": [payload]})
    assert found["items"][0]["crm_contact_id"] == "9"
    none = run("merge_crm_lookup", input=[{"total": 0, "results": []}], nodes={"Build CRM payload": [payload]})
    assert none["items"][0]["crm_contact_id"] == ""


# --- error workflow ---------------------------------------------------------------------------------------------------

def test_format_error_alert():
    execution = {"workflow": {"id": "1", "name": "My flow"},
                 "execution": {"id": "5", "url": "http://n8n/workflow/1/executions/5", "mode": "webhook", "lastNodeExecuted": "Create contact",
                               "error": {"message": "503 Service Unavailable"}}}
    (a,) = run("format_error_alert", input=[execution])["items"]
    for needle in ("My flow", "Create contact", "503 Service Unavailable", "http://n8n/workflow/1/executions/5", "webhook"):
        assert needle in a["text"]
    trig = {"workflow": {"name": "Gmail flow"}, "trigger": {"error": {"message": "invalid_grant", "node": {"name": "Gmail Trigger"}}}}
    (b,) = run("format_error_alert", input=[trig])["items"]
    assert "Gmail Trigger" in b["text"] and "invalid_grant" in b["text"] and "no execution URL" in b["text"]
