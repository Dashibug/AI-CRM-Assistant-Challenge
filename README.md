# 🤖 AI CRM Risk Assistant

AI-ассистент для оценки рисков сделок в **Kommo CRM** на основе LLM.  
Позволяет быстро выявлять проблемные сделки, видеть причины риска и предлагает дальнейшие действия, а также генерирует PDF-отчёт.

<img width="2610" height="1310" alt="image" src="https://github.com/user-attachments/assets/7706f5b8-ef25-463f-9fc8-c1af6e459366" />


---

##  Функциональность

- Автоматическая оценка рисков (красные/жёлтые/зелёные)
- Причины риска и рекомендации от LLM
- Генерация PDF-отчёта с топ-сделками
- Интерфейс менеджера: ссылки на Kommo, генерация письма, загрузка отчётов и планирование задач в Kommo CRM

---

##  Стек технологий

- **Python 3.11+**
- **Streamlit** — пользовательский веб-интерфейс
- **ReportLab** — генерация PDF
- **Pandas** — обработка данных
- LLM API (OpenAI) — анализ сделок
- **Kommo API** — загрузка сделок

---

##  Структура проекта
```
AI_CRM_Assistant_Challenge/
├── src/
│ ├── app_streamlit.py       – Основной UI и логика Streamlit
│ ├── data_loader.py         – Компонент для работы с Kommo API и загрузки данных
│ ├── llm_client.py          – Клиент для взаимодействия с LLM
│ ├── risk_engine.py         – Логика вычисления скоринга рисков
│ └── fonts/                 – Дополнительные шрифты для генерации PDF
├── requirements.txt         – Список всех Python-зависимостей
├── README.md                – Документация проекта
```
---

##  Инструкция по установке и локальному запуску

1. Clone repo
```
git clone https://github.com/<your-username>/AI_CRM_Assistant_Challenge.git
cd AI_CRM_Assistant_Challenge
```
2. Create and activate venv
```
python3 -m venv .venv
source .venv/bin/activate                # для macOS/Linux
.venv\Scripts\activate                    # для Windows
```
3. Install needed requirements
```
pip install -r requirements.txt
```
4. Create .env file and your KOMMO_API_KEY/URL
```
KOMMO_BASE_URL=https://your-account.kommo.com
KOMMO_API_KEY=your_api_key
SLA_DAYS=2
```
5. Run app and enjoy
```
streamlit run src/app_streamlit.py
```
---

## 💻 Как использовать готовый сервис
Сервис уже развёрнут и доступен по ссылке:
[https://ai-crm-assistant-dashi.amvera.io/](https://ai-crm-assistant-dashi.amvera.io/)

Для начала работы просто введите **базовый домен** вашего аккаунта Kommo и **токен доступа** в боковой панели приложения.

---

