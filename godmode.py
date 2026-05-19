import sqlite3
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import altair as alt
import streamlit as st

# ==========================================
# KONFIGURASI SISTEM & ATURAN BISNIS
# ==========================================
st.set_page_config(page_title="RESET - Pro Mobile", layout="centered", initial_sidebar_state="collapsed")

WIB = ZoneInfo("Asia/Jakarta")

LEVELS = {
    1: {"days": 3},
    2: {"days": 7},
    3: {"days": 14},
    4: {"days": 21},
    5: {"days": 45}
}
REWARD = 10
PENALTY_BASE = 10
PENALTY_MULTIPLIER = 2
DB_NAME = "reset_v8.db"

# ==========================================
# DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY, name TEXT, theme TEXT, goal TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, current_level INTEGER, current_day INTEGER, score INTEGER, last_processed_date TEXT, completed INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs (date TEXT, level INTEGER, day INTEGER, status TEXT, score INTEGER, PRIMARY KEY (date, level, day))''')
    c.execute('''CREATE TABLE IF NOT EXISTS badges (level INTEGER, type TEXT, PRIMARY KEY (level, type))''')
    conn.commit()
    conn.close()

def hard_reset_db():
    conn = sqlite3.connect(DB_NAME)
    for table in ["profile", "state", "logs", "badges"]:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    conn.close()
    init_db()

init_db()

# ==========================================
# CORE LOGIC (BACKEND)
# ==========================================
def get_profile():
    conn = sqlite3.connect(DB_NAME)
    res = conn.execute("SELECT name, theme, goal FROM profile WHERE id=1").fetchone()
    conn.close()
    return res

def save_profile(name, theme, goal):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("INSERT OR REPLACE INTO profile (id, name, theme, goal) VALUES (1, ?, ?, ?)", (name, theme, goal))
    check = conn.execute("SELECT id FROM state WHERE id=1").fetchone()
    if not check:
        yesterday = (datetime.datetime.now(WIB).date() - datetime.timedelta(days=1)).isoformat()
        conn.execute("INSERT INTO state (id, current_level, current_day, score, last_processed_date, completed) VALUES (1, 1, 1, 0, ?, 0)", (yesterday,))
    conn.commit()
    conn.close()

def get_state():
    conn = sqlite3.connect(DB_NAME)
    res = conn.execute("SELECT current_level, current_day, score, last_processed_date, completed FROM state WHERE id=1").fetchone()
    conn.close()
    if res:
        return {"level": res[0], "day": res[1], "score": res[2], "last_date": datetime.date.fromisoformat(res[3]), "completed": bool(res[4])}
    return None

def check_possibility_to_pass(current_score, current_day, duration):
    remaining_days = duration - current_day
    max_possible_points = current_score + (remaining_days * REWARD)
    passing_grade = 0.75 * (duration * REWARD)
    return max_possible_points < passing_grade

def advance_one_day(target_date, status):
    state = get_state()
    if state['completed']: return
    
    lvl = state['level']
    day_t = state['day']
    score = state['score']
    duration = LEVELS[lvl]['days']
    
    if status == 'checked_in':
        score += REWARD
    else:
        penalty = PENALTY_BASE + (PENALTY_MULTIPLIER * day_t)
        score = max(0, score - penalty)
        
    conn = sqlite3.connect(DB_NAME)
    conn.execute("INSERT OR REPLACE INTO logs VALUES (?, ?, ?, ?, ?)", (target_date.isoformat(), lvl, day_t, status, score))
    
    if check_possibility_to_pass(score, day_t, duration):
        st.session_state['system_alert'] = "⚠️ Secara matematis Anda tidak mungkin lagi mencapai target. Arena di-reset untuk kesempatan kedua."
        conn.execute("DELETE FROM logs WHERE level=?", (lvl,))
        conn.execute("UPDATE state SET current_level=?, current_day=?, score=?, last_processed_date=? WHERE id=1", (lvl, 1, 0, target_date.isoformat()))
        conn.commit()
        conn.close()
        return

    just_graduated = False
    if day_t == duration:
        max_score = duration * REWARD
        passing_grade = 0.75 * max_score
        
        if score >= passing_grade:
            pct = score / max_score
            badge_type = "Umum 🥉"
            if lvl in [4, 5]:
                if pct == 1.0: badge_type = "Platinum 👑"
                elif pct >= 0.9: badge_type = "Premium 🌟"
            
            conn.execute("INSERT OR REPLACE INTO badges VALUES (?, ?)", (lvl, badge_type))
            if lvl in [4, 5] and pct >= 0.9: just_graduated = True
            
            if lvl < 5:
                lvl += 1
                day_t = 1
                score = 0
            else:
                conn.execute("UPDATE state SET completed=1 WHERE id=1")
        else:
            st.session_state['system_alert'] = f"❌ GAGAL DI LEVEL {lvl}! Skor akhir di bawah Passing Grade. Arena di-reset."
            conn.execute("DELETE FROM logs WHERE level=?", (lvl,))
            day_t = 1
            score = 0
    else:
        day_t += 1
        
    conn.execute("UPDATE state SET current_level=?, current_day=?, score=?, last_processed_date=? WHERE id=1", (lvl, day_t, score, target_date.isoformat()))
    conn.commit()
    conn.close()
    if just_graduated: st.session_state['show_share'] = True

def process_missed_days():
    state = get_state()
    if not state or state['completed']: return
    today = datetime.datetime.now(WIB).date()
    last_date = state['last_date']
    
    while last_date < today - datetime.timedelta(days=1):
        target_missed_date = last_date + datetime.timedelta(days=1)
        advance_one_day(target_missed_date, 'missed')
        last_date = target_missed_date

# ==========================================
# KOMPONEN VISUAL KHUSUS (MOBILE FRIENDLY)
# ==========================================
def render_likert_progress(current_lvl):
    """Render Likert Scale menggunakan CSS Flexbox agar pas di Mobile"""
    css = """
    <style>
    @keyframes pulse { 0% {transform: scale(1); opacity:1;} 50% {transform: scale(1.2); opacity:0.7;} 100% {transform: scale(1); opacity:1;} }
    .pulsing { animation: pulse 1.5s infinite; display: inline-block; }
    .likert-container { display: flex; justify-content: space-between; align-items: center; max-width: 350px; margin: 0 auto 15px auto; padding: 10px; background-color: #1e1e1e; border-radius: 10px; }
    .likert-item { text-align: center; }
    .likert-icon { font-size: 16px; }
    .likert-label { font-size: 10px; font-weight: bold; color: #888; margin-top: 3px; }
    </style>
    """
    html = "<div class='likert-container'>"
    for i in range(1, 6):
        if i < current_lvl: icon, cls = "🟢", ""
        elif i == current_lvl: icon, cls = "🟡", "pulsing"
        else: icon, cls = "⚪", ""
        html += f"<div class='likert-item'><div class='likert-icon {cls}'>{icon}</div><div class='likert-label'>L{i}</div></div>"
    html += "</div>"
    
    st.markdown(css + html, unsafe_allow_html=True)

def get_prev_score(lvl, current_day):
    if current_day <= 1: return 0
    conn = sqlite3.connect(DB_NAME)
    res = conn.execute("SELECT score FROM logs WHERE level=? AND day=?", (lvl, current_day - 1)).fetchone()
    conn.close()
    return res[0] if res else 0

# ==========================================
# UI FRONTEND UTAMA
# ==========================================
st.markdown("<style>h1, h2, h3, h4, h5 {text-align: center;}</style>", unsafe_allow_html=True)

if 'system_alert' in st.session_state:
    st.error(st.session_state['system_alert'])
    del st.session_state['system_alert']
