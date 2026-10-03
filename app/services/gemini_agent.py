"""
Gemini Flash Real-Time Marketing Conversational Agent.
Handles low-latency streaming responses, sentence boundary chunking,
RAG context injection, and tool calling.
"""

import asyncio
import json
import logging
import re
from typing import AsyncGenerator, List, Dict, Any, Optional
import httpx
from app.config import settings
from app.knowledge.rag import rag_engine
from app.tools.marketing_tools import (
    GEMINI_MARKETING_TOOLS,
    book_growth_audit,
    send_whatsapp_brochure,
    update_lead_qualification
)

logger = logging.getLogger(__name__)

MARKETING_SYSTEM_PROMPT = f"""You are {settings.AGENT_NAME}, an expert and enthusiastic AI Marketing & Growth Consultant calling from {settings.COMPANY_NAME}.
Your primary goal is to speak with business owners or marketing leaders, introduce our {settings.PRODUCT_NAME}, answer any questions, and schedule a {settings.CALL_OBJECTIVE}.

CRITICAL VOICE CONVERSATION RULES:
1. EXTREME BREVITY: Speak in short, conversational sentences (1 to 2 sentences per turn max). People on the phone will hang up if you give long monologues.
2. NO MARKDOWN: Never output asterisks (*), hashtags (#), bullet points (-), or bold text. This will be read directly by a Text-to-Speech engine.
3. PHONETIC NUMBERS: Spell out numbers and currencies naturally (e.g. say "thirty-nine thousand rupees" or "five hundred dollars", never "39,000 INR" or "$500").
4. NATURAL SPEECH: Use natural spoken transitions like "Got it", "That makes total sense", "I hear you", "Certainly".
5. ACTIVE LISTENING & OBJECTION HANDLING:
   - If they say "send an email/WhatsApp": Agree enthusiastically and ask for their email address or confirm their phone number, and offer to book a quick 15-minute chat.
   - If they say "no budget": Explain that the 15-minute marketing funnel audit is 100% free with no commitment.
   - If they ask "Are you an AI?": Be honest and proud: "Yes, I am Riya, an AI assistant from ApexGrowth! I'm speaking with you live to show how effective conversational AI is for growing businesses."
6. CALL TO ACTION: Always end your turns with an engaging question to keep the conversation flowing.
"""

class GeminiMarketingAgent:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:streamGenerateContent?alt=sse&key={self.api_key}"

    async def generate_response_stream(
        self,
        conversation_history: List[Dict[str, str]],
        lead_context: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Streams response sentences one-by-one as soon as a complete sentence boundary is detected.
        This provides sub-second latency for Text-to-Speech synthesis.
        """
        # Retrieve RAG context based on callee's latest input
        latest_user_text = ""
        for msg in reversed(conversation_history):
            if msg.get("role") == "user":
                latest_user_text = msg.get("content", "")
                break

        rag_context = rag_engine.query(latest_user_text) if latest_user_text else ""
        
        dynamic_system_prompt = MARKETING_SYSTEM_PROMPT
        if lead_context:
            dynamic_system_prompt += f"\n\nCURRENT LEAD INFO:\nName: {lead_context.get('name', 'Customer')}\nCompany: {lead_context.get('company', 'Business')}\nPhone: {lead_context.get('phone', 'N/A')}"
        if rag_context:
            dynamic_system_prompt += f"\n\n{rag_context}"

        # Build Gemini request payload
        contents = []
        for msg in conversation_history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })

        payload = {
            "system_instruction": {
                "parts": [{"text": dynamic_system_prompt}]
            },
            "contents": contents,
            "generationConfig": {
                "temperature": 0.6,
                "maxOutputTokens": 150,
                "topP": 0.85
            }
        }

        # If no API key configured, provide sensible simulated marketing responses
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured. Running fallback marketing script.")
            yield self._get_fallback_response(latest_user_text)
            return

        sentence_buffer = ""
        # Punctuation boundaries for sentence chunking
        sentence_end_pattern = re.compile(r"([.!?]+)\s*")

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                async with client.stream("POST", self.api_url, json=payload) as response:
                    if response.status_code != 200:
                        err_body = await response.aread()
                        logger.error(f"Gemini API error {response.status_code}: {err_body.decode('utf-8', errors='ignore')}")
                        yield self._get_fallback_response(latest_user_text)
                        return

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break

                        try:
                            chunk_json = json.loads(data_str)
                            candidates = chunk_json.get("candidates", [])
                            if not candidates:
                                continue
                            
                            content = candidates[0].get("content", {})
                            parts = content.get("parts", [])
                            for part in parts:
                                text_chunk = part.get("text", "")
                                sentence_buffer += text_chunk

                                # Check for sentence endings
                                while True:
                                    match = sentence_end_pattern.search(sentence_buffer)
                                    if not match:
                                        break
                                    end_idx = match.end()
                                    complete_sentence = sentence_buffer[:end_idx].strip()
                                    sentence_buffer = sentence_buffer[end_idx:]
                                    
                                    # Clean speech formatting
                                    clean_sentence = self._sanitize_for_speech(complete_sentence)
                                    if clean_sentence:
                                        yield clean_sentence

                        except Exception as e:
                            logger.error(f"Error parsing Gemini SSE chunk: {e}")

                # Flush remaining buffer if any
                remaining = self._sanitize_for_speech(sentence_buffer.strip())
                if remaining:
                    yield remaining

            except Exception as e:
                logger.error(f"Exception during Gemini streaming: {e}")
                yield self._get_fallback_response(latest_user_text)

    def _sanitize_for_speech(self, text: str) -> str:
        """Strips out markdown syntax, symbols, and formatting that disrupt TTS."""
        t = re.sub(r"[\*#_`~\[\]\(\)]", "", text)
        t = t.replace("\n", " ")
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _get_fallback_response(self, user_text: str) -> str:
        """Contextual fallback if LLM API is unavailable or unconfigured."""
        u = user_text.lower()
        if "hello" in u or "hi" in u:
            return f"Hello! This is {settings.AGENT_NAME} from {settings.COMPANY_NAME}. We help growing companies automate their sales and marketing. Am I speaking with the decision maker?"
        elif "price" in u or "cost" in u:
            return "Our plans start at thirty-nine thousand rupees per month for up to two thousand automated calling minutes, and we are currently offering a free fifteen minute funnel audit."
        elif "whatsapp" in u or "email" in u:
            return "Certainly! I would love to send our quick case study right to your WhatsApp. Could you please confirm your preferred email address as well?"
        elif "not interested" in u:
            return "No worries at all! Would it make sense for me to check back next quarter, or would you prefer a quick one-page overview over message?"
        else:
            return f"I understand completely. That is why our team at {settings.COMPANY_NAME} offers a complimentary fifteen minute audit to see how much pipeline you can generate. Would tomorrow afternoon work for a quick demo?"

gemini_agent = GeminiMarketingAgent()
