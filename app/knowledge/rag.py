"""
RAG Engine for Real-Time Marketing Knowledge Retrieval.
Quickly indexes and matches callee queries against company collateral,
product pricing, FAQs, and objection handling scripts.
"""

import json
import os
import re
from typing import List, Dict, Any

class MarketingRAG:
    def __init__(self, data_path: str = None):
        if data_path is None:
            base_dir = os.path.dirname(__file__)
            data_path = os.path.join(base_dir, "marketing_knowledge.json")
        
        self.data_path = data_path
        self.documents: List[Dict[str, str]] = []
        self._load_and_index()

    def _load_and_index(self):
        """Loads JSON data and creates searchable chunks."""
        if not os.path.exists(self.data_path):
            return

        with open(self.data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Index Offer
        if "offer" in data:
            self.documents.append({
                "category": "offer",
                "title": data["offer"].get("title", ""),
                "content": f"Special Offer: {data['offer'].get('title')} - {data['offer'].get('description')} Bonus: {data['offer'].get('bonuses')}",
                "keywords": ["audit", "demo", "offer", "free", "trial", "pilot", "consultation"]
            })

        # Index Pricing
        if "pricing" in data:
            pricing_text = "\n".join([f"{k.capitalize()}: {v}" for k, v in data["pricing"].items()])
            self.documents.append({
                "category": "pricing",
                "title": "Pricing & Packages",
                "content": f"Pricing Plans:\n{pricing_text}",
                "keywords": ["price", "pricing", "cost", "how much", "rate", "expensive", "charges", "fees", "discount", "starter", "growth"]
            })

        # Index FAQs
        for faq in data.get("faqs", []):
            self.documents.append({
                "category": "faq",
                "title": faq["question"],
                "content": f"Q: {faq['question']}\nA: {faq['answer']}",
                "keywords": self._extract_keywords(faq["question"])
            })

        # Index Objections
        for obj in data.get("objection_handling", []):
            self.documents.append({
                "category": "objection",
                "title": f"Objection: {obj['objection']}",
                "content": f"When callee says: '{obj['objection']}' -> Suggested response angle: {obj['counter']}",
                "keywords": self._extract_keywords(obj["objection"])
            })

    def _extract_keywords(self, text: str) -> List[str]:
        words = re.findall(r"\b\w{3,}\b", text.lower())
        stopwords = {"what", "when", "where", "which", "who", "whom", "this", "that", "with", "have", "from", "they", "will"}
        return [w for w in words if w not in stopwords]

    def query(self, user_text: str, top_k: int = 2) -> str:
        """
        Retrieves the most relevant knowledge context for the callee's utterance.
        """
        if not user_text or not self.documents:
            return ""

        user_words = set(re.findall(r"\b\w{3,}\b", user_text.lower()))
        scored_docs = []

        for doc in self.documents:
            score = 0
            # Keyword overlap
            for kw in doc["keywords"]:
                if kw in user_words or kw in user_text.lower():
                    score += 2
            # Text substring match
            if doc["title"].lower() in user_text.lower():
                score += 5
            
            if score > 0:
                scored_docs.append((score, doc))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        top_matches = [doc["content"] for _, doc in scored_docs[:top_k]]
        
        if top_matches:
            return "\n\nRelevant Knowledge Base Information:\n" + "\n---\n".join(top_matches)
        return ""

rag_engine = MarketingRAG()
