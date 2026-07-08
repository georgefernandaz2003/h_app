import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime
from databricks.sdk import WorkspaceClient

# Set Page Config
st.set_page_config(
    page_title="Healthcare Portal - Supervisor Agent Gateway",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom premium CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    
    /* Global styles */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Header styling */
    .main-header {
        font-size: 2.25rem;
        font-weight: 700;
        background: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    .sub-header {
        font-size: 1.1rem;
        color: #94a3b8;
        margin-bottom: 2rem;
    }
    
    /* Cards and containers */
    .status-card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
    }
    
    .audit-log-container {
        font-family: 'JetBrains Mono', monospace;
        background-color: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 1rem;
        height: 250px;
        overflow-y: auto;
        font-size: 0.85rem;
        color: #38bdf8;
    }
    
    /* Badge styling */
    .badge {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        font-size: 0.75rem;
        font-weight: 600;
        border-radius: 9999px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    .badge-patient { background-color: #1e3a8a; color: #60a5fa; border: 1px solid #3b82f6; }
    .badge-doctor { background-color: #064e3b; color: #34d399; border: 1px solid #10b981; }
    .badge-lab { background-color: #701a75; color: #f472b6; border: 1px solid #ec4899; }
    .badge-admin { background-color: #7c2d12; color: #fb923c; border: 1px solid #f97316; }
    
    /* Buttons */
    .stButton>button {
        background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
        color: white;
        border: none;
        padding: 0.6rem 1.2rem;
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.2s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(124, 58, 237, 0.3);
    }
</style>
""", unsafe_allow_html=True)

# Helper function to write audit logs
def log_audit_request(user_id, role, query, status, details=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "user_id": user_id,
        "role": role,
        "query": query,
        "status": status,
        "details": details
    }
    if "audit_logs" not in st.session_state:
        st.session_state.audit_logs = []
    st.session_state.audit_logs.insert(0, log_entry)

# Initialize Session State for audit logs and settings
if "audit_logs" not in st.session_state:
    st.session_state.audit_logs = []
    # Add an initial log
    log_audit_request("SYSTEM", "system", "Gateway Initialized", "SUCCESS", "HIPAA-compliant logging active.")

# App Header
st.markdown('<div class="main-header">Healthcare Supervisor Agent Gateway</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Enforcing Secure Role-Based Access Control (RBAC) & Row-Level Filtering via Databricks Model Serving</div>', unsafe_allow_html=True)

# Databricks Auth Helper
@st.cache_resource
def get_db_client():
    try:
        # Automatically detects credentials when running inside Databricks Apps or via local .databrickscfg
        return WorkspaceClient()
    except Exception as e:
        return None

db_client = get_db_client()

# ================= SIDEBAR: AUTHENTICATION & SECURITY CONTEXT SIMULATOR =================
st.sidebar.markdown("### 🔐 Identity & Access Management")
st.sidebar.caption("Simulate the authenticated user session context that is passed to the supervisor agent.")

role = st.sidebar.selectbox(
    "Select Role",
    ["patient", "doctor", "lab", "admin"],
    format_func=lambda x: x.upper()
)

# Render badge based on role
role_badges = {
    "patient": '<span class="badge badge-patient">Patient</span>',
    "doctor": '<span class="badge badge-doctor">Doctor</span>',
    "lab": '<span class="badge badge-lab">Lab Specialist</span>',
    "admin": '<span class="badge badge-admin">Administrator</span>'
}
st.sidebar.markdown(f"**Current Context Badge:** {role_badges[role]}", unsafe_allow_html=True)

# Dynamic Inputs based on role
user_id = st.sidebar.text_input("User ID (Authenticated)", value=f"usr_{role}_88")
patient_id = ""
doctor_id = ""

if role == "patient":
    patient_id = st.sidebar.selectbox("Patient ID", ["P101", "P102", "P103"], index=0)
    st.sidebar.info(f"🔒 Row-level security matches ONLY patient_id = `{patient_id}`.")
elif role == "doctor":
    doctor_id = st.sidebar.selectbox("Doctor ID", ["D201", "D202"], index=0)
    
    st.sidebar.markdown("**Simulated Doctor-Patient Mapping Table:**")
    mapping_df = pd.DataFrame({
        "Doctor ID": ["D201", "D201", "D202"],
        "Assigned Patient ID": ["P101", "P103", "P102"]
    })
    st.sidebar.table(mapping_df)
    
    # Active doctor patient mapping display
    assigned = mapping_df[mapping_df["Doctor ID"] == doctor_id]["Assigned Patient ID"].tolist()
    st.sidebar.success(f"Verified Assigned Patients: {', '.join(assigned)}")
elif role == "lab":
    st.sidebar.info("🔬 Lab role allows access only to lab reports. Diagnosis notes are filtered out.")
elif role == "admin":
    st.sidebar.warning("⚡ Admin role has unrestricted access to mappings, users, and all records.")

# Sidebar Endpoint Configuration
st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Endpoint Settings")

# Default endpoint name from your serving endpoint screenshot
endpoint_name = st.sidebar.text_input("Databricks Serving Endpoint", value="mas-871d1c5e-endpoint")

# If client is not authenticated automatically, allow manual token setup
with st.sidebar.expander("🔑 Manual Token Override"):
    host_override = st.text_input("Databricks Host URL", value=os.environ.get("DATABRICKS_HOST", ""))
    token_override = st.text_input("Personal Access Token", type="password", value=os.environ.get("DATABRICKS_TOKEN", ""))

# Determine credentials to use
db_host = host_override if host_override else (db_client.config.host if db_client else "")
db_token = token_override if token_override else (db_client.config.token if db_client else "")

# Connection Status Indicator
if db_host and db_token:
    st.sidebar.success("🟢 Databricks Endpoint Connected")
else:
    st.sidebar.error("🔴 Databricks Auth Required (Use token override for local testing)")

# ================= MAIN PANEL: USER INTERACTION & QUERY GENERATION =================
col1, col2 = st.columns([2, 1])

with col1:
    st.markdown("### 💬 Ask Supervisor Agent")
    st.caption("Submit queries. The gateway automatically injects row-level filters and role context.")
    
    # Quick Examples based on selected role
    st.markdown("**Quick Examples:**")
    example_prompts = {
        "patient": [
            f"Show my medical history",
            f"Show clinical details for patient P102"  # Should fail due to Patient RBAC rules
        ],
        "doctor": [
            "Show my patients",
            "Show medical history for Patient P101",
            "Show medical history for Patient P102"  # Depends on D201/D202 mapping
        ],
        "lab": [
            "List recent lab reports",
            "Show diagnosis notes for Patient P101"  # Should be denied to lab role
        ],
        "admin": [
            "Show doctor-patient mappings",
            "Show all medical records across all patients"
        ]
    }
    
    # Dynamic buttons for examples
    example_cols = st.columns(len(example_prompts[role]))
    selected_example = None
    for idx, ex in enumerate(example_prompts[role]):
        if example_cols[idx].button(ex, key=f"ex_{idx}"):
            selected_example = ex
            
    # Main Query Text Input
    default_text = selected_example if selected_example else example_prompts[role][0]
    query = st.text_area("Your Question / Command", value=default_text, height=100)
    
    # Submit Request
    if st.button("Send Request to Serving Endpoint", use_container_width=True):
        if not db_host or not db_token:
            st.error("Please configure Databricks authentication details in the sidebar to send requests.")
            log_audit_request(user_id, role, query, "FAILED_AUTH", "Missing Databricks host/token credentials.")
        else:
            with st.spinner("Invoking Supervisor Agent & Applying Policy Rules..."):
                # Prepare context and payload
                payload = {
                    "messages": [
                        {"role": "user", "content": query}
                    ],
                    "user_id": user_id,
                    "role": role,
                    "patient_id": patient_id,
                    "doctor_id": doctor_id,
                    "custom_inputs": {
                        "user_id": user_id,
                        "role": role,
                        "patient_id": patient_id,
                        "doctor_id": doctor_id
                    }
                }
                
                # Setup endpoint invocation
                url = f"{db_host.rstrip('/')}/serving-endpoints/{endpoint_name}/invocations"
                headers = {
                    "Authorization": f"Bearer {db_token}",
                    "Content-Type": "application/json"
                }
                
                start_time = datetime.now()
                try:
                    # Execute API request to serving endpoint
                    response = requests.post(url, json=payload, headers=headers, timeout=30)
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    
                    if response.status_code == 200:
                        res_data = response.json()
                        st.success(f"Response Received in {duration_ms}ms")
                        
                        # Handle potential response formats (MLflow format uses 'predictions' or agent outputs)
                        predictions = res_data.get("predictions", res_data)
                        
                        st.markdown("#### 📝 Agent Response:")
                        st.info(predictions)
                        
                        # Extract outcome for audit log
                        outcome = "SUCCESS"
                        details = f"HTTP 200 | Latency: {duration_ms}ms"
                        log_audit_request(user_id, role, query, outcome, details)
                    else:
                        st.error(f"Endpoint Error (HTTP {response.status_code})")
                        st.code(response.text)
                        log_audit_request(user_id, role, query, f"ERROR_{response.status_code}", response.text)
                        
                except Exception as e:
                    st.error(f"Failed to connect to endpoint: {str(e)}")
                    log_audit_request(user_id, role, query, "CONNECTION_ERROR", str(e))

with col2:
    st.markdown("### 🛡️ Active Security Policy")
    st.caption("How the Supervisor enforces HIPAA & row-level filtering:")
    
    # Render rules based on role
    if role == "patient":
        st.markdown(f"""
        <div class="status-card">
            <h5 style="color: #60a5fa; margin-top:0;">Patient Policy Rules</h5>
            <ul style="padding-left: 20px; font-size:0.9rem; color:#cbd5e1;">
                <li>Allows reading ONLY patient's own records (<code>patient_id == "{patient_id}"</code>)</li>
                <li>Denies and reports access requests for all other identifiers</li>
                <li>Hides columns / metadata of unrelated patients</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    elif role == "doctor":
        st.markdown(f"""
        <div class="status-card">
            <h5 style="color: #34d399; margin-top:0;">Doctor Policy Rules</h5>
            <ul style="padding-left: 20px; font-size:0.9rem; color:#cbd5e1;">
                <li>Checks mappings for <code>doctor_id == "{doctor_id}"</code></li>
                <li>Denies access if requested patient is not mapped to doctor</li>
                <li>Limits query response strictly to matching rows</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    elif role == "lab":
        st.markdown(f"""
        <div class="status-card">
            <h5 style="color: #f472b6; margin-top:0;">Lab Policy Rules</h5>
            <ul style="padding-left: 20px; font-size:0.9rem; color:#cbd5e1;">
                <li>Allows viewing lab test reports ONLY</li>
                <li>Removes diagnosis notes, clinical consult logs, and doctor summaries</li>
                <li>Redacts sensitive identifiers</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    elif role == "admin":
        st.markdown(f"""
        <div class="status-card">
            <h5 style="color: #fb923c; margin-top:0;">Admin Policy Rules</h5>
            <ul style="padding-left: 20px; font-size:0.9rem; color:#cbd5e1;">
                <li>Allows full database reads and administrative actions</li>
                <li>Enables schema and policy configuration commands</li>
                <li>Maintains full audit trails of administrative reads</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
    # Show outbound payload simulation
    with st.expander("🔍 Inspect Security Token Payload"):
        simulated_token_claims = {
            "iss": "databricks-app-gateway",
            "sub": user_id,
            "role": role,
            "context": {
                "patient_id": patient_id if patient_id else None,
                "doctor_id": doctor_id if doctor_id else None
            },
            "compliance": {
                "hipaa_audit": True,
                "log_access_requests": True
            }
        }
        st.json(simulated_token_claims)

# ================= BOTTOM PANEL: HIPAA AUDIT LOGS =================
st.markdown("---")
st.markdown("### 📋 HIPAA Access & Audit Compliance Logs")
st.caption("All queries, context payloads, and authorization outcomes are logged in real-time.")

# Format audit logs as markdown table or raw logs
if st.session_state.audit_logs:
    log_text = ""
    for log in st.session_state.audit_logs:
        badge_style = "color:#10b981;" if "SUCCESS" in log["status"] else "color:#ef4444;" if "FAILED" in log["status"] else "color:#eab308;"
        log_text += f"[{log['timestamp']}] [USER: {log['user_id']} ({log['role'].upper()})] \n"
        log_text += f"  👉 Request: \"{log['query']}\"\n"
        log_text += f"  🟢 Outcome: {log['status']} | {log['details']}\n"
        log_text += "-"*80 + "\n"
    
    st.markdown(f'<pre class="audit-log-container">{log_text}</pre>', unsafe_allow_html=True)
else:
    st.info("No audit logs generated yet.")
