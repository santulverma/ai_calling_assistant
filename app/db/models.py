"""
Database Models for AI Calling Assistant.
Tracks Leads, Calls, Transcripts, and Appointments.
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, Float, DateTime, ForeignKey, Boolean
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    phone_number = Column(String(30), unique=True, index=True, nullable=False)
    company = Column(String(150), nullable=True)
    email = Column(String(150), nullable=True)
    status = Column(String(50), default="Pending")  # Pending, In_Progress, Qualified, Not_Interested, Follow_Up
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    calls = relationship("CallLog", back_populates="lead", cascade="all, delete-orphan")


class CallLog(Base):
    __tablename__ = "call_logs"

    id = Column(Integer, primary_key=True, index=True)
    call_uuid = Column(String(100), unique=True, index=True, nullable=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    phone_number = Column(String(30), nullable=False)
    direction = Column(String(20), default="outbound")  # outbound, inbound
    status = Column(String(50), default="initiated")   # initiated, ringing, in_progress, completed, busy, failed
    duration_seconds = Column(Integer, default=0)
    sentiment = Column(String(50), nullable=True)       # Positive, Neutral, Negative, Interested, Hesitant
    qualification_status = Column(String(50), nullable=True)  # Qualified, Disqualified, Needs_Followup
    summary = Column(Text, nullable=True)
    recording_url = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    lead = relationship("Lead", back_populates="calls")
    transcripts = relationship("TranscriptMessage", back_populates="call", cascade="all, delete-orphan")


class TranscriptMessage(Base):
    __tablename__ = "transcripts"

    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(Integer, ForeignKey("call_logs.id"), nullable=False)
    speaker = Column(String(20), nullable=False)  # "agent", "callee", "system"
    text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    call = relationship("CallLog", back_populates="transcripts")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    call_id = Column(Integer, ForeignKey("call_logs.id"), nullable=True)
    customer_name = Column(String(100), nullable=False)
    customer_email = Column(String(150), nullable=True)
    customer_phone = Column(String(30), nullable=False)
    slot_time = Column(String(100), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
