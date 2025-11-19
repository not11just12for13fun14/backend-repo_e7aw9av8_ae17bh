"""
Database Schemas for the Event Ticketing SaaS

Each Pydantic model below corresponds to a MongoDB collection.
Collection name is the lowercase of the class name (e.g., Event -> "event").

We store events, ticket types, orders, and attendees. Attendees carry a
unique QR token used for on-site check-in.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class Event(BaseModel):
    title: str = Field(..., description="Event name")
    description: Optional[str] = Field(None, description="Event description")
    venue: Optional[str] = Field(None, description="Venue or location")
    start_at: Optional[datetime] = Field(None, description="Event start datetime (ISO)")
    end_at: Optional[datetime] = Field(None, description="Event end datetime (ISO)")
    currency: str = Field("USD", description="Default currency for pricing")
    status: str = Field("draft", description="draft | published | archived")


class Tickettype(BaseModel):
    event_id: str = Field(..., description="Related event id")
    name: str = Field(..., description="Ticket name (e.g., General Admission)")
    price: float = Field(..., ge=0, description="Unit price")
    quantity_total: int = Field(..., ge=0, description="Total inventory")
    quantity_sold: int = Field(0, ge=0, description="Sold count")


class Order(BaseModel):
    event_id: str = Field(..., description="Related event id")
    ticket_type_id: str = Field(..., description="Ticket type id")
    buyer_name: str = Field(..., description="Buyer full name")
    buyer_email: str = Field(..., description="Buyer email")
    quantity: int = Field(..., ge=1, description="Quantity purchased")
    total_amount: float = Field(..., ge=0, description="Total price charged")
    status: str = Field("paid", description="paid | refunded | canceled")


class Attendee(BaseModel):
    event_id: str = Field(...)
    order_id: str = Field(...)
    ticket_type_id: str = Field(...)
    name: str = Field(...)
    email: Optional[str] = Field(None)
    qr_token: str = Field(..., description="Unique token encoded in QR for check-in")
    checked_in: bool = Field(False)
    checked_in_at: Optional[datetime] = Field(None)
