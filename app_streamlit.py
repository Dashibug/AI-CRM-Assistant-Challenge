# src/app_streamlit.py

import os
import streamlit as st
import pandas as pd
from datetime import datetime
import base64
from io import BytesIO
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.rl_config import TTFSearchPath
from src.data_loader import fetch_leads, normalize_to_df, create_task
from src.llm_client import LLMClient
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


BASE = os.getenv("KOMMO_BASE_URL", "").rstrip("/")

# ---------------- Kommo-like styles ----------------
KOMMO_CSS = """
<style>
:root {
  --kommo-primary: #6a5cff;
  --kommo-primary-2: #8b7cff;
  --kommo-bg: #f6f7fb;
  --kommo-card: #ffffff;
  --kommo-text: #1f1f2e;
  --kommo-muted: #6b7080;
  --kommo-green: #21c17a;
  --kommo-yellow: #ffcc00;
  --kommo-red: #ff5a5f;
  --kommo-border: #e6e8ef;
  --radius: 18px;
}
section.main > div {background: var(--kommo-bg) !important;}

/* header */
.kommo-header {
  background: linear-gradient(135deg, var(--kommo-primary), var(--kommo-primary-2));
  color: white; border-radius: 20px; padding: 22px 24px; margin-bottom: 14px;
  box-shadow: 0 10px 30px rgba(106, 92, 255, 0.18);
}
.kommo-title {font-size: 22px; font-weight: 700; margin: 0 0 6px 0;}
.kommo-subtitle {opacity: 0.9; font-size: 14px; margin: 0;}

/* СТИЛЬ ДЛЯ streamlit-КНОПКИ (глобально) */
.stButton > button {
  background: #ffffff;
  color: #3a2fff;
  border: 1px solid rgba(255,255,255,0.6);
  padding: 10px 16px;
  border-radius: 12px;
  font-weight: 800;
  box-shadow: 0 8px 22px rgba(31,31,46,0.08);
}
.stButton > button:hover { background: #f7f6ff; }

/* не трогаем кнопку скачивания */
.stDownloadButton > button {
  background: #fff; color: var(--kommo-text);
  border: 1px solid var(--kommo-border); border-radius: 12px;
}

/* KPI и карточки */
.kpi-row {display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 10px 0 18px;}
.kpi-card {background: var(--kommo-card); border: 1px solid var(--kommo-border); border-radius: var(--radius); padding: 14px 16px; box-shadow: 0 6px 18px rgba(31,31,46,0.04);}
.kpi-label {color: var(--kommo-muted); font-size: 12px; margin-bottom: 6px;}
.kpi-value {color: var(--kommo-text); font-size: 22px; font-weight: 800;}

.lead-card {background: var(--kommo-card); border: 1px solid var(--kommo-border); border-radius: var(--radius); padding: 14px 16px; margin-bottom: 10px; box-shadow: 0 8px 22px rgba(31,31,46,0.05);}
.lead-head {display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;}
.lead-name {font-weight: 750; font-size: 16px; color: var(--kommo-text);}
.lead-sec {color: var(--kommo-muted); font-size: 12px;}
.badge {font-size: 12px; font-weight: 800; padding: 4px 10px; border-radius: 999px; border: 1px solid transparent;}
.badge.red { background: #ffe9ea; color: var(--kommo-red); border-color: #ffd1d4; }
.badge.yellow { background: #fff7dd; color: #b58900; border-color: #ffe9a8; }
.badge.green { background: #e9fbf3; color: var(--kommo-green); border-color: #c8f3df; }
.lead-body {color: var(--kommo-text); font-size: 13px; line-height: 1.45;}
.lead-actions {margin-top: 10px; display:flex; gap:10px; flex-wrap: wrap;}
.link-btn {display:inline-block; padding:8px 12px; border-radius: 10px; text-decoration:none; border:1px solid var(--kommo-border); background:#fff; color: var(--kommo-text); font-weight:700;}
</style>
"""

st.set_page_config(page_title="AI CRM Deal Risk Radar — LLM", layout="wide")

# ---------------- Header ----------------
st.markdown(KOMMO_CSS, unsafe_allow_html=True)
st.markdown(
    """
    <div class="kommo-header">
      <div class="kommo-title">🤖 AI CRM Risk Assistant</div>
      <p class="kommo-subtitle">Kommo → LLM-оценка риска → приоритеты и действия</p>
    </div>
    """,
    unsafe_allow_html=True
)

# --- Controls / globals ---
refresh_clicked = st.button("Посмотреть риски", key="refresh_btn")
SLA_DAYS = int(os.getenv("SLA_DAYS", "2"))

def _task_text(row: pd.Series) -> str:
    return (f"[Сделка #{row['deal_id']}] Риск: {row['risk_level']}. "
            f"Причина: {row['risk_reason']}. Действие: {row['action']}")

def _deadline_today_18() -> int:
    now = datetime.now()
    return int(datetime(now.year, now.month, now.day, 18, 0, 0).timestamp())

# ---- fonts: лежат в src/fonts ----
ROOT = os.path.dirname(__file__)
FONTS_DIR = os.path.join(ROOT, "src", "fonts")
TTFSearchPath.append(FONTS_DIR)

FONT_REGULAR = os.path.join(FONTS_DIR, "DejaVuSans.ttf")
FONT_BOLD    = os.path.join(FONTS_DIR, "DejaVuSans-Bold.ttf")

USING_DEJAVU = False
if not os.path.exists(FONT_REGULAR):
    st.error(f"Не найден шрифт: {FONT_REGULAR}")
else:
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", FONT_REGULAR))
        if os.path.exists(FONT_BOLD):
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_BOLD))
            pdfmetrics.registerFont(TTFont("DejaVu-Italic", FONT_REGULAR))
            pdfmetrics.registerFont(TTFont("DejaVu-BoldItalic", FONT_BOLD))
        else:
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_REGULAR))
            pdfmetrics.registerFont(TTFont("DejaVu-Italic", FONT_REGULAR))
            pdfmetrics.registerFont(TTFont("DejaVu-BoldItalic", FONT_REGULAR))

        addMapping('DejaVu', 0, 0, 'DejaVu')
        addMapping('DejaVu', 0, 1, 'DejaVu-Italic')
        addMapping('DejaVu', 1, 0, 'DejaVu-Bold')
        addMapping('DejaVu', 1, 1, 'DejaVu-BoldItalic')
        USING_DEJAVU = True
    except Exception as e:
        st.error(f"Ошибка регистрации шрифта: {e}")

def get_pdf_download_link(pdf_bytes: bytes, filename: str, link_text: str = "Скачать отчёт (PDF)") -> str:
    """
    Возвращает HTML <a> с data:application/pdf;base64,....
    """
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    href = f'<a href="data:application/pdf;base64,{b64}" download="{filename}" ' \
           f'style="display:inline-block;padding:10px 14px;border-radius:10px;' \
           f'background:#6a5cff;color:#fff;font-weight:700;text-decoration:none;">{link_text}</a>'
    return href

def _digest_pdf(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm,
        title="Отчёт по рискам сделок"
    )

    styles = getSampleStyleSheet()
    base_font = 'DejaVu' if USING_DEJAVU else styles['Normal'].fontName
    bold_font = 'DejaVu-Bold' if USING_DEJAVU else styles['Heading1'].fontName

    # стили
    styles.add(ParagraphStyle(name="H1", fontName=bold_font, fontSize=18, leading=22, spaceAfter=8))
    styles.add(ParagraphStyle(name="H2", fontName=bold_font, fontSize=13, leading=17, spaceBefore=8, spaceAfter=6))
    styles.add(ParagraphStyle(name="P",  fontName=base_font, fontSize=10.5, leading=14))
    styles.add(ParagraphStyle(name="Small", fontName=base_font, fontSize=9, leading=12, textColor=colors.grey))
    styles.add(ParagraphStyle(name="Wrap", fontName=base_font, fontSize=9.5, leading=12.5, wordWrap='CJK'))  # переносы

    def P(text, style="P"):
        return Paragraph(text, styles[style])

    def _fmt_money(x):
        try:
            return f"{int(x):,}".replace(",", " ")
        except Exception:
            return str(x)

    red = df[df["risk_level"] == "red"]
    yellow = df[df["risk_level"] == "yellow"]
    total_red = int(red["deal_value"].sum()) if "deal_value" in df.columns else 0

    elems = []
    elems.append(P("Ежедневный отчёт по рискам", "H1"))
    elems.append(P(f"Сформировано: <b>{datetime.now().strftime('%d.%m.%Y %H:%M')}</b>", "Small"))
    elems.append(Spacer(1, 6))

    # KPI
    kpi_data = [
        [P("<b>Красные</b>", "Small"), P("<b>Сумма сделок в красной зоне, ₽</b>", "Small"), P("<b>Жёлтые</b>", "Small")],
        [P(str(len(red))), P(_fmt_money(total_red)), P(str(len(yellow)))]
    ]
    kpi_tbl = Table(kpi_data, colWidths=[55*mm, 60*mm, 40*mm])
    kpi_tbl.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), base_font),
        ('FONTSIZE', (0,1), (-1,1), 14),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('ALIGN', (0,1), (-1,1), 'CENTER'),
        ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
        ('BOX', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.lightgrey),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('TOPPADDING', (0,1), (-1,1), 3),
        ('BOTTOMPADDING', (0,1), (-1,1), 5),
    ]))
    elems.append(kpi_tbl)
    elems.append(Spacer(1, 8))

    # ===== TOP-5 КРАСНЫХ =====
    elems.append(P("ТОП-5 красных сделок", "H2"))
    top_red = red.sort_values("deal_value", ascending=False).head(5) if "deal_value" in df.columns else red.head(5)

    if top_red.empty:
        elems.append(P("Нет критичных сделок", "P"))
    else:
        # фиксированные колонки
        w_id = 18*mm
        w_lead = 35*mm
        w_sum = 22*mm
        w_last = 28*mm
        w_lvl = 16*mm
        w_link = 14*mm

        fixed = w_id + w_lead + w_sum + w_last + w_lvl + w_link
        avail = doc.width
        rest = max(20*mm, avail - fixed)  # остаток под Причину+Действие
        w_reason = rest * 0.55
        w_action = rest * 0.45

        header = [P("<b>ID</b>"), P("<b>Лид</b>"), P("<b>Сумма, ₽</b>"), P("<b>Последний контакт</b>"),
                  P("<b>Уровень</b>"), P("<b>Причина</b>"), P("<b>Действие</b>"), P("<b>Kommo</b>")]
        rows = [header]

        for _, r in top_red.iterrows():
            link = r.get("kommo") or ""
            link_txt = '<u>Откр.</u>' if link else "—"
            rows.append([
                P(str(r.get("deal_id","—"))),
                P(str(r.get("client_name","—"))),
                P(_fmt_money(r.get("deal_value", 0))),
                P(str(r.get("last_contact_date","—"))),
                P(str(r.get("risk_level","—")).upper()),
                Paragraph(str(r.get("risk_reason","—")), styles["Wrap"]),
                Paragraph(str(r.get("action","—")), styles["Wrap"]),
                (Paragraph(f'<a href="{link}">{link_txt}</a>', styles["P"]) if link else P("—"))
            ])

        col_widths = [w_id, w_lead, w_sum, w_last, w_lvl, w_reason, w_action, w_link]
        t = Table(rows, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), base_font),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LINEBELOW', (0,0), (-1,0), 0.8, colors.black),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.white]),
            ('BOX', (0,0), (-1,-1), 0.5, colors.lightgrey),
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.lightgrey),
            ('LEFTPADDING', (0,0), (-1,-1), 3),
            ('RIGHTPADDING', (0,0), (-1,-1), 3),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))
        elems.append(t)

    # ===== ЖЁЛТЫЕ (топ-10) =====
    if not yellow.empty:
        elems.append(Spacer(1, 10))
        elems.append(P("Жёлтые сделки (топ-10 по сумме)", "H2"))

        w_id = 18*mm
        w_lead = 35*mm
        w_sum = 22*mm
        w_last = 28*mm
        fixed = w_id + w_lead + w_sum + w_last
        rest = max(20*mm, doc.width - fixed)
        w_reason = rest * 0.50
        w_action = rest * 0.50

        header = [P("<b>ID</b>"), P("<b>Лид</b>"), P("<b>Сумма, ₽</b>"), P("<b>Последний контакт</b>"),
                  P("<b>Причина</b>"), P("<b>Действие</b>")]
        rows = [header]

        yv = yellow.sort_values("deal_value", ascending=False).head(10) if "deal_value" in yellow.columns else yellow.head(10)
        for _, r in yv.iterrows():
            rows.append([
                P(str(r.get("deal_id","—"))),
                P(str(r.get("client_name","—"))),
                P(_fmt_money(r.get("deal_value", 0))),
                P(str(r.get("last_contact_date","—"))),
                Paragraph(str(r.get("risk_reason","—")), styles["Wrap"]),
                Paragraph(str(r.get("action","—")), styles["Wrap"])
            ])

        col_widths = [w_id, w_lead, w_sum, w_last, w_reason, w_action]
        yt = Table(rows, colWidths=col_widths, repeatRows=1)
        yt.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), base_font),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LINEBELOW', (0,0), (-1,0), 0.8, colors.black),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.white]),
            ('BOX', (0,0), (-1,-1), 0.5, colors.lightgrey),
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.lightgrey),
            ('LEFTPADDING', (0,0), (-1,-1), 3),
            ('RIGHTPADDING', (0,0), (-1,-1), 3),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))
        elems.append(yt)

    elems.append(Spacer(1, 8))
    elems.append(P("Примечание: уровень риска и действия рассчитаны LLM на основе последних коммуникаций и метрик активности."
                   "Ссылки работают в PDF-ридерах с поддержкой переходов.", "Small"))

    doc.build(elems)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

def kommo_url(deal_id: str) -> str:
    return f"{BASE}/leads/detail/{deal_id}" if BASE and str(deal_id).strip() else ""

def _days_since_any(s: str | None) -> int:
    """Для last_contact_days: если даты нет — трактуем как 'очень давно'."""
    if not s:
        return 9999
    try:
        dt = pd.to_datetime(s, utc=False, errors="coerce")
        if pd.isna(dt): return 9999
        return max(0, int((pd.Timestamp(datetime.now()) - dt).days))
    except Exception:
        return 9999

def _stage_age_days(s: str | None) -> int:
    """Для возраста стадии: если даты нет — НЕ штрафуем (0)."""
    if not s:
        return 0
    try:
        dt = pd.to_datetime(s, utc=False, errors="coerce")
        if pd.isna(dt): return 0
        return max(0, int((pd.Timestamp(datetime.now()) - dt).days))
    except Exception:
        return 0

# ---------------- Main flow ----------------
# 1) При клике «Обновить» — загрузка и скоринг, кладём в session_state
if refresh_clicked:
    with st.spinner("Загружаем сделки из Kommo..."):
        leads = fetch_leads(limit=200)
        df = normalize_to_df(leads, fetch_notes=True)

    if df is None or df.empty:
        st.warning("Нет данных.")
    else:
        client = LLMClient()
        scores, levels, reasons, actions = [], [], [], []

        with st.spinner("Оцениваем риски LLM..."):
            for _, row in df.iterrows():
                feats = {
                    "deal_id": str(row.get("deal_id", "")),
                    "client_name": str(row.get("client_name", "")),
                    "stage": str(row.get("stage", "")),
                    "last_contact_days": _days_since_any(row.get("last_contact_date")),
                    "stage_age_days": _stage_age_days(row.get("last_stage_change_date")),
                    "deal_value": float(row.get("deal_value", 0) or 0),
                    "last_message_text": str(row.get("last_message_text", "")),
                }
                res = client.assess_risk_llm(feats)
                scores.append(res["score"])
                levels.append(res["level"])
                reasons.append(res["reason"])
                actions.append(res["action"])

        df_out = df.copy()
        df_out["risk_score"]  = scores
        df_out["risk_level"]  = levels
        df_out["risk_reason"] = reasons
        df_out["action"]      = actions
        df_out["kommo"]       = df_out["deal_id"].apply(kommo_url)
        df_out["last_contact_days"] = df_out["last_contact_date"].apply(_days_since_any)

        st.session_state["df_out"] = df_out
        st.session_state.setdefault("drafts", {})
        st.session_state["data_ready"] = True

        # сформируем PDF и положим в session_state (чтобы не считать заново на каждом ререндере)
        try:
            st.session_state["risk_pdf"] = _digest_pdf(df_out)
        except Exception as e:
            st.session_state["risk_pdf"] = None
            st.warning(f"Не удалось собрать PDF: {e}")

# 2) Рендерим UI из session_state
df_out = st.session_state.get("df_out")
if not st.session_state.get("data_ready") or df_out is None or df_out.empty:
    st.info("Нажмите «Обновить риски», чтобы подтянуть сделки и оценить их LLM-ом.")
else:
    # KPI
    red = df_out[df_out["risk_level"] == "red"]
    yellow = df_out[df_out["risk_level"] == "yellow"]
    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-label">Красные сделки</div>
        <div class="kpi-value">{len(red)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Cумма красных сделок, ₽</div>
        <div class="kpi-value">{int(red["deal_value"].sum()) if "deal_value" in df_out else 0}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Жёлтые сделки</div>
        <div class="kpi-value">{len(yellow)}</div>
      </div>
    </div>
    """
    st.markdown(kpi_html, unsafe_allow_html=True)

    # Фильтры
    st.subheader("Фильтры")
    c1, c2 = st.columns(2)
    with c1:
        only_red = st.checkbox("Показать только красные", value=False, key="flt_only_red")
    with c2:
        top_by_value = st.checkbox("Топ-10 по сумме", value=False, key="flt_top_value")

    # Приоритизация (score скрыт в UI)
    order = {"red": 0, "yellow": 1, "green": 2}
    view = (df_out.copy()
            .assign(_ord=df_out["risk_level"].map(order))
            .sort_values(["_ord", "risk_score"], ascending=[True, False]))

    if only_red:
        view = view[view["risk_level"] == "red"]
    if top_by_value and "deal_value" in view.columns:
        view = view.sort_values("deal_value", ascending=False).head(10)

    # Карточки + действия
    st.subheader("Приоритеты")
    client = LLMClient()  # для генерации писем (не для скоринга)

    for _, r in view.iterrows():
        level = r["risk_level"]
        badge = f'<span class="badge {level}">{level.upper()}</span>'

        lc = r.get("last_contact_date") or "—"
        lcd = int(r.get("last_contact_days") or 0)
        sla_txt = "OK" if lcd <= SLA_DAYS else "SLA: просрочен"
        reason = r.get("risk_reason") or "—"
        action = r.get("action") or "—"
        kommo_link = r.get("kommo") or "#"
        name = r.get("client_name") or f"Lead #{r.get('deal_id', '')}"

        card_html = f"""
        <div class="lead-card">
          <div class="lead-head">
            <div>
              <div class="lead-name">{name}</div>
              <div class="lead-sec">Последний контакт: {lc} • {sla_txt}</div>
            </div>
            {badge}
          </div>
          <div class="lead-body">
            <b>Причина:</b> {reason}<br/>
            <b>Действие:</b> {action}
          </div>
          <div class="lead-actions">
            <a class="link-btn" href="{kommo_link}" target="_blank">Открыть в Kommo</a>
          </div>
        </div>
        """
        st.markdown(card_html, unsafe_allow_html=True)

        # Кнопки действий
        colA, colB = st.columns(2)
        with colA:
            if st.button("Создать задачу в Kommo", key=f"task_{r['deal_id']}"):
                try:
                    create_task(
                        int(r["deal_id"]),
                        _task_text(r),
                        _deadline_today_18(),
                        responsible_user_id=int(r.get("owner") or 0) or None
                    )
                    st.success("Задача создана ✅")
                except Exception as e:
                    st.error(f"Не удалось создать задачу: {e}")

        with colB:
            with st.expander("Сгенерировать письмо"):
                deal_key = str(r["deal_id"])
                existing = st.session_state.setdefault("drafts", {}).get(deal_key, "")
                st.text_area("Письмо", value=existing, height=150, key=f"txt_{deal_key}")
                if st.button("Сгенерировать", key=f"draft_{deal_key}"):
                    try:
                        draft = client.draft_followup(r["client_name"], reason, r.get("last_message_text", ""))
                        st.session_state["drafts"][deal_key] = draft
                        # мгновенно обновим textarea
                        try:
                            st.rerun()
                        except Exception:
                            st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Ошибка генерации письма: {e}")

    # --- Скачать отчёт (PDF) — в самом низу страницы
    st.markdown("---")
    pdf_bytes = st.session_state.get("risk_pdf")
    if pdf_bytes:
        st.markdown(
            get_pdf_download_link(pdf_bytes, "risk_report.pdf", "Скачать отчёт (PDF)"),
            unsafe_allow_html=True
        )
    else:
        st.info("Отчёт (PDF) недоступен — обнови данные и попробуй снова.")
