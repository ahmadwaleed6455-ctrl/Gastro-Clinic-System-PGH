import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from google.oauth2 import service_account
from google.cloud import firestore

# Set page config
st.set_page_config(page_title="Gastro Dr. Naveed Anwar - Clinic Portal", layout="wide")

# ----------------------------------------------------
# 🔐 FIREBASE CONNECTION
# ----------------------------------------------------
@st.cache_resource
def get_firestore_client():
    key_dict = dict(st.secrets["textkey"])
    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
    creds = service_account.Credentials.from_service_account_info(key_dict)
    return firestore.Client(credentials=creds, project=key_dict["project_id"])

db = get_firestore_client()
log_ref = db.collection("patient_log")
settings_ref = db.collection("clinic_settings")

# ----------------------------------------------------
# ⚙️ DYNAMIC PRICING ENGINE (FETCH FROM FIREBASE)
# ----------------------------------------------------
def get_clinic_fees():
    # Default prices if database is empty
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

# ----------------------------------------------------
# 🕒 TIME & AUTO-RECEIPT GENERATOR
# ----------------------------------------------------
current_date_str = datetime.now().strftime("%Y-%m-%d")
display_date_form = datetime.now().strftime("%d-%m-%Y")
receipt_date_suffix = datetime.now().strftime("%d%m%Y")

def generate_receipt_number():
    docs = log_ref.where("date", "==", current_date_str).stream()
    count = sum(1 for _ in docs)
    return f"GNA{receipt_date_suffix}{count + 1}"

auto_receipt_no = generate_receipt_number()

# ----------------------------------------------------
# 🧭 MULTI-PAGE NAVIGATION BAR
# ----------------------------------------------------
page = st.sidebar.radio("Navigate System Pages", ["🏥 Dashboard & Form", "🔍 Date-Range Financial Auditor", "⚙️ Procedure Price Settings"])

# ----------------------------------------------------
# PAGE 1: MAIN DASHBOARD & ENTRY FORM
# ----------------------------------------------------
if page == "🏥 Dashboard & Form":
    st.title("🏥 Gastro Dr. Naveed Anwar Clinic Management System")
    st.markdown("---")
    
    col_form, col_display = st.columns(2)
    
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
                    log_ref.document(auto_receipt_no).set(patient_data)
                    st.success(f"Saved successfully! Receipt: {auto_receipt_no}")
                    st.rerun()

    with col_display:
        st.header("📊 Live Worksheet (New entries add to the BOTTOM)")
        
        # Pull records sorted old-to-new (Ascending) so new submissions append at the bottom
        docs = log_ref.order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
        data_list = [doc.to_dict() for doc in docs]
        
        if data_list:
            df_master = pd.DataFrame(data_list)
            df_master['date_parsed'] = pd.to_datetime(df_master['date'])
            today_start = pd.Timestamp(datetime.now().date())
            df_today = df_master[df_master['date_parsed'] >= today_start]
            
            tab_today, tab_receipt = st.tabs(["📅 Today's Live Records", "🧾 Patient Receipt Generator Viewer"])
            
            with tab_today:
                if not df_today.empty:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Today's Total Billings", f"Rs. {df_today['actual_amount'].sum():,.0f}")
                    m2.metric("Today's Total Collected", f"Rs. {df_today['paid_amount'].sum():,.0f}")
                    m3.metric("Today's Pending Balances", f"Rs. {df_today['balance'].sum():,.0f}")
                    
                    columns_to_show = ['receipt_no', 'patient_name', 'procedure', 'actual_amount', 'paid_amount', 'refund', 'balance']
                    st.dataframe(df_today[columns_to_show], use_container_width=True, hide_index=True)
                    
                    # Print Day Summary Sheet Section
                    st.markdown("---")
                    st.subheader("🖨️ End-of-Day Print Summary")
                    summary_text = f"""
                    ========================================
                    GASTRO DR. NAVEED ANWAR CLINIC SUMMARY
                    Date: {display_date_form}
                    ========================================
                    Total Patients Seen: {len(df_today)}
                    Total Appointment Revenue: Rs. {df_today['appt_fee'].sum():,.0f}
                    Total Procedure Revenue: Rs. {df_today['procedure_fee'].sum():,.0f}
                    ----------------------------------------
                    GRAND TOTAL BILLINGS: Rs. {df_today['actual_amount'].sum():,.0f}
                    TOTAL CASH COLLECTED: Rs. {df_today['paid_amount'].sum():,.0f}
                    TOTAL REFUNDS PAID:   Rs. {df_today['refund'].sum():,.0f}
                    TOTAL NET OUTSTANDING:Rs. {df_today['balance'].sum():,.0f}
                    ========================================
                    """
                    st.text_area("Copy/Send to Printer", value=summary_text, height=220)
                else:
                    st.warning("No patients entered today yet.")

            with tab_receipt:
                st.subheader("Select a Patient to view/print their individual official receipt:")
                patient_options = df_master.sort_values(by="timestamp", ascending=False)
                patient_select = st.selectbox(
                    "Choose Patient Folder", 
                    options=patient_options['receipt_no'].tolist(),
                    format_func=lambda x: f"{x} - {patient_options[patient_options['receipt_no']==x]['patient_name'].values}"
                )
                
                if patient_select:
                    # Isolate the exact matching row as a dictionary to avoid Pandas indexing bugs
                    matching_rows = df_master[df_master['receipt_no'] == patient_select]
                    
                    if not matching_rows.empty:
                        # Convert the single row directly into a clean Python dictionary
                        p_info = matching_rows.iloc[0].to_dict()
                        
                        st.markdown(f"""
                        <div style="padding:20px; border:2px solid #008080; border-radius:10px; background-color:#f9f9f9; font-family:monospace;">
                            <h2 style="text-align:center; color:#008080; margin-bottom:0;">DR. NAVEED ANWAR</h2>
                            <p style="text-align:center; margin-top:0; font-size:12px;">Gastroenterology & Hepatology Specialist Clinic</p>
                            <hr style="border-top:1px dashed #008080;">
                            <p><b>Receipt No:</b> {p_info['receipt_no']} <span style="float:right;"><b>Date:</b> {p_info['date']}</span></p>
                            <p><b>Patient Name:</b> {p_info['patient_name']}</p>
                            <p><b>Procedure Performed:</b> {p_info['procedure']}</p>
                            <hr style="border-top:1px dashed #ced4da;">
                            <p>Appointment Charges: <span style="float:right;">Rs. {float(p_info['appt_fee']):,.0f}</span></p>
                            <p>Procedure Charges: <span style="float:right;">Rs. {float(p_info['procedure_fee']):,.0f}</span></p>
                            <h4 style="margin-bottom:5px;">Actual Total Amount: <span style="float:right;">Rs. {float(p_info['actual_amount']):,.0f}</span></h4>
                            <p style="color:green; margin-top:0; margin-bottom:5px;">Paid Amount: <span style="float:right;">Rs. {float(p_info['paid_amount']):,.0f}</span></p>
                            <p style="color:red; margin-top:0; margin-bottom:5px;"><b>Refund Disbursed:</b> <span style="float:right;">Rs. {float(p_info['refund']):,.0f}</span></p>
                            <hr style="border-top: 2px solid #008080;">
                            <h3 style="color:#008080; margin-top:0;">Net Outstanding Balance: <span style="float:right;">Rs. {float(p_info['balance']):,.0f}</span></h3>
                        </div>
                        """, unsafe_allow_html=True)

           
# ----------------------------------------------------
# PAGE 2: DATE-RANGE AUDITOR ARCHIVE
# ----------------------------------------------------
elif page == "🔍 Date-Range Financial Auditor":
    st.title("🔍 Advanced Historical Audit & Custom Date Filters")
    st.markdown("---")
    
    docs = log_ref.stream()
    data_list = [doc.to_dict() for doc in docs]
    
    if data_list:
        df_audit = pd.DataFrame(data_list)
        df_audit['date_parsed'] = pd.to_datetime(df_audit['date']).dt.date
        
        c1, c2 = st.columns(2)
        start_date = c1.date_input("From Date", datetime.now().date() - timedelta(days=7))
        end_date = c2.date_input("To Date", datetime.now().date())
        
        if start_date <= end_date:
            filtered_df = df_audit[(df_audit['date_parsed'] >= start_date) & (df_audit['date_parsed'] <= end_date)]
            
            if not filtered_df.empty:
                st.subheader(f"📊 Aggregated Summaries from {start_date.strftime('%d-%m-%Y')} to {end_date.strftime('%d-%m-%Y')}")
                
                a1, a2, a3, a4 = st.columns(4)
                a1.metric("Total Appointment Fees", f"Rs. {filtered_df['appt_fee'].sum():,.0f}")
                a2.metric("Total Surgery/Proc Billings", f"Rs. {filtered_df['procedure_fee'].sum():,.0f}")
                a3.metric("Grand Cash Collected", f"Rs. {filtered_df['paid_amount'].sum():,.0f}")
                a4.metric("Total Patients Processed", f"{len(filtered_df)} Patients")
                
                # Procedure Metrics breakdown
                st.markdown("---")
                st.subheader("📋 Count & Revenue Breakdown per Surgery/Procedure Type")
                
                proc_breakdown = filtered_df.groupby('procedure').agg(
                    Total_Count=('patient_name', 'count'),
                    Total_Revenue=('procedure_fee', 'sum')
                ).reset_index()
                
                st.dataframe(proc_breakdown, use_container_width=True, hide_index=True)
                
                st.markdown("---")
                st.subheader("🗄️ Detailed Matching Patient Sub-List")
                st.dataframe(filtered_df.drop(columns=['timestamp', 'date_parsed']), use_container_width=True, hide_index=True)
            else:
                st.warning("No clinic documents match the selected date constraints.")
        else:
            st.error("Error: 'From Date' must be earlier than or equal to 'To Date'.")
    else:
        st.info("Cloud Archive database is empty.")

# ----------------------------------------------------
# PAGE 3: PRICING SETTINGS MANAGER
# ----------------------------------------------------
elif page == "⚙️ Procedure Price Settings":
    st.title("⚙️ Clinic Control Panel & Pricing Administration")
    st.markdown("---")
    st.subheader("Modify procedure fees globally below. Changes update the Patient Entry Form instantly.")
    
    with st.form("settings_form"):
        new_appt = st.number_input("Universal Consultation/Appointment Fee (Rs.)", min_value=0.0, value=float(APPT_FEE), step=500.0)
        
        updated_fees = {"appt_fee": new_appt}
        for proc, current_fee in PROCEDURE_FEES.items():
            if proc != "None (Consultation Only)":
                updated_fees[proc] = st.number_input(f"{proc} Fee Cost (Rs.)", min_value=0.0, value=float(current_fee), step=500.0)
            else:
                updated_fees[proc] = 0.0
                
        save_settings = st.form_submit_button("Update Rates Globally")
        
        if save_settings:
            settings_ref.document("pricing").set(updated_fees)
            st.success("Clinic pricing configurations synchronized successfully!")
            st.rerun()
