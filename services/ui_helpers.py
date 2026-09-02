"""UI helper functions for consistent styling and components"""
import streamlit as st
from typing import List, Dict


def set_page_style():
    """Set custom CSS for professional healthcare design"""
    st.markdown("""
    <style>
    /* Main styling */
    :root {
        --primary-navy: #1a2f4d;
        --secondary-charcoal: #2c3e50;
        --light-bg: #f8fafc;
        --card-white: #ffffff;
        --accent-blue: #2563eb;
        --text-dark: #1e293b;
        --text-muted: #64748b;
        --border-light: #e2e8f0;
        --success-green: #10b981;
        --warning-orange: #f59e0b;
        --danger-red: #ef4444;
    }
    
    /* Page background */
    .stApp {
        background-color: var(--light-bg);
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: var(--primary-navy);
    }
    
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        color: #ffffff;
    }
    
    /* Text styling */
    body {
        color: var(--text-dark);
    }
    
    h1, h2, h3, h4, h5, h6 {
        color: var(--text-dark);
        font-weight: 600;
    }
    
    /* Card styling */
    .card {
        background-color: var(--card-white);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        border: 1px solid var(--border-light);
    }
    
    /* KPI card styling */
    .kpi-card {
        background: linear-gradient(135deg, var(--card-white) 0%, #f1f5f9 100%);
        border-radius: 12px;
        padding: 24px;
        border: 1px solid var(--border-light);
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }
    
    .kpi-value {
        font-size: 32px;
        font-weight: 700;
        color: var(--primary-navy);
        line-height: 1.2;
    }
    
    .kpi-label {
        font-size: 14px;
        color: var(--text-muted);
        font-weight: 500;
        margin-top: 8px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    /* Table styling */
    [data-testid="stDataFrame"] {
        background-color: var(--card-white);
        border-radius: 12px;
    }
    
    /* Button styling */
    .stButton > button {
        background-color: var(--accent-blue);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 500;
        padding: 10px 24px;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        background-color: #1d4ed8;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.15);
    }
    
    /* Status badge styling */
    .badge-waiting {
        background-color: #fef3c7;
        color: #92400e;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
    }
    
    .badge-with-doctor {
        background-color: #dbeafe;
        color: #1e40af;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
    }
    
    .badge-completed {
        background-color: #d1fae5;
        color: #065f46;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
    }
    
    .badge-cancelled {
        background-color: #fee2e2;
        color: #7f1d1d;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
    }
    
    /* Metric styling */
    .metric-label {
        font-size: 14px;
        color: var(--text-muted);
        font-weight: 500;
    }
    
    .metric-value {
        font-size: 28px;
        font-weight: 700;
        color: var(--primary-navy);
    }
    
    /* Header styling */
    .dashboard-header {
        padding: 0 0 20px 0;
        border-bottom: 1px solid var(--border-light);
        margin-bottom: 30px;
    }
    
    .greeting {
        font-size: 28px;
        font-weight: 700;
        color: var(--text-dark);
        margin: 0 0 8px 0;
    }
    
    .subtitle {
        font-size: 14px;
        color: var(--text-muted);
        margin: 0;
    }
    </style>
    """, unsafe_allow_html=True)


def render_kpi_cards(kpis: Dict[str, int]):
    """Render KPI cards in a row"""
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{kpis['total_patients']}</div>
            <div class="kpi-label">Patients Today</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{kpis['waiting']}</div>
            <div class="kpi-label">Waiting</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{kpis['with_doctor']}</div>
            <div class="kpi-label">With Doctor</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{kpis['completed']}</div>
            <div class="kpi-label">Completed</div>
        </div>
        """, unsafe_allow_html=True)


def render_status_badge(status: str) -> str:
    """Render a status badge with appropriate styling"""
    status_lower = status.lower()
    
    if status_lower == "waiting":
        return '🔵 Waiting'
    elif status_lower == "with_doctor" or status_lower == "with doctor":
        return '👨‍⚕️ With Doctor'
    elif status_lower == "completed":
        return '✅ Completed'
    elif status_lower == "called":
        return '📢 Called'
    elif status_lower == "cancelled":
        return '❌ Cancelled'
    else:
        return status


def render_queue_table(queue_data: List[Dict]):
    """Render the queue table"""
    if not queue_data:
        st.info("No patients in queue today")
        return
    
    # Format data for display
    display_data = []
    for item in queue_data:
        token_number = item.get("token_number") or item.get("token") or "Unknown"
        patient_name = item.get("patient_name") or item.get("patient") or "Unknown"
        doctor_name = item.get("doctor_name") or item.get("doctor") or "Unknown"
        token_time = item.get("token_date") or item.get("time") or "--:--"

        display_data.append({
            "Token": token_number,
            "Patient": patient_name,
            "Age": item.get("age", 0),
            "Department": item.get("department", "Unknown"),
            "Doctor": doctor_name,
            "Status": render_status_badge(item.get("status", "Unknown")),
            "Time": token_time
        })
    
    # Display as dataframe
    st.dataframe(
        display_data,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Token": st.column_config.TextColumn("Token", width=80),
            "Patient": st.column_config.TextColumn("Patient", width=130),
            "Age": st.column_config.NumberColumn("Age", width=60),
            "Department": st.column_config.TextColumn("Department", width=130),
            "Doctor": st.column_config.TextColumn("Doctor", width=130),
            "Status": st.column_config.TextColumn("Status", width=120),
            "Time": st.column_config.TextColumn("Time", width=70),
        }
    )


def render_department_overview(dept_data: List[Dict]):
    """Render department overview section"""
    cols = st.columns(len(dept_data))
    
    for idx, (col, dept) in enumerate(zip(cols, dept_data)):
        with col:
            st.markdown(f"""
            <div class="card" style="text-align: center;">
                <div style="font-size: 18px; font-weight: 600; color: var(--text-dark); margin-bottom: 12px;">
                    {dept['name']}
                </div>
                <div style="font-size: 24px; font-weight: 700; color: var(--accent-blue);">
                    {dept['waiting']}
                </div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 8px;">
                    Waiting
                </div>
            </div>
            """, unsafe_allow_html=True)


def render_facility_sidebar(facility):
    """Render facility information in sidebar."""
    if not facility:
        return

    if isinstance(facility, dict):
        name = facility.get("name") or "Facility not configured"
        district = facility.get("district") or "Unknown"
    else:
        name = getattr(facility, "name", None) or "Facility not configured"
        district = getattr(facility, "district", None) or "Unknown"

    st.markdown("""
    <hr style="border: none; border-top: 1px solid rgba(255, 255, 255, 0.1); margin: 20px 0;">
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="color: rgba(255, 255, 255, 0.7); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
        Facility
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="color: #ffffff; font-size: 14px; font-weight: 600; line-height: 1.6;">
        {name}<br>
        <span style="color: rgba(255, 255, 255, 0.7); font-size: 12px;">{district}</span>
    </div>
    """, unsafe_allow_html=True)


def render_coming_soon_page():
    """Render a coming soon placeholder page"""
    st.markdown("""
    <div style="display: flex; align-items: center; justify-content: center; height: 500px; flex-direction: column; text-align: center;">
        <div style="font-size: 48px; margin-bottom: 20px;">🚧</div>
        <h2 style="color: var(--text-dark); margin-bottom: 10px;">Coming Soon</h2>
        <p style="color: var(--text-muted); font-size: 16px;">This feature is under development.</p>
    </div>
    """, unsafe_allow_html=True)
