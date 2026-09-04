"""
AI Company Builder — Build Your Own AI-Powered Company
=======================================================
Create projects, let AI design your team structure (or do it manually),
watch agents debate and collaborate, see org charts, and track everything
on a professional dashboard.

SETUP:
  pip install -r requirements.txt
  Create .env file with:
    GROQ_API_KEY=your-groq-key-here
    OPENROUTER_API_KEY_BETA=your-beta-key-here
    OPENROUTER_API_KEY_CHARLIE=your-charlie-key-here

RUN:
  streamlit run app.py
"""

import os
import json
import time
import uuid
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from groq import Groq
from openai import OpenAI

load_dotenv()

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
PROJECTS_FILE = Path("projects.json")
MEMORY_FILE = Path("memory.json")
DEBATE_ROUNDS = 2
MAX_TOKENS = 1000

st.set_page_config(
    page_title="AI Company Builder",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CUSTOM CSS — Dashboard Style
# ---------------------------------------------------------------------------
st.markdown("""
<style>
/* ---- Main background & typography ---- */
[data-testid="stMain"] {
    background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
}
[data-testid="stSidebar"] {
    background: #0d0d1a;
    border-right: 1px solid #2a2a4a;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] .stMarkdown {
    color: #e0e0e0 !important;
}
h1, h2, h3, h4, h5, h6, p, span, label, div {
    color: #e8e8f0 !important;
}

/* ---- Metric cards ---- */
.metric-card {
    background: linear-gradient(135deg, #1e1e3a, #2a2a4a);
    border: 1px solid #3a3a5c;
    border-radius: 16px;
    padding: 20px 24px;
    text-align: center;
    transition: transform 0.2s, box-shadow 0.2s;
}
.metric-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(100, 100, 255, 0.15);
}
.metric-value {
    font-size: 2.4rem;
    font-weight: 700;
    background: linear-gradient(135deg, #6c63ff, #48c6ef);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 4px 0;
}
.metric-label {
    font-size: 0.85rem;
    color: #8888aa !important;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    font-weight: 600;
}
.metric-icon {
    font-size: 1.6rem;
    margin-bottom: 4px;
}

/* ---- Agent cards ---- */
.agent-card {
    background: linear-gradient(135deg, #1a1a35, #252545);
    border: 1px solid #3a3a5c;
    border-radius: 14px;
    padding: 18px;
    margin-bottom: 12px;
}
.agent-card-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
}
.agent-name {
    font-size: 1.1rem;
    font-weight: 700;
    color: #c8c8ff !important;
}
.agent-role-tag {
    display: inline-block;
    background: rgba(108, 99, 255, 0.2);
    border: 1px solid rgba(108, 99, 255, 0.4);
    border-radius: 20px;
    padding: 2px 12px;
    font-size: 0.75rem;
    color: #a8a0ff !important;
}
.agent-desc {
    font-size: 0.85rem;
    color: #9999bb !important;
    line-height: 1.5;
}
.reports-to {
    font-size: 0.78rem;
    color: #7777aa !important;
    margin-top: 6px;
}

/* ---- Status indicators ---- */
.status-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 6px;
}
.status-active { background: #4ade80; box-shadow: 0 0 8px #4ade8066; }
.status-thinking { background: #facc15; box-shadow: 0 0 8px #facc1566; }
.status-idle { background: #6b7280; }

/* ---- Section headers ---- */
.section-header {
    font-size: 1.3rem;
    font-weight: 700;
    color: #c8c8ff !important;
    margin: 24px 0 12px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid #3a3a5c;
}

/* ---- Chat bubbles for debate ---- */
.chat-bubble {
    background: #1e1e3a;
    border: 1px solid #3a3a5c;
    border-radius: 12px;
    padding: 14px 18px;
    margin-bottom: 10px;
    font-size: 0.92rem;
    line-height: 1.6;
    color: #d0d0e8 !important;
}
.chat-bubble-header {
    font-weight: 700;
    color: #a8a0ff !important;
    margin-bottom: 6px;
    font-size: 0.95rem;
}

/* ---- Buttons ---- */
.stButton>button {
    background: linear-gradient(135deg, #6c63ff, #5a52d5) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 8px 24px !important;
    font-weight: 600 !important;
    transition: all 0.2s !important;
}
.stButton>button:hover {
    background: linear-gradient(135deg, #7c73ff, #6a62e5) !important;
    box-shadow: 0 4px 16px rgba(108, 99, 255, 0.4) !important;
}

/* ---- Tabs ---- */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: #1a1a2e;
    border-radius: 12px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    color: #8888aa !important;
    font-weight: 600;
}
.stTabs [aria-selected="true"] {
    background: #6c63ff !important;
    color: white !important;
}

/* ---- Inputs ---- */
.stTextInput>div>div>input, .stTextArea>div>div>textarea {
    background: #1e1e3a !important;
    border: 1px solid #3a3a5c !important;
    color: #e0e0f0 !important;
    border-radius: 10px !important;
}
.stSelectbox>div>div {
    background: #1e1e3a !important;
    border: 1px solid #3a3a5c !important;
    border-radius: 10px !important;
}

/* ---- Expander ---- */
.streamlit-expanderHeader {
    background: #1e1e3a !important;
    border-radius: 10px !important;
    color: #c8c8ff !important;
}

/* ---- Org chart background ---- */
[data-testid="stVegaLiteChart"], .stGraphVizChart {
    background: #12122a;
    border-radius: 12px;
    padding: 12px;
}

/* ---- Hide streamlit branding (keep header for sidebar toggle) ---- */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

/* ---- Fix sidebar interactivity ---- */
[data-testid="stSidebar"] button {
    color: white !important;
    cursor: pointer !important;
}
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stTextInput label,
[data-testid="stSidebar"] .stTextArea label {
    color: #b0b0cc !important;
}
/* Fix dropdown options visibility */
[data-baseweb="menu"] {
    background: #1e1e3a !important;
}
[data-baseweb="menu"] li {
    color: #e0e0f0 !important;
}
[data-baseweb="menu"] li:hover {
    background: #3a3a5c !important;
}
/* Fix radio buttons */
[data-testid="stSidebar"] .stRadio label span {
    color: #d0d0e8 !important;
}
/* Fix expander arrow & click area */
[data-testid="stSidebar"] .streamlit-expanderHeader {
    cursor: pointer !important;
    background: #1a1a30 !important;
    border: 1px solid #3a3a5c !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] details summary {
    cursor: pointer !important;
    color: #c8c8ff !important;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# API CLIENTS
# ---------------------------------------------------------------------------
@st.cache_resource
def get_clients():
    groq_key = os.environ.get("GROQ_API_KEY")
    beta_key = os.environ.get("OPENROUTER_API_KEY_BETA")
    charlie_key = os.environ.get("OPENROUTER_API_KEY_CHARLIE")
    clients = []
    if groq_key:
        clients.append(("groq", Groq(api_key=groq_key), "openai/gpt-oss-120b"))
    if beta_key:
        clients.append(("openrouter", OpenAI(base_url="https://openrouter.ai/api/v1", api_key=beta_key), "openrouter/free"))
    if charlie_key:
        clients.append(("openrouter", OpenAI(base_url="https://openrouter.ai/api/v1", api_key=charlie_key), "openrouter/free"))
    return clients

API_SLOTS = get_clients()

# ---------------------------------------------------------------------------
# DATA STORAGE
# ---------------------------------------------------------------------------
# Project structure:
# { "projects": { pid: {
#     "name", "description", "created",
#     "team": { agent_id: { "name", "emoji", "role", "reports_to" (agent_id|null),
#               "coordinates_with": [agent_id,...], "api_slot": int } },
#     "team_reasoning": str,
#     "tasks": { tid: { "name", "created", "status", "history": [...],
#                "subtasks": { sid: { "name", "created", "history": [...] } }
#     }}
# }}}

def load_projects():
    if PROJECTS_FILE.exists():
        with open(PROJECTS_FILE, "r") as f:
            return json.load(f)
    return {"projects": {}}

def save_projects(data):
    with open(PROJECTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_memory():
    if MEMORY_FILE.exists():
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {"lessons": []}

def save_memory(mem):
    with open(MEMORY_FILE, "w") as f:
        json.dump(mem, f, indent=2)

def new_id():
    return uuid.uuid4().hex[:8]

def memory_context(mem):
    if not mem.get("lessons"):
        return ""
    recent = mem["lessons"][-10:]
    txt = "\n".join(f"- {l}" for l in recent)
    return f"\n\nLESSONS FROM PAST WORK (avoid repeating these mistakes):\n{txt}\n"

# ---------------------------------------------------------------------------
# API CALL HELPER
# ---------------------------------------------------------------------------
def call_api(api_slot_idx, system_prompt, user_prompt, max_retries=2):
    """Call the API at the given slot index (wraps around if out of range)."""
    if not API_SLOTS:
        return "No API keys configured. Please check your .env file."
    idx = api_slot_idx % len(API_SLOTS)
    _, client, model = API_SLOTS[idx]
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return resp.choices[0].message.content
        except Exception as e:
            if "429" in str(e) and attempt < max_retries:
                time.sleep(5 * (attempt + 1))
                continue
            return f"⚠️ Unavailable: {e}"

# ---------------------------------------------------------------------------
# TEAM PLANNING (AI-powered)
# ---------------------------------------------------------------------------
DEFAULT_EMOJIS = ["👔", "💡", "🔍", "🏗️", "📊", "🎨", "📣", "⚙️"]

def ai_plan_team(project_description):
    """Ask an AI agent to suggest the optimal team structure."""
    prompt = f"""You are a company organizational designer. Given this project description, design the optimal team of AI agents.

PROJECT: {project_description}

Rules:
- Create 3 to 6 agents depending on project complexity
- Each agent needs a distinct professional role
- Establish a clear hierarchy (who reports to whom)
- Define coordination links (who works closely together)
- The top-level agent (CEO/Lead) reports_to should be null

Return ONLY valid JSON, no markdown fences, no explanation outside the JSON:
{{
  "agents": [
    {{
      "name": "Role Title",
      "emoji": "single_emoji",
      "role": "One paragraph describing this agent's responsibilities and expertise",
      "reports_to": null,
      "coordinates_with": []
    }},
    {{
      "name": "Another Role",
      "emoji": "single_emoji",
      "role": "Description...",
      "reports_to": "Role Title",
      "coordinates_with": ["Role Title"]
    }}
  ],
  "reasoning": "Brief explanation of why this structure fits the project"
}}"""

    system = "You are an expert organizational designer. Return ONLY valid JSON. No markdown code fences."
    raw = call_api(0, system, prompt)

    # Try to parse JSON from the response
    try:
        # Strip markdown fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```\w*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
        data = json.loads(cleaned)
        return data
    except (json.JSONDecodeError, TypeError):
        # Fallback: return a default 3-agent team
        return {
            "agents": [
                {"name": "Project Lead", "emoji": "👔",
                 "role": "Oversees the entire project, makes final decisions, and synthesizes team output.",
                 "reports_to": None, "coordinates_with": []},
                {"name": "Specialist", "emoji": "💡",
                 "role": "Provides deep domain expertise and innovative solutions for the project.",
                 "reports_to": "Project Lead", "coordinates_with": ["Project Lead"]},
                {"name": "Quality Reviewer", "emoji": "🔍",
                 "role": "Reviews all work for errors, edge cases, and quality standards.",
                 "reports_to": "Project Lead", "coordinates_with": ["Specialist"]},
            ],
            "reasoning": "Default team (AI response could not be parsed). You can customize roles below."
        }

def build_team_dict(agents_list):
    """Convert a list of agent dicts into the stored team structure with IDs."""
    team = {}
    name_to_id = {}
    # First pass: assign IDs
    for i, ag in enumerate(agents_list):
        aid = new_id()
        name_to_id[ag["name"]] = aid
        team[aid] = {
            "name": ag["name"],
            "emoji": ag.get("emoji", DEFAULT_EMOJIS[i % len(DEFAULT_EMOJIS)]),
            "role": ag["role"],
            "reports_to": None,  # filled in second pass
            "coordinates_with": [],  # filled in second pass
            "api_slot": i % max(len(API_SLOTS), 1),
        }
    # Second pass: resolve references
    for aid, ag_data in team.items():
        orig = next(a for a in agents_list if a["name"] == ag_data["name"])
        if orig.get("reports_to") and orig["reports_to"] in name_to_id:
            ag_data["reports_to"] = name_to_id[orig["reports_to"]]
        coords = []
        for cname in orig.get("coordinates_with", []):
            if cname in name_to_id and name_to_id[cname] != aid:
                coords.append(name_to_id[cname])
        ag_data["coordinates_with"] = coords
    return team

# ---------------------------------------------------------------------------
# ORG CHART RENDERING (Graphviz DOT)
# ---------------------------------------------------------------------------
def render_hierarchy_dot(team):
    """Generate DOT for a top-down hierarchy tree."""
    lines = [
        'digraph G {',
        '  rankdir=TB;',
        '  bgcolor="transparent";',
        '  node [shape=box, style="rounded,filled", fillcolor="#2a2a4a", fontcolor="#e0e0f0",',
        '        fontname="Helvetica", fontsize=11, color="#6c63ff", penwidth=2];',
        '  edge [color="#6c63ff", penwidth=1.5, arrowsize=0.8];',
    ]
    for aid, ag in team.items():
        label = f'{ag["emoji"]} {ag["name"]}'
        lines.append(f'  "{aid}" [label="{label}"];')
    for aid, ag in team.items():
        if ag.get("reports_to") and ag["reports_to"] in team:
            lines.append(f'  "{ag["reports_to"]}" -> "{aid}";')
    lines.append("}")
    return "\n".join(lines)

def render_coordination_dot(team):
    """Generate DOT for a coordination network diagram."""
    lines = [
        'digraph G {',
        '  layout=neato;',
        '  overlap=false;',
        '  bgcolor="transparent";',
        '  node [shape=ellipse, style="filled", fillcolor="#2a2a4a", fontcolor="#e0e0f0",',
        '        fontname="Helvetica", fontsize=11, color="#48c6ef", penwidth=2];',
        '  edge [penwidth=1.2, arrowsize=0.7];',
    ]
    for aid, ag in team.items():
        label = f'{ag["emoji"]} {ag["name"]}'
        lines.append(f'  "{aid}" [label="{label}"];')
    # Reporting lines (solid)
    for aid, ag in team.items():
        if ag.get("reports_to") and ag["reports_to"] in team:
            lines.append(f'  "{ag["reports_to"]}" -> "{aid}" [color="#6c63ff", style=solid, label="reports"];')
    # Coordination lines (dashed, bidirectional)
    seen_pairs = set()
    for aid, ag in team.items():
        for cid in ag.get("coordinates_with", []):
            if cid in team:
                pair = tuple(sorted([aid, cid]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    lines.append(f'  "{aid}" -> "{cid}" [color="#4ade80", style=dashed, dir=both, label="coords"];')
    lines.append("}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# DASHBOARD METRICS
# ---------------------------------------------------------------------------
def compute_metrics(data, memory):
    total_projects = len(data.get("projects", {}))
    total_tasks = 0
    total_runs = 0
    total_agents = 0
    for pid, proj in data.get("projects", {}).items():
        total_agents += len(proj.get("team", {}))
        for tid, task in proj.get("tasks", {}).items():
            total_tasks += 1
            total_runs += len(task.get("history", []))
            for sid, sub in task.get("subtasks", {}).items():
                total_runs += len(sub.get("history", []))
    total_lessons = len(memory.get("lessons", []))
    return {
        "projects": total_projects,
        "tasks": total_tasks,
        "runs": total_runs,
        "agents": total_agents,
        "lessons": total_lessons,
    }

def render_metric_card(icon, value, label):
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-icon">{icon}</div>
        <div class="metric-value">{value}</div>
        <div class="metric-label">{label}</div>
    </div>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# DEBATE WORKFLOW (dynamic agents)
# ---------------------------------------------------------------------------
def run_debate(task_text, team, memory):
    """Run the multi-agent debate with the project's dynamic team."""
    context = memory_context(memory)
    agent_ids = list(team.keys())
    agent_names = {aid: team[aid]["name"] for aid in agent_ids}

    transcript = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "task_text": task_text,
        "round0": {},
        "debate_rounds": [],
        "final_answer": "",
        "auto_lesson": "",
    }

    # ---- Round 0: Independent proposals ----
    st.markdown('<div class="section-header">Round 0 — Independent Proposals</div>', unsafe_allow_html=True)
    cols = st.columns(min(len(agent_ids), 4))
    proposals = {}
    placeholders = {}

    for i, aid in enumerate(agent_ids):
        ag = team[aid]
        col = cols[i % len(cols)]
        with col:
            st.markdown(f"""<div class="chat-bubble-header">{ag['emoji']} {ag['name']}</div>""", unsafe_allow_html=True)
            placeholders[aid] = st.empty()
            placeholders[aid].markdown('<span class="status-dot status-thinking"></span> Thinking...', unsafe_allow_html=True)

    for i, aid in enumerate(agent_ids):
        ag = team[aid]
        user_prompt = (
            f"Task from the user: {task_text}\n\n"
            "Give your professional, independent proposal or answer. Be concise but complete."
        )
        reply = call_api(ag["api_slot"], ag["role"] + context, user_prompt)
        proposals[aid] = reply
        placeholders[aid].markdown(f'<div class="chat-bubble">{reply}</div>', unsafe_allow_html=True)

    transcript["round0"] = {team[aid]["name"]: text for aid, text in proposals.items()}

    # ---- Debate rounds ----
    for round_num in range(1, DEBATE_ROUNDS + 1):
        st.markdown(f'<div class="section-header">Debate Round {round_num}</div>', unsafe_allow_html=True)
        cols = st.columns(min(len(agent_ids), 4))
        new_proposals = {}
        round_placeholders = {}

        for i, aid in enumerate(agent_ids):
            ag = team[aid]
            col = cols[i % len(cols)]
            with col:
                st.markdown(f"""<div class="chat-bubble-header">{ag['emoji']} {ag['name']}</div>""", unsafe_allow_html=True)
                round_placeholders[aid] = st.empty()
                round_placeholders[aid].markdown('<span class="status-dot status-thinking"></span> Reviewing & revising...', unsafe_allow_html=True)

        for aid in agent_ids:
            ag = team[aid]
            others = "\n\n".join(
                f"{team[oid]['name']}'s position:\n{text}"
                for oid, text in proposals.items() if oid != aid
            )
            user_prompt = (
                f"Original task: {task_text}\n\n{others}\n\n"
                "Critique the other proposals where they're weak or wrong, "
                "acknowledge what's genuinely good, and give your "
                "OWN updated, improved position. Be specific and concise."
            )
            reply = call_api(ag["api_slot"], ag["role"] + context, user_prompt)
            new_proposals[aid] = reply
            round_placeholders[aid].markdown(f'<div class="chat-bubble">{reply}</div>', unsafe_allow_html=True)

        proposals = new_proposals
        transcript["debate_rounds"].append({team[aid]["name"]: text for aid, text in proposals.items()})

    # ---- Final Synthesis ----
    st.markdown('<div class="section-header">Final Synthesis</div>', unsafe_allow_html=True)
    # Find the lead agent (no reports_to)
    lead_id = next((aid for aid, ag in team.items() if not ag.get("reports_to")), agent_ids[0])
    lead = team[lead_id]

    with st.spinner(f"{lead['emoji']} {lead['name']} is synthesizing the final answer..."):
        all_positions = "\n\n".join(
            f"{team[aid]['name']}'s final position:\n{text}"
            for aid, text in proposals.items()
        )
        synthesis_prompt = (
            f"Original task: {task_text}\n\n{all_positions}\n\n"
            "You are the team lead. Combine the strongest points from all positions "
            "into ONE clear, professional, final answer. Note remaining disagreements briefly."
        )
        final = call_api(lead["api_slot"],
                         "You are the team lead synthesizing a team debate into one final answer.",
                         synthesis_prompt)
    st.markdown(f'<div class="chat-bubble" style="border-color: #4ade80;">{final}</div>', unsafe_allow_html=True)
    transcript["final_answer"] = final

    # ---- Auto self-learning ----
    with st.spinner("Team is reflecting on what they learned..."):
        reflection_prompt = (
            f"Task was: {task_text}\n\nFinal answer produced:\n{final}\n\n"
            "Reflect briefly: what went well in this debate? What was one mistake or "
            "weakness? State ONE concrete lesson for future tasks in one sentence."
        )
        lesson = call_api(lead["api_slot"],
                          "You are a team coach extracting one actionable lesson from this debate.",
                          reflection_prompt)
    if lesson and not lesson.startswith("⚠️"):
        transcript["auto_lesson"] = lesson
        memory["lessons"].append(
            f"[{datetime.now().strftime('%Y-%m-%d')}] Task: '{task_text[:60]}' -> {lesson.strip()}"
        )
        save_memory(memory)
        st.markdown(f"""
        <div class="agent-card" style="border-color: #4ade80;">
            <div class="chat-bubble-header">🧠 Auto-Lesson Learned</div>
            <div class="agent-desc">{lesson}</div>
        </div>
        """, unsafe_allow_html=True)

    return transcript

# ---------------------------------------------------------------------------
# RENDER PAST TRANSCRIPTS
# ---------------------------------------------------------------------------
def render_transcript(entry, team_snapshot=None):
    ts = entry.get("timestamp", "")
    with st.expander(f"🗨️ {ts} — {entry['task_text'][:60]}"):
        st.markdown("**Round 0 — Independent Proposals**")
        for name, text in entry.get("round0", {}).items():
            st.markdown(f"**{name}:**")
            st.write(text)
        for i, rd in enumerate(entry.get("debate_rounds", []), 1):
            st.markdown(f"**Debate Round {i}**")
            for name, text in rd.items():
                st.markdown(f"**{name}:**")
                st.write(text)
        st.markdown("**Final Answer**")
        st.success(entry.get("final_answer", ""))
        if entry.get("auto_lesson"):
            st.info(f"🧠 Lesson: {entry['auto_lesson']}")

# ---------------------------------------------------------------------------
# RENDER AGENT CARDS
# ---------------------------------------------------------------------------
def render_agent_card(ag, team):
    reports_name = ""
    if ag.get("reports_to") and ag["reports_to"] in team:
        reports_name = team[ag["reports_to"]]["name"]
    coords = [team[c]["name"] for c in ag.get("coordinates_with", []) if c in team]

    reports_html = f'<div class="reports-to">📤 Reports to: {reports_name}</div>' if reports_name else '<div class="reports-to">👑 Top-level / Lead</div>'
    coords_html = f'<div class="reports-to">🔗 Coordinates with: {", ".join(coords)}</div>' if coords else ''

    st.markdown(f"""
    <div class="agent-card">
        <div class="agent-card-header">
            <span style="font-size:1.6rem">{ag['emoji']}</span>
            <span class="agent-name">{ag['name']}</span>
            <span class="status-dot status-active"></span>
        </div>
        <div class="agent-desc">{ag['role'][:200]}</div>
        {reports_html}
        {coords_html}
    </div>
    """, unsafe_allow_html=True)

# ===================================================================
# MAIN APP
# ===================================================================
data = load_projects()
memory = load_memory()

# Check for missing keys
missing_keys = [k for k in ("GROQ_API_KEY", "OPENROUTER_API_KEY_BETA", "OPENROUTER_API_KEY_CHARLIE")
                if not os.environ.get(k)]

# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🏢 AI Company Builder")
    st.caption("Build your AI-powered team")

    if missing_keys:
        st.error(f"Missing: {', '.join(missing_keys)}")

    st.markdown("---")

    # Project selector
    st.markdown("### 📁 Projects")
    project_names = {pid: p["name"] for pid, p in data.get("projects", {}).items()}
    project_options = ["-- Select --"] + [f"{p['name']}" for p in data["projects"].values()]
    project_choice = st.selectbox("Choose project", project_options, label_visibility="collapsed")

    selected_project_id = None
    for pid, pname in project_names.items():
        if pname == project_choice:
            selected_project_id = pid
            break

    # New project creation
    with st.expander("➕ New Project", expanded=not selected_project_id):
        new_proj_name = st.text_input("Project name", key="new_proj_name")
        new_proj_desc = st.text_area("Describe your project (for AI team planning)", key="new_proj_desc",
                                     placeholder="e.g., Build a mobile app for tracking fitness goals...")
        team_mode = st.radio("Team setup mode", ["🤖 AI designs the team", "✏️ I'll build it manually"], key="team_mode")

        if st.button("🚀 Create Project", type="primary") and new_proj_name.strip():
            pid = new_id()
            new_project = {
                "name": new_proj_name.strip(),
                "description": new_proj_desc.strip(),
                "created": datetime.now().isoformat(timespec="seconds"),
                "team": {},
                "team_reasoning": "",
                "tasks": {},
            }

            if team_mode.startswith("🤖") and new_proj_desc.strip():
                with st.spinner("🤖 AI is designing your team..."):
                    plan = ai_plan_team(new_proj_desc.strip())
                    new_project["team"] = build_team_dict(plan.get("agents", []))
                    new_project["team_reasoning"] = plan.get("reasoning", "")
            else:
                # Default 3-agent team for manual mode
                default_agents = [
                    {"name": "Project Lead", "emoji": "👔",
                     "role": "Oversees the project, makes final decisions, synthesizes output.",
                     "reports_to": None, "coordinates_with": []},
                    {"name": "Specialist", "emoji": "💡",
                     "role": "Provides domain expertise and innovative solutions.",
                     "reports_to": "Project Lead", "coordinates_with": ["Project Lead"]},
                    {"name": "Reviewer", "emoji": "🔍",
                     "role": "Reviews work for errors, edge cases, and quality.",
                     "reports_to": "Project Lead", "coordinates_with": ["Specialist"]},
                ]
                new_project["team"] = build_team_dict(default_agents)
                new_project["team_reasoning"] = "Default team. Customize in the Team tab."

            data["projects"][pid] = new_project
            save_projects(data)
            st.rerun()

    # Task navigation (if project selected)
    selected_task_id = None
    selected_subtask_id = None

    if selected_project_id:
        project = data["projects"][selected_project_id]
        st.markdown("---")
        st.markdown(f"### 📋 Tasks in {project['name']}")
        task_names = {tid: t["name"] for tid, t in project.get("tasks", {}).items()}
        task_options = ["-- None --"] + list(task_names.values())
        task_choice = st.selectbox("Select task", task_options, label_visibility="collapsed")

        for tid, tname in task_names.items():
            if tname == task_choice:
                selected_task_id = tid
                break

        new_task = st.text_input("New task name", key="new_task_name")
        if st.button("➕ Add Task") and new_task.strip():
            tid = new_id()
            project["tasks"][tid] = {
                "name": new_task.strip(),
                "created": datetime.now().isoformat(timespec="seconds"),
                "status": "pending",
                "history": [],
                "subtasks": {},
            }
            save_projects(data)
            st.rerun()

        if selected_task_id:
            task = project["tasks"][selected_task_id]
            st.markdown("---")
            st.markdown(f"### 🔹 Subtasks")
            sub_names = {sid: s["name"] for sid, s in task.get("subtasks", {}).items()}
            sub_options = ["-- Task itself --"] + list(sub_names.values())
            sub_choice = st.selectbox("Select subtask", sub_options, label_visibility="collapsed")

            for sid, sname in sub_names.items():
                if sname == sub_choice:
                    selected_subtask_id = sid
                    break

            new_sub = st.text_input("New subtask", key="new_sub_name")
            if st.button("➕ Add Subtask") and new_sub.strip():
                sid = new_id()
                task["subtasks"][sid] = {
                    "name": new_sub.strip(),
                    "created": datetime.now().isoformat(timespec="seconds"),
                    "history": [],
                }
                save_projects(data)
                st.rerun()

# ---------------------------------------------------------------------------
# MAIN CONTENT AREA
# ---------------------------------------------------------------------------

# ---- No project selected: show dashboard overview ----
if not selected_project_id:
    st.markdown("# 🏢 AI Company Builder")
    st.caption("Create projects, build AI teams, watch them collaborate")

    metrics = compute_metrics(data, memory)
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        render_metric_card("📁", metrics["projects"], "Projects")
    with c2:
        render_metric_card("📋", metrics["tasks"], "Tasks")
    with c3:
        render_metric_card("🤖", metrics["agents"], "Agents")
    with c4:
        render_metric_card("▶️", metrics["runs"], "Runs")
    with c5:
        render_metric_card("🧠", metrics["lessons"], "Lessons")

    st.markdown("")

    if data["projects"]:
        st.markdown('<div class="section-header">Your Projects</div>', unsafe_allow_html=True)
        for pid, proj in data["projects"].items():
            team_count = len(proj.get("team", {}))
            task_count = len(proj.get("tasks", {}))
            st.markdown(f"""
            <div class="agent-card">
                <div class="agent-card-header">
                    <span style="font-size:1.4rem">📁</span>
                    <span class="agent-name">{proj['name']}</span>
                    <span class="agent-role-tag">{team_count} agents · {task_count} tasks</span>
                </div>
                <div class="agent-desc">{proj.get('description', 'No description')[:150]}</div>
                <div class="reports-to">Created: {proj.get('created', 'N/A')}</div>
            </div>
            """, unsafe_allow_html=True)

        # Show recent lessons
        if memory.get("lessons"):
            st.markdown('<div class="section-header">🧠 Recent Lessons Learned</div>', unsafe_allow_html=True)
            for lesson in reversed(memory["lessons"][-5:]):
                st.markdown(f"""<div class="chat-bubble" style="border-left: 3px solid #4ade80;">{lesson}</div>""", unsafe_allow_html=True)
    else:
        st.markdown("")
        st.markdown("""
        <div style="text-align: center; padding: 60px 20px;">
            <div style="font-size: 4rem; margin-bottom: 16px;">🚀</div>
            <div style="font-size: 1.4rem; color: #c8c8ff; font-weight: 600;">Create your first project</div>
            <div style="color: #8888aa; margin-top: 8px;">Use the sidebar to get started. Describe your project and let AI build your team.</div>
        </div>
        """, unsafe_allow_html=True)

# ---- Project selected: show project dashboard with tabs ----
else:
    project = data["projects"][selected_project_id]
    team = project.get("team", {})

    st.markdown(f"# {project['name']}")
    if project.get("description"):
        st.caption(project["description"][:200])

    tab_dashboard, tab_team, tab_work, tab_history = st.tabs(["📊 Dashboard", "👥 Team & Org Chart", "⚡ Work", "📜 History"])

    # =============== TAB: Dashboard ===============
    with tab_dashboard:
        # Project-specific metrics
        task_count = len(project.get("tasks", {}))
        run_count = sum(len(t.get("history", [])) for t in project.get("tasks", {}).values())
        run_count += sum(
            len(s.get("history", []))
            for t in project.get("tasks", {}).values()
            for s in t.get("subtasks", {}).values()
        )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            render_metric_card("👥", len(team), "Team Size")
        with c2:
            render_metric_card("📋", task_count, "Tasks")
        with c3:
            render_metric_card("▶️", run_count, "Total Runs")
        with c4:
            render_metric_card("🧠", len(memory.get("lessons", [])), "Lessons")

        if project.get("team_reasoning"):
            st.markdown("")
            st.markdown('<div class="section-header">🧠 Team Design Reasoning</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="chat-bubble">{project["team_reasoning"]}</div>', unsafe_allow_html=True)

        # Quick team overview
        if team:
            st.markdown("")
            st.markdown('<div class="section-header">Team Overview</div>', unsafe_allow_html=True)
            cols = st.columns(min(len(team), 3))
            for i, (aid, ag) in enumerate(team.items()):
                with cols[i % len(cols)]:
                    render_agent_card(ag, team)

    # =============== TAB: Team & Org Chart ===============
    with tab_team:
        st.markdown('<div class="section-header">📊 Organization Charts</div>', unsafe_allow_html=True)

        if team:
            chart_col1, chart_col2 = st.columns(2)

            with chart_col1:
                st.markdown("**Reporting Hierarchy**")
                st.caption("Solid lines = who reports to whom")
                try:
                    st.graphviz_chart(render_hierarchy_dot(team), use_container_width=True)
                except Exception as e:
                    st.warning(f"Could not render hierarchy chart: {e}")

            with chart_col2:
                st.markdown("**Coordination Network**")
                st.caption("Solid = reporting · Dashed = coordination")
                try:
                    st.graphviz_chart(render_coordination_dot(team), use_container_width=True)
                except Exception as e:
                    st.warning(f"Could not render coordination chart: {e}")

            # Agent detail cards
            st.markdown('<div class="section-header">👥 Team Members</div>', unsafe_allow_html=True)
            for aid, ag in team.items():
                render_agent_card(ag, team)

            # Manual team editing
            st.markdown('<div class="section-header">✏️ Edit Team</div>', unsafe_allow_html=True)
            with st.expander("Add a new agent"):
                new_ag_name = st.text_input("Agent title", key="new_ag_name")
                new_ag_emoji = st.text_input("Emoji (one character)", value="⚙️", key="new_ag_emoji")
                new_ag_role = st.text_area("Role description", key="new_ag_role")
                supervisor_options = ["None (top-level)"] + [f"{ag['emoji']} {ag['name']}" for ag in team.values()]
                new_ag_reports = st.selectbox("Reports to", supervisor_options, key="new_ag_reports")
                coord_options = [f"{ag['emoji']} {ag['name']}" for ag in team.values()]
                new_ag_coords = st.multiselect("Coordinates with", coord_options, key="new_ag_coords")

                if st.button("➕ Add Agent") and new_ag_name.strip():
                    aid = new_id()
                    # Find supervisor ID
                    sup_id = None
                    if new_ag_reports != "None (top-level)":
                        sup_name = new_ag_reports.split(" ", 1)[1] if " " in new_ag_reports else new_ag_reports
                        for sid, sag in team.items():
                            if sag["name"] == sup_name:
                                sup_id = sid
                                break
                    # Find coordination IDs
                    coord_ids = []
                    for c in new_ag_coords:
                        c_name = c.split(" ", 1)[1] if " " in c else c
                        for cid, cag in team.items():
                            if cag["name"] == c_name:
                                coord_ids.append(cid)
                                break

                    team[aid] = {
                        "name": new_ag_name.strip(),
                        "emoji": new_ag_emoji.strip() or "⚙️",
                        "role": new_ag_role.strip(),
                        "reports_to": sup_id,
                        "coordinates_with": coord_ids,
                        "api_slot": len(team) % max(len(API_SLOTS), 1),
                    }
                    save_projects(data)
                    st.rerun()

            # Remove agent
            with st.expander("Remove an agent"):
                remove_options = [f"{ag['emoji']} {ag['name']}" for aid, ag in team.items()]
                remove_choice = st.selectbox("Select agent to remove", remove_options, key="remove_ag")
                if st.button("🗑️ Remove Agent") and remove_choice:
                    rm_name = remove_choice.split(" ", 1)[1] if " " in remove_choice else remove_choice
                    rm_id = None
                    for rid, rag in team.items():
                        if rag["name"] == rm_name:
                            rm_id = rid
                            break
                    if rm_id and len(team) > 2:
                        del team[rm_id]
                        # Clean up references
                        for aid, ag in team.items():
                            if ag.get("reports_to") == rm_id:
                                ag["reports_to"] = None
                            if rm_id in ag.get("coordinates_with", []):
                                ag["coordinates_with"].remove(rm_id)
                        save_projects(data)
                        st.rerun()
                    elif rm_id:
                        st.warning("Team must have at least 2 agents.")
        else:
            st.info("No team configured yet. Create one using the sidebar's project setup.")

    # =============== TAB: Work ===============
    with tab_work:
        if not selected_task_id:
            st.info("👈 Select or create a task in the sidebar to start working.")
        else:
            task = project["tasks"][selected_task_id]
            node = task["subtasks"][selected_subtask_id] if selected_subtask_id else task
            breadcrumb = f"{project['name']} → {task['name']}"
            if selected_subtask_id:
                breadcrumb += f" → {node['name']}"

            st.markdown(f"### {breadcrumb}")

            if not team:
                st.warning("This project has no team. Go to the Team tab to set one up.")
            else:
                # Show which agents will work on this
                st.markdown("**Active team:**")
                agent_chips = " ".join(
                    f'<span class="agent-role-tag">{ag["emoji"]} {ag["name"]}</span>'
                    for ag in team.values()
                )
                st.markdown(agent_chips, unsafe_allow_html=True)
                st.markdown("")

                order_text = st.text_area(
                    "Give the team an order:",
                    placeholder="Describe what you want the team to work on...",
                    key=f"order_{selected_task_id}_{selected_subtask_id}",
                )

                if st.button("▶️ Run Team", type="primary") and order_text.strip():
                    st.divider()
                    transcript = run_debate(order_text.strip(), team, memory)
                    node["history"].append(transcript)
                    save_projects(data)

    # =============== TAB: History ===============
    with tab_history:
        all_entries = []
        for tid, t in project.get("tasks", {}).items():
            for entry in t.get("history", []):
                all_entries.append((t["name"], None, entry))
            for sid, s in t.get("subtasks", {}).items():
                for entry in s.get("history", []):
                    all_entries.append((t["name"], s["name"], entry))

        if all_entries:
            st.markdown(f'<div class="section-header">📜 All Runs ({len(all_entries)})</div>', unsafe_allow_html=True)
            # Sort newest first
            all_entries.sort(key=lambda x: x[2].get("timestamp", ""), reverse=True)
            for task_name, sub_name, entry in all_entries:
                label = f"{task_name}"
                if sub_name:
                    label += f" → {sub_name}"
                st.caption(label)
                render_transcript(entry)
        else:
            st.markdown("""
            <div style="text-align: center; padding: 40px;">
                <div style="font-size: 2.5rem; margin-bottom: 12px;">📭</div>
                <div style="color: #8888aa;">No runs yet. Go to the Work tab to start.</div>
            </div>
            """, unsafe_allow_html=True)
