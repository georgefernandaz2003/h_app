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



def get_automatic_warehouse_id(client):
    try:
        warehouses = list(client.warehouses.list())
        if not warehouses:
            return None
        # Try to find a RUNNING warehouse
        running = [w for w in warehouses if str(w.state).upper() == "RUNNING"]
        if running:
            return running[0].id
        # Try to find a STARTING warehouse
        starting = [w for w in warehouses if str(w.state).upper() == "STARTING"]
        if starting:
            return starting[0].id
        # Default to the first one in the list
        return warehouses[0].id
    except Exception:
        return None

def execute_statement_with_fallback(sql, catalog, schema, table, warehouse_id, host, token):
    primary_client = get_db_client()
    has_sso = bool(get_request_header("x-forwarded-access-token"))
    user_token = get_request_header("x-forwarded-access-token")
    
    fallback_client = None
    if has_sso:
        fallback_client = get_db_client(host=host, token=user_token)
    elif host and token:
        fallback_client = get_db_client(host=host, token=token)
        
    wh_id = warehouse_id if warehouse_id else os.environ.get("SQL_WAREHOUSE_ID", "")
    
    client_attempts = []
    if primary_client:
        client_attempts.append((primary_client, "Service Principal"))
    if fallback_client:
        client_attempts.append((fallback_client, "User Access Token"))
        
    if not client_attempts:
        raise ValueError("No valid Databricks clients could be initialized.")
        
    last_error = None
    for client, client_name in client_attempts:
        try:
            active_wh = wh_id
            if not active_wh:
                active_wh = get_automatic_warehouse_id(client)
            if not active_wh:
                raise ValueError(f"SQL Warehouse ID is missing for client {client_name}")
                
            res = client.statement_execution.execute_statement(
                warehouse_id=active_wh,
                statement=sql
            )
            
            # Poll statement status
            statement_id = res.statement_id
            state = res.status.state.value if hasattr(res.status.state, "value") else str(res.status.state)
            start_poll = time.time()
            while state in ["PENDING", "RUNNING"]:
                if time.time() - start_poll > 30:
                    raise TimeoutError("Databricks database query timed out.")
                time.sleep(1)
                poll_res = client.statement_execution.get_statement(statement_id=statement_id)
                state = poll_res.status.state.value if hasattr(poll_res.status.state, "value") else str(poll_res.status.state)
                res = poll_res
                
            if state == "FAILED":
                error_msg = res.status.error.message if res.status.error else "Unknown SQL Execution Error"
                raise ValueError(f"SQL State {state}: {error_msg}")
                
            return res, client_name, active_wh
        except Exception as e:
            last_error = e
            continue
            
    raise last_error

# Credentials & Role Validation Function via Databricks table
def validate_credentials(login_role, login_id, catalog, schema, table, warehouse_id, host, token):
    try:
        uid_clean = login_id.strip()
        sql = f"SELECT user_id, username, role, patient_id, email, doctor_id FROM {catalog}.{schema}.{table} WHERE user_id = '{uid_clean}' OR LOWER(email) = '{uid_clean.lower()}'"
        
        res, auth_source, _ = execute_statement_with_fallback(
            sql, catalog, schema, table, warehouse_id, host, token
        )
        
        if not res.result or not res.result.data_array:
            return False, f"User '{login_id}' not found in Databricks users table `{catalog}.{schema}.{table}`.", ""
            
        row = res.result.data_array[0]
        schema_fields = [f.name.lower() for f in res.manifest.schema.columns]
        record = dict(zip(schema_fields, row))
        
        db_role = record.get("role", "").lower().strip()
        if db_role != login_role.lower().strip():
            return False, f"Role mismatch: User `{login_id}` is registered in Databricks as `{db_role.upper()}`, not `{login_role.upper()}`.", ""
            
        user_info = {
            "role": db_role,
            "name": record.get("username", f"User {record.get('user_id')}"),
            "id": record.get("user_id"),
            "patient_id": record.get("patient_id") if record.get("patient_id") and record.get("patient_id") != "null" else None,
            "email": record.get("email", ""),
            "doctor_id": record.get("doctor_id") if record.get("doctor_id") and record.get("doctor_id") != "null" else None
        }
        return True, user_info, f"Databricks table ({auth_source})"
    except Exception as e:
        return False, f"Databricks table query error: {str(e)}", ""

def validate_credentials_by_email(email, catalog, schema, table, warehouse_id, host, token):
    try:
        email_clean = email.strip().lower()
        sql = f"SELECT user_id, username, role, patient_id, email, doctor_id FROM {catalog}.{schema}.{table} WHERE LOWER(email) = '{email_clean}'"
        
        res, auth_source, _ = execute_statement_with_fallback(
            sql, catalog, schema, table, warehouse_id, host, token
        )
        
        if not res.result or not res.result.data_array:
            return False, f"Email '{email}' not found in Databricks users table `{catalog}.{schema}.{table}`.", ""
            
        row = res.result.data_array[0]
        schema_fields = [f.name.lower() for f in res.manifest.schema.columns]
        record = dict(zip(schema_fields, row))
        
        db_role = record.get("role", "").lower().strip()
        user_info = {
            "role": db_role,
            "name": record.get("username", f"User {record.get('user_id')}"),
            "id": record.get("user_id"),
            "patient_id": record.get("patient_id") if record.get("patient_id") and record.get("patient_id") != "null" else None,
            "email": record.get("email", ""),
            "doctor_id": record.get("doctor_id") if record.get("doctor_id") and record.get("doctor_id") != "null" else None
        }
        return True, user_info, f"Databricks table ({auth_source})"
    except Exception as e:
        return False, f"Databricks table query error: {str(e)}", ""

def fetch_patients_for_doctor(doctor_id, catalog, schema, table, warehouse_id, host, token):
    try:
        sql = f"SELECT user_id FROM {catalog}.{schema}.{table} WHERE doctor_id = '{doctor_id.strip()}' AND role = 'patient'"
        res, _, _ = execute_statement_with_fallback(
            sql, catalog, schema, table, warehouse_id, host, token
        )
        if not res.result or not res.result.data_array:
            return []
        return [row[0] for row in res.result.data_array]
    except Exception:
        return []

def fetch_all_patients(catalog, schema, table, warehouse_id, host, token):
    try:
        sql = f"SELECT user_id FROM {catalog}.{schema}.{table} WHERE role = 'patient'"
        res, _, _ = execute_statement_with_fallback(
            sql, catalog, schema, table, warehouse_id, host, token
        )
        if not res.result or not res.result.data_array:
            return []
        return [row[0] for row in res.result.data_array]
    except Exception:
        return []

def fetch_all_doctors(catalog, schema, table, warehouse_id, host, token):
    try:
        sql = f"SELECT user_id FROM {catalog}.{schema}.{table} WHERE role = 'doctor'"
        res, _, _ = execute_statement_with_fallback(
            sql, catalog, schema, table, warehouse_id, host, token
        )
        if not res.result or not res.result.data_array:
            return []
        return [row[0] for row in res.result.data_array]
    except Exception:
        return []

# Initialize Session State
if "audit_logs" not in st.session_state:
    st.session_state.audit_logs = []
    log_audit_request("SYSTEM", "system", "Gateway Initialized", "SUCCESS", "HIPAA-compliant logging active.")
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "logged_out" not in st.session_state:
    st.session_state.logged_out = False
if "users_directory" not in st.session_state:
    st.session_state.users_directory = {}

headers_email = get_request_header("X-Forwarded-Email")
headers_user = get_request_header("X-Forwarded-Preferred-Username")

# ================= SIDEBAR: AUTHENTICATION & SETTINGS =================
st.sidebar.markdown("### ⚙️ Gateway Settings")
endpoint_name = st.sidebar.text_input("Databricks Serving Endpoint", value="mas-871d1c5e-endpoint")

with st.sidebar.expander("🔑 Manual Token Override"):
    host_override = st.text_input("Databricks Host URL", value=os.environ.get("DATABRICKS_HOST", ""))
    token_override = st.text_input("Personal Access Token", type="password", value=os.environ.get("DATABRICKS_TOKEN", ""))

with st.sidebar.expander("🗄️ Databricks Table Settings"):
    sync_catalog = st.text_input("Catalog", value="aienterprise")
    sync_schema = st.text_input("Schema", value="default")
    sync_table = st.text_input("Table", value="users")
    sync_warehouse = st.text_input("SQL Warehouse ID", value=os.environ.get("SQL_WAREHOUSE_ID", ""))

db_host = host_override if host_override else (default_client.config.host if default_client else os.environ.get("DATABRICKS_HOST", ""))
db_token = (
        token_override if token_override
    else (get_request_header("x-forwarded-access-token") if get_request_header("x-forwarded-access-token")
          else (default_client.config.token if default_client else os.environ.get("DATABRICKS_TOKEN", "")))
)

if db_host and not db_host.startswith(("http://", "https://")):
    db_host = f"https://{db_host}"

# Auto-SSO login flow
if not st.session_state.authenticated and not st.session_state.logged_out:
    sso_email = headers_email or headers_user
    if sso_email:
        # Check if warehouse is configured before attempting auto-login
        if db_host and db_token:
            success, result, source = validate_credentials_by_email(
                sso_email, sync_catalog, sync_schema, sync_table, sync_warehouse, db_host, db_token
            )
            if success:
                st.session_state.authenticated = True
                st.session_state.user_role = result["role"]
                st.session_state.user_id = result["id"]
                st.session_state.user_info = result
                st.session_state.auth_source = "Databricks SSO"
                st.session_state.logged_out = False
                log_audit_request(result["id"], result["role"], "User Auto SSO Sign-In", "SUCCESS", f"Authenticated via {source}")
                st.rerun()

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
        user_info = st.session_state.get("user_info")
        doctor_id = user_info.get("doctor_id") if user_info else ""
        st.sidebar.info(f"🔒 Row-level security matches ONLY patient_id = `{patient_id}`.")
    elif role == "doctor":
        doctor_id = user_id
        st.sidebar.markdown("**Assigned Patients:**")
        assigned = fetch_patients_for_doctor(
            doctor_id, sync_catalog, sync_schema, sync_table, sync_warehouse, db_host, db_token
        )
        if not assigned:
            assigned = ["PA001", "PA002"]
            st.sidebar.warning("⚠️ Using fallback simulated patient mapping.")
        else:
            st.sidebar.success(f"Verified Assigned Patients: {', '.join(assigned)}")
        patient_id = st.sidebar.selectbox("Select Patient to Query", assigned, key="doctor_patient_select")
    elif role == "pharmacist":
        st.sidebar.info("💊 Pharmacist: Reviewing medical and prescription records compatibility.")
        all_patients = fetch_all_patients(sync_catalog, sync_schema, sync_table, sync_warehouse, db_host, db_token)
        if not all_patients:
            all_patients = ["PA001", "PA002"]
        patient_id = st.sidebar.selectbox("Select Patient Context", [""] + all_patients, index=0, key="pharmacist_patient_select")
    elif role == "labtechnician":
        st.sidebar.info("🔬 Lab Technician: Restricting queries to laboratory test records.")
        all_patients = fetch_all_patients(sync_catalog, sync_schema, sync_table, sync_warehouse, db_host, db_token)
        if not all_patients:
            all_patients = ["PA001", "PA002"]
        patient_id = st.sidebar.selectbox("Select Patient Context", [""] + all_patients, index=0, key="labtech_patient_select")
    elif role == "admin":
        st.sidebar.warning("⚡ Admin has unrestricted access.")
        all_patients = fetch_all_patients(sync_catalog, sync_schema, sync_table, sync_warehouse, db_host, db_token)
        if not all_patients:
            all_patients = ["PA001", "PA002"]
        all_doctors = fetch_all_doctors(sync_catalog, sync_schema, sync_table, sync_warehouse, db_host, db_token)
        if not all_doctors:
            all_doctors = ["D001", "D002"]
        patient_id = st.sidebar.selectbox("Simulate Patient Context", [""] + all_patients, index=0, key="admin_patient_select")
        doctor_id = st.sidebar.selectbox("Simulate Doctor Context", [""] + all_doctors, index=0, key="admin_doctor_select")

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
                    success, result, source = validate_credentials(
                        login_role.strip().lower(),
                        login_id.strip(),
                        sync_catalog,
                        sync_schema,
                        sync_table,
                        sync_warehouse,
                        db_host,
                        db_token
                    )
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
            sso_email = (headers_email or headers_user).strip().lower()
            st.write(f"Detected SSO User: **{sso_email}**")
            if st.button("Sign In with SSO", use_container_width=True, key="btn_sso_login"):
                with st.spinner("Validating credentials with Databricks table..."):
                    success, result, source = validate_credentials_by_email(
                        sso_email,
                        sync_catalog,
                        sync_schema,
                        sync_table,
                        sync_warehouse,
                        db_host,
                        db_token
                    )
                    if success:
                        st.session_state.authenticated = True
                        st.session_state.user_role = result["role"]
                        st.session_state.user_id = result["id"]
                        st.session_state.user_info = result
                        st.session_state.auth_source = source
                        st.session_state.logged_out = False
                        log_audit_request(result["id"], result["role"], "User SSO Sign-In", "SUCCESS", f"Authenticated via {source}")
                        st.success("SSO Sign-in Successful!")
                        st.rerun()
                    else:
                        st.error(f"❌ SSO Login Failed: {result}")
                        log_audit_request(sso_email, "unknown", "User SSO Sign-In", "FAILED", result)
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
                        res_data = response.json()
                        predictions = res_data.get("predictions", res_data)
                        extracted_response = extract_agent_response_text(predictions)
                        
                        # Save assistant response
                        st.session_state.chat_history.append({
                            "role": "assistant", 
                            "content": extracted_response,
                            "caption": f"⚡ *Response received in {duration_ms}ms*"
                        })
                        log_audit_request(user_id, role, active_query, "SUCCESS", f"HTTP 200 | Latency: {duration_ms}ms")
                        st.rerun()
                    else:
                        error_msg = f"**Endpoint Error (HTTP {response.status_code})**\n```json\n{response.text}\n```"
                        st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
                        log_audit_request(user_id, role, active_query, f"ERROR_{response.status_code}", response.text)
                        st.rerun()
                except Exception as e:
                    error_msg = f"**Connection Error:** {str(e)}"
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
                    log_audit_request(user_id, role, active_query, "CONNECTION_ERROR", str(e))
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
