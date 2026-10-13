import pytest
from app.main import CATEGORIES, app
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    client.post("/admin/reset")


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


# --- CRM (HubSpot v3 style) --------------------------------------------------

def create(email="ana@example.com", **props):
    return client.post("/crm/v3/objects/contacts", json={"properties": {"email": email, **props}})


def search(email):
    body = {"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}]}
    return client.post("/crm/v3/objects/contacts/search", json=body).json()


def test_crm_create_search_update():
    r = create("Ana@Example.com", firstname="Ana")
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["properties"]["email"] == "ana@example.com"  # normalised
    found = search("ANA@example.com")
    assert found["total"] == 1 and found["results"][0]["id"] == cid
    u = client.patch(f"/crm/v3/objects/contacts/{cid}", json={"properties": {"ai_lead_score": 80}})
    assert u.status_code == 200 and u.json()["properties"]["ai_lead_score"] == 80
    assert client.get(f"/crm/v3/objects/contacts/{cid}").json()["properties"]["firstname"] == "Ana"


def test_crm_duplicate_missing_email_and_unknown_id():
    create()
    assert create().status_code == 409
    assert client.post("/crm/v3/objects/contacts", json={"properties": {}}).status_code == 400
    assert client.patch("/crm/v3/objects/contacts/999", json={"properties": {}}).status_code == 404
    assert search("nobody@example.com")["total"] == 0


def test_chaos_fails_next_n_crm_calls_then_recovers():
    assert client.post("/admin/chaos", json={"crm": 2}).json() == {"crm": 2}
    assert create().status_code == 503
    assert client.post("/crm/v3/objects/contacts/search", json={"filterGroups": []}).status_code == 503
    assert create().status_code == 201


# --- knowledge base ----------------------------------------------------------

def kb(question, **extra):
    return client.post("/kb/search", json={"question": question, **extra}).json()["results"]


def test_kb_finds_the_right_entry():
    top = kb("What is your refund policy?")[0]
    assert top["id"] == "faq-refunds" and top["score"] >= 0.9
    assert kb("How do I reset my password?")[0]["id"] == "faq-password"


def test_kb_unrelated_question_has_no_results_and_partial_match_scores_low():
    assert kb("What is the weather in Paris tomorrow?") == []
    partial = kb("Do you offer student discounts?")
    assert all(r["score"] < 0.4 for r in partial)  # below the workflow's default KB_MIN_SCORE


def test_kb_top_k_and_validation():
    assert len(kb("plan pricing refund password support", top_k=2)) <= 2
    assert client.post("/kb/search", json={"question": ""}).status_code == 422


# --- fake classifier (shape and fallbacks the workflow validator depends on) --

def classify(subject, body="", **extra):
    r = client.post("/classify", json={"from_email": "bo@x.com", "from_name": "Bo Lee", "subject": subject, "body": body, **extra})
    assert r.status_code == 200
    return r.json()["output"]


@pytest.mark.parametrize("subject,body,expected", [
    ("Production is down", "Customers cannot log in, fix ASAP", "Urgent"),
    ("Invoice 4411", "Payment is overdue", "Billing"),
    ("Contract draft", "Please review the proposal", "Client"),
    ("Meeting", "Please confirm the deadline", "Important"),
    ("Big sale", "Limited time, 50% off, click here", "Low Value"),
    ("Monthly newsletter", "Release notes inside", "Informational"),
    ("Hello", "Just saying hi", "Routine"),
])
def test_classifier_categories(subject, body, expected):
    out = classify(subject, body)
    assert out["category"] == expected and out["category"] in CATEGORIES
    assert 0 <= out["confidence"] <= 1


def test_classifier_drafts_only_when_a_reply_makes_sense():
    assert classify("Production is down", "asap")["reply_draft"].startswith("Hi Bo,")
    assert classify("Monthly newsletter", "digest")["needs_reply"] is False
    assert classify("Monthly newsletter", "digest")["reply_draft"] == ""


def test_classifier_can_simulate_bad_llm_output():
    assert classify("Hello", simulate="invalid_category")["category"] == "Spam"
    assert "confidence" not in classify("Hello", simulate="missing_field")
    assert isinstance(classify("Hello", simulate="prose"), str)


def test_lead_scoring_ranks_good_leads_above_spam():
    good = {"name": "Dana", "email": "dana@bigco.com", "company": "BigCo", "phone": "+1 555 0100",
            "message": "We need a quote for automating our onboarding. Budget is 15k, we want to launch next week."}
    spam = {"name": "Sam", "email": "sam@gmail.com", "message": "Cheap SEO backlinks and guest post offers"}
    g = client.post("/lead/score", json=good).json()["output"]
    s = client.post("/lead/score", json=spam).json()["output"]
    assert g["score"] >= 70 and s["score"] < 40 and 0 <= s["score"] <= 100
    assert isinstance(client.post("/lead/score", json={**good, "simulate": "invalid"}).json()["output"]["score"], str)


# --- fake Gmail / Slack / Sheets and the request log -----------------------------

def test_gmail_labels_drafts_and_no_send_endpoint():
    labels = client.get("/gmail/labels").json()
    assert {f"AI/{c}" for c in CATEGORIES} <= {x["name"] for x in labels}
    assert client.post("/gmail/messages/m1/labels", json={"labelIds": ["Label_1"]}).status_code == 200
    d = client.post("/gmail/drafts", json={"to": "a@b.com", "subject": "Re: x", "body": "hi"})
    assert d.status_code == 201 and d.json()["sent"] is False
    assert len(client.get("/gmail/drafts").json()) == 1
    assert client.post("/gmail/messages/send", json={}).status_code in (404, 405)


def test_slack_and_sheets_roundtrip():
    assert client.post("/slack", json={"text": "hello", "channel": "#ops"}).json() == {"ok": True}
    assert client.get("/slack/messages").json()[0]["text"] == "hello"
    client.post("/sheets/triage/rows", json={"Category": "Urgent"})
    assert client.get("/sheets/triage/rows").json() == [{"Category": "Urgent"}]
    assert client.get("/sheets/empty/rows").json() == []


def test_request_log_and_state_summary_and_reset():
    client.post("/slack", json={"text": "x"})
    log = client.get("/log").json()
    assert log[-1]["path"] == "/slack" and log[-1]["method"] == "POST" and '"text"' in log[-1]["body"]
    assert client.get("/state").json()["slack_messages"] == 1
    client.post("/admin/reset")
    assert client.get("/state").json()["slack_messages"] == 0 and client.get("/log").json() == []
