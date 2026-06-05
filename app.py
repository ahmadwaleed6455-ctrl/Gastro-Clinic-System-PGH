import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from google.oauth2 import service_account
from google.cloud import firestore

# Set page config to wide layout
st.set_page_config(page_title="Gastro Dr. Naveed Anwar - Firebase Clinic", layout="wide")

# ----------------------------------------------------
# FIREBASE CONNECTION SETUP
# ----------------------------------------------------
@st.cache_resource
def get_firestore_client():
    # Load credentials directly from Streamlit secrets management
    key_dict = dict(st.secrets["textkey"])
    # Fix formatting for newlines in private key if any string issues happen
    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
    creds = service_account.Credentials.from_service_account_info(key_dict)
    return firestore.Client(credentials=creds, project=key_dict["project_id"])

db = get_firestore_client()
# Reference to your firestore collection
db_collection = db.collection("patient_log")

# Define static clinic fees
PROCEDURE_FEES = {
    "None (Consultation Only)": 0,
    "OGD": 5000,
    "Limit Colonoscopy": 6000,
    "Colonoscopy": 9000,
    "ERCP": 25000,
    "PEG Tube": 15000
}
APPT_FEE = 2500.0

# ----------------------------------------------------
# SYSTEM TIME & AUTOMATION LOGIC
# ----------------------------------------------------
current_date_str = datetime.now().strftime("%Y-%m-%d")
display_date_form = datetime.now().strftime("%d-%m-%Y")
receipt_date_suffix = datetime.now().strftime("%d%m%Y")

def generate_receipt_number():
    # Query Firebase to count records matching today's date string
    docs = db_collection.where("date", "==", current_date_str).stream()
    # Fixed syntax: added the 'in' keyword back into the list comprehension
    count = sum(1 for _ in docs)
    next_index = count + 1
    return f"GNA{receipt_date_suffix}{next_index}"
    
# Auto-generate receipt number for this instant session
auto_receipt_no = generate_receipt_number()

# ----------------------------------------------------
# APP UI & INTERFACE
# ----------------------------------------------------
st.title("🏥 Gastro Dr. Naveed Anwar Clinic Management System (Cloud Powered)")
st.markdown("---")

col_form, col_display = st.columns()

# --- LEFT COLUMN: DATA ENTRY FORM ---
with col_form:
    st.header("📋 Patient Entry Form")
    
    with st.form(key="patient_entry_form", clear_on_submit=True):
        st.info(f"**Date:** {display_date_form} | **Receipt No:** `{auto_receipt_no}`")
        
        patient_name = st.text_input("Patient Name *", placeholder="Enter patient's full name")
        selected_procedure = st.selectbox("Select Procedure", list(PROCEDURE_FEES.keys()))
        
        calculated_proc_fee = PROCEDURE_FEES[selected_procedure]
        actual_total = APPT_FEE + calculated_proc_fee
        
        st.markdown(f"""
        * **Appointment Fee:** Rs. {APPT_FEE:,.0f}
        * **Procedure Fee:** Rs. {calculated_proc_fee:,.0f}
        * **Actual Total Amount:** **Rs. {actual_total:,.0f}**
        """)
        
        paid_amount = st.number_input("Paid Amount (Rs.)", min_value=0.0, step=500.0, value=actual_total)
        refund_amount = st.number_input("Refund Amount (Rs.)", min_value=0.0, step=500.0, value=0.0)
        
        calculated_balance = actual_total - paid_amount + refund_amount
        st.markdown(f"**Calculated Balance:** Rs. {calculated_balance:,.0f}")
        
        submit_button = st.form_submit_button(label="Save Record & Auto-Reset")
        
        if submit_button:
            if not patient_name.strip():
                st.error("Submission failed! Patient Name is required.")
            else:
                # Structure document data
                patient_data = {
                    "receipt_no": auto_receipt_no,
                    "date": current_date_str,
                    "timestamp": firestore.SERVER_TIMESTAMP,
                    "patient_name": patient_name.strip(),
                    "procedure": selected_procedure,
                    "appt_fee": APPT_FEE,
                    "procedure_fee": calculated_proc_fee,
                    "actual_amount": actual_total,
                    "paid_amount": paid_amount,
                    "refund": refund_amount,
                    "balance": calculated_balance
                }
                # Save dynamically to Cloud Firebase with Receipt No as unique Document ID
                db_collection.document(auto_receipt_no).set(patient_data)
                
                st.success(f"Saved successfully to Cloud! Receipt: {auto_receipt_no}")
                st.rerun()

# --- RIGHT COLUMN: LIVE WORKSHEETS FROM FIREBASE ---
with col_display:
    st.header("📊 Live Worksheet & Cloud Archive")
    
    # Fetch data directly from Firebase Firestore
    docs = db_collection.order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    data_list = [doc.to_dict() for doc in docs]
    
    if data_list:
        df_master = pd.DataFrame(data_list)
        # Drop the metadata timestamp from viewing layout, convert string date to sorting date
        df_master['date_parsed'] = pd.to_datetime(df_master['date'])
        
        today_start = pd.Timestamp(datetime.now().date())
        one_week_ago = today_start - pd.Timedelta(days=7)
        one_month_ago = today_start - pd.Timedelta(days=30)
        
        df_today = df_master[df_master['date_parsed'] >= today_start]
        df_weekly = df_master[df_master['date_parsed'] >= one_week_ago]
        df_monthly = df_master[df_master['date_parsed'] >= one_month_ago]
        
        # Display Workspace
        tab_today, tab_weekly, tab_monthly, tab_master = st.tabs([
            "📅 Today's Live Records", "🗓️ Weekly Archive", "📆 Monthly Archive", "🗄️ Master Cloud Backup"
        ])
        
        columns_to_show = ['receipt_no', 'date', 'patient_name', 'procedure', 'appt_fee', 'procedure_fee', 'actual_amount', 'paid_amount', 'refund', 'balance']
        
        with tab_today:
            if not df_today.empty:
                m1, m2, m3 = st.columns(3)
                m1.metric("Today's Total Billings", f"Rs. {df_today['actual_amount'].sum():,.0f}")
                m2.metric("Today's Total Collected", f"Rs. {df_today['paid_amount'].sum():,.0f}")
                m3.metric("Today's Pending Balances", f"Rs. {df_today['balance'].sum():,.0f}")
                
                st.dataframe(df_today[columns_to_show], use_container_width=True)
            else:
                st.warning("No patients entered today yet.")
                
        with tab_weekly:
            if not df_weekly.empty:
                st.metric("Total 7-Day Revenue", f"Rs. {df_weekly['actual_amount'].sum():,.0f}")
                st.dataframe(df_weekly[columns_to_show], use_container_width=True)
                
        with tab_monthly:
            if not df_monthly.empty:
                st.metric("Total 30-Day Revenue", f"Rs. {df_monthly['actual_amount'].sum():,.0f}")
                st.dataframe(df_monthly[columns_to_show], use_container_width=True)
                
        with tab_master:
            st.dataframe(df_master[columns_to_show], use_container_width=True)
            
            csv = df_master[columns_to_show].to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Complete Data Backup",
                data=csv,
                file_name=f"Firebase_Clinic_Backup_{receipt_date_suffix}.csv",
                mime='text/csv',
            )
    else:
        st.info("Connected securely to Firebase Cloud. Data dashboards will populate instantly as your first patient is saved.")
