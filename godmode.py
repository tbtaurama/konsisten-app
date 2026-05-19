import sqlite3
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import altair as alt
import streamlit as st

# ==========================================
# KONFIGURASI SISTEM & ATURAN BISNIS
# ==========================================
st.set_page_config(page_title="RESET - Pro", layout="centered", initial_sidebar_state="expanded")

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
DB_NAME = "reset_v7.db" # Database baru untuk skema chart yang bersih

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
    """Logika Early-Kill: Mengembalikan True jika secara matematis MUSTAHIL lulus"""
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
    
    # 1. Kalkulasi Harian
    if status == 'checked_in':
        score += REWARD
    else:
        penalty = PENALTY_BASE + (PENALTY_MULTIPLIER * day_t)
        score = max(0, score - penalty)
        
    # Catat ke log DULU agar historinya sempat terekam jika mau dianalisis
    conn = sqlite3.connect(DB_NAME)
    conn.execute("INSERT OR REPLACE INTO logs VALUES (?, ?, ?, ?, ?)", (target_date.isoformat(), lvl, day_t, status, score))
    
    # 2. LOGIKA EARLY-KILL
    if check_possibility_to_pass(score, day_t, duration):
        st.session_state['system_alert'] = "⚠️ Secara matematis Anda tidak mungkin lagi mencapai target. Arena di-reset untuk kesempatan kedua."
        # Reset Grafik: Hapus histori log untuk level yang gagal ini
        conn.execute("DELETE FROM logs WHERE level=?", (lvl,))
        # Reset State
        day_t = 1
        score = 0
        conn.execute("UPDATE state SET current_level=?, current_day=?, score=?, last_processed_date=? WHERE id=1", 
                     (lvl, day_t, score, target_date.isoformat()))
        conn.commit()
        conn.close()
        return

    # 3. EVALUASI NORMAL AKHIR LEVEL
    just_graduated = False
    if day_t == duration:
        max_score = duration * REWARD
        passing_grade = 0.75 * max_score
        
        if score >= passing_grade:
            # LULUS
            pct = score / max_score
            badge_type = "Umum 🥉"
            if lvl in [4, 5]:
                if pct == 1.0: badge_type = "Platinum 👑"
                elif pct >= 0.9: badge_type = "Premium 🌟"
            
            conn.execute("INSERT OR REPLACE INTO badges VALUES (?, ?)", (lvl, badge_type))
            if lvl in [4, 5] and pct >= 0.9: just_graduated = True
            
            if lvl < 5:
                # Naik Level, bersihkan persiapan grafik (opsional, tapi bagus agar aman)
                lvl += 1
                day_t = 1
                score = 0
            else:
                conn.execute("UPDATE state SET completed=1 WHERE id=1")
        else:
            # GAGAL NORMAL (Jaga-jaga jika Early-Kill terlewat di hari terakhir)
            st.session_state['system_alert'] = f"❌ GAGAL DI LEVEL {lvl}! Skor akhir di bawah Passing Grade. Arena di-reset."
            conn.execute("DELETE FROM logs WHERE level=?", (lvl,))
            day_t = 1
            score = 0
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
# KOMPONEN VISUAL KHUSUS
# ==========================================
def render_likert_progress(current_lvl):
    st.markdown("""
    <style>
    @keyframes pulse {
        0% { transform: scale(1); opacity: 1;}
        50% { transform: scale(1.3); opacity: 0.7;}
        100% { transform: scale(1); opacity: 1;}
    }
    .pulsing { animation: pulse 1.5s infinite; display: inline-block; }
    .likert-box { text-align: center; padding: 10px 0; }
    .likert-label { font-size: 14px; font-weight: 600; color: #888; margin-top: 5px; }
    </style>
    """, unsafe_allow_html=True)
    
    cols = st.columns(5)
    for i in range(1, 6):
        with cols[i-1]:
            if i < current_lvl:
                icon = "🟢"
                css_class = ""
            elif i == current_lvl:
                icon = "🟡"
                css_class = "pulsing"
            else:
                icon = "⚪"
                css_class = ""
                
            st.markdown(f"<div class='likert-box'><span class='{css_class}' style='font-size:24px;'>{icon}</span><br><div class='likert-label'>L{i}</div></div>", unsafe_allow_html=True)

def get_prev_score(lvl, current_day):
    """Mengambil skor di hari sebelumnya untuk kalkulasi Delta"""
    if current_day <= 1: return 0
    conn = sqlite3.connect(DB_NAME)
    res = conn.execute("SELECT score FROM logs WHERE level=? AND day=?", (lvl, current_day - 1)).fetchone()
    conn.close()
    return res[0] if res else 0

# ==========================================
# UI FRONTEND
# ==========================================
st.markdown("<style>h1, h2, h3 {text-align: center;}</style>", unsafe_allow_html=True)

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
        if st.form_submit_button("INISIASI PROTOKOL", use_container_width=True) and name and goal:
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
    st.markdown(f"<h4 style='text-align: center; color: #aaa;'><i>\"{goal}\"</i></h4>", unsafe_allow_html=True)
    st.markdown("---")
    
    if state['completed']:
        st.success("🏁 PROTOKOL SELESAI. ANDA TELAH MENGUASAI DIRI ANDA SENDIRI.")
        st.balloons()
    else:
        lvl = state['level']
        day_t = state['day']
        current_score = state['score']
        duration = LEVELS[lvl]['days']
        
        # 1. VISUALISASI SKALA LEVEL (LIKERT)
        render_likert_progress(lvl)
        st.markdown("<br>", unsafe_allow_html=True)
        
        # 2. METRIK POIN SAAT INI (DENGAN DELTA)
        prev_score = get_prev_score(lvl, day_t)
        delta_val = current_score - prev_score
        
        col1, col2, col3 = st.columns(3)
        with col2: # Taruh di tengah agar simetris
            st.metric("POIN SAAT INI", current_score, delta=int(delta_val))
            
        st.markdown("<hr style='margin-top: 5px; margin-bottom: 15px;'>", unsafe_allow_html=True)
        
        # STATUS LEVEL & HARI
        col_st1, col_st2 = st.columns(2)
        col_st1.metric("LEVEL SAAT INI", f"Level {lvl} ({duration} Hari)")
        col_st2.metric("PROGRES LEVEL", f"Hari {day_t} / {duration}")
        
        # KONTROL WAKTU
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
        
        # 3. VISUALISASI CHART (GRAFIK BERSIH PER LEVEL)
        st.markdown("### 📈 TREN SKOR LEVEL INI")
        conn = sqlite3.connect(DB_NAME)
        # HANYA tarik data log untuk level saat ini, mengamankan grafik agar tetap bersih
        df_logs = pd.read_sql_query("SELECT day, score FROM logs WHERE level=?", conn, params=(lvl,))
        conn.close()
        
        passing_grade = 0.75 * (duration * REWARD)
        
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
            st.info("Belum ada data eksekusi di level ini.")
            
        st.caption(f"Syarat Lulus (Garis Merah): {int(passing_grade)} Poin dari Maksimal {duration * REWARD} Poin.")

    # SOCIAL & BADGE
    if st.session_state.get('show_share', False):
        st.success("🎉 SELAMAT! Lulus Level Tinggi.")
        if st.button("📢 Bagikan Pencapaian (Social Share)"):
            st.code("Saya telah berhasil menjadi orang yang konsisten! #RESET90Days", language="markdown")
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
