import os
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
import secrets

from database import db, create_document, get_documents

app = FastAPI(title="Event Ticketing SaaS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helpers
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


def oid_str(oid):
    return str(oid) if isinstance(oid, ObjectId) else oid


@app.get("/")
def read_root():
    return {"message": "Event Ticketing SaaS Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"

    return response


# Schemas for requests
class EventIn(BaseModel):
    title: str
    description: Optional[str] = None
    venue: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    currency: str = "USD"
    status: str = "draft"  # draft | published | archived


class TicketTypeIn(BaseModel):
    event_id: str
    name: str
    price: float
    quantity_total: int


class OrderIn(BaseModel):
    event_id: str
    ticket_type_id: str
    buyer_name: str
    buyer_email: str
    quantity: int


# Endpoints
@app.post("/api/events")
def create_event(payload: EventIn):
    data = payload.model_dump()
    event_id = create_document("event", data)
    return {"id": event_id, **data}


@app.get("/api/events")
def list_events():
    docs = get_documents("event")
    for d in docs:
        d["id"] = oid_str(d.pop("_id", None))
    return docs


@app.post("/api/tickets")
def create_ticket_type(payload: TicketTypeIn):
    # validate event exists
    event = db["event"].find_one({"_id": ObjectId(payload.event_id)})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    doc = {
        "event_id": payload.event_id,
        "name": payload.name,
        "price": payload.price,
        "quantity_total": payload.quantity_total,
        "quantity_sold": 0,
    }
    tid = create_document("tickettype", doc)
    return {"id": tid, **doc}


@app.get("/api/tickets")
def list_ticket_types(event_id: Optional[str] = None):
    filt = {"event_id": event_id} if event_id else {}
    docs = get_documents("tickettype", filt)
    for d in docs:
        d["id"] = oid_str(d.pop("_id", None))
    return docs


@app.post("/api/orders")
def create_order(payload: OrderIn):
    # verify ticket
    tt = db["tickettype"].find_one({"_id": ObjectId(payload.ticket_type_id)})
    if not tt:
        raise HTTPException(status_code=404, detail="Ticket type not found")

    # inventory check
    remaining = int(tt.get("quantity_total", 0)) - int(tt.get("quantity_sold", 0))
    if payload.quantity > remaining:
        raise HTTPException(status_code=400, detail="Not enough inventory")

    total_amount = float(tt.get("price", 0)) * payload.quantity

    order_doc = {
        "event_id": payload.event_id,
        "ticket_type_id": payload.ticket_type_id,
        "buyer_name": payload.buyer_name,
        "buyer_email": payload.buyer_email,
        "quantity": payload.quantity,
        "total_amount": total_amount,
        "status": "paid",
    }
    order_id = create_document("order", order_doc)

    # generate attendees with unique qr tokens
    attendees = []
    for i in range(payload.quantity):
        qr_token = secrets.token_urlsafe(16)
        att_doc = {
            "event_id": payload.event_id,
            "order_id": order_id,
            "ticket_type_id": payload.ticket_type_id,
            "name": payload.buyer_name,
            "email": payload.buyer_email,
            "qr_token": qr_token,
            "checked_in": False,
            "checked_in_at": None,
        }
        aid = create_document("attendee", att_doc)
        attendees.append({"id": aid, **att_doc})

    # increment quantity_sold atomically
    db["tickettype"].update_one(
        {"_id": ObjectId(payload.ticket_type_id)},
        {"$inc": {"quantity_sold": payload.quantity}}
    )

    return {"order_id": order_id, "total_amount": total_amount, "attendees": attendees}


@app.get("/api/attendees")
def list_attendees(event_id: Optional[str] = None, order_id: Optional[str] = None):
    filt = {}
    if event_id:
        filt["event_id"] = event_id
    if order_id:
        filt["order_id"] = order_id
    docs = get_documents("attendee", filt)
    for d in docs:
        d["id"] = oid_str(d.pop("_id", None))
    return docs


@app.post("/api/checkin/{qr_token}")
def check_in(qr_token: str):
    att = db["attendee"].find_one({"qr_token": qr_token})
    if not att:
        raise HTTPException(status_code=404, detail="Attendee not found")
    if att.get("checked_in"):
        return {"status": "already_checked_in", "checked_in_at": att.get("checked_in_at")}

    db["attendee"].update_one(
        {"_id": att["_id"]},
        {"$set": {"checked_in": True, "checked_in_at": datetime.now(timezone.utc)}}
    )

    return {"status": "checked_in", "attendee_id": oid_str(att["_id"]) }


# Expose schemas for admin viewer
@app.get("/schema")
def get_schema_definitions():
    try:
        from schemas import Event, Tickettype, Order, Attendee
        return {
            "event": Event.model_json_schema(),
            "tickettype": Tickettype.model_json_schema(),
            "order": Order.model_json_schema(),
            "attendee": Attendee.model_json_schema(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
