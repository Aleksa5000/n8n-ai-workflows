"""Mock services for the n8n demo mode: no accounts, no API keys, no LLM.

Everything the workflows would normally send to Gmail, Slack, Google Sheets, a CRM, a
knowledge base or an LLM has a fake stand-in here. All state lives in memory and every
request is recorded, so you can see exactly what n8n did (GET /log, GET /state).
"""
import re
from collections import deque
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="n8n-ai-workflows mock services", version="1.0.0")

CATEGORIES = ["Urgent", "Important", "Client", "Billing", "Routine", "Informational", "Low Value"]
LOG_SKIP = ("/health", "/log", "/state", "/docs", "/openapi.json", "/admin/reset")


def fresh_state() -> dict[str, Any]:
    return {"contacts": {}, "next_contact_id": 101, "drafts": [], "labels_applied": [], "slack": [],
            "sheets": {}, "chaos": {"crm": 0}}


STATE = fresh_state()
LOG: deque = deque(maxlen=500)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@app.middleware("http")
async def record(request: Request, call_next):
    body = await request.body()
    response = await call_next(request)
    if not request.url.path.startswith(LOG_SKIP):
        LOG.append({"ts": now(), "method": request.method, "path": request.url.path,
                    "status": response.status_code, "body": body.decode("utf-8", "replace")[:1500]})
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/log")
def get_log(limit: int = 50):
    return list(LOG)[-limit:]


@app.get("/state")
def get_state():
    s = STATE
    return {"contacts": len(s["contacts"]), "drafts": len(s["drafts"]), "labels_applied": len(s["labels_applied"]),
            "slack_messages": len(s["slack"]), "sheets": {k: len(v) for k, v in s["sheets"].items()},
            "chaos": s["chaos"], "log_entries": len(LOG)}


@app.post("/admin/reset")
def reset():
    STATE.clear()
    STATE.update(fresh_state())
    LOG.clear()
    return {"status": "reset"}


class Chaos(BaseModel):
    crm: int = Field(0, ge=0, le=50, description="make the next N CRM calls fail with HTTP 503")


@app.post("/admin/chaos")
def set_chaos(c: Chaos):
    STATE["chaos"]["crm"] = c.crm
    return STATE["chaos"]


# ----------------------------------------------------------------------------- CRM (HubSpot v3 style)

class ContactIn(BaseModel):
    properties: dict[str, Any]


def crm_chaos() -> None:
    if STATE["chaos"]["crm"] > 0:
        STATE["chaos"]["crm"] -= 1
        raise HTTPException(503, "CRM temporarily unavailable (injected failure)")


def contact_out(c: dict) -> dict:
    return {"id": c["id"], "properties": c["properties"], "createdAt": c["createdAt"], "updatedAt": c["updatedAt"]}


@app.post("/crm/v3/objects/contacts", status_code=201)
def create_contact(body: ContactIn):
    crm_chaos()
    email = str(body.properties.get("email", "")).strip().lower()
    if not email:
        raise HTTPException(400, "properties.email is required")
    if any(c["properties"].get("email", "").lower() == email for c in STATE["contacts"].values()):
        raise HTTPException(409, f"Contact already exists: {email}")
    cid = str(STATE["next_contact_id"])
    STATE["next_contact_id"] += 1
    contact = {"id": cid, "properties": {**body.properties, "email": email}, "createdAt": now(), "updatedAt": now()}
    STATE["contacts"][cid] = contact
    return contact_out(contact)


class Filter(BaseModel):
    propertyName: str
    operator: str = "EQ"
    value: str = ""


class FilterGroup(BaseModel):
    filters: list[Filter]


class SearchIn(BaseModel):
    filterGroups: list[FilterGroup] = []
    limit: int = 10


@app.post("/crm/v3/objects/contacts/search")
def search_contacts(body: SearchIn):
    crm_chaos()

    def matches(c: dict, g: FilterGroup) -> bool:
        return all(f.operator == "EQ" and str(c["properties"].get(f.propertyName, "")).lower() == f.value.lower()
                   for f in g.filters)

    found = [c for c in STATE["contacts"].values() if any(matches(c, g) for g in body.filterGroups)]
    return {"total": len(found), "results": [contact_out(c) for c in found[: body.limit]]}


@app.patch("/crm/v3/objects/contacts/{contact_id}")
def update_contact(contact_id: str, body: ContactIn):
    crm_chaos()
    c = STATE["contacts"].get(contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    c["properties"].update(body.properties)
    c["updatedAt"] = now()
    return contact_out(c)


@app.get("/crm/v3/objects/contacts/{contact_id}")
def get_contact(contact_id: str):
    c = STATE["contacts"].get(contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    return contact_out(c)


@app.get("/crm/v3/objects/contacts")
def list_contacts():
    return {"results": [contact_out(c) for c in STATE["contacts"].values()]}


# ----------------------------------------------------------------------------- knowledge base

KB = [
    {"id": "faq-refunds", "title": "Refund policy", "source": "faq/refunds.md",
     "text": "We offer a full refund within 30 days of purchase, no questions asked. After 30 days, refunds are "
             "prorated for annual plans only. Refunds go back to the original payment method within 5 to 7 business days."},
    {"id": "faq-cancel", "title": "Cancel a subscription", "source": "faq/cancel.md",
     "text": "You can cancel at any time under Settings > Billing > Cancel subscription. Your workspace stays active "
             "until the end of the paid period and your data is kept for 30 days afterwards."},
    {"id": "faq-password", "title": "Reset your password", "source": "faq/password.md",
     "text": "To reset your password, open the login page and choose Forgot password. We email a reset link that is "
             "valid for 60 minutes. If the email does not arrive, check spam or contact support."},
    {"id": "faq-hours", "title": "Support hours", "source": "faq/support-hours.md",
     "text": "Support is available Monday to Friday, 09:00 to 17:00 CET. Customers on the Business plan also have a "
             "24/7 on-call line for critical incidents."},
    {"id": "faq-pricing", "title": "Plans and pricing", "source": "faq/pricing.md",
     "text": "Starter costs 19 euro per user per month, Team costs 49 euro per user per month and Business costs 99 euro "
             "per user per month. Paying yearly saves 20 percent. All plans include a 14 day free trial."},
    {"id": "faq-privacy", "title": "Data privacy and GDPR", "source": "faq/privacy.md",
     "text": "Customer data is stored in EU data centres and encrypted at rest and in transit. We are GDPR compliant "
             "and sign a data processing agreement (DPA) on request. You can export or delete your data at any time."},
    {"id": "faq-integrations", "title": "Integrations", "source": "faq/integrations.md",
     "text": "Acme Cloud integrates with Slack, Gmail, Google Sheets, Zapier and n8n. A REST API and webhooks are "
             "available on the Team and Business plans."},
    {"id": "faq-invoices", "title": "Invoices and billing address", "source": "faq/invoices.md",
     "text": "Invoices are emailed on every billing date and can be downloaded under Settings > Billing. To change the "
             "billing address or add a VAT number, edit the company details before the next invoice is issued."},
]
STOP = set("the and for you your are was what how can does did do have has with this that from about when where who why "
           "which would could should please tell any there their they them our out not but its it's i'm a an of to in on "
           "is it be as at by or if me my we us".split())


def tokens(text: str) -> set[str]:
    words = (w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", text.lower()))
    return {w for w in words if len(w) > 2 and w not in STOP}


class KbQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")  # docs-rag-assistant uses the same {"question": ...} body
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(4, ge=1, le=10)


@app.post("/kb/search")
def kb_search(q: KbQuery):
    """Score = share of the question's meaningful words found in the entry (0..1)."""
    qt = tokens(q.question)
    scored = []
    for e in KB:
        score = len(qt & tokens(e["title"] + " " + e["text"])) / len(qt) if qt else 0.0
        if score > 0:
            scored.append({**e, "score": round(score, 3)})
    scored.sort(key=lambda e: e["score"], reverse=True)
    return {"query": q.question, "results": scored[: q.top_k]}


# ----------------------------------------------------------------------------- fake classifier / scorer (no LLM)

class EmailIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    from_email: str = ""
    from_name: str = ""
    subject: str = ""
    body: str = ""
    simulate: str | None = Field(None, description="invalid_category | prose | missing_field: emit bad 'LLM' output")


RULES = [
    ("Urgent", r"\b(urgent|asap|immediately|outage|emergency|critical|is down|right now)\b"),
    ("Billing", r"\b(invoice|payment|receipt|refund|billing|overdue|charged)\b"),
    ("Client", r"\b(contract|proposal|statement of work|milestone|deliverable|our project)\b"),
    ("Important", r"\b(deadline|meeting|interview|approval|action required|please confirm)\b"),
    ("Low Value", r"\b(unsubscribe|% off|limited time|special offer|click here|webinar)\b"),
    ("Informational", r"\b(newsletter|fyi|announcement|release notes|digest|for your information)\b"),
]
DRAFTS = {
    "Urgent": "Thanks for flagging this. I am looking into it right now and will update you within the hour.",
    "Important": "Thanks for the heads-up. I have noted the date and will confirm shortly.",
    "Client": "Thanks for your message. I will review the details and come back to you with next steps today.",
    "Billing": "Thanks for getting in touch. I am checking the billing details and will reply as soon as I have them.",
    "Routine": "Thanks for your email. I will get back to you shortly.",
}


@app.post("/classify")
def classify(e: EmailIn):
    """LLM-free stand-in for the Claude classification step. Returns the same shape the chain node returns."""
    text = f"{e.subject}\n{e.body}".lower()
    category, matched = "Routine", ""
    for cat, pattern in RULES:
        m = re.search(pattern, text)
        if m:
            category, matched = cat, m.group(0)
            break
    first = (e.from_name or e.from_email.split("@")[0] or "there").split()[0].title()
    needs_reply = category in DRAFTS and (category != "Routine" or "?" in e.body)
    out = {
        "category": category,
        "confidence": 0.5 if category == "Routine" and not matched else 0.9,
        "summary": re.sub(r"\s+", " ", e.body).strip()[:200] or e.subject[:200],
        "needs_reply": needs_reply,
        "reply_draft": f"Hi {first},\n\n{DRAFTS[category]}\n\nBest regards" if needs_reply else "",
        "reason": f"keyword '{matched}'" if matched else "no strong signal",
    }
    if e.simulate == "invalid_category":
        out["category"] = "Spam"
    elif e.simulate == "missing_field":
        del out["confidence"]
    elif e.simulate == "prose":
        return {"output": f"Sure! I think this email is {category}."}
    return {"output": out}


FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "proton.me", "aol.com"}


class LeadIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    email: str = ""
    company: str = ""
    phone: str = ""
    message: str = ""
    simulate: str | None = None


@app.post("/lead/score")
def lead_score(lead: LeadIn):
    """LLM-free stand-in for the Claude lead-scoring step (returns the chain-node output shape)."""
    msg = lead.message.lower()
    score, signals = 10, []

    def add(points: int, label: str, cond: bool) -> None:
        nonlocal score
        if cond:
            score += points
            signals.append(f"{label} ({points:+d})")

    add(25, "business email", lead.email.split("@")[-1].lower() not in FREE_MAIL and "@" in lead.email)
    add(15, "company given", bool(lead.company.strip()))
    add(20, "budget or pricing language", bool(re.search(r"budget|quote|pricing|proposal|contract|retainer|per month|[$€]\s?\d", msg)))
    add(15, "timeline mentioned", bool(re.search(r"asap|urgent|this week|next week|timeline|deadline|launch|q[1-4]\b", msg)))
    add(10, "detailed message", len(lead.message) >= 120)
    add(5, "phone given", bool(lead.phone.strip()))
    add(-40, "spam wording", bool(re.search(r"seo|backlink|crypto|casino|guest post|free money", msg)))
    add(-20, "student or job seeker", bool(re.search(r"student|homework|thesis|internship|job opening", msg)))
    score = max(0, min(100, score))
    if lead.simulate == "invalid":
        return {"output": {"score": "very high", "reason": ""}}
    return {"output": {"score": score, "intent": "inbound enquiry", "reason": "; ".join(signals) or "no strong signals"}}


# ----------------------------------------------------------------------------- fake Gmail / Slack / Sheets

@app.get("/gmail/labels")
def gmail_labels():
    """Top-level array, so n8n turns it into one item per label (like the Gmail node does)."""
    return [{"id": f"Label_{i}", "name": f"AI/{c}", "type": "user"} for i, c in enumerate(CATEGORIES, start=1)] + [
        {"id": "INBOX", "name": "INBOX", "type": "system"}, {"id": "UNREAD", "name": "UNREAD", "type": "system"}]


class LabelIn(BaseModel):
    labelIds: list[str]


@app.post("/gmail/messages/{message_id}/labels")
def gmail_add_label(message_id: str, body: LabelIn):
    STATE["labels_applied"].append({"message_id": message_id, "label_ids": body.labelIds})
    return {"id": message_id, "labelIds": body.labelIds}


class DraftIn(BaseModel):
    thread_id: str = ""
    to: str
    subject: str
    body: str


@app.post("/gmail/drafts", status_code=201)
def gmail_create_draft(d: DraftIn):
    """Only drafts exist in this fake: there is deliberately no 'send' endpoint."""
    draft = {"id": f"draft-{len(STATE['drafts']) + 1}", "sent": False, **d.model_dump()}
    STATE["drafts"].append(draft)
    return draft


@app.get("/gmail/drafts")
def gmail_list_drafts():
    return STATE["drafts"]


class SlackIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str
    channel: str = "#demo"


@app.post("/slack")
def slack_post(m: SlackIn):
    """Stands in for a Slack incoming webhook."""
    STATE["slack"].append({"ts": now(), **m.model_dump()})
    return {"ok": True}


@app.get("/slack/messages")
def slack_messages():
    return STATE["slack"]


@app.post("/sheets/{sheet}/rows", status_code=201)
def sheets_append(sheet: str, row: dict[str, Any]):
    STATE["sheets"].setdefault(sheet, []).append(row)
    return {"appended": 1, "row_number": len(STATE["sheets"][sheet]) + 1}


@app.get("/sheets/{sheet}/rows")
def sheets_rows(sheet: str):
    """Top-level array, so n8n turns it into one item per row (like the Google Sheets 'read' operation)."""
    return STATE["sheets"].get(sheet, [])
