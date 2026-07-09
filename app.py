import streamlit as st
import time
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
    .badge-pharmacist { background-color: #1e1b4b; color: #a5b4fc; border: 1px solid #6366f1; }
    .badge-labtechnician { background-color: #701a75; color: #f472b6; border: 1px solid #ec4899; }
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

# Databricks Auth Helper
@st.cache_resource(show_spinner=False)
def get_db_client(host=None, token=None):
    try:
        if host and token:
            # Strip scheme from host overrides as WorkspaceClient expects a clean hostname/domain
            clean_host = host.strip()
            if clean_host.startswith("https://"):
                clean_host = clean_host[8:]
            elif clean_host.startswith("http://"):
                clean_host = clean_host[7:]
            return WorkspaceClient(host=clean_host, token=token.strip())
        # Automatically detects credentials when running inside Databricks Apps or via local .databrickscfg
        return WorkspaceClient()
    except Exception as e:
        return None

default_client = get_db_client()

# Helper to retrieve headers in Streamlit (with fallback for older versions)
def get_request_header(header_name):
    # Try modern st.context API (Streamlit 1.35.0+)
    try:
        if hasattr(st, "context") and hasattr(st.context, "headers"):
            val = st.context.headers.get(header_name, "")
            if val:
                return val
    except Exception:
        pass
    
    # Try legacy websocket headers
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        if headers:
            for k, v in headers.items():
                if k.lower() == header_name.lower():
                    return v
    except Exception:
        pass
    return ""

# Helper to extract readable text response from nested Databricks Agent responses
def extract_agent_response_text(predictions):
    if isinstance(predictions, str):
        return predictions
        
    if isinstance(predictions, dict):
        # Check if it has a nested 'output' list representing agent outputs
        outputs = predictions.get("output")
        if isinstance(outputs, list):
            texts = []
            for out in outputs:
                if isinstance(out, dict):
                    # Check for messages from assistant
                    if out.get("type") == "message" and out.get("role") == "assistant":
                        contents = out.get("content")
                        if isinstance(contents, list):
                            for block in contents:
                                if isinstance(block, dict) and block.get("type") == "output_text":
                                    text_val = block.get("text", "")
                                    if text_val:
                                        texts.append(text_val)
            if texts:
                return "\n\n".join(texts)
                
        # Try finding predictions key
        if "predictions" in predictions:
            return extract_agent_response_text(predictions["predictions"])
            
        # Try finding text key
        if "text" in predictions:
            return str(predictions["text"])
            
    if isinstance(predictions, list):
        # Check if it looks like a list of streaming deltas
        is_delta_stream = False
        texts = []
        for item in predictions:
            if isinstance(item, dict):
                # Check for OpenAI delta stream format
                if "choices" in item and isinstance(item["choices"], list) and len(item["choices"]) > 0:
                    choice = item["choices"][0]
                    if isinstance(choice, dict) and ("delta" in choice or "text" in choice):
                        is_delta_stream = True
                        delta = choice.get("delta")
                        if isinstance(delta, dict) and "content" in delta:
                            texts.append(delta["content"])
                        elif "text" in choice:
                            texts.append(choice["text"])
                # Check for MLflow delta stream format
                elif "type" in item and ("text" in item or "text_delta" in item or "delta" in item):
                    is_delta_stream = True
                    if "text_delta" in item:
                        texts.append(item["text_delta"])
                    elif "text" in item:
                        texts.append(item["text"])
                    elif "delta" in item:
                        texts.append(item["delta"])
        if is_delta_stream:
            return "".join(texts)

        if len(predictions) > 0:
            first = predictions[0]
            if isinstance(first, dict) and "text" in first:
                return first["text"]
            return "\n\n".join([extract_agent_response_text(item) for item in predictions])
            
    # Fallback to JSON-formatted dump for fallback readability
    try:
        return json.dumps(predictions, indent=2)
    except Exception:
        return str(predictions)

# Parses either a standard single JSON response or Server-Sent Events (SSE) stream text
def parse_sse_or_json(response_text):
    # Try parsing as a single JSON first
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass
        
    # If not valid JSON, check if it's SSE format
    lines = response_text.strip().split("\n")
    data_chunks = []
    has_sse = False
    error_info = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("event:"):
            has_sse = True
            event_type = line[6:].strip()
            if event_type == "error":
                # Marked as error event
                pass
        elif line.startswith("data:"):
            has_sse = True
            data_val = line[5:].strip()
            if data_val == "[DONE]":
                continue
            try:
                chunk_json = json.loads(data_val)
                if "error_code" in chunk_json or "error" in chunk_json:
                    error_info = chunk_json
                else:
                    data_chunks.append(chunk_json)
            except json.JSONDecodeError:
                data_chunks.append(data_val)
                
    if has_sse:
        if error_info:
            error_msg = error_info.get("message", json.dumps(error_info))
            raise ValueError(error_msg)
        return data_chunks
        
    raise ValueError("Response is not valid JSON and does not conform to SSE stream format.")

# Local Simulation Agent Response Generator (for localhost testing without Databricks Token)
def get_mock_agent_response(query, role, patient_id, doctor_id):
    query_lower = query.lower()
    
    # Check roles and target IDs for RBAC simulation
    if role == "patient":
        # If querying another patient ID
        if patient_id and any(pid in query_lower for pid in ["pa001", "pa002", "pa003", "p001", "p002", "p003"]) and patient_id.lower() not in query_lower:
            return f"❌ **Access Denied (RBAC Policy violation)**: As a Patient (`{patient_id}`), you are only authorized to access your own records. Access to records of other patients is denied and has been logged."
        return f"📋 **Patient Record Details for Patient `{patient_id}`**:\n\n- **Simulation Mode**: Real-time records fetched from Unity Catalog are simulated here.\n- **Access Policy**: Row-Level Security matches ONLY your user ID."
        
    elif role == "doctor":
        return f"👨‍⚕️ **Doctor Portal (Doctor ID: `{doctor_id}`)**:\n\n- **Context**: Accessing records under your clinical scope.\n- **Policy**: Row-level filtering limits queries to patients assigned to your Doctor ID."
            
    elif role == "pharmacist":
        return f"💊 **Pharmacist Access (Pharmacist ID: `{doctor_id or 'P001'}`)**:\n\n- **Scope**: Authorized view for prescription compatibility review.\n- **Policies**: Row-level visibility active."
        
    elif role == "labtechnician":
        if "diagnosis" in query_lower or "history" in query_lower:
            return f"❌ **Access Denied (Lab Technician Policy)**: Lab technicians are restricted from viewing clinical histories, diagnoses, or consult notes. You are only authorized to view raw laboratory results."
        return f"🔬 **Lab Report Portal (Lab Technician)**:\n\n- **Scope**: Lab results view only.\n- **Access**: Clinical history fields filtered."
        
    elif role == "admin":
        return f"⚡ **Administrator Portal**:\n\nFull database access granted. Active Policy Rules:\n- Row-Level Security: Bypass active.\n- Audit logs active.\n\nAll records retrieved across all patients."
        
    return f"Hello! As a Healthcare Supervisor with role `{role.upper()}`, here is the simulated response for your query: \"{query}\"."



# Hardcoded local user database
HARDCODED_USERS = {
    "D001": {
        "role": "doctor",
        "name": "Dr. Smith",
        "id": "D001",
        "patient_id": None,
        "email": "dr.smith@hospital.com",
        "doctor_id": "D001"
    },
    "D002": {
        "role": "doctor",
        "name": "Dr. Jones",
        "id": "D002",
        "patient_id": None,
        "email": "dr.jones@hospital.com",
        "doctor_id": "D002"
    },
    "P001": {
        "role": "pharmacist",
        "name": "Pharm. Doe",
        "id": "P001",
        "patient_id": None,
        "email": "pharm.doe@hospital.com",
        "doctor_id": None
    },
    "A001": {
        "role": "admin",
        "name": "Admin User",
        "id": "A001",
        "patient_id": None,
        "email": "admin@hospital.com",
        "doctor_id": None
    },
    "L001": {
        "role": "labtechnician",
        "name": "Lab Tech 1",
        "id": "L001",
        "patient_id": None,
        "email": "lab.tech1@hospital.com",
        "doctor_id": None
    },
    "PA001": {
        "role": "patient",
        "name": "Patient 001",
        "id": "PA001",
        "patient_id": None,
        "email": "patient001@hospital.com",
        "doctor_id": "D001"
    },
    "U001": {
        "role": "admin",
        "name": "jeevanmg958",
        "id": "U001",
        "patient_id": None,
        "email": "jeevanmg958@gmail.com",
        "doctor_id": None
    }
}

# Credentials & Role Validation Function (Local Hardcoded DB)
def validate_credentials(login_role, login_id):
    uid_clean = login_id.strip()
    if uid_clean in HARDCODED_USERS:
        user_info = HARDCODED_USERS[uid_clean]
        db_role = user_info.get("role", "").lower().strip()
        if db_role != login_role.lower().strip():
            return False, f"Role mismatch: User `{uid_clean}` is registered locally as `{db_role.upper()}`, not `{login_role.upper()}`.", ""
        return True, user_info, "Local Hardcoded Database"
    return False, f"User ID `{login_id}` not found in local database.", ""

# Initialize Session State
if "audit_logs" not in st.session_state:
    st.session_state.audit_logs = []
    log_audit_request("SYSTEM", "system", "Gateway Initialized", "SUCCESS", "HIPAA-compliant logging active.")
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "logged_out" not in st.session_state:
    st.session_state.logged_out = False
if "users_directory" not in st.session_state or not st.session_state.users_directory:
    st.session_state.users_directory = HARDCODED_USERS.copy()

headers_email = get_request_header("X-Forwarded-Email")
headers_user = get_request_header("X-Forwarded-Preferred-Username")

# ================= SIDEBAR: AUTHENTICATION & SETTINGS =================
st.sidebar.markdown("### ⚙️ Gateway Settings")
endpoint_name = st.sidebar.text_input("Databricks Serving Endpoint", value="mas-871d1c5e-endpoint")

with st.sidebar.expander("🔑 Manual Token Override"):
    host_override = st.text_input("Databricks Host URL", value=os.environ.get("DATABRICKS_HOST", ""))
    token_override = st.text_input("Personal Access Token", type="password", value=os.environ.get("DATABRICKS_TOKEN", ""))

db_host = host_override if host_override else (default_client.config.host if default_client else os.environ.get("DATABRICKS_HOST", ""))
db_token = (
    token_override if token_override
    else (get_request_header("x-forwarded-access-token") if get_request_header("x-forwarded-access-token")
          else (default_client.config.token if default_client else os.environ.get("DATABRICKS_TOKEN", "")))
)

if db_host and not db_host.startswith(("http://", "https://")):
    db_host = f"https://{db_host}"



USERS_BY_ID = st.session_state.users_directory

if st.session_state.authenticated:
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔐 Authenticated Identity")
    role = st.session_state.user_role
    user_id = st.session_state.user_id
    
    role_badges = {
        "patient": '<span class="badge badge-patient">Patient</span>',
        "doctor": '<span class="badge badge-doctor">Doctor</span>',
        "pharmacist": '<span class="badge badge-pharmacist">Pharmacist</span>',
        "labtechnician": '<span class="badge badge-labtechnician">Lab Technician</span>',
        "admin": '<span class="badge badge-admin">Administrator</span>'
    }
    
    st.sidebar.markdown(f"**Role:** {role_badges.get(role, role)}", unsafe_allow_html=True)
    st.sidebar.markdown(f"**User ID:** `{user_id}`")
    
    if st.sidebar.button("🚪 Log Out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_id = None
        st.session_state.user_role = None
        if "user_info" in st.session_state:
            st.session_state.user_info = None
        if "auth_source" in st.session_state:
            st.session_state.auth_source = None
        st.session_state.chat_history = []
        if "login_role_input" in st.session_state:
            st.session_state.login_role_input = ""
        if "login_id_input" in st.session_state:
            st.session_state.login_id_input = ""
        for select_key in [
            "doctor_patient_select",
            "pharmacist_patient_select",
            "labtech_patient_select",
            "admin_patient_select",
            "admin_doctor_select"
        ]:
            if select_key in st.session_state:
                del st.session_state[select_key]
        st.session_state.logged_out = True
        st.rerun()
    if st.sidebar.button("🧹 Clear Chat History", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🛡️ Active Session Context")
    patient_id = ""
    doctor_id = ""
    if role == "patient":
        patient_id = user_id
        st.sidebar.info(f"🔒 Row-level security matches ONLY patient_id = `{patient_id}`.")
    elif role == "doctor":
        doctor_id = user_id
        st.sidebar.markdown("**Simulated Doctor-Patient Mapping:**")
        mapping_df = pd.DataFrame({"Doctor ID": ["D001", "D002"], "Assigned Patient ID": ["PA001", "PA002"]})
        st.sidebar.table(mapping_df)
        assigned = mapping_df[mapping_df["Doctor ID"] == doctor_id]["Assigned Patient ID"].tolist()
        if assigned:
            patient_id = st.sidebar.selectbox("Select Patient to Query", assigned, key="doctor_patient_select")
            st.sidebar.success(f"Verified Assigned Patients: {', '.join(assigned)}")
    elif role == "pharmacist":
        st.sidebar.info("💊 Pharmacist: Reviewing medical and prescription records compatibility.")
        patient_id = st.sidebar.selectbox("Select Patient Context", ["", "PA001", "PA002"], index=0, key="pharmacist_patient_select")
    elif role == "labtechnician":
        st.sidebar.info("🔬 Lab Technician: Restricting queries to laboratory test records.")
        patient_id = st.sidebar.selectbox("Select Patient Context", ["", "PA001", "PA002"], index=0, key="labtech_patient_select")
    elif role == "admin":
        st.sidebar.warning("⚡ Admin has unrestricted access.")
        patient_id = st.sidebar.selectbox("Simulate Patient Context", ["", "PA001", "PA002"], index=0, key="admin_patient_select")
        doctor_id = st.sidebar.selectbox("Simulate Doctor Context", ["", "D001", "D002"], index=0, key="admin_doctor_select")

# App Header
st.markdown('<div class="main-header">Healthcare Portal - Supervisor Agent Gateway</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Enforcing Secure Role-Based Access Control (RBAC) & Row-Level Filtering via Databricks Model Serving</div>', unsafe_allow_html=True)

# Login Page UI
if not st.session_state.authenticated:
    st.markdown("""
    <div class="status-card" style="max-width: 500px; margin: 2rem auto; border-radius: 16px; background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px);">
        <h3 style="text-align: center; color: #fff; margin-bottom: 1.5rem;">🔐 Portal Sign-In</h3>
    """, unsafe_allow_html=True)
    login_tab1, login_tab2 = st.tabs(["👤 Manual Sign-In", "🌐 Databricks SSO"])
    with login_tab1:
        login_role = st.text_input("Enter Your Role", placeholder="e.g. doctor, patient, admin, pharmacist, labtechnician", key="login_role_input")
        login_id = st.text_input("Enter Your User ID", placeholder="e.g. D001, PA001, U001", key="login_id_input")
        if st.button("Sign In to Portal", use_container_width=True, key="btn_manual_login"):
            if not login_role or not login_id:
                st.error("❌ Please enter both Role and User ID.")
            else:
                with st.spinner("Validating credentials..."):
                    success, result, source = validate_credentials(login_role.strip().lower(), login_id.strip())
                    if success:
                        st.session_state.authenticated = True
                        st.session_state.user_role = login_role.strip().lower()
                        st.session_state.user_id = login_id.strip()
                        st.session_state.user_info = result
                        st.session_state.auth_source = source
                        st.session_state.logged_out = False
                        log_audit_request(login_id.strip(), login_role.strip().lower(), "User Sign-In", "SUCCESS", f"Authenticated via {source}")
                        st.success(f"Successfully logged in via {source}!")
                        st.rerun()
                    else:
                        st.error(f"❌ Login Failed: {result}")
                        log_audit_request(login_id.strip(), login_role.strip().lower(), "User Sign-In", "FAILED", result)
    with login_tab2:
        if headers_email or headers_user:
            st.write(f"Detected SSO User: **{headers_email or headers_user}**")
            email_key = (headers_email or headers_user).lower().strip()
            matched_user = None
            scan_users = USERS_BY_ID
            for u in scan_users.values():
                if u["email"].lower() == email_key:
                    matched_user = u
                    break
            
            if matched_user:
                st.write(f"Mapped Profile: **{matched_user['name']}** ({matched_user['role'].upper()})")
                if st.button("Sign In with SSO", use_container_width=True, key="btn_sso_login"):
                    st.session_state.authenticated = True
                    st.session_state.user_role = matched_user["role"]
                    st.session_state.user_id = matched_user["id"]
                    st.session_state.user_info = matched_user
                    st.session_state.auth_source = "Databricks SSO"
                    st.session_state.logged_out = False
                    log_audit_request(matched_user["id"], matched_user["role"], "User SSO Sign-In", "SUCCESS", f"SSO logged in via header email: {headers_email}")
                    st.success("SSO Sign-in Successful!")
                    st.rerun()
            else:
                st.warning("Your SSO email is not mapped in the portal directory. Please sign in manually.")
        else:
            st.info("No SSO headers detected. Please sign in manually via the Select Identity tab.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ================= MAIN PANEL: USER INTERACTION & QUERY GENERATION =================
col1, col2 = st.columns([2, 1])

with col1:
    st.markdown("### 💬 Ask Supervisor Agent")
    st.caption("Submit queries. The gateway automatically injects row-level filters and role context.")
    
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
        
    example_prompts = {
        "patient": [
            f"Show my medical history",
            f"Show clinical details for patient PA002"  # Should fail due to Patient RBAC rules
        ],
        "doctor": [
            "Show my patients",
            "Show medical history for Patient PA001",
            "Show medical history for Patient PA002"  # Depends on mapping
        ],
        "pharmacist": [
            "Check medication history for Patient PA001",
            "Check drug compatibility for Patient PA001"
        ],
        "labtechnician": [
            "List recent lab reports",
            "Show lab reports for Patient PA001"
        ],
        "admin": [
            "Show doctor-patient mappings",
            "Show all medical records across all patients"
        ]
    }
        
    # Render chat history container
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if "caption" in msg:
                    st.caption(msg["caption"])
                    
    # Render quick examples if history is empty
    clicked_prompt = None
    if not st.session_state.chat_history:
        st.markdown("**Quick Examples:**")
        example_cols = st.columns(len(example_prompts[role]))
        for idx, ex in enumerate(example_prompts[role]):
            if example_cols[idx].button(ex, key=f"ex_{idx}"):
                clicked_prompt = ex

    # Main chat input at the bottom
    user_query = st.chat_input("Ask the Healthcare Supervisor...")
    active_query = user_query if user_query else clicked_prompt

    if active_query:
        # Check if we should use local simulation mode (e.g. running on localhost without tokens)
        use_simulation = not db_host or not db_token
        
        # Append user message
        st.session_state.chat_history.append({"role": "user", "content": active_query})
        with chat_container:
            with st.chat_message("user"):
                st.markdown(active_query)
                
        if use_simulation:
            with st.spinner("Invoking Local Supervisor Agent Simulation..."):
                time.sleep(0.8) # Simulate slight network latency
                mock_response = get_mock_agent_response(active_query, role, patient_id, doctor_id)
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": mock_response,
                    "caption": "⚠️ *Local Simulation Mode Active*"
                })
                log_audit_request(user_id, role, active_query, "SUCCESS_SIMULATED", "Processed locally via simulation.")
                st.rerun()
        else:
                    
            with st.spinner("Invoking Supervisor Agent & Applying Policy Rules..."):
                # Format query content to automatically pass identity and context
                context_prefix = f"[User Context - Role: {role.upper()} | User ID: {user_id}"
                if patient_id:
                    context_prefix += f" | Patient ID: {patient_id}"
                if doctor_id:
                    context_prefix += f" | Doctor ID: {doctor_id}"
                context_prefix += "]\n\n"

                payload = {
                    "input": [
                        {"role": "user", "content": f"{context_prefix}{active_query}"}
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
                    response = requests.post(url, json=payload, headers=headers, timeout=120)
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    
                    if response.status_code == 200:
                        try:
                            if not response.text.strip():
                                raise ValueError("Empty response body received from the serving endpoint.")
                            res_data = parse_sse_or_json(response.text)
                            if isinstance(res_data, dict):
                                predictions = res_data.get("predictions", res_data)
                            else:
                                predictions = res_data
                            extracted_response = extract_agent_response_text(predictions)
                            
                            # Save assistant response
                            st.session_state.chat_history.append({
                                "role": "assistant", 
                                "content": extracted_response,
                                "caption": f"⚡ *Response received in {duration_ms}ms*"
                            })
                            log_audit_request(user_id, role, active_query, "SUCCESS", f"HTTP 200 | Latency: {duration_ms}ms")
                            st.rerun()
                        except Exception as parse_err:
                            err_str = str(parse_err)
                            content_type = response.headers.get("Content-Type", "unknown")
                            error_preview = response.text[:1000] if response.text else "(No content)"
                            
                            if "INSUFFICIENT_SCOPE" in err_str or "vector-search" in err_str:
                                error_msg = (
                                    f"❌ **OAuth Security Scope Error (INSUFFICIENT_SCOPE)**\n\n"
                                    f"The Databricks serving endpoint agent requires access to the **Vector Search Index**, "
                                    f"but the OAuth token passed to the endpoint lacks the required `vector-search` scope.\n\n"
                                    f"**Active Token Scopes:** `{err_str}`\n\n"
                                    f"### 💡 How to Resolve:\n"
                                    f"1. **Workspace OAuth Scopes**: Ensure the application configuration in the workspace allows the `vector-search` scope.\n"
                                    f"2. **Manual Token Override**: Generate a Personal Access Token (PAT) with `all-apis` or `vector-search` scope and use the **Manual Token Override** in the sidebar."
                                )
                            else:
                                error_msg = (
                                    f"**JSON/SSE Parsing Error:** The endpoint returned status code `200 OK`, "
                                    f"but the response body could not be parsed correctly.\n\n"
                                    f"**Error Details:** `{err_str}`\n"
                                    f"**Content-Type:** `{content_type}`\n\n"
                                    f"**Response Preview:**\n```html\n{error_preview}\n```"
                                )
                            st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
                            log_audit_request(user_id, role, active_query, "JSON_DECODE_ERROR", f"Content-Type: {content_type} | Error: {err_str}")
                            st.rerun()
                    else:
                        error_msg = f"**Endpoint Error (HTTP {response.status_code})**\n```json\n{response.text}\n```"
                        st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
                        log_audit_request(user_id, role, active_query, f"ERROR_{response.status_code}", response.text)
                        st.rerun()
                except Exception as e:
                    err_str = str(e)
                    if "INSUFFICIENT_SCOPE" in err_str or "vector-search" in err_str:
                        error_msg = (
                            f"❌ **OAuth Security Scope Error (INSUFFICIENT_SCOPE)**\n\n"
                            f"The Databricks serving endpoint agent requires access to the **Vector Search Index**, "
                            f"but the OAuth token passed to the endpoint lacks the required `vector-search` scope.\n\n"
                            f"**Active Token Scopes:** `{err_str}`\n\n"
                            f"### 💡 How to Resolve:\n"
                            f"1. **Workspace OAuth Scopes**: Ensure the application configuration in the workspace allows the `vector-search` scope.\n"
                            f"2. **Manual Token Override**: Generate a Personal Access Token (PAT) with `all-apis` or `vector-search` scope and use the **Manual Token Override** in the sidebar."
                        )
                    else:
                        error_msg = f"**Connection Error:** {err_str}"
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
                    log_audit_request(user_id, role, active_query, "CONNECTION_ERROR", err_str)
                    st.rerun()

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
    elif role == "pharmacist":
        st.markdown(f"""
        <div class="status-card">
            <h5 style="color: #a5b4fc; margin-top:0;">Pharmacist Policy Rules</h5>
            <ul style="padding-left: 20px; font-size:0.9rem; color:#cbd5e1;">
                <li>Allows viewing medical histories and prescriptions to review compatibility</li>
                <li>Restricts editing of medical records or billing profiles</li>
                <li>Audit logged under pharmacist credentials</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    elif role == "labtechnician":
        st.markdown(f"""
        <div class="status-card">
            <h5 style="color: #f472b6; margin-top:0;">Lab Technician Policy Rules</h5>
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
