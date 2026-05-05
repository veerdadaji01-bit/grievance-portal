from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, String, Text, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import json
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = "sqlite:///./tickets.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Ticket(Base):
    __tablename__ = "tickets"
    id       = Column(String, primary_key=True)
    title    = Column(String)
    problem  = Column(Text)
    location = Column(String)
    name     = Column(String)
    status   = Column(String)
    priority = Column(String)
    tags     = Column(Text)
    category = Column(String)

Base.metadata.create_all(bind=engine)


with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE tickets ADD COLUMN category TEXT"))
    except:
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    client = None

def analyze_ticket_with_ai(title: str, problem: str):
    if not client:
        
        return {
            "category": "public",
            "priority": "medium",
            "tags": ["unverified"],
            "blacklist": False,
            "fake": False
        }
        
    prompt = f"""
    You are an AI for a grievance portal. 
    Title: {title}
    Problem: {problem}
    
    Analyze the above ticket and return a JSON object with EXACTLY these keys:
    1. category: "public" or "private". "public" includes EVERYTHING related to public spaces, government, transport, trains, delays, railway wifi, amenities, and ANY suggestions for the city. "private" is ONLY for personal issues inside a home (my laptop is broken, my bank account, looking for a girlfriend).
    2. priority: MUST be "high" for REAL, GENUINE life-threatening issues, accidents, fire, exposed live wires, open deep drains, gas leaks, collapsing roads, or major safety hazards. "medium" is for non-urgent broken pipes, normal potholes, or garbage. "low" is for suggestions, delays, or minor amenities.
    3. tags: A list of 1 to 3 short tags.
    4. blacklist: true ONLY if it is 100% random keyboard mashing (like "asdfasdf" or "hfsjkdf"). Set to false for EVERYTHING else.
    5. fake: true if it is obviously a joke, or if it uses EXTREMELY EXAGGERATED/FAKE URGENCY for trivial things (e.g., "my son is dying because of wifi", "world is ending due to no internet", "my life is over because of a pothole"). Real emergencies don't typically involve wifi or minor inconveniences. Set to false for genuine complaints.
    
    CRITICAL: When in doubt, ALWAYS set category="public", blacklist=false, and fake=false.
    
    {{
        "category": "public" | "private",
        "priority": "high" | "medium" | "low",
        "tags": ["string"],
        "blacklist": boolean,
        "fake": boolean
    }}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        
    
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
            
        print(f"AI Output: {raw_text.strip()}") 
        
        
        result = json.loads(raw_text.strip())
        return result
    except Exception as e:
        print(f"AI Error: {e}")
        try:
            print(f"Raw response: {response.text}")
        except:
            pass
    
        return {
            "category": "public",
            "priority": "medium",
            "tags": ["unverified_ai_error"],
            "blacklist": False,
            "fake": False
        }

@app.post("/tickets")
def create_ticket(title: str, problem: str, location: str, name: str = "user", db: Session = Depends(get_db)):
    count     = db.query(Ticket).count() + 1
    ticket_id = f"GRV-{count:04d}"

    ai_data = analyze_ticket_with_ai(title, problem)
    category = ai_data.get("category", "public")
    priority = ai_data.get("priority", "medium")
    tags = ai_data.get("tags", [])
    

    if category == "private" or ai_data.get("blacklist") or ai_data.get("fake"):
        return {
            "ticket_id": "REJECTED",
            "category": "private",
            "priority": "low"
        }

    ticket = Ticket(
        id=ticket_id,
        title=title,
        problem=problem,
        location=location,
        name=name,
        status="staging",
        priority=priority,
        tags=", ".join(tags),
        category=category
    )

    db.add(ticket)
    db.commit()

    return {
        "ticket_id": ticket_id,
        "category": category,
        "priority": priority
    }


@app.get("/ticket/{ticket_id}")
def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    t = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


@app.post("/admin/login")
def admin_login(username: str, password: str):
    if username == "admin" and password == "1234":
        return {"status": "success"}
    return {"status": "failed"}


@app.get("/admin/tickets")
def get_all(db: Session = Depends(get_db)):
    return db.query(Ticket).all()


@app.patch("/admin/tickets/{ticket_id}")
def update(ticket_id: str, status: str = None, priority: str = None, db: Session = Depends(get_db)):
    t = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if status:
        t.status = status
    if priority:
        t.priority = priority
    db.commit()
    return {"message": "updated"}