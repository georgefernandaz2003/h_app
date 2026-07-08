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

    /* Premium Login UI styles */
    .login-wrapper {
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 2rem 0;
    }
    .login-card {
        background: rgba(30, 41, 59, 0.75);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 2.5rem;
        width: 100%;
        max-width: 480px;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.4), 0 10px 10px -5px rgba(0, 0, 0, 0.4);
        backdrop-filter: blur(12px);
    }
    .login-title {
        font-size: 1.8rem;
        font-weight: 700;
        text-align: center;
        background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 1.5rem;
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

# Mock Medical Records Database (HIPAA compliant structure)
MOCK_PATIENTS_DB = {
    "P101": {
        "name": "John Doe",
        "medical_history": "Diagnosed with Type 2 Diabetes in 2023. Managed with Metformin. Periodic blood sugar checks stable.",
        "lab_reports": [
            {"date": "2026-01-15", "test": "HbA1c", "result": "6.8%", "status": "Normal"},
            {"date": "2026-05-10", "test": "Fast Glucose", "result": "110 mg/dL", "status": "Borderline"}
        ],
        "diagnosis_notes": "Patient is adhering well to diet and exercise. Metformin dosage is appropriate."
    },
    "P102": {
        "name": "Jane Smith",
        "medical_history": "History of mild asthma. Diagnosed in 2021. Albuterol inhaler prescribed for emergency use.",
        "lab_reports": [
            {"date": "2026-02-20", "test": "Spirometry", "result": "FEV1 85%", "status": "Normal"}
        ],
        "diagnosis_notes": "Slight wheezing reported during spring season. Increase inhaler frequency if needed."
    },
    "P103": {
        "name": "Robert Johnson",
        "medical_history": "Hypertension diagnosed in 2020. Treated with Lisinopril. Blood pressure consistently monitored.",
        "lab_reports": [
            {"date": "2026-03-05", "test": "Basic Metabolic Panel", "result": "Normal electrolytes", "status": "Normal"},
            {"date": "2026-06-22", "test": "Lipid Panel", "result": "Cholesterol: 210 mg/dL", "status": "Elevated"}
        ],
        "diagnosis_notes": "Blood pressure stabilized at 128/82. Recommend low-sodium diet and follow-up in 6 months."
    }
}

DOCTOR_PATIENT_MAPPING = {
    "D201": ["P101", "P103"],
    "D202": ["P102"]
}

def simulate_supervisor_agent(query, role, user_id, patient_id, doctor_id):
    query_lower = query.lower().strip()
    
    # Verify identity and role access
    if not role or role not in ["admin", "doctor", "patient", "lab"]:
        return "Access Denied: Invalid user role or identity unverified."
        
    # PATIENT Policy: Allow access only to own records.
    if role == "patient":
        if not patient_id:
            return "Access Denied: You are authorized to view only your own records."
            
        # Stop patient if querying about another patient ID
        for p_id in MOCK_PATIENTS_DB.keys():
            if p_id in query and p_id != patient_id:
                return "Access Denied: You are authorized to view only your own records."
                
        patient_data = MOCK_PATIENTS_DB.get(patient_id)
        if not patient_data:
            return "Access Denied: You are authorized to view only your own records."
            
        if "lab" in query_lower:
            reports_str = "\n".join([f"- {r['date']}: {r['test']} -> {r['result']} ({r['status']})" for r in patient_data["lab_reports"]])
            return f"### 📊 Your Lab Reports:\n{reports_str}"
        elif "diagnosis" in query_lower or "notes" in query_lower:
            return f"### 📝 Your Diagnosis Notes:\n{patient_data['diagnosis_notes']}"
        else:
            return f"### 🏥 Your Medical History Summary:\n{patient_data['medical_history']}\n\n*Note: Row-level filter applied (Patient: {patient_id}).*"
            
    # DOCTOR Policy: Check assignments and filter data.
    elif role == "doctor":
        if not doctor_id:
            return "Access Denied: Doctor identity not verified."
            
        allowed_patients = DOCTOR_PATIENT_MAPPING.get(doctor_id, [])
        
        # Scenario: List doctor's own patients
        if "my patients" in query_lower or "list patients" in query_lower:
            patients_list = []
            for p_id in allowed_patients:
                p_name = MOCK_PATIENTS_DB[p_id]["name"]
                patients_list.append(f"- **{p_id}**: {p_name}")
            return "### 👥 Your Assigned Patients:\n" + "\n".join(patients_list)
            
        # Check if the doctor is querying a specific patient
        target_patient = None
        for p_id in MOCK_PATIENTS_DB.keys():
            if p_id in query or p_id.lower() in query_lower:
                target_patient = p_id
                break
                
        if target_patient:
            if target_patient not in allowed_patients:
                return "Access Denied: Patient is not assigned to you."
                
            patient_data = MOCK_PATIENTS_DB[target_patient]
            if "lab" in query_lower:
                reports_str = "\n".join([f"- {r['date']}: {r['test']} -> {r['result']} ({r['status']})" for r in patient_data["lab_reports"]])
                return f"### 📊 Lab Reports for Patient {target_patient}:\n{reports_str}"
            elif "diagnosis" in query_lower or "notes" in query_lower:
                return f"### 📝 Diagnosis Notes for Patient {target_patient}:\n{patient_data['diagnosis_notes']}"
            else:
                return f"### 🏥 Medical Records for Patient {target_patient} ({patient_data['name']}):\n- **History:** {patient_data['medical_history']}\n- **Diagnosis:** {patient_data['diagnosis_notes']}"
        else:
            return f"Please specify an assigned patient ID (e.g. {', '.join(allowed_patients)}) to query records."
            
    # LAB Policy: Expose only lab reports, redact diagnosis/history.
    elif role == "lab":
        if "diagnosis" in query_lower or "notes" in query_lower or "history" in query_lower:
            return "Access Denied: Lab specialists are only authorized to view laboratory reports. Diagnosis and History notes are restricted."
            
        target_patient = None
        for p_id in MOCK_PATIENTS_DB.keys():
            if p_id in query or p_id.lower() in query_lower:
                target_patient = p_id
                break
                
        if target_patient:
            patient_data = MOCK_PATIENTS_DB[target_patient]
            reports_str = "\n".join([f"- {r['date']}: {r['test']} -> {r['result']} ({r['status']})" for r in patient_data["lab_reports"]])
            return f"### 🧪 Lab Test Reports for Patient {target_patient}:\n{reports_str}\n\n*Note: Diagnosis notes and clinical consultation logs redacted under LAB policy.*"
        else:
            all_reports = []
            for p_id, p_data in MOCK_PATIENTS_DB.items():
                for r in p_data["lab_reports"]:
                    all_reports.append(f"- **Patient {p_id}** | {r['date']}: {r['test']} -> {r['result']}")
            return "### 🧪 Laboratory Reports Registry (Names Redacted):\n" + "\n".join(all_reports)
            
    # ADMIN Policy: Unrestricted access.
    elif role == "admin":
        target_patient = None
        for p_id in MOCK_PATIENTS_DB.keys():
            if p_id in query or p_id.lower() in query_lower:
                target_patient = p_id
                break
                
        if target_patient:
            patient_data = MOCK_PATIENTS_DB[target_patient]
            return f"### 🔑 [ADMIN] Full Profile for Patient {target_patient} ({patient_data['name']}):\n- **History:** {patient_data['medical_history']}\n- **Diagnosis Notes:** {patient_data['diagnosis_notes']}\n- **Raw Database Record:**\n```json\n{json.dumps(patient_data, indent=2)}\n```"
        elif "mapping" in query_lower or "assignments" in query_lower or "doctors" in query_lower:
            mappings_str = "\n".join([f"- Doctor **{d_id}** assigned to Patients: {', '.join(p_ids)}" for d_id, p_ids in DOCTOR_PATIENT_MAPPING.items()])
            return f"### 🔑 [ADMIN] Doctor-Patient Assignment Mappings:\n{mappings_str}"
        else:
            summary = []
            for p_id, p_data in MOCK_PATIENTS_DB.items():
                summary.append(f"- **{p_id}** ({p_data['name']}): {p_data['medical_history']}")
            return "### 🔑 [ADMIN] Comprehensive Medical Registry:\n" + "\n".join(summary)

# Initialize Session State for audit logs and settings
if "audit_logs" not in st.session_state:
    st.session_state.audit_logs = []
    # Add an initial log
    log_audit_request("SYSTEM", "system", "Gateway Initialized", "SUCCESS", "HIPAA-compliant logging active.")

# User-role mapping in code
USER_ROLE_MAPPING = {
    "admin@example.com": {"role": "admin", "password": "adminpassword", "name": "Admin User", "id": "usr_admin_99"},
    "doctor@example.com": {"role": "doctor", "password": "doctorpassword", "name": "Dr. Sarah Jenkins", "id": "D201", "doctor_id": "D201"},
    "patient@example.com": {"role": "patient", "password": "patientpassword", "name": "John Doe", "id": "P101", "patient_id": "P101"},
    "lab@example.com": {"role": "lab", "password": "labpassword", "name": "Lab Specialist Alex", "id": "usr_lab_77"},
    "george3032003@gmail.com": {"role": "admin", "password": "adminpassword", "name": "George Fernandaz", "id": "usr_admin_george"}
}

# Check Databricks App Headers for automatic user logins
headers = st.context.headers
db_email = headers.get("X-Forwarded-Email")
db_user = headers.get("X-Forwarded-Preferred-Username")
db_token = headers.get("X-Forwarded-Access-Token")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user_info = None

# Auto-login if headers are detected (running inside Databricks)
if (db_email or db_user) and not st.session_state.authenticated:
    email_key = (db_email or db_user).lower()
    if email_key in USER_ROLE_MAPPING:
        info = USER_ROLE_MAPPING[email_key]
    else:
        # Fallback patient role for auto-provisioned Databricks user
        info = {
            "role": "patient",
            "name": db_user or db_email,
            "id": f"usr_{db_user or 'db'}_88",
            "patient_id": "P101"
        }
    st.session_state.authenticated = True
    st.session_state.user_info = info
    st.session_state.auth_source = "Databricks SSO"
    if db_token:
        st.session_state.db_token = db_token

# Sleek Login UI
if not st.session_state.authenticated:
    st.markdown('<div class="login-wrapper">', unsafe_allow_html=True)
    st.markdown('<div class="login-card">', unsafe_allow_html=True)
    st.markdown('<div class="login-title">🏥 Healthcare Portal Gateway</div>', unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #94a3b8; font-size: 0.9rem; margin-top: -1rem; margin-bottom: 1.5rem;'>Enter your credentials or access via Databricks App Portal</p>", unsafe_allow_html=True)
    
    login_username = st.text_input("Username / Email", placeholder="doctor@example.com")
    login_password = st.text_input("Password", type="password", placeholder="••••••••")
    
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    
    # Sign In Action
    if st.button("Sign In Securely", use_container_width=True):
        email_key = login_username.lower().strip()
        if email_key in USER_ROLE_MAPPING and USER_ROLE_MAPPING[email_key]["password"] == login_password:
            st.session_state.authenticated = True
            st.session_state.user_info = USER_ROLE_MAPPING[email_key]
            st.session_state.auth_source = "Local Credentials"
            log_audit_request(email_key, USER_ROLE_MAPPING[email_key]["role"], "User Login", "SUCCESS", "Local portal authentication successful.")
            st.success("Successfully logged in!")
            st.rerun()
        else:
            st.error("Invalid username or password.")
            log_audit_request(login_username or "UNKNOWN", "none", "User Login", "FAILED", "Incorrect username or password.")
            
    st.markdown("<hr style='border-color: rgba(255, 255, 255, 0.1); margin: 1.5rem 0;'>", unsafe_allow_html=True)
    st.markdown("<p style='font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.5rem; font-weight: 600;'>Local Demo Accounts:</p>", unsafe_allow_html=True)
    
    accounts_col1, accounts_col2 = st.columns(2)
    with accounts_col1:
        st.markdown("<p style='font-size: 0.75rem; color: #cbd5e1; margin: 0;'>🔑 <b>Admin</b>:<br>admin@example.com / adminpassword</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size: 0.75rem; color: #cbd5e1; margin: 0.5rem 0 0 0;'>🔑 <b>Doctor</b>:<br>doctor@example.com / doctorpassword</p>", unsafe_allow_html=True)
    with accounts_col2:
        st.markdown("<p style='font-size: 0.75rem; color: #cbd5e1; margin: 0;'>🔑 <b>Patient</b>:<br>patient@example.com / patientpassword</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size: 0.75rem; color: #cbd5e1; margin: 0.5rem 0 0 0;'>🔑 <b>Lab</b>:<br>lab@example.com / labpassword</p>", unsafe_allow_html=True)
        
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

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

# ================= SIDEBAR: AUTHENTICATION & SECURITY CONTEXT =================
st.sidebar.markdown("### 🔐 Authenticated Identity")
user_info = st.session_state.user_info
role = user_info["role"]

st.sidebar.markdown(f"**Logged in as:** `{user_info['name']}`")
st.sidebar.markdown(f"**Auth Method:** `{st.session_state.auth_source}`")

# Render badge based on role
role_badges = {
    "patient": '<span class="badge badge-patient">Patient</span>',
    "doctor": '<span class="badge badge-doctor">Doctor</span>',
    "lab": '<span class="badge badge-lab">Lab Specialist</span>',
    "admin": '<span class="badge badge-admin">Administrator</span>'
}
st.sidebar.markdown(f"**Access level:** {role_badges[role]}", unsafe_allow_html=True)

# Determine defaults from active identity
user_id = user_info["id"]
patient_id = user_info.get("patient_id", "")
doctor_id = user_info.get("doctor_id", "")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛡️ Active Session Context")

if role == "patient":
    patient_id = st.sidebar.selectbox("Patient ID", [patient_id], index=0, disabled=True)
    st.sidebar.info(f"🔒 Row-level security matches ONLY patient_id = `{patient_id}`.")
elif role == "doctor":
    doctor_id = st.sidebar.selectbox("Doctor ID", [doctor_id], index=0, disabled=True)
    
    mapping_df = pd.DataFrame({
        "Doctor ID": ["D201", "D201", "D202"],
        "Assigned Patient ID": ["P101", "P103", "P102"]
    })
    st.sidebar.markdown("**Assigned Patients Mapping Table:**")
    st.sidebar.table(mapping_df)
    
    assigned = mapping_df[mapping_df["Doctor ID"] == doctor_id]["Assigned Patient ID"].tolist()
    patient_id = st.sidebar.selectbox("Select Patient to Query", assigned)
    st.sidebar.success(f"Verified Assigned Patients: {', '.join(assigned)}")
elif role == "lab":
    st.sidebar.info("🔬 Lab role allows access only to lab reports. Diagnosis notes are filtered out.")
elif role == "admin":
    st.sidebar.warning("⚡ Admin has unrestricted database access.")
    patient_id = st.sidebar.selectbox("Simulate Patient Context", ["", "P101", "P102", "P103"], index=0)
    doctor_id = st.sidebar.selectbox("Simulate Doctor Context", ["", "D201", "D202"], index=0)

# Sidebar Endpoint Configuration
st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Endpoint Settings")

endpoint_name = st.sidebar.text_input("Databricks Serving Endpoint", value="mas-871d1c5e-endpoint")

# Setup tokens and host URLs
host_override = os.environ.get("DATABRICKS_HOST", "")
token_override = os.environ.get("DATABRICKS_TOKEN", "")

db_host = host_override if host_override else (db_client.config.host if db_client else "")
db_token = st.session_state.get("db_token", "") or token_override or (db_client.config.token if db_client else "")

with st.sidebar.expander("🔑 Connection Details"):
    st.text_input("Databricks Host URL", value=db_host, disabled=True)
    st.text_input("Databricks Token Source", value="SSO Header" if st.session_state.get("db_token") else "Environment/Config", disabled=True)

# Connection Status Indicator & Mode Toggle
if db_host and db_token:
    st.sidebar.success("🟢 Databricks Connected")
    simulation_mode = st.sidebar.checkbox("Local Agent Simulation Mode", value=False)
else:
    st.sidebar.warning("🟡 Local Simulation Mode Active")
    simulation_mode = True

# Log Out Button
st.sidebar.markdown("---")
if st.sidebar.button("🚪 Log Out", use_container_width=True):
    st.session_state.authenticated = False
    st.session_state.user_info = None
    if "db_token" in st.session_state:
        del st.session_state.db_token
    st.rerun()

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
    if st.button("Send Request to Serving Endpoint" if not simulation_mode else "Query Simulated Supervisor Agent", use_container_width=True):
        if not simulation_mode and (not db_host or not db_token):
            st.error("Please configure Databricks authentication details in the sidebar to send requests.")
            log_audit_request(user_id, role, query, "FAILED_AUTH", "Missing Databricks host/token credentials.")
        elif simulation_mode:
            with st.spinner("Simulating Supervisor Agent & Applying Policy Rules..."):
                start_time = datetime.now()
                # Run the simulation logic
                response_text = simulate_supervisor_agent(query, role, user_id, patient_id, doctor_id)
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                
                st.success(f"Simulation Response Generated in {duration_ms}ms")
                st.markdown("#### 📝 Agent Response:")
                st.info(response_text)
                
                # Determine outcome based on "Access Denied" or other factors
                if "Access Denied" in response_text:
                    outcome = "DENIED"
                else:
                    outcome = "SUCCESS_SIMULATION"
                log_audit_request(user_id, role, query, outcome, f"Simulated execution. Response size: {len(response_text)} chars")
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
