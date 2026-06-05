import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from google.oauth2 import service_account
from google.cloud import firestore
import streamlit.components.v1 as components

# -------------------------------
# PAGE CONFIG
# -------------------------------
st.set_page_config(page_title="Gastro Dr. Naveed Anwar - Clinic Portal", layout="wide")

# -------------------------------
# FIREBASE CONNECTION
# -------------------------------
@st.cache_resource
def get_firestore_client():
    key_dict = dict(st.secrets["textkey"])
    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
    creds = service_account.Credentials.from_service_account_info(key_dict)
    return firestore.Client(credentials=creds, project=key_dict["project_id"])

db = get_firestore_client()
log_ref = db.collection("patient_log")
settings_ref = db.collection("clinic_settings")

# -------------------------------
# PRICING ENGINE
# -------------------------------
def get_clinic_fees():
    defaults = {
        "appt_fee": 2500.0,
        "None (Consultation Only)": 0.0,
        "OGD": 5000.0,
        "Limit Colonoscopy": 6000.0,
        "Colonoscopy": 9000.0,
        "ERCP": 25000.0,
        "PEG Tube": 15000.0
    }

    doc = settings_ref.document("pricing").get()
    if doc.exists:
        return doc.to_dict()
    else:
        settings_ref.document("pricing").set(defaults)
        return defaults

FEES = get_clinic_fees()
APPT_FEE = FEES.get("appt_fee", 2500.0)
PROCEDURE_FEES = {k: v for k, v in FEES.items() if k != "appt_fee"}

# -------------------------------
# DATE HANDLING
# -------------------------------
now = datetime.now()
current_date_str = now.strftime("%Y-%m-%d")
display_datetime_form = now.strftime("%d-%m-%Y %I:%M %p")
receipt_date_suffix = now.strftime("%d%m%Y")

# -------------------------------
# FIXED RECEIPT GENERATOR (SESSION SAFE)
# -------------------------------
def generate_receipt_number():
    docs = log_ref.where("date", "==", current_date_str).stream()
    count = sum(1 for _ in docs)
    return f"GNA{receipt_date_suffix}{count + 1}"

if "receipt_no" not in st.session_state:
    st.session_state.receipt_no = generate_receipt_number()

# -------------------------------
# NAVIGATION
# -------------------------------
page = st.sidebar.radio(
    "Navigate System Pages",
    ["🏥 Dashboard & Form", "💸 Issue Patient Refund", "🔍 Date-Range Auditor", "⚙️ Procedure Price Settings"]
)

# =====================================================
# PAGE 1: DASHBOARD
# =====================================================
if page == "🏥 Dashboard & Form":
    st.title("🏥 Gastro Dr. Naveed Anwar Clinic Management System")
    st.markdown("---")

    col_form, col_display = st.columns(2)

    # ---------------- FORM ----------------
    with col_form:
        st.header("📋 Patient Entry Form")

        with st.form("patient_form", clear_on_submit=True):
            st.info(f"Date: {display_datetime_form}\n\nReceipt: {st.session_state.receipt_no}")

            patient_name = st.text_input("Patient Name *")
            selected_procedure = st.selectbox("Procedure", list(PROCEDURE_FEES.keys()))

            proc_fee = PROCEDURE_FEES[selected_procedure]
            actual_total = APPT_FEE + proc_fee

            st.markdown(f"""
            **Appointment:** Rs. {APPT_FEE:,.0f}  
            **Procedure:** Rs. {proc_fee:,.0f}  
            **Total:** Rs. {actual_total:,.0f}
            """)

            paid_amount = st.number_input("Paid Amount", min_value=0.0, value=actual_total, step=500.0)
            refund_amount = st.number_input("Refund", min_value=0.0, value=0.0, step=500.0)

            balance = actual_total - paid_amount + refund_amount
            st.write(f"**Balance:** Rs. {balance:,.0f}")

            submit = st.form_submit_button("Save Record")

            if submit:
                if not patient_name.strip():
                    st.error("Patient name required")
                else:
                    data = {
                        "receipt_no": st.session_state.receipt_no,
                        "date": current_date_str,
                        "datetime_str": display_datetime_form,
                        "timestamp": firestore.SERVER_TIMESTAMP,
                        "patient_name": patient_name.strip(),
                        "procedure": selected_procedure,
                        "appt_fee": APPT_FEE,
                        "procedure_fee": proc_fee,
                        "actual_amount": actual_total,
                        "paid_amount": paid_amount,
                        "refund": refund_amount,
                        "balance": balance
                    }

                    log_ref.document(st.session_state.receipt_no).set(data)

                    st.success("Saved successfully")
                    st.session_state.receipt_no = generate_receipt_number()
                    st.rerun()

    # ---------------- DISPLAY ----------------
    with col_display:
        st.header("📊 Live Records")

        docs = log_ref.order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
        df = pd.DataFrame([d.to_dict() for d in docs])

        if not df.empty:
            df["date_parsed"] = pd.to_datetime(df["date"])

            today = pd.Timestamp(datetime.now().date())
            df_today = df[df["date_parsed"] >= today]

            tab1, tab2 = st.tabs(["Today", "Receipt Viewer"])

            with tab1:
                st.metric("Billing", df_today["actual_amount"].sum())
                st.metric("Collected", df_today["paid_amount"].sum())
                st.metric("Balance", df_today["balance"].sum())

                st.dataframe(df_today, use_container_width=True)

            with tab2:
                options = df["receipt_no"] + " | " + df["patient_name"]

                selected = st.selectbox("Select Receipt", options)

                receipt_no = selected.split(" | ")[0]

                match = df[df["receipt_no"] == receipt_no]

                if not match.empty:
                    row = match.iloc[0].to_dict()   # ✅ FIXED

                    st.json(row)

                    receipt_html = f"""
                    <div style="padding:20px;border:2px solid teal;">
                        <h3>{row['receipt_no']}</h3>
                        <p>{row['patient_name']}</p>
                    </div>
                    <button onclick="window.print()">Print</button>
                    """

                    components.html(receipt_html, height=300)
# =====================================================
# PAGE 2: REFUND PANEL
# =====================================================
elif page == "💸 Issue Patient Refund":
    st.title("Refund Manager")

    docs = log_ref.stream()
    df = pd.DataFrame([d.to_dict() for d in docs])

    if not df.empty:
        options = df["receipt_no"] + " | " + df["patient_name"]
        selected = st.selectbox("Select Patient", options)

        receipt_no = selected.split(" | ")[0]
        row = df[df["receipt_no"] == receipt_no].iloc[0]

        st.write(row.to_dict())

        with st.form("refund"):
            new_refund = st.number_input("Refund", value=float(row["refund"]), step=500.0)

            if st.form_submit_button("Update"):
                new_balance = float(row["actual_amount"]) - float(row["paid_amount"]) + new_refund

                log_ref.document(receipt_no).update({
                    "refund": new_refund,
                    "balance": new_balance
                })

                st.success("Updated")
                st.rerun()

    else:
        st.info("No data")

# =====================================================
# PAGE 3: AUDIT
# =====================================================
elif page == "🔍 Date-Range Auditor":
    st.title("Audit Logs")

    docs = log_ref.stream()
    df = pd.DataFrame([d.to_dict() for d in docs])

    if not df.empty:
        df["date_parsed"] = pd.to_datetime(df["date"]).dt.date

        start = st.date_input("Start", datetime.now().date() - timedelta(days=7))
        end = st.date_input("End", datetime.now().date())

        filtered = df[(df["date_parsed"] >= start) & (df["date_parsed"] <= end)]

        if not filtered.empty:
            st.metric("Patients", len(filtered))
            st.metric("Revenue", filtered["paid_amount"].sum())

            st.dataframe(filtered)

        else:
            st.warning("No records")

# =====================================================
# PAGE 4: SETTINGS
# =====================================================
elif page == "⚙️ Procedure Price Settings":
    st.title("Pricing Settings")

    with st.form("settings"):
        new_appt = st.number_input("Appointment Fee", value=float(APPT_FEE), step=500.0)

        updated = {"appt_fee": new_appt}

        for k, v in PROCEDURE_FEES.items():
            updated[k] = st.number_input(k, value=float(v), step=500.0)

        if st.form_submit_button("Save"):
            settings_ref.document("pricing").set(updated)
            st.success("Updated")
            st.rerun()
