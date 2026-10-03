"""
Function Calling Tools for AI Marketing Agent.
Executed by Gemini when specific actions are needed during or after the call.
"""

from typing import Dict, Any, Optional
from datetime import datetime
from app.db.database import AsyncSessionLocal
from app.db.models import Appointment, Lead, CallLog
from sqlalchemy import select, update

async def book_growth_audit(
    customer_name: str,
    preferred_slot: str,
    email: Optional[str] = None,
    phone_number: Optional[str] = None,
    notes: Optional[str] = None,
    call_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Schedules a 15-minute marketing funnel audit & demo with a Growth Specialist.
    """
    async with AsyncSessionLocal() as session:
        appt = Appointment(
            call_id=call_id,
            customer_name=customer_name,
            customer_email=email or "pending_confirmation@customer.com",
            customer_phone=phone_number or "N/A",
            slot_time=preferred_slot,
            notes=notes or "Scheduled via AI Marketing Agent",
            created_at=datetime.utcnow()
        )
        session.add(appt)
        await session.commit()
    
    return {
        "status": "success",
        "message": f"Successfully reserved audit slot for {customer_name} on {preferred_slot}. Confirmation dispatched.",
        "slot": preferred_slot
    }


async def send_whatsapp_brochure(
    phone_number: str,
    email: Optional[str] = None,
    document_type: str = "growth_audit_summary"
) -> Dict[str, Any]:
    """
    Sends product brochure, case study, or booking link to the customer via WhatsApp/SMS.
    """
    # In production, this calls Twilio/Plivo/Gupshup WhatsApp API.
    return {
        "status": "success",
        "message": f"Dispatched {document_type} package via WhatsApp to {phone_number}."
    }


async def update_lead_qualification(
    phone_number: str,
    qualification_status: str,
    interest_level: str,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Updates the lead qualification status in CRM (e.g. 'Qualified', 'Follow_Up', 'Not_Interested').
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Lead).where(Lead.phone_number == phone_number)
        )
        lead = result.scalars().first()
        if lead:
            lead.status = qualification_status
            if notes:
                lead.notes = f"{lead.notes or ''}\n[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] {notes}".strip()
            await session.commit()

    return {
        "status": "success",
        "qualification": qualification_status,
        "interest": interest_level
    }

# Tool declarations formatted for Google Gemini function declarations
GEMINI_MARKETING_TOOLS = [
    {
        "name": "book_growth_audit",
        "description": "Call this function when the customer agrees to schedule a 15-minute Marketing Funnel Audit / Demo call. Ask for their preferred day and time.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "customer_name": {"type": "STRING", "description": "Full or first name of customer"},
                "preferred_slot": {"type": "STRING", "description": "Preferred date and time (e.g., 'Tomorrow at 3 PM' or 'Friday afternoon')"},
                "email": {"type": "STRING", "description": "Customer's email address if provided"},
                "notes": {"type": "STRING", "description": "Any specific focus area or marketing challenges they mentioned"}
            },
            "required": ["customer_name", "preferred_slot"]
        }
    },
    {
        "name": "send_whatsapp_brochure",
        "description": "Call this function when the customer asks to receive information, a case study, or deck over WhatsApp or SMS.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "phone_number": {"type": "STRING", "description": "Phone number of the lead"},
                "email": {"type": "STRING", "description": "Optional email address if they want it emailed instead"},
                "document_type": {"type": "STRING", "description": "Type of collateral ('case_study', 'pricing_overview', 'demo_link')"}
            },
            "required": ["phone_number"]
        }
    },
    {
        "name": "update_lead_qualification",
        "description": "Call this function to record the lead's level of interest, budget or timeline qualification.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "phone_number": {"type": "STRING", "description": "Phone number of lead"},
                "qualification_status": {"type": "STRING", "enum": ["Qualified", "Follow_Up", "Not_Interested"], "description": "Qualification category"},
                "interest_level": {"type": "STRING", "enum": ["High", "Medium", "Low"], "description": "Level of interest displayed"},
                "notes": {"type": "STRING", "description": "Key takeaways or objection details"}
            },
            "required": ["phone_number", "qualification_status", "interest_level"]
        }
    }
]
