import sqlite3
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import altair as alt
import streamlit as st

# ==========================================
# KONFIGURASI SISTEM & ATURAN BISNIS
# ==========================================
st.set_page_config(page_title="RESET - QA Mode v2", layout="centered", initial_sidebar_state="expanded")

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
DB_NAME = "reset_qa_v2.db" # Database baru untuk pengujian aturan Sudden Death

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
    conn.execute("DROP TABLE IF EXISTS profile")
    conn.execute("DROP TABLE IF EXISTS state")
    conn.execute("DROP TABLE IF EXISTS logs")
    conn.execute("DROP TABLE IF EXISTS badges")
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

def advance_one_day(target_date, status):
    state = get_state()
    if state['completed']: return
    
    lvl = state['level']
    day_t = state['day']
    score = state['score']
    duration = LEVELS[lvl]['days']
    max_score = duration * REWARD
    passing_grade = 0.75 * max_score
    
    # 1. Kalkulasi Aksi Harian
    if status == 'checked_in':
        score += REWARD
    else:
        penalty = PENALTY_BASE + (PENALTY_MULTIPLIER * day_t)
        score = max(0, score - penalty)
        
    # LOGIKA SUDDEN DEATH & PREDIKSI MATEMATIS
    remaining_days_after = duration - day_t
    harapan_final = score + (remaining_days_after * REWARD)
    
    if harapan_final < passing_grade:
        # EKSEKUSI RESET TOTAL (Sudden Death atau Gagal Normal di akhir)
        conn = sqlite3.connect(DB_NAME)
        conn.execute("DELETE FROM logs WHERE level=?", (lvl,)) # Bersihkan visual grafik
        conn.execute("UPDATE state SET current_day=1, score=0, last_processed_date=? WHERE id=1", (target_date.isoformat(),))
        conn.commit()
        conn.close()
        
        if remaining_days_after > 0:
            st.session_state['qa_alert'] = "💀 **SUDDEN DEATH TRIGGERED!** Skor maksimal yang bisa Anda raih sudah tidak dapat mengejar syarat kelulusan. Anda dikembalikan ke Hari 1 tanpa menyelesaikan level."
        else:
            st.session_state['qa_alert'] = f"❌ **GAGAL DI LEVEL {lvl}**: Skor akhir Anda di bawah Passing Grade. Anda dikembalikan ke Hari 1."
        return # Hentikan proses, kembali ke hari 1
        
    # 2. Catat Log Harian (Hanya jika lolos Sudden Death)
    conn = sqlite3.connect(DB_NAME)
    conn.execute("INSERT OR REPLACE INTO logs VALUES (?, ?, ?, ?, ?)", (target_date.isoformat(), lvl, day_t, status, score))
    
    just_graduated = False
    
    # 3. Evaluasi Lulus Level
    if day_t == duration:
        # Pasti lolos karena sudah di-filter oleh logika Sudden Death di atas
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
        day_t += 1
        
    conn.execute("UPDATE state SET current_level=?, current_day=?, score=?, last_processed_date=? WHERE id=1", 
                 (lvl, day_t, score, target_date.isoformat()))
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
# UI FRONTEND
# ==========================================
st.markdown("<style>h1, h2, h3 {text-align: center;}</style>", unsafe_allow_html=True)

# Notifikasi Sudden Death / Reset
if 'qa_alert' in st.session_state:
    st.error(st.session_state['qa_alert'])
    del st.session_state['qa_alert']

profile = get_profile()

if not profile:
    st.title("⬛ R E S E T [QA V2]")
    st.write("Silakan inisiasi protokol baru.")
    with st.form("onboarding"):
        name = st.text_input("Nama Panggilan")
        theme = st.selectbox("Tema", ["Olah Raga", "QA Testing", "Lainnya"])
        goal = st.text_input("Tujuan", max_chars=100)
        if st.form_submit_button("INISIASI", use_container_width=True) and name and goal:
            save_profile(name, theme, goal)
            st.rerun()
else:
    name, theme, goal = profile
    process_missed_days()
    state = get_state()
    
    # ----------------------------------------
    # SIDEBAR: QA / GOD MODE
    # ----------------------------------------
    with st.sidebar:
        st.error("🛠️ **QA / GOD MODE**")
        if not state['completed']:
            next_sim_date = state['last_date'] + datetime.timedelta(days=1)
            st.write(f"**Target Injeksi:** Hari ke-{state['day']} (Level {state['level']})")
            
            c1, c2 = st.columns(2)
            if c1.button("✅ Paksa\nCheck-In", type="primary", use_container_width=True):
                advance_one_day(next_sim_date, 'checked_in')
                st.rerun()
            if c2.button("❌ Paksa\nBolos", type="secondary", use_container_width=True):
                advance_one_day(next_sim_date, 'missed')
                st.rerun()
        
        st.markdown("---")
        if st.button("♻️ Nuke/Reset Database", use_container_width=True):
            hard_reset_db()
            st.rerun()

    # ----------------------------------------
    # MAIN DASHBOARD
    # ----------------------------------------
    st.caption(f"AGENT: **{name.upper()}** | SEKTOR: **{theme.upper()}**")
    st.markdown(f"<h4 style='text-align: center; color: #aaa;'><i>\"{goal}\"</i></h4>", unsafe_allow_html=True)
    st.markdown("---")
    
    if state['completed']:
        st.success("🏁 PROTOKOL SELESAI. TESTING TAMAT MENCAPAI AKHIR LEVEL 5.")
        st.balloons()
    else:
        lvl = state['level']
        day_t = state['day']
        current_score = state['score']
        duration = LEVELS[lvl]['days']
        passing_grade = int(0.75 * duration * REWARD)
        
        # Kalkulasi Harapan Skor (Peluang Tersisa)
        sisa_hari_potensial = duration - day_t + 1
        harapan_skor_final = current_score + (sisa_hari_potensial * REWARD)
        
        # UI: STATUS PROGRESS
        col1, col2 = st.columns(2)
        col1.metric("LEVEL SAAT INI", f"Level {lvl} ({duration} Hari)")
        col2.metric("PROGRES LEVEL", f"Hari {day_t} / {duration}")
        
        # UI: VISUALISASI POIN SAAT INI (FEATURE BARU)
        st.markdown("### 📊 METRIK PERFORMA")
        m1, m2, m3 = st.columns(3)
        m1.metric("Skor Saat Ini", current_score)
        m2.metric("Passing Grade", passing_grade)
        
        # Logika Delta Indikator Warna
        delta_val = harapan_skor_final - passing_grade
        if delta_val >= 10:
            delta_str = f"Aman (+{delta_val})"
            d_color = "normal"
        elif delta_val >= 0:
            delta_str = f"Kritis (+{delta_val})"
            d_color = "off"
        else:
            delta_str = "Gagal"
            d_color = "inverse"
            
        m3.metric("Harapan Skor Final", harapan_skor_final, delta=delta_str, delta_color=d_color)
        
        # KONTROL WAKTU (PANEL EKSEKUSI)
        now = datetime.datetime.now(WIB)
        today = now.date()
        
        st.write("")
        st.markdown("### ⏳ PANEL EKSEKUSI")
        if state['last_date'] >= today:
            st.success("✔️ Eksekusi harian dikonfirmasi (Atau disimulasi oleh QA).")
        else:
            if datetime.time(20, 0) <= now.time() <= datetime.time(23, 0):
                if st.button("🔥 CHECK-IN SEKARANG 🔥", use_container_width=True, type="primary"):
                    advance_one_day(today, 'checked_in')
                    st.rerun()
            else:
                st.error("🔒 ARENA BELUM DIBUKA ATAU HANGUS. (20:00 - 23:00 WIB)")
                st.info("💡 *Gunakan Panel QA di sebelah kiri untuk Bypass.*")

        st.markdown("---")
        
        # VISUALISASI GRAFIK
        st.markdown("### 📈 TREN SKOR LEVEL INI")
        conn = sqlite3.connect(DB_NAME)
        df_logs = pd.read_sql_query("SELECT day, score FROM logs WHERE level=?", conn, params=(lvl,))
        conn.close()
        
        if not df_logs.empty:
            if not (state['last_date'] >= today and df_logs['day'].max() == day_t):
                df_logs = pd.concat([df_logs, pd.DataFrame([{'day': day_t, 'score': current_score}])], ignore_index=True)
                
            base_chart = alt.Chart(df_logs).mark_line(point=True, strokeWidth=3).encode(
                x=alt.X('day:Q', title="Hari ke-", scale=alt.Scale(domain=[1, duration], nice=False)),
                y=alt.Y('score:Q', title="Poin", scale=alt.Scale(domain=[0, duration * REWARD + 10])),
                tooltip=['day', 'score']
            )
            rule = alt.Chart(pd.DataFrame({'y': [passing_grade]})).mark_rule(color='red', strokeDash=[5, 5], strokeWidth=2).encode(y='y:Q')
            st.altair_chart((base_chart + rule).properties(height=300), use_container_width=True)
        else:
            st.info("Grafik telah di-reset. Lintasan kosong dan siap untuk eksekusi baru.")

    # SOCIAL & BADGE
    if st.session_state.get('show_share', False):
        st.success("🎉 SELAMAT! Lulus Level Tinggi.")
        if st.button("📢 Bagikan Pencapaian (Social Share)"):
            st.code("Saya konsisten! #RESET", language="markdown")
            st.session_state['show_share'] = False

    st.markdown("---")
    st.markdown("### 🎖️ GALERI LENCANA")
    conn = sqlite3.connect(DB_NAME)
    badges = conn.execute("SELECT level, type FROM badges ORDER BY level ASC").fetchall()
    conn.close()
    
    if badges:
        cols = st.columns(5)
        for i, (b_lvl, b_type) in enumerate(badges):
            with cols[i % 5]:
                st.markdown(f"<div style='text-align:center; padding:10px; border:1px solid #555; border-radius:5px;'><b>Lvl {b_lvl}</b><br>{b_type}</div>", unsafe_allow_html=True)
    else:
        st.caption("Belum ada lencana yang diraih.")
