# rag_service.py
import os
import json
import re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from supabase import create_client
from typing import Optional, List
import uvicorn
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="BookLeaf RAG Service")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load embedding model
print("📥 Loading embedding model...")
model = SentenceTransformer("mixedbread-ai/mxbai-embed-large-v1")
print("✅ Model loaded!")

# Supabase client
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

# Path to your markdown knowledge base file
KNOWLEDGE_BASE_FILE = "/home/pranav/Code/bookleaf/FAQs (Knowledge Base) - AI Automation assignment.md"

class RAGRequest(BaseModel):
    query: str
    match_threshold: Optional[float] = 0.7
    match_count: Optional[int] = 3

class RAGResponse(BaseModel):
    results: List[dict]
    query: str
    count: int

@app.get("/health")
async def health():
    return {"status": "healthy", "model_loaded": True}

@app.post("/rag/search", response_model=RAGResponse)
async def search_knowledge_base(request: RAGRequest):
    try:
        embedding = model.encode(request.query).tolist()
        result = supabase.rpc(
            "match_knowledge_base",
            {
                "query_embedding": embedding,
                "match_threshold": request.match_threshold,
                "match_count": request.match_count
            }
        ).execute()
        return RAGResponse(
            results=result.data,
            query=request.query,
            count=len(result.data)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def parse_faq_markdown(filepath: str) -> List[dict]:
    """
    Parse a markdown file containing FAQs.
    Assumes questions are headings (##, ###, etc.) and answers are the following paragraphs.
    Returns list of {question, answer} dicts.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by headings (lines starting with #)
    # We'll capture the heading text and the following content until next heading
    # Use regex to find all headings and their content
    # Pattern: ^(#+)\s+(.*)$ for heading, then capture everything until next heading or end
    lines = content.split('\n')
    qa_pairs = []
    current_question = None
    current_answer_lines = []

    # We'll iterate and detect headings
    # Also handle bullet points and plain text
    for line in lines:
        stripped = line.strip()
        # Check if line is a heading (starts with #)
        heading_match = re.match(r'^(#+)\s+(.*)$', line)
        if heading_match:
            # If we were accumulating an answer, save previous pair
            if current_question is not None:
                answer = '\n'.join(current_answer_lines).strip()
                if answer:
                    qa_pairs.append({
                        "question": current_question,
                        "answer": answer
                    })
            # Start new question
            current_question = heading_match.group(2).strip()
            current_answer_lines = []
        else:
            # If we have a current question, accumulate lines as answer
            if current_question is not None:
                # Skip empty lines? We'll keep them for formatting but trim later
                current_answer_lines.append(line)

    # Don't forget the last pair
    if current_question is not None:
        answer = '\n'.join(current_answer_lines).strip()
        if answer:
            qa_pairs.append({
                "question": current_question,
                "answer": answer
            })

    # Fallback: if no headings found, try to detect questions by '?' and grouping
    if not qa_pairs:
        # Simple fallback: split by double newlines, look for lines ending with ?
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        i = 0
        while i < len(paragraphs):
            para = paragraphs[i]
            if para.endswith('?') or para.startswith('Q:'):
                question = para
                # Gather following paragraphs until next question
                answer_parts = []
                i += 1
                while i < len(paragraphs) and not (paragraphs[i].endswith('?') or paragraphs[i].startswith('Q:')):
                    answer_parts.append(paragraphs[i])
                    i += 1
                answer = '\n\n'.join(answer_parts).strip()
                if answer:
                    qa_pairs.append({"question": question, "answer": answer})
            else:
                i += 1

    return qa_pairs

@app.post("/rag/ingest")
async def ingest_knowledge_base():
    """
    Ingest knowledge base from the markdown file.
    """
    if not os.path.exists(KNOWLEDGE_BASE_FILE):
        raise HTTPException(status_code=404, detail=f"Knowledge base file not found: {KNOWLEDGE_BASE_FILE}")

    qa_pairs = parse_faq_markdown(KNOWLEDGE_BASE_FILE)
    if not qa_pairs:
        raise HTTPException(status_code=400, detail="No Q&A pairs found in the file.")

    count = 0
    for pair in qa_pairs:
        question = pair["question"]
        answer = pair["answer"]
        content = f"Q: {question}\nA: {answer}"
        embedding = model.encode(content).tolist()
        # Determine category from first heading? Not available, set to 'General'
        supabase.table("knowledge_base").insert({
            "content": content,
            "embedding": embedding,
            "category": "FAQ",
            "metadata": {"question": question, "answer": answer}
        }).execute()
        count += 1

    return {"message": f"✅ Ingested {count} Q&A pairs from {KNOWLEDGE_BASE_FILE}"}

@app.post("/rag/ingest-hardcoded")
async def ingest_hardcoded():
    """
    (Optional) Ingest the old hardcoded list (kept for testing)
    """
    knowledge_base = [
        # ... (your old hardcoded list) ...
    ]
    count = 0
    for section in knowledge_base:
        for q, a in section["qa"]:
            content = f"Q: {q}\nA: {a}"
            embedding = model.encode(content).tolist()
            supabase.table("knowledge_base").insert({
                "content": content,
                "embedding": embedding,
                "category": section["category"],
                "metadata": {"question": q, "answer": a}
            }).execute()
            count += 1
    return {"message": f"✅ Ingested {count} hardcoded Q&A pairs"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8009)