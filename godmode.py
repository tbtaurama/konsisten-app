import sqlite3
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import altair as alt
import streamlit as st

# ==========================================
# KONFIGURASI SISTEM & ATURAN BISNIS
# ==========================================
st.set_page_config(page_title="RESET - Pro Mobile v11", layout="centered", initial_sidebar_state="collapsed")

WIB = ZoneInfo("Asia/Jakarta")

# REVISI: Level dipangkas hanya sampai Level 3
LEVELS = {
    1: {"days": 3},
    2: {"days": 7},
    3: {"days": 14}
}
REWARD = 10
DB_NAME = "reset_v11.db"

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

def reset_challenge_only():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM profile")
    conn.execute("DELETE FROM state")
    conn.execute("DELETE FROM logs")
    conn.execute("DELETE FROM badges")
    conn.commit()
    conn.close()

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
        penalty = day_t * 2
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
            # Hadiah premium sekarang dialihkan ke Level 3 karena ini adalah level akhir
            if lvl == 3:
                if pct == 1.0: badge_type = "Platinum 👑"
                elif pct >= 0.9: badge_type = "Premium 🌟"
            
            conn.execute("INSERT OR REPLACE INTO badges VALUES (?, ?)", (lvl, badge_type))
            if lvl == 3 and pct >= 0.9: just_graduated = True
            
            # Pengecekan batas level diubah ke Level 3
            if lvl < 3:
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
# KOMPONEN VISUAL KHUSUS (REVERTED & MOBILE)
# ==========================================
def render_likert_progress(current_lvl):
    """Render Skala Progress Bar Lama (titik berkedip) disesuaikan untuk 3 Level"""
    css = """
    <style>
    @keyframes pulse { 0% {transform: scale(1); opacity:1;} 50% {transform: scale(1.2); opacity:0.7;} 100% {transform: scale(1); opacity:1;} }
    .pulsing { animation: pulse 1.5s infinite; display: inline-block; }
    .likert-container { display: flex; justify-content: space-around; align-items: center; max-width: 300px; margin: 0 auto 15px auto; padding: 10px; background-color: #1e1e1e; border-radius: 10px; }
    .likert-item { text-align: center; }
    .likert-icon { font-size: 20px; }
    .likert-label { font-size: 12px; font-weight: bold; color: #888; margin-top: 5px; }
    </style>
    """
    html = "<div class='likert-container'>"
    # Perulangan disesuaikan dari 5 ke 3 level
    for i in range(1, 4):
        if i < current_lvl: icon, cls = "🟢", ""
        elif i == current_lvl: icon, cls = "🟡", "pulsing"
        else: icon, cls = "⚪", ""
        html += f"<div class='likert-item'><div class='likert-icon {cls}'>{icon}</div><div class='likert-label'>L{i}</div></div>"
    html += "</div>"
    st.markdown(css + html, unsafe_allow_html=True)

def render_eye_catching_progress(day_t, duration):
    """Render Banner Progress Hari yang jauh lebih eye-catching"""
    html = f"""
    <div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); padding: 15px; border-radius: 12px; text-align: center; margin-bottom: 25px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); border: 1px solid #3a62a8;">
        <p style="margin: 0; color: #a8c2f0; font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px;">Status Perjalanan</p>
        <h3 style="margin: 5px 0 0 0; color: white; font-size: 24px;">HARI KE-{day_t} <span style="color:#a8c2f0; font-size: 18px;">dari {duration} HARI</span></h3>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

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

profile = get_profile()

if not profile:
    st.title("⬛ R E S E T")
    st.write("Silakan isi data untuk masuk ke arena eksekusi.")
    with st.form("onboarding"):
        name = st.text_input("Nama Panggilan")
        theme = st.selectbox("Tema", ["Olah Raga", "Membuat Karya", "Wirausaha (Bisnis)", "Belajar/Membaca", "Mengerjakan Proyek", "Tugas Sekolah", "Cari Pekerjaan Baru", "Orang Tua & Anak", "Lainnya"])
        goal = st.text_input("Tujuan (Maks 100 Karakter)", max_chars=100)
        if st.form_submit_button("SUBMIT", use_container_width=True) and name and goal:
            save_profile(name, theme, goal)
            st.rerun()
else:
    name, theme, goal = profile
    process_missed_days()
    state = get_state()
    
    # ----------------------------------------
    # SIDEBAR: QA / GOD MODE CONTROLS
    # ----------------------------------------
    with st.sidebar:
        st.error("🛠️ **QA / GOD MODE**")
        if not state['completed']:
            next_sim_date = state['last_date'] + datetime.timedelta(days=1)
            st.write(f"Target Injeksi: Hari ke-{state['day']} (Level {state['level']})")
            c1, c2 = st.columns(2)
            if c1.button("✅ Check-In", type="primary", use_container_width=True):
                advance_one_day(next_sim_date, 'checked_in')
                st.rerun()
            if c2.button("❌ Bolos", type="secondary", use_container_width=True):
                advance_one_day(next_sim_date, 'missed')
                st.rerun()
        st.markdown("---")
        if st.button("♻️ Nuke Database", use_container_width=True):
            hard_reset_db()
            st.rerun()

    # ----------------------------------------
    # MAIN DASHBOARD 
    # ----------------------------------------
    st.caption(f"AGENT: **{name.upper()}** | SEKTOR: **{theme.upper()}**")
    st.markdown(f"<h4 style='color: #aaa; margin-bottom: 25px;'><i>\"{goal}\"</i></h4>", unsafe_allow_html=True)
    
    if state['completed']:
        st.success("🏁 PROTOKOL SELESAI. ANDA TELAH MENGUASAI DIRI ANDA SENDIRI.")
        st.balloons()
        
        st.markdown("### 🏆 SIKLUS TANTANGAN SELESAI")
        st.write("Silakan bagikan keberhasilan Anda atau mulai tantangan fokus baru.")
        
        col_end1, col_end2 = st.columns(2)
        with col_end1:
            whatsapp_msg = "Saya telah berhasil menjadi orang yang konsisten! %23RESET"
            wa_url = f"https://api.whatsapp.com/send?text={whatsapp_msg}"
            st.link_button("📢 Social Share", wa_url, use_container_width=True, type="primary")
            
        with col_end2:
            if st.button("🔄 Ganti Tantangan", use_container_width=True, type="secondary"):
                reset_challenge_only()
                st.rerun()
        st.stop()
        
    else:
        lvl = state['level']
        day_t = state['day']
        current_score = state['score']
        duration = LEVELS[lvl]['days']
        
        # 1. UI Progress Bar Titik Berkedip (Dikembalikan)
        render_likert_progress(lvl)
        
        # 2. UI Banner Progress Hari yang Eye-Catching (Dipertahankan)
        render_eye_catching_progress(day_t, duration)
        
        # 3. Metrik Skor & Target Lulus
        max_lvl_score = duration * REWARD
        passing_grade = int(0.75 * max_lvl_score)
        
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            prev_score = get_prev_score(lvl, day_t)
            st.metric("Poin Saat Ini", current_score, delta=int(current_score - prev_score))
        with col_m2:
            st.metric("Target Lulus", f"{passing_grade} pts", delta=f"Max: {max_lvl_score}", delta_color="off")
            
        # 4. Panel Eksekusi Tombol Utama
        now = datetime.datetime.now(WIB)
        today = now.date()
        is_time_valid = datetime.time(20, 0) <= now.time() <= datetime.time(23, 0)
        
        st.markdown("<hr style='margin-top: 10px; margin-bottom: 20px;'>", unsafe_allow_html=True)
        st.markdown("### ⏳ PANEL EKSEKUSI")
        
        if state['last_date'] >= today:
            st.success("✔️ Eksekusi harian dikonfirmasi. Kembali besok pukul 20:00 WIB.")
        else:
            if is_time_valid:
                st.success("✅ Arena Terbuka. Silakan tentukan pilihan Anda.")
            else:
                st.warning("🔒 Arena Tertutup. Tunggu pukul 20:00 - 23:00 WIB.")
                
            col_b1, col_b2 = st.columns(2)
            lbl_in = "🔥 CHECK-IN" if is_time_valid else "🔒 CHECK-IN"
            lbl_ms = "❌ BOLOS" if is_time_valid else "🔒 BOLOS"
            
            if col_b1.button(lbl_in, type="primary", disabled=not is_time_valid, use_container_width=True):
                advance_one_day(today, 'checked_in')
                st.rerun()
            if col_b2.button(lbl_ms, type="secondary", disabled=not is_time_valid, use_container_width=True):
                advance_one_day(today, 'missed')
                st.rerun()

        st.markdown("---")
        
        # 5. Visualisasi Grafik
        st.markdown("### 📈 TREN SKOR LEVEL INI")
        conn = sqlite3.connect(DB_NAME)
        df_logs = pd.read_sql_query("SELECT day, score FROM logs WHERE level=?", conn, params=(lvl,))
        conn.close()
        
        if not df_logs.empty:
            if not (state['last_date'] >= today and df_logs['day'].max() == day_t):
                df_logs = pd.concat([df_logs, pd.DataFrame([{'day': day_t, 'score': current_score}])], ignore_index=True)
                
            base_chart = alt.Chart(df_logs).mark_line(point=True, strokeWidth=3).encode(
                x=alt.X('day:Q', title="Hari ke-", scale=alt.Scale(domain=[1, duration], nice=False)),
                y=alt.Y('score:Q', title="Poin", scale=alt.Scale(domain=[0, max_lvl_score + 10])),
                tooltip=['day', 'score']
            )
            rule = alt.Chart(pd.DataFrame({'y': [passing_grade]})).mark_rule(color='red', strokeDash=[5, 5], strokeWidth=2).encode(y='y:Q')
            st.altair_chart((base_chart + rule).properties(height=250), use_container_width=True)
        else:
            st.info("Belum ada data eksekusi di level ini.")

    # Galeri Badge & Social Share (Disesuaikan untuk max 3 badge)
    st.markdown("---")
    st.markdown("### 🎖️ GALERI LENCANA")
    conn = sqlite3.connect(DB_NAME)
    badges = conn.execute("SELECT level, type FROM badges ORDER BY level ASC").fetchall()
    conn.close()
    
    if badges:
        # Menyesuaikan menjadi 3 kolom karena maksimal hanya ada 3 level
        cols = st.columns(3)
        for i, (b_lvl, b_type) in enumerate(badges):
            with cols[i % 3]:
                st.markdown(f"<div style='text-align:center; padding:10px; border:1px solid #555; border-radius:8px; font-size:14px;'><b>Lvl {b_lvl}</b><br>{b_type}</div>", unsafe_allow_html=True)
    else:
        st.caption("Belum ada lencana yang diraih.")
